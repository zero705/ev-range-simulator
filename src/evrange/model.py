"""From work at the wheels to energy from the battery and from the mains.

    battery = W+ / eta_drive  -  k_regen * W-  +  P_aux * t
    mains   = battery / eta_charge

W+ and W- are the work the wheels deliver and absorb (see physics.py). eta_drive is the
battery-to-wheel efficiency while driving, k_regen the share of the braking work that returns
to the battery, P_aux the car's own consumption, and eta_charge the share of mains energy that
the battery gives back. How each is obtained is described in docs/method.md.
"""

from __future__ import annotations

from dataclasses import dataclass

from evrange.constants import J_PER_WH
from evrange.physics import WheelWork


@dataclass(frozen=True)
class Powertrain:
    drive_efficiency: float
    regen_coefficient: float
    auxiliary_w: float
    charging_efficiency: float

    def __post_init__(self) -> None:
        if not 0 < self.drive_efficiency <= 1:
            raise ValueError("drive efficiency must be in (0, 1]")
        if not 0 <= self.regen_coefficient <= 1:
            raise ValueError("regeneration coefficient must be in [0, 1]")
        if self.auxiliary_w < 0:
            raise ValueError("auxiliary power cannot be negative")
        if not 0 < self.charging_efficiency <= 1:
            raise ValueError("charging efficiency must be in (0, 1]")


# The six places the energy from the mains ends up, in the order the charts show them.
BREAKDOWN = {
    "aero": "Air drag",
    "rolling": "Rolling resistance",
    "braking": "Braking not recovered",
    "drive": "Drivetrain losses",
    "auxiliary": "Auxiliaries and climate",
    "charging": "Charging losses",
}


@dataclass(frozen=True)
class EnergyUse:
    """Energy use over a trace, in watt-hours."""

    wheel: WheelWork
    powertrain: Powertrain
    battery_wh: float
    drive_loss_wh: float
    regenerated_wh: float
    braking_loss_wh: float
    auxiliary_wh: float
    mains_wh: float
    charging_loss_wh: float

    @property
    def distance_km(self) -> float:
        return self.wheel.distance_m / 1000

    @property
    def battery_wh_per_km(self) -> float:
        return self.battery_wh / self.distance_km

    @property
    def mains_wh_per_km(self) -> float:
        return self.mains_wh / self.distance_km

    def range_km(self, usable_energy_wh: float) -> float:
        """Distance the usable battery energy lasts at this consumption."""
        if usable_energy_wh <= 0:
            raise ValueError("usable energy must be positive")
        if self.battery_wh <= 0:
            raise ValueError("this trace takes no energy from the battery")
        return usable_energy_wh / self.battery_wh_per_km

    def breakdown_wh(self) -> dict[str, float]:
        """Where the energy from the mains goes.

        The parts add up to mains_wh when the net work at the wheels is the road-load work:
        over a trace that starts and ends at rest, and at a steady speed.
        """
        return {
            "aero": self.wheel.aero_j / J_PER_WH,
            "rolling": self.wheel.rolling_j / J_PER_WH,
            "braking": self.braking_loss_wh,
            "drive": self.drive_loss_wh,
            "auxiliary": self.auxiliary_wh,
            "charging": self.charging_loss_wh,
        }


def energy_use(wheel: WheelWork, powertrain: Powertrain) -> EnergyUse:
    """Apply the powertrain to the work at the wheels."""
    positive = wheel.positive_j / J_PER_WH
    negative = wheel.negative_j / J_PER_WH
    traction = positive / powertrain.drive_efficiency
    regenerated = powertrain.regen_coefficient * negative
    auxiliary = powertrain.auxiliary_w * wheel.duration_s / J_PER_WH
    battery = traction - regenerated + auxiliary
    mains = battery / powertrain.charging_efficiency
    return EnergyUse(
        wheel=wheel,
        powertrain=powertrain,
        battery_wh=battery,
        drive_loss_wh=traction - positive,
        regenerated_wh=regenerated,
        braking_loss_wh=negative - regenerated,
        auxiliary_wh=auxiliary,
        mains_wh=mains,
        charging_loss_wh=mains - battery,
    )
