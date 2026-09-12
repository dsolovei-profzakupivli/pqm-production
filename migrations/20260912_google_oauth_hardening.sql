-- Short-lived, one-time PKCE transactions survive a process restart.
-- OAuth client secrets and access/refresh tokens are intentionally not stored here.
CREATE TABLE IF NOT EXISTS google_oauth_transactions (
  state_hash TEXT PRIMARY KEY,
  code_verifier TEXT NOT NULL,
  redirect_uri TEXT NOT NULL,
  expected_origin TEXT NOT NULL,
  created_at REAL NOT NULL,
  expires_at REAL NOT NULL,
  created_by TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS ix_google_oauth_transactions_expiry
  ON google_oauth_transactions(expires_at);
