// Entry point: wires up the independent modules and drives the initial
// graph.json fetch. Loaded as a <script type="module">, which defers
// execution until the document is parsed, so all the element lookups
// below are safe without a DOMContentLoaded listener.

import { store, buildFromGraph } from "./store.js";
import { initRenderer, draw } from "./render.js";
import { initTheme } from "./theme.js";
import { initTooltip } from "./tooltip.js";
import { initCamera, resizeCanvas } from "./camera.js";
import { initPanel, selectNode, deselect } from "./panel.js";
import { syncURL, initFilterControls, populateTermOptions, initFromLocation } from "./filters.js";

const canvas = document.getElementById("graph");
const wrap = document.getElementById("canvasWrap");
const tooltip = document.getElementById("tooltip");
const loadingEl = document.getElementById("loading");
const loadErrorEl = document.getElementById("loadError");
const lastUpdatedEl = document.getElementById("lastUpdated");

initRenderer(canvas);
initTooltip(tooltip, wrap);
initTheme(draw);
initPanel(() => syncURL(true));
initFilterControls();
initCamera(canvas, wrap, clickedNode => {
  if (clickedNode) {
    if (clickedNode === store.selected) deselect();
    else selectNode(clickedNode);
  } else if (store.selected) {
    deselect(); // clicking empty background clears the current focus
  }
});

function init(g) {
  buildFromGraph(g);

  if (g.generated_at) {
    const d = new Date(g.generated_at);
    lastUpdatedEl.textContent = isNaN(d) ? "" :
      "Updated " + d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
  }

  populateTermOptions();
  resizeCanvas();
  initFromLocation();
}

fetch("graph.json")
  .then(r => { if (!r.ok) throw new Error(r.status); return r.json(); })
  .then(g => { init(g); loadingEl.style.display = "none"; })
  .catch(() => { loadingEl.style.display = "none"; loadErrorEl.style.display = "flex"; });
