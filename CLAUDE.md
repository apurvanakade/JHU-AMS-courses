# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A scraper for JHU course listings, scoped to Applied Mathematics &
Statistics. The entire tool is one script: `fetch_courses.py`.

It queries the Typesense search backend behind JHU's public course search
site (https://courses.jhu.edu), not the documented SIS API
(https://sis.jhu.edu/api) — that API never populates its `SectionDetails`
field (no prerequisites, restrictions, or catalog descriptions) and
requires a registered key. courses.jhu.edu itself gets richer data by
fetching a public, search-only-scoped Typesense key from
`https://api.sis.jhu.edu/api/coursesearch/configuration` (the same key every
visitor's browser downloads, unauthenticated) and querying a `sections`
collection directly. This script does the same thing.

## Commands

```bash
pip install requests

python3 fetch_courses.py --term "Fall 2026"          # skip prompt
python3 fetch_courses.py                              # prompts for term interactively
python3 fetch_courses.py --term "Fall 2026" --yes      # skip overwrite confirmation
```

No API key or registration is required.

There is no build, lint, or test suite in this repo.

## Architecture

- `fetch_courses.py` first fetches Typesense connection info (node host +
  scoped search key) from `https://api.sis.jhu.edu/api/coursesearch/configuration`,
  then queries `https://{node}/collections/sections/documents/search`,
  paginating with `page`/`per_page` until all hits for the term are
  collected.
- The Typesense filter matches on `AllDepartments` (not `Department`) to
  replicate courses.jhu.edu's own matching behavior: this includes courses
  cross-listed into Applied Mathematics & Statistics even when it isn't
  their primary department (e.g. `EN.500.113` lists `Department: "EN
  General Engineering"` but cross-lists into every WSE department via
  `AllDepartments`). Filtering on `Department` instead silently drops these.
- `term_to_folder()` converts an API term string like `"Fall 2026"` into the
  on-disk layout `data/2026 Fall/` (year/season order flipped from the API's
  season/year order). This mapping is the one non-obvious piece of logic in
  the script — the API and the file layout use different orderings.
- Output per term is a pair of files in that folder: `courses.json` (the raw
  list of Typesense section documents, one per section — each includes a
  nested `SectionDetails` object with `Prerequisites`, `Restrictions`,
  `CoRequisites`, and a full catalog `Description`) and `courses.csv`
  (flattened; list/dict fields are JSON-encoded into a single cell).
- Before writing, the script checks whether either output file already
  exists and prompts to confirm overwrite (bypass with `--yes`/`-y`). This
  check happens *before* the Typesense call, so declining doesn't waste a
  request.
- Default query scope is school `Whiting School of Engineering`, department
  `EN Applied Mathematics & Statistics`; override with `--school`/
  `--department` to scrape other JHU departments with the same script.

## Data layout

`data/<Year> <Season>/` holds one `courses.json` + `courses.csv` pair per
term already fetched (e.g. `data/2023 Spring/`, `data/2026 Fall/`). These are
committed to the repo as a historical record, not regenerated on every run.
