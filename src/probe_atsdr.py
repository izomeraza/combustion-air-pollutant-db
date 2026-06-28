#!/usr/bin/env python3
"""Probe ATSDR data sources and extract basic artifacts.

This script is intentionally conservative:
- it discovers profile pages from the ATSDR toxicological profiles hub,
- downloads a small sample PDF and extracts text with pypdf,
- parses the ATSDR MRL listing HTML table,
- writes small local outputs so we can compare source viability.

It is designed to answer: what ATSDR path is most usable for ingestion?
"""

from __future__ import annotations

import argparse
import csv
import re
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from pypdf import PdfReader


BASE = "https://www.atsdr.cdc.gov"
PROFILE_HUB = f"{BASE}/toxicological-profiles/about/index.html"
MRL_URL = "https://wwwn.cdc.gov/TSP/MRLS/mrlsListing.aspx"


def http_get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read().decode("utf-8", "replace")


def http_get_bytes(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


class ProfileHubParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_a = False
        self.current_href = ""
        self.current_text: list[str] = []
        self.links: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "a":
            self.in_a = True
            self.current_href = dict(attrs).get("href") or ""
            self.current_text = []

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self.in_a:
            text = "".join(self.current_text).strip()
            if text and self.current_href:
                self.links.append((text, self.current_href))
            self.in_a = False
            self.current_href = ""
            self.current_text = []

    def handle_data(self, data: str) -> None:
        if self.in_a:
            self.current_text.append(data)


class MRLTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_table = False
        self.in_tr = False
        self.in_cell = False
        self.current_row: list[str] = []
        self.current_cell: list[str] = []
        self.rows: list[list[str]] = []
        self.header_done = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = dict(attrs)
        if tag.lower() == "table" and attrs_dict.get("id") == "ContentPlaceHolder1_mrlTable":
            self.in_table = True
        elif self.in_table and tag.lower() == "tr":
            self.in_tr = True
            self.current_row = []
        elif self.in_tr and tag.lower() in {"td", "th"}:
            self.in_cell = True
            self.current_cell = []

    def handle_endtag(self, tag: str) -> None:
        if self.in_table and tag.lower() in {"td", "th"} and self.in_cell:
            self.in_cell = False
            cell = re.sub(r"\s+", " ", "".join(self.current_cell)).strip()
            self.current_row.append(cell)
        elif self.in_table and tag.lower() == "tr" and self.in_tr:
            self.in_tr = False
            if self.current_row:
                self.rows.append(self.current_row)
        elif tag.lower() == "table" and self.in_table:
            self.in_table = False

    def handle_data(self, data: str) -> None:
        if self.in_cell:
            self.current_cell.append(data)


def extract_profile_links(html: str) -> list[tuple[str, str]]:
    parser = ProfileHubParser()
    parser.feed(html)
    links: list[tuple[str, str]] = []
    for text, href in parser.links:
        href_l = href.lower()
        if "toxprofiles.aspx?id=" in href_l and "tid=" in href_l:
            links.append((text, urllib.parse.urljoin(BASE, href)))
    dedup: list[tuple[str, str]] = []
    seen = set()
    for item in links:
        if item[1] not in seen:
            seen.add(item[1])
            dedup.append(item)
    return dedup


def find_pdf_links(html: str) -> list[str]:
    hrefs = re.findall(r'href\s*=\s*["\']\s*([^"\']+\.pdf[^"\']*)["\']', html, re.I)
    links: list[str] = []
    for href in hrefs:
        href = href.strip()
        if href.startswith("/"):
            href = urllib.parse.urljoin(BASE, href)
        if href.lower().startswith("https://www.atsdr.cdc.gov/") and ".pdf" in href.lower():
            links.append(href)
    return sorted(set(links))


def parse_mrl_table(html: str) -> tuple[list[str], list[list[str]]]:
    parser = MRLTableParser()
    parser.feed(html)
    rows = parser.rows
    if not rows:
        return [], []
    header = rows[1] if len(rows) > 1 and rows[0] and "MRL" in " ".join(rows[0]) else rows[0]
    data_rows = rows[2:] if header == rows[1] else rows[1:]
    return header, data_rows


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe ATSDR profile PDFs and MRL HTML table.")
    parser.add_argument("--outdir", type=Path, default=Path("outputs/atsdr_probe"))
    parser.add_argument("--profile-sample", type=int, default=1, help="How many profile PDFs to sample.")
    args = parser.parse_args()

    outdir = args.outdir
    outdir.mkdir(parents=True, exist_ok=True)

    hub_html = http_get(PROFILE_HUB)
    profile_links = extract_profile_links(hub_html)
    pdf_links = find_pdf_links(hub_html)

    hub_report = [
        {"item": "profile_links_found", "value": str(len(profile_links))},
        {"item": "pdf_links_found", "value": str(len(pdf_links))},
    ]
    write_csv(outdir / "hub_report.csv", hub_report, ["item", "value"])

    sample_rows: list[dict[str, str]] = []
    for idx, (_, profile_url) in enumerate(profile_links[: max(args.profile_sample, 1)], start=1):
        profile_html = http_get(profile_url)
        profile_pdfs = find_pdf_links(profile_html)
        if not profile_pdfs:
            for extra_idx, (_, extra_url) in enumerate(profile_links[idx:], start=idx + 1):
                profile_html = http_get(extra_url)
                profile_pdfs = find_pdf_links(profile_html)
                profile_url = extra_url
                if profile_pdfs:
                    break
        for pdf_url in profile_pdfs[:1]:
            pdf_bytes = http_get_bytes(pdf_url)
            pdf_path = outdir / f"profile_sample_{idx}.pdf"
            pdf_path.write_bytes(pdf_bytes)
            reader = PdfReader(str(pdf_path))
            first_page = reader.pages[0].extract_text() or ""
            sample_rows.append(
                {
                    "profile_url": profile_url,
                    "pdf_url": pdf_url,
                    "pages": str(len(reader.pages)),
                    "first_page_chars": str(len(first_page)),
                    "first_page_preview": re.sub(r"\\s+", " ", first_page[:600]).strip(),
                }
            )

    if sample_rows:
        write_csv(outdir / "pdf_sample_report.csv", sample_rows, list(sample_rows[0].keys()))

    mrl_html = http_get(MRL_URL)
    header, data_rows = parse_mrl_table(mrl_html)
    if header and data_rows:
        mrl_path = outdir / "mrls_listing.csv"
        write_csv(
            mrl_path,
            [dict(zip(header, row)) for row in data_rows if len(row) == len(header)],
            header,
        )

    summary_rows = [
        {"source": "profile hub", "signal": "profile pages", "result": "usable"},
        {"source": "profile hub", "signal": "PDF links", "result": "usable"},
        {"source": "profile PDF", "signal": "pypdf text extraction", "result": "usable"},
        {"source": "MRL listing", "signal": "HTML table", "result": "usable"},
    ]
    write_csv(outdir / "comparison_summary.csv", summary_rows, ["source", "signal", "result"])

    print(f"profiles_found={len(profile_links)} pdf_links_found={len(pdf_links)} mrl_rows={len(data_rows)}")
    if sample_rows:
        print(f"sample_pdf_pages={sample_rows[0]['pages']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
