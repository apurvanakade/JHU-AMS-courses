// Canvas rendering. Positions are computed once by layout.js and never
// change on their own — draw() just repaints the current camera view of
// whatever's in `store`, so it's cheap and only runs again on interaction.

import { store } from "./store.js";
import { LEVEL_LABEL, EDGE_STYLE, DEGREE_HUE, COLUMN_WIDTH } from "./constants.js";
import { cssVar, isDarkMode } from "./theme.js";

let canvas, ctx;

export function initRenderer(canvasEl) {
  canvas = canvasEl;
  ctx = canvas.getContext("2d");
}

function nodeColor(n) {
  if (!n.degreeLevel) return cssVar("--muted"); // stub/external course
  const { h, s } = DEGREE_HUE[n.degreeLevel] || { h: 0, s: 0 };
  const col = Math.min(8, Math.max(1, Number(n.col) || 5));
  const t = (col - 1) / 7; // 0 (100s) .. 1 (800s)
  const dark = isDarkMode();
  const lightLo = dark ? 76 : 70; // lightness at the 100s (lightest)
  const lightHi = dark ? 46 : 32; // lightness at the 800s (darkest)
  const L = lightLo + (lightHi - lightLo) * t;
  return `hsl(${h}, ${s}%, ${L}%)`;
}

// ids of nodes currently "in focus": hovered (transient), selected
// (persists until closed or re-clicked), and the sole search match
// (persists while the search narrows to one course). Edges only ever
// draw when they touch one of these — nothing is shown by default.
function focusNodes() {
  const arr = [];
  if (store.hovered) arr.push(store.hovered);
  if (store.selected) arr.push(store.selected);
  if (store.searchFocus) arr.push(store.searchFocus);
  return arr;
}

function neighborSet(focusArr) {
  const set = new Set(focusArr.map(n => n.id));
  for (const e of store.activeEdges) {
    for (const n of focusArr) {
      if (e.source.id === n.id) set.add(e.target.id);
      if (e.target.id === n.id) set.add(e.source.id);
    }
  }
  return set;
}

function truncate(text, max) {
  if (!text) return "";
  return text.length > max ? text.slice(0, max - 1) + "…" : text;
}

export function draw() {
  const { camera, graphBounds, allLevels, nodes, activeEdges, selected } = store;
  const rect = canvas.getBoundingClientRect();
  ctx.clearRect(0, 0, rect.width, rect.height);
  ctx.save();
  ctx.translate(rect.width / 2 + camera.x, rect.height / 2 + camera.y);
  ctx.scale(camera.scale, camera.scale);

  // column headers
  ctx.font = `${12}px system-ui, sans-serif`;
  ctx.fillStyle = cssVar("--muted");
  ctx.textBaseline = "alphabetic";
  allLevels.forEach((lvl, ci) => {
    ctx.fillText(LEVEL_LABEL[lvl] || lvl, ci * COLUMN_WIDTH, graphBounds.minY - 4);
  });

  const focus = focusNodes();
  const focusIds = new Set(focus.map(n => n.id));
  const focusSet = focus.length ? neighborSet(focus) : null;
  const edgeInk = cssVar("--edge-ink");

  for (const e of activeEdges) {
    if (!focusIds.has(e.source.id) && !focusIds.has(e.target.id)) continue;
    const style = EDGE_STYLE[e.type];
    const s = e.source, t = e.target;

    ctx.beginPath();
    if (s.col === t.col) {
      const bulge = 26 + Math.abs(s.y - t.y) * 0.12;
      ctx.moveTo(s.x, s.y);
      ctx.bezierCurveTo(s.x + bulge, s.y, t.x + bulge, t.y, t.x, t.y);
    } else {
      const dx = (t.x - s.x) * 0.5;
      ctx.moveTo(s.x, s.y);
      ctx.bezierCurveTo(s.x + dx, s.y, t.x - dx, t.y, t.x, t.y);
    }
    ctx.setLineDash(style.dash);
    ctx.strokeStyle = edgeInk;
    ctx.globalAlpha = 0.55;
    ctx.lineWidth = style.width / camera.scale;
    ctx.stroke();

    if (style.arrow) {
      const dx = t.x - s.x, dy = t.y - s.y;
      const len = Math.sqrt(dx * dx + dy * dy) || 1;
      const ux = dx / len, uy = dy / len;
      const tx = t.x - ux * (t.r + 3);
      const ty = t.y - uy * (t.r + 3);
      const size = 4.5 / camera.scale;
      ctx.setLineDash([]);
      ctx.beginPath();
      ctx.moveTo(tx, ty);
      ctx.lineTo(tx - ux * size - uy * size * 0.6, ty - uy * size + ux * size * 0.6);
      ctx.lineTo(tx - ux * size + uy * size * 0.6, ty - uy * size - ux * size * 0.6);
      ctx.closePath();
      ctx.fillStyle = edgeInk;
      ctx.globalAlpha = 0.5;
      ctx.fill();
    }
  }
  ctx.setLineDash([]);
  ctx.globalAlpha = 1;

  const textColor = cssVar("--text-primary");
  const secColor = cssVar("--text-secondary");
  const selColor = cssVar("--node-selected");
  const newColor = cssVar("--node-new");
  const titleBudget = Math.max(0, Math.floor((COLUMN_WIDTH - 90) / 6));

  for (const n of nodes) {
    if (!n.visible) continue;
    const dim = (focusSet && !focusSet.has(n.id)) || (store.search && !n.matched);
    ctx.globalAlpha = dim ? 0.15 : 1;

    // A course new this term has, by definition, only one term on
    // record so far — "only offered in Fall/Spring" isn't a pattern yet,
    // just an artifact of it being new. So it never gets the diamond,
    // and gets a distinct fill instead of its usual degree color.
    const isNew = n.firstTerm === store.term;
    const fill = isNew ? newColor : nodeColor(n);
    ctx.beginPath();
    if (n.seasonOnly && !isNew) {
      // Fall-only and Spring-only share one shape — every term here is
      // either Fall or Spring, so "only one season" is a single fact;
      // which season it is reads from the label/tooltip instead.
      const d = n.r * 1.4; // diamond
      ctx.moveTo(n.x, n.y - d);
      ctx.lineTo(n.x + d, n.y);
      ctx.lineTo(n.x, n.y + d);
      ctx.lineTo(n.x - d, n.y);
      ctx.closePath();
    } else {
      ctx.arc(n.x, n.y, n.r, 0, Math.PI * 2);
    }
    ctx.fillStyle = n.stub ? "transparent" : fill;
    ctx.fill();
    ctx.lineWidth = (n === selected ? 2.5 : 1.2) / camera.scale;
    ctx.strokeStyle = n === selected ? selColor : fill;
    if (n.stub) ctx.setLineDash([2, 2]); else ctx.setLineDash([]);
    ctx.stroke();
    ctx.setLineDash([]);

    ctx.font = `${11}px system-ui, sans-serif`;
    ctx.textBaseline = "middle";
    ctx.fillStyle = n === selected ? selColor : textColor;
    ctx.fillText(n.id, n.x + n.r + 5, n.y);

    if (n.title) {
      const codeWidth = ctx.measureText(n.id).width;
      ctx.fillStyle = secColor;
      ctx.fillText(truncate(n.title, titleBudget), n.x + n.r + 9 + codeWidth, n.y);
    }
  }
  ctx.globalAlpha = 1;
  ctx.restore();
}
