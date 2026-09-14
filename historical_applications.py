"""Read-only provenance registry for authoritative historical applications."""
from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from pathlib import Path


ROOT = Path(__file__).resolve().parent
MANIFEST_PATH = Path(os.environ.get(
    "PQM_MEDDATA_APPLICATIONS_MANIFEST",
    str(ROOT / "metadata" / "meddata_historical_applications.v1.json"),
))


class HistoricalApplicationReadOnlyError(PermissionError):
    pass


@lru_cache(maxsize=1)
def manifest() -> dict:
    if not MANIFEST_PATH.is_file():
        return {"version": 1, "applications": {}}
    payload = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    applications = payload.get("applications")
    if payload.get("version") != 1 or not isinstance(applications, dict):
        raise RuntimeError("Некоректний manifest historical MedData applications")
    if any(not re.fullmatch(r"[a-f0-9]{32}", str(key)) for key in applications):
        raise RuntimeError("Manifest MedData містить некоректний submission_id")
    return payload


def provenance(submission_id: str) -> dict | None:
    item = manifest()["applications"].get(str(submission_id or ""))
    return dict(item) if isinstance(item, dict) else None


def is_read_only(submission_id: str) -> bool:
    return provenance(submission_id) is not None


def assert_editable(submission_id: str) -> None:
    if is_read_only(submission_id):
        raise HistoricalApplicationReadOnlyError(
            "Історична заявка MedData доступна лише для перегляду"
        )
