// Light/dark theme: reading resolved CSS custom properties, and the
// toggle button that overrides the OS-level preference via [data-theme].

const root = document.documentElement;

export function cssVar(name) {
  return getComputedStyle(root).getPropertyValue(name).trim();
}

export function isDarkMode() {
  const attr = root.getAttribute("data-theme");
  if (attr) return attr === "dark";
  return matchMedia("(prefers-color-scheme: dark)").matches;
}

// `onToggle` is called after the theme attribute flips, so the caller can
// redraw anything that reads cssVar()/isDarkMode() (the canvas doesn't
// repaint on its own — colors are only sampled when draw() runs).
export function initTheme(onToggle) {
  document.getElementById("themeToggle").addEventListener("click", () => {
    const current = root.getAttribute("data-theme");
    const system = matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
    const effective = current || system;
    root.setAttribute("data-theme", effective === "dark" ? "light" : "dark");
    onToggle();
  });
}
