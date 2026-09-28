"""The Streamlit app runs, reacts to its controls and shows exactly the model's numbers."""

from __future__ import annotations

import importlib.util
from itertools import pairwise
from pathlib import Path
from types import ModuleType

import pytest
from streamlit.testing.v1 import AppTest

from evrange import CYCLE_SPECS, Conditions, Study
from evrange.report import short_name

APP = str(Path(__file__).resolve().parent.parent / "streamlit_app.py")


@pytest.fixture(scope="module")
def helpers() -> ModuleType:
    """The app's module, imported without running the app (it runs only as __main__)."""
    spec = importlib.util.spec_from_file_location("streamlit_app", APP)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0.0, 1.0),
        (-3.0, 1.0),
        (1.0, 1.0),
        (1.1, 1.2),
        (7.0, 8.0),
        (9.0, 10.0),
        (23.0, 25.0),
        (101.0, 120.0),
        (0.013, 0.015),
    ],
)
def test_nice_ceiling(helpers: ModuleType, value: float, expected: float) -> None:
    assert helpers.nice_ceiling(value) == pytest.approx(expected)


def test_links_are_made_for_https_addresses_only(helpers: ModuleType, study: Study) -> None:
    for vehicle in study.vehicles:  # the real links: the EPA certificate reports
        assert vehicle.report_url.startswith("https://dis.epa.gov/")
        assert helpers.https_link("report", vehicle.report_url) == f"[report]({vehicle.report_url})"
    for url in (
        "javascript:alert(1)",
        "http://dis.epa.gov/x",
        "data:text/html,x",
        "https://a b",
        "https://dis.epa.gov/x)[y](javascript:alert(1)",
        "https://",
    ):
        assert helpers.https_link("report", url) == "report", url


def test_spread_labels_keep_order_and_distance(helpers: ModuleType) -> None:
    assert helpers.spread_labels({}, 1.0) == {}
    assert helpers.spread_labels({"a": 3.0}, 1.0) == {"a": 3.0}
    values = {"b": 10.2, "a": 10.0, "c": 10.1, "d": 20.0}
    placed = helpers.spread_labels(values, 1.0)
    order = sorted(values, key=values.__getitem__)
    assert sorted(placed, key=placed.__getitem__) == order  # the lines' order is kept
    gaps = [placed[hi] - placed[lo] for lo, hi in pairwise(order)]
    assert min(gaps) >= 1.0 - 1e-12  # no two labels closer than the gap
    shift = sum(placed[k] - values[k] for k in values) / len(values)
    assert shift == pytest.approx(0.0, abs=1e-12)  # centred on the lines


@pytest.fixture
def app() -> AppTest:
    at = AppTest.from_file(APP, default_timeout=120)
    at.run()
    assert not at.exception
    return at


def _ranges(app: AppTest) -> dict[str, str]:
    return {m.label: m.value for m in app.metric}


def test_default_view_shows_the_modelled_wltc_ranges(app: AppTest, study: Study) -> None:
    shown = _ranges(app)
    assert len(shown) == 4
    for vehicle in study.vehicles:
        use = study.on_cycle(vehicle.id, "wltc")
        assert shown[short_name(vehicle.id)] == f"{study.range_km(vehicle.id, use):.0f} km"
    captions = " ".join(c.value for c in app.caption)
    for vehicle in study.vehicles:
        assert f"EU official: {vehicle.eu_range_km.mode:.0f} km" in captions


def test_steady_speed_with_load_and_climate(app: AppTest, study: Study) -> None:
    app.selectbox(key="drive").select("steady").run()
    app.slider(key="speed").set_value(130).run()
    app.slider(key="load").set_value(150).run()
    app.slider(key="climate").set_value(2000).run()
    assert not app.exception
    conditions = Conditions(extra_mass_kg=150, climate_w=2000)
    shown = _ranges(app)
    for vehicle in study.vehicles:
        use = study.at_speed(vehicle.id, 130, conditions)
        assert shown[short_name(vehicle.id)] == f"{study.range_km(vehicle.id, use):.0f} km"
    captions = " ".join(c.value for c in app.caption)
    assert "EU official" not in captions


def test_every_drive_runs(app: AppTest) -> None:
    # The drive options are the cycle keys plus "steady"; select them by value, which works
    # the same in every Streamlit version.
    for key in [*CYCLE_SPECS, "steady"]:
        app.selectbox(key="drive").select(key).run()
        assert not app.exception, key
        assert len(app.metric) == 4


def test_one_car_and_no_car(app: AppTest, study: Study) -> None:
    app.multiselect(key="cars").set_value(["vw-id4-pro"]).run()
    assert [m.label for m in app.metric] == ["VW ID.4 Pro"]
    app.multiselect(key="cars").set_value([]).run()
    assert not app.exception
    assert "Choose at least one car" in app.info[0].value


def test_validation_tab_reports_the_implied_charging_efficiency(app: AppTest, study: Study) -> None:
    text = " ".join(m.value for m in app.markdown)
    assert "not** used to identify them" in text
    ex30 = study.vehicle("volvo-ex30-sm-er")
    assert f"Volvo EX30 0.830 (EPA {ex30.epa.charging_efficiency:.3f})" in text
    assert "more than 3 % apart: Volvo EX30 consumption, Polestar 2 range)" in text
    assert f"The car's own consumption ({study.auxiliary_w:.0f} W)" in text


def test_cars_tab_lists_the_inputs(app: AppTest, study: Study) -> None:
    table = next(m.value for m in app.markdown if m.value.startswith("| | Tesla Model 3 RWD"))
    rows = {line.split(" | ")[0].strip("| "): line for line in table.splitlines()[2:]}
    tesla = study.vehicle("tesla-model3-rwd")
    assert f"| {tesla.wltp_test_mass_kg:.0f} |" in rows["EU: WLTP test mass (kg)"]
    assert (
        f"| {tesla.epa.usable_energy_wh / 1000:.1f} |" in rows["EPA: usable battery energy (kWh)"]
    )
    assert tesla.report_url in rows["EPA certificate"]
    assert len(rows) == 17


def test_sweep_text_uses_the_computed_crossover(app: AppTest, study: Study) -> None:
    text = " ".join(m.value for m in app.markdown)
    setup = study.vehicle("tesla-model3-rwd").wltp_setup()
    kmh = setup.road_load.drag_crossover_ms() * 3.6
    assert f"Tesla Model 3 RWD {kmh:.0f} km/h" in text
