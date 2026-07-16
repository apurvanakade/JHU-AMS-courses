// Static layered layout: one column per course-level (course number's
// hundreds digit), ordered top-to-bottom within a column by a barycenter
// sweep against connected courses. Recomputed on demand (e.g. whenever
// the term changes, so hidden courses don't leave gaps) — there is no
// physics, no animation; positions never move on their own between
// recomputes.

import { store } from "./store.js";
import { COLUMN_WIDTH, ROW_HEIGHT } from "./constants.js";
import { fitToScreen } from "./camera.js";

// Courses to lay out under the current term/level/external-prereqs
// filters — the same criteria applyFilters() uses to decide visibility,
// minus the free-text search (search dims/hides within a layout rather
// than reshuffling it on every keystroke). Mirroring applyFilters() here
// is what keeps filtered-out courses from leaving empty rows in their
// column: a course that won't be shown never reserves a slot.
export function nodesForLayout() {
  return store.nodes.filter(n => {
    if (!store.showStubs && n.stub) return false;
    if (n.degreeLevel && !store.degree.has(n.degreeLevel)) return false;
    if (!n.stub && !n.terms.includes(store.term)) return false;
    return true;
  });
}

export function layoutStatic(layoutNodes) {
  const layoutIds = new Set(layoutNodes.map(n => n.id));
  const columns = new Map();
  for (const n of layoutNodes) {
    if (!columns.has(n.col)) columns.set(n.col, []);
    columns.get(n.col).push(n);
  }
  store.allLevels = Array.from(columns.keys()).sort((a, b) => Number(a) - Number(b));
  for (const lvl of store.allLevels) columns.get(lvl).sort((a, b) => a.id.localeCompare(b.id));

  const neighbors = new Map();
  for (const n of layoutNodes) neighbors.set(n.id, []);
  for (const e of store.edges) {
    if (!layoutIds.has(e.source.id) || !layoutIds.has(e.target.id)) continue;
    neighbors.get(e.source.id).push(e.target.id);
    neighbors.get(e.target.id).push(e.source.id);
  }

  function assignFractions() {
    for (const lvl of store.allLevels) {
      const arr = columns.get(lvl);
      arr.forEach((n, i) => { n._frac = arr.length > 1 ? i / (arr.length - 1) : 0.5; });
    }
  }
  assignFractions();

  for (let pass = 0; pass < 8; pass++) {
    for (const lvl of store.allLevels) {
      const arr = columns.get(lvl);
      const scored = arr.map(n => {
        const neigh = neighbors.get(n.id).map(id => store.nodeById.get(id)).filter(Boolean);
        const key = neigh.length ? neigh.reduce((s, m) => s + m._frac, 0) / neigh.length : n._frac;
        return { n, key };
      });
      scored.sort((a, b) => a.key - b.key || a.n.id.localeCompare(b.n.id));
      columns.set(lvl, scored.map(s => s.n));
    }
    assignFractions();
  }

  const maxHeight = Math.max(...store.allLevels.map(lvl => columns.get(lvl).length)) * ROW_HEIGHT;
  store.allLevels.forEach((lvl, ci) => {
    const arr = columns.get(lvl);
    const colHeight = arr.length * ROW_HEIGHT;
    const offsetY = (maxHeight - colHeight) / 2;
    arr.forEach((n, ri) => {
      n.x = ci * COLUMN_WIDTH;
      n.y = offsetY + ri * ROW_HEIGHT;
    });
  });

  store.graphBounds = {
    minX: -80, maxX: (store.allLevels.length - 1) * COLUMN_WIDTH + COLUMN_WIDTH,
    minY: -20, maxY: maxHeight + 20,
  };
}

// Recompute column positions for the current filters and reframe the
// camera. Called whenever term/level/external-prereqs changes — not on
// search, which only dims/hides within the existing layout.
export function relayout() {
  layoutStatic(nodesForLayout());
  fitToScreen();
}
