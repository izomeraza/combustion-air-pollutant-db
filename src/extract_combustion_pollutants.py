#!/usr/bin/env python3
"""Extract unique combustion pollutants from the curated source-profile set.

This script uses the annotated profile filter as the scope definition:
`recommended_use == keep_for_v0_source_set`.

It joins the selected profiles to SPECIES and SPECIES_PROPERTIES, deduplicates
pollutants by CAS, and records which profile families each pollutant appears in
along with per-family frequency counts.
"""

from __future__ import annotations

import argparse
import csv
import re
from collections import Counter, defaultdict
from pathlib import Path


def read_csv_dicts(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def normalize_cas(row: dict[str, str]) -> str:
    cas = (row.get("CAS no hyphen") or row.get("CAS") or "").strip()
    if not cas:
        raise ValueError("selected species rows should all have CAS values")
    return cas


def is_real_cas(cas: str) -> bool:
    return bool(re.fullmatch(r"\d{5,10}", cas))


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract deduplicated combustion pollutants by CAS.")
    parser.add_argument(
        "--profiles",
        type=Path,
        default=Path("candidate_combustion_profiles_annotated_filter.csv"),
        help="Annotated profile filter CSV.",
    )
    parser.add_argument(
        "--species",
        type=Path,
        default=Path("data/raw/speciate_export/SPECIES.csv"),
        help="SPECIES export CSV.",
    )
    parser.add_argument(
        "--species-properties",
        type=Path,
        default=Path("data/raw/speciate_export/SPECIES_PROPERTIES.csv"),
        help="SPECIES_PROPERTIES export CSV.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("outputs/candidate_combustion_pollutants_by_cas.csv"),
        help="Output CSV path.",
    )
    args = parser.parse_args()

    profile_rows = read_csv_dicts(args.profiles)
    selected_profiles = {
        row["profile_code"]: row
        for row in profile_rows
        if row.get("recommended_use") == "keep_for_v0_source_set"
    }

    species_rows = read_csv_dicts(args.species)
    species_props_rows = read_csv_dicts(args.species_properties)
    props_by_species_id = {row["SPECIES_ID"]: row for row in species_props_rows}

    # Collect distinct profile-family occurrences by CAS.
    cas_to_profiles: dict[str, set[str]] = defaultdict(set)
    cas_to_families: dict[str, set[str]] = defaultdict(set)
    cas_to_species_ids: dict[str, set[str]] = defaultdict(set)
    cas_to_names: dict[str, Counter[str]] = defaultdict(Counter)

    for row in species_rows:
        profile_code = row.get("PROFILE_CODE", "")
        if profile_code not in selected_profiles:
            continue

        prop = props_by_species_id.get(row.get("SPECIES_ID", ""))
        if not prop:
            continue

        cas = normalize_cas(prop)
        if not is_real_cas(cas):
            continue
        family = (selected_profiles[profile_code].get("profile_family") or "").strip()
        species_name = (prop.get("SPECIES_NAME") or "").strip()

        cas_to_profiles[cas].add(profile_code)
        if family:
            cas_to_families[cas].add(family)
        cas_to_species_ids[cas].add(row.get("SPECIES_ID", ""))
        if species_name:
            cas_to_names[cas][species_name] += 1

    output_rows: list[dict[str, str]] = []
    for cas in sorted(cas_to_profiles):
        family_counts = Counter()
        for profile_code in cas_to_profiles[cas]:
            family = (selected_profiles[profile_code].get("profile_family") or "").strip()
            if family:
                family_counts[family] += 1

        canonical_name = ""
        if cas_to_names[cas]:
            canonical_name = cas_to_names[cas].most_common(1)[0][0]

        source_categories = "; ".join(sorted(cas_to_families[cas]))
        source_category_frequency = "; ".join(
            f"{family}:{family_counts[family]}" for family in sorted(family_counts)
        )

        output_rows.append(
            {
                "cas": cas,
                "species_name": canonical_name,
                "species_ids": "; ".join(sorted(cas_to_species_ids[cas])),
                "profile_count": str(len(cas_to_profiles[cas])),
                "source_categories": source_categories,
                "source_category_frequency": source_category_frequency,
            }
        )

    output_rows.sort(key=lambda row: (-int(row["profile_count"]), row["cas"]))
    write_csv(
        args.output,
        output_rows,
        [
            "cas",
            "species_name",
            "species_ids",
            "profile_count",
            "source_categories",
            "source_category_frequency",
        ],
    )

    print(f"wrote {len(output_rows)} pollutants to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
