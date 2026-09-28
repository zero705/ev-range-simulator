"""Scenarios behave as physics says they must."""

from __future__ import annotations

from pathlib import Path

import pytest

from evrange import CYCLE_SPECS, Conditions, Study, load_study
from evrange.constants import EPA_AIR_DENSITY, KMH_MS
from evrange.physics import steady_work
from evrange.study import auxiliary_reference, climate_references


@pytest.mark.parametrize("drive", [*CYCLE_SPECS, 120.0])
def test_breakdown_adds_up_on_every_drive_the_app_offers(study: Study, drive: str | float) -> None:
    # Every cycle starts and ends at rest, so the net work at the wheels is the road-load work
    # and the six parts of the breakdown account for all the energy from the mains.
    conditions = Conditions(extra_mass_kg=150, climate_w=1500)
    for vehicle in study.vehicles:
        use = (
            study.on_cycle(vehicle.id, drive, conditions)
            if isinstance(drive, str)
            else study.at_speed(vehicle.id, drive, conditions)
        )
        assert sum(use.breakdown_wh().values()) == pytest.approx(use.mains_wh, rel=1e-9)


def test_auxiliary_load_is_the_mean_of_the_two_measurements() -> None:
    central, bounds = auxiliary_reference()
    assert bounds == (144.0, 226.0)
    assert central == 185.0


def test_explicit_auxiliary_load(data_copy: Path) -> None:
    study = load_study(data_copy, auxiliary_w=144.0)
    assert study.auxiliary_w == 144.0
    assert all(c.auxiliary_w == 144.0 for c in study.calibrations.values())


def test_climate_references_are_the_six_argonne_measurements() -> None:
    references = climate_references()
    assert sorted(r.power_w for r in references) == [755, 956, 1848, 2898, 3376, 3732]
    coldest = min(references, key=lambda r: r.ambient_f)
    assert coldest.ambient_c == pytest.approx(-17.78, abs=0.01)


def test_unknown_names(study: Study) -> None:
    with pytest.raises(KeyError, match="vehicle"):
        study.vehicle("tesla-model-s")
    with pytest.raises(KeyError, match="cycle"):
        study.on_cycle("tesla-model3-rwd", "nedc")


@pytest.mark.parametrize(
    "conditions",
    [
        {"extra_mass_kg": -1.0},
        {"extra_mass_kg": 1001.0},
        {"climate_w": -5.0},
        {"climate_w": 10_001.0},
        {"air_density": 0.2},
    ],
)
def test_conditions_are_bounded(conditions: dict[str, float]) -> None:
    with pytest.raises(ValueError, match="between"):
        Conditions(**conditions)


def test_extra_load_costs_energy_and_range(study: Study) -> None:
    for vehicle in study.vehicles:
        empty = study.on_cycle(vehicle.id, "wltc")
        loaded = study.on_cycle(vehicle.id, "wltc", Conditions(extra_mass_kg=300.0))
        assert loaded.battery_wh_per_km > empty.battery_wh_per_km
        assert study.range_km(vehicle.id, loaded) < study.range_km(vehicle.id, empty)


def test_climate_power_matters_most_in_slow_traffic(study: Study) -> None:
    vehicle = "vw-id4-pro"
    heated = Conditions(climate_w=2000.0)
    added = {}
    for key in ("wltc-low", "hwfet"):
        base = study.on_cycle(vehicle, key)
        warm = study.on_cycle(vehicle, key, heated)
        added[key] = warm.battery_wh_per_km - base.battery_wh_per_km
        per_km = 2000.0 * study.cycles[key].duration_s / 3600 / base.distance_km
        assert added[key] == pytest.approx(per_km)
    assert added["wltc-low"] > 3 * added["hwfet"]


def test_denser_air_costs_energy(study: Study) -> None:
    thin = study.on_cycle("polestar-2-lr-sm", "hwfet", Conditions(air_density=EPA_AIR_DENSITY))
    dense = study.on_cycle("polestar-2-lr-sm", "hwfet", Conditions(air_density=1.3))
    assert dense.battery_wh_per_km > thin.battery_wh_per_km


def test_steady_speed(study: Study) -> None:
    vehicle = study.vehicle("tesla-model3-rwd")
    calibration = study.calibrations[vehicle.id]
    use = study.at_speed(vehicle.id, 100.0)
    setup = vehicle.wltp_setup()
    wheel = steady_work(100.0 * KMH_MS, setup.road_load)
    expected = (
        wheel.positive_j / 3600 / calibration.drive_efficiency
        + calibration.auxiliary_w * wheel.duration_s / 3600
    )
    assert use.battery_wh_per_km == pytest.approx(expected)
    slow, fast = study.at_speed(vehicle.id, 60.0), study.at_speed(vehicle.id, 130.0)
    assert fast.battery_wh_per_km > use.battery_wh_per_km > slow.battery_wh_per_km
    for speed in (0.0, 251.0):
        with pytest.raises(ValueError, match="speed"):
            study.at_speed(vehicle.id, speed)


def test_range_uses_the_epa_usable_energy(study: Study) -> None:
    vehicle = study.vehicle("volvo-ex30-sm-er")
    use = study.on_cycle(vehicle.id, "wltc")
    assert study.range_km(vehicle.id, use) == pytest.approx(
        vehicle.epa.usable_energy_wh / use.battery_wh_per_km
    )
