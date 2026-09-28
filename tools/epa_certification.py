"""Extract battery (DC) and mains (AC) energy from EPA certificate summaries.

Source: US EPA, Document Index System, "Certificate Summary Information" reports
https://dis.epa.gov/otaqpub/ (one report per test group and model year; public records)

Electric cars are certified with the procedures of SAE J1634 (40 CFR 600.116-12): the test
vehicle is driven from full to empty on a dynamometer set to its EPA road load, then recharged
from the mains. The report of each test group records, for its test vehicles:

    Recharge Event Energy          AC energy taken from the mains to recharge, kWh
    MCT UBE energy                 usable battery energy: all DC energy discharged in the test
    DC energy consumption          DC energy per mile on the UDDS and highway cycles, Wh/mi
    Charge Depleting Range         usable battery energy divided by that consumption, miles

40 CFR 600.116-12(a)(8): "SAE J1634 Section 3.13 defines useable battery energy (UBE) as the
total DC discharge energy (Edc total), measured in DC watt-hours for a full discharge test."

Two report layouts occur. Tesla, Polestar and Volkswagen state the DC consumption of each
cycle in the manufacturer's comments. Volvo lists the eight phases of the Multi-Cycle Test
(UDDS 1, highway 1, UDDS 2, constant speed, UDDS 3, highway 2, UDDS 4, constant speed) with
the DC energy and distance of each; the cycle values are then computed the way the other
reports weight them (UDDS 1 by its share of the usable energy, the other three UDDS equally;
the two highway cycles equally), and the result is checked against the ranges the report
certifies.

Every number in the output is read from the reports by this script and checked:
    - each report has the fingerprint recorded below,
    - the test vehicle, its road-load coefficients and test weight are the ones in
      data/vehicles.json (EPA Test Car List),
    - usable energy / consumption reproduces each certified range,
    - stated averages and weightings reproduce the values the report gives,
    - for the Multi-Cycle Test, the phases are in the regulatory order and the computed cycle
      values reproduce both certified ranges.

Usage:
    python tools/epa_certification.py              reports must be in data/sources/
    python tools/epa_certification.py --download   fetch missing reports from the EPA first
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean
from typing import Any

from downloads import download as fetch_document
from downloads import store
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parent.parent
SOURCES = ROOT / "data" / "sources"
VEHICLES = ROOT / "data" / "vehicles.json"
OUTPUT = ROOT / "data" / "epa_certification.json"
URL = "https://dis.epa.gov/otaqpub/display_file.jsp?docid={docid}&flag=1"

MILE_KM = 1.609344  # exact
UDDS_MI = (7.3, 7.6)  # distance windows that recognise the phases of a Multi-Cycle Test
HWFET_MI = (10.1, 10.4)
RANGE_TOLERANCE = 0.001  # 0.1 %
STATED_TOLERANCE = 0.051  # Wh/mi: reports state consumption to 0.1 Wh/mi

# What to take from each report. "use" is the configuration the model is built on (the EPA
# record in data/vehicles.json); "also" are further configurations of the same test vehicle,
# kept as out-of-sample checks.
REPORTS: list[dict[str, Any]] = [
    {
        "vehicle": "tesla-model3-rwd",
        "docid": 59856,
        "file": "epa_cert_RTSLV00.0L13_59856.pdf",
        "sha256": "96c5872776de25db398efc3efce597eeac4c718fc21d53c8880da52b5a2460d1",
        "use": {
            "test_vehicle": "3R124-649670/0",
            "tests": ["RTSL10083348", "RTSL10083349"],
            "label": "base",
        },
        "also": [],
    },
    {
        "vehicle": "volvo-ex30-sm-er",
        "docid": 63199,
        "file": "epa_cert_SVVXV00.0Z0D_63199.pdf",
        "sha256": "84720bc1990767a4c6c36486c8879399be9ae15871bf5f08ff314a19371b08e4",
        "use": {
            "test_vehicle": "202532/1",
            "tests": ["SVVX10086370"],
            "label": "19 and 20 inch wheels",
        },
        "also": [
            {"test_vehicle": "202532/0", "tests": ["SVVX10086354"], "label": "18 inch wheels"}
        ],
    },
    {
        "vehicle": "polestar-2-lr-sm",
        "docid": 60467,
        "file": "epa_cert_SVVXV00.0Z0B_60467.pdf",
        "sha256": "ce442301f3b615f029719077af232a9a9577dbc5d1d57314018d6ce48991a4ec",
        "use": {
            "test_vehicle": "202506/0",
            "tests": ["SVVX10084256", "SVVX10084257"],
            "label": "19 inch wheels",
        },
        "also": [
            {
                "test_vehicle": "202506/1",
                "tests": ["SVVX10084258", "SVVX10084259"],
                "label": "20 inch wheels",
            }
        ],
    },
    {
        "vehicle": "vw-id4-pro",
        "docid": 59583,
        "file": "epa_cert_RVGAV00.0VZR_59583.pdf",
        "sha256": "ba306b696357a6559964162de33eda57eccc1b317580ce0cca8c5d83a2976cbb",
        "use": {
            "test_vehicle": "VW316640473/0",
            "tests": ["RVGA10082539", "RVGA10082542"],
            "label": "D mode (default drive mode)",
        },
        "also": [
            {
                "test_vehicle": "VW316640473/0",
                "tests": ["RVGA10082538", "RVGA10082541"],
                "label": "B mode (stronger regenerative braking)",
            }
        ],
    },
]

PAGE_HEADER = re.compile(
    r"^(Date: .* Certification Summary Information Report"
    r"|Test Group \S+ Evaporative/Refueling Family .*"
    r"|Page \d+ of \d+ .*)$",
    re.MULTILINE,
)
NUMBER = r"(-?\d[\d,]*\.?\d*)"
VEHICLE_MARK = re.compile(r"Vehicle ID / Configuration (\S+) / (\d+)")
TEST_MARK = re.compile(r"Test # (\S+) Test Procedure (\d+) - ([^\n]+)")
PHASE = re.compile(
    r"Actual Distance Driven \(miles\) ([\d.]+)\s+(?:.*?\n)*?"
    r"Integrated DC KW-HRS ([\d.]+)\s+Manufacturer Fuel Economy ([\d.]+)"
)


def num(text: str) -> float:
    return float(text.replace(",", ""))


def find(pattern: str, text: str) -> str:
    match = re.search(pattern, text)
    if match is None:
        raise ValueError(f"not found in report: {pattern}")
    return match.group(1)


@dataclass
class Report:
    header: dict[str, Any]
    vehicles: dict[str, dict[str, Any]] = field(default_factory=dict)
    tests: dict[str, dict[str, Any]] = field(default_factory=dict)


def parse(path: Path) -> Report:
    raw = "\n".join((page.extract_text() or "") for page in PdfReader(str(path)).pages)
    report = Report(
        {
            "test_group": find(r"Test Group (\S+) Evaporative", raw),
            "certificate": find(r"Certificate Number (\S+)", raw),
            "issued": find(r"Certificate Issue Date (\d\d/\d\d/\d{4})", raw),
            "revision_submitted": find(
                r"CSI Submission/Revision Date (\d\d/\d\d/\d{4} [\d:]+ [AP]M)", raw
            ),
            "model_year": int(find(r"Model Year (\d{4})", raw)),
        }
    )
    body = PAGE_HEADER.sub("", raw)
    marks = sorted(
        [(m.start(), m) for m in VEHICLE_MARK.finditer(body)]
        + [(m.start(), m) for m in TEST_MARK.finditer(body)],
        key=lambda mark: mark[0],
    )
    vehicle_key = None
    for index, (start, match) in enumerate(marks):
        end = marks[index + 1][0] if index + 1 < len(marks) else len(body)
        block = body[start:end]
        if match.re is VEHICLE_MARK:
            vehicle_key = f"{match.group(1)}/{match.group(2)}"
            report.vehicles[vehicle_key] = parse_vehicle(match, block)
        else:
            report.tests[match.group(1)] = parse_test(match, block, vehicle_key)
    return report


def parse_vehicle(match: re.Match[str], block: str) -> dict[str, Any]:
    coefficients = re.search(r"City/Highway/Evap" + (" " + NUMBER) * 6, block)
    if coefficients is None:
        raise ValueError(f"no road-load coefficients for {match.group(0)}")
    return {
        "test_vehicle_id": match.group(1),
        "configuration": int(match.group(2)),
        "curb_weight_lb": num(find(r"Curb Weight \(lbs\) " + NUMBER, block)),
        "equivalent_test_weight_lb": num(
            find(r"Equivalent Test Weight \(pounds\) " + NUMBER, block)
        ),
        "target_coefficients": {
            "A_lbf": num(coefficients.group(1)),
            "B_lbf_per_mph": num(coefficients.group(2)),
            "C_lbf_per_mph2": num(coefficients.group(3)),
        },
    }


def parse_test(match: re.Match[str], block: str, vehicle_key: str | None) -> dict[str, Any]:
    highway = re.search(r"Charge Depleting Range Highway\s*\(Calculated miles\) ([\d.]+|--)", block)
    comments = re.search(
        r"Manufacturer Test Comments (.*?)(?:\nCertification\s*\n|\Z)", block, re.DOTALL
    )
    test: dict[str, Any] = {
        "number": match.group(1),
        "procedure": f"{match.group(2)} - {match.group(3).strip()}",
        "test_vehicle": vehicle_key,
        "date": find(r"Test Date (\d\d/\d\d/\d{4})", block),
        "four_wheel_drive_dynamometer": find(r"4WD Test Dyno (Yes|No)", block) == "Yes",
        "recharge_voltage_v": num(find(r"Recharge Event Voltage " + NUMBER, block)),
        "recharge_energy_kwh": num(
            find(r"Recharge Event Energy \(kiloWatt-hours\) " + NUMBER, block)
        ),
        "certified_range_mi": num(
            find(r"Charge Depleting Range \(Calculated miles\) " + NUMBER, block)
        ),
        "certified_highway_range_mi": (
            num(highway.group(1)) if highway and highway.group(1) != "--" else None
        ),
        "comments": " ".join(comments.group(1).split()) if comments else "",
    }
    if match.group(2) == "77":  # Multi-Cycle Test: the report lists its phases one by one
        test["phases"] = [
            {"miles": num(d), "dc_kwh": num(e), "reported_kwh_per_100mi": num(f)}
            for d, e, f in PHASE.findall(block)
        ]
    return test


def comment_values(comments: str) -> dict[str, float | None]:
    def value(pattern: str) -> float | None:
        match = re.search(pattern, comments, re.IGNORECASE)
        return num(match.group(1)) if match else None

    values = {
        "udds_weighted": value(r"UDDS weighted\s*=\s*([\d.]+)\s*Wh/mi"),
        "hwfet_average": value(r"HWFE\s*average\s*[=-]\s*([\d.]+)\s*Wh/mi"),
        "udds1_dc_wh": value(r"UDDS1 DC discharge energy\s*=\s*([\d.,]+)\s*Wh"),
        "ube_wh": value(r"MCT UBE energy\s*=\s*([\d.,]+)\s*Wh"),
    }
    for cycle, count in (("UDDS", 4), ("HWFE", 2)):
        for i in range(1, count + 1):
            values[f"{cycle.lower()}{i}"] = value(rf"{cycle}{i}\s*[=-]\s*([\d.]+)\s*Wh/mi")
    return values


class Checks:
    def __init__(self) -> None:
        self.failures = 0

    def __call__(self, ok: bool, label: str) -> bool:
        self.failures += not ok
        print(f"  {'ok  ' if ok else 'FAIL'}  {label}")
        return ok

    @staticmethod
    def note(label: str) -> None:
        print(f"  note  {label}")


def from_comments(tests: list[dict[str, Any]], check: Checks) -> dict[str, Any]:
    """Cycle values stated by the manufacturer (Tesla, Polestar and Volkswagen layout)."""
    udds, hwfet = tests
    u, h = comment_values(udds["comments"]), comment_values(hwfet["comments"])
    ube, city, highway = u["ube_wh"], u["udds_weighted"], h["hwfet_average"]
    check(
        None not in (ube, city, highway),
        "report states usable energy, UDDS and highway DC consumption",
    )
    if ube is None or city is None or highway is None:
        raise ValueError("incomplete report")
    check(
        udds["recharge_energy_kwh"] == hwfet["recharge_energy_kwh"],
        f"UDDS and highway results come from one test (recharge {udds['recharge_energy_kwh']} kWh)",
    )
    for cycle, test, consumption in (("UDDS", udds, city), ("highway", hwfet, highway)):
        certified = test["certified_range_mi"]
        # some reports print the certified range rounded to whole miles
        ok = abs(ube / consumption - certified) <= max(0.5, RANGE_TOLERANCE * certified)
        check(
            ok,
            f"{cycle}: {ube:.0f} Wh / {consumption} Wh/mi = {ube / consumption:.2f} mi, "
            f"certified {certified} mi",
        )
    if h["hwfe1"] is not None and h["hwfe2"] is not None:
        average = mean([h["hwfe1"], h["hwfe2"]])
        check(
            abs(average - highway) < STATED_TOLERANCE,
            f"highway {highway} Wh/mi = mean of {h['hwfe1']} and {h['hwfe2']}",
        )
    phases = [p for p in (u[f"udds{i}"] for i in range(1, 5)) if p is not None]
    first_udds_wh = u["udds1_dc_wh"]
    if first_udds_wh is not None and len(phases) == 4:
        k1 = first_udds_wh / ube
        weighted = k1 * phases[0] + (1 - k1) * mean(phases[1:])
        check(
            abs(weighted - city) < STATED_TOLERANCE,
            f"UDDS weighting reproduced: {weighted:.2f} vs stated {city} Wh/mi",
        )
    return {
        "usable_battery_energy_wh": ube,
        "dc_wh_per_mi": {"udds": city, "hwfet": highway},
        "certified_range_mi": {
            "udds": udds["certified_range_mi"],
            "hwfet": hwfet["certified_range_mi"],
        },
        "recharge": {
            "mains_voltage_v": udds["recharge_voltage_v"],
            "energy_kwh": udds["recharge_energy_kwh"],
        },
    }


def phase_kind(miles: float) -> str:
    if UDDS_MI[0] <= miles <= UDDS_MI[1]:
        return "udds"
    if HWFET_MI[0] <= miles <= HWFET_MI[1]:
        return "hwfet"
    return "constant_speed"


def from_phases(test: dict[str, Any], check: Checks) -> dict[str, Any]:
    """Cycle values computed from the phases of a Multi-Cycle Test (Volvo layout)."""
    phases = test["phases"]
    order = [phase_kind(p["miles"]) for p in phases]
    check(
        order == ["udds", "hwfet", "udds", "constant_speed"] * 2,
        f"{len(phases)} phases in the regulatory order (UDDS, highway, UDDS, constant speed, "
        "twice; 40 CFR 600.116-12(a)(2))",
    )
    for i, p in enumerate(phases, 1):
        computed = p["dc_kwh"] / p["miles"] * 100
        if abs(computed - p["reported_kwh_per_100mi"]) > 0.001 * computed:
            check.note(
                f"phase {i}: printed {p['reported_kwh_per_100mi']} kWh/100 mi, but its own "
                f"energy and distance give {computed:.3f}; the computed value is used"
            )
    ube = sum(p["dc_kwh"] for p in phases) * 1000
    wh_per_mi = [p["dc_kwh"] * 1000 / p["miles"] for p in phases]
    by_kind = {
        kind: [w for w, k in zip(wh_per_mi, order, strict=True) if k == kind]
        for kind in ("udds", "hwfet", "constant_speed")
    }
    k1 = phases[0]["dc_kwh"] * 1000 / ube
    city = k1 * by_kind["udds"][0] + (1 - k1) * mean(by_kind["udds"][1:])
    highway = mean(by_kind["hwfet"])
    certified = test["certified_range_mi"]
    certified_hwy = test["certified_highway_range_mi"]
    check(
        abs(ube / city - certified) <= RANGE_TOLERANCE * certified,
        f"UDDS: {ube:.1f} Wh / {city:.2f} Wh/mi = {ube / city:.3f} mi, certified {certified} mi",
    )
    check(
        certified_hwy is not None
        and abs(ube / highway - certified_hwy) <= RANGE_TOLERANCE * certified_hwy,
        f"highway: {ube:.1f} Wh / {highway:.2f} Wh/mi = {ube / highway:.3f} mi, "
        f"certified {certified_hwy} mi",
    )
    return {
        "usable_battery_energy_wh": round(ube, 1),
        "dc_wh_per_mi": {"udds": round(city, 2), "hwfet": round(highway, 2)},
        "certified_range_mi": {"udds": certified, "hwfet": certified_hwy},
        "recharge": {
            "mains_voltage_v": test["recharge_voltage_v"],
            "energy_kwh": test["recharge_energy_kwh"],
        },
        "constant_65_mph_dc_wh_per_mi": [round(w, 2) for w in by_kind["constant_speed"]],
        "phases": [dict(p, kind=k) for p, k in zip(phases, order, strict=True)],
    }


def summarise(report: Report, spec: dict[str, Any], check: Checks) -> dict[str, Any]:
    vehicle = report.vehicles[spec["test_vehicle"]]
    tests = [report.tests[n] for n in spec["tests"]]
    check(
        all(t["test_vehicle"] == spec["test_vehicle"] for t in tests),
        f"tests {', '.join(spec['tests'])} belong to test vehicle {spec['test_vehicle']}",
    )
    values = from_phases(tests[0], check) if len(tests) == 1 else from_comments(tests, check)
    ube = values["usable_battery_energy_wh"]
    return {
        "label": spec["label"],
        "test_vehicle": vehicle,
        "tests": [
            {k: t[k] for k in ("number", "procedure", "date", "four_wheel_drive_dynamometer")}
            for t in tests
        ],
        **values,
        "dc_wh_per_km": {k: round(v / MILE_KM, 2) for k, v in values["dc_wh_per_mi"].items()},
        "charging_efficiency": round(ube / (values["recharge"]["energy_kwh"] * 1000), 4),
    }


def matches_road_load(summary: dict[str, Any], record: dict[str, Any]) -> bool:
    vehicle = summary["test_vehicle"]
    return bool(
        vehicle["test_vehicle_id"] == record["test_vehicle_id"]
        and vehicle["target_coefficients"] == record["target_coefficients"]
        and vehicle["equivalent_test_weight_lb"] == record["equivalent_test_weight_lb"]
    )


def fetch(spec: dict[str, Any], download: bool) -> Path | None:
    """The local copy of a report, downloaded first if it is missing and download is set."""
    path = SOURCES / str(spec["file"])
    url = URL.format(docid=spec["docid"])
    if path.is_file():
        return path
    if not download:
        print(f"  missing {path.name}: run with --download or fetch {url}")
        return None
    if not store(path, fetch_document(url), spec["sha256"]):
        print(f"  FAIL  the EPA now serves another {path.name}; saved as {path.name}.rejected")
        return None
    return path


def main(download: bool) -> int:
    road_load = {
        v["id"]: v["us_road_load"]
        for v in json.loads(VEHICLES.read_text(encoding="utf-8"))["vehicles"]
    }
    check = Checks()
    out = []
    for spec in REPORTS:
        print(f"{spec['vehicle']}  (EPA document {spec['docid']})")
        path = fetch(spec, download)
        if path is None:
            check.failures += 1
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if not check(digest == spec["sha256"], f"fingerprint of {path.name}"):
            continue
        report = parse(path)
        used = summarise(report, spec["use"], check)
        check(
            matches_road_load(used, road_load[spec["vehicle"]]),
            "test vehicle, road-load coefficients and test weight match data/vehicles.json",
        )
        others = []
        for extra in spec["also"]:
            print(f"  -- also: {extra['label']}")
            others.append(summarise(report, extra, check))
        out.append(
            {
                "id": spec["vehicle"],
                "report": {
                    "publisher": "US Environmental Protection Agency",
                    "title": "Certificate Summary Information Report",
                    **report.header,
                    "docid": spec["docid"],
                    "url": URL.format(docid=spec["docid"]),
                    "file": spec["file"],
                    "sha256": spec["sha256"],
                },
                **used,
                "other_configurations": others,
            }
        )
    if check.failures:
        print(f"\n{check.failures} problem(s); {OUTPUT.name} not written")
        return 1
    result = {
        "about": "Battery-side (DC) and mains-side (AC) energy measured in the EPA "
        "certification test of each car, read from the EPA certificate summaries by "
        "tools/epa_certification.py. See docs/data-sources.md.",
        "definitions": {
            "usable_battery_energy_wh": "total DC energy discharged in the full-discharge test "
            "(40 CFR 600.116-12(a)(8))",
            "dc_wh_per_mi": "DC energy per mile on the UDDS (weighted over the four UDDS of the "
            "Multi-Cycle Test) and on the highway cycle (mean of the two)",
            "recharge": "AC energy taken from the mains to recharge after the test",
            "charging_efficiency": "usable battery energy / recharge energy (computed here)",
            "constant_65_mph_dc_wh_per_mi": "DC energy per mile in the constant-speed phases "
            "of the Multi-Cycle Test, driven at 65 mph (40 CFR 600.116-12(a)(5))",
        },
        "conversions": "1 mi = 1.609344 km (exact)",
        "vehicles": out,
    }
    # LF on every system, so that the file is byte-identical wherever the tool runs.
    OUTPUT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"\nall checks passed; wrote {OUTPUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--download", action="store_true", help="fetch missing reports first")
    sys.exit(main(download=parser.parse_args().download))
