"""Locate and read the verified data files in the repository's data/ folder.

The data are not typed into the code: every value the model uses is read from these files,
which the scripts in tools/ build from official sources and verify.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_REPOSITORY_DATA = Path(__file__).resolve().parents[2] / "data"


def data_dir(path: Path | str | None = None) -> Path:
    """Return the data folder: the one given, or the repository's own data/ folder."""
    folder = Path(path) if path is not None else _REPOSITORY_DATA
    if not (folder / "vehicles.json").is_file():
        raise FileNotFoundError(
            f"no vehicle data in {folder}; pass the path of the repository's data/ folder"
        )
    return folder


def read_json(name: str, path: Path | str | None = None) -> dict[str, Any]:
    """Read one of the JSON files in the data folder."""
    with (data_dir(path) / name).open(encoding="utf-8") as handle:
        content = json.load(handle)
    if not isinstance(content, dict):
        raise ValueError(f"{name}: expected a JSON object at the top level")
    return content


def watts(text: str) -> float:
    """Parse a power written in a source document, such as '226 W'."""
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*W\s*", text)
    if match is None:
        raise ValueError(f"not a power in watts: {text!r}")
    return float(match.group(1))


def reference_items(group: str, path: Path | str | None = None) -> list[dict[str, Any]]:
    """Return the verified reference values of one group in reference_values.json."""
    values = read_json("reference_values.json", path)["values"]
    if group not in values:
        raise KeyError(f"reference_values.json has no group {group!r}")
    return list(values[group])
