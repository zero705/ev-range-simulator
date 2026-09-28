"""Summarise official EU WLTP values for one vehicle variant.

Source: European Environment Agency, "Monitoring of CO2 emissions from passenger cars"
(Regulation (EU) 2019/631), queried through the public DiscoData SQL service:
https://discodata.eea.europa.eu/
(table [CO2Emission].[latest].[co2cars_2024Fv30] holds the 2024 final data)

Field definitions, from the EEA's table definition attached to the dataset's metadata record
https://sdi.eea.europa.eu/catalogue/api/records/5018ec17-2348-4c92-8761-6f2377bbd1c0/attachments/Table-definition-cars-2024-Final.xlsx
    M (kg)     "Mass in running order Completed/complete vehicle"
    Mt         "WLTP test mass"
    Z (Wh/km)  "Electric energy consumption"
    Zr         "Electric range"
    R          "Total new registrations" (the registrations the row stands for)
    Ep (KW)    "Engine power"

Each registered car carries its own WLTP values: under the WLTP interpolation method a car's
mass and consumption depend on its options (wheels, packs). The script therefore reports the
most common value set and the 5th-95th percentile range, weighted by registrations, which
also keeps obvious reporting errors out of the range.

The filter is SQL written by whoever runs the script, and it is sent to the EEA's public,
read-only DiscoData service, which decides what it executes; nothing runs locally.

Usage:
    python tools/eea_query.py "Mk LIKE 'TESLA%' AND Cn LIKE '%MODEL 3%' AND Va = 'H6LR'"
"""

from __future__ import annotations

import json
import sys
import urllib.parse
from typing import Any

from downloads import download

ENDPOINT = "https://discodata.eea.europa.eu/sql"
TABLE = "[CO2Emission].[latest].[co2cars_2024Fv30]"


def sql(query: str, hits: int = 5000) -> list[dict[str, Any]]:
    parameters = urllib.parse.urlencode(
        {"query": " ".join(query.split()), "p": 1, "nrOfHits": hits}
    )
    payload = json.loads(download(f"{ENDPOINT}?{parameters}", accept="application/json"))
    if "errors" in payload:
        raise SystemExit(f"EEA query failed: {payload['errors']}")
    return list(payload["results"])


def weighted_percentile(pairs: list[tuple[float, int]], share: float) -> float:
    ordered = sorted(pairs)
    total = sum(weight for _, weight in ordered)
    running = 0
    for value, weight in ordered:
        running += weight
        if running >= share * total:
            return value
    return ordered[-1][0]


def summarise(where: str) -> dict[str, Any]:
    # The filter is the operator's own SQL for the remote read-only service (see above).
    rows = sql(
        f"""
        SELECT [M (kg)] AS M, Mt, [Z (Wh/km)] AS Z, Zr, SUM(R) AS n
        FROM {TABLE}
        WHERE {where}
        GROUP BY [M (kg)], Mt, [Z (Wh/km)], Zr
        """  # noqa: S608
    )
    total = sum(int(r["n"]) for r in rows)
    complete = [r for r in rows if None not in (r["M"], r["Mt"], r["Z"], r["Zr"])]
    covered = sum(int(r["n"]) for r in complete)
    mode = max(complete, key=lambda r: int(r["n"]))
    summary: dict[str, Any] = {
        "filter": where,
        "table": TABLE,
        "registrations": total,
        "registrations_with_all_fields": covered,
        "mode": {k: mode[k] for k in ("M", "Mt", "Z", "Zr")},
        "mode_registrations": mode["n"],
    }
    for field in ("M", "Mt", "Z", "Zr"):
        pairs = [(float(r[field]), int(r["n"])) for r in complete]
        summary[f"{field}_p05"] = weighted_percentile(pairs, 0.05)
        summary[f"{field}_p95"] = weighted_percentile(pairs, 0.95)

    # Motor power is summarised on its own: member states do not all report the same value
    # for the same variant, and grouping it with the other fields would split otherwise
    # identical records.
    power = sql(
        f"""
        SELECT [Ep (KW)] AS Ep, SUM(R) AS n
        FROM {TABLE}
        WHERE {where}
        GROUP BY [Ep (KW)]
        """  # noqa: S608
    )
    reported = [r for r in power if r["Ep"] is not None]
    top = max(reported, key=lambda r: int(r["n"]))
    summary["Ep_mode_kw"] = top["Ep"]
    summary["Ep_mode_share"] = round(int(top["n"]) / sum(int(r["n"]) for r in reported), 4)
    return summary


if __name__ == "__main__":
    print(json.dumps(summarise(sys.argv[1]), indent=2))
