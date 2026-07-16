// Filter state (search text, term, degree levels, external-prereq toggle),
// the URL <-> state round-trip, and the DOM wiring for the filter controls.
//
// Level/term/external and the focused course (if any) round-trip through
// the query string, so a reload, a shared link, or the browser's
// back/forward buttons all restore the same view. Hover and in-progress
// search text are deliberately excluded: too transient to belong in history.

import { store } from "./store.js";
import { computeDefaultTerm } from "./course-utils.js";
import { relayout } from "./layout.js";
import { centerOn } from "./camera.js";
import { draw } from "./render.js";
import { selectNode, deselect } from "./panel.js";

const DEFAULT_TERM = computeDefaultTerm();

const statusEl = document.getElementById("status");
const searchInput = document.getElementById("search");
const termSelect = document.getElementById("termFilter");
const stubToggle = document.getElementById("stubToggle");
const stubChip = document.getElementById("stubChip");

let suppressHistory = false;

function syncURL(push) {
  if (suppressHistory) return;
  const params = new URLSearchParams();
  params.set("level", Array.from(store.degree).join(","));
  params.set("term", store.term);
  if (store.showStubs) params.set("external", "1");
  const focus = store.selected || store.searchFocus;
  if (focus) params.set("focus", focus.id);
  const url = `${location.pathname}?${params.toString()}`;
  if (push) history.pushState({}, "", url);
  else history.replaceState({}, "", url);
}

function restoreFromParams(params) {
  const level = params.get("level");
  store.degree = new Set(level ? level.split(",").filter(Boolean) : ["Undergraduate"]);
  const term = params.get("term");
  store.term = store.allTerms.includes(term) ? term : DEFAULT_TERM;
  store.showStubs = params.get("external") === "1";

  document.querySelectorAll("#degreeLegend .chip").forEach(chip => {
    const on = store.degree.has(chip.dataset.degree);
    chip.querySelector("input").checked = on;
    chip.classList.toggle("active", on);
  });
  termSelect.value = store.term;
  stubToggle.checked = store.showStubs;
  stubChip.classList.toggle("active", store.showStubs);

  relayout();
  applyFilters(false);

  const focusNode = store.nodeById.get(params.get("focus"));
  if (focusNode) { selectNode(focusNode); centerOn(focusNode, 1.6); }
  else deselect();
  draw();
}

function applyFilters(pushHistory) {
  const q = store.search.trim().toLowerCase();
  let matchedNode = null, matchCount = 0;
  for (const n of store.nodes) {
    let visible = true;
    if (!store.showStubs && n.stub) visible = false;
    // n.degreeLevel is null for stub/external courses (no registrar level
    // data) — exempt them from this filter rather than hiding them
    // whenever any box is unchecked.
    if (visible && n.degreeLevel && !store.degree.has(n.degreeLevel)) visible = false;
    // n.terms is always empty for stub/external courses (no term data of
    // their own); exempt them here too, matching nodesForLayout().
    if (visible && !n.stub && !n.terms.includes(store.term)) visible = false;
    if (visible && q) {
      const hay = (n.id + " " + (n.title || "")).toLowerCase();
      visible = hay.includes(q);
    }
    n.visible = visible;
    n.matched = q ? visible : true;
    if (q && visible) { matchCount++; matchedNode = n; }
  }
  store.activeEdges = store.edges.filter(e => e.source.visible && e.target.visible);

  // Node radius = how many currently-visible courses require this one as
  // a prerequisite (outgoing "prerequisite" edges only — not corequisite/
  // exclusion/equivalent, and not incoming edges). Recomputed on every
  // filter change since the count only makes sense against what's
  // actually on screen right now.
  const outCount = new Map();
  for (const e of store.activeEdges) {
    if (e.type !== "prerequisite") continue;
    outCount.set(e.source.id, (outCount.get(e.source.id) || 0) + 1);
  }
  for (const n of store.nodes) {
    n.r = Math.max(3, Math.min(7, 3 + Math.sqrt(outCount.get(n.id) || 0)));
  }

  const shown = store.nodes.filter(n => n.visible).length;
  statusEl.textContent = `${shown} course${shown === 1 ? "" : "s"} · ${store.activeEdges.length} connection${store.activeEdges.length === 1 ? "" : "s"}`;

  store.searchFocus = matchCount === 1 ? matchedNode : null;
  if (store.searchFocus) centerOn(store.searchFocus, 1.6);
  syncURL(!!pushHistory);
  draw();
}

function initFilterControls() {
  searchInput.addEventListener("input", e => { store.search = e.target.value; applyFilters(false); });
  termSelect.addEventListener("change", e => {
    store.term = e.target.value;
    relayout();
    applyFilters(true);
  });
  document.querySelectorAll("#degreeLegend .chip").forEach(chip => {
    const degree = chip.dataset.degree;
    const input = chip.querySelector("input");
    input.addEventListener("change", () => {
      if (input.checked) store.degree.add(degree); else store.degree.delete(degree);
      chip.classList.toggle("active", input.checked);
      relayout();
      applyFilters(true);
    });
  });
  stubToggle.addEventListener("change", e => {
    store.showStubs = e.target.checked;
    stubChip.classList.toggle("active", store.showStubs);
    relayout();
    applyFilters(true);
  });
}

// Populates the term <select>'s options from the loaded graph. Called once
// after store.allTerms is known, before the first restoreFromParams().
function populateTermOptions() {
  for (const t of store.allTerms) {
    const opt = document.createElement("option");
    opt.value = t; opt.textContent = t;
    termSelect.appendChild(opt);
  }
}

// Restores state from the current address bar without writing history
// (used on load), then normalizes the address bar to the resolved state.
function initFromLocation() {
  suppressHistory = true;
  restoreFromParams(new URLSearchParams(location.search));
  suppressHistory = false;
  syncURL(false); // normalize the address bar to the resolved state, even on a fresh visit

  window.addEventListener("popstate", () => {
    suppressHistory = true;
    restoreFromParams(new URLSearchParams(location.search));
    suppressHistory = false;
  });
}

export { syncURL, applyFilters, initFilterControls, populateTermOptions, initFromLocation };
