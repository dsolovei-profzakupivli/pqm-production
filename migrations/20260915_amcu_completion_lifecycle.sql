-- Additive immutable qualification targets for the AMKU post-sync lifecycle.
CREATE TABLE IF NOT EXISTS operational_task_qualifications (
  task_id TEXT NOT NULL REFERENCES operational_tasks(id) ON DELETE CASCADE,
  qualification_id TEXT NOT NULL REFERENCES qualifications(id),
  registry_contract_id TEXT NOT NULL REFERENCES registry_contracts(id),
  relation_type TEXT NOT NULL DEFAULT 'targeted_exclusion',
  linked_at TEXT NOT NULL,
  PRIMARY KEY(task_id,qualification_id,registry_contract_id,relation_type)
);
CREATE INDEX IF NOT EXISTS ix_operational_task_qualifications_task
  ON operational_task_qualifications(task_id,relation_type);
