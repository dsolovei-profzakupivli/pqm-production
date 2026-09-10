-- Additive global SVG icon library for the administrator navigation editor.
CREATE TABLE IF NOT EXISTS navigation_icons(
  icon_key TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  svg TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  updated_by TEXT NOT NULL DEFAULT ''
);
