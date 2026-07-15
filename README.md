# JHU AMS Course Scraper

Fetches course listings — including prerequisites, restrictions,
corequisites, and full catalog descriptions — from the Typesense search
backend behind JHU's public course search site
(https://courses.jhu.edu).

## Setup

```bash
pip install requests
```

No API key or registration needed.

## Run

```bash
python3 fetch_courses.py
```

You'll be prompted for a term (e.g. `Fall 2026`) if you don't pass `--term`.
Or pass everything directly:

```bash
python3 fetch_courses.py --term "Fall 2026"
```

By default this fetches Applied Mathematics & Statistics courses. Override
any of the search parameters:

```bash
python3 fetch_courses.py \
  --school "Whiting School of Engineering" \
  --department "EN Applied Mathematics & Statistics" \
  --term "Fall 2026" \
  --out-dir "data/2026 Fall"
```

## Output

Data is written to `data/<Year> <Season>/` (e.g. `data/2026 Fall/`), matching
the term you queried — override with `--out-dir`:

- `courses.json` — raw section documents (one per section), including a
  nested `SectionDetails` object with `Prerequisites`, `Restrictions`,
  `CoRequisites`, and a full catalog `Description`
- `courses.csv` — flattened table (nested fields are JSON-encoded strings)

If either file already exists, you'll be asked to confirm before it's
overwritten. Pass `--yes`/`-y` to skip the prompt (e.g. in scripts).
