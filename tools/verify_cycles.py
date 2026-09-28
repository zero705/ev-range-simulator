"""Compare the drive-cycle files second by second with the tables printed in the regulations.

    WLTC class 3b  UN GTR No. 15, Annex 1, Tables A1/7, A1/9, A1/11 and A1/12 (Low3,
                   Medium3-2, High3-2, Extra High3)
    UDDS           40 CFR Part 86, Appendix I, paragraph (a)
    HWFET          40 CFR Part 600, Appendix I

The regulations are read from fingerprinted copies in data/sources/: the GTR as a PDF, the two
CFR appendices as the eCFR's point-in-time XML of 1 September 2026. The eCFR tables contain four
misprinted time labels; each is listed in MISPRINTS with the speed printed next to it, and is
corrected only when both match. Any other difference fails the check. The fingerprints of the
EPA's two schedule images, whose figures tools/check_cycles.py uses, are checked as well.

Usage:
    python tools/verify_cycles.py              # needs the documents in data/sources/
    python tools/verify_cycles.py --download   # fetch them first (see tools/downloads.py)
"""

from __future__ import annotations

import argparse
import hashlib
import html
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from downloads import download, store
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parent.parent
CYCLES = ROOT / "data" / "cycles"
SOURCES = ROOT / "data" / "sources"
ECFR = "https://www.ecfr.gov/api/versioner/v1/full/2026-09-01/title-40.xml"

DOCUMENTS = {
    "gtr15": {
        "file": "unece_gtr15_ece-trans-180-add15_2014-05-12.pdf",
        "url": "https://www.transportpolicy.net/wp-content/uploads/2021/08/GTR-No-15.pdf",
        "sha256": "2b15775dfc03b1692661ea60e528ac8b9937c189f88674933c190400264c82a1",
    },
    "cfr86": {
        "file": "ecfr_40cfr86_appendix_I_2026-09-01.xml",
        "url": f"{ECFR}?part=86&appendix=Appendix%20I%20to%20Part%2086",
        "sha256": "47aceb0e68799738952d9df5bc3d71ecec0e84a5afd925bfb8eb9d908d71ccf5",
    },
    "cfr600": {
        "file": "ecfr_40cfr600_appendix_I_2026-09-01.xml",
        "url": f"{ECFR}?part=600&appendix=Appendix%20I%20to%20Part%20600",
        "sha256": "f3cec162e6c700e822804bfda32c737b9d257392bbc86386ccbc4dddd771759a",
    },
    # The EPA states each cycle's length, distance and average speed as text drawn on these
    # images; tools/check_cycles.py checks the files against the figures, read by eye.
    "udds-image": {
        "file": "epa_uddsdds.gif",
        "url": "https://www.epa.gov/sites/default/files/2015-10/uddsdds.gif",
        "sha256": "3a87f73e8ecb4d24ef77fd52b2b4aa6fdaa099886c9561bebdeb0e413124a4a8",
    },
    "hwfet-image": {
        "file": "epa_hwfetdds.gif",
        "url": "https://www.epa.gov/sites/default/files/2015-10/hwfetdds.gif",
        "sha256": "e6103581acabf959613c79b6f1607f8c6fa600510925332a414457ebe4550a49",
    },
}
# The eCFR serves its point-in-time text as XML when asked for it.
ACCEPT = {"cfr86": "application/xml", "cfr600": "application/xml"}

# (printed time label, printed speed) -> the second the speed belongs to. The printed label's
# own second appears elsewhere in the table with its own speed, so the pair is unambiguous.
MISPRINTS: dict[str, dict[tuple[str, str], int]] = {
    "udds": {("1318", "21.5"): 1218},
    "hwfet": {("446", "58.3"): 466, ("6.36", "53.6"): 636, ("6.39", "48.2"): 639},
}
# 40 CFR 600 Appendix I prints the sampling events at the first and last second, not a speed.
MARKERS: dict[str, dict[int, str]] = {"hwfet": {0: "Sample On", 765: "Sample Off"}}
# (last second of the file, last second of the table) where they differ: the table of
# 40 CFR 86 Appendix I(a) runs on at rest for three seconds after the EPA file ends.
RUN_ON: dict[str, tuple[int, int]] = {"udds": (1369, 1372)}

GTR_TABLES = ("A1/7", "A1/9", "A1/11", "A1/12")
UDDS_CAPTION = "EPA Urban Dynamometer Driving Schedule"

Pair = tuple[str, str]


def read_cycle(name: str) -> list[float]:
    """The speeds of a cycle file, in the unit of the file (km/h or mph), one per second."""
    lines = (CYCLES / name).read_text(encoding="utf-8").splitlines()
    body = [line for line in lines if line and not line.startswith("#")]
    return [float(row.split(",")[1]) for row in body[1:]]


def _clean(fragment: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def _caption(table: str) -> str:
    return _clean("".join(re.findall(r"<CAPTION>.*?</CAPTION>", table, flags=re.S)))


def cfr_pairs(xml: str, caption: str | None = None) -> list[Pair]:
    """The (time, speed) cells of an eCFR appendix's tables, or of the one with this caption."""
    tables = re.findall(r"<TABLE.*?</TABLE>", xml, flags=re.S)
    if caption is not None:
        tables = [t for t in tables if caption in _caption(t)]
        if len(tables) != 1:
            raise ValueError(f"expected one table captioned {caption!r}, found {len(tables)}")
    pairs = []
    for table in tables:
        for row in re.findall(r"<TR>(.*?)</TR>", table, flags=re.S):
            cells = [_clean(c) for c in re.findall(r"<TD[^>]*>(.*?)</TD>", row, flags=re.S)]
            pairs += [(t, v) for t, v in zip(cells[::2], cells[1::2], strict=False) if t or v]
    return pairs


def gtr_pairs(path: Path) -> list[Pair]:
    """The (time, speed) pairs of the class 3b tables of GTR 15 Annex 1, in the order printed."""
    text = "\n".join(page.extract_text() or "" for page in PdfReader(path).pages)
    headings = list(re.finditer(r"Table (A1/\d+)\s*\n[^\n]*?WLTC, Class 3 vehicles, phase", text))
    end = text.index("7. Cycle modification", headings[-1].end())
    pairs = []
    for number, heading in enumerate(headings):
        if heading.group(1) not in GTR_TABLES:
            continue
        stop = headings[number + 1].start() if number + 1 < len(headings) else end
        for line in text[heading.end() : stop].splitlines():
            tokens = line.split()
            times, speeds = tokens[::2], tokens[1::2]
            if (
                tokens
                and len(times) == len(speeds)
                and all(re.fullmatch(r"\d+", t) for t in times)
                and all(re.fullmatch(r"\d+(\.\d)?", s) for s in speeds)
            ):
                pairs += list(zip(times, speeds, strict=True))
    found = [h.group(1) for h in headings if h.group(1) in GTR_TABLES]
    if found != list(GTR_TABLES):
        raise ValueError(f"expected the tables {GTR_TABLES}, found {found}")
    return pairs


@dataclass
class Table:
    """A regulation table read second by second."""

    speeds: dict[int, float] = field(default_factory=dict)
    marked: list[int] = field(default_factory=list)
    corrected: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)


def read_table(cycle: str, pairs: list[Pair]) -> Table:
    """The speed at each second, with the listed misprints corrected and markers set aside."""
    misprints, markers = MISPRINTS.get(cycle, {}), MARKERS.get(cycle, {})
    table = Table()
    for label, speed in pairs:
        if (label, speed) in misprints:
            second = misprints[(label, speed)]
            table.corrected.append(f"'{label}' is second {second}")
        elif re.fullmatch(r"\d+", label):
            second = int(label)
        else:
            table.problems.append(f"time label {label!r} (speed {speed!r}) is not a second")
            continue
        if markers.get(second) == speed:
            table.marked.append(second)
        elif not re.fullmatch(r"\d+(\.\d+)?", speed):
            table.problems.append(f"second {second}: {speed!r} is not a speed")
        elif second in table.speeds:
            table.problems.append(f"second {second} is printed twice")
        else:
            table.speeds[second] = float(speed)
    if len(table.corrected) != len(misprints):
        table.problems.append(f"expected {len(misprints)} misprints, found {table.corrected}")
    if sorted(table.marked) != sorted(markers):
        table.problems.append(f"sampling markers at {sorted(table.marked)}, not {sorted(markers)}")
    return table


def compare(cycle: str, pairs: list[Pair], values: list[float]) -> tuple[list[str], list[str]]:
    """Compare a regulation table with a cycle file: (problems, notes); no problems if equal."""
    markers = MARKERS.get(cycle, {})
    table = read_table(cycle, pairs)
    speeds, problems = table.speeds, table.problems
    last = len(values) - 1
    ends = (last, max([*speeds, *table.marked], default=-1))
    expected = RUN_ON.get(cycle, (last, last))
    if ends != expected:
        problems.append(
            f"the file ends at second {ends[0]} and the table at {ends[1]}, "
            f"expected {expected[0]} and {expected[1]}"
        )
    run_on = [s for s in range(last + 1, ends[1] + 1) if s not in markers]
    problems += [f"second {s} after the file is not at rest" for s in run_on if speeds.get(s) != 0]
    for second, value in enumerate(values):
        if second in markers:
            if value != 0.0:
                problems.append(f"second {second}: the file has {value}, not the car at rest")
        elif second not in speeds:
            problems.append(f"second {second} is not in the table")
        elif speeds[second] != value:
            problems.append(f"second {second}: {speeds[second]} in the table, {value} in the file")
    notes = []
    if table.corrected:
        notes.append("misprinted time labels, corrected: " + "; ".join(table.corrected))
    if table.marked:
        events = ", ".join(f"{s} '{markers[s]}'" for s in sorted(table.marked))
        notes.append(f"sampling events instead of a speed at seconds {events}; the file is at rest")
    if run_on:
        notes.append(f"the table runs on at rest to second {ends[1]}; the file ends at {last}")
    return problems, notes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--download", action="store_true", help="fetch the documents first")
    args = parser.parse_args()
    failures = 0
    paths = {}
    for key, doc in DOCUMENTS.items():
        path = SOURCES / doc["file"]
        if args.download and not store(path, download(doc["url"], ACCEPT.get(key)), doc["sha256"]):
            print(f"  FAIL  {key}: the download differs; saved as {doc['file']}.rejected")
            failures += 1
        if not path.is_file():
            print(f"  skip  {key}: {doc['file']} is not in data/sources; download {doc['url']}")
            continue
        ok = hashlib.sha256(path.read_bytes()).hexdigest() == doc["sha256"]
        failures += not ok
        print(f"  {'ok  ' if ok else 'FAIL'}  {key}: fingerprint")
        if ok:
            paths[key] = path
    checks = (
        ("wltc", "wltc_class3b.csv", "gtr15", "GTR 15, Annex 1"),
        ("udds", "udds.csv", "cfr86", "40 CFR 86, Appendix I(a)"),
        ("hwfet", "hwfet.csv", "cfr600", "40 CFR 600, Appendix I"),
    )
    for cycle, name, key, source in checks:
        if key not in paths:
            print(f"  skip  {cycle}: {source} not available")
            continue
        if key == "gtr15":
            pairs = gtr_pairs(paths[key])
        else:
            xml = paths[key].read_text(encoding="utf-8")
            pairs = cfr_pairs(xml, UDDS_CAPTION if key == "cfr86" else None)
        values = read_cycle(name)
        print(f"{name} against {source}")
        problems, notes = compare(cycle, pairs, values)
        for problem in problems:
            print(f"  FAIL  {problem}")
        if not problems:
            speeds = len(values) - len(MARKERS.get(cycle, {}))
            print(f"  ok    {speeds} speeds, second by second, identical to the table")
        for note in notes:
            print(f"        {note}")
        failures += len(problems)
    print("\nall cycles verified" if not failures else f"\n{failures} problem(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
