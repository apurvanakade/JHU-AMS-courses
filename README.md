# JHU AMS Course Scraper

Fetches course listings from the JHU SIS Self-Service Public Course Search API
(https://sis.jhu.edu/api).

## Setup

```bash
pip install requests
```

## Get an API key

1. Go to https://sis.jhu.edu/api
2. Scroll to "Access Validation (register and request an API key)"
3. Enter your email, solve the reCAPTCHA, and submit
4. The key is emailed to you

## Run

```bash
export SIS_API_KEY=your_key_here
python3 fetch_courses.py
```

You'll be prompted for a term (e.g. `Fall 2026`) if you don't pass `--term`.
Or pass everything directly:

```bash
python3 fetch_courses.py --key your_key_here --term "Fall 2026"
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

- `courses.json` — raw API response
- `courses.csv` — flattened table (nested fields are JSON-encoded strings)

If either file already exists, you'll be asked to confirm before it's
overwritten. Pass `--yes`/`-y` to skip the prompt (e.g. in scripts).
