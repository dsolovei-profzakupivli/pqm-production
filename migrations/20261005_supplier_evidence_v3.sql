-- Stage 1 only: additive DDL, no backfill or runtime registration.
-- effective_date is business time; recorded_at is observation time.
CREATE TABLE IF NOT EXISTS supplier_evidence_events_v3 (
  event_id TEXT PRIMARY KEY,
  supplier_code TEXT NOT NULL,
  semantic_type TEXT NOT NULL CHECK (semantic_type IN ('verification','lifecycle')),
  event_kind TEXT NOT NULL CHECK (event_kind IN
    ('admission','edr_check','rejection','suspension','resumption','exclusion','expiry')),
  effective_date TEXT NOT NULL CHECK (length(effective_date)=10),
  source_event_at TEXT,
  recorded_at TEXT NOT NULL CHECK (length(trim(recorded_at)) > 0),
  actor_type TEXT NOT NULL CHECK (actor_type IN ('officer','system')),
  officer_id TEXT,
  actor_display TEXT NOT NULL CHECK (length(trim(actor_display)) > 0),
  environment TEXT NOT NULL CHECK (environment IN ('prod','sandbox')),
  source_system TEXT NOT NULL CHECK (length(trim(source_system)) > 0),
  source_event_id TEXT NOT NULL CHECK (length(trim(source_event_id)) > 0),
  submission_id TEXT,
  qualification_id TEXT,
  contract_id TEXT,
  factual_snapshot_json TEXT NOT NULL DEFAULT '{}',
  snapshot_hash TEXT NOT NULL,
  provenance_json TEXT NOT NULL DEFAULT '{}',
  schema_version INTEGER NOT NULL DEFAULT 3 CHECK (schema_version = 3),
  CHECK ((semantic_type='verification' AND event_kind IN ('admission','edr_check')
          AND actor_type='officer') OR
         (semantic_type='lifecycle' AND event_kind IN
          ('rejection','suspension','resumption','exclusion','expiry'))),
  CHECK (event_kind NOT IN ('suspension','resumption','expiry') OR
         (actor_type='system' AND actor_display='ЕСЗ')),
  CHECK (event_kind NOT IN ('exclusion','rejection') OR actor_type='officer'),
  UNIQUE(environment,source_system,source_event_id,supplier_code,semantic_type)
);
CREATE INDEX IF NOT EXISTS ix_supplier_evidence_v3_supplier
  ON supplier_evidence_events_v3(supplier_code,effective_date,semantic_type);

-- Rebuildable cache. Stage 1 never populates it.
CREATE TABLE IF NOT EXISTS supplier_evidence_projections_v3 (
  supplier_code TEXT PRIMARY KEY,
  current_event_id TEXT REFERENCES supplier_evidence_events_v3(event_id),
  last_verification_event_id TEXT REFERENCES supplier_evidence_events_v3(event_id),
  projection_json TEXT NOT NULL,
  projection_version INTEGER NOT NULL DEFAULT 3,
  rebuilt_at TEXT NOT NULL
);
-- Attribution corrections are separate from original historical observations.
CREATE TABLE IF NOT EXISTS supplier_evidence_normalizations_v3 (
  normalization_id TEXT PRIMARY KEY,
  supplier_code TEXT NOT NULL,
  historical_source TEXT NOT NULL,
  historical_observation_id TEXT NOT NULL,
  attribution_json TEXT NOT NULL,
  provenance_json TEXT NOT NULL,
  recorded_at TEXT NOT NULL,
  UNIQUE(historical_source,historical_observation_id,supplier_code)
);
