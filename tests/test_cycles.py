"""The cycles have the durations the regulators state, and the figures of the verified files."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from evrange.constants import MILE_M, MPH_MS
from evrange.cycles import CYCLE_SPECS, DriveCycle, load_cycle, load_cycles, read_speed_file
from evrange.datafiles import reference_items

# Class 3b phases: duration (s), distance (m) and top speed (km/h) of the verified file
# (docs/data-sources.md, section 1), and the item quoting the duration from UN GTR No. 15.
WLTC_PHASES = {
    "wltc-low": (589, 3095, 56.5, "low_phase_duration"),
    "wltc-medium": (433, 4756, 76.6, "medium_phase_duration"),
    "wltc-high": (455, 7162, 97.4, "high_phase_duration"),
    "wltc-extra-high": (323, 8254, 131.3, "extra_high_phase_duration"),
}


@pytest.mark.parametrize(("key", "expected"), WLTC_PHASES.items())
def test_wltc_phases(key: str, expected: tuple[int, int, float, str]) -> None:
    duration, distance, top, _ = expected
    cycle = load_cycle(key)
    assert cycle.duration_s == duration
    assert round(cycle.distance_m) == distance
    assert cycle.max_speed_kmh == pytest.approx(top)


def test_wltc_phase_durations_are_the_regulation_ones() -> None:
    quoted = {i["item"]: i["value"] for i in reference_items("drive_cycles")}
    for key, (*_, item) in WLTC_PHASES.items():
        assert f"{load_cycle(key).duration_s:.0f} seconds" == quoted[item]


def test_whole_wltc_is_its_four_phases() -> None:
    cycles = load_cycles()
    wltc = cycles["wltc"]
    assert wltc.duration_s == 1800
    assert round(wltc.distance_m) == 23266
    assert wltc.distance_m == pytest.approx(sum(cycles[k].distance_m for k in WLTC_PHASES))
    joined = np.concatenate(
        [cycles["wltc-low"].speed_ms] + [cycles[k].speed_ms[1:] for k in list(WLTC_PHASES)[1:]]
    )
    np.testing.assert_array_equal(joined, wltc.speed_ms)


@pytest.mark.parametrize(
    ("key", "duration", "miles", "top_mph"),
    [("udds", 1369, 7.45, 56.7), ("hwfet", 765, 10.26, 59.9)],
)
def test_epa_cycles(key: str, duration: int, miles: float, top_mph: float) -> None:
    # Length and distance as the EPA states them (docs/data-sources.md, section 1); top speed
    # of the verified file.
    cycle = load_cycle(key)
    assert cycle.duration_s == duration
    assert round(cycle.distance_m / MILE_M, 2) == miles
    assert cycle.speed_ms.max() / MPH_MS == pytest.approx(top_mph)


def test_every_cycle_starts_and_ends_at_rest() -> None:
    for cycle in load_cycles().values():
        assert cycle.speed_ms[0] == 0
        assert cycle.speed_ms[-1] == 0
        assert 0 < cycle.standstill_share < 1
        assert cycle.mean_speed_kmh == pytest.approx(cycle.distance_m / cycle.duration_s * 3.6)


def test_cycle_arrays_are_read_only() -> None:
    cycle = load_cycle("udds")
    with pytest.raises(ValueError, match="read-only"):
        cycle.speed_ms[0] = 1.0


def test_unknown_cycle() -> None:
    with pytest.raises(KeyError, match="unknown cycle"):
        load_cycle("nedc")


@pytest.mark.parametrize(
    "speeds",
    [np.array([1.0]), np.array([[0.0, 1.0]]), np.array([0.0, -1.0]), np.array([0.0, np.nan])],
)
def test_drive_cycle_rejects_bad_traces(speeds: np.ndarray) -> None:
    with pytest.raises(ValueError, match=r"cycle|speeds"):
        DriveCycle("x", "x", "x", speeds)


def _write(folder: Path, text: str) -> Path:
    path = folder / "cycle.csv"
    path.write_text(text, encoding="utf-8")
    return path


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("time_s,speed\n0,0\n", "header"),
        ("# note\ntime_s,speed_kmh\n0,0\n2,1\n", "row 1"),
        ("time_s,speed_kmh\n0,0\n1,-3\n", "invalid speed"),
        ("time_s,speed_kmh\n0,0\n1,inf\n", "invalid speed"),
        ("time_s,speed_kmh\n0,0,1\n", "row 0"),
    ],
)
def test_speed_file_errors(tmp_path: Path, text: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        read_speed_file(_write(tmp_path, text), "kmh")


def test_speed_file_units(tmp_path: Path) -> None:
    path = _write(tmp_path, "# comment\ntime_s,speed_mph\n0,0\n1,10\n")
    np.testing.assert_allclose(read_speed_file(path, "mph"), [0, 10 * MPH_MS])
    with pytest.raises(ValueError, match="unit"):
        read_speed_file(path, "knots")


def test_phase_beyond_the_file_is_refused(data_copy: Path) -> None:
    short = data_copy / "cycles" / "wltc_class3b.csv"
    lines = short.read_text(encoding="utf-8").splitlines()
    short.write_text("\n".join(lines[:-10]) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="shorter"):
        load_cycle("wltc-extra-high", data_copy)


def test_specs_cover_every_file() -> None:
    files = {spec.file for spec in CYCLE_SPECS.values()}
    assert files == {"wltc_class3b.csv", "udds.csv", "hwfet.csv"}
