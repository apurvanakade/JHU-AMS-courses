#!/usr/bin/env python3
"""
Fetch course listings from the JHU SIS Self-Service Public Course Search API.

API docs: https://sis.jhu.edu/api

Usage:
    python fetch_courses.py --key YOUR_API_KEY \
        --school "Whiting School of Engineering" \
        --department "EN Applied Mathematics & Statistics" \
        --term "Fall 2026"

If --term is omitted, you'll be prompted for it interactively. Output is
written to a "<Year> <Season>" folder (e.g. "2026 Fall/"), matching the
existing data layout in this repo.

The API key is requested from https://sis.jhu.edu/api (see "Access
Validation" section) and can also be supplied via the SIS_API_KEY
environment variable instead of --key.
"""

import argparse
import csv
import json
import os
import sys
from urllib.parse import quote

import requests

API_BASE = "https://sis.jhu.edu/api/classes"


DATA_DIR = "data"


def term_to_folder(term: str) -> str:
    """Convert an API term like "Fall 2026" into a folder name "data/2026 Fall"."""
    season, year = term.rsplit(" ", 1)
    return os.path.join(DATA_DIR, f"{year} {season}")


def fetch_courses(school: str, department: str, term: str, api_key: str) -> list[dict]:
    """Query the SIS Public Course Search API for a school/department/term.

    A literal "/" in a department name must be replaced with "_" per the
    API docs before URL-encoding.
    """
    department = department.replace("/", "_")
    path = "/".join(quote(part, safe="") for part in (school, department, term))
    url = f"{API_BASE}/{path}"

    response = requests.get(url, params={"key": api_key}, timeout=30)
    response.raise_for_status()

    data = response.json()
    if isinstance(data, dict) and data.get("isError"):
        message = data.get("apiException", {}).get("exceptionMessage", "Unknown API error")
        raise RuntimeError(f"SIS API error: {message}")

    return data


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
    parser.add_argument("--key", default=os.environ.get("SIS_API_KEY"),
                         help="SIS API key (or set SIS_API_KEY env var)")
    parser.add_argument("--school", default="Whiting School of Engineering")
    parser.add_argument("--department", default="EN Applied Mathematics & Statistics")
    parser.add_argument("--term", help='Academic term, e.g. "Fall 2026" (prompted if omitted)')
    parser.add_argument("--out-dir", help='Output folder (defaults to "<Year> <Season>")')
    parser.add_argument("--yes", "-y", action="store_true",
                         help="Overwrite existing output files without prompting")
    args = parser.parse_args()

    if not args.key:
        parser.error("An API key is required: pass --key or set SIS_API_KEY")

    term = args.term or input('Term (e.g. "Fall 2026"): ').strip()
    if not term:
        parser.error("A term is required")

    out_dir = args.out_dir or term_to_folder(term)
    json_path = os.path.join(out_dir, "courses.json")
    csv_path = os.path.join(out_dir, "courses.csv")

    if not args.yes and not confirm_overwrite([json_path, csv_path]):
        print("Aborted.")
        return 1

    os.makedirs(out_dir, exist_ok=True)

    courses = fetch_courses(args.school, args.department, term, args.key)

    write_json(courses, json_path)
    write_csv(courses, csv_path)

    print(f"Fetched {len(courses)} course record(s).")
    print(f"Wrote {json_path} and {csv_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
