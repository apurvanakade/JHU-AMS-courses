#!/usr/bin/env python3
"""
Fetch course listings (including prerequisites, restrictions, corequisites,
and full catalog descriptions) from the Typesense search backend behind
JHU's public course search site (https://courses.jhu.edu).

This used to call the documented SIS API (https://sis.jhu.edu/api), but that
API never populates its `SectionDetails` field (no prereqs/restrictions/
descriptions) and requires a registered API key. courses.jhu.edu itself gets
richer data from a Typesense collection instead: it fetches a public,
search-only-scoped API key from `https://api.sis.jhu.edu/api/coursesearch/configuration`
(the same key every visitor's browser downloads, no login needed) and
queries a `sections` collection directly. This script does the same thing.

Usage:
    python3 fetch_courses.py --term "Fall 2026"          # skip prompt
    python3 fetch_courses.py                              # prompts for term
    python3 fetch_courses.py --term "Fall 2026" --yes      # skip overwrite confirmation

No API key is required. Output is written to a "<Year> <Season>" folder
(e.g. "data/2026 Fall/"), matching the existing data layout in this repo.
"""

import argparse
import csv
import json
import os
import sys

import requests

CONFIG_URL = "https://api.sis.jhu.edu/api/coursesearch/configuration"
COLLECTION = "sections"
PAGE_SIZE = 250

DATA_DIR = "data"


def term_to_folder(term: str) -> str:
    """Convert an API term like "Fall 2026" into a folder name "data/2026 Fall"."""
    season, year = term.rsplit(" ", 1)
    return os.path.join(DATA_DIR, f"{year} {season}")


def get_typesense_config() -> dict:
    response = requests.get(CONFIG_URL, timeout=30)
    response.raise_for_status()
    data = response.json()["data"]
    return {
        "api_key": data["typesenseApiKey"],
        "node": data["typesenseNearestNode"],
    }


def fetch_courses(school: str, department: str, term: str, config: dict) -> list[dict]:
    """Page through the Typesense `sections` collection for a school/department/term.

    Filters on AllDepartments (not Department) to match courses.jhu.edu's own
    matching behavior: it includes courses cross-listed into this department
    even when it isn't their primary Department (e.g. EN.500.113 lists as
    "EN General Engineering" but cross-lists into every WSE department).
    """
    url = f"https://{config['node']}/collections/{COLLECTION}/documents/search"
    headers = {"X-TYPESENSE-API-KEY": config["api_key"]}
    filter_by = f'AllDepartments:="{department}" && Term:="{term}"'
    if school:
        filter_by += f' && SchoolName:="{school}"'

    hits = []
    page = 1
    while True:
        response = requests.get(
            url,
            headers=headers,
            params={
                "q": "*",
                "filter_by": filter_by,
                "per_page": PAGE_SIZE,
                "page": page,
            },
            timeout=30,
        )
        response.raise_for_status()
        result = response.json()
        page_hits = result.get("hits", [])
        hits.extend(page_hits)
        if len(hits) >= result.get("found", 0) or not page_hits:
            break
        page += 1

    return [hit["document"] for hit in hits]


def write_json(courses: list[dict], path: str) -> None:
    with open(path, "w") as f:
        json.dump(courses, f, indent=2)


def confirm_overwrite(paths: list[str]) -> bool:
    """Ask the user before clobbering any file that already exists."""
    existing = [p for p in paths if os.path.exists(p)]
    if not existing:
        return True
    for p in existing:
        print(f"File already exists: {p}")
    reply = input("Overwrite? [y/N]: ").strip().lower()
    return reply in ("y", "yes")


def write_csv(courses: list[dict], path: str) -> None:
    if not courses:
        return
    fieldnames = sorted({key for course in courses for key in course.keys()})
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for course in courses:
            row = {
                key: (json.dumps(value) if isinstance(value, (list, dict)) else value)
                for key, value in course.items()
            }
            writer.writerow(row)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--school", default="Whiting School of Engineering")
    parser.add_argument("--department", default="EN Applied Mathematics & Statistics")
    parser.add_argument("--term", help='Academic term, e.g. "Fall 2026" (prompted if omitted)')
    parser.add_argument("--out-dir", help='Output folder (defaults to "<Year> <Season>")')
    parser.add_argument("--yes", "-y", action="store_true",
                         help="Overwrite existing output files without prompting")
    args = parser.parse_args()

    term = args.term or input('Term (e.g. "Fall 2026"): ').strip()
    if not term:
        parser.error("A term is required")

    out_dir = args.out_dir or term_to_folder(term)
    json_path = os.path.join(out_dir, "courses.json")
    csv_path = os.path.join(out_dir, "courses.csv")

    if not args.yes and not confirm_overwrite([json_path, csv_path]):
        print("Aborted.")
        return 1

    config = get_typesense_config()
    courses = fetch_courses(args.school, args.department, term, config)

    os.makedirs(out_dir, exist_ok=True)
    write_json(courses, json_path)
    write_csv(courses, csv_path)

    print(f"Fetched {len(courses)} course record(s).")
    print(f"Wrote {json_path} and {csv_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
