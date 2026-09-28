"""Everything together: the four calibrated cars and the scenarios they can be run on.

    study = load_study()
    wltc = study.on_cycle("tesla-model3-rwd", "wltc")
    wltc.mains_wh_per_km, study.range_km("tesla-model3-rwd", wltc)

A scenario is the car at its WLTP test mass on a drive cycle or at a steady speed, with
optional extra load and climate-control power. Range is the usable battery energy the EPA
measured for the car, divided by the modelled battery consumption.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean

from evrange.calibration import Calibration, calibrate
from evrange.constants import KMH_MS, WLTP_AIR_DENSITY
from evrange.cycles import DriveCycle, load_cycles
from evrange.datafiles import reference_items, watts
from evrange.model import EnergyUse, energy_use
from evrange.physics import steady_work, wheel_work
from evrange.vehicles import Vehicle, load_vehicles

AUXILIARY_ITEMS = ("other_power_72F_bev1", "other_power_72F_bev2")
MAX_EXTRA_MASS_KG = 1000.0
MAX_CLIMATE_W = 10_000.0


@dataclass(frozen=True)
class Conditions:
    """What a scenario changes relative to the car as tested."""

    extra_mass_kg: float = 0.0
    climate_w: float = 0.0
    air_density: float = WLTP_AIR_DENSITY

    def __post_init__(self) -> None:
        if not 0 <= self.extra_mass_kg <= MAX_EXTRA_MASS_KG:
            raise ValueError(f"extra mass must be between 0 and {MAX_EXTRA_MASS_KG:.0f} kg")
        if not 0 <= self.climate_w <= MAX_CLIMATE_W:
            raise ValueError(f"climate power must be between 0 and {MAX_CLIMATE_W:.0f} W")
        if not 0.5 <= self.air_density <= 2.0:
            raise ValueError("air density must be between 0.5 and 2.0 kg/m^3")


@dataclass(frozen=True)
class ClimateReference:
    """Climate-control power measured by Argonne on a stationary car (DOE program record)."""

    item: str
    ambient_f: float
    power_w: float

    @property
    def ambient_c(self) -> float:
        return (self.ambient_f - 32) * 5 / 9


@dataclass(frozen=True)
class Study:
    vehicles: tuple[Vehicle, ...]
    cycles: Mapping[str, DriveCycle]
    auxiliary_w: float
    auxiliary_bounds_w: tuple[float, float]
    calibrations: Mapping[str, Calibration]
    climate_references: tuple[ClimateReference, ...] = field(default_factory=tuple)

    def vehicle(self, vehicle_id: str) -> Vehicle:
        for vehicle in self.vehicles:
            if vehicle.id == vehicle_id:
                return vehicle
        raise KeyError(f"unknown vehicle {vehicle_id!r}")

    def on_cycle(
        self, vehicle_id: str, cycle_key: str, conditions: Conditions | None = None
    ) -> EnergyUse:
        """Energy use of a car on a drive cycle."""
        conditions = conditions or Conditions()
        if cycle_key not in self.cycles:
            raise KeyError(f"unknown cycle {cycle_key!r}")
        setup = self.vehicle(vehicle_id).wltp_setup(
            conditions.extra_mass_kg, conditions.air_density
        )
        work = wheel_work(self.cycles[cycle_key].speed_ms, setup.road_load, setup.inertial_mass_kg)
        return energy_use(work, self.calibrations[vehicle_id].powertrain(conditions.climate_w))

    def at_speed(
        self, vehicle_id: str, speed_kmh: float, conditions: Conditions | None = None
    ) -> EnergyUse:
        """Energy use of a car per kilometre at a steady speed."""
        conditions = conditions or Conditions()
        if not 0 < speed_kmh <= 250:
            raise ValueError("speed must be between 0 and 250 km/h")
        setup = self.vehicle(vehicle_id).wltp_setup(
            conditions.extra_mass_kg, conditions.air_density
        )
        work = steady_work(speed_kmh * KMH_MS, setup.road_load)
        return energy_use(work, self.calibrations[vehicle_id].powertrain(conditions.climate_w))

    def range_km(self, vehicle_id: str, energy: EnergyUse) -> float:
        """Range at this consumption, from the usable battery energy the EPA measured."""
        return energy.range_km(self.vehicle(vehicle_id).epa.usable_energy_wh)


def auxiliary_reference(path: Path | str | None = None) -> tuple[float, tuple[float, float]]:
    """Mean and bounds of the two measured auxiliary loads (DOE program record, Table 2)."""
    items = {i["item"]: i for i in reference_items("auxiliary_load", path)}
    values = [watts(items[name]["value"]) for name in AUXILIARY_ITEMS]
    return mean(values), (min(values), max(values))


def climate_references(path: Path | str | None = None) -> tuple[ClimateReference, ...]:
    return tuple(
        ClimateReference(i["item"], float(i["ambient_f"]), watts(i["value"]))
        for i in reference_items("climate_power", path)
        if "ambient_f" in i
    )


def load_study(path: Path | str | None = None, auxiliary_w: float | None = None) -> Study:
    """Load the data, calibrate every car and return the study."""
    vehicles = load_vehicles(path)
    cycles = load_cycles(path)
    central, bounds = auxiliary_reference(path)
    aux = central if auxiliary_w is None else auxiliary_w
    return Study(
        vehicles=vehicles,
        cycles=cycles,
        auxiliary_w=aux,
        auxiliary_bounds_w=bounds,
        calibrations={v.id: calibrate(v, cycles, aux) for v in vehicles},
        climate_references=climate_references(path),
    )
