"""The data files are found, read strictly, and point to their sources over HTTPS."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from evrange.datafiles import data_dir, read_json, reference_items, watts

DATA_FILES = (
    "vehicles.json",
    "epa_certification.json",
    "reference_values.json",
    "manufacturer_facts.json",
)


@pytest.mark.parametrize("name", DATA_FILES)
def test_every_recorded_source_address_is_https(name: str) -> None:
    # tools/downloads.py fetches over HTTPS only; the addresses the data record follow suit.
    text = (data_dir() / name).read_text(encoding="utf-8")
    assert re.findall(r"https://\S+", text)
    assert not re.findall(r"http://\S+", text)


def test_default_data_folder_is_the_repository_one() -> None:
    assert (data_dir() / "vehicles.json").is_file()
    assert data_dir(data_dir()) == data_dir()


def test_missing_data_folder_is_explained(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="no vehicle data"):
        data_dir(tmp_path)


def test_json_must_be_an_object(data_copy: Path) -> None:
    (data_copy / "list.json").write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(ValueError, match="JSON object"):
        read_json("list.json", data_copy)


@pytest.mark.parametrize(("text", "expected"), [("226 W", 226.0), (" 95.5 W ", 95.5)])
def test_watts_parses_document_values(text: str, expected: float) -> None:
    assert watts(text) == expected


@pytest.mark.parametrize("text", ["226", "226 kW", "W", "-5 W", "2 W 3"])
def test_watts_rejects_anything_else(text: str) -> None:
    with pytest.raises(ValueError, match="watts"):
        watts(text)


def test_unknown_reference_group() -> None:
    with pytest.raises(KeyError, match="no group"):
        reference_items("nothing")
