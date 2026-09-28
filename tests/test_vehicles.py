from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from evrange.constants import EPA_AIR_DENSITY, WLTP_AIR_DENSITY, rotating_mass_kg
from evrange.datafiles import read_json
from evrange.vehicles import RoadLoad, load_vehicles

IDS = ["tesla-model3-rwd", "volvo-ex30-sm-er", "polestar-2-lr-sm", "vw-id4-pro"]

Edit = Callable[[Path, Callable[[dict[str, Any]], None]], None]


def test_the_four_cars_load() -> None:
    assert [v.id for v in load_vehicles()] == IDS


def test_si_road_load_matches_the_stored_conversion() -> None:
    """vehicles.json stores the SI coefficients rounded; the exact conversion must agree."""
    listed = {v["id"]: v["us_road_load"]["si"] for v in read_json("vehicles.json")["vehicles"]}
    for vehicle in load_vehicles():
        si = listed[vehicle.id]
        load = vehicle.epa.road_load
        assert load.f0 == pytest.approx(si["F0_N"], abs=1e-4)
        assert load.f1 == pytest.approx(si["F1_N_per_m_per_s"], abs=1e-5)
        assert load.f2 == pytest.approx(si["F2_N_per_m2_per_s2"], abs=1e-6)
        assert vehicle.epa.test_weight_kg == pytest.approx(
            si["equivalent_test_weight_kg"], abs=0.01
        )
        assert load.air_density == EPA_AIR_DENSITY


def test_charging_efficiency_matches_the_certificate_file() -> None:
    stated = {
        v["id"]: v["charging_efficiency"] for v in read_json("epa_certification.json")["vehicles"]
    }
    for vehicle in load_vehicles():
        assert round(vehicle.epa.charging_efficiency, 4) == stated[vehicle.id]


def test_other_configurations_are_loaded() -> None:
    counts = {v.id: len(v.epa_other) for v in load_vehicles()}
    assert counts == {IDS[0]: 0, IDS[1]: 1, IDS[2]: 1, IDS[3]: 1}
    ex30 = load_vehicles()[1]
    assert len(ex30.epa.constant_65_mph_wh_per_km) == 2


def test_road_load_scaling() -> None:
    load = RoadLoad(100.0, 2.0, 0.4, 1.2)
    denser = load.at_air_density(1.8)
    assert (denser.f0, denser.f1, denser.air_density) == (100.0, 2.0, 1.8)
    assert denser.f2 == pytest.approx(0.6)
    heavier = load.with_rolling_scaled(1.1)
    assert heavier.f0 == pytest.approx(110.0)
    assert heavier.f1 == pytest.approx(2.2)
    assert heavier.f2 == 0.4
    assert load.force([0.0, 10.0]).tolist() == [100.0, 160.0]
    with pytest.raises(ValueError, match="density"):
        load.at_air_density(0.0)
    with pytest.raises(ValueError, match="factor"):
        load.with_rolling_scaled(-1.0)


def test_drag_crossover() -> None:
    load = RoadLoad(120.0, 2.8, 0.27, 1.2)
    v = load.drag_crossover_ms()
    assert load.f2 * v * v == pytest.approx(load.f0 + load.f1 * v)
    assert v > 0
    # A negative linear term (the EX30 has one) still gives the positive root.
    negative = RoadLoad(147.7, -0.85, 0.45, 1.2)
    w = negative.drag_crossover_ms()
    assert negative.f2 * w * w == pytest.approx(negative.f0 + negative.f1 * w)
    for bad in (RoadLoad(0.0, 1.0, 0.3, 1.2), RoadLoad(100.0, 1.0, 0.0, 1.2)):
        with pytest.raises(ValueError, match="positive"):
            bad.drag_crossover_ms()


def test_setups() -> None:
    vehicle = load_vehicles()[0]
    epa = vehicle.epa_setup()
    assert epa.inertial_mass_kg == pytest.approx(
        vehicle.epa.test_weight_kg + rotating_mass_kg(vehicle.mass_in_running_order_kg)
    )
    assert vehicle.epa_setup(rotating_mass=False).inertial_mass_kg == vehicle.epa.test_weight_kg
    wltp = vehicle.wltp_setup()
    assert wltp.road_load.air_density == WLTP_AIR_DENSITY
    assert wltp.road_load.f0 == pytest.approx(vehicle.epa.road_load.f0)
    loaded = vehicle.wltp_setup(extra_mass_kg=193.2)
    factor = (vehicle.wltp_test_mass_kg + 193.2) / vehicle.wltp_test_mass_kg
    assert loaded.road_load.f0 == pytest.approx(vehicle.epa.road_load.f0 * factor)
    assert loaded.inertial_mass_kg == pytest.approx(wltp.inertial_mass_kg + 193.2)
    rescaled = vehicle.wltp_setup(rolling_to_test_mass=True)
    assert rescaled.road_load.f0 == pytest.approx(
        vehicle.epa.road_load.f0 * vehicle.wltp_test_mass_kg / vehicle.epa.test_weight_kg
    )
    with pytest.raises(ValueError, match="negative"):
        vehicle.wltp_setup(extra_mass_kg=-1.0)


def test_epa_test_cycles() -> None:
    test = load_vehicles()[0].epa
    assert test.dc_wh_per_km("udds") == test.udds_wh_per_km
    assert test.dc_wh_per_km("hwfet") == test.hwfet_wh_per_km
    with pytest.raises(KeyError, match="no EPA measurement"):
        test.dc_wh_per_km("wltc")
    assert replace(test, recharge_energy_wh=test.usable_energy_wh).charging_efficiency == 1.0


def test_mismatched_files_are_refused(data_copy: Path, edit_json: Edit) -> None:
    def change(content: dict[str, Any]) -> None:
        content["vehicles"][0]["test_vehicle"]["target_coefficients"]["A_lbf"] = 27.03

    edit_json(data_copy / "epa_certification.json", change)
    with pytest.raises(ValueError, match="different cars"):
        load_vehicles(data_copy)


def test_missing_certificate_is_refused(data_copy: Path, edit_json: Edit) -> None:
    edit_json(data_copy / "epa_certification.json", lambda c: c["vehicles"].pop())
    with pytest.raises(ValueError, match="no EPA certificate"):
        load_vehicles(data_copy)


def test_data_files_are_consistent_with_each_other() -> None:
    listed = read_json("vehicles.json")["vehicles"]
    certified = read_json("epa_certification.json")["vehicles"]
    assert [v["id"] for v in listed] == [v["id"] for v in certified]
    for entry in certified:
        assert json.dumps(entry["report"]["url"]).count("dis.epa.gov") == 1
