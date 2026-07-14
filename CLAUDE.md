# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A scraper for the JHU SIS Self-Service Public Course Search API
(https://sis.jhu.edu/api), scoped to Applied Mathematics & Statistics course
listings. The entire tool is one script: `fetch_courses.py`.

## Commands

```bash
pip install requests

export SIS_API_KEY=your_key_here
python3 fetch_courses.py --term "Fall 2026"          # skip prompt
python3 fetch_courses.py                              # prompts for term interactively
python3 fetch_courses.py --term "Fall 2026" --yes      # skip overwrite confirmation
```

An API key is required (get one at https://sis.jhu.edu/api under "Access
Validation" — registration needs a human to solve a reCAPTCHA, so it can't be
automated). Pass via `--key` or `SIS_API_KEY`.

There is no build, lint, or test suite in this repo.

## Architecture

- `fetch_courses.py` builds a request to
  `https://sis.jhu.edu/api/classes/{school}/{department}/{term}?key=...`
  (school/department/term are individually URL-encoded path segments; a
  literal `/` in a department name must first become `_` per the API's own
  encoding rule).
- `term_to_folder()` converts an API term string like `"Fall 2026"` into the
  on-disk layout `data/2026 Fall/` (year/season order flipped from the API's
  season/year order). This mapping is the one non-obvious piece of logic in
  the script — the API and the file layout use different orderings.
- Output per term is a pair of files in that folder: `courses.json` (raw API
  response) and `courses.csv` (flattened; list/dict fields are JSON-encoded
  into a single cell).
- Before writing, the script checks whether either output file already
  exists and prompts to confirm overwrite (bypass with `--yes`/`-y`). This
  check happens *before* the API call, so declining doesn't waste a request.
- Default query scope is school `Whiting School of Engineering`, department
  `EN Applied Mathematics & Statistics`; override with `--school`/
  `--department` to scrape other JHU departments with the same script.

## Data layout

`data/<Year> <Season>/` holds one `courses.json` + `courses.csv` pair per
term already fetched (e.g. `data/2023 Spring/`, `data/2026 Fall/`). These are
committed to the repo as a historical record, not regenerated on every run.
