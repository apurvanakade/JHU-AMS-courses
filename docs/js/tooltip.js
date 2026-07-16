// The small hover tooltip anchored to the pointer over a course node.

let tooltip, wrap;

export function initTooltip(tooltipEl, wrapEl) {
  tooltip = tooltipEl;
  wrap = wrapEl;
}

export function showTooltip(n, px, py) {
  const rect = wrap.getBoundingClientRect();
  tooltip.innerHTML = "";
  const code = document.createElement("div"); code.className = "t-code"; code.textContent = n.id;
  tooltip.appendChild(code);
  if (n.title) {
    const title = document.createElement("div"); title.className = "t-title"; title.textContent = n.title;
    tooltip.appendChild(title);
  }
  if (n.stub) {
    const rel = document.createElement("div"); rel.className = "t-rel"; rel.textContent = "Referenced course (not offered by AMS)";
    tooltip.appendChild(rel);
  }
  tooltip.style.display = "block";
  let left = px - rect.left + 14, top = py - rect.top + 14;
  if (left + 260 > rect.width) left = px - rect.left - 260 - 14;
  tooltip.style.left = left + "px";
  tooltip.style.top = top + "px";
}

export function hideTooltip() {
  tooltip.style.display = "none";
}
