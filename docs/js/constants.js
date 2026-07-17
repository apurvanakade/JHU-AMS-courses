// Static lookup tables shared across the layout and rendering modules.
// Nothing here depends on the loaded graph or on app state.

export const SEASON_ORDER = { Spring: 0, Summer: 1, Fall: 2, Intersession: 3 };

export const LEVEL_LABEL = {
  1: "100s", 2: "200s", 3: "300s", 4: "400s", 5: "500s",
  6: "600s", 7: "700s", 8: "800s", 9: "other",
};

export const EDGE_STYLE = {
  prerequisite: { dash: [], arrow: true, width: 1 },
  corequisite:  { dash: [1, 4], arrow: false, width: 1 },
  exclusion:    { dash: [6, 4], arrow: false, width: 1 },
  equivalent:   { dash: [], arrow: false, width: 2.4 },
};

// Color is keyed by degree (Undergraduate/Graduate — two hues, fixed) with
// an ordinal lightness ramp across the course-number column (100s
// lightest, 800s darkest) inside each hue, rather than a different hue per
// column: level and degree are two different axes, and eight distinct hues
// was more identity-work than the graph needed.
export const DEGREE_HUE = {
  Undergraduate: { h: 213, s: 68 }, // blue
  Graduate:      { h: 152, s: 45 }, // teal-green
};

export const COLUMN_WIDTH = 320;
export const ROW_HEIGHT = 28;
