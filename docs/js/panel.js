// The course detail side panel: building its DOM from a selected node,
// and the drag-to-resize handle on its left edge.

import { store } from "./store.js";
import { LEVEL_LABEL } from "./constants.js";
import { termKey } from "./course-utils.js";
import { draw } from "./render.js";
import { resizeCanvas } from "./camera.js";

const panel = document.getElementById("panel");
const panelBody = document.getElementById("panelBody");

// Called after selection changes, so the caller can persist it to the URL.
// Wired by main.js to filters.syncURL — kept as a callback (rather than
// importing filters.js directly) so this module doesn't need to know
// anything about URL state.
let onSelectionChange = () => {};

export function initPanel(onChange) {
  onSelectionChange = onChange;
  document.getElementById("closePanel").addEventListener("click", deselect);
  initPanelResize();
}

function el(tag, props = {}, children = []) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === "text") node.textContent = v;
    else if (k === "class") node.className = v;
    else node.setAttribute(k, v);
  }
  for (const c of children) node.appendChild(c);
  return node;
}

function courseLink(code) {
  const n = store.nodeById.get(code);
  const label = n && n.title ? `${code} — ${n.title}` : code;
  const a = el("a", { class: "course-link", text: label });
  a.addEventListener("click", () => { if (n) selectNode(n); });
  return a;
}

function reqBlock(entries, prefix) {
  if (!entries.length) return null;
  const wrap = document.createElement("div");
  for (const req of entries) {
    const line = el("div", { class: "req-line" });
    const label = req.is_exclusion ? "Cannot also take: " : prefix;
    line.appendChild(document.createTextNode(label));
    renderTree(req.logic, line);
    wrap.appendChild(line);
    if (req.description) {
      const note = el("span", { class: "note", text: req.description });
      wrap.appendChild(note);
    }
  }
  return wrap;
}

function renderTree(node, container) {
  if (node.type === "COURSE") { container.appendChild(courseLink(node.course)); return; }
  const joiner = node.type === "ALL" ? " and " : " or ";
  node.children.forEach((c, i) => {
    if (i > 0) container.appendChild(document.createTextNode(joiner));
    const wrapParens = c.type !== "COURSE";
    if (wrapParens) container.appendChild(document.createTextNode("("));
    renderTree(c, container);
    if (wrapParens) container.appendChild(document.createTextNode(")"));
  });
}

export function deselect() {
  panel.classList.remove("open");
  store.selected = null;
  resizeCanvas(); // closing the panel grows #canvasWrap back; see selectNode()
  onSelectionChange();
  draw();
}

export function selectNode(n) {
  const wasOpen = panel.classList.contains("open");
  store.selected = n;
  panel.classList.add("open");
  if (!wasOpen) resizeCanvas(); // opening the panel shrinks #canvasWrap via flexbox;
                                 // the canvas's pixel size only updates on a real window
                                 // resize otherwise, so it would keep covering the panel
  panelBody.innerHTML = "";

  panelBody.appendChild(el("div", { class: "code", text: n.id }));
  panelBody.appendChild(el("div", { class: "title", text: n.title || (n.stub ? "Referenced course (outside AMS scrape scope)" : "") }));

  const meta = el("div", { class: "meta" });
  if (n.col) meta.appendChild(el("span", { text: LEVEL_LABEL[n.col] || n.col }));
  if (n.level) meta.appendChild(el("span", { text: n.level }));
  if (n.credits) meta.appendChild(el("span", { text: n.credits + " cr" }));
  if (n.department) meta.appendChild(el("span", { text: n.department.replace(/^EN |^AS /, "") }));
  if (n.cross_listed) meta.appendChild(el("span", { text: "Cross-listed" }));
  const isNew = n.firstTerm === store.term;
  if (n.seasonOnly && !isNew) meta.appendChild(el("span", { text: `${n.seasonOnly} only` }));
  if (isNew) meta.appendChild(el("span", { text: "New this term" }));
  panelBody.appendChild(meta);

  const currentSections = (n.sections || []).filter(s => s.term === store.term);
  if (currentSections.length) {
    panelBody.appendChild(el("h3", { text: `Sections — ${store.term}` }));
    const table = el("table", { class: "sections" });
    const thead = el("tr");
    for (const h of ["Sec", "Instructor(s)", "Seats", "Status", ""]) {
      thead.appendChild(el("th", { text: h }));
    }
    table.appendChild(thead);
    const sorted = [...currentSections].sort((a, b) => (a.section || "").localeCompare(b.section || ""));
    for (const s of sorted) {
      const row = el("tr");
      row.appendChild(el("td", { class: "section-term", text: s.section || "" }));
      row.appendChild(el("td", { class: "section-instructors", text: (s.instructors || []).join(", ") }));
      row.appendChild(el("td", { text: s.seats_available || "" }));
      row.appendChild(el("td", { text: s.status || "" }));
      const linkCell = el("td");
      if (s.syllabus_url) {
        linkCell.appendChild(el("a", {
          class: "course-link", text: "Syllabus",
          href: s.syllabus_url, target: "_blank", rel: "noopener noreferrer",
        }));
      }
      row.appendChild(linkCell);
      table.appendChild(row);
    }
    const scroll = el("div", { class: "table-scroll" }, [table]);
    panelBody.appendChild(scroll);
  }

  if (n.description) {
    panelBody.appendChild(el("h3", { text: "Description" }));
    panelBody.appendChild(el("div", { class: "desc", text: n.description }));
  }

  const preBlock = reqBlock(n.prerequisites || [], "Requires: ");
  if (preBlock) {
    panelBody.appendChild(el("h3", { text: "Prerequisites" }));
    panelBody.appendChild(preBlock);
  }

  const unlocks = store.edges.filter(e => e.type === "prerequisite" && e.source.id === n.id).map(e => e.target.id);
  const excludedBy = store.edges.filter(e => e.type === "exclusion" && (e.source.id === n.id || e.target.id === n.id))
    .map(e => (e.source.id === n.id ? e.target.id : e.source.id));
  const equivalents = store.edges.filter(e => e.type === "equivalent" && (e.source.id === n.id || e.target.id === n.id))
    .map(e => (e.source.id === n.id ? e.target.id : e.source.id));

  if (unlocks.length) {
    panelBody.appendChild(el("h3", { text: "Is a prerequisite for" }));
    const list = document.createElement("div");
    Array.from(new Set(unlocks)).forEach(code => { list.appendChild(courseLink(code)); list.appendChild(document.createElement("br")); });
    panelBody.appendChild(list);
  }
  if (excludedBy.length) {
    panelBody.appendChild(el("h3", { text: "Mutually exclusive with" }));
    const list = document.createElement("div");
    Array.from(new Set(excludedBy)).forEach(code => { list.appendChild(courseLink(code)); list.appendChild(document.createElement("br")); });
    panelBody.appendChild(list);
  }
  if (equivalents.length) {
    panelBody.appendChild(el("h3", { text: "Equivalent to" }));
    const list = document.createElement("div");
    Array.from(new Set(equivalents)).forEach(code => { list.appendChild(courseLink(code)); list.appendChild(document.createElement("br")); });
    panelBody.appendChild(list);
  }

  const otherTerms = (n.terms || []).filter(t => t !== store.term);
  if (otherTerms.length) {
    panelBody.appendChild(el("h3", { text: "Also offered" }));
    const sorted = [...otherTerms].sort((a, b) => termKey(b) - termKey(a));
    panelBody.appendChild(el("div", { class: "termlist", text: sorted.join(", ") }));
  }

  onSelectionChange();
  draw();
}

// Drag the panel's left edge to resize it — the canvas shrinks/grows to
// match, same as it does when the panel opens/closes.
function initPanelResize() {
  const panelResizer = document.getElementById("panelResizer");
  let resizingPanel = false, resizeStartX = 0, resizeStartWidth = 0;
  panelResizer.addEventListener("pointerdown", e => {
    resizingPanel = true;
    resizeStartX = e.clientX;
    resizeStartWidth = panel.getBoundingClientRect().width;
    panelResizer.classList.add("dragging");
    panelResizer.setPointerCapture(e.pointerId);
    e.preventDefault();
  });
  panelResizer.addEventListener("pointermove", e => {
    if (!resizingPanel) return;
    const maxWidth = Math.max(340, window.innerWidth * 0.7);
    const width = Math.min(maxWidth, Math.max(280, resizeStartWidth + (resizeStartX - e.clientX)));
    panel.style.width = width + "px";
    resizeCanvas();
    draw();
  });
  function endPanelResize(e) {
    if (!resizingPanel) return;
    resizingPanel = false;
    panelResizer.classList.remove("dragging");
    panelResizer.releasePointerCapture(e.pointerId);
  }
  panelResizer.addEventListener("pointerup", endPanelResize);
  panelResizer.addEventListener("pointercancel", endPanelResize);
}
