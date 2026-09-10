CREATE TABLE IF NOT EXISTS navigation_settings (
  id INTEGER PRIMARY KEY CHECK(id=1),
  overrides_json TEXT NOT NULL DEFAULT '{}',
  updated_at TEXT NOT NULL,
  updated_by TEXT NOT NULL DEFAULT ''
);
