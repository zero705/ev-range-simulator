"""Checks against data the calibration never saw.

1. EU WLTP: consumption from the mains and range, from the EU registration data. The model
   uses the WLTP test mass, the WLTC and the WLTP reference air; the road load is the EPA one,
   because the EU road loads are not published.
2. EPA configurations that differ physically from the calibrated one (other wheels, so other
   road-load coefficients), and the constant 65 mph phases of the Multi-Cycle Test.
3. How much each modelling choice moves the EU comparison (sensitivity).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from statistics import mean

from evrange.calibration import Calibration, calibrate
from evrange.constants import EPA_AIR_DENSITY, MPH_MS, WLTP_AIR_DENSITY
from evrange.model import energy_use
from evrange.physics import steady_work, wheel_work
from evrange.study import Study
from evrange.vehicles import EpaTest, Vehicle


@dataclass(frozen=True)
class Comparison:
    vehicle_id: str
    check: str
    unit: str
    model: float
    measured: float
    low: float | None = None
    high: float | None = None

    @property
    def error_pct(self) -> float:
        return (self.model - self.measured) / self.measured * 100

    @property
    def within_band(self) -> bool | None:
        """For EU values: is the model inside the 5-95 % range of the registrations?"""
        if self.low is None or self.high is None:
            return None
        return self.low <= self.model <= self.high


@dataclass(frozen=True)
class EuPrediction:
    mains_wh_per_km: float
    battery_wh_per_km: float
    range_km: float


def eu_prediction(
    study: Study,
    vehicle: Vehicle,
    calibration: Calibration | None = None,
    *,
    air_density: float = WLTP_AIR_DENSITY,
    rotating_mass: bool = True,
    rolling_to_test_mass: bool = False,
    charging_efficiency: float | None = None,
) -> EuPrediction:
    """The car on the WLTC at its WLTP test mass."""
    calibration = calibration or study.calibrations[vehicle.id]
    setup = vehicle.wltp_setup(
        air_density=air_density,
        rotating_mass=rotating_mass,
        rolling_to_test_mass=rolling_to_test_mass,
    )
    work = wheel_work(study.cycles["wltc"].speed_ms, setup.road_load, setup.inertial_mass_kg)
    use = energy_use(work, calibration.powertrain())
    efficiency = (
        calibration.charging_efficiency if charging_efficiency is None else charging_efficiency
    )
    return EuPrediction(
        mains_wh_per_km=use.battery_wh_per_km / efficiency,
        battery_wh_per_km=use.battery_wh_per_km,
        range_km=use.range_km(vehicle.epa.usable_energy_wh),
    )


def eu_comparisons(study: Study) -> list[Comparison]:
    rows = []
    for vehicle in study.vehicles:
        prediction = eu_prediction(study, vehicle)
        z, zr = vehicle.eu_consumption_wh_per_km, vehicle.eu_range_km
        rows.append(
            Comparison(
                vehicle.id,
                "EU WLTP consumption from the mains",
                "Wh/km",
                prediction.mains_wh_per_km,
                z.mode,
                z.p05,
                z.p95,
            )
        )
        rows.append(
            Comparison(
                vehicle.id,
                "EU WLTP range",
                "km",
                prediction.range_km,
                zr.mode,
                zr.p05,
                zr.p95,
            )
        )
    return rows


def _differs(test: EpaTest, base: EpaTest) -> bool:
    return test.road_load != base.road_load or test.test_weight_kg != base.test_weight_kg


def _steady_65(vehicle: Vehicle, test: EpaTest, calibration: Calibration) -> float:
    setup = vehicle.epa_setup(test)
    work = steady_work(65 * MPH_MS, setup.road_load)
    return energy_use(work, calibration.powertrain()).battery_wh_per_km


def epa_comparisons(study: Study) -> list[Comparison]:
    """EPA measurements not used by the calibration (battery-side, Wh/km)."""
    rows = []
    for vehicle in study.vehicles:
        calibration = study.calibrations[vehicle.id]
        for test in vehicle.epa_other:
            if not _differs(test, vehicle.epa):
                continue
            for key, name in (("udds", "UDDS"), ("hwfet", "highway")):
                setup = vehicle.epa_setup(test)
                work = wheel_work(
                    study.cycles[key].speed_ms, setup.road_load, setup.inertial_mass_kg
                )
                rows.append(
                    Comparison(
                        vehicle.id,
                        f"EPA {name}, {test.label}",
                        "Wh/km",
                        energy_use(work, calibration.powertrain()).battery_wh_per_km,
                        test.dc_wh_per_km(key),
                    )
                )
        for test in (vehicle.epa, *vehicle.epa_other):
            for phase, measured in zip(
                ("mid-test", "end-of-test"), test.constant_65_mph_wh_per_km, strict=False
            ):
                rows.append(
                    Comparison(
                        vehicle.id,
                        f"EPA 65 mph, {phase}, {test.label}",
                        "Wh/km",
                        _steady_65(vehicle, test, calibration),
                        measured,
                    )
                )
    return rows


def implied_eu_charging_efficiency(vehicle: Vehicle) -> float:
    """EPA usable battery energy over the mains energy implied by the EU values.

    UN GTR No. 15 defines a pure electric car's consumption as the energy recharged from the
    mains divided by its range, so consumption times range is the mains energy of a full
    recharge. Dividing the EPA-measured usable energy by it gives the charging efficiency the
    EU figures imply, if the EU and US cars store the same usable energy.
    """
    mains_wh = vehicle.eu_consumption_wh_per_km.mode * vehicle.eu_range_km.mode
    return vehicle.epa.usable_energy_wh / mains_wh


@dataclass(frozen=True)
class Sensitivity:
    name: str
    consumption_pp: dict[str, float]
    range_pp: dict[str, float]


def sensitivities(study: Study) -> list[Sensitivity]:
    """Change in the EU errors (percentage points) when one modelling choice is changed."""
    cycles = study.cycles
    shared_charging = mean(v.epa.charging_efficiency for v in study.vehicles)

    def recalibrated(aux: float, rotating: bool = True) -> Callable[[Vehicle], EuPrediction]:
        return lambda v: eu_prediction(
            study, v, calibrate(v, cycles, aux, rotating_mass=rotating), rotating_mass=rotating
        )

    low, high = study.auxiliary_bounds_w
    variants: list[tuple[str, Callable[[Vehicle], EuPrediction]]] = [
        (f"Auxiliary load {low:.0f} W instead of {study.auxiliary_w:.0f} W", recalibrated(low)),
        (f"Auxiliary load {high:.0f} W instead of {study.auxiliary_w:.0f} W", recalibrated(high)),
        ("No rotating-mass allowance", recalibrated(study.auxiliary_w, rotating=False)),
        (
            "No air-density correction (EPA air for the WLTC)",
            lambda v: eu_prediction(study, v, air_density=EPA_AIR_DENSITY),
        ),
        (
            "Rolling resistance rescaled to the WLTP test mass",
            lambda v: eu_prediction(study, v, rolling_to_test_mass=True),
        ),
        (
            f"One charging efficiency for all cars ({shared_charging:.4f})",
            lambda v: eu_prediction(study, v, charging_efficiency=shared_charging),
        ),
    ]
    base = {v.id: eu_prediction(study, v) for v in study.vehicles}
    rows = []
    for name, predict in variants:
        consumption, distance = {}, {}
        for v in study.vehicles:
            p = predict(v)
            z, zr = v.eu_consumption_wh_per_km.mode, v.eu_range_km.mode
            consumption[v.id] = (p.mains_wh_per_km - base[v.id].mains_wh_per_km) / z * 100
            distance[v.id] = (p.range_km - base[v.id].range_km) / zr * 100
        rows.append(Sensitivity(name, consumption, distance))
    return rows
