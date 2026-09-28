"""Draw the README figures from the model, each in a light and a dark version.

Every value plotted is computed by the evrange package from the verified data; the only
things set here are colours and layout. The colours passed the data-visualisation palette
checks (lightness band, chroma, colour-vision separation, contrast) against the GitHub light
and dark page backgrounds.

Usage:
    python tools/make_figures.py [output folder]      (default: docs/images)
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib as mpl

mpl.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.patches import Rectangle

from evrange import BREAKDOWN, Study, load_study
from evrange.report import short_name, signed
from evrange.validation import epa_comparisons, eu_comparisons

ROOT = Path(__file__).resolve().parent.parent

THEMES: dict[str, dict[str, object]] = {
    "light": {
        "background": "#ffffff",
        "text": "#1f2328",
        "muted": "#59636e",
        "grid": "#d1d9e0",
        "band": "#eef0f3",
        "cars": ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"],
        "parts": ["#221657", "#372a88", "#5143b3", "#6d5ecc", "#8b7edb", "#a99ee6"],
    },
    "dark": {
        "background": "#0d1117",
        "text": "#e6edf3",
        "muted": "#9198a1",
        "grid": "#3d444d",
        "band": "#161b22",
        "cars": ["#4389dd", "#e06a37", "#23a176", "#c08a00"],
        "parts": ["#443799", "#5b4db8", "#7466cc", "#8f82da", "#ab9fe5", "#c6bdef"],
    },
}
SPEEDS_KMH = list(range(30, 165, 5))


def colours(theme: dict[str, object], key: str) -> list[str]:
    value = theme[key]
    if not isinstance(value, list):
        raise TypeError(f"theme entry {key!r} is not a list of colours")
    return [str(v) for v in value]


def colour(theme: dict[str, object], key: str) -> str:
    return str(theme[key])


def setup_axes(ax: Axes, theme: dict[str, object]) -> None:
    ax.set_facecolor(colour(theme, "background"))
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(colour(theme, "grid"))
    ax.tick_params(colors=colour(theme, "muted"), labelsize=9, length=0)
    ax.xaxis.label.set_color(colour(theme, "muted"))
    ax.yaxis.label.set_color(colour(theme, "muted"))
    ax.grid(axis="x", color=colour(theme, "grid"), linewidth=0.6)
    ax.set_axisbelow(True)


def title(fig: Figure, theme: dict[str, object], text: str, sub: str) -> None:
    fig.text(
        0.02, 0.965, text, fontsize=13, fontweight="bold", color=colour(theme, "text"), va="top"
    )
    fig.text(0.02, 0.91, sub, fontsize=9.5, color=colour(theme, "muted"), va="top")


def breakdown_figure(study: Study, theme: dict[str, object], path: Path) -> None:
    ids = [v.id for v in study.vehicles]
    uses = {vid: study.on_cycle(vid, "wltc") for vid in ids}
    fig, ax = plt.subplots(figsize=(9, 3.9), dpi=200)
    fig.patch.set_facecolor(colour(theme, "background"))
    setup_axes(ax, theme)
    rows = list(reversed(ids))
    for row, vid in enumerate(rows):
        use = uses[vid]
        left = 0.0
        for part, fill in zip(BREAKDOWN, colours(theme, "parts"), strict=True):
            width = use.breakdown_wh()[part] / use.distance_km
            ax.barh(
                row,
                width,
                left=left,
                height=0.62,
                color=fill,
                edgecolor=colour(theme, "background"),
                linewidth=1.5,
            )
            left += width
        ax.text(
            left + 1.5,
            row,
            f"{use.mains_wh_per_km:.0f} Wh/km",
            va="center",
            fontsize=9,
            color=colour(theme, "text"),
        )
    ax.set_yticks(range(len(rows)), [short_name(v) for v in rows])
    ax.tick_params(axis="y", labelsize=10, labelcolor=colour(theme, "text"))
    ax.set_xlabel("Wh per km from the socket, WLTC")
    ax.set_xlim(0, 185)
    handles = [Rectangle((0, 0), 1, 1, color=fill) for fill in colours(theme, "parts")]
    legend = ax.legend(
        handles,
        list(BREAKDOWN.values()),
        ncol=3,
        loc="upper center",
        bbox_to_anchor=(0.45, -0.28),
        frameon=False,
        fontsize=8.5,
    )
    for label in legend.get_texts():
        label.set_color(colour(theme, "text"))
    title(
        fig,
        theme,
        "Where the energy goes on the WLTC",
        "Energy taken from the socket per kilometre, from the road back to the socket",
    )
    fig.subplots_adjust(left=0.19, right=0.97, top=0.8, bottom=0.36)
    fig.savefig(path, facecolor=colour(theme, "background"), metadata={"Software": None})
    plt.close(fig)


def speed_figure(study: Study, theme: dict[str, object], path: Path) -> None:
    fig, ax = plt.subplots(figsize=(9, 4.4), dpi=200)
    fig.patch.set_facecolor(colour(theme, "background"))
    setup_axes(ax, theme)
    ax.grid(axis="y", color=colour(theme, "grid"), linewidth=0.6)
    ends = {}
    for vehicle, line in zip(study.vehicles, colours(theme, "cars"), strict=True):
        values = [study.at_speed(vehicle.id, s).battery_wh_per_km / 10 for s in SPEEDS_KMH]
        ax.plot(SPEEDS_KMH, values, color=line, linewidth=2)
        ends[vehicle.id] = (values[-1], line)
    # Direct labels, nudged apart so that no two touch.
    order = sorted(ends, key=lambda vid: ends[vid][0])
    placed: list[float] = []
    for vid in order:
        y = ends[vid][0]
        if placed:
            y = max(y, placed[-1] + 1.6)
        placed.append(y)
        ax.text(SPEEDS_KMH[-1] + 2, y, short_name(vid), va="center", fontsize=9, color=ends[vid][1])
    ax.set_xlim(SPEEDS_KMH[0], SPEEDS_KMH[-1])
    ax.set_ylim(0, 40)
    ax.set_xlabel("Steady speed (km/h)")
    ax.set_ylabel("kWh/100 km from the battery")
    title(
        fig,
        theme,
        "Consumption at a steady speed",
        "Each car at its WLTP test mass, climate control off",
    )
    fig.subplots_adjust(left=0.08, right=0.8, top=0.8, bottom=0.14)
    fig.savefig(path, facecolor=colour(theme, "background"), metadata={"Software": None})
    plt.close(fig)


def compact(check: str) -> str:
    """A short row label for an EPA check, such as '65 mph, mid-test, 18 in'."""
    return (
        check.removeprefix("EPA ")
        .replace(" and 20 inch wheels", "-20 in")
        .replace(" inch wheels", " in")
    )


def validation_figure(study: Study, theme: dict[str, object], path: Path) -> None:
    car_colour = dict(zip([v.id for v in study.vehicles], colours(theme, "cars"), strict=True))
    eu = eu_comparisons(study)
    groups = [
        ("EPA tests not used to identify the cars", epa_comparisons(study), True),
        ("EU WLTP consumption from the socket", [c for c in eu if c.unit == "Wh/km"], False),
        ("EU WLTP range", [c for c in eu if c.unit == "km"], False),
    ]
    rows = sum(len(items) for _, items, _ in groups) + len(groups)
    height = 0.27 * rows + 1.7
    fig, ax = plt.subplots(figsize=(9, height), dpi=200)
    fig.patch.set_facecolor(colour(theme, "background"))
    setup_axes(ax, theme)
    ax.axvspan(-2, 2, color=colour(theme, "band"), zorder=0)
    ax.axvline(0, color=colour(theme, "muted"), linewidth=0.8, zorder=1)
    y = rows - 1
    ticks: list[int] = []
    labels: list[str] = []
    for heading, items, detailed in groups:
        # Headings sit in the label column: x in axes coordinates, y in data coordinates.
        ax.text(
            -0.02,
            y,
            heading,
            transform=ax.get_yaxis_transform(),
            ha="right",
            va="center",
            fontsize=9,
            fontweight="bold",
            color=colour(theme, "text"),
        )
        y -= 1
        for c in items:
            right = c.error_pct >= 0
            ax.plot(c.error_pct, y, "o", markersize=6.5, color=car_colour[c.vehicle_id], zorder=3)
            ax.text(
                c.error_pct + (0.35 if right else -0.35),
                y,
                f"{signed(c.error_pct)} %",
                va="center",
                ha="left" if right else "right",
                fontsize=7.5,
                color=colour(theme, "muted"),
            )
            label = short_name(c.vehicle_id)
            ticks.append(y)
            labels.append(f"{label}, {compact(c.check)}" if detailed else label)
            y -= 1
    ax.set_yticks(ticks, labels)
    ax.tick_params(axis="y", labelsize=8.5, labelcolor=colour(theme, "text"))
    ax.set_xlim(-11, 11)
    ax.set_ylim(-0.7, rows - 0.3)
    ax.set_xlabel("Model minus measured, % of the measured value (shaded: ±2 %)")
    title(
        fig,
        theme,
        "How well the model predicts what it was not fitted to",
        "Each car is identified from its EPA city and highway tests only",
    )
    fig.subplots_adjust(left=0.4, right=0.97, top=1 - 1.1 / height, bottom=0.6 / height)
    fig.savefig(path, facecolor=colour(theme, "background"), metadata={"Software": None})
    plt.close(fig)


def main(folder: Path) -> list[Path]:
    folder.mkdir(parents=True, exist_ok=True)
    study = load_study()
    written = []
    for name, theme in THEMES.items():
        for stem, draw in (
            ("breakdown", breakdown_figure),
            ("speed", speed_figure),
            ("validation", validation_figure),
        ):
            path = folder / f"{stem}-{name}.png"
            draw(study, theme, path)
            written.append(path)
    return written


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "docs" / "images"
    for path in main(out):
        print(f"wrote {path}")
