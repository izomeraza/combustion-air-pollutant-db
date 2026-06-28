#!/usr/bin/env python3
"""Join pollutants with IARC classification data.

Matching order:
- exact normalized CAS
- conservative normalized agent name

Output fields are appended to the working pollutant CSV.
"""

from __future__ import annotations

import argparse
import csv
import re
from collections import defaultdict
from pathlib import Path


DEFAULT_INPUT = Path("outputs/candidate_combustion_pollutants_by_cas_pubchem.csv")
DEFAULT_IARC = Path(
    "List of Classifications – IARC Monographs on the Identification of Carcinogenic Hazards to Humans.csv"
)
DEFAULT_OUTPUT = Path("outputs/candidate_combustion_pollutants_by_cas_pubchem_iarc.csv")


def read_csv_dicts(path: Path, encoding: str = "utf-8") -> list[dict[str, str]]:
    with path.open(newline="", encoding=encoding) as f:
        return list(csv.DictReader(f))


def write_csv_atomic(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    tmp_path.replace(path)


def normalize_cas(value: str) -> str:
    return re.sub(r"[^0-9]", "", (value or "").strip())


def normalize_text(value: str) -> str:
    text = (value or "").strip().lower()
    text = text.replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def split_name_variants(value: str) -> list[str]:
    text = (value or "").strip()
    if not text:
        return []

    parts = [text]
    for separator in (" (or ", " || ", " or "):
        next_parts: list[str] = []
        for part in parts:
            next_parts.extend(re.split(re.escape(separator), part))
        parts = next_parts

    variants: list[str] = []
    for part in parts:
        cleaned = part.strip(" ()[]{};,.")
        cleaned = normalize_text(cleaned)
        if cleaned and cleaned not in variants:
            variants.append(cleaned)
    return variants


def append_missing(fieldnames: list[str], candidates: list[str]) -> list[str]:
    out = list(fieldnames)
    for candidate in candidates:
        if candidate not in out:
            out.append(candidate)
    return out


def merge_records(records: list[dict[str, str]]) -> dict[str, str]:
    if not records:
        return {
            "iarc_agent": "",
            "iarc_group": "",
            "iarc_volume": "",
            "iarc_volume_publication_year": "",
            "iarc_evaluation_year": "",
            "iarc_additional_information": "",
        }

    def unique_values(key: str) -> str:
        values: list[str] = []
        for record in records:
            value = (record.get(key, "") or "").strip()
            if value and value not in values:
                values.append(value)
        return " | ".join(values)

    return {
        "iarc_agent": unique_values("Agent"),
        "iarc_group": unique_values("Group"),
        "iarc_volume": unique_values("Volume"),
        "iarc_volume_publication_year": unique_values("Volume publication year"),
        "iarc_evaluation_year": unique_values("Evaluation year"),
        "iarc_additional_information": unique_values("Additional information"),
    }


def build_indexes(iarc_rows: list[dict[str, str]]) -> tuple[dict[str, list[dict[str, str]]], dict[str, list[dict[str, str]]]]:
    by_cas: dict[str, list[dict[str, str]]] = defaultdict(list)
    by_name: dict[str, list[dict[str, str]]] = defaultdict(list)

    for row in iarc_rows:
        cas = normalize_cas(row.get("CAS No.", ""))
        if cas:
            by_cas[cas].append(row)

        for variant in split_name_variants(row.get("Agent", "")):
            by_name[variant].append(row)

    return by_cas, by_name


def join_rows(
    work_rows: list[dict[str, str]],
    by_cas: dict[str, list[dict[str, str]]],
    by_name: dict[str, list[dict[str, str]]],
) -> tuple[list[dict[str, str]], dict[str, int]]:
    joined_rows: list[dict[str, str]] = []
    stats = {"matched_rows": 0, "cas_matches": 0, "name_matches": 0}

    for row in work_rows:
        cas = normalize_cas(row.get("cas", ""))
        matched_records: list[dict[str, str]] = []
        match_method = ""

        if cas and cas in by_cas:
            matched_records = by_cas[cas]
            match_method = "cas"
            stats["cas_matches"] += 1
        else:
            name_variants = split_name_variants(row.get("species_name", ""))
            for variant in name_variants:
                if variant in by_name:
                    matched_records = by_name[variant]
                    match_method = "name"
                    stats["name_matches"] += 1
                    break

        enriched = dict(row)
        enriched.update(merge_records(matched_records))
        enriched["iarc_match_method"] = match_method
        enriched["iarc_match_count"] = str(len(matched_records))
        if matched_records:
            stats["matched_rows"] += 1
        joined_rows.append(enriched)

    return joined_rows, stats


def main() -> int:
    parser = argparse.ArgumentParser(description="Join pollutants with IARC classifications.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--iarc", type=Path, default=DEFAULT_IARC)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    if not args.input.exists():
        raise SystemExit(f"input file not found: {args.input}")
    if not args.iarc.exists():
        raise SystemExit(f"IARC file not found: {args.iarc}")

    work_rows = read_csv_dicts(args.input)
    iarc_rows = read_csv_dicts(args.iarc, encoding="utf-8-sig")
    by_cas, by_name = build_indexes(iarc_rows)
    joined_rows, stats = join_rows(work_rows, by_cas, by_name)

    fieldnames = append_missing(
        list(work_rows[0].keys()),
        [
            "iarc_agent",
            "iarc_group",
            "iarc_volume",
            "iarc_volume_publication_year",
            "iarc_evaluation_year",
            "iarc_additional_information",
            "iarc_match_method",
            "iarc_match_count",
        ],
    )
    write_csv_atomic(args.output, joined_rows, fieldnames)

    total = len(work_rows)
    print(
        f"wrote {len(joined_rows)} rows to {args.output} "
        f"with {stats['matched_rows']}/{total} matched rows ({stats['matched_rows'] / total:.1%})"
    )
    print(f"CAS matches: {stats['cas_matches']}, name matches: {stats['name_matches']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
