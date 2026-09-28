"""Check every value in data/reference_values.json against its source document.

For each value this script confirms that:
    1. the source document in data/sources/ has the fingerprint recorded for it,
    2. the quote appears verbatim in the document's text, and the value inside the quote
       (whitespace and the dot leaders of printed tables are ignored, and typographic
       ligatures such as the "fi" in "efficiency" are compared in their plain form, because
       PDF text extraction renders all three differently from how a page looks),
    3. for a value read from a spreadsheet, the named cell holds that value (a quote from a
       spreadsheet is looked for in the text of all its cells, row by row).

Usage:
    python tools/verify_references.py
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any

import openpyxl
import openpyxl.xml
from verify_manufacturer import document_text, squash

ROOT = Path(__file__).resolve().parent.parent
REFERENCES = ROOT / "data" / "reference_values.json"
SOURCES = ROOT / "data" / "sources"


def plain(text: str) -> str:
    """Text compared without whitespace, ligatures or the dot leaders of printed tables."""
    return re.sub(r"\.{2,}", "", squash(unicodedata.normalize("NFKC", text)))


def workbook_text(path: Path) -> str:
    """Every cell of a workbook as text, row by row, for quotes taken from a spreadsheet."""
    book = openpyxl.load_workbook(path, read_only=True, data_only=True)
    cells = (
        c for sheet in book.worksheets for row in sheet.iter_rows(values_only=True) for c in row
    )
    return " ".join(str(c) for c in cells if c is not None)


def cell(path: Path, row_label: str, column: float) -> float:
    sheet = openpyxl.load_workbook(path, read_only=True, data_only=True).worksheets[0]
    rows = list(sheet.iter_rows(values_only=True))
    header = rows[0]
    col = next(i for i, h in enumerate(header) if isinstance(h, (int, float)) and h == column)
    row = next(r for r in rows[1:] if r[0] == row_label)
    value = row[col]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{row_label}, {column}: the cell holds {value!r}, not a number")
    return float(value)


def main() -> int:
    if not openpyxl.xml.DEFUSEDXML:
        print("install defusedxml (pip install -e '.[tools]'): spreadsheets are parsed with it")
        return 1
    refs: dict[str, Any] = json.loads(REFERENCES.read_text(encoding="utf-8"))
    failures = 0
    texts: dict[str, str] = {}
    paths: dict[str, Path] = {}
    for key, doc in refs["documents"].items():
        path = SOURCES / doc["file"]
        if not path.is_file():
            print(f"  skip  {key}: {doc['file']} is not in data/sources; download {doc['url']}")
            continue
        ok = hashlib.sha256(path.read_bytes()).hexdigest() == doc["sha256"]
        failures += not ok
        print(f"  {'ok  ' if ok else 'FAIL'}  {key}: fingerprint")
        if ok:
            paths[key] = path
            text = workbook_text(path) if path.suffix == ".xlsx" else document_text(path)
            texts[key] = plain(text)
    for group, items in refs["values"].items():
        print(group)
        for item in items:
            if item["doc"] not in paths:
                print(f"  skip  {item['item']}: source not available")
                continue
            if "cell" in item:
                found = cell(paths[item["doc"]], item["cell"]["row"], item["cell"]["column"])
                ok = round(found, 2) == float(item["value"])
                detail = f" (cell holds {found})"
            else:
                quote = plain(item["quote"])
                in_doc = quote in texts[item["doc"]]
                in_quote = plain(item["value"]) in quote
                ok = in_doc and in_quote
                detail = "" if ok else f" (quote found: {in_doc}, value in quote: {in_quote})"
            failures += not ok
            print(f"  {'ok  ' if ok else 'FAIL'}  {item['item']} = {item['value']}{detail}")
    print("\nall references verified" if not failures else f"\n{failures} problem(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
