"""Extract measured road-load coefficients from the EPA Test Car List.

Source: US EPA, "Data on Cars used for Testing Fuel Economy"
https://www.epa.gov/compliance-and-fuel-economy-data/data-cars-used-testing-fuel-economy

The target coefficients A, B, C describe the road-load force F = A + B*v + C*v^2 measured by
coastdown on the road and corrected to reference conditions of 20 C, 98.21 kPa and no wind
(40 CFR 1066.305). Their units are part of the column names (lbf, lbf/mph, lbf/mph**2).

Conversions use exact definitions (NIST SP 811, Appendix B and footnotes):
    1 lbf = 4.448 221 615 260 5 N   (with standard gravity 9.806 65 m/s^2)
    1 mph = 0.447 04 m/s
    1 lb  = 0.453 592 37 kg

Only a file whose SHA-256 fingerprint is recorded in tools/build_vehicles.py (EPA_FILES) is
read, and only with defusedxml installed, which makes openpyxl parse the file safely.

Usage:
    python tools/epa_roadload.py data/sources/24-testcar-2025-05.xlsx 3R124-649670
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import openpyxl
import openpyxl.xml
from build_vehicles import EPA_FILES

LBF_TO_N = 4.4482216152605
MPH_TO_MS = 0.44704
LB_TO_KG = 0.45359237


def number(value: object) -> float:
    """A numeric spreadsheet cell as a float; anything else is an error, not a guess."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"expected a number in the EPA file, found {value!r}")
    return float(value)


def verified(path: Path) -> Path:
    """The path of an EPA file with its recorded fingerprint, safe to parse; else an error."""
    if not openpyxl.xml.DEFUSEDXML:
        raise RuntimeError("install defusedxml (pip install -e '.[tools]') to parse spreadsheets")
    recorded = EPA_FILES.get(path.name)
    if recorded is None:
        raise ValueError(f"{path.name} has no recorded fingerprint; add it to EPA_FILES first")
    if hashlib.sha256(path.read_bytes()).hexdigest() != recorded["sha256"]:
        raise ValueError(f"{path.name} does not match its recorded fingerprint")
    return path


def find(path: Path, vehicle_id: str) -> list[dict[str, Any]]:
    book = openpyxl.load_workbook(verified(path), read_only=True, data_only=True)
    rows = book.worksheets[0].iter_rows(values_only=True)
    header = [str(h).strip() if h is not None else "" for h in next(rows)]
    found = []
    for values in rows:
        record = dict(zip(header, values, strict=False))
        if str(record["Test Vehicle ID"]) != vehicle_id:
            continue
        a = number(record["Target Coef A (lbf)"])
        b = number(record["Target Coef B (lbf/mph)"])
        c = number(record["Target Coef C (lbf/mph**2)"])
        etw = number(record["Equivalent Test Weight (lbs.)"])
        found.append(
            {
                "model_year": record["Model Year"],
                "model": record["Represented Test Veh Model"],
                "test_vehicle_id": vehicle_id,
                "test_procedure": record["Test Procedure Description"],
                "target_A_lbf": a,
                "target_B_lbf_per_mph": b,
                "target_C_lbf_per_mph2": c,
                "equivalent_test_weight_lb": etw,
                "F0_N": a * LBF_TO_N,
                "F1_N_per_mps": b * LBF_TO_N / MPH_TO_MS,
                "F2_N_per_mps2": c * LBF_TO_N / MPH_TO_MS**2,
                "equivalent_test_weight_kg": etw * LB_TO_KG,
            }
        )
    return found


if __name__ == "__main__":
    print(json.dumps(find(Path(sys.argv[1]), sys.argv[2]), indent=2, default=str))
