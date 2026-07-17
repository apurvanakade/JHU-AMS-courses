// Pure helpers for interpreting course/term fields from graph.json.
// No DOM access, no shared mutable state.

import { SEASON_ORDER } from "./constants.js";

export function termKey(term) {
  const [season, year] = term.split(" ");
  return Number(year) * 10 + (SEASON_ORDER[season] ?? 0);
}

// course number's hundreds digit, e.g. EN.553.310 -> "3". Anything that
// doesn't parse falls into a "9" catch-all column.
export function levelDigit(code) {
  const m = code.match(/\.(\d)\d{2}$/);
  return m ? m[1] : "9";
}

// the registrar's own coarse level string (e.g. "Upper Level Undergraduate",
// "Graduate") bucketed into the two groups the old dropdown used.
export function degreeBucket(level) {
  if (!level) return null;
  if (level.includes("Graduate")) return "Graduate";
  return "Undergraduate";
}

// The earliest term (in our scraped window, Fall 2023 onward) a course
// appears in — used to flag "first offered this term". Null for stubs
// (no term data of their own).
export function firstTermOf(n) {
  if (!n.terms.length) return null;
  return n.terms.reduce((a, b) => (termKey(a) <= termKey(b) ? a : b));
}

// 'Fall' if every offering on record is a Fall term, 'Spring' if every one
// is Spring, null if it's offered in both (or we have no term data at all).
export function seasonOnlyOf(n) {
  if (!n.terms.length) return null;
  const seasons = new Set(n.terms.map(t => t.split(" ")[0]));
  return seasons.size === 1 ? [...seasons][0] : null;
}

// Mirrors the Jan-Jun -> Spring / Jul-Dec -> Fall heuristic in
// scripts/refresh_terms.py, so the default view always tracks "now"
// instead of going stale as a hardcoded term would.
export function computeDefaultTerm() {
  const now = new Date();
  const year = now.getFullYear();
  const month = now.getMonth() + 1; // 1-12
  return (month >= 1 && month <= 6) ? `Spring ${year}` : `Fall ${year}`;
}
