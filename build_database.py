#!/usr/bin/env python3
"""
Build a course-connections database from the scraped term data in `data/`.

Reads every `data/<Year> <Season>/courses.json` produced by fetch_courses.py,
collapses per-term/per-section records down to one row per course, and
extracts the relationships between courses: prerequisite logic (AND/OR
trees) and mutual-exclusion rules.

JHU's `CoRequisites` field is intentionally not extracted at all — despite
the name, it's always actually a same-term mutual-exclusion rule ("may not
be taken concurrently with"), never a true corequisite. Since the
visualizer's graph isn't scoped to a single term, there's no way to render
"can't combine in the same term" as distinct from any other relationship,
so this field is dropped on load rather than kept as a edge type nobody
can usefully read.

EN.550.* is the department's old numbering (renumbered to EN.553.* at some
point) and is deprecated — it never appears as a scraped course, only as
stale references inside other courses' prerequisite data (JHU's own
records still carry the old codes in a handful of spots).
Those references are dropped entirely rather than turned into stub nodes,
along with any other referenced code that has no usable title at all (no
`PrereqCoursesCatalogs` entry and never scraped directly) — a stub node
with neither a title nor its own data isn't worth showing. See
`is_deprecated_code()`/`strip_codes()` in `build_courses()`.

Two outputs are written:

- `db/courses.db` (SQLite): the queryable source of truth. Tables:
  `courses`, `course_terms`, `course_sections`, `prereq_nodes`.
  `course_sections` holds one row per actual section per
  term (instructors, syllabus URL) since a single course can have many
  sections in one term taught by different people — this data doesn't
  collapse to one row per course the way `courses` does. Prerequisite logic
  is stored as a tree (self-referencing `parent_id`) rather than flattened,
  so "(A or B) and C" is preserved exactly rather than collapsed into loose
  edges. Gitignored — fully reproducible from `data/` by re-running this
  script.
- `docs/graph.json`: a nodes/edges export flattened from the database, for
  the static visualizer at `docs/index.html`. `docs/` doubles as the GitHub
  Pages source, so this file is committed (unlike `db/`) — the published
  site has no build step and fetches it directly. Each node keeps its full
  prerequisite tree (`prerequisites`) in addition to the flattened `edges`
  list, so a consumer can render a simple graph or the exact logic.

Only `EN.553.*` codes are real AMS courses. Any other code referenced as a
prerequisite of an AMS course (e.g. AS.110.202 Calculus III, or
a cross-listed EN.500/EN.601 course pulled in by `AllDepartments` matching)
gets a "stub" node instead of a full one, titled from `PrereqCoursesCatalogs`
or its own scraped title when available — even if it was scraped as its own
record, so prerequisite edges always resolve to a node without treating
non-AMS courses as first-class. If neither source has a title for it, the
reference is dropped instead (see above).

500-level, 800-level, and "Independent Academic Work" sections (JHU's own
label for independent-study arrangements) are dropped entirely before
being collapsed into `courses` — see `is_excluded()`. These are one-off
student/faculty arrangements, not real courses, and nothing else in the
scraped data references them as a prerequisite, so excluding them doesn't
leave any dangling stub nodes behind.

Usage:
    python3 build_database.py              # reads data/, writes db/ + docs/graph.json
    python3 build_database.py --data-dir data --db-dir db --docs-dir docs
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone

DATA_DIR = "data"
DB_DIR = "db"
DOCS_DIR = "docs"


# ---------------------------------------------------------------------------
# Prerequisite expression parsing
#
# Expressions look like:
#   "EN.550.692[C]"
#   "EN.550.632[C]^OR^EN.553.432[C]^OR^EN.553.732[C]"
#   "(^AS.110.202[C]^OR^AS.110.211[C]^)^AND^(^AS.110.201[C]^OR^EN.553.291[C]^)"
#
# Splitting on "^" tokenizes cleanly into course codes (with a trailing
# "[C]" completion marker), "AND"/"OR" operators, and "(" / ")". A handful of
# expressions mix AND and OR at the same nesting depth without parens fully
# disambiguating them (e.g. "A OR B OR (C OR D AND (E OR F))" for
# EN.553.488) — even JHU's own human-readable Description field for those
# leaves the ambiguity unresolved. This parser follows the conventional
# reading (AND binds tighter than OR), same as most boolean-expression
# grammars.
# ---------------------------------------------------------------------------


def tokenize(expression: str) -> list[str]:
    return [tok for tok in expression.split("^") if tok != ""]


def parse_expression(expression: str) -> dict:
    """Parse an Expression string into a nested {type, children} tree.

    Leaf nodes: {"type": "COURSE", "course": "EN.553.420"}
    Group nodes: {"type": "ALL" | "ANY", "children": [...]}
    A bare single course/group with no enclosing operator is returned
    directly (no redundant single-child wrapper).
    """
    tokens = tokenize(expression)
    node, pos = _parse_or(tokens, 0)
    if pos != len(tokens):
        raise ValueError(f"Unexpected trailing tokens in expression: {expression!r}")
    return node


def _parse_operand(tokens: list[str], pos: int) -> tuple[dict, int]:
    tok = tokens[pos]
    if tok == "(":
        node, pos = _parse_or(tokens, pos + 1)
        if pos >= len(tokens) or tokens[pos] != ")":
            raise ValueError(f"Unbalanced parens in tokens: {tokens}")
        return node, pos + 1
    course = tok[:-3] if tok.endswith("[C]") else tok
    return {"type": "COURSE", "course": course}, pos + 1


def _parse_and(tokens: list[str], pos: int) -> tuple[dict, int]:
    node, pos = _parse_operand(tokens, pos)
    children = [node]
    while pos < len(tokens) and tokens[pos] == "AND":
        child, pos = _parse_operand(tokens, pos + 1)
        children.append(child)
    if len(children) == 1:
        return children[0], pos
    return {"type": "ALL", "children": children}, pos


def _parse_or(tokens: list[str], pos: int) -> tuple[dict, int]:
    node, pos = _parse_and(tokens, pos)
    children = [node]
    while pos < len(tokens) and tokens[pos] == "OR":
        child, pos = _parse_and(tokens, pos + 1)
        children.append(child)
    if len(children) == 1:
        return children[0], pos
    return {"type": "ANY", "children": children}, pos


def referenced_courses(node: dict) -> set[str]:
    if node["type"] == "COURSE":
        return {node["course"]}
    refs = set()
    for child in node["children"]:
        refs |= referenced_courses(child)
    return refs


def is_deprecated_code(code: str) -> bool:
    """EN.550.* is the department's pre-renumbering code (now EN.553.*).
    It never appears as a scraped course, only as a stale reference inside
    other courses' prerequisite data, and is dropped everywhere rather than
    kept as a stub node."""
    return code.startswith("EN.550.")


def strip_codes(node: dict | None, drop_codes: set[str]) -> dict | None:
    """Prune COURSE leaves in `drop_codes` out of a parsed prereq tree,
    collapsing ALL/ANY groups down as children are removed. Returns
    None if nothing is left (e.g. the whole expression referenced a dropped
    code)."""
    if node is None:
        return None
    if node["type"] == "COURSE":
        return None if node["course"] in drop_codes else node
    children = [c for c in (strip_codes(child, drop_codes) for child in node["children"]) if c is not None]
    if not children:
        return None
    if len(children) == 1:
        return children[0]
    return {"type": node["type"], "children": children}


# ---------------------------------------------------------------------------
# Loading + collapsing scraped term data
# ---------------------------------------------------------------------------


def load_term_files(data_dir: str) -> list[tuple[str, list[dict]]]:
    files = sorted(glob.glob(os.path.join(data_dir, "*", "courses.json")))
    out = []
    for path in files:
        with open(path) as f:
            out.append((path, json.load(f)))
    return out


def most_common(values) -> str | None:
    values = [v for v in values if v]
    if not values:
        return None
    return Counter(values).most_common(1)[0][0]


def is_excluded(rec: dict) -> bool:
    """500-level, 800-level, and "Independent Academic Work" sections are
    one-off arrangements between a student and a faculty sponsor rather than
    real courses to route through — they clutter the graph with barely
    connected nodes for no navigational benefit, so they're dropped before
    ever entering `courses`."""
    number = rec.get("OfferingName", "").rpartition(".")[2]
    if number[:1] in ("5", "8"):
        return True
    return "Independent Academic Work" in (rec.get("Level") or "")


def build_courses(term_files: list[tuple[str, list[dict]]]) -> tuple[dict[str, dict], set[str]]:
    """Collapse every section record down to one row per course code."""
    by_code: dict[str, dict] = defaultdict(lambda: {
        "titles": [], "descriptions": [], "departments": [], "schools": [],
        "levels": [], "credits": [], "all_departments": set(),
        "areas": set(), "pos_tags": set(), "cross_listed": set(),
        "terms": set(),
        "sections": [],     # list of (term, section, instructors, syllabus_url,
                            #           max_seats, seats_available, waitlisted, status)
        "prereq_raw": [],   # list of (expression, description, is_negative)
        "pcc_titles": {},   # course code -> title, from PrereqCoursesCatalogs
    })

    for _path, records in term_files:
        for rec in records:
            if is_excluded(rec):
                continue
            code = rec["OfferingName"]
            row = by_code[code]
            row["titles"].append(rec.get("Title"))
            row["descriptions"].append(rec.get("Description"))
            row["departments"].append(rec.get("Department"))
            row["schools"].append(rec.get("SchoolName"))
            row["levels"].append(rec.get("Level"))
            row["credits"].append(rec.get("Credits"))
            row["all_departments"].update(rec.get("AllDepartments") or [])
            row["terms"].add(rec.get("Term"))
            row["cross_listed"].add(rec.get("SectionDetails", {}).get("CrossListed"))
            row["sections"].append((
                rec.get("Term"),
                rec.get("SectionName"),
                tuple(rec.get("InstructorsDelimited") or []),
                rec.get("Syllabus_Url"),
                rec.get("MaxSeats"),
                rec.get("SeatsAvailable"),
                rec.get("Waitlisted"),
                rec.get("Status"),
            ))

            for area in rec.get("Areas") or []:
                desc = area.get("Description") if isinstance(area, dict) else area
                if desc:
                    row["areas"].add(desc)
            for tag in rec.get("PosTags") or []:
                row["pos_tags"].add(tag)

            sd = rec.get("SectionDetails", {})
            for p in sd.get("Prerequisites") or []:
                row["prereq_raw"].append((
                    p.get("Expression", ""),
                    p.get("Description", ""),
                    p.get("IsNegative") == "Y",
                ))
            for pcc in sd.get("PrereqCoursesCatalogs") or []:
                name, title = pcc.get("Name"), pcc.get("Title")
                if name and title:
                    row["pcc_titles"][name] = title

    # Only EN.553.* is a real AMS course number; everything else (e.g. a
    # cross-listed EN.500 or EN.601 course pulled in via AllDepartments
    # matching) is external and gets nothing more than a stub, regardless of
    # whether it happened to be scraped as its own record.
    real_codes = {code for code in by_code if code.startswith("EN.553.")}

    # External-title map: courses referenced as a prereq of an AMS
    # course but never real AMS courses themselves (out of department
    # scope). Prefer JHU's own PrereqCoursesCatalogs title; fall back to a
    # scraped title if the external course happened to be scraped directly
    # (e.g. cross-listed EN.500.113).
    external_titles: dict[str, str] = {}
    for code in real_codes:
        for pcc_code, title in by_code[code]["pcc_titles"].items():
            external_titles.setdefault(pcc_code, title)
    for code, row in by_code.items():
        if code not in real_codes:
            title = most_common(row["titles"])
            if title:
                external_titles.setdefault(code, title)

    def title_for(code: str) -> str | None:
        if code in real_codes:
            return most_common(by_code[code]["titles"])
        return external_titles.get(code)

    # Only AMS courses' own prerequisite data defines which external
    # courses are worth a stub node — an external course's own prereqs
    # (e.g. EN.500.113's mutual-exclusion with other EN.500 sections)
    # aren't part of the AMS graph. This first pass is unfiltered
    # (drop_codes isn't known yet) — it just finds the full universe of
    # referenced codes.
    referenced = set()
    for code in real_codes:
        row = by_code[code]
        for expr, _desc, _neg in row["prereq_raw"]:
            if expr:
                referenced |= referenced_courses(parse_expression(expr))

    # Drop EN.550.* deprecated codes and any code with no usable title —
    # nothing worth showing, and no way to tell real signal from scrape
    # noise. This can also drop a real EN.553.* course (none currently lack
    # a title, but the rule should hold either way).
    drop_codes = {c for c in referenced if is_deprecated_code(c)}
    drop_codes |= {c for c in referenced - drop_codes if not title_for(c)}
    drop_codes |= {code for code in real_codes if not title_for(code)}

    courses = {}
    for code in real_codes - drop_codes:
        row = by_code[code]
        courses[code] = {
            "code": code,
            "title": title_for(code),
            "description": most_common(row["descriptions"]),
            "department": most_common(row["departments"]),
            "school": most_common(row["schools"]),
            "level": most_common(row["levels"]),
            "credits": most_common(row["credits"]),
            "all_departments": sorted(row["all_departments"]),
            "areas": sorted(row["areas"]),
            "pos_tags": sorted(row["pos_tags"]),
            "cross_listed": "Y" in row["cross_listed"],
            "terms": sorted(row["terms"], key=_term_sort_key),
            "sections": dedupe_preserve_order(row["sections"]),
            "prereq_raw": dedupe_preserve_order(row["prereq_raw"]),
            "stub": False,
        }

    for code in sorted(referenced - courses.keys() - drop_codes):
        courses[code] = {
            "code": code, "title": external_titles.get(code), "description": None,
            "department": None, "school": None, "level": None, "credits": None,
            "all_departments": [], "areas": [], "pos_tags": [], "cross_listed": False,
            "terms": [], "sections": [], "prereq_raw": [],
            "stub": True,
        }

    return courses, drop_codes


def dedupe_preserve_order(items: list) -> list:
    seen = set()
    out = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


_SEASON_ORDER = {"Spring": 0, "Summer": 1, "Fall": 2, "Intersession": 3}


def _term_sort_key(term: str | None) -> tuple[int, int]:
    if not term:
        return (0, 0)
    season, _, year = term.rpartition(" ")
    return (int(year), _SEASON_ORDER.get(season, 0))


# ---------------------------------------------------------------------------
# SQLite database
# ---------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE courses (
    code TEXT PRIMARY KEY,
    title TEXT,
    description TEXT,
    department TEXT,
    school TEXT,
    level TEXT,
    credits TEXT,
    all_departments TEXT,   -- JSON array
    areas TEXT,             -- JSON array
    pos_tags TEXT,          -- JSON array
    cross_listed INTEGER,
    is_stub INTEGER         -- 1 if only ever seen as a prereq reference
);

CREATE TABLE course_terms (
    code TEXT REFERENCES courses(code),
    term TEXT,
    PRIMARY KEY (code, term)
);

CREATE TABLE course_sections (
    code TEXT REFERENCES courses(code),
    term TEXT,
    section TEXT,
    instructors TEXT,       -- JSON array of full names, e.g. "Miller, John C"
    syllabus_url TEXT,
    max_seats TEXT,         -- raw JHU field, e.g. "60" or "N/A"
    seats_available TEXT,   -- raw JHU field, e.g. "45/60"
    waitlisted TEXT,        -- raw JHU field, e.g. "0" or "N/A"
    status TEXT,            -- e.g. "Open", "Waitlist Only", "Approval Required"
    PRIMARY KEY (code, term, section)
);

CREATE TABLE prereq_nodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    course_code TEXT REFERENCES courses(code),
    parent_id INTEGER REFERENCES prereq_nodes(id),
    node_type TEXT NOT NULL,       -- 'ALL' | 'ANY' | 'COURSE'
    ref_course_code TEXT,          -- set when node_type = 'COURSE'
    is_exclusion INTEGER,          -- set on root nodes only
    raw_expression TEXT,           -- set on root nodes only
    raw_description TEXT           -- set on root nodes only
);

CREATE TABLE metadata (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE INDEX idx_prereq_course ON prereq_nodes(course_code);
CREATE INDEX idx_prereq_ref ON prereq_nodes(ref_course_code);
"""


def build_database(courses: dict[str, dict], drop_codes: set[str], db_path: str, generated_at: str) -> None:
    if os.path.exists(db_path):
        os.remove(db_path)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.executescript(SCHEMA)
    cur.execute("INSERT INTO metadata (key, value) VALUES ('generated_at', ?)", (generated_at,))

    for code, c in courses.items():
        cur.execute(
            "INSERT INTO courses (code, title, description, department, school, "
            "level, credits, all_departments, areas, pos_tags, cross_listed, is_stub) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (c["code"], c["title"], c["description"], c["department"], c["school"],
             c["level"], c["credits"], json.dumps(c["all_departments"]),
             json.dumps(c["areas"]), json.dumps(c["pos_tags"]),
             int(c["cross_listed"]), int(c["stub"])),
        )
        for term in c["terms"]:
            cur.execute("INSERT INTO course_terms (code, term) VALUES (?, ?)", (code, term))

        for term, section, instructors, syllabus_url, max_seats, seats_available, waitlisted, status in c["sections"]:
            cur.execute(
                "INSERT INTO course_sections (code, term, section, instructors, syllabus_url, "
                "max_seats, seats_available, waitlisted, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (code, term, section, json.dumps(list(instructors)), syllabus_url,
                 max_seats, seats_available, waitlisted, status),
            )

        for expression, description, is_negative in c["prereq_raw"]:
            if not expression:
                continue
            tree = strip_codes(parse_expression(expression), drop_codes)
            if tree is None:
                continue
            insert_prereq_root(cur, code, tree, is_negative, expression, description)

    conn.commit()
    conn.close()


def insert_prereq_root(cur, course_code, tree, is_negative, expression, description):
    if tree["type"] == "COURSE":
        cur.execute(
            "INSERT INTO prereq_nodes (course_code, parent_id, node_type, ref_course_code, "
            "is_exclusion, raw_expression, raw_description) VALUES (?, NULL, 'COURSE', ?, ?, ?, ?)",
            (course_code, tree["course"], int(is_negative), expression, description),
        )
        return
    cur.execute(
        "INSERT INTO prereq_nodes (course_code, parent_id, node_type, ref_course_code, "
        "is_exclusion, raw_expression, raw_description) VALUES (?, NULL, ?, NULL, ?, ?, ?)",
        (course_code, tree["type"], int(is_negative), expression, description),
    )
    root_id = cur.lastrowid
    for child in tree["children"]:
        insert_prereq_child(cur, course_code, child, root_id)


def insert_prereq_child(cur, course_code, node, parent_id):
    if node["type"] == "COURSE":
        cur.execute(
            "INSERT INTO prereq_nodes (course_code, parent_id, node_type, ref_course_code, "
            "is_exclusion, raw_expression, raw_description) VALUES (?, ?, 'COURSE', ?, NULL, NULL, NULL)",
            (course_code, parent_id, node["course"]),
        )
        return
    cur.execute(
        "INSERT INTO prereq_nodes (course_code, parent_id, node_type, ref_course_code, "
        "is_exclusion, raw_expression, raw_description) VALUES (?, ?, ?, NULL, NULL, NULL, NULL)",
        (course_code, parent_id, node["type"]),
    )
    node_id = cur.lastrowid
    for child in node["children"]:
        insert_prereq_child(cur, course_code, child, node_id)


# ---------------------------------------------------------------------------
# graph.json export
# ---------------------------------------------------------------------------


def tree_to_json(node: dict) -> dict:
    if node["type"] == "COURSE":
        return {"type": "COURSE", "course": node["course"]}
    return {"type": node["type"], "children": [tree_to_json(c) for c in node["children"]]}


def flatten_edges(course_code: str, node: dict, edge_type: str, group_id: int,
                   is_exclusion: bool, edges: list) -> None:
    """Flatten a prereq tree into simple source->target edges for graphs
    that don't need exact AND/OR logic. `group_id` ties edges from the same
    tree back together so a consumer can still distinguish "any of these"
    from "all of these" if it wants to."""
    if node["type"] == "COURSE":
        edges.append({
            "source": node["course"],
            "target": course_code,
            "type": "exclusion" if is_exclusion else edge_type,
            "group_id": group_id,
            "logic": "ONE",
        })
        return
    for child in node["children"]:
        if child["type"] == "COURSE":
            edges.append({
                "source": child["course"],
                "target": course_code,
                "type": "exclusion" if is_exclusion else edge_type,
                "group_id": group_id,
                "logic": node["type"],
            })
        else:
            flatten_edges(course_code, child, edge_type, group_id, is_exclusion, edges)


def build_graph(courses: dict[str, dict], drop_codes: set[str], generated_at: str) -> dict:
    nodes = []
    edges = []
    group_id = 0

    for code, c in courses.items():
        prereq_trees = []
        for expression, description, is_negative in c["prereq_raw"]:
            if not expression:
                continue
            tree = strip_codes(parse_expression(expression), drop_codes)
            if tree is None:
                continue
            group_id += 1
            prereq_trees.append({
                "logic": tree_to_json(tree),
                "is_exclusion": is_negative,
                "description": description,
            })
            flatten_edges(code, tree, "prerequisite", group_id, is_negative, edges)

        nodes.append({
            "id": code,
            "title": c["title"],
            "description": c["description"],
            "department": c["department"],
            "school": c["school"],
            "level": c["level"],
            "credits": c["credits"],
            "all_departments": c["all_departments"],
            "areas": c["areas"],
            "pos_tags": c["pos_tags"],
            "cross_listed": c["cross_listed"],
            "terms": c["terms"],
            "stub": c["stub"],
            "prerequisites": prereq_trees,
            "sections": [
                {"term": term, "section": section, "instructors": list(instructors),
                 "syllabus_url": syllabus_url or None, "max_seats": max_seats or None,
                 "seats_available": seats_available or None, "waitlisted": waitlisted or None,
                 "status": status or None}
                for term, section, instructors, syllabus_url, max_seats, seats_available,
                    waitlisted, status in c["sections"]
            ],
        })

    return {"generated_at": generated_at, "nodes": nodes, "edges": edges}


# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default=DATA_DIR, help="Folder of scraped term data")
    parser.add_argument("--db-dir", default=DB_DIR, help="Folder to write courses.db")
    parser.add_argument("--docs-dir", default=DOCS_DIR, help="Folder to write graph.json (GitHub Pages source)")
    args = parser.parse_args()

    term_files = load_term_files(args.data_dir)
    if not term_files:
        parser.error(f"No courses.json files found under {args.data_dir}/*/")

    courses, drop_codes = build_courses(term_files)
    scraped = sum(1 for c in courses.values() if not c["stub"])
    stubs = sum(1 for c in courses.values() if c["stub"])
    print(f"Loaded {len(term_files)} term file(s), {len(courses)} distinct course(s) "
          f"({scraped} scraped, {stubs} referenced-only stubs, {len(drop_codes)} "
          f"deprecated/titleless code(s) dropped).")

    os.makedirs(args.db_dir, exist_ok=True)
    os.makedirs(args.docs_dir, exist_ok=True)

    generated_at = datetime.now(timezone.utc).isoformat()

    db_path = os.path.join(args.db_dir, "courses.db")
    build_database(courses, drop_codes, db_path, generated_at)
    print(f"Wrote {db_path}")

    graph = build_graph(courses, drop_codes, generated_at)
    graph_path = os.path.join(args.docs_dir, "graph.json")
    with open(graph_path, "w") as f:
        json.dump(graph, f, indent=2)
    print(f"Wrote {graph_path} ({len(graph['nodes'])} nodes, {len(graph['edges'])} edges)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
