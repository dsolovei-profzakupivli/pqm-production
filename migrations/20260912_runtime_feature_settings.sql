-- Persistent runtime-over-environment switches for non-scheduler capabilities.
CREATE TABLE IF NOT EXISTS runtime_feature_settings (
  feature_key TEXT PRIMARY KEY,
  enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),
  updated_at TEXT NOT NULL,
  updated_by TEXT NOT NULL
);
