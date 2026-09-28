"""Rewrite the generated tables in README.md and docs/method.md from the model.

The tables sit between '<!-- generated: name -->' and '<!-- end generated -->'.
tests/test_report.py fails if a document no longer matches what the model computes.

Usage:
    python tools/update_docs.py           rewrite the tables
    python tools/update_docs.py --check   only report whether they are up to date
"""

from __future__ import annotations

import sys
from pathlib import Path

from evrange import load_study
from evrange.report import refresh

ROOT = Path(__file__).resolve().parent.parent
DOCUMENTS = [ROOT / "README.md", ROOT / "docs" / "method.md"]


def main(check: bool) -> int:
    study = load_study()
    stale = []
    for path in DOCUMENTS:
        text = path.read_text(encoding="utf-8")
        updated = refresh(text, study)
        if updated == text:
            print(f"up to date  {path.relative_to(ROOT)}")
            continue
        stale.append(path)
        if not check:
            path.write_text(updated, encoding="utf-8", newline="\n")  # LF on every system
            print(f"updated     {path.relative_to(ROOT)}")
    if check and stale:
        print(f"{len(stale)} document(s) out of date; run python tools/update_docs.py")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(check="--check" in sys.argv[1:]))
