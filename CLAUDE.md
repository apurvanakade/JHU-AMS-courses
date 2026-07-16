# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A scraper for JHU course listings, scoped to Applied Mathematics &
Statistics, plus a database builder and static visualizer that turn the
scraped terms into a browsable map of how courses connect (prerequisites,
exclusions, equivalencies). Three pieces: `fetch_courses.py` (scraper),
`build_database.py` (extracts connections into a database), and
`docs/index.html` (the visualizer, published via GitHub Pages from `docs/`).

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

python3 build_database.py                              # rebuild db/courses.db + docs/graph.json from data/

python3 -m http.server                                 # serve the repo root, then open
                                                         # http://localhost:8000/docs/ to view
                                                         # the visualizer (fetch() needs http://,
                                                         # not a file:// open)
```

No API key or registration is required.

There is no build, lint, or test suite in this repo. `build_database.py` and
`docs/index.html` use only the Python/JS standard library — no `npm`,
no bundler.

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

## build_database.py

Reads every `data/*/courses.json` and collapses per-term/per-section records
into one row per course, extracting the relationships between courses:

- **Prerequisites** — JHU encodes these as a string like
  `"(^A[C]^OR^B[C]^)^AND^C[C]"`; splitting on `^` tokenizes it into course
  codes, `AND`/`OR`, and parens. A handful of expressions mix `AND`/`OR` at
  the same nesting depth without full parens (e.g. `EN.553.488`'s prereq) —
  the parser follows conventional precedence (`AND` binds tighter than
  `OR`) since even JHU's own human-readable description of that expression
  leaves the ambiguity unresolved.
- **Exclusions** — `IsNegative: "Y"` on a prerequisite entry, and
  (confusingly) JHU's `CoRequisites` field, which in this data is always
  actually a mutual-exclusion rule ("may not be taken concurrently with"),
  never a true corequisite.
- **Equivalencies** — cross-numbering, e.g. `EN.550.310` ≡ `EN.553.311`
  (the department was renumbered from 550 to 553 at some point).

Only `EN.553.*` codes count as real AMS courses. Any other code referenced
as a prerequisite/corequisite/equivalency of an AMS course (e.g.
`AS.110.202` Calculus III, or a cross-listed `EN.500`/`EN.601` course pulled
in via `AllDepartments` matching) gets a stub node instead of a full one,
titled from JHU's own `PrereqCoursesCatalogs` metadata or its own scraped
title when available — even if it was scraped as its own record, so it's
never treated as a first-class AMS course.

500-level, 800-level, and "Independent Academic Work"-level sections (JHU's
label for independent-study arrangements) are dropped before they're
collapsed into a course row (`is_excluded()`) — these are one-off
student/faculty arrangements, not real courses, and add nodes to the graph
with little to no navigational value. Nothing else in the scraped data
references them as a prerequisite/corequisite/equivalency, so dropping them
doesn't leave dangling stub nodes behind.

Two outputs, both fully reproducible by re-running the script:
- `db/courses.db` (SQLite, gitignored) — the queryable source of truth,
  with prerequisite/corequisite logic stored as a tree via `parent_id`
  rather than flattened, so `(A or B) and C` round-trips exactly. Most
  tables (`courses`, `prereq_nodes`, `corequisite_nodes`, `equivalencies`)
  hold one row per course, since that's the collapsed unit the rest of the
  script works with. `course_sections` is the exception: it keeps one row
  per actual section per term (`instructors`, `syllabus_url`, `max_seats`,
  `seats_available`, `waitlisted`, `status`) because a single course can
  have many sections in the same term taught by different people — that
  data doesn't collapse to one row per course the way everything else does.
- `docs/graph.json` (committed) — a nodes/edges flattening of the same data
  for `docs/index.html` to fetch directly; no server-side build step. Each
  node's `sections` array mirrors `course_sections` (term, section,
  instructors, syllabus_url, enrollment) and is rendered as a per-section
  table in the visualizer's detail panel.

## docs/ (the visualizer)

`docs/index.html` is a single self-contained file (no dependencies, no
build step) that fetches `graph.json` and renders it as a **static**
layout: one column per course level (the course number's hundreds digit,
so `EN.553.310` sits in the "300s" column), ordered top-to-bottom within
each column by a one-time barycenter sweep against connected courses to
reduce crossings. Node fill color encodes level (categorical, one hue per
column); edge dash pattern encodes relationship type (solid+arrow =
prerequisite, dotted = corequisite/can't-combine, dashed = mutually
exclusive, thick solid = equivalent). There is no physics simulation —
positions are computed once at load and never move on their own; the only
interactivity is pan/zoom/click.

This folder doubles as the GitHub Pages source (repo Settings → Pages →
Deploy from branch → `/docs`), so `graph.json` must stay committed even
though it's a build artifact — unlike `db/courses.db`, which is gitignored.
Regenerate both with `python3 build_database.py` after re-scraping a term.
