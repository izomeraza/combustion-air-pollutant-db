#!/usr/bin/env python3
"""Extract brief ATSDR health-hazard summaries.

Preferred path:
- discover ATSDR toxicological profile pages from the hub,
- fetch the complete profile PDF,
- extract a short summary from the relevant PDF pages,
- optionally attach MRL rows when a CAS number is detected.

This is intentionally shallow. The goal is a brief health hazard summary, not
full toxicological profile normalization.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from probe_atsdr import (
    BASE,
    MRL_URL,
    PROFILE_HUB,
    extract_profile_links,
    find_pdf_links,
    http_get,
    http_get_bytes,
    parse_mrl_table,
    write_csv,
)


DEFAULT_OUTDIR = Path("outputs/atsdr_summaries")
DEFAULT_CACHE = Path("outputs/.atsdr_summary_cache.json")
CAS_RE = re.compile(r"\b\d{2,7}-\d{2}-\d\b")


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, dict) else {}


def write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, sort_keys=True)
    tmp_path.replace(path)


def clean_text(text: str) -> str:
    text = re.sub(r"\r", "\n", text or "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            lines.append("")
            continue
        if stripped.startswith("***DRAFT FOR PUBLIC COMMENT***"):
            continue
        if re.fullmatch(r"[A-Z][A-Z0-9 ,&\-\(\)\/]{2,}", stripped) and len(stripped) < 120:
            # Common page headers / running headers.
            continue
        lines.append(stripped)
    return "\n".join(lines)


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def sentence_prefix(text: str, limit: int = 3) -> str:
    text = normalize_space(text)
    if not text:
        return ""
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", text)
    out: list[str] = []
    for part in parts:
        if part:
            out.append(part.strip())
        if len(out) >= limit:
            break
    if not out:
        return text[:900]
    return " ".join(out)


def find_complete_profile_pdf(profile_html: str) -> str:
    pdf_links = find_pdf_links(profile_html)
    for link in pdf_links:
        if link.lower().endswith(".pdf"):
            return link
    return ""


def choose_summary_page(pages: list[str]) -> int:
    best_idx = 0
    best_score = -1
    for idx, text in enumerate(pages[:60]):
        low = text.lower()
        score = 0
        if "relevance to public health" in low:
            score += 100
        if "public health statement" in low:
            score += 80
        if "health effects summary" in low:
            score += 70
        if "summary" in low:
            score += 20
        if "carcinogenicity" in low:
            score += 15
        if "health effects" in low:
            score += 10
        if len(text) > 500:
            score += 5
        if idx < 5:
            score -= 10
        if "table of contents" in low:
            score -= 50
        if "........" in text:
            score -= 30
        if score > best_score:
            best_score = score
            best_idx = idx
    return best_idx


def extract_pdf_brief_summary(pdf_bytes: bytes) -> dict[str, Any]:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    pages = [clean_text((page.extract_text() or "")) for page in reader.pages[:80]]
    summary_idx = choose_summary_page(pages)
    window = "\n\n".join(pages[summary_idx : min(summary_idx + 2, len(pages))])
    window = normalize_space(window)

    heading_match = re.search(
        r"(relevance to public health|public health statement|health effects summary|summary|health effects|carcinogenicity)",
        window,
        re.I,
    )
    if heading_match:
        window = window[heading_match.start() :]
    brief = sentence_prefix(window, limit=3)

    cas_candidates = Counter(CAS_RE.findall("\n".join(pages[:20])))
    cas = cas_candidates.most_common(1)[0][0] if cas_candidates else ""

    return {
        "summary": brief,
        "summary_page": str(summary_idx + 1),
        "cas": cas,
        "page_count": str(len(reader.pages)),
    }


def build_mrl_index(mrl_rows: list[list[str]], header: list[str]) -> dict[str, list[dict[str, str]]]:
    idx: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in mrl_rows:
        if len(row) != len(header):
            continue
        record = dict(zip(header, row))
        cas = record.get("CAS Number", "").strip()
        if cas:
            idx[cas].append(record)
    return idx


def summarize_mrl_rows(rows: list[dict[str, str]], limit: int = 2) -> str:
    if not rows:
        return ""
    parts = []
    for row in rows[:limit]:
        parts.append(
            f"{row.get('Route', '')} {row.get('Duration', '')} {row.get('MRL', '')} "
            f"({row.get('Endpoint', '')}, {row.get('Draft/ Final', '')}, {row.get('Cover Date', '')})".strip()
        )
    return " ; ".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract brief ATSDR health hazard summaries.")
    parser.add_argument("--outdir", type=Path, default=DEFAULT_OUTDIR)
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--profile-sample", type=int, default=0, help="If >0, limit to this many profiles.")
    parser.add_argument("--force", action="store_true", help="Ignore cache and re-extract.")
    args = parser.parse_args()

    outdir = args.outdir
    outdir.mkdir(parents=True, exist_ok=True)

    cache = load_json(args.cache)
    summary_cache: dict[str, Any] = cache.get("summary_cache", {}) if isinstance(cache.get("summary_cache"), dict) else {}

    hub_html = http_get(PROFILE_HUB)
    profile_links = extract_profile_links(hub_html)
    if args.profile_sample > 0:
        profile_links = profile_links[: args.profile_sample]

    mrl_html = http_get(MRL_URL)
    mrl_header, mrl_rows = parse_mrl_table(mrl_html)
    mrl_index = build_mrl_index(mrl_rows, mrl_header)

    output_rows: list[dict[str, str]] = []
    for idx, (title, profile_url) in enumerate(profile_links, start=1):
        if not args.force and profile_url in summary_cache:
            enriched = summary_cache[profile_url]
        else:
            profile_html = http_get(profile_url)
            pdf_url = find_complete_profile_pdf(profile_html) or ""
            pdf_bytes = http_get_bytes(pdf_url) if pdf_url else b""
            pdf_summary = extract_pdf_brief_summary(pdf_bytes) if pdf_bytes else {"summary": "", "summary_page": "", "cas": "", "page_count": ""}
            cas = pdf_summary.get("cas", "")
            mrl_summary = summarize_mrl_rows(mrl_index.get(cas, [])) if cas else ""
            enriched = {
                "profile_title": title,
                "profile_url": profile_url,
                "pdf_url": pdf_url,
                "cas": cas,
                "page_count": pdf_summary.get("page_count", ""),
                "summary_page": pdf_summary.get("summary_page", ""),
                "brief_health_hazard_summary": pdf_summary.get("summary", ""),
                "mrl_summary": mrl_summary,
                "mrl_match_count": str(len(mrl_index.get(cas, []))) if cas else "0",
            }
            summary_cache[profile_url] = enriched
            write_json_atomic(args.cache, {"summary_cache": summary_cache})

        output_rows.append(
            {
                "profile_title": enriched.get("profile_title", ""),
                "profile_url": enriched.get("profile_url", ""),
                "pdf_url": enriched.get("pdf_url", ""),
                "cas": enriched.get("cas", ""),
                "page_count": enriched.get("page_count", ""),
                "summary_page": enriched.get("summary_page", ""),
                "brief_health_hazard_summary": enriched.get("brief_health_hazard_summary", ""),
                "mrl_summary": enriched.get("mrl_summary", ""),
                "mrl_match_count": enriched.get("mrl_match_count", ""),
            }
        )

        write_csv(
            outdir / "atsdr_brief_summaries.csv",
            output_rows,
            [
                "profile_title",
                "profile_url",
                "pdf_url",
                "cas",
                "page_count",
                "summary_page",
                "brief_health_hazard_summary",
                "mrl_summary",
                "mrl_match_count",
            ],
        )
        print(f"checkpoint {idx}/{len(profile_links)}: {title}")

    print(f"wrote {len(output_rows)} rows to {outdir / 'atsdr_brief_summaries.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
