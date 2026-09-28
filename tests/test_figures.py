"""The README figures can be drawn from the model in both themes."""

from __future__ import annotations

import importlib.util
from pathlib import Path

TOOL = Path(__file__).resolve().parent.parent / "tools" / "make_figures.py"
PNG = b"\x89PNG\r\n\x1a\n"


def test_figures_are_drawn_in_both_themes(tmp_path: Path) -> None:
    spec = importlib.util.spec_from_file_location("make_figures", TOOL)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    written = module.main(tmp_path)
    names = sorted(path.name for path in written)
    assert names == sorted(
        f"{stem}-{theme}.png"
        for stem in ("breakdown", "speed", "validation")
        for theme in ("light", "dark")
    )
    for path in written:
        assert path.read_bytes()[:8] == PNG
        assert path.stat().st_size > 20_000


def test_compact_labels() -> None:
    spec = importlib.util.spec_from_file_location("make_figures", TOOL)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.compact("EPA 65 mph, mid-test, 19 and 20 inch wheels") == (
        "65 mph, mid-test, 19-20 in"
    )
    assert module.compact("EPA UDDS, 18 inch wheels") == "UDDS, 18 in"
