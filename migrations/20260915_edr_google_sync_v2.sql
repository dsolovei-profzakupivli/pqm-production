-- Additive storage for coherent Google/Clarity and PQM admission verification events.
CREATE TABLE IF NOT EXISTS supplier_edr_verification_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  supplier_code TEXT NOT NULL,
  event_type TEXT NOT NULL,
  occurred_at TEXT NOT NULL,
  officer TEXT NOT NULL DEFAULT '',
  source TEXT NOT NULL,
  source_submission_id TEXT NOT NULL DEFAULT '',
  source_sheet TEXT NOT NULL DEFAULT '',
  source_row INTEGER NOT NULL DEFAULT 0,
  changed_fields TEXT NOT NULL DEFAULT '[]',
  snapshot_hash TEXT NOT NULL,
  snapshot_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  UNIQUE(supplier_code,event_type,occurred_at,source,snapshot_hash)
);
CREATE INDEX IF NOT EXISTS ix_supplier_edr_verification_events_current
  ON supplier_edr_verification_events(supplier_code,occurred_at DESC,id DESC);

ALTER TABLE supplier_edr_profiles ADD COLUMN termination_record_date TEXT DEFAULT '';
ALTER TABLE supplier_edr_profiles ADD COLUMN termination_record_number TEXT DEFAULT '';
ALTER TABLE supplier_edr_sync_log ADD COLUMN source_fingerprint TEXT DEFAULT '';
ALTER TABLE supplier_edr_sync_log ADD COLUMN unchanged INTEGER DEFAULT 0;
ALTER TABLE supplier_edr_sync_log ADD COLUMN details_json TEXT DEFAULT '{}';
