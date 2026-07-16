// The single shared, mutable app state: the loaded graph, the current
// camera transform, and the transient hover/selection/search focus. Every
// other module reads and writes through this object rather than holding
// its own copy, so there is one source of truth for "what's on screen".

import { levelDigit, degreeBucket, firstTermOf, seasonOnlyOf, termKey, computeDefaultTerm } from "./course-utils.js";

export const store = {
  nodeById: new Map(),
  nodes: [],
  edges: [],
  allTerms: [],
  allLevels: [],
  graphBounds: { minX: 0, maxX: 1, minY: 0, maxY: 1 },

  // Edges between two currently-visible nodes, irrespective of relationship
  // type — recomputed by applyFilters() whenever the filters change.
  activeEdges: [],
  searchFocus: null, // the sole search match, if search narrows to exactly one course

  selected: null,
  hovered: null,

  camera: { x: 0, y: 0, scale: 1 },

  // Active filters — read by layout, render, and panel, and written by
  // filters.js in response to the search box, term select, degree chips,
  // and the "show external prereqs" toggle.
  search: "",
  term: computeDefaultTerm(),
  degree: new Set(["Undergraduate"]),
  showStubs: false,
};

// Populates `store` from a freshly-fetched graph.json. Called once, from
// main.js, after the fetch resolves.
export function buildFromGraph(g) {
  store.nodeById = new Map();
  store.nodes = g.nodes.map(n => ({
    ...n,
    col: levelDigit(n.id),          // course-number column, e.g. "4" for the 400s
    degreeLevel: degreeBucket(n.level), // "Undergraduate" | "Graduate" | "Independent"
    firstTerm: firstTermOf(n),      // earliest term on record, or null for stubs
    seasonOnly: seasonOnlyOf(n),    // 'Fall' | 'Spring' | null (offered in both, or a stub)
    x: 0, y: 0, r: 4,
  }));
  store.nodes.forEach(n => store.nodeById.set(n.id, n));

  store.edges = g.edges
    .filter(e => store.nodeById.has(e.source) && store.nodeById.has(e.target))
    .map(e => ({ ...e, source: store.nodeById.get(e.source), target: store.nodeById.get(e.target) }));

  store.allTerms = Array.from(new Set(store.nodes.flatMap(n => n.terms))).sort((a, b) => termKey(a) - termKey(b));
}
