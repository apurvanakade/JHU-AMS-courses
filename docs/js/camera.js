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

// Touch pinch-to-zoom. `canvas` has `touch-action: none` (graph.css) so the
// browser never applies its own page-zoom gesture here — that native zoom
// only rescales the DOM (crisp) while leaving the canvas's rasterized
// bitmap stretched, which visibly desyncs the graph from the rest of the
// page. We track up to two active touch points ourselves instead and
// reproduce zoom-to-midpoint the same way the wheel handler zooms to the
// cursor.
const activePointers = new Map();
let pinch = null; // { dist, scale, mx, my, camX, camY } while 2 touches are down
let suppressClick = false; // set once a pinch ends, so lifting the second finger doesn't register as a tap

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

  function beginPan(x, y) {
    lastPointer = { x, y };
    panning = true;
    panStart = { x: store.camera.x, y: store.camera.y, px: x, py: y };
    canvas.classList.add("dragging");
  }

  canvas.addEventListener("pointerdown", e => {
    if (activePointers.size >= 2) return; // ignore a third touch point
    canvas.setPointerCapture(e.pointerId);
    activePointers.set(e.pointerId, { x: e.clientX, y: e.clientY });

    if (activePointers.size === 2) {
      panning = false;
      const [a, b] = [...activePointers.values()];
      const rect = canvas.getBoundingClientRect();
      const mid = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
      pinch = {
        dist: Math.hypot(a.x - b.x, a.y - b.y) || 1,
        scale: store.camera.scale,
        mx: mid.x - rect.left,
        my: mid.y - rect.top,
        camX: store.camera.x,
        camY: store.camera.y,
      };
      hideTooltip();
    } else {
      beginPan(e.clientX, e.clientY);
    }
  });

  canvas.addEventListener("pointermove", e => {
    if (!activePointers.has(e.pointerId)) {
      // Hover-only move (mouse, no button down) — never went through pointerdown.
      const n = nodeAt(e.clientX, e.clientY);
      const changed = n !== store.hovered;
      store.hovered = n;
      if (n) showTooltip(n, e.clientX, e.clientY); else hideTooltip();
      if (changed) draw();
      return;
    }
    activePointers.set(e.pointerId, { x: e.clientX, y: e.clientY });

    if (pinch && activePointers.size === 2) {
      const [a, b] = [...activePointers.values()];
      const rect = canvas.getBoundingClientRect();
      const dist = Math.hypot(a.x - b.x, a.y - b.y) || 1;
      const mid = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
      store.camera.scale = Math.min(4, Math.max(0.08, pinch.scale * (dist / pinch.dist)));
      store.camera.x = pinch.camX + (mid.x - rect.left - pinch.mx);
      store.camera.y = pinch.camY + (mid.y - rect.top - pinch.my);
      draw();
      return;
    }

    if (panning && (Math.abs(e.clientX - lastPointer.x) > 2 || Math.abs(e.clientY - lastPointer.y) > 2)) {
      store.camera.x = panStart.x + (e.clientX - panStart.px);
      store.camera.y = panStart.y + (e.clientY - panStart.py);
      hideTooltip();
      draw();
    }
  });

  function endPointer(e) {
    activePointers.delete(e.pointerId);
    try { canvas.releasePointerCapture(e.pointerId); } catch { /* already released */ }

    if (pinch && activePointers.size < 2) {
      pinch = null;
      suppressClick = true; // lifting the second finger shouldn't register as a tap
    }
    if (activePointers.size === 1) {
      const [p] = [...activePointers.values()];
      beginPan(p.x, p.y); // resume single-finger panning from the remaining touch without a jump
    } else if (activePointers.size === 0) {
      panning = false;
      canvas.classList.remove("dragging");
    }
  }

  canvas.addEventListener("pointerup", e => {
    // `pinch` is still set for the first of the two pinch fingers to lift;
    // `suppressClick` (set by endPointer below) carries that suppression
    // through to the second finger's lift, which is otherwise a plain
    // pointerup that looks just like a tap.
    const suppress = !!pinch || suppressClick;
    const moved = Math.abs(e.clientX - lastPointer.x) > 3 || Math.abs(e.clientY - lastPointer.y) > 3;
    const clickedNode = (!moved && !suppress) ? nodeAt(e.clientX, e.clientY) : null;
    endPointer(e);
    if (activePointers.size === 0) suppressClick = false;
    if (suppress) return;
    if (clickedNode) onClick(clickedNode);
    else if (!moved) onClick(null); // clicking empty background clears the current focus
  });
  canvas.addEventListener("pointercancel", endPointer);
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
