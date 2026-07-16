// Camera (pan/zoom) and canvas sizing — no node dragging, layout is static.
// Also owns the pointer/wheel event wiring since hover, pan, and click
// detection all share the same hit-testing logic.

import { store } from "./store.js";
import { draw } from "./render.js";
import { showTooltip, hideTooltip } from "./tooltip.js";

let canvas, wrap;
let panning = false;
let panStart = null;
let lastPointer = { x: 0, y: 0 };

export function resizeCanvas() {
  const rect = wrap.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  canvas.width = rect.width * dpr;
  canvas.height = rect.height * dpr;
  canvas.style.width = rect.width + "px";
  canvas.style.height = rect.height + "px";
  canvas.getContext("2d").setTransform(dpr, 0, 0, dpr, 0, 0);
}

export function fitToScreen() {
  const { camera, graphBounds } = store;
  const rect = canvas.getBoundingClientRect();
  const gw = graphBounds.maxX - graphBounds.minX;
  const gh = graphBounds.maxY - graphBounds.minY;
  const scale = Math.min(rect.width / gw, rect.height / gh) * 0.94;
  camera.scale = Math.max(0.08, Math.min(2, scale));
  const gcx = (graphBounds.minX + graphBounds.maxX) / 2;
  const gcy = (graphBounds.minY + graphBounds.maxY) / 2;
  camera.x = -gcx * camera.scale;
  camera.y = -gcy * camera.scale;
}

export function centerOn(n, scale) {
  const { camera } = store;
  camera.scale = scale;
  camera.x = -n.x * camera.scale;
  camera.y = -n.y * camera.scale;
}

function screenToWorld(px, py) {
  const { camera } = store;
  const rect = canvas.getBoundingClientRect();
  const cx = rect.width / 2, cy = rect.height / 2;
  return {
    x: (px - rect.left - cx - camera.x) / camera.scale,
    y: (py - rect.top - cy - camera.y) / camera.scale,
  };
}

export function nodeAt(px, py) {
  const { camera } = store;
  const { x, y } = screenToWorld(px, py);
  // Hit radius is defined in screen pixels, not world units, and
  // converted per-lookup — otherwise a comfortable click target at fit-
  // to-screen zoom (where camera.scale can be well under 1) shrinks to a
  // sub-pixel target in world space.
  const hitPx = 9;
  let best = null, bestDist = Infinity;
  for (const n of store.nodes) {
    if (!n.visible) continue;
    const dx = n.x - x, dy = n.y - y;
    const d = Math.sqrt(dx * dx + dy * dy);
    const hit = Math.max(n.r, hitPx / camera.scale);
    if (d <= hit && d < bestDist) { best = n; bestDist = d; }
  }
  return best;
}

// `onClick(node|null)` fires on a plain click (not a drag) — with the
// clicked node, or null when the background was clicked.
export function initCamera(canvasEl, wrapEl, onClick) {
  canvas = canvasEl;
  wrap = wrapEl;

  window.addEventListener("resize", () => { resizeCanvas(); draw(); });
  document.getElementById("fitBtn").addEventListener("click", () => { fitToScreen(); draw(); });

  canvas.addEventListener("pointerdown", e => {
    lastPointer = { x: e.clientX, y: e.clientY };
    panning = true;
    panStart = { x: store.camera.x, y: store.camera.y, px: e.clientX, py: e.clientY };
    canvas.classList.add("dragging");
    canvas.setPointerCapture(e.pointerId);
  });

  canvas.addEventListener("pointermove", e => {
    if (panning && (Math.abs(e.clientX - lastPointer.x) > 2 || Math.abs(e.clientY - lastPointer.y) > 2)) {
      store.camera.x = panStart.x + (e.clientX - panStart.px);
      store.camera.y = panStart.y + (e.clientY - panStart.py);
      hideTooltip();
      draw();
      return;
    }
    const n = nodeAt(e.clientX, e.clientY);
    const changed = n !== store.hovered;
    store.hovered = n;
    if (n) showTooltip(n, e.clientX, e.clientY); else hideTooltip();
    if (changed) draw();
  });

  function endDrag(e) {
    if (panning) { panning = false; canvas.classList.remove("dragging"); canvas.releasePointerCapture(e.pointerId); }
  }
  canvas.addEventListener("pointerup", e => {
    const moved = Math.abs(e.clientX - lastPointer.x) > 3 || Math.abs(e.clientY - lastPointer.y) > 3;
    const clickedNode = !moved ? nodeAt(e.clientX, e.clientY) : null;
    endDrag(e);
    if (clickedNode) onClick(clickedNode);
    else if (!moved) onClick(null); // clicking empty background clears the current focus
  });
  canvas.addEventListener("pointerleave", () => { hideTooltip(); draw(); });

  canvas.addEventListener("wheel", e => {
    e.preventDefault();
    const { camera } = store;
    const rect = canvas.getBoundingClientRect();
    const cx = rect.width / 2, cy = rect.height / 2;
    const mx = e.clientX - rect.left - cx, my = e.clientY - rect.top - cy;
    const worldX = (mx - camera.x) / camera.scale;
    const worldY = (my - camera.y) / camera.scale;
    const factor = Math.exp(-e.deltaY * 0.0015);
    camera.scale = Math.min(4, Math.max(0.08, camera.scale * factor));
    camera.x = mx - worldX * camera.scale;
    camera.y = my - worldY * camera.scale;
    draw();
  }, { passive: false });
}
