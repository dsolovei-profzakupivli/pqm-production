-- Canonical evidence collections for one supplier_nazk_checks.id cycle.
-- Scalar identity/result/officer columns are added idempotently by
-- nazk_evidence.migrate(), because supported SQLite versions do not provide
-- portable ALTER TABLE ... ADD COLUMN IF NOT EXISTS.

CREATE TABLE IF NOT EXISTS supplier_nazk_check_channels (
  check_id INTEGER NOT NULL REFERENCES supplier_nazk_checks(id) ON DELETE CASCADE,
  channel TEXT NOT NULL CHECK(channel IN ('supplier','nazk')),
  status TEXT NOT NULL DEFAULT 'not_sent',
  sent_at TEXT,
  document_number TEXT NOT NULL DEFAULT '',
  evidence_url TEXT NOT NULL DEFAULT '',
  comment TEXT NOT NULL DEFAULT '',
  recorded_at TEXT,
  recorded_by TEXT NOT NULL DEFAULT '',
  source_task_id TEXT,
  PRIMARY KEY(check_id,channel)
);

CREATE TABLE IF NOT EXISTS supplier_nazk_check_evidence (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  check_id INTEGER NOT NULL REFERENCES supplier_nazk_checks(id) ON DELETE CASCADE,
  evidence_type TEXT NOT NULL DEFAULT 'response',
  source TEXT NOT NULL DEFAULT 'other',
  evidence_date TEXT,
  document_number TEXT NOT NULL DEFAULT '',
  short_summary TEXT NOT NULL DEFAULT '',
  uploaded_document_name TEXT NOT NULL DEFAULT '',
  uploaded_document_url TEXT NOT NULL DEFAULT '',
  evidence_url TEXT NOT NULL DEFAULT '',
  comment TEXT NOT NULL DEFAULT '',
  information_result TEXT NOT NULL DEFAULT 'neutral',
  post_close INTEGER NOT NULL DEFAULT 0,
  recorded_at TEXT NOT NULL,
  recorded_by TEXT NOT NULL,
  updated_at TEXT,
  updated_by TEXT NOT NULL DEFAULT '',
  source_task_id TEXT,
  legacy_task_response_id INTEGER UNIQUE
);

CREATE INDEX IF NOT EXISTS ix_nazk_check_evidence_check
  ON supplier_nazk_check_evidence(check_id,recorded_at,id);
