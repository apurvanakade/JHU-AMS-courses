#!/usr/bin/env python3
"""
Build a course-connections database from the scraped term data in `data/`.

Reads every `data/<Year> <Season>/courses.json` produced by fetch_courses.py,
collapses per-term/per-section records down to one row per course, and
extracts the relationships between courses: prerequisite logic (AND/OR
trees), mutual-exclusion rules, and cross-numbering equivalencies (e.g. the
old EN.550.xxx codes that were renumbered to EN.553.xxx).

Two outputs are written:

- `db/courses.db` (SQLite): the queryable source of truth. Tables:
  `courses`, `course_terms`, `prereq_nodes`, `corequisite_nodes`,
  `equivalencies`. Prerequisite/corequisite logic is stored as a tree
  (self-referencing `parent_id`) rather than flattened, so "(A or B) and C"
  is preserved exactly rather than collapsed into loose edges. Gitignored —
  fully reproducible from `data/` by re-running this script.
- `docs/graph.json`: a nodes/edges export flattened from the database, for
  the static visualizer at `docs/index.html`. `docs/` doubles as the GitHub
  Pages source, so this file is committed (unlike `db/`) — the published
  site has no build step and fetches it directly. Each node keeps its full
  prerequisite/corequisite tree (`prerequisites`/`corequisites`) in
  addition to the flattened `edges` list, so a consumer can render a simple
  graph or the exact logic.

Courses referenced as prerequisites but never scraped themselves (e.g.
AS.110.202 Calculus III, outside the AMS department scope of this repo's
scraper) get a "stub" node, titled from `PrereqCoursesCatalogs` when
available, so prerequisite edges always resolve to a real node.

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

DATA_DIR = "data"
DB_DIR = "db"
DOCS_DIR = "docs"


# ---------------------------------------------------------------------------
# Prerequisite/corequisite expression parsing
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


def build_courses(term_files: list[tuple[str, list[dict]]]) -> dict[str, dict]:
    """Collapse every section record down to one row per course code."""
    by_code: dict[str, dict] = defaultdict(lambda: {
        "titles": [], "descriptions": [], "departments": [], "schools": [],
        "levels": [], "credits": [], "all_departments": set(),
        "areas": set(), "pos_tags": set(), "cross_listed": set(),
        "terms": set(),
        "prereq_raw": [],   # list of (expression, description, is_negative)
        "coreq_raw": [],    # list of (expression, description)
        "equivalent_to": set(),
        "pcc_titles": {},   # course code -> title, from PrereqCoursesCatalogs
    })

    for _path, records in term_files:
        for rec in records:
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
            for c in sd.get("CoRequisites") or []:
                row["coreq_raw"].append((c.get("Expression", ""), c.get("Description", "")))
            for eq in sd.get("Equivalencies") or []:
                name = eq.get("CourseName")
                if name:
                    row["equivalent_to"].add(name)
            for pcc in sd.get("PrereqCoursesCatalogs") or []:
                name, title = pcc.get("Name"), pcc.get("Title")
                if name and title:
                    row["pcc_titles"][name] = title

    courses = {}
    for code, row in by_code.items():
        courses[code] = {
            "code": code,
            "title": most_common(row["titles"]),
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
            "prereq_raw": dedupe_preserve_order(row["prereq_raw"]),
            "coreq_raw": dedupe_preserve_order(row["coreq_raw"]),
            "equivalent_to": sorted(row["equivalent_to"]),
            "stub": False,
        }

    # External-title map: courses referenced as a prereq/coreq but never
    # scraped as their own record (out of this repo's department scope).
    external_titles: dict[str, str] = {}
    for row in by_code.values():
        for code, title in row["pcc_titles"].items():
            external_titles.setdefault(code, title)

    referenced = set()
    for row in by_code.values():
        for expr, _desc, _neg in row["prereq_raw"]:
            if expr:
                referenced |= referenced_courses(parse_expression(expr))
        for expr, _desc in row["coreq_raw"]:
            if expr:
                referenced |= referenced_courses(parse_expression(expr))
        referenced |= row["equivalent_to"]

    for code in referenced - courses.keys():
        courses[code] = {
            "code": code, "title": external_titles.get(code), "description": None,
            "department": None, "school": None, "level": None, "credits": None,
            "all_departments": [], "areas": [], "pos_tags": [], "cross_listed": False,
            "terms": [], "prereq_raw": [], "coreq_raw": [], "equivalent_to": [],
            "stub": True,
        }

    return courses


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
    is_stub INTEGER         -- 1 if only ever seen as a prereq/coreq reference
);

CREATE TABLE course_terms (
    code TEXT REFERENCES courses(code),
    term TEXT,
    PRIMARY KEY (code, term)
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

CREATE TABLE corequisite_nodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    course_code TEXT REFERENCES courses(code),
    parent_id INTEGER REFERENCES corequisite_nodes(id),
    node_type TEXT NOT NULL,
    ref_course_code TEXT,
    raw_expression TEXT,
    raw_description TEXT
);

CREATE TABLE equivalencies (
    course_a TEXT REFERENCES courses(code),
    course_b TEXT REFERENCES courses(code),
    PRIMARY KEY (course_a, course_b)
);

CREATE INDEX idx_prereq_course ON prereq_nodes(course_code);
CREATE INDEX idx_prereq_ref ON prereq_nodes(ref_course_code);
CREATE INDEX idx_coreq_course ON corequisite_nodes(course_code);
CREATE INDEX idx_coreq_ref ON corequisite_nodes(ref_course_code);
"""


def build_database(courses: dict[str, dict], db_path: str) -> None:
    if os.path.exists(db_path):
        os.remove(db_path)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.executescript(SCHEMA)

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

        for expression, description, is_negative in c["prereq_raw"]:
            if not expression:
                continue
            tree = parse_expression(expression)
            insert_prereq_root(cur, code, tree, is_negative, expression, description)

        for expression, description in c["coreq_raw"]:
            if not expression:
                continue
            tree = parse_expression(expression)
            insert_coreq_root(cur, code, tree, expression, description)

        for other in c["equivalent_to"]:
            a, b = sorted((code, other))
            cur.execute(
                "INSERT OR IGNORE INTO equivalencies (course_a, course_b) VALUES (?, ?)",
                (a, b),
            )

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


def insert_coreq_root(cur, course_code, tree, expression, description):
    if tree["type"] == "COURSE":
        cur.execute(
            "INSERT INTO corequisite_nodes (course_code, parent_id, node_type, ref_course_code, "
            "raw_expression, raw_description) VALUES (?, NULL, 'COURSE', ?, ?, ?)",
            (course_code, tree["course"], expression, description),
        )
        return
    cur.execute(
        "INSERT INTO corequisite_nodes (course_code, parent_id, node_type, ref_course_code, "
        "raw_expression, raw_description) VALUES (?, NULL, ?, NULL, ?, ?)",
        (course_code, tree["type"], expression, description),
    )
    root_id = cur.lastrowid
    for child in tree["children"]:
        insert_coreq_child(cur, course_code, child, root_id)


def insert_coreq_child(cur, course_code, node, parent_id):
    if node["type"] == "COURSE":
        cur.execute(
            "INSERT INTO corequisite_nodes (course_code, parent_id, node_type, ref_course_code, "
            "raw_expression, raw_description) VALUES (?, ?, 'COURSE', ?, NULL, NULL)",
            (course_code, parent_id, node["course"]),
        )
        return
    cur.execute(
        "INSERT INTO corequisite_nodes (course_code, parent_id, node_type, ref_course_code, "
        "raw_expression, raw_description) VALUES (?, ?, ?, NULL, NULL, NULL)",
        (course_code, parent_id, node["type"]),
    )
    node_id = cur.lastrowid
    for child in node["children"]:
        insert_coreq_child(cur, course_code, child, node_id)


# ---------------------------------------------------------------------------
# graph.json export
# ---------------------------------------------------------------------------


def tree_to_json(node: dict) -> dict:
    if node["type"] == "COURSE":
        return {"type": "COURSE", "course": node["course"]}
    return {"type": node["type"], "children": [tree_to_json(c) for c in node["children"]]}


def flatten_edges(course_code: str, node: dict, edge_type: str, group_id: int,
                   is_exclusion: bool, edges: list) -> None:
    """Flatten a prereq/coreq tree into simple source->target edges for graphs
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


def build_graph(courses: dict[str, dict]) -> dict:
    nodes = []
    edges = []
    group_id = 0

    for code, c in courses.items():
        prereq_trees = []
        for expression, description, is_negative in c["prereq_raw"]:
            if not expression:
                continue
            tree = parse_expression(expression)
            group_id += 1
            prereq_trees.append({
                "logic": tree_to_json(tree),
                "is_exclusion": is_negative,
                "description": description,
            })
            flatten_edges(code, tree, "prerequisite", group_id, is_negative, edges)

        coreq_trees = []
        for expression, description in c["coreq_raw"]:
            if not expression:
                continue
            tree = parse_expression(expression)
            group_id += 1
            coreq_trees.append({"logic": tree_to_json(tree), "description": description})
            flatten_edges(code, tree, "corequisite", group_id, False, edges)

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
            "corequisites": coreq_trees,
        })

    seen_pairs = set()
    for code, c in courses.items():
        for other in c["equivalent_to"]:
            pair = tuple(sorted((code, other)))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            edges.append({"source": pair[0], "target": pair[1], "type": "equivalent",
                           "group_id": None, "logic": None})

    return {"nodes": nodes, "edges": edges}


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

    courses = build_courses(term_files)
    scraped = sum(1 for c in courses.values() if not c["stub"])
    stubs = sum(1 for c in courses.values() if c["stub"])
    print(f"Loaded {len(term_files)} term file(s), {len(courses)} distinct course(s) "
          f"({scraped} scraped, {stubs} referenced-only stubs).")

    os.makedirs(args.db_dir, exist_ok=True)
    os.makedirs(args.docs_dir, exist_ok=True)

    db_path = os.path.join(args.db_dir, "courses.db")
    build_database(courses, db_path)
    print(f"Wrote {db_path}")

    graph = build_graph(courses)
    graph_path = os.path.join(args.docs_dir, "graph.json")
    with open(graph_path, "w") as f:
        json.dump(graph, f, indent=2)
    print(f"Wrote {graph_path} ({len(graph['nodes'])} nodes, {len(graph['edges'])} edges)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
