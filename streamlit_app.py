"""EV Range Simulator: interactive front end to the evrange model.

Run with:  streamlit run streamlit_app.py

Every number shown comes from the model (src/evrange) and the verified data in data/;
nothing is typed into this file except labels and the chart colours, and the regulatory facts
in two help texts are checked against their verified quotes by tests/test_docs.py.
"""

from __future__ import annotations

import math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
# Use this checkout's package, whether or not it has been installed.
sys.path.insert(0, str(ROOT / "src"))

import altair as alt  # noqa: E402
import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from evrange import BREAKDOWN, Conditions, EnergyUse, Study, load_study  # noqa: E402
from evrange.constants import DRIVER_MASS_KG, EPA_PRESSURE_PA, EPA_TEMPERATURE_K  # noqa: E402
from evrange.report import AGREEMENT_PCT, short_name  # noqa: E402
from evrange.validation import (  # noqa: E402
    epa_comparisons,
    eu_comparisons,
    implied_eu_charging_efficiency,
)

REPOSITORY = "https://github.com/zero705/ev-range-simulator"

# Validated with the data-visualisation palette checks (lightness band, chroma, colour-vision
# separation of neighbours, contrast against the white chart surface): one colour per car,
# always in this order.
CAR_COLOURS = {
    "tesla-model3-rwd": "#2a78d6",
    "volvo-ex30-sm-er": "#eb6834",
    "polestar-2-lr-sm": "#1baf7a",
    "vw-id4-pro": "#eda100",
}
# One hue whose lightness steps along the energy path from the road back to the socket.
BREAKDOWN_COLOURS = ["#221657", "#372a88", "#5143b3", "#6d5ecc", "#8b7edb", "#a99ee6"]
ACCENT = "#5143b3"

DRIVES = ["wltc", "wltc-low", "wltc-medium", "wltc-high", "wltc-extra-high", "udds", "hwfet"]
STEADY = "steady"
SWEEP_KMH = list(range(30, 165, 5))
CHART_HEIGHT = 420  # whole chart, axes and legend included (Streamlit fits charts to it)
AXIS_AND_LEGEND_PX = 90
LABEL_PX = 15
LABEL_ROOM = 130  # pixels to the right of line charts for the car names


@st.cache_resource(show_spinner=False)
def get_study() -> Study:
    return load_study(ROOT / "data")


def drive_label(study: Study, key: str) -> str:
    if key == STEADY:
        return "Steady speed"
    cycle = study.cycles[key]
    return f"{cycle.name}, average {cycle.mean_speed_kmh:.0f} km/h"


def car_scale(ids: list[str]) -> alt.Scale:
    return alt.Scale(domain=[short_name(i) for i in ids], range=[CAR_COLOURS[i] for i in ids])


def run(
    study: Study, vehicle_id: str, drive: str, speed: float, conditions: Conditions
) -> EnergyUse:
    if drive == STEADY:
        return study.at_speed(vehicle_id, speed, conditions)
    return study.on_cycle(vehicle_id, drive, conditions)


def sidebar(study: Study) -> tuple[str, float, Conditions, list[str]]:
    st.sidebar.header("Scenario")
    drive = st.sidebar.selectbox(
        "Drive",
        [*DRIVES, STEADY],
        format_func=lambda key: drive_label(study, key),
        key="drive",
    )
    speed = 110.0
    if drive == STEADY:
        speed = float(st.sidebar.slider("Speed (km/h)", 30, 160, 110, 5, key="speed"))
    load = st.sidebar.slider(
        "Extra load (kg)",
        0,
        300,
        0,
        25,
        key="load",
        help=(
            "Added to the WLTP test mass, which already carries the driver, 25 kg and 15 % "
            f"of the maximum load. The regulation counts a driver as {DRIVER_MASS_KG:.0f} kg."
        ),
    )
    climate = st.sidebar.slider(
        "Climate control (W)",
        0,
        4000,
        0,
        100,
        key="climate",
        help="Heating or air conditioning, added to the car's own consumption. "
        "The official tests run with it off.",
    )
    with st.sidebar.expander("Measured climate-control power"):
        rows = [
            {"Outside": f"{r.ambient_c:.0f} °C ({r.ambient_f:.0f} °F)", "Power (W)": r.power_w}
            for r in sorted(study.climate_references, key=lambda r: (r.ambient_f, r.power_w))
        ]
        st.dataframe(
            pd.DataFrame(rows),
            hide_index=True,
            column_config={"Power (W)": st.column_config.NumberColumn(format="%.0f")},
        )
        st.caption(
            "Two cars measured by Argonne National Laboratory at a standstill, holding a 22 °C "
            "cabin, battery thermal management included (US DOE program record, 2024). "
            "Cold also reduces what a battery delivers, which the model does not include."
        )
    names = {v.id: short_name(v.id) for v in study.vehicles}
    cars = st.sidebar.multiselect(
        "Cars", list(names), default=list(names), format_func=names.__getitem__, key="cars"
    )
    conditions = Conditions(extra_mass_kg=float(load), climate_w=float(climate))
    return drive, speed, conditions, cars


def headline(
    study: Study, results: dict[str, EnergyUse], drive: str, conditions: Conditions
) -> None:
    baseline = drive == "wltc" and conditions == Conditions()
    for column, (vehicle_id, use) in zip(st.columns(len(results)), results.items(), strict=True):
        vehicle = study.vehicle(vehicle_id)
        with column:
            st.metric(
                short_name(vehicle_id),
                f"{study.range_km(vehicle_id, use):.0f} km",
                border=True,
                help="Usable battery energy measured by the EPA, divided by the modelled "
                "battery consumption.",
            )
            st.caption(
                f"Battery: {use.battery_wh_per_km / 10:.1f} kWh/100 km  \n"
                f"From the socket: {use.mains_wh_per_km / 10:.1f} kWh/100 km"
            )
            if baseline:
                st.caption(
                    f"EU official: {vehicle.eu_range_km.mode:.0f} km, "
                    f"{vehicle.eu_consumption_wh_per_km.mode / 10:.1f} kWh/100 km"
                )


def breakdown_tab(results: dict[str, EnergyUse]) -> None:
    st.markdown(
        "Energy taken from the socket per kilometre, split by where it ends up: resistance "
        "at the road, braking the regeneration does not recover, losses in the drivetrain, "
        "the car's own consumption with any climate control, and losses while charging."
    )
    labels = list(BREAKDOWN.values())
    rows = []
    for vehicle_id, use in results.items():
        parts = use.breakdown_wh()
        for order, (key, label) in enumerate(BREAKDOWN.items()):
            rows.append(
                {
                    "Car": short_name(vehicle_id),
                    "Part": label,
                    "order": order,
                    "Wh/km": parts[key] / use.distance_km,
                    "Share": parts[key] / use.mains_wh,
                }
            )
    data = pd.DataFrame(rows)
    chart = (
        alt.Chart(data)
        .mark_bar(stroke="#ffffff", strokeWidth=2)
        .encode(
            x=alt.X("sum(Wh/km):Q", title="Wh per km from the socket"),
            y=alt.Y("Car:N", title=None, sort=[short_name(i) for i in results]),
            color=alt.Color(
                "Part:N",
                scale=alt.Scale(domain=labels, range=BREAKDOWN_COLOURS),
                legend=alt.Legend(
                    title="From the road back to the socket",
                    orient="bottom",
                    titleLimit=0,
                    labelLimit=0,
                ),
            ),
            order=alt.Order("order:Q"),
            tooltip=[
                "Car",
                "Part",
                alt.Tooltip("Wh/km:Q", format=".1f"),
                alt.Tooltip("Share:Q", format=".0%"),
            ],
        )
        .properties(height=60 * len(results) + 40)
    )
    st.altair_chart(chart, width="stretch")
    table = data.pivot(index="Car", columns="Part", values="Wh/km")[labels]
    table["Total"] = pd.Series({short_name(i): use.mains_wh_per_km for i, use in results.items()})
    st.dataframe(
        table.reindex([short_name(i) for i in results]),
        width="stretch",
        column_config={n: st.column_config.NumberColumn(format="%.1f") for n in [*labels, "Total"]},
    )


def trace_tab(study: Study, drive: str, speed: float) -> None:
    if drive == STEADY:
        st.markdown(
            f"A steady {speed:.0f} km/h: no acceleration and no braking, so the energy goes into "
            "road resistance, drivetrain losses, the car's own consumption with any climate "
            "control, and losses while charging."
        )
        return
    cycle = study.cycles[drive]
    st.markdown(
        f"**{cycle.name}** ({cycle.source}): {cycle.distance_m / 1000:.2f} km in "
        f"{cycle.duration_s / 60:.1f} min, average {cycle.mean_speed_kmh:.1f} km/h, top "
        f"{cycle.max_speed_kmh:.1f} km/h, standing still {cycle.standstill_share:.0%} of the time."
    )
    data = pd.DataFrame(
        {"Time (s)": range(cycle.speed_ms.size), "Speed (km/h)": cycle.speed_ms * 3.6}
    )
    chart = (
        alt.Chart(data)
        .mark_line(strokeWidth=2, color=ACCENT)
        .encode(
            x=alt.X("Time (s):Q"),
            y=alt.Y("Speed (km/h):Q"),
            tooltip=["Time (s)", alt.Tooltip("Speed (km/h):Q", format=".1f")],
        )
        .properties(height=280)
    )
    st.altair_chart(chart, width="stretch")


def nice_ceiling(value: float) -> float:
    """Round up to a clean axis end: 1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6 or 8 times a power of ten."""
    if value <= 0:
        return 1.0
    power = 10.0 ** math.floor(math.log10(value))
    steps = (1.0, 1.2, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0)
    return next(power * m for m in steps if power * m >= value)


def spread_labels(values: dict[str, float], gap: float) -> dict[str, float]:
    """Positions for end-of-line labels: in the lines' order, at least `gap` apart."""
    if not values:
        return {}
    ordered = sorted(values.items(), key=lambda item: item[1])
    positions = [ordered[0][1]]
    for _, value in ordered[1:]:
        positions.append(max(value, positions[-1] + gap))
    shift = sum(p - v for p, (_, v) in zip(positions, ordered, strict=True)) / len(positions)
    return {name: p - shift for (name, _), p in zip(ordered, positions, strict=True)}


def sweep_chart(data: pd.DataFrame, value: str, ids: list[str], title: str) -> alt.LayerChart:
    top = nice_ceiling(1.05 * float(data[value].max()))
    colour = alt.Color("Car:N", scale=car_scale(ids), legend=alt.Legend(orient="bottom"))
    base = alt.Chart(data).encode(
        x=alt.X("Speed (km/h):Q", scale=alt.Scale(domain=[SWEEP_KMH[0], SWEEP_KMH[-1]])),
        y=alt.Y(f"{value}:Q", title=title, scale=alt.Scale(domain=[0, top])),
        color=colour,
    )
    hover = alt.selection_point(
        fields=["Speed (km/h)"], nearest=True, on="pointerover", empty=False
    )
    lines = base.mark_line(strokeWidth=2)
    points = (
        base.mark_point(size=60, filled=True)
        .encode(
            opacity=alt.condition(hover, alt.value(1), alt.value(0)),
            tooltip=["Car", "Speed (km/h)", alt.Tooltip(f"{value}:Q", format=".1f")],
        )
        .add_params(hover)
    )
    rule = (
        alt.Chart(data)
        .mark_rule(color="#8b8b8b")
        .encode(x="Speed (km/h):Q")
        .transform_filter(hover)
    )
    last = data[data["Speed (km/h)"] == SWEEP_KMH[-1]]
    # Labels are about 15 px tall; the plot area is roughly the chart height minus the axis
    # and legend, so this gap in data units keeps neighbouring names from touching.
    gap = top * LABEL_PX / (CHART_HEIGHT - AXIS_AND_LEGEND_PX)
    placed = spread_labels(dict(zip(last["Car"], last[value], strict=True)), gap)
    labels = (
        alt.Chart(pd.DataFrame({"Car": list(placed), "y": list(placed.values())}))
        .mark_text(align="left", dx=8, fontSize=12)
        .encode(
            x=alt.datum(SWEEP_KMH[-1]),
            y="y:Q",
            text="Car:N",
            color=alt.Color("Car:N", scale=car_scale(ids), legend=None),
        )
    )
    return alt.LayerChart(
        layer=[lines, points, rule, labels],
        height=CHART_HEIGHT,
        padding={"right": LABEL_ROOM},
    )


def drag_crossover_kmh(study: Study, vehicle_id: str, conditions: Conditions) -> float:
    setup = study.vehicle(vehicle_id).wltp_setup(conditions.extra_mass_kg, conditions.air_density)
    return setup.road_load.drag_crossover_ms() * 3.6


def sweep_tab(study: Study, cars: list[str], conditions: Conditions) -> None:
    crossovers = ", ".join(
        f"{short_name(v)} {drag_crossover_kmh(study, v, conditions):.0f} km/h" for v in cars
    )
    st.markdown(
        "Consumption and range at a steady speed, with the extra load and climate power set in "
        "the sidebar. Air drag grows with the square of speed and overtakes rolling resistance "
        f"at {crossovers}. The car's own consumption and any climate power cost the same per "
        "hour, so they weigh more per kilometre the slower the car goes: with the climate "
        "control on, the lowest consumption moves to a higher speed."
    )
    rows = []
    for vehicle_id in cars:
        for kmh in SWEEP_KMH:
            use = study.at_speed(vehicle_id, kmh, conditions)
            rows.append(
                {
                    "Car": short_name(vehicle_id),
                    "Speed (km/h)": kmh,
                    "kWh/100 km": use.battery_wh_per_km / 10,
                    "Range (km)": study.range_km(vehicle_id, use),
                }
            )
    data = pd.DataFrame(rows)
    st.altair_chart(
        sweep_chart(data, "kWh/100 km", cars, "kWh/100 km from the battery"), width="stretch"
    )
    st.altair_chart(sweep_chart(data, "Range (km)", cars, "Range (km)"), width="stretch")
    with st.expander("Table of ranges"):
        names = [short_name(v) for v in cars]
        st.dataframe(
            data.pivot(index="Speed (km/h)", columns="Car", values="Range (km)")[names],
            width="stretch",
            column_config={n: st.column_config.NumberColumn(format="%.0f") for n in names},
        )


SAFE_URL = re.compile(r"https://[\w.-]+(?:/[\w./?=&%~+-]*)?")


def https_link(label: str, url: str) -> str:
    """A Markdown link, made only for a plain HTTPS address; anything else stays text."""
    return f"[{label}]({url})" if SAFE_URL.fullmatch(url) else label


def car_rows(study: Study, cars: list[str]) -> list[tuple[str, list[str]]]:
    """Every input the model uses for each car, as table rows (label, one cell per car)."""
    vehicles = [study.vehicle(v) for v in cars]
    cal = [study.calibrations[v] for v in cars]

    def row(label: str, values: list[str]) -> tuple[str, list[str]]:
        return label, values

    return [
        row("EU: registrations in 2024", [f"{v.eu_registrations:,}" for v in vehicles]),
        row(
            "EU: mass in running order (kg)",
            [f"{v.mass_in_running_order_kg:.0f}" for v in vehicles],
        ),
        row("EU: WLTP test mass (kg)", [f"{v.wltp_test_mass_kg:.0f}" for v in vehicles]),
        row("EU: motor power (kW)", [f"{v.motor_power_kw:.0f}" for v in vehicles]),
        row(
            "EU: official consumption (Wh/km)",
            [f"{v.eu_consumption_wh_per_km.mode:.0f}" for v in vehicles],
        ),
        row("EU: official range (km)", [f"{v.eu_range_km.mode:.0f}" for v in vehicles]),
        row("EPA: test weight (kg)", [f"{v.epa.test_weight_kg:.0f}" for v in vehicles]),
        row("EPA: road load f0 (N)", [f"{v.epa.road_load.f0:.1f}" for v in vehicles]),
        row("EPA: road load f1 (N per m/s)", [f"{v.epa.road_load.f1:.3f}" for v in vehicles]),
        row(
            f"EPA: road load f2 (N per (m/s)², air at {EPA_TEMPERATURE_K - 273.15:.0f} °C, "
            f"{EPA_PRESSURE_PA / 1000:.2f} kPa)",
            [f"{v.epa.road_load.f2:.4f}" for v in vehicles],
        ),
        row(
            "EPA: usable battery energy (kWh)",
            [f"{v.epa.usable_energy_wh / 1000:.1f}" for v in vehicles],
        ),
        row("EPA: charging efficiency", [f"{v.epa.charging_efficiency:.3f}" for v in vehicles]),
        row("GTR 15: rotating mass (kg)", [f"{v.rotating_mass_kg:.1f}" for v in vehicles]),
        row("Identified: drivetrain efficiency", [f"{c.drive_efficiency:.3f}" for c in cal]),
        row("Identified: regeneration coefficient", [f"{c.regen_coefficient:.3f}" for c in cal]),
        row(
            "Air drag equals rolling resistance at (km/h)",
            [f"{drag_crossover_kmh(study, v, Conditions()):.0f}" for v in cars],
        ),
        row("EPA certificate", [https_link("report", v.report_url) for v in vehicles]),
    ]


def cars_tab(study: Study, cars: list[str]) -> None:
    st.markdown(
        "Every input the model uses, per car, with where it comes from: the EU registrations "
        "(EEA, 2024), the EPA Test Car List and certificate reports, the UN GTR No. 15 "
        "estimate of the rotating mass, and the two values identified from the EPA tests."
    )
    names = [short_name(v) for v in cars]
    lines = [
        "| | " + " | ".join(names) + " |",
        "|---" + "|---:" * len(names) + "|",
    ]
    for label, values in car_rows(study, cars):
        lines.append(f"| {label} | " + " | ".join(values) + " |")
    st.markdown("\n".join(lines))


def validation_tab(study: Study) -> None:
    st.markdown(
        "Each car's drivetrain efficiency and regeneration coefficient are identified from its "
        "US certification test (EPA city and highway cycles, energy measured at the battery). "
        "Everything below was **not** used to identify them."
    )
    calibration = pd.DataFrame(
        [
            {
                "Car": short_name(v.id),
                "Drivetrain efficiency": study.calibrations[v.id].drive_efficiency,
                "Regeneration coefficient": study.calibrations[v.id].regen_coefficient,
                "Charging efficiency (EPA)": v.epa.charging_efficiency,
            }
            for v in study.vehicles
        ]
    )
    st.markdown("##### Identified from the EPA certification tests")
    st.dataframe(
        calibration,
        hide_index=True,
        width="stretch",
        column_config={
            n: st.column_config.NumberColumn(format="%.3f") for n in list(calibration.columns[1:])
        },
    )

    st.markdown("##### EPA tests of other wheels and of a steady 65 mph")
    epa = pd.DataFrame(
        [
            {
                "Car": short_name(c.vehicle_id),
                "Measurement": c.check.removeprefix("EPA "),
                "Model (Wh/km)": c.model,
                "Measured (Wh/km)": c.measured,
                "Difference (%)": c.error_pct,
            }
            for c in epa_comparisons(study)
        ]
    )
    st.dataframe(
        epa,
        hide_index=True,
        width="stretch",
        column_config={
            "Model (Wh/km)": st.column_config.NumberColumn(format="%.1f"),
            "Measured (Wh/km)": st.column_config.NumberColumn(format="%.1f"),
            "Difference (%)": st.column_config.NumberColumn(format="%+.1f"),
        },
    )

    st.markdown("##### EU type-approval values (WLTP)")
    eu = pd.DataFrame(
        [
            {
                "Car": short_name(c.vehicle_id),
                "Quantity": "Consumption (Wh/km)" if c.unit == "Wh/km" else "Range (km)",
                "Model": c.model,
                "Official": c.measured,
                "Difference (%)": c.error_pct,
            }
            for c in eu_comparisons(study)
        ]
    )
    st.dataframe(
        eu,
        hide_index=True,
        width="stretch",
        column_config={
            "Model": st.column_config.NumberColumn(format="%.1f"),
            "Official": st.column_config.NumberColumn(format="%.0f"),
            "Difference (%)": st.column_config.NumberColumn(format="%+.1f"),
        },
    )
    implied = ", ".join(
        f"{short_name(v.id)} {implied_eu_charging_efficiency(v):.3f} "
        f"(EPA {v.epa.charging_efficiency:.3f})"
        for v in study.vehicles
    )
    apart = ", ".join(
        f"{short_name(c.vehicle_id)} {'consumption' if c.unit == 'Wh/km' else 'range'}"
        for c in eu_comparisons(study)
        if abs(c.error_pct) >= AGREEMENT_PCT
    )
    st.markdown(
        "Consumption and range start from the same modelled battery consumption. Where they "
        f"disagree (more than {AGREEMENT_PCT:.0f} % apart: {apart}), the EU figures differ "
        "from the US ones in charging or usable battery energy: official consumption times "
        "official range is the energy of a full recharge, and the charging efficiency it "
        f"implies is {implied}. The gaps are reported, not tuned away. "
        f"[The method and every check]({REPOSITORY}/blob/main/docs/method.md)."
    )


def method_tab(study: Study) -> None:
    st.markdown(
        f"""
**Model.** At each second the wheels must overcome the measured road load and the change of
kinetic energy. Energy from the battery is the work the wheels deliver divided by the
drivetrain efficiency, minus the share of braking work returned by regeneration, plus the
car's own consumption. Energy from the socket divides that by the charging efficiency.

**Where every number comes from.**

| Input | Source |
|---|---|
| Drive cycles | UN GTR No. 15 (WLTC), 40 CFR Parts 86 and 600 (UDDS, HWFET) |
| Road load (coastdown) | US EPA Test Car List |
| Battery and socket energy, charging | US EPA certificate reports of the same test cars |
| Masses, official consumption and range | EU registrations 2024, European Environment Agency |
| The car's own consumption ({study.auxiliary_w:.0f} W) | US DOE program record 2024 (Argonne) |
| Climate-control reference values | same record |
| Reference air, rotating mass | UN GTR No. 15, Regulation (EU) 2017/1151, 40 CFR 1066.305 |

**Limits.** One efficiency per car; flat road and no wind; cold weather is represented only
by climate power; the EU road loads are not public, so the EPA coastdown is used for both.

Full account: [method]({REPOSITORY}/blob/main/docs/method.md) ·
[data sources]({REPOSITORY}/blob/main/docs/data-sources.md) ·
[source code]({REPOSITORY}).
"""
    )


def main() -> None:
    st.set_page_config(page_title="EV Range Simulator", layout="wide")
    study = get_study()
    drive, speed, conditions, cars = sidebar(study)
    st.title("EV Range Simulator")
    st.caption(
        "Four electric cars, identified from their US certification tests and checked "
        "against the EU type-approval figures. Every input has an official or peer-reviewed "
        "source."
    )
    if not cars:
        st.info("Choose at least one car in the sidebar.")
        return
    ordered = [v.id for v in study.vehicles if v.id in cars]
    results = {vid: run(study, vid, drive, speed, conditions) for vid in ordered}
    headline(study, results, drive, conditions)
    tabs = st.tabs(
        ["Where the energy goes", "Drive trace", "Speed sweep", "Cars", "Validation", "Method"]
    )
    with tabs[0]:
        breakdown_tab(results)
    with tabs[1]:
        trace_tab(study, drive, speed)
    with tabs[2]:
        sweep_tab(study, ordered, conditions)
    with tabs[3]:
        cars_tab(study, ordered)
    with tabs[4]:
        validation_tab(study)
    with tabs[5]:
        method_tab(study)
    st.caption(
        "Built by Ömer Faruk Şenol · MIT License · data from the EEA, the US EPA, the US DOE "
        "and the UNECE"
    )


if __name__ == "__main__":  # Streamlit runs the script as __main__; tests import its helpers
    main()
