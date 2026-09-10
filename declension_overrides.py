"""Safe CSV repository for user-maintained declension overrides."""
from __future__ import annotations

import csv
import hashlib
import os
import re
import tempfile
import threading
import time
from pathlib import Path

from declension import DEFAULT_OVERRIDES_PATH, ENTITY_TYPES, normalize_lookup

FIELDS = ("entity_type", "original", "genitive", "dative", "accusative", "comment")
_WRITE_LOCK = threading.Lock()
_AUTO_COMMENT = "unresolved auto-added"
_REQUIRED_CASE_RE = re.compile(r"required_case=([a-z,]+)")


class OverrideConflictError(ValueError):
    pass


def _required_cases(comment: str) -> tuple[str, ...]:
    match = _REQUIRED_CASE_RE.search(str(comment or "").casefold())
    return tuple(sorted({case for case in (match.group(1).split(",") if match else [])
                         if case in {"genitive", "dative", "accusative"}}))


def _with_status(row: dict[str, str]) -> dict[str, str | bool | list[str]]:
    required = _required_cases(row.get("comment", ""))
    pending = bool(required and any(not row.get(case, "").strip() for case in required))
    return {**row, "id": row.get("id") or _record_id(row["entity_type"], row["original"]),
            "required_cases": list(required), "needs_completion": pending,
            "status": "pending" if pending else "ready"}


def _record_id(entity_type: str, original: str) -> str:
    source = f"{entity_type}\0{normalize_lookup(original)}".encode("utf-8")
    return hashlib.sha256(source).hexdigest()[:20]


def list_overrides(path: str | Path = DEFAULT_OVERRIDES_PATH) -> list[dict[str, str]]:
    target = Path(path)
    if not target.exists():
        return []
    with target.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = []
        for raw in csv.DictReader(handle, delimiter=";"):
            row = {field: str(raw.get(field) or "") for field in FIELDS}
            row["entity_type"] = row["entity_type"].strip().casefold()
            row["original"] = row["original"].strip()
            if row["entity_type"] not in ENTITY_TYPES or not row["original"]:
                continue
            row["id"] = _record_id(row["entity_type"], row["original"])
            rows.append(_with_status(row))
    return rows


def _validated(payload: dict) -> dict[str, str]:
    row = {field: str(payload.get(field) or "").strip() for field in FIELDS}
    row["entity_type"] = row["entity_type"].casefold()
    if row["entity_type"] not in ENTITY_TYPES:
        raise ValueError("Оберіть коректний тип назви")
    if not row["original"]:
        raise ValueError("Вкажіть оригінальну назву")
    required = _required_cases(row["comment"])
    if _AUTO_COMMENT in row["comment"].casefold() and required and all(row[case] for case in required):
        row["comment"] = ""
    return row


def _write_atomic(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDS, delimiter=";", lineterminator="\n")
            writer.writeheader()
            writer.writerows({field: row.get(field, "") for field in FIELDS} for row in rows)
            handle.flush()
            os.fsync(handle.fileno())
        replaced = False
        for attempt in range(6):
            try:
                os.replace(temporary, path)
                replaced = True
                break
            except PermissionError:
                if attempt == 5:
                    break
                time.sleep(0.05 * (2 ** attempt))
        if not replaced:
            # Windows may allow writing an existing file while denying rename
            # over it (sharing violation from a reader/indexer).  Keep the
            # repository lock, retain rollback bytes, and use this only after
            # the atomic path has been exhausted.
            replacement = temporary.read_bytes()
            previous = path.read_bytes() if path.exists() else None
            try:
                mode = "r+b" if path.exists() else "w+b"
                with path.open(mode) as handle:
                    handle.seek(0); handle.write(replacement); handle.truncate()
                    handle.flush(); os.fsync(handle.fileno())
            except Exception:
                if previous is not None:
                    try:
                        with path.open("r+b") as handle:
                            handle.seek(0); handle.write(previous); handle.truncate()
                            handle.flush(); os.fsync(handle.fileno())
                    except Exception:
                        pass
                raise
            temporary.unlink(missing_ok=True)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def save_override(payload: dict, record_id: str | None = None,
                  path: str | Path = DEFAULT_OVERRIDES_PATH) -> dict[str, str]:
    target, candidate = Path(path), _validated(payload)
    with _WRITE_LOCK:
        rows = list_overrides(target)
        current = next((row for row in rows if row["id"] == record_id), None) if record_id else None
        if record_id and current is None:
            raise KeyError(record_id)
        normalized = normalize_lookup(candidate["original"])
        duplicate = next((row for row in rows
                          if row["id"] != record_id and row["entity_type"] == candidate["entity_type"]
                          and normalize_lookup(row["original"]) == normalized), None)
        if duplicate:
            raise OverrideConflictError("Такий тип і оригінальна назва вже є у довіднику")
        stored = {field: candidate[field] for field in FIELDS}
        if current:
            rows[rows.index(current)] = stored
        else:
            rows.append(stored)
        _write_atomic(target, rows)
    return _with_status({**stored, "id": _record_id(stored["entity_type"], stored["original"])})


def ensure_pending_overrides(items: list[dict], path: str | Path = DEFAULT_OVERRIDES_PATH) -> list[dict]:
    """Record unresolved exact names once without inventing grammatical forms."""
    target = Path(path)
    with _WRITE_LOCK:
        rows = list_overrides(target)
        changed = False
        for item in items:
            entity_type = str(item.get("entity_type") or "other").strip().casefold()
            original = str(item.get("original") or "").strip()
            grammatical_case = str(item.get("grammatical_case") or "").strip().casefold()
            if entity_type not in ENTITY_TYPES or not original or grammatical_case not in {
                    "genitive", "dative", "accusative"}:
                continue
            existing = next((row for row in rows if row["entity_type"] == entity_type
                             and normalize_lookup(row["original"]) == normalize_lookup(original)), None)
            if existing:
                # Never rewrite a verified form or a user's own comment.  Only
                # merge technical case hints on rows created by this function.
                if _AUTO_COMMENT in existing.get("comment", "").casefold():
                    required = set(_required_cases(existing["comment"]))
                    required.add(grammatical_case)
                    comment = f"{_AUTO_COMMENT}; required_case={','.join(sorted(required))}"
                    if comment != existing["comment"]:
                        existing["comment"] = comment; changed = True
                continue
            rows.append({"entity_type": entity_type, "original": original,
                         "genitive": "", "dative": "", "accusative": "",
                         "comment": f"{_AUTO_COMMENT}; required_case={grammatical_case}"})
            changed = True
        if changed:
            _write_atomic(target, rows)
        return [_with_status(row) for row in rows]


def delete_override(record_id: str, path: str | Path = DEFAULT_OVERRIDES_PATH) -> None:
    target = Path(path)
    with _WRITE_LOCK:
        rows = list_overrides(target)
        remaining = [row for row in rows if row["id"] != record_id]
        if len(remaining) == len(rows):
            raise KeyError(record_id)
        _write_atomic(target, remaining)
