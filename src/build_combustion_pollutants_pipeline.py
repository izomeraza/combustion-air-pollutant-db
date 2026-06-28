#!/usr/bin/env python3
"""Run the pollutant enrichment pipeline end to end.

Stages:
- PubChem / CompTox enrichment
- ATSDR SPL join
- IARC classification join
- EPA IRIS toxicity join
- NIOSH Pocket Guide join

The final artifact is:
  outputs/candidate_combustion_pollutants_by_cas_pubchem.csv
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv" / "bin" / "python"
PUBCHEM_SCRIPT = ROOT / "src" / "enrich_pollutants_pubchem.py"
ATSDR_SCRIPT = ROOT / "src" / "enrich_pollutants_atsdr.py"
IARC_SCRIPT = ROOT / "src" / "enrich_pollutants_iarc.py"
IRIS_SCRIPT = ROOT / "src" / "enrich_pollutants_iris.py"
NIOSH_SCRIPT = ROOT / "src" / "enrich_pollutants_niosh.py"
DEFAULT_OUTPUT = ROOT / "outputs" / "candidate_combustion_pollutants_by_cas_pubchem.csv"


def run_step(label: str, script: Path, args: list[str]) -> None:
    print(f"==> {label}")
    python = PYTHON if PYTHON.exists() else Path(sys.executable)
    subprocess.run([str(python), str(script), *args], check=True, cwd=ROOT)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the combustion pollutant enrichment pipeline.")
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Final toxicity-enriched CSV output path.",
    )
    args = parser.parse_args()

    run_step("PubChem enrichment", PUBCHEM_SCRIPT, [])
    run_step("ATSDR SPL join", ATSDR_SCRIPT, [])
    run_step("IARC join", IARC_SCRIPT, [])
    run_step("IRIS join", IRIS_SCRIPT, ["--output", str(args.output)])
    run_step("NIOSH join", NIOSH_SCRIPT, ["--output", str(args.output)])

    print(f"done: wrote final pipeline output to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
