#!/usr/bin/env python3
"""
Refresh the current and next academic term's course data, then rebuild the
database and graph.json. Intended to be run on a schedule (see
.github/workflows/refresh-courses.yml) but also safe to run by hand:

    python3 scripts/refresh_terms.py

Only re-fetches the current + next term (not the full historical data/
folder) since those are the only terms whose sections, instructors, seat
counts, or syllabus links realistically change over time.

Term boundary is a simple calendar-month heuristic (Jan-Jun -> Spring is
current, Jul-Dec -> Fall is current). This department's data/ folder has
only ever had Spring/Fall terms (no Summer/Intersession), and JHU's actual
registration windows don't align exactly to calendar-year halves, but since
this runs weekly the heuristic self-corrects over time.
"""

import subprocess
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def current_and_next_term(today: date) -> tuple[str, str]:
    year = today.year
    if 1 <= today.month <= 6:
        return f"Spring {year}", f"Fall {year}"
    return f"Fall {year}", f"Spring {year + 1}"


def main() -> int:
    current_term, next_term = current_and_next_term(date.today())
    print(f'Refreshing "{current_term}" and "{next_term}"...')

    for term in (current_term, next_term):
        subprocess.run(
            [sys.executable, "fetch_courses.py", "--term", term, "--yes"],
            cwd=REPO_ROOT,
            check=True,
        )

    subprocess.run([sys.executable, "build_database.py"], cwd=REPO_ROOT, check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
