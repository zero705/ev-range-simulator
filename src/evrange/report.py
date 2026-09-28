"""Markdown tables of the results, for docs/method.md and README.md.

The documents carry these tables between marker comments. tools/update_docs.py rewrites
them and tests/test_report.py fails if a document no longer matches the model, so no number
in the documentation can drift from what the code computes.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from evrange.study import Conditions, Study
from evrange.validation import (
    Comparison,
    epa_comparisons,
    eu_comparisons,
    implied_eu_charging_efficiency,
    sensitivities,
)

SHORT_NAMES = {
    "tesla-model3-rwd": "Tesla Model 3 RWD",
    "volvo-ex30-sm-er": "Volvo EX30",
    "polestar-2-lr-sm": "Polestar 2",
    "vw-id4-pro": "VW ID.4 Pro",
}


def short_name(vehicle_id: str) -> str:
    return SHORT_NAMES.get(vehicle_id, vehicle_id)


def signed(value: float, digits: int = 1) -> str:
    """A signed number for tables and charts; a value that rounds to zero has no sign."""
    text = f"{value:+.{digits}f}"
    return f"{0:.{digits}f}" if float(text) == 0 else text


def calibration_table(study: Study) -> str:
    lines = [
        "| Car | Drivetrain efficiency | Regeneration coefficient | Charging efficiency |",
        "|---|---|---|---|",
    ]
    for vehicle in study.vehicles:
        c = study.calibrations[vehicle.id]
        lines.append(
            f"| {short_name(vehicle.id)} | {c.drive_efficiency:.3f} | "
            f"{c.regen_coefficient:.3f} | {c.charging_efficiency:.3f} |"
        )
    return "\n".join(lines)


def eu_table(study: Study) -> str:
    rows = {(c.vehicle_id, c.check): c for c in eu_comparisons(study)}
    lines = [
        "| Car | Consumption, model (Wh/km) | Official | Difference | Range, model (km) | "
        "Official | Difference |",
        "|---|---|---|---|---|---|---|",
    ]
    for vehicle in study.vehicles:
        z = rows[(vehicle.id, "EU WLTP consumption from the mains")]
        r = rows[(vehicle.id, "EU WLTP range")]
        lines.append(
            f"| {short_name(vehicle.id)} | {z.model:.1f} | {_official(z, 0)} | "
            f"{signed(z.error_pct)} % | {r.model:.0f} | {_official(r, 0)} | "
            f"{signed(r.error_pct)} % |"
        )
    return "\n".join(lines)


def _official(row: Comparison, digits: int) -> str:
    text = f"{row.measured:.{digits}f}"
    if row.low is not None and row.high is not None and row.low != row.high:
        text += f" ({row.low:.{digits}f}-{row.high:.{digits}f})"
    return text


def epa_table(study: Study) -> str:
    lines = [
        "| Car | Measurement | Model (Wh/km) | Measured (Wh/km) | Difference |",
        "|---|---|---|---|---|",
    ]
    for c in epa_comparisons(study):
        check = c.check.removeprefix("EPA ")
        lines.append(
            f"| {short_name(c.vehicle_id)} | {check} | {c.model:.1f} | {c.measured:.1f} | "
            f"{signed(c.error_pct)} % |"
        )
    return "\n".join(lines)


def charging_table(study: Study) -> str:
    lines = [
        "| Car | EPA, measured | Implied by the EU values |",
        "|---|---|---|",
    ]
    for vehicle in study.vehicles:
        lines.append(
            f"| {short_name(vehicle.id)} | {vehicle.epa.charging_efficiency:.3f} | "
            f"{implied_eu_charging_efficiency(vehicle):.3f} |"
        )
    return "\n".join(lines)


def sensitivity_table(study: Study) -> str:
    ids = [v.id for v in study.vehicles]
    header = " | ".join(short_name(i) for i in ids)
    lines = [f"| Change | {header} |", "|---" * (len(ids) + 1) + "|"]
    for row in sensitivities(study):
        cells = " | ".join(
            f"{signed(row.consumption_pp[i])} / {signed(row.range_pp[i])}" for i in ids
        )
        lines.append(f"| {row.name} | {cells} |")
    return "\n".join(lines)


def summary_table(study: Study) -> str:
    """The README table: EU official values, the model, and the EPA checks per car."""
    eu = {(c.vehicle_id, c.check): c for c in eu_comparisons(study)}
    epa: dict[str, list[float]] = {}
    for c in epa_comparisons(study):
        epa.setdefault(c.vehicle_id, []).append(abs(c.error_pct))
    lines = [
        "| Car | WLTP consumption, official / model | WLTP range, official / model | "
        "Unused EPA tests, largest difference |",
        "|---|---|---|---|",
    ]
    for vehicle in study.vehicles:
        z = eu[(vehicle.id, "EU WLTP consumption from the mains")]
        r = eu[(vehicle.id, "EU WLTP range")]
        checks = epa.get(vehicle.id)
        epa_text = f"{max(checks):.1f} % ({len(checks)} tests)" if checks else "none"
        lines.append(
            f"| {short_name(vehicle.id)} | {z.measured:.0f} / {z.model:.0f} Wh/km "
            f"({signed(z.error_pct)} %) | {r.measured:.0f} / {r.model:.0f} km "
            f"({signed(r.error_pct)} %) | {epa_text} |"
        )
    return "\n".join(lines)


def accuracy_table(study: Study) -> str:
    """How far the model is from the official measurements it was not fitted to."""
    epa, eu = epa_comparisons(study), eu_comparisons(study)
    groups = [
        ("EPA tests the identification did not use", epa),
        ("EU WLTP consumption and range", eu),
        ("All of them", epa + eu),
    ]
    lines = [
        "| Compared with | Values | Mean difference | Largest difference | Within 3 % |",
        "|---|---|---|---|---|",
    ]
    for name, rows in groups:
        if not rows:
            continue
        differences = [abs(r.error_pct) for r in rows]
        lines.append(
            f"| {name} | {len(rows)} | {sum(differences) / len(rows):.1f} % | "
            f"{max(differences):.1f} % | {sum(d <= 3 for d in differences)} of {len(rows)} |"
        )
    return "\n".join(lines)


RANGE_DRIVES = (
    ("WLTC", "wltc"),
    ("UDDS (city)", "udds"),
    ("HWFET (highway)", "hwfet"),
    ("100 km/h", 100.0),
    ("130 km/h", 130.0),
)


def ranges_table(study: Study) -> str:
    """Modelled range of each car on each drive, climate control off."""
    header = " | ".join(name for name, _ in RANGE_DRIVES)
    lines = [f"| Car | {header} |", "|---" * (len(RANGE_DRIVES) + 1) + "|"]
    for vehicle in study.vehicles:
        cells = []
        for _, drive in RANGE_DRIVES:
            use = (
                study.on_cycle(vehicle.id, drive)
                if isinstance(drive, str)
                else study.at_speed(vehicle.id, drive)
            )
            cells.append(f"{study.range_km(vehicle.id, use):.0f}")
        lines.append(f"| {short_name(vehicle.id)} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


AGREEMENT_PCT = 3.0
METHOD_CHARGING = "docs/method.md#53-what-the-eu-figures-imply-about-charging"


def _joined(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def findings(study: Study) -> str:
    """The README's findings, as a list whose every number is computed."""
    epa = epa_comparisons(study)
    eu = {(c.vehicle_id, c.unit): c for c in eu_comparisons(study)}
    agree: list[tuple[str, Comparison, Comparison]] = []
    differ: list[tuple[str, Comparison, Comparison]] = []
    for vehicle in study.vehicles:
        z, r = eu[(vehicle.id, "Wh/km")], eu[(vehicle.id, "km")]
        largest = max(abs(z.error_pct), abs(r.error_pct))
        (agree if largest < AGREEMENT_PCT else differ).append((vehicle.id, z, r))
    lines = ["- Each car's model is identified from its two US certification cycles alone."]
    if epa:
        checked = [
            short_name(v.id) for v in study.vehicles if any(c.vehicle_id == v.id for c in epa)
        ]
        worst = max(abs(c.error_pct) for c in epa)
        lines[0] += (
            f" The EPA reports of the {_joined(checked)} contain {len(epa)} further measurements "
            "(other wheels, a steady 65 mph); the largest difference between model and "
            f"measurement is {worst:.1f} %."
        )
    else:
        lines[0] += " The EPA reports contain no further measurements to check it against."
    if agree:
        lines.append(
            f"- For the {_joined([short_name(v) for v, _, _ in agree])} the model matches the "
            f"EU official consumption and range within {AGREEMENT_PCT:.0f} %."
        )
    if differ:
        parts = "; ".join(
            f"{short_name(v)}: consumption {signed(z.error_pct)} %, range {signed(r.error_pct)} %"
            for v, z, r in differ
        )
        lines.append(
            f"- For the other cars the two EU comparisons disagree with each other ({parts}). "
            "Both start from the same modelled battery consumption and differ only in the "
            "charging efficiency and usable battery energy carried over from the US tests, so "
            "what separates them lies there; the EU figures imply other values than the EPA "
            f"measured ([method, section 5.3]({METHOD_CHARGING})). The gaps are reported, not "
            "tuned away."
        )
    return "\n".join(lines)


def example(study: Study) -> str:
    """A short Python session with the output it really prints."""
    car = "tesla-model3-rwd"
    wltc = study.on_cycle(car, "wltc")
    winter = study.at_speed(car, 130, Conditions(extra_mass_kg=150, climate_w=2000))
    return "\n".join(
        [
            "```python",
            "from evrange import Conditions, load_study",
            "",
            "study = load_study()",
            f'wltc = study.on_cycle("{car}", "wltc")',
            f'print(round(wltc.battery_wh_per_km, 1), round(study.range_km("{car}", wltc)))',
            f"# {wltc.battery_wh_per_km:.1f} {study.range_km(car, wltc):.0f}",
            "",
            "# 130 km/h with 150 kg on board and 2 kW of heating",
            f'winter = study.at_speed("{car}", 130, Conditions(extra_mass_kg=150, climate_w=2000))',
            f'print(round(study.range_km("{car}", winter)))',
            f"# {study.range_km(car, winter):.0f}",
            "```",
        ]
    )


BLOCKS: dict[str, Callable[[Study], str]] = {
    "calibration": calibration_table,
    "eu": eu_table,
    "epa": epa_table,
    "charging": charging_table,
    "sensitivity": sensitivity_table,
    "summary": summary_table,
    "findings": findings,
    "accuracy": accuracy_table,
    "ranges": ranges_table,
    "example": example,
}

_OPEN = "<!-- generated: "
_CLOSE = "<!-- end generated -->"
# A block may be empty, and its body may not contain another marker, so a missing end marker
# can never make one block swallow the text up to the next block's end.
_BLOCK = re.compile(
    r"<!-- generated: (?P<name>[a-z]+) -->\n"
    r"(?P<body>(?:(?!<!-- (?:end )?generated).)*?)"
    r"<!-- end generated -->",
    re.DOTALL,
)


def _matches(text: str) -> list[re.Match[str]]:
    matches = list(_BLOCK.finditer(text))
    if not len(matches) == text.count(_OPEN) == text.count(_CLOSE):
        raise ValueError("generated-block markers are unbalanced")
    return matches


def blocks_in(text: str) -> dict[str, str]:
    """The generated blocks a document contains, by name."""
    return {m.group("name"): m.group("body").removesuffix("\n") for m in _matches(text)}


def refresh(text: str, study: Study) -> str:
    """Rewrite every generated block of a document from the model."""
    for match in _matches(text):
        if match.group("name") not in BLOCKS:
            raise KeyError(f"unknown generated block {match.group('name')!r}")

    def replace(match: re.Match[str]) -> str:
        name = match.group("name")
        return f"{_OPEN}{name} -->\n{BLOCKS[name](study)}\n{_CLOSE}"

    return _BLOCK.sub(replace, text)
