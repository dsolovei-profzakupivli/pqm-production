-- Stage 3 standalone recording. Apply explicitly AFTER Stage 1 DDL.
-- No startup registration, historical backfill, or updates to legacy tables.
CREATE TABLE IF NOT EXISTS supplier_evidence_observations_v3 (
  observation_id TEXT PRIMARY KEY,
  environment TEXT NOT NULL CHECK(environment IN ('prod','sandbox')),
  supplier_code TEXT NOT NULL,
  source_system TEXT NOT NULL,
  source_object TEXT NOT NULL,
  source_id TEXT NOT NULL,
  observed_at TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  payload_hash TEXT NOT NULL,
  UNIQUE(environment,supplier_code,source_system,source_object,source_id)
);
CREATE TABLE IF NOT EXISTS supplier_evidence_gaps_v3 (
  gap_id TEXT PRIMARY KEY,
  observation_id TEXT NOT NULL REFERENCES supplier_evidence_observations_v3(observation_id),
  gap_type TEXT NOT NULL,
  gap_reason TEXT NOT NULL,
  review_scope TEXT NOT NULL CHECK(review_scope IN ('active','history_only')),
  remediation TEXT NOT NULL CHECK(remediation IN ('factual_verification','provenance_review')),
  known_event_date TEXT NOT NULL DEFAULT '',
  known_actor TEXT NOT NULL DEFAULT '',
  source_json TEXT NOT NULL DEFAULT '{}',
  recommended_action TEXT NOT NULL,
  UNIQUE(observation_id,gap_type)
);
-- A resolution never erases or edits the original observation/gap.
CREATE TABLE IF NOT EXISTS supplier_evidence_gap_resolutions_v3 (
  gap_id TEXT PRIMARY KEY REFERENCES supplier_evidence_gaps_v3(gap_id),
  disposition TEXT NOT NULL CHECK(disposition IN ('resolved','history_only')),
  evidence_event_id TEXT REFERENCES supplier_evidence_events_v3(event_id),
  assessed_at TEXT NOT NULL,
  assessment_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_evidence_observation_supplier_v3
  ON supplier_evidence_observations_v3(environment,supplier_code);
CREATE INDEX IF NOT EXISTS ix_evidence_gap_scope_v3
  ON supplier_evidence_gaps_v3(review_scope,observation_id);
-- Inclusion events are NOT supplier lifecycle events or verification events.
CREATE TABLE IF NOT EXISTS supplier_inclusion_history_v3 (
  event_id TEXT PRIMARY KEY,
  environment TEXT NOT NULL CHECK(environment IN ('prod','sandbox')),
  supplier_code TEXT NOT NULL,
  inclusion_id TEXT NOT NULL,
  event_kind TEXT NOT NULL CHECK(event_kind IN ('activation','suspension','resumption','termination','expiry')),
  state_after TEXT NOT NULL CHECK(state_after IN ('active','suspended','inactive')),
  effective_date TEXT NOT NULL,
  source_event_at TEXT,
  recorded_at TEXT NOT NULL,
  source_system TEXT NOT NULL,
  source_event_id TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  payload_hash TEXT NOT NULL,
  UNIQUE(environment,supplier_code,inclusion_id,event_kind,source_system,source_event_id)
);
CREATE INDEX IF NOT EXISTS ix_inclusion_history_supplier_v3
  ON supplier_inclusion_history_v3(environment,supplier_code,inclusion_id);
-- Separate environment-aware cache; Stage 1/legacy projections remain untouched.
CREATE TABLE IF NOT EXISTS supplier_evidence_current_v3 (
  environment TEXT NOT NULL CHECK(environment IN ('prod','sandbox')),
  supplier_code TEXT NOT NULL,
  current_event_id TEXT REFERENCES supplier_evidence_events_v3(event_id),
  last_verification_event_id TEXT REFERENCES supplier_evidence_events_v3(event_id),
  projection_json TEXT NOT NULL,
  as_of_date TEXT NOT NULL,
  rebuilt_at TEXT NOT NULL,
  PRIMARY KEY(environment,supplier_code)
);
CREATE INDEX IF NOT EXISTS ix_evidence_recording_supplier_v3
  ON supplier_evidence_events_v3(environment,supplier_code,effective_date);
