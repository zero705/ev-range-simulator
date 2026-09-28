"""The four cars: official EU values, EPA road load and EPA certification energies.

Everything is read from data/vehicles.json (EU registrations and the EPA Test Car List) and
data/epa_certification.json (EPA certificate reports). The two files come from different
EPA publications about the same test vehicles; loading checks that they agree.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import ArrayLike, NDArray

from evrange.constants import (
    EPA_AIR_DENSITY,
    LB_KG,
    LBF_N,
    MILE_M,
    MPH_MS,
    WLTP_AIR_DENSITY,
    rotating_mass_kg,
)
from evrange.datafiles import read_json


@dataclass(frozen=True)
class RoadLoad:
    """Road-load force F = f0 + f1*v + f2*v^2 (v in m/s), for a stated air density."""

    f0: float
    f1: float
    f2: float
    air_density: float

    @classmethod
    def from_epa(cls, a_lbf: float, b_lbf_per_mph: float, c_lbf_per_mph2: float) -> RoadLoad:
        """Convert EPA target coefficients (lbf, lbf/mph, lbf/mph^2) with exact factors."""
        return cls(
            f0=a_lbf * LBF_N,
            f1=b_lbf_per_mph * LBF_N / MPH_MS,
            f2=c_lbf_per_mph2 * LBF_N / MPH_MS**2,
            air_density=EPA_AIR_DENSITY,
        )

    def force(self, speed_ms: ArrayLike) -> NDArray[np.float64]:
        v = np.asarray(speed_ms, dtype=np.float64)
        return np.asarray(self.f0 + self.f1 * v + self.f2 * v * v, dtype=np.float64)

    def at_air_density(self, density: float) -> RoadLoad:
        """The quadratic (aerodynamic) term scales with air density."""
        if density <= 0:
            raise ValueError("air density must be positive")
        return replace(self, f2=self.f2 * density / self.air_density, air_density=density)

    def with_rolling_scaled(self, factor: float) -> RoadLoad:
        """Rolling resistance is m*g*fRR and sits in the constant and linear terms."""
        if factor <= 0:
            raise ValueError("the rolling-resistance factor must be positive")
        return replace(self, f0=self.f0 * factor, f1=self.f1 * factor)

    def drag_crossover_ms(self) -> float:
        """Speed at which the quadratic (drag) term equals the constant and linear terms."""
        if self.f2 <= 0 or self.f0 <= 0:
            raise ValueError("needs a positive constant and a positive quadratic term")
        return (self.f1 + math.sqrt(self.f1**2 + 4 * self.f2 * self.f0)) / (2 * self.f2)


@dataclass(frozen=True)
class Spread:
    """An official EU value: the value most registrations carry, and the 5-95 % range."""

    mode: float
    p05: float
    p95: float


@dataclass(frozen=True)
class EpaTest:
    """One test vehicle configuration from an EPA certificate report."""

    label: str
    test_vehicle_id: str
    road_load: RoadLoad
    test_weight_kg: float
    udds_wh_per_km: float
    hwfet_wh_per_km: float
    usable_energy_wh: float
    recharge_energy_wh: float
    mains_voltage_v: float
    constant_65_mph_wh_per_km: tuple[float, ...]

    @property
    def charging_efficiency(self) -> float:
        """Usable battery energy over the energy taken from the mains to recharge it."""
        return self.usable_energy_wh / self.recharge_energy_wh

    def dc_wh_per_km(self, cycle: str) -> float:
        if cycle == "udds":
            return self.udds_wh_per_km
        if cycle == "hwfet":
            return self.hwfet_wh_per_km
        raise KeyError(f"no EPA measurement for cycle {cycle!r}")


@dataclass(frozen=True)
class Vehicle:
    id: str
    name: str
    mass_in_running_order_kg: float
    wltp_test_mass_kg: float
    eu_consumption_wh_per_km: Spread
    eu_range_km: Spread
    eu_registrations: int
    motor_power_kw: float
    epa: EpaTest
    epa_other: tuple[EpaTest, ...]
    report_url: str

    @property
    def rotating_mass_kg(self) -> float:
        return rotating_mass_kg(self.mass_in_running_order_kg)

    def epa_setup(self, test: EpaTest | None = None, *, rotating_mass: bool = True) -> Setup:
        """The car on the EPA dynamometer: EPA road load and test weight."""
        test = test or self.epa
        extra = self.rotating_mass_kg if rotating_mass else 0.0
        return Setup(test.road_load, test.test_weight_kg + extra)

    def wltp_setup(
        self,
        extra_mass_kg: float = 0.0,
        air_density: float = WLTP_AIR_DENSITY,
        *,
        rotating_mass: bool = True,
        rolling_to_test_mass: bool = False,
    ) -> Setup:
        """The car at its WLTP test mass (plus any extra load), EPA road load at the given air.

        rolling_to_test_mass rescales rolling resistance from the EPA test weight to the WLTP
        test mass; by default the measured coefficients are used as they are.
        """
        if extra_mass_kg < 0:
            raise ValueError("extra mass cannot be negative")
        mass = self.wltp_test_mass_kg + extra_mass_kg
        factor = mass / self.wltp_test_mass_kg
        if rolling_to_test_mass:
            factor *= self.wltp_test_mass_kg / self.epa.test_weight_kg
        road_load = self.epa.road_load.at_air_density(air_density).with_rolling_scaled(factor)
        return Setup(road_load, mass + (self.rotating_mass_kg if rotating_mass else 0.0))


@dataclass(frozen=True)
class Setup:
    """What a simulation needs from the car: road load and inertial mass."""

    road_load: RoadLoad
    inertial_mass_kg: float


def _spread(block: dict[str, Any]) -> Spread:
    return Spread(float(block["mode"]), float(block["p05"]), float(block["p95"]))


def _epa_test(entry: dict[str, Any]) -> EpaTest:
    vehicle = entry["test_vehicle"]
    target = vehicle["target_coefficients"]
    per_mile = entry["dc_wh_per_mi"]
    return EpaTest(
        label=str(entry["label"]),
        test_vehicle_id=f"{vehicle['test_vehicle_id']}/{vehicle['configuration']}",
        road_load=RoadLoad.from_epa(
            float(target["A_lbf"]), float(target["B_lbf_per_mph"]), float(target["C_lbf_per_mph2"])
        ),
        test_weight_kg=float(vehicle["equivalent_test_weight_lb"]) * LB_KG,
        udds_wh_per_km=float(per_mile["udds"]) * 1000 / MILE_M,
        hwfet_wh_per_km=float(per_mile["hwfet"]) * 1000 / MILE_M,
        usable_energy_wh=float(entry["usable_battery_energy_wh"]),
        recharge_energy_wh=float(entry["recharge"]["energy_kwh"]) * 1000,
        mains_voltage_v=float(entry["recharge"]["mains_voltage_v"]),
        constant_65_mph_wh_per_km=tuple(
            float(w) * 1000 / MILE_M for w in entry.get("constant_65_mph_dc_wh_per_mi", [])
        ),
    )


def load_vehicles(path: Path | str | None = None) -> tuple[Vehicle, ...]:
    """Load the four cars and check that the EU/EPA files and the EPA reports agree."""
    listed = read_json("vehicles.json", path)["vehicles"]
    certified = {v["id"]: v for v in read_json("epa_certification.json", path)["vehicles"]}
    vehicles = []
    for entry in listed:
        vid = entry["id"]
        if vid not in certified:
            raise ValueError(f"{vid}: no EPA certificate data")
        report = certified[vid]
        us = entry["us_road_load"]
        stated = report["test_vehicle"]
        if (
            stated["target_coefficients"] != us["target_coefficients"]
            or stated["equivalent_test_weight_lb"] != us["equivalent_test_weight_lb"]
            or stated["test_vehicle_id"] != us["test_vehicle_id"]
        ):
            raise ValueError(f"{vid}: EPA report and Test Car List describe different cars")
        eu = entry["eu_wltp"]
        vehicles.append(
            Vehicle(
                id=vid,
                name=str(entry["name"]),
                mass_in_running_order_kg=float(eu["mass_in_running_order_kg"]["mode"]),
                wltp_test_mass_kg=float(eu["wltp_test_mass_kg"]["mode"]),
                eu_consumption_wh_per_km=_spread(eu["energy_consumption_wh_per_km"]),
                eu_range_km=_spread(eu["electric_range_km"]),
                eu_registrations=int(eu["registrations"]),
                motor_power_kw=float(eu["motor_power_kw"]["mode"]),
                epa=_epa_test(report),
                epa_other=tuple(_epa_test(o) for o in report["other_configurations"]),
                report_url=str(report["report"]["url"]),
            )
        )
    return tuple(vehicles)
