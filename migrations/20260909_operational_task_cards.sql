CREATE TABLE IF NOT EXISTS operational_task_blocking_decisions (
  task_id TEXT PRIMARY KEY REFERENCES operational_tasks(id) ON DELETE CASCADE,
  decision_date TEXT NOT NULL DEFAULT '',
  protocol_number TEXT NOT NULL DEFAULT '',
  prozorro_url TEXT NOT NULL DEFAULT '',
  document_url TEXT NOT NULL DEFAULT '',
  officer_note TEXT NOT NULL DEFAULT '',
  attached_at TEXT,
  attached_by TEXT DEFAULT '',
  used_for_blocking INTEGER NOT NULL DEFAULT 0
);
