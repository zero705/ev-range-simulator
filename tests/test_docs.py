"""Every number the documents state outside the generated tables is what the data and model give.

The tables between marker comments are rewritten by tools/update_docs.py (tests/test_report.py).
The numbers checked here are in the prose and in the hand-laid tables of docs/data-sources.md;
if the data or the model change, these tests name the sentence that has to change with them.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

import pytest

from evrange import Study
from evrange.constants import (
    EPA_AIR_DENSITY,
    EPA_PRESSURE_PA,
    EPA_TEMPERATURE_K,
    MILE_M,
    MPH_MS,
    WLTP_AIR_DENSITY,
    WLTP_PRESSURE_PA,
    WLTP_TEMPERATURE_K,
)
from evrange.cycles import CYCLE_SPECS
from evrange.datafiles import read_json, reference_items
from evrange.physics import wheel_work
from evrange.report import signed
from evrange.validation import (
    Sensitivity,
    epa_comparisons,
    eu_comparisons,
    eu_prediction,
    implied_eu_charging_efficiency,
    sensitivities,
)

REPOSITORY = Path(__file__).resolve().parent.parent


def _text(name: str) -> str:
    """A document with its line breaks folded, so that a phrase may wrap across lines."""
    return re.sub(r"\s+", " ", (REPOSITORY / name).read_text(encoding="utf-8"))


def _rows(marker: str) -> list[str]:
    """The table rows of docs/data-sources.md that contain the marker."""
    lines = (REPOSITORY / "docs" / "data-sources.md").read_text(encoding="utf-8").splitlines()
    return [line for line in lines if line.startswith("| ") and marker in line]


def _reference(group: str, item: str) -> dict[str, Any]:
    return next(i for i in reference_items(group) if i["item"] == item)


def _percent(group: str, item: str) -> float:
    return float(str(_reference(group, item)["value"]).rstrip("%").strip())


def _certificate(vehicle_id: str) -> dict[str, Any]:
    vehicles = read_json("epa_certification.json")["vehicles"]
    return dict(next(v for v in vehicles if v["id"] == vehicle_id))


def _spread(block: dict[str, Any]) -> str:
    text = f"{block['mode']:.0f}"
    if block["p05"] != block["p95"]:
        text += f" ({block['p05']:.0f}-{block['p95']:.0f})"
    return text


def _largest(rows: list[Sensitivity]) -> float:
    return max(abs(x) for r in rows for x in (*r.consumption_pp.values(), *r.range_pp.values()))


def _cabin_celsius() -> float:
    """The cabin temperature Argonne's climate-control measurements held."""
    quote = _reference("climate_power", "hvac_definition")["quote"]
    cabin = re.search(r"(\d+)°F cabin", quote)
    assert cabin is not None
    return (float(cabin.group(1)) - 32) * 5 / 9


# docs/data-sources.md -------------------------------------------------------------------------

WLTC_PHASE_ROWS = {
    "wltc-low": "Low3",
    "wltc-medium": "Medium3-2",
    "wltc-high": "High3-2",
    "wltc-extra-high": "Extra High3",
}


def _within_half(printed: str, value: float) -> bool:
    """A figure printed rounded to the unit: within half a unit of the exact value."""
    return abs(int(printed.replace(" ", "")) - value) <= 0.5 + 1e-9


def test_drive_cycle_table(study: Study) -> None:
    whole = study.cycles["wltc"].speed_ms
    for key, name in WLTC_PHASE_ROWS.items():
        spec, cycle = CYCLE_SPECS[key], study.cycles[key]
        assert spec.end_s is not None
        inner = range(max(spec.start_s, 1), min(spec.end_s, whole.size - 2) + 1)
        accel = max((whole[i + 1] - whole[i - 1]) / 2 for i in inner)  # central difference
        [row] = _rows(f"| {name} |")
        duration, metres, top, a_max = (c.strip() for c in row.strip(" |").split("|")[1:])
        assert int(duration) == cycle.duration_s, name
        assert _within_half(metres, cycle.distance_m), name
        assert top == f"{cycle.max_speed_kmh:.1f}", name
        assert a_max == f"{accel:.2f}", name
    wltc = study.cycles["wltc"]
    assert (
        f"| **WLTC class 3b** | **{wltc.duration_s:.0f}** | **{wltc.distance_m:.0f}** | "
        f"{wltc.max_speed_kmh:.1f} | |"
    ) in _rows("WLTC class 3b** |")
    for key, name in (("udds", "UDDS"), ("hwfet", "HWFET")):
        cycle = study.cycles[key]
        [row] = _rows(f"| {name} | {cycle.duration_s:.0f} |")
        found = re.search(r"\| ([\d ]+) \(([\d.]+) mi\) \| ([\d.]+) \(([\d.]+) mph\) \|", row)
        assert found is not None, row
        metres, miles, top_kmh, top_mph = found.groups()
        assert _within_half(metres, cycle.distance_m), name
        assert miles == f"{cycle.distance_m / MILE_M:.2f}", name
        assert top_kmh == f"{cycle.max_speed_kmh:.2f}", name
        assert top_mph == f"{cycle.speed_ms.max() / MPH_MS:.1f}", name


def test_eu_values_tables() -> None:
    for entry in read_json("vehicles.json")["vehicles"]:
        eu = entry["eu_wltp"]
        cells = (
            f"| {eu['registrations']:,} | {_spread(eu['mass_in_running_order_kg'])} | "
            f"{_spread(eu['wltp_test_mass_kg'])} | "
            f"{_spread(eu['energy_consumption_wh_per_km'])} | "
            f"{_spread(eu['electric_range_km'])} |"
        )
        rows = [r for r in _rows(f"| {entry['name']} | type ") if r.endswith(cells)]
        assert len(rows) == 1, (entry["name"], cells)
        power = eu["motor_power_kw"]
        share = f"{power['share_of_registrations_reporting_power'] * 100:.1f}".removesuffix(".0")
        assert f"| {entry['name']} | {power['mode']:.0f} | {share} % |" in _rows(entry["name"])


def test_single_tesla_value_statement() -> None:
    tesla = next(v for v in read_json("vehicles.json")["vehicles"] if v["id"] == "tesla-model3-rwd")
    eu = tesla["eu_wltp"]
    assert (
        f"{eu['registrations_with_mode_values']:,} of the {eu['registrations_with_all_fields']:,} "
        "complete records carry the same mass, consumption and range"
    ) in _text("docs/data-sources.md")


def test_road_load_table(study: Study) -> None:
    for entry in read_json("vehicles.json")["vehicles"]:
        us = entry["us_road_load"]
        target = us["target_coefficients"]
        road_load = study.vehicle(entry["id"]).epa.road_load
        row = (
            f"| {entry['name']} | MY{us['model_year']} {us['model']}, {us['test_vehicle_id']} | "
            f"{target['A_lbf']} | {target['B_lbf_per_mph']} | {target['C_lbf_per_mph2']} | "
            f"{road_load.f0:.2f} | {road_load.f1:.4f} | {road_load.f2:.5f} | "
            f"{us['equivalent_test_weight_lb']:.0f} |"
        )
        assert row in _rows(entry["name"]), row


def test_physical_consistency_table(study: Study) -> None:
    # The check made before the model: the EPA road load as measured (EPA air), the WLTP test
    # mass plus the rotating mass, and the positive wheel energy on the WLTC.
    for vehicle in study.vehicles:
        setup = vehicle.wltp_setup(air_density=EPA_AIR_DENSITY)
        work = wheel_work(study.cycles["wltc"].speed_ms, setup.road_load, setup.inertial_mass_kg)
        per_km = work.positive_j / 3600 / (work.distance_m / 1000)
        official = vehicle.eu_consumption_wh_per_km.mode
        row = f"| {vehicle.name} | {per_km:.1f} | {official:.0f} | {official / per_km:.2f} |"
        assert row in _rows(vehicle.name), row


def test_certificate_table() -> None:
    text = _text("docs/data-sources.md")
    voltages = []
    for entry in read_json("epa_certification.json")["vehicles"]:
        report, recharge = entry["report"], entry["recharge"]
        usable = entry["usable_battery_energy_wh"]
        cells = (
            f"| {recharge['mains_voltage_v']:.0f} V | {recharge['energy_kwh']} | "
            f"{f'{usable:,.1f}'.removesuffix('.0')} | {entry['dc_wh_per_mi']['udds']} | "
            f"{entry['dc_wh_per_mi']['hwfet']} | {usable / (recharge['energy_kwh'] * 1000):.4f} |"
        )
        rows = _rows(f"{report['certificate']} ({report['docid']}), MY{report['model_year']}")
        assert len(rows) == 1, report["certificate"]
        assert rows[0].endswith(cells), (rows[0], cells)
        voltages.append(recharge["mains_voltage_v"])
        for other in entry["other_configurations"]:
            per_mile = other["dc_wh_per_mi"]
            assert f"{per_mile['udds']} and {per_mile['hwfet']} Wh/mi" in text, other["label"]
    assert f"The EPA recharge was made at {min(voltages):.0f}-{max(voltages):.0f} V" in text


def test_ex30_certificate_statements() -> None:
    text = _text("docs/data-sources.md")
    ex30 = _certificate("volvo-ex30-sm-er")
    wheels18 = ex30["other_configurations"][0]
    ranges = ex30["certified_range_mi"]
    assert f"({ranges['udds']} and {ranges['hwfet']} mi)" in text
    assert f"({wheels18['certified_range_mi']['udds']} mi)" in text
    phase5 = wheels18["phases"][4]
    computed = phase5["dc_kwh"] / phase5["miles"] * 100
    assert (
        f"phase 5 is printed as {phase5['reported_kwh_per_100mi']} kWh/100 mi, but its own energy "
        f"and distance give {computed:.3f}"
    ) in text
    a, b = ex30["constant_65_mph_dc_wh_per_mi"]
    c, d = wheels18["constant_65_mph_dc_wh_per_mi"]
    assert f"({a} and {b} Wh/mi; 18-inch: {c} and {d})" in text
    for config in (ex30, wheels18):
        last = config["phases"][-1]["reported_kwh_per_100mi"]
        assert f"{last} as {last:.1f}" in text


def test_manufacturer_table() -> None:
    # The figures of section 6 are those of data/manufacturer_facts.json, whose quotes
    # tools/verify_manufacturer.py finds in the manufacturers' documents.
    text = _text("docs/data-sources.md")
    section = text[text.index("## 6. Manufacturer data") : text.index("## 7. ")].replace(",", "")
    for vehicle, facts in read_json("manufacturer_facts.json")["vehicles"].items():
        for fact in facts:
            if fact["value"] is None or fact["item"] in ("table_column_order", "drive"):
                continue
            for number in re.findall(r"\d+(?:[.,/-]\d+)*", str(fact["value"])):
                assert number.replace(",", "") in section, (vehicle, fact["item"], number)


def test_other_wheel_records() -> None:
    text = _text("docs/data-sources.md")
    ex30, polestar = _certificate("volvo-ex30-sm-er"), _certificate("polestar-2-lr-sm")
    base = ex30["test_vehicle"]["target_coefficients"]
    wheels18 = ex30["other_configurations"][0]["test_vehicle"]["target_coefficients"]
    assert wheels18["B_lbf_per_mph"] == base["B_lbf_per_mph"]
    assert (
        f"(A = {wheels18['A_lbf']} lbf and C = {wheels18['C_lbf_per_mph2']} lbf/mph², against "
        f"{base['A_lbf']} and {base['C_lbf_per_mph2']})"
    ) in text
    base = polestar["test_vehicle"]["target_coefficients"]
    wheels20 = polestar["other_configurations"][0]["test_vehicle"]["target_coefficients"]
    assert {k: v for k, v in wheels20.items() if k != "A_lbf"} == {
        k: v for k, v in base.items() if k != "A_lbf"
    }
    assert f"only in the rolling term (A = {wheels20['A_lbf']} lbf against {base['A_lbf']})" in text


def test_polestar_wheel_statement() -> None:
    wheels20 = _certificate("polestar-2-lr-sm")["other_configurations"][0]
    rolling = wheels20["test_vehicle"]["target_coefficients"]["A_lbf"]
    assert f"rolling term A = {rolling} lbf" in _text("docs/data-sources.md")


def test_reference_values_in_the_text(study: Study) -> None:
    text = _text("docs/data-sources.md")
    low, high = study.auxiliary_bounds_w
    assert f"**{high:.0f} W and {low:.0f} W**" in text
    group = "charging_efficiency"
    assert (
        f"DTU: {_percent(group, 'dtu_obc_tesla_model_3_sr_2020_6_A'):.2f} % at 6 A and "
        f"{_percent(group, 'dtu_obc_tesla_model_3_sr_2020_16_A'):.2f} % at 16 A for the same "
        "Tesla charger"
    ) in text
    assert (
        f"Reick et al.: {_percent(group, 'reick_kia_e_niro_1_phase_10_A'):.2f} % single-phase at "
        f"10 A and {_percent(group, 'reick_kia_e_niro_3_phases_16_A'):.2f} % three-phase at 16 A"
    ) in text
    assert f"2021 VW ID.4 Pro: {_percent(group, 'dtu_obc_vw_id4_pro_2021_16_A'):.2f} %" in text
    assert f'"often {_reference(group, "doe_typical_range")["value"]}"' in text
    efficiencies = [v.epa.charging_efficiency for v in study.vehicles]
    assert f"the EPA values ({min(efficiencies):.3f}-{max(efficiencies):.3f})" in text
    peak = _reference("drivetrain_efficiency", "tesla_power_unit_peak")["value"]
    assert f"measured a maximum efficiency of {peak}" in text


def test_air_density_statement() -> None:
    text = _text("docs/data-sources.md")
    gas_constant = 287.05  # J/(kg K), dry air: a cross-check only, the model does not use it
    wltp = WLTP_PRESSURE_PA / (gas_constant * WLTP_TEMPERATURE_K)
    epa = EPA_PRESSURE_PA / (gas_constant * EPA_TEMPERATURE_K)
    assert f"gives {wltp:.4f} kg/m³ at 100 kPa and 293 K" in text
    assert f"and {epa:.4f} kg/m³ at the EPA conditions" in text
    assert round(wltp, 3) == WLTP_AIR_DENSITY
    assert round(epa, 4) == round(EPA_AIR_DENSITY, 4)


def test_rotating_mass_note(study: Study) -> None:
    text = _text("docs/data-sources.md")
    extra = [(0.03 * v.mass_in_running_order_kg + 25) - v.rotating_mass_kg for v in study.vehicles]
    share = [
        e / v.wltp_setup().inertial_mass_kg * 100
        for e, v in zip(extra, study.vehicles, strict=True)
    ]
    assert f"add about {max(extra):.0f} kg, {min(share):.1f}-{max(share):.1f} % of" in text
    row = [r for r in sensitivities(study) if r.name == "No rotating-mass allowance"]
    bound = math.ceil(_largest(row) * 100) / 100
    assert f"no EU result by more than {bound:.2f} percentage points" in text


# docs/method.md -------------------------------------------------------------------------------


def test_method_air_and_parameters(study: Study) -> None:
    text = _text("docs/method.md")
    assert f"the EPA air has {EPA_AIR_DENSITY:.4f} kg/m³" in text
    assert f"the ratio of the two densities ({WLTP_AIR_DENSITY / EPA_AIR_DENSITY:.4f})" in text
    efficiency = {v: c.drive_efficiency for v, c in study.calibrations.items()}
    peak = _reference("drivetrain_efficiency", "tesla_power_unit_peak")["value"]
    assert efficiency["tesla-model3-rwd"] < float(peak.rstrip(" %")) / 100
    assert f"The Tesla's {efficiency['tesla-model3-rwd']:.3f} lies below the {peak} " in text
    assert min(efficiency, key=efficiency.__getitem__) == "volvo-ex30-sm-er"
    assert f"the lowest, {efficiency['volvo-ex30-sm-er']:.3f}, is the EX30's" in text
    auxiliary = [r for r in sensitivities(study) if r.name.startswith("Auxiliary load")]
    assert f"moves the results by at most {_largest(auxiliary):.1f} percentage points" in text
    low, high = study.auxiliary_bounds_w
    assert f"({high:.0f} W and {low:.0f} W, DOE program record, 2024)" in text
    assert f"| {study.auxiliary_w:.0f} W (section 3) |" in text


def test_method_epa_validation(study: Study) -> None:
    text = _text("docs/method.md")
    comparisons = epa_comparisons(study)
    bound = math.ceil(max(abs(c.error_pct) for c in comparisons) * 10) / 10
    assert f"No prediction is off by more than {bound:.1f} %" in text
    assert f"unseen tests within {bound:.1f} %" in text
    steady = [c.error_pct for c in comparisons if "65 mph" in c.check]
    assert f"come out {min(steady):.1f}-{max(steady):.1f} % high" in text
    id4 = _certificate("vw-id4-pro")
    d_mode, b_mode = id4["dc_wh_per_mi"], id4["other_configurations"][0]["dc_wh_per_mi"]
    udds = (d_mode["udds"] - b_mode["udds"]) / d_mode["udds"] * 100
    hwfet = (d_mode["hwfet"] - b_mode["hwfet"]) / d_mode["hwfet"] * 100
    assert f"{udds:.1f} % less energy on the UDDS than in the default D mode" in text
    assert f"and {hwfet:.1f} % on the highway cycle" in text


def test_method_eu_validation(study: Study) -> None:
    text = _text("docs/method.md")
    errors = {(c.vehicle_id, c.unit): c.error_pct for c in eu_comparisons(study)}
    ex30_z, ex30_r = errors[("volvo-ex30-sm-er", "Wh/km")], errors[("volvo-ex30-sm-er", "km")]
    pole_z, pole_r = errors[("polestar-2-lr-sm", "Wh/km")], errors[("polestar-2-lr-sm", "km")]
    assert (
        f"the EX30's range agrees ({signed(ex30_r)} %) but its consumption is "
        f"{abs(ex30_z):.1f} % below the official value"
    ) in text
    assert (
        f"the Polestar 2's consumption agrees ({signed(pole_z)} %) but its range falls "
        f"{abs(pole_r):.1f} % short"
    ) in text
    for car in ("tesla-model3-rwd", "vw-id4-pro"):
        assert max(abs(errors[(car, "Wh/km")]), abs(errors[(car, "km")])) < 3
    assert "For the Tesla and the ID.4 both comparisons agree within 3 %" in text
    ex30 = study.vehicle("volvo-ex30-sm-er")
    socket = eu_prediction(study, ex30).battery_wh_per_km / implied_eu_charging_efficiency(ex30)
    official = ex30.eu_consumption_wh_per_km.mode
    assert f"becomes {socket:.1f} Wh/km against the official {official:.0f}" in text
    polestar = study.vehicle("polestar-2-lr-sm")
    implied = polestar.epa.usable_energy_wh / polestar.eu_range_km.mode
    modelled = eu_prediction(study, polestar).battery_wh_per_km
    assert f"of {implied:.1f} Wh/km against the model's {modelled:.1f}" in text


def test_method_climate_powers(study: Study) -> None:
    text = _text("docs/method.md")
    by_ambient: dict[float, list[float]] = defaultdict(list)
    for reference in study.climate_references:
        by_ambient[reference.ambient_c].append(reference.power_w / 1000)
    parts = [
        f"{min(kw):.1f}-{max(kw):.1f} kW at {celsius:.0f} °C"
        for celsius, kw in sorted(by_ambient.items(), reverse=True)
    ]
    parts[0] = parts[0].replace(" kW at", " kW on stationary cars at")
    assert f"measured {parts[0]}, {parts[1]} and {parts[2]}" in text
    assert f"to hold a {_cabin_celsius():.0f} °C cabin" in text


@pytest.mark.parametrize("name", ["docs/method.md", "README.md"])
def test_charging_voltages(name: str) -> None:
    certificates = read_json("epa_certification.json")["vehicles"]
    voltages = [c["recharge"]["mains_voltage_v"] for c in certificates]
    assert f"recharges at {min(voltages):.0f}-{max(voltages):.0f} V" in _text(name)


# README.md ------------------------------------------------------------------------------------


def test_readme_statements(study: Study) -> None:
    text = _text("README.md")
    assert f"The car's own consumption, {study.auxiliary_w:.0f} W, is the mean of two" in text
    worst = max(abs(c.error_pct) for c in epa_comparisons(study))
    assert f"unseen tests within about {worst:.0f} %" in text


def test_readme_figure_descriptions(study: Study) -> None:
    text = _text("README.md")
    wltc = {v.id: study.on_cycle(v.id, "wltc").mains_wh_per_km for v in study.vehicles}
    assert min(wltc, key=wltc.__getitem__) == "tesla-model3-rwd"
    assert "the Tesla needs the least energy" in text
    use: dict[str, float] = {}
    for kmh in range(30, 161):
        use = {v.id: study.at_speed(v.id, kmh).battery_wh_per_km for v in study.vehicles}
        assert min(use, key=use.__getitem__) == "tesla-model3-rwd", kmh
    assert max(use, key=use.__getitem__) == "volvo-ex30-sm-er"  # at 160 km/h
    assert (
        "The Tesla uses the least at every speed; at 160 km/h the Volvo EX30 uses the most" in text
    )


# streamlit_app.py -----------------------------------------------------------------------------


def test_app_help_texts() -> None:
    # The app computes every number it shows; these two are regulatory facts in its help texts.
    text = _text("streamlit_app.py")
    load = re.match(
        r"(\d+) per cent", _reference("wltp_definitions", "test_mass_vehicle_load")["value"]
    )
    assert load is not None
    added = _reference("wltp_definitions", "test_mass")["value"]
    assert f"which already carries the driver, {added} and {load.group(1)} % " in text
    assert f"holding a {_cabin_celsius():.0f} °C " in text
