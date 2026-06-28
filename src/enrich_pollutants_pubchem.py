#!/usr/bin/env python3
"""Enrich deduplicated pollutants with PubChem, CompTox, and IARC data.

Input:
  outputs/candidate_combustion_pollutants_by_cas.csv

Output:
  outputs/candidate_combustion_pollutants_by_cas_pubchem.csv

Progress is checkpointed to:
  outputs/.pubchem_enrichment_cache.json

The script is intentionally resumable:
- PubChem results are cached by CAS.
- The enriched CSV is rewritten after each batch of new lookups.
- A rerun reuses the cache and continues from there.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any


DEFAULT_INPUT = Path("outputs/candidate_combustion_pollutants_by_cas.csv")
DEFAULT_OUTPUT = Path("outputs/candidate_combustion_pollutants_by_cas_pubchem.csv")
DEFAULT_CACHE = Path("outputs/.pubchem_enrichment_cache.json")

PUBCHEM_PHYSCHEM_HEADINGS: dict[str, tuple[str, ...]] = {
    "boiling_point": ("Boiling Point",),
    "melting_point": ("Melting Point",),
    "vapor_pressure": ("Vapor Pressure",),
    "logkow": ("LogP",),
    "water_solubility": ("Solubility",),
}

PUBCHEM_CARCINOGENICITY_HEADINGS: tuple[str, ...] = ("Carcinogenicity",)

PROPERTY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "boiling_point": ("boiling", "bp"),
    "melting_point": ("melting", "mp"),
    "vapor_pressure": ("vapor pressure", "vapour pressure", "vp"),
    "logkow": ("logkow", "log kow", "octanol-water partition", "partition coefficient", "kow", "logp"),
    "water_solubility": ("water solubility", "solubility", "in water"),
}

CARCINOGENICITY_KEYWORDS = (
    "iarc",
    "international agency for research on cancer",
    "group 1",
    "group 2a",
    "group 2b",
    "group 3",
    "not classifiable",
    "possibly carcinogenic",
    "probably carcinogenic",
    "carcinogenic",
)

COMPTOX_SEARCH_URLS = (
    "https://comptox.epa.gov/dashboard-api/ccdapp2/chemical-detail/search/by-cas/{cas}",
    "https://comptox.epa.gov/dashboard-api/ccdapp2/chemical-detail/search/by-cas/{cas}?format=json",
    "https://comptox.epa.gov/dashboard-api/ccdapp2/chemical-detail/search/by-casrn/{cas}",
    "https://comptox.epa.gov/dashboard-api/ccdapp2/chemical-detail/search/by-casrn/{cas}?format=json",
)


def read_csv_dicts(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv_atomic(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    tmp_path.replace(path)


def write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, sort_keys=True)
    tmp_path.replace(path)


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, dict) else {}


def normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize_cas(cas: str) -> str:
    return re.sub(r"[^0-9]", "", cas or "").strip()


def hyphenate_cas(cas: str) -> str:
    digits = normalize_cas(cas)
    if len(digits) < 3:
        return cas
    return f"{digits[:-3]}-{digits[-3:-1]}-{digits[-1]}"


def http_get_json(url: str, retries: int = 3, sleep_seconds: float = 1.5) -> Any:
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=45) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            last_exc = exc
            if attempt < retries - 1:
                time.sleep(sleep_seconds * (attempt + 1))
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("unreachable")


def extract_formula_and_weight(record_json: Any) -> tuple[str, str]:
    compounds = record_json.get("PC_Compounds") or []
    if not compounds:
        return "", ""
    props = compounds[0].get("props") or []
    formula = ""
    weight = ""
    for prop in props:
        urn = prop.get("urn") or {}
        label = urn.get("label")
        value = prop.get("value") or {}
        if label == "Molecular Formula" and not formula:
            formula = str(value.get("sval") or "").strip()
        elif label == "Molecular Weight" and not weight:
            weight = str(value.get("sval") or "").strip()
    return formula, weight


def extract_synonyms(synonyms_json: Any, limit: int | None = None) -> list[str]:
    info = (synonyms_json.get("InformationList") or {}).get("Information") or []
    if not info:
        return []
    synonyms = info[0].get("Synonym") or []
    unique = list(dict.fromkeys(str(s).strip() for s in synonyms if str(s).strip()))
    if limit is not None:
        unique = unique[:limit]
    return unique


def value_to_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (str, int, float)):
        return normalize_text(value)
    if isinstance(value, dict):
        if "StringWithMarkup" in value:
            parts = [normalize_text(item.get("String")) for item in value.get("StringWithMarkup") or []]
            parts = [part for part in parts if part]
            return " | ".join(parts)
        if "String" in value:
            return normalize_text(value.get("String"))
        if "Number" in value:
            numbers = value.get("Number") or []
            return " | ".join(normalize_text(n) for n in numbers if normalize_text(n))
        if "sval" in value:
            return normalize_text(value.get("sval"))
        if "fval" in value:
            return normalize_text(value.get("fval"))
        if "ival" in value:
            return normalize_text(value.get("ival"))
    return normalize_text(value)


def collect_section_values(section: Any) -> list[str]:
    values: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            info = node.get("Information") or []
            for item in info:
                text = value_to_text(item.get("Value"))
                if text:
                    values.append(text)
            for child in node.get("Section") or []:
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(section)
    unique: list[str] = []
    for text in values:
        if text not in unique:
            unique.append(text)
    return unique


def find_section_by_heading(sections: Any, heading: str) -> Any:
    target = normalize_text(heading).lower()

    def walk(node: Any) -> Any:
        if isinstance(node, list):
            for child in node:
                found = walk(child)
                if found is not None:
                    return found
        elif isinstance(node, dict):
            toc = normalize_text(node.get("TOCHeading") or node.get("Name")).lower()
            if toc == target:
                return node
            found = walk(node.get("Section") or [])
            if found is not None:
                return found
        return None

    return walk(sections)


def choose_preferred_value(values: list[str], target: str) -> str:
    if not values:
        return ""

    targets = PROPERTY_KEYWORDS[target]
    for needle in targets:
        for value in values:
            if needle in value.lower():
                return value

    if target in {"boiling_point", "melting_point"}:
        for value in values:
            if "°c" in value.lower():
                return value
    if target == "vapor_pressure":
        for value in values:
            if "25 °c" in value.lower() or "25°c" in value.lower():
                return value
    return values[0]


def choose_carcinogenicity_value(values: list[str]) -> str:
    if not values:
        return ""

    for needle in CARCINOGENICITY_KEYWORDS:
        for value in values:
            if needle in value.lower():
                return value

    return values[0]


def extract_pubchem_heading_value(cid: str, heading: str, target: str) -> str:
    encoded = urllib.parse.quote(heading, safe="")
    url = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug_view/data/compound/{cid}/JSON?heading={encoded}"
    data = http_get_json(url)
    section = find_section_by_heading((data.get("Record") or {}).get("Section") or [], heading)
    if not section:
        return ""
    values = collect_section_values(section)
    return choose_preferred_value(values, target)


def extract_pubchem_carcinogenicity_value(cid: str) -> str:
    for heading in PUBCHEM_CARCINOGENICITY_HEADINGS:
        encoded = urllib.parse.quote(heading, safe="")
        url = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug_view/data/compound/{cid}/JSON?heading={encoded}"
        data = http_get_json(url)
        section = find_section_by_heading((data.get("Record") or {}).get("Section") or [], heading)
        if not section:
            continue
        values = collect_section_values(section)
        chosen = choose_carcinogenicity_value(values)
        if chosen:
            return chosen
    return ""


def parse_iarc_group(text: str) -> str:
    low = normalize_text(text).lower()
    if not low:
        return ""

    patterns = (
        r"\bgroup\s*1\b",
        r"\bgroup\s*2a\b",
        r"\bgroup\s*2b\b",
        r"\bgroup\s*3\b",
        r"\bnot\s+classifiable\b",
    )
    for pattern in patterns:
        match = re.search(pattern, low, re.I)
        if match:
            value = match.group(0).upper().replace("  ", " ")
            return value.replace("GROUP", "Group")
    return ""


def extract_comptox_value(payload: Any, target: str) -> str:
    keywords = PROPERTY_KEYWORDS[target]
    candidates: list[str] = []

    def walk(node: Any, parent_keys: tuple[str, ...] = ()) -> None:
        if isinstance(node, dict):
            lower_keys = {normalize_text(key).lower(): key for key in node.keys()}
            joined_keys = " ".join(lower_keys.keys())
            label = ""
            for key in ("name", "label", "property", "title", "parameter", "analyte"):
                if key in lower_keys:
                    label = normalize_text(node.get(lower_keys[key])).lower()
                    break
            hint = " ".join([joined_keys, label])
            if any(needle in hint for needle in keywords):
                for key in (
                    "value",
                    "Value",
                    "val",
                    "result",
                    "text",
                    "displayValue",
                    "formattedValue",
                    "measurement",
                    "amount",
                    "data",
                ):
                    if key in node:
                        text = value_to_text(node.get(key))
                        if text:
                            candidates.append(text)
                            break
            for key, value in node.items():
                walk(value, parent_keys + (normalize_text(key).lower(),))
        elif isinstance(node, list):
            for item in node:
                walk(item, parent_keys)
        else:
            text = value_to_text(node)
            if not text:
                return
            joined = " ".join(parent_keys)
            if any(needle in joined for needle in keywords):
                candidates.append(text)

    walk(payload)

    unique: list[str] = []
    for text in candidates:
        if text and text not in unique:
            unique.append(text)
    return choose_preferred_value(unique, target)


def search_comptox_payload(cas: str) -> Any:
    rn = hyphenate_cas(cas)
    encoded = urllib.parse.quote(rn, safe="")
    last_error: Exception | None = None
    for template in COMPTOX_SEARCH_URLS:
        url = template.format(cas=encoded)
        try:
            payload = http_get_json(url, retries=2, sleep_seconds=0.5)
            if payload:
                return payload
        except Exception as exc:
            last_error = exc
            continue
    if last_error is not None:
        raise last_error
    return {}


def search_cids_by_cas(cas: str) -> list[int]:
    rn = hyphenate_cas(cas)
    encoded = urllib.parse.quote(rn, safe="")
    for url in (
        f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/xref/RN/{encoded}/cids/JSON",
        f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{encoded}/cids/JSON",
    ):
        try:
            data = http_get_json(url)
            cid_list = (data.get("IdentifierList") or {}).get("CID") or []
            if cid_list:
                return [int(cid) for cid in cid_list]
        except Exception:
            continue
    return []


def lookup_pubchem_basics(cas: str, synonym_limit: int | None = None) -> dict[str, str]:
    cids = search_cids_by_cas(cas)
    if not cids:
        return {
            "pubchem_cid": "",
            "molecular_formula": "",
            "molecular_weight": "",
            "synonyms": "",
        }

    chosen_cid = ""
    molecular_formula = ""
    molecular_weight = ""
    synonyms: list[str] = []

    for cid in cids:
        try:
            record_json = http_get_json(
                f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/{cid}/record/JSON"
            )
            formula, weight = extract_formula_and_weight(record_json)
            if formula or weight:
                chosen_cid = str(cid)
                molecular_formula = formula
                molecular_weight = weight
                try:
                    synonyms_json = http_get_json(
                        f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/{cid}/synonyms/JSON"
                    )
                    synonyms = extract_synonyms(synonyms_json, limit=synonym_limit)
                except Exception:
                    synonyms = []
                break
        except Exception:
            continue

    if not chosen_cid:
        chosen_cid = str(cids[0])
        try:
            record_json = http_get_json(
                f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/{chosen_cid}/record/JSON"
            )
            molecular_formula, molecular_weight = extract_formula_and_weight(record_json)
        except Exception:
            pass
        try:
            synonyms_json = http_get_json(
                f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/{chosen_cid}/synonyms/JSON"
            )
            synonyms = extract_synonyms(synonyms_json, limit=synonym_limit)
        except Exception:
            synonyms = []

    return {
        "pubchem_cid": chosen_cid,
        "molecular_formula": molecular_formula,
        "molecular_weight": molecular_weight,
        "synonyms": "; ".join(synonyms),
    }


def lookup_physchem(cas: str, pubchem_cid: str | None = None) -> dict[str, str]:
    result = {
        "boiling_point": "",
        "boiling_point_source": "",
        "melting_point": "",
        "melting_point_source": "",
        "vapor_pressure": "",
        "vapor_pressure_source": "",
        "logkow": "",
        "logkow_source": "",
        "water_solubility": "",
        "water_solubility_source": "",
    }

    cid = (pubchem_cid or "").strip()
    if not cid:
        cids = search_cids_by_cas(cas)
        if cids:
            cid = str(cids[0])

    if cid:
        for target, headings in PUBCHEM_PHYSCHEM_HEADINGS.items():
            value = ""
            for heading in headings:
                try:
                    value = extract_pubchem_heading_value(cid, heading, target)
                except Exception:
                    value = ""
                if value:
                    break
            if value:
                result[target] = value
                result[f"{target}_source"] = "pubchem"

    if not all(result[key] for key in ("boiling_point", "melting_point", "vapor_pressure", "logkow", "water_solubility")):
        try:
            comptox_payload = search_comptox_payload(cas)
        except Exception:
            comptox_payload = {}
        if comptox_payload:
            for target in PUBCHEM_PHYSCHEM_HEADINGS:
                if result[target]:
                    continue
                value = extract_comptox_value(comptox_payload, target)
                if value:
                    result[target] = value
                    result[f"{target}_source"] = "comptox"

    return result


def lookup_carcinogenicity(cas: str, pubchem_cid: str | None = None) -> dict[str, str]:
    result = {
        "iarc_carcinogenicity": "",
        "iarc_group": "",
        "iarc_carcinogenicity_source": "",
    }

    cid = (pubchem_cid or "").strip()
    if not cid:
        cids = search_cids_by_cas(cas)
        if cids:
            cid = str(cids[0])

    if cid:
        try:
            value = extract_pubchem_carcinogenicity_value(cid)
        except Exception:
            value = ""
        if value:
            result["iarc_carcinogenicity"] = value
            result["iarc_group"] = parse_iarc_group(value)
            result["iarc_carcinogenicity_source"] = "pubchem"

    return result


def enrich_cas_entry(cas: str, existing: dict[str, str], synonym_limit: int | None = None) -> dict[str, str]:
    enriched = dict(existing)
    basics_needed = any(
        key not in enriched
        for key in ("pubchem_cid", "molecular_formula", "molecular_weight", "synonyms")
    )
    if basics_needed:
        enriched.update(lookup_pubchem_basics(cas, synonym_limit=synonym_limit))

    physchem_keys = (
        "boiling_point",
        "boiling_point_source",
        "melting_point",
        "melting_point_source",
        "vapor_pressure",
        "vapor_pressure_source",
        "logkow",
        "logkow_source",
        "water_solubility",
        "water_solubility_source",
    )
    if any(key not in enriched for key in physchem_keys):
        enriched.update(lookup_physchem(cas, enriched.get("pubchem_cid")))

    iarc_keys = ("iarc_carcinogenicity", "iarc_group", "iarc_carcinogenicity_source")
    if any(key not in enriched for key in iarc_keys):
        enriched.update(lookup_carcinogenicity(cas, enriched.get("pubchem_cid")))

    for key in physchem_keys:
        enriched.setdefault(key, "")
    for key in iarc_keys:
        enriched.setdefault(key, "")
    return enriched


def main() -> int:
    parser = argparse.ArgumentParser(description="Enrich combustion pollutants with PubChem and IARC data.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument(
        "--synonym-limit",
        type=int,
        default=50,
        help="Maximum PubChem synonyms to keep per pollutant. Use 0 for no limit.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=25,
        help="Write cache/output after this many new CAS lookups.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=8,
        help="Maximum concurrent PubChem lookups.",
    )
    args = parser.parse_args()

    if not args.input.exists():
        raise SystemExit(f"input file not found: {args.input}")

    input_rows = read_csv_dicts(args.input)
    cache = load_json(args.cache)
    cas_cache: dict[str, dict[str, str]] = cache.get("cas_cache", {}) if isinstance(cache.get("cas_cache"), dict) else {}

    fieldnames = list(input_rows[0].keys()) + [
        "pubchem_cid",
        "molecular_formula",
        "molecular_weight",
        "synonyms",
        "boiling_point",
        "boiling_point_source",
        "melting_point",
        "melting_point_source",
        "vapor_pressure",
        "vapor_pressure_source",
        "logkow",
        "logkow_source",
        "water_solubility",
        "water_solubility_source",
        "iarc_carcinogenicity",
        "iarc_group",
        "iarc_carcinogenicity_source",
    ]

    ordered_unique_cas: list[str] = []
    seen_cas: set[str] = set()
    for row in input_rows:
        cas = (row.get("cas") or "").strip()
        if cas not in seen_cas:
            seen_cas.add(cas)
            ordered_unique_cas.append(cas)

    required_keys = {
        "pubchem_cid",
        "molecular_formula",
        "molecular_weight",
        "synonyms",
        "boiling_point",
        "boiling_point_source",
        "melting_point",
        "melting_point_source",
        "vapor_pressure",
        "vapor_pressure_source",
        "logkow",
        "logkow_source",
        "water_solubility",
        "water_solubility_source",
        "iarc_carcinogenicity",
        "iarc_group",
        "iarc_carcinogenicity_source",
    }
    missing_cas = [
        cas for cas in ordered_unique_cas if any(key not in cas_cache.get(cas, {}) for key in required_keys)
    ]
    total_new = 0
    synonym_limit = None if args.synonym_limit == 0 else args.synonym_limit

    if missing_cas:
        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
            future_to_cas = {
                executor.submit(enrich_cas_entry, cas, cas_cache.get(cas, {}), synonym_limit): cas
                for cas in missing_cas
            }
            for future in as_completed(future_to_cas):
                cas = future_to_cas[future]
                try:
                    cas_cache[cas] = future.result()
                except Exception:
                    cas_cache[cas] = {
                        "pubchem_cid": "",
                        "molecular_formula": "",
                        "molecular_weight": "",
                        "synonyms": "",
                        "boiling_point": "",
                        "boiling_point_source": "",
                        "melting_point": "",
                        "melting_point_source": "",
                        "vapor_pressure": "",
                        "vapor_pressure_source": "",
                        "logkow": "",
                        "logkow_source": "",
                        "water_solubility": "",
                        "water_solubility_source": "",
                        "iarc_carcinogenicity": "",
                        "iarc_group": "",
                        "iarc_carcinogenicity_source": "",
                    }
                total_new += 1

                if total_new % args.batch_size == 0:
                    write_json_atomic(args.cache, {"cas_cache": cas_cache})
                    for idx, row in enumerate(input_rows):
                        cas_i = (row.get("cas") or "").strip()
                        enriched = dict(row)
                        enriched.update(cas_cache.get(cas_i, {}))
                        input_rows[idx] = enriched
                    write_csv_atomic(args.output, input_rows, fieldnames)
                    print(
                        f"checkpoint: {total_new} new CAS lookups cached; wrote {len(input_rows)} rows"
                    )

    for idx, row in enumerate(input_rows):
        cas = (row.get("cas") or "").strip()
        enriched = dict(row)
        enriched.update(cas_cache.get(cas, {}))
        input_rows[idx] = enriched

    write_json_atomic(args.cache, {"cas_cache": cas_cache})
    write_csv_atomic(args.output, input_rows, fieldnames)
    print(f"done: wrote {len(input_rows)} enriched rows to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
