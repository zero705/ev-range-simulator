"""Shared fixtures: the study built from the repository's verified data, and scratch copies."""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from evrange import Study, load_study
from evrange.datafiles import data_dir

REPOSITORY = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def study() -> Study:
    return load_study()


@pytest.fixture
def data_copy(tmp_path: Path) -> Path:
    """A writable copy of the data folder (JSON files and cycles, not the source documents)."""
    source = data_dir()
    target = tmp_path / "data"
    shutil.copytree(source / "cycles", target / "cycles")
    for name in ("vehicles.json", "epa_certification.json", "reference_values.json"):
        shutil.copy2(source / name, target / name)
    return target


@pytest.fixture
def edit_json() -> Callable[[Path, Callable[[dict[str, Any]], None]], None]:
    """Change a JSON file in place: edit_json(path, lambda content: ...)."""

    def edit(path: Path, change: Callable[[dict[str, Any]], None]) -> None:
        content = json.loads(path.read_text(encoding="utf-8"))
        change(content)
        path.write_text(json.dumps(content), encoding="utf-8")

    return edit
