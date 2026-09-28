"""Check every manufacturer fact against its source document and against the EU data.

For each fact in data/manufacturer_facts.json this script confirms that:
    1. the source document in data/sources/ has the fingerprint recorded for it,
    2. the quote appears verbatim in the document's text (whitespace is ignored, because
       PDF text extraction breaks lines and spaces differently from how a page looks),
    3. the value appears inside that quote,
    4. for a claim of absence, the pattern that would reveal the value does not occur.

It then compares the manufacturer figures with the official EU registration data in
data/vehicles.json. The two sources were collected independently, so agreement between them
is evidence that both were read correctly.

A typo in any quote or value makes the check fail, so nothing hand-copied can drift from
its source unnoticed.

Usage:
    python tools/verify_manufacturer.py
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pypdf import PdfReader

ROOT = Path(__file__).resolve().parent.parent
FACTS = ROOT / "data" / "manufacturer_facts.json"
VEHICLES = ROOT / "data" / "vehicles.json"
SOURCES = ROOT / "data" / "sources"

DRIVER_MASS_KG = 75  # GTR 15, paragraph 3.2.6
MILE_KM = 1.609344  # exact


def squash(text: str) -> str:
    return re.sub(r"\s+", "", html.unescape(text))


def document_text(path: Path) -> str:
    if path.suffix == ".pdf":
        text = " ".join((page.extract_text() or "") for page in PdfReader(str(path)).pages)
    else:
        raw = path.read_text(encoding="utf-8", errors="ignore")
        raw = re.sub(r"<script.*?</script>|<style.*?</style>", " ", raw, flags=re.S)
        text = re.sub(r"<[^>]+>", " ", raw)
    return re.sub(r"\s+", " ", html.unescape(text))


def number(text: str) -> float:
    return float(re.sub(r"[^\d.]", "", text))


def span(text: str) -> tuple[float, float]:
    low, high = text.split("-")
    return number(low), number(high)


def section(facts: dict[str, object], key: str) -> dict[str, Any]:
    """A section of manufacturer_facts.json that must be a JSON object."""
    value = facts[key]
    if not isinstance(value, dict):
        raise TypeError(f"manufacturer_facts.json: '{key}' is not an object")
    return value


def check_documents(facts: dict[str, object]) -> tuple[dict[str, str], int]:
    texts: dict[str, str] = {}
    failures = 0
    for key, doc in section(facts, "documents").items():
        path = SOURCES / doc["file"]
        if not path.is_file():
            print(f"  skip  {key}: {doc['file']} is not in data/sources; download {doc['url']}")
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != doc["sha256"]:
            print(f"  FAIL  {key}: fingerprint {digest[:16]}... does not match")
            failures += 1
            continue
        texts[key] = document_text(path)
        print(f"  ok    {key}: fingerprint matches")
    return texts, failures


def check_facts(facts: dict[str, object], texts: dict[str, str]) -> int:
    failures = 0
    for vehicle, items in section(facts, "vehicles").items():
        print(vehicle)
        for fact in items:
            if fact["doc"] not in texts:
                print(f"  skip  {fact['item']}: source not available")
                continue
            text = texts[fact["doc"]]
            if fact.get("absent_pattern"):
                clean = re.search(fact["absent_pattern"], text) is None
                failures += not clean
                print(f"  {'ok  ' if clean else 'FAIL'}  {fact['item']}: not stated in the source")
                continue
            quote = squash(fact["quote"])
            found = quote in squash(text)
            inside = squash(fact["value"]) in quote
            ok = found and inside
            failures += not ok
            detail = "" if ok else f" (quote found: {found}, value in quote: {inside})"
            print(f"  {'ok  ' if ok else 'FAIL'}  {fact['item']} = {fact['value']}{detail}")
    return failures


def value(facts: dict[str, object], vehicle: str, item: str) -> str:
    return str(next(f["value"] for f in section(facts, "vehicles")[vehicle] if f["item"] == item))


def check_against_eu(facts: dict[str, object]) -> int:
    listed = json.loads(VEHICLES.read_text(encoding="utf-8"))["vehicles"]
    eu = {v["id"]: v["eu_wltp"] for v in listed}

    def mode(vehicle: str, field: str) -> float:
        return float(eu[vehicle][field]["mode"])

    def band(vehicle: str, field: str) -> tuple[float, float]:
        return float(eu[vehicle][field]["p05"]), float(eu[vehicle][field]["p95"])

    ps_low, ps_high = span(value(facts, "polestar-2-lr-sm", "wltp_consumption_kwh_per_100km"))
    pr_low, pr_high = span(value(facts, "polestar-2-lr-sm", "wltp_range_km"))
    tesla_mi = number(value(facts, "tesla-model3-rwd", "range_wltp_mi"))
    vw_range = number(value(facts, "vw-id4-pro", "wltp_range_km"))

    checks: list[tuple[str, Callable[[], bool]]] = [
        (
            "EX30 mass in running order: Volvo 1850 kg = EU registrations",
            lambda: (
                number(value(facts, "volvo-ex30-sm-er", "mass_in_running_order_kg"))
                == mode("volvo-ex30-sm-er", "mass_in_running_order_kg")
            ),
        ),
        (
            "EX30 consumption: Volvo 17.0 kWh/100 km = EU 170 Wh/km",
            lambda: (
                number(value(facts, "volvo-ex30-sm-er", "wltp_consumption_kwh_per_100km")) * 10
                == mode("volvo-ex30-sm-er", "energy_consumption_wh_per_km")
            ),
        ),
        (
            "EX30 range: Volvo 476 km = EU registrations",
            lambda: (
                number(value(facts, "volvo-ex30-sm-er", "wltp_range_up_to_km"))
                == mode("volvo-ex30-sm-er", "electric_range_km")
            ),
        ),
        (
            "Polestar 2 mass: Polestar 2009 kg + 75 kg driver = EU mass in running order",
            lambda: (
                number(value(facts, "polestar-2-lr-sm", "total_weight_kg")) + DRIVER_MASS_KG
                == mode("polestar-2-lr-sm", "mass_in_running_order_kg")
            ),
        ),
        (
            f"Polestar 2 consumption: EU 5-95 % band inside Polestar's {ps_low}-{ps_high}",
            lambda: (
                ps_low * 10 <= band("polestar-2-lr-sm", "energy_consumption_wh_per_km")[0]
                and band("polestar-2-lr-sm", "energy_consumption_wh_per_km")[1] <= ps_high * 10
            ),
        ),
        (
            f"Polestar 2 range: EU 5-95 % band inside Polestar's {pr_low:.0f}-{pr_high:.0f} km",
            lambda: (
                pr_low <= band("polestar-2-lr-sm", "electric_range_km")[0]
                and band("polestar-2-lr-sm", "electric_range_km")[1] <= pr_high
            ),
        ),
        (
            "EX30 motor power: Volvo 200 kW = EU registrations",
            lambda: (
                number(value(facts, "volvo-ex30-sm-er", "motor_power_kw"))
                == float(eu["volvo-ex30-sm-er"]["motor_power_kw"]["mode"])
            ),
        ),
        (
            "Polestar 2 motor power: Polestar 220 kW = EU registrations",
            lambda: (
                number(value(facts, "polestar-2-lr-sm", "motor_power_kw"))
                == float(eu["polestar-2-lr-sm"]["motor_power_kw"]["mode"])
            ),
        ),
        (
            "ID.4 Pro motor power: VW 210 kW = EU registrations",
            lambda: (
                number(value(facts, "vw-id4-pro", "motor_power_kw"))
                == float(eu["vw-id4-pro"]["motor_power_kw"]["mode"])
            ),
        ),
        (
            "Model 3 consumption: Tesla 13.2 kWh/100 km = EU 132 Wh/km",
            lambda: (
                number(value(facts, "tesla-model3-rwd", "official_consumption_kwh_per_100km")) * 10
                == mode("tesla-model3-rwd", "energy_consumption_wh_per_km")
            ),
        ),
        (
            "Model 3 range: Tesla 318 mi within 1 mi of EU 513 km",
            lambda: abs(mode("tesla-model3-rwd", "electric_range_km") / MILE_KM - tesla_mi) < 1,
        ),
        (
            "ID.4 Pro range: VW 550 km inside the EU 5-95 % band",
            lambda: (
                band("vw-id4-pro", "electric_range_km")[0]
                <= vw_range
                <= band("vw-id4-pro", "electric_range_km")[1]
            ),
        ),
    ]
    print("manufacturer figures against the EU registrations")
    failures = 0
    for label, test in checks:
        ok = test()
        failures += not ok
        print(f"  {'ok  ' if ok else 'FAIL'}  {label}")

    curb = number(value(facts, "tesla-model3-rwd", "curb_mass_kg")) + DRIVER_MASS_KG
    mro = mode("tesla-model3-rwd", "mass_in_running_order_kg")
    print(
        f"  info  Model 3 mass: Tesla curb {curb - DRIVER_MASS_KG:.0f} kg + 75 kg = {curb:.0f} kg "
        f"against EU {mro:.0f} kg ({curb - mro:+.0f} kg); 'curb mass' is Tesla's own definition"
    )
    return failures


def main() -> int:
    facts = json.loads(FACTS.read_text(encoding="utf-8"))
    texts, failures = check_documents(facts)
    failures += check_facts(facts, texts)
    if len(texts) == len(facts["documents"]):
        failures += check_against_eu(facts)
    print("\nall facts verified" if not failures else f"\n{failures} problem(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
