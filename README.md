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

Or pass the key directly:

```bash
python3 fetch_courses.py --key your_key_here
```

By default this fetches Applied Mathematics & Statistics courses for
Fall 2026. Override any of the search parameters:

```bash
python3 fetch_courses.py \
  --school "Whiting School of Engineering" \
  --department "EN Applied Mathematics & Statistics" \
  --term "Fall 2026" \
  --json-out courses.json \
  --csv-out courses.csv
```

## Output

- `courses.json` — raw API response
- `courses.csv` — flattened table (nested fields are JSON-encoded strings)
