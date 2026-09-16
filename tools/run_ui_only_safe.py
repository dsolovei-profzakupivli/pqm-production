"""Controlled WEB/LOCAL acceptance: no jobs, external integrations or business writes."""
from pathlib import Path
import os
import sys

os.environ.update(PQM_SAFE_MODE="1", PQM_RELEASE_SCHEMA_ONLY="1", PQM_ENABLE_BROWSER="0",
    PQM_ENABLE_SCHEDULER="0", PQM_ENABLE_PROZORRO_SCHEDULER="0",
    PQM_ENABLE_VIOLATION_SCHEDULER="0", PQM_ENABLE_NAZK_SCHEDULER="0",
    PQM_ENABLE_NAZK_WORKFLOW="0", PQM_ENABLE_BIDS_UPDATE="0", PQM_BIDS_MODE="disabled",
    PQM_ENABLE_GOOGLE="0", PQM_ENABLE_POWERBI="0")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server

if __name__ == "__main__":
    server.main()
