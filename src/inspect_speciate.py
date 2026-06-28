#!/usr/bin/env python3
"""Inspect a SPECIATE .accdb database with mdbtools.

The script is read-only. It prints:
1. table names
2. columns per table
3. row counts
4. candidate tables for source profiles and chemical species

It also prints primary keys and relationship lines when available, because those
are directly relevant to interpreting profile/species linkage.
"""

from __future__ import annotations

import argparse
import collections
import dataclasses
import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable


@dataclasses.dataclass(frozen=True)
class TableInfo:
    name: str
    columns: list[str]
    primary_key: list[str]


@dataclasses.dataclass(frozen=True)
class Relationship:
    source_table: str
    source_columns: list[str]
    target_table: str
    target_columns: list[str]
    enforced: bool
    raw: str


CREATE_TABLE_RE = re.compile(r"^CREATE TABLE `([^`]+)`")
COLUMN_RE = re.compile(r"^\s*`([^`]+)`")
PRIMARY_KEY_RE = re.compile(r"ADD PRIMARY KEY \((.+)\);$")
FK_RE = re.compile(
    r"ALTER TABLE `([^`]+)` ADD CONSTRAINT `([^`]+)` FOREIGN KEY \((.+)\) REFERENCES `([^`]+)`\((.+)\)"
)
COMMENT_REL_RE = re.compile(
    r"^-- Relationship from `([^`]+)` \(([^)]+)\) to `([^`]+)`\(([^)]+)\) does not enforce integrity\.$"
)


def run_cmd(args: list[str]) -> str:
    result = subprocess.run(args, check=True, capture_output=True, text=True)
    return result.stdout


def parse_ident_list(text: str) -> list[str]:
    return [part.strip().strip("`") for part in text.split(",")]


def parse_schema(schema_text: str) -> tuple[dict[str, TableInfo], list[Relationship]]:
    tables: dict[str, list[str]] = {}
    primary_keys: dict[str, list[str]] = {}
    relationships: list[Relationship] = []
    current_table: str | None = None
    in_create = False

    for raw_line in schema_text.splitlines():
        line = raw_line.rstrip()
        if not line:
            continue

        create_match = CREATE_TABLE_RE.match(line)
        if create_match:
            current_table = create_match.group(1)
            tables[current_table] = []
            in_create = True
            continue

        if in_create and line.startswith(");"):
            current_table = None
            in_create = False
            continue

        if in_create and current_table:
            col_match = COLUMN_RE.match(line)
            if col_match:
                col_name = col_match.group(1)
                if col_name not in tables[current_table]:
                    tables[current_table].append(col_name)
            continue

        pk_match = PRIMARY_KEY_RE.search(line)
        if pk_match and current_table is None:
            # The last CREATE TABLE block is the one being amended.
            # mdb-schema emits ALTER TABLE immediately after each CREATE TABLE,
            # so we can recover the table name from the line itself.
            pass

        if line.startswith("ALTER TABLE `") and "ADD PRIMARY KEY" in line:
            table_name = line.split("`")[1]
            key_cols = parse_ident_list(pk_match.group(1)) if pk_match else []
            primary_keys[table_name] = key_cols
            continue

        fk_match = FK_RE.match(line)
        if fk_match:
            relationships.append(
                Relationship(
                    source_table=fk_match.group(1),
                    source_columns=parse_ident_list(fk_match.group(3)),
                    target_table=fk_match.group(4),
                    target_columns=parse_ident_list(fk_match.group(5)),
                    enforced=True,
                    raw=line,
                )
            )
            continue

        comment_rel_match = COMMENT_REL_RE.match(line)
        if comment_rel_match:
            relationships.append(
                Relationship(
                    source_table=comment_rel_match.group(1),
                    source_columns=parse_ident_list(comment_rel_match.group(2)),
                    target_table=comment_rel_match.group(3),
                    target_columns=parse_ident_list(comment_rel_match.group(4)),
                    enforced=False,
                    raw=line,
                )
            )

    table_infos = {
        name: TableInfo(
            name=name,
            columns=cols,
            primary_key=primary_keys.get(name, []),
        )
        for name, cols in tables.items()
    }
    return table_infos, relationships


def row_count(db_path: Path, table: str) -> int | None:
    try:
        output = run_cmd(["mdb-count", str(db_path), table]).strip()
    except subprocess.CalledProcessError as exc:
        sys.stderr.write(f"warning: failed to count rows for {table}: {exc}\n")
        return None

    match = re.search(r"(\d+)\s*$", output)
    if match:
        return int(match.group(1))
    return None


def candidate_tables(tables: Iterable[TableInfo]) -> dict[str, list[str]]:
    source_profile_keywords = ("profile", "reference", "crosswalk", "mnemonic", "result")
    species_keywords = ("species", "cas", "synonym", "oxide", "svoc")

    source_profile_tables: list[str] = []
    species_tables: list[str] = []

    for table in tables:
        name_l = table.name.lower()
        cols_l = " ".join(c.lower() for c in table.columns)

        if any(k in name_l for k in source_profile_keywords) or (
            "profile_code" in cols_l and "reference" in cols_l
        ):
            source_profile_tables.append(table.name)

        if any(k in name_l for k in species_keywords) or (
            "species_id" in cols_l and ("cas" in cols_l or "species_name" in cols_l)
        ):
            species_tables.append(table.name)

    return {
        "source_profiles": source_profile_tables,
        "chemical_species": species_tables,
    }


def print_section(title: str) -> None:
    print(f"\n{title}")
    print("-" * len(title))


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect a SPECIATE .accdb schema.")
    parser.add_argument(
        "database",
        nargs="?",
        default="SPECIATE 5.4 2025-09-08.accdb",
        help="Path to the Access .accdb file.",
    )
    args = parser.parse_args()

    db_path = Path(args.database)
    if not db_path.exists():
        raise SystemExit(f"database not found: {db_path}")

    try:
        tables_output = run_cmd(["mdb-tables", "-1", str(db_path)])
        schema_output = run_cmd(
            ["mdb-schema", str(db_path), "mysql", "--relations", "--indexes", "--no-comments"]
        )
    except FileNotFoundError as exc:
        raise SystemExit(
            "mdbtools commands not found. Install mdbtools first."
        ) from exc

    table_names = [line.strip() for line in tables_output.splitlines() if line.strip()]
    table_infos, relationships = parse_schema(schema_output)
    counts = {name: row_count(db_path, name) for name in table_names}
    candidates = candidate_tables(table_infos.values())

    print_section("Tables")
    for name in table_names:
        print(name)

    print_section("Columns, keys, and row counts")
    for name in table_names:
        info = table_infos.get(name, TableInfo(name=name, columns=[], primary_key=[]))
        count = counts.get(name)
        print(f"{name}")
        print(f"  rows: {count if count is not None else 'n/a'}")
        print(f"  primary_key: {', '.join(info.primary_key) if info.primary_key else 'none'}")
        print(f"  columns ({len(info.columns)}):")
        for column in info.columns:
            print(f"    - {column}")

    print_section("Relationships")
    if relationships:
        for rel in relationships:
            enforced = "enforced" if rel.enforced else "not enforced"
            print(
                f"{rel.source_table}({', '.join(rel.source_columns)}) -> "
                f"{rel.target_table}({', '.join(rel.target_columns)}) [{enforced}]"
            )
    else:
        print("none found")

    print_section("Candidate Tables")
    print("Source profiles:")
    for name in candidates["source_profiles"]:
        print(f"  - {name}")
    print("Chemical species:")
    for name in candidates["chemical_species"]:
        print(f"  - {name}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
