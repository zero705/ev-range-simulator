"""Drive cycles: vehicle speed at one-second steps, read from data/cycles/.

tools/verify_cycles.py compares each file second by second with the table printed in its
regulation (docs/data-sources.md, section 1). The WLTC phases follow UN GTR No. 15, Annex 1:
the low, medium, high and extra-high phases last 589, 433, 455 and 323 seconds.
"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from evrange.constants import KMH_MS, MPH_MS
from evrange.datafiles import data_dir


@dataclass(frozen=True)
class CycleSpec:
    """Where a cycle comes from and which part of the file it uses."""

    file: str
    unit: str
    name: str
    source: str
    start_s: int = 0
    end_s: int | None = None


_WLTC = "UN GTR No. 15, Annex 1 (class 3b)"
CYCLE_SPECS: dict[str, CycleSpec] = {
    "wltc": CycleSpec("wltc_class3b.csv", "kmh", "WLTC", _WLTC),
    "wltc-low": CycleSpec("wltc_class3b.csv", "kmh", "WLTC low phase", _WLTC, 0, 589),
    "wltc-medium": CycleSpec("wltc_class3b.csv", "kmh", "WLTC medium phase", _WLTC, 589, 1022),
    "wltc-high": CycleSpec("wltc_class3b.csv", "kmh", "WLTC high phase", _WLTC, 1022, 1477),
    "wltc-extra-high": CycleSpec(
        "wltc_class3b.csv", "kmh", "WLTC extra-high phase", _WLTC, 1477, 1800
    ),
    "udds": CycleSpec("udds.csv", "mph", "UDDS (EPA city)", "40 CFR Part 86, Appendix I"),
    "hwfet": CycleSpec("hwfet.csv", "mph", "HWFET (EPA highway)", "40 CFR Part 600, Appendix I"),
}
_UNITS = {"kmh": KMH_MS, "mph": MPH_MS}


@dataclass(frozen=True, eq=False)
class DriveCycle:
    """A speed trace sampled once per second, starting at t = 0."""

    key: str
    name: str
    source: str
    speed_ms: NDArray[np.float64]

    def __post_init__(self) -> None:
        speed = np.array(self.speed_ms, dtype=np.float64)
        if speed.ndim != 1 or speed.size < 2:
            raise ValueError(f"{self.key}: a cycle needs at least two speed samples")
        if not np.all(np.isfinite(speed)) or np.any(speed < 0):
            raise ValueError(f"{self.key}: speeds must be finite and not negative")
        speed.setflags(write=False)
        object.__setattr__(self, "speed_ms", speed)

    @property
    def duration_s(self) -> float:
        return float(self.speed_ms.size - 1)

    @property
    def distance_m(self) -> float:
        """Distance by the trapezoidal rule, as physics.wheel_work integrates it."""
        return float(np.sum(self.speed_ms[:-1] + self.speed_ms[1:]) / 2)

    @property
    def mean_speed_kmh(self) -> float:
        return self.distance_m / self.duration_s / KMH_MS

    @property
    def max_speed_kmh(self) -> float:
        return float(self.speed_ms.max()) / KMH_MS

    @property
    def standstill_share(self) -> float:
        """Share of the one-second intervals spent at a standstill."""
        still = (self.speed_ms[:-1] == 0) & (self.speed_ms[1:] == 0)
        return float(np.mean(still))


def read_speed_file(path: Path, unit: str) -> NDArray[np.float64]:
    """Read a cycle file: comment lines starting with '#', then 'time_s,speed_<unit>' rows."""
    if unit not in _UNITS:
        raise ValueError(f"unknown speed unit {unit!r}")
    with path.open(encoding="utf-8") as handle:
        rows = [line for line in handle if line.strip() and not line.startswith("#")]
    reader = csv.reader(rows)
    header = next(reader, None)
    if header != ["time_s", f"speed_{unit}"]:
        raise ValueError(f"{path.name}: expected the header time_s,speed_{unit}")
    speeds: list[float] = []
    for expected, row in enumerate(reader):
        if len(row) != 2 or int(row[0]) != expected:
            raise ValueError(f"{path.name}: row {expected} is not at t = {expected} s")
        value = float(row[1])
        if not math.isfinite(value) or value < 0:
            raise ValueError(f"{path.name}: invalid speed at t = {expected} s")
        speeds.append(value)
    return np.asarray(speeds, dtype=np.float64) * _UNITS[unit]


def load_cycle(key: str, path: Path | str | None = None) -> DriveCycle:
    """Load one cycle, or one WLTC phase, by its key (see CYCLE_SPECS)."""
    if key not in CYCLE_SPECS:
        raise KeyError(f"unknown cycle {key!r}; choose from {', '.join(CYCLE_SPECS)}")
    spec = CYCLE_SPECS[key]
    speed = read_speed_file(data_dir(path) / "cycles" / spec.file, spec.unit)
    end = speed.size - 1 if spec.end_s is None else spec.end_s
    if end >= speed.size:
        raise ValueError(f"{spec.file} is shorter than the {spec.name}")
    return DriveCycle(key, spec.name, spec.source, speed[spec.start_s : end + 1])


def load_cycles(path: Path | str | None = None) -> dict[str, DriveCycle]:
    """Load every cycle and WLTC phase."""
    return {key: load_cycle(key, path) for key in CYCLE_SPECS}
