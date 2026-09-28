"""Check the drive-cycle files against what the regulators state about the cycles.

tools/verify_cycles.py compares every file second by second with the tables printed in the
regulations, which needs the documents. This script needs nothing but the files and the
verified quotes in data/reference_values.json:

WLTC class 3b (UN GTR No. 15, Annex 1)
    - 1801 samples, t = 0..1800 s
    - phase durations of 589, 433, 455 and 323 s, as quoted from GTR 15 Annex 1, para. 3.4
    - per-phase checksums of the JRC reference implementation (JRCSTU/wltp): the sums of the
      speeds, in km/h, of seconds 0-589, 590-1022, 1023-1477 and 1478-1800
    - per-phase distance, maximum speed and maximum acceleration (a central difference,
      (v[i+1] - v[i-1]) / 2), pinned to the values computed from the verified file, so that
      any later change to the file shows up
UDDS and HWFET (40 CFR 86 Appendix I(a), 40 CFR 600 Appendix I)
    - length, distance and average speed as the EPA states them, to the digits it prints

Usage:
    python tools/check_cycles.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "cycles"
REFERENCES = ROOT / "data" / "reference_values.json"
MPH_TO_KMH = 1.609344  # exact

# name: (first second, last second, quoted duration, distance in m, v_max in km/h,
# a_max in m/s^2); the last three are computed from the verified file.
WLTC_PHASES = {
    "Low3": (0, 589, "low_phase_duration", 3095, 56.5, 1.47),
    "Medium3-2": (589, 1022, "medium_phase_duration", 4756, 76.6, 1.57),
    "High3-2": (1022, 1477, "high_phase_duration", 7162, 97.4, 1.58),
    "Extra High3": (1477, 1800, "extra_high_phase_duration", 8254, 131.3, 1.03),
}
# name: sum of the speeds in km/h over the phase's own seconds (the JRC checksums)
JRC_CHECKSUMS = {"Low3": 11140.3, "Medium3-2": 17121.2, "High3-2": 25782.2, "Extra High3": 29714.9}
# As the EPA states them on its schedule images uddsdds.gif and hwfetdds.gif
# (https://www.epa.gov/vehicle-and-fuel-emissions-testing/dynamometer-drive-schedules):
# "Length 1369 seconds - Distance = 7.45 miles - Average Speed = 19.59 mph" and
# "Length 765 seconds - Distance = 10.26 miles - Average Speed = 48.3 mph".
EPA_STATED = {"udds.csv": (1369, "7.45", "19.59"), "hwfet.csv": (765, "10.26", "48.3")}


def read(name: str) -> list[float]:
    """Speeds in km/h, one per second."""
    lines = [line for line in (DATA / name).read_text(encoding="utf-8").splitlines() if line]
    body = [line for line in lines if not line.startswith("#")]
    unit = body[0].split(",")[1]
    scale = MPH_TO_KMH if unit == "speed_mph" else 1.0
    return [float(row.split(",")[1]) * scale for row in body[1:]]


def quoted_durations() -> dict[str, int]:
    """Phase durations as quoted from GTR 15 (checked by tools/verify_references.py)."""
    items = json.loads(REFERENCES.read_text(encoding="utf-8"))["values"]["drive_cycles"]
    return {i["item"]: int(i["value"].removesuffix(" seconds")) for i in items}


def like(value: float, stated: str) -> str:
    """The value printed with as many decimals as the stated figure has."""
    return f"{value:.{len(stated.partition('.')[2])}f}"


def check(condition: bool, message: str, failures: list[str]) -> None:
    print(("  ok    " if condition else "  FAIL  ") + message)
    if not condition:
        failures.append(message)


def main() -> int:
    failures: list[str] = []

    wltc = read("wltc_class3b.csv")
    durations = quoted_durations()
    print("WLTC class 3b")
    check(len(wltc) == 1801, f"1801 samples (found {len(wltc)})", failures)
    total = 0.0
    for name, (start, end, quoted, distance, v_max, a_max) in WLTC_PHASES.items():
        part = wltc[start : end + 1]
        speed_sum = sum(part[1:] if start else part)  # the phase's own seconds
        metres = speed_sum / 3.6
        total += metres
        inner = range(max(start, 1), min(end, len(wltc) - 2) + 1)  # needs a neighbour each side
        accel = max((wltc[i + 1] - wltc[i - 1]) / (2 * 3.6) for i in inner)
        check(
            end - start == durations[quoted],
            f"{name}: {end - start} s, GTR 15: {durations[quoted]} s",
            failures,
        )
        check(
            round(speed_sum, 1) == JRC_CHECKSUMS[name],
            f"{name}: JRC checksum {speed_sum:.1f} -> {JRC_CHECKSUMS[name]}",
            failures,
        )
        check(
            round(metres) == distance, f"{name}: distance {metres:.1f} m -> {distance} m", failures
        )
        check(max(part) == v_max, f"{name}: v_max {max(part)} km/h", failures)
        check(round(accel, 2) == a_max, f"{name}: a_max {accel:.3f} m/s2 -> {a_max}", failures)
    check(round(total) == 23266, f"total distance {total:.1f} m -> 23266 m", failures)

    for name, (seconds, miles, mph) in EPA_STATED.items():
        speeds = read(name)
        length = len(speeds) - 1
        distance_mi = sum(speeds) / 3600 / MPH_TO_KMH
        average = distance_mi / (length / 3600)
        print(name)
        check(length == seconds, f"length {length} s, EPA: {seconds} s", failures)
        check(
            like(distance_mi, miles) == miles,
            f"distance {distance_mi:.3f} mi, EPA: {miles} mi",
            failures,
        )
        check(like(average, mph) == mph, f"average speed {average:.3f} mph, EPA: {mph}", failures)

    print("\nall checks passed" if not failures else f"\n{len(failures)} check(s) failed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
