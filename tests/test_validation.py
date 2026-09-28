"""The validation results that the documentation reports."""

from __future__ import annotations

import pytest

from evrange import Study
from evrange.validation import (
    Comparison,
    epa_comparisons,
    eu_comparisons,
    implied_eu_charging_efficiency,
    sensitivities,
)

# EU official values vs model: percentage differences as documented (one decimal).
EU = {
    ("tesla-model3-rwd", "consumption"): -0.6,
    ("tesla-model3-rwd", "range"): 2.3,
    ("volvo-ex30-sm-er", "consumption"): -8.5,
    ("volvo-ex30-sm-er", "range"): 2.0,
    ("polestar-2-lr-sm", "consumption"): 1.9,
    ("polestar-2-lr-sm", "range"): -6.9,
    ("vw-id4-pro", "consumption"): -2.8,
    ("vw-id4-pro", "range"): 0.0,
}


def test_eu_comparisons(study: Study) -> None:
    rows = eu_comparisons(study)
    assert len(rows) == 8
    for row in rows:
        kind = "consumption" if "consumption" in row.check else "range"
        assert round(row.error_pct, 1) == pytest.approx(EU[(row.vehicle_id, kind)], abs=1e-9)


def test_epa_checks_the_calibration_never_saw(study: Study) -> None:
    rows = epa_comparisons(study)
    checked = sorted({(r.vehicle_id, r.check) for r in rows})
    assert len(checked) == 8
    assert {r.vehicle_id for r in rows} == {"volvo-ex30-sm-er", "polestar-2-lr-sm"}
    assert max(abs(r.error_pct) for r in rows) < 2.1
    # The ID.4's B mode shares the road load of the calibrated D mode, so it is no new check.
    assert not any("B mode" in r.check for r in rows)


def test_implied_eu_charging_efficiency(study: Study) -> None:
    implied = {v.id: round(implied_eu_charging_efficiency(v), 3) for v in study.vehicles}
    assert implied == {
        "tesla-model3-rwd": 0.901,
        "volvo-ex30-sm-er": 0.830,
        "polestar-2-lr-sm": 0.845,
        "vw-id4-pro": 0.876,
    }


def test_no_modelling_choice_moves_a_result_by_more_than_about_one_point(study: Study) -> None:
    rows = sensitivities(study)
    assert len(rows) == 6
    for row in rows:
        for value in (*row.consumption_pp.values(), *row.range_pp.values()):
            assert abs(value) < 1.1


def test_comparison_band() -> None:
    row = Comparison("x", "check", "km", 105.0, 100.0)
    assert row.error_pct == pytest.approx(5.0)
    assert row.within_band is None
    assert Comparison("x", "c", "km", 105.0, 100.0, 90.0, 110.0).within_band is True
    assert Comparison("x", "c", "km", 115.0, 100.0, 90.0, 110.0).within_band is False
