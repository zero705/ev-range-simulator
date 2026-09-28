"""Identify each car's drivetrain efficiency and regeneration from its EPA certification test.

The EPA report gives the DC energy the car took from its battery per kilometre on the UDDS
and on the highway cycle, on a dynamometer set to the same road load and test weight the
model uses. For each cycle the model reads

    DC = W+ / eta_drive  -  k_regen * W-  +  P_aux * t          (all per km)

which is linear in 1/eta_drive and k_regen. Two cycles give two equations and the two
unknowns follow exactly. No EU value enters, so the EU official figures remain an
independent check.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from evrange.constants import J_PER_WH
from evrange.cycles import DriveCycle
from evrange.model import Powertrain
from evrange.physics import wheel_work
from evrange.vehicles import EpaTest, Vehicle

CALIBRATION_CYCLES = ("udds", "hwfet")


class CalibrationError(ValueError):
    """The measurements cannot be reproduced with physically possible parameters."""


@dataclass(frozen=True)
class Calibration:
    vehicle_id: str
    drive_efficiency: float
    regen_coefficient: float
    auxiliary_w: float
    charging_efficiency: float

    def powertrain(self, extra_auxiliary_w: float = 0.0) -> Powertrain:
        """The car's powertrain, with any additional consumption such as climate control."""
        if extra_auxiliary_w < 0:
            raise ValueError("additional auxiliary power cannot be negative")
        return Powertrain(
            drive_efficiency=self.drive_efficiency,
            regen_coefficient=self.regen_coefficient,
            auxiliary_w=self.auxiliary_w + extra_auxiliary_w,
            charging_efficiency=self.charging_efficiency,
        )


@dataclass(frozen=True)
class CycleTerms:
    """Per-kilometre terms of the calibration equation for one cycle."""

    positive_wh_per_km: float
    negative_wh_per_km: float
    auxiliary_wh_per_km: float
    measured_wh_per_km: float


def cycle_terms(
    vehicle: Vehicle,
    cycle: DriveCycle,
    auxiliary_w: float,
    test: EpaTest | None = None,
    *,
    rotating_mass: bool = True,
) -> CycleTerms:
    test = test or vehicle.epa
    setup = vehicle.epa_setup(test, rotating_mass=rotating_mass)
    work = wheel_work(cycle.speed_ms, setup.road_load, setup.inertial_mass_kg)
    km = work.distance_m / 1000
    return CycleTerms(
        positive_wh_per_km=work.positive_j / J_PER_WH / km,
        negative_wh_per_km=work.negative_j / J_PER_WH / km,
        auxiliary_wh_per_km=auxiliary_w * work.duration_s / J_PER_WH / km,
        measured_wh_per_km=test.dc_wh_per_km(cycle.key),
    )


def calibrate(
    vehicle: Vehicle,
    cycles: Mapping[str, DriveCycle],
    auxiliary_w: float,
    *,
    rotating_mass: bool = True,
) -> Calibration:
    """Solve the two EPA equations of one car for eta_drive and k_regen."""
    if auxiliary_w < 0:
        raise ValueError("auxiliary power cannot be negative")
    city, highway = (
        cycle_terms(vehicle, cycles[key], auxiliary_w, rotating_mass=rotating_mass)
        for key in CALIBRATION_CYCLES
    )
    # [ W+_c  -W-_c ] [ 1/eta ]   [ DC_c - aux_c ]
    # [ W+_h  -W-_h ] [ k     ] = [ DC_h - aux_h ]
    rhs_c = city.measured_wh_per_km - city.auxiliary_wh_per_km
    rhs_h = highway.measured_wh_per_km - highway.auxiliary_wh_per_km
    det = -city.positive_wh_per_km * highway.negative_wh_per_km + (
        highway.positive_wh_per_km * city.negative_wh_per_km
    )
    scale = city.positive_wh_per_km * highway.negative_wh_per_km
    if abs(det) < 1e-9 * scale:
        raise CalibrationError(f"{vehicle.id}: the two cycles do not separate the unknowns")
    inverse_eta = (-rhs_c * highway.negative_wh_per_km + rhs_h * city.negative_wh_per_km) / det
    regen = (city.positive_wh_per_km * rhs_h - highway.positive_wh_per_km * rhs_c) / det
    if inverse_eta < 1:
        raise CalibrationError(f"{vehicle.id}: the measurements imply an efficiency above 100 %")
    if not 0 <= regen <= 1:
        raise CalibrationError(
            f"{vehicle.id}: the measurements imply a regeneration coefficient of {regen:.3f}"
        )
    return Calibration(
        vehicle_id=vehicle.id,
        drive_efficiency=1 / inverse_eta,
        regen_coefficient=regen,
        auxiliary_w=auxiliary_w,
        charging_efficiency=vehicle.epa.charging_efficiency,
    )
