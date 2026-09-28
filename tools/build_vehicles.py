"""Assemble data/vehicles.json from the outputs of eea_query.py and epa_roadload.py.

Numbers are never typed by hand: every value in the output file is copied programmatically
from a query result, so the file can be rebuilt and diffed at any time.

Usage:
    python tools/build_vehicles.py <folder with eea_*.json and epa_*.json> data/vehicles.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

EEA_SOURCE = {
    "publisher": "European Environment Agency",
    "dataset": "Monitoring of CO2 emissions from passenger cars, 2024 final data "
    "(Regulation (EU) 2019/631)",
    "access": "https://discodata.eea.europa.eu/ table [CO2Emission].[latest].[co2cars_2024Fv30]",
    "doi": "https://doi.org/10.2909/5018ec17-2348-4c92-8761-6f2377bbd1c0",
    "licence": "CC BY 4.0; copyright holder: Directorate-General for Climate Action (DG CLIMA)",
    "field_definitions": "EEA table definition: M = mass in running order, Mt = WLTP test mass, "
    "Z = electric energy consumption (Wh/km), Zr = electric range (km), R = registrations",
    "tool": "tools/eea_query.py",
}

EPA_FILES = {
    "24-testcar-2025-05.xlsx": {
        "url": "https://www.epa.gov/system/files/documents/2025-05/24-testcar-2025-05.xlsx",
        "sha256": "e3a5378fa5e6820861d705e36fd2f2046234be8d050026bcfde29f0b8e63a6f9",
    },
    "25-testcar-2026-01-21.xlsx": {
        "url": "https://www.epa.gov/system/files/documents/2026-01/25-testcar-2026-01-21.xlsx",
        "sha256": "f131cbb353d0737874e9d61215ba8055b47e4df845f34072bf77faaf780e9dbc",
    },
}

VEHICLES: list[dict[str, Any]] = [
    {
        "id": "tesla-model3-rwd",
        "name": "Tesla Model 3 RWD",
        "eea": "tesla",
        "epa": ("epa_tesla", "Model 3 RWD", "24-testcar-2025-05.xlsx"),
        "eu_variant": "type 003, variant H6LR (2024 registrations)",
        "notes": [
            "Tesla declares a single WLTP value for the whole variant: 45,736 of the 45,809 "
            "complete records carry exactly the same mass, consumption and range.",
            "EPA lists the drive system of this record as '4-Wheel Drive'; the model name and the "
            "test vehicle ID (3R1..) identify the single-motor rear-wheel-drive car. The drive "
            "field is not used anywhere in the model.",
        ],
    },
    {
        "id": "volvo-ex30-sm-er",
        "name": "Volvo EX30 Single Motor Extended Range",
        "eea": "ex30",
        "epa": ("epa_ex30", "EX30 Single Motor extended range", "25-testcar-2026-01-21.xlsx"),
        "eu_variant": "type 2, variant 2ZEL (2024 registrations)",
        "notes": [
            "EPA also lists an 18-inch-wheel version of the same test vehicle, with a higher "
            "constant and quadratic term (A = 33.96 lbf, C = 0.02022 lbf/mph^2). The record for "
            "the 19- and 20-inch wheels is used; the other serves as a check.",
            "EPA lists the drive system as 'All Wheel Drive'; the model name states a single "
            "motor. The drive field is not used anywhere in the model.",
        ],
    },
    {
        "id": "polestar-2-lr-sm",
        "name": "Polestar 2 Long Range Single Motor",
        "eea": "polestar",
        "epa": (
            "epa_polestar",
            "Polestar 2 Single Motor (19 Inch Wheels)",
            "25-testcar-2026-01-21.xlsx",
        ),
        "eu_variant": "type V, variant VSFE (2024 registrations)",
        "notes": [
            "EPA also lists a 20-inch-wheel version (A = 39.23 lbf, same B and C). The 19-inch "
            "record is used; the other serves as a check.",
            "EPA lists the drive system as 'All Wheel Drive'; the model name states a single "
            "motor. The drive field is not used anywhere in the model.",
        ],
    },
    {
        "id": "vw-id4-pro",
        "name": "Volkswagen ID.4 Pro (210 kW, RWD)",
        "eea": "id4",
        "epa": ("epa_id4", "ID.4 Pro", "24-testcar-2025-05.xlsx"),
        "eu_variant": "type E2, variant 4ACEDFAD7PX2, 'ID.4 PRO 210KW' without 4MOTION "
        "(2024 registrations)",
        "notes": [],
    },
]

CANDIDATE_WITHOUT_ROAD_LOAD: dict[str, Any] = {
    "id": "vw-id3-pro",
    "name": "Volkswagen ID.3 Pro (150 kW)",
    "eea": "id3",
    "eu_variant": "type E1, variant ACEBJCL1FX2, version C051AA (2024 registrations)",
    "status": "not used: the ID.3 is not sold in the United States, so no measured road load "
    "exists in the EPA data. Kept here only to document the decision.",
}


def load(folder: Path, name: str) -> Any:
    return json.loads((folder / f"{name}.json").read_text(encoding="utf-8"))


def eu_block(summary: dict[str, Any], variant: str) -> dict[str, Any]:
    def spread(field: str) -> dict[str, Any]:
        mode = summary["mode"]
        if not isinstance(mode, dict):
            raise TypeError("the EEA summary has no 'mode' record")
        return {
            "mode": mode[field],
            "p05": summary[f"{field}_p05"],
            "p95": summary[f"{field}_p95"],
        }

    return {
        "variant": variant,
        "query": summary["filter"],
        "registrations": summary["registrations"],
        "registrations_with_all_fields": summary["registrations_with_all_fields"],
        "registrations_with_mode_values": summary["mode_registrations"],
        "mass_in_running_order_kg": spread("M"),
        "wltp_test_mass_kg": spread("Mt"),
        "energy_consumption_wh_per_km": spread("Z"),
        "electric_range_km": spread("Zr"),
        "motor_power_kw": {
            "mode": summary["Ep_mode_kw"],
            "share_of_registrations_reporting_power": summary["Ep_mode_share"],
        },
    }


def us_block(rows: list[dict[str, Any]], model: str, file: str) -> dict[str, Any]:
    record = next(r for r in rows if r["model"] == model)
    return {
        "file": file,
        "url": EPA_FILES[file]["url"],
        "sha256": EPA_FILES[file]["sha256"],
        "model_year": record["model_year"],
        "model": record["model"],
        "test_vehicle_id": record["test_vehicle_id"],
        "target_coefficients": {
            "A_lbf": record["target_A_lbf"],
            "B_lbf_per_mph": record["target_B_lbf_per_mph"],
            "C_lbf_per_mph2": record["target_C_lbf_per_mph2"],
        },
        "equivalent_test_weight_lb": record["equivalent_test_weight_lb"],
        "si": {
            "F0_N": round(float(record["F0_N"]), 4),
            "F1_N_per_m_per_s": round(float(record["F1_N_per_mps"]), 5),
            "F2_N_per_m2_per_s2": round(float(record["F2_N_per_mps2"]), 6),
            "equivalent_test_weight_kg": round(float(record["equivalent_test_weight_kg"]), 2),
        },
    }


def build(folder: Path) -> dict[str, Any]:
    vehicles = []
    for spec in VEHICLES:
        epa_name, model, file = spec["epa"]
        entry: dict[str, Any] = {
            "id": spec["id"],
            "name": spec["name"],
            "eu_wltp": eu_block(load(folder, spec["eea"]), spec["eu_variant"]),
            "us_road_load": us_block(load(folder, epa_name), model, file),
        }
        entry["notes"] = spec["notes"]
        vehicles.append(entry)

    candidate = dict(CANDIDATE_WITHOUT_ROAD_LOAD)
    candidate["eu_wltp"] = eu_block(load(folder, candidate.pop("eea")), candidate.pop("eu_variant"))

    return {
        "about": "Official regulatory data for the EV range simulator: EU WLTP registrations and "
        "US EPA measured road load. Manufacturer figures are kept separately in "
        "data/manufacturer_facts.json. See docs/data-sources.md.",
        "sources": {
            "eu_wltp": EEA_SOURCE,
            "us_road_load": {
                "publisher": "US Environmental Protection Agency",
                "dataset": "Test Car List Data Files",
                "page": "https://www.epa.gov/compliance-and-fuel-economy-data/"
                "data-cars-used-testing-fuel-economy",
                "reference_conditions": "20 C, 98.21 kPa, no wind (40 CFR 1066.305)",
                "conversions": "1 lbf = 4.4482216152605 N, 1 mph = 0.44704 m/s, "
                "1 lb = 0.45359237 kg (exact; NIST SP 811)",
                "tool": "tools/epa_roadload.py",
            },
        },
        "vehicles": vehicles,
        "considered_but_not_used": [candidate],
    }


if __name__ == "__main__":
    result = build(Path(sys.argv[1]))
    # LF line endings on every system, so that a rebuild is byte-identical wherever it runs.
    Path(sys.argv[2]).write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"wrote {sys.argv[2]}: {len(result['vehicles'])} vehicles")
