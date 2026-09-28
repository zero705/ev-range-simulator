"""Run every check of the data and the documents, and summarise the result.

    python tools/verify_all.py              # with the documents already in data/sources/
    python tools/verify_all.py --download   # fetch the EPA certificates and the regulations first

A check whose document is not in data/sources/ reports it as skipped instead of failing;
docs/data-sources.md says where each document comes from. Re-reading the EPA certificates
rewrites data/epa_certification.json, so the run also fails if that file changes.

Usage:
    python tools/verify_all.py [--download]
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CERTIFICATES = ROOT / "data" / "epa_certification.json"


def steps(download: bool) -> list[tuple[str, list[str]]]:
    fetch = ["--download"] if download else []
    return [
        ("drive cycles against the regulators' figures", ["tools/check_cycles.py"]),
        (
            "drive cycles second by second against the regulations",
            ["tools/verify_cycles.py", *fetch],
        ),
        ("EPA certificates re-read", ["tools/epa_certification.py", *fetch]),
        ("reference values against their documents", ["tools/verify_references.py"]),
        ("manufacturer facts against their documents", ["tools/verify_manufacturer.py"]),
        (
            "tables of README.md and docs/method.md against the model",
            ["tools/update_docs.py", "--check"],
        ),
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--download", action="store_true", help="fetch the documents first")
    args = parser.parse_args()
    before = CERTIFICATES.read_bytes()
    results = []
    for name, command in steps(args.download):
        print(f"\n=== {name}: python {' '.join(command)}", flush=True)
        # This interpreter, with the fixed script list above; no shell and no outside input.
        completed = subprocess.run([sys.executable, *command], cwd=ROOT, check=False)  # noqa: S603
        results.append((name, completed.returncode == 0))
    results.append(("data/epa_certification.json unchanged", CERTIFICATES.read_bytes() == before))
    print("\nsummary")
    for name, ok in results:
        print(f"  {'ok  ' if ok else 'FAIL'}  {name}")
    failed = sum(not ok for _, ok in results)
    print("\neverything verified" if not failed else f"\n{failed} check(s) failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
