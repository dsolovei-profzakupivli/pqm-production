"""Audit and optionally backfill WEB review_officer login values.

The default mode is read-only.  Apply changes only resolved login values outside
the authoritative MedData manifest; historical rows are intentionally left for
the separate MedData migration.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


ACTOR = "migration:web_review_officer_login_v1"


def normalized(value) -> str:
    return " ".join(str(value or "").strip().upper().split())


def display_name(value: str) -> str:
    parts = " ".join(str(value or "").split()).split()
    return " ".join([*(part.lower().capitalize() for part in parts[:-1]), parts[-1].upper()]) if parts else ""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def manifest_ids(path: Path) -> set[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    applications = payload.get("applications")
    if payload.get("version") != 1 or not isinstance(applications, dict):
        raise RuntimeError("Invalid MedData manifest")
    return set(applications)


def audit(db_path: Path, manifest_path: Path) -> tuple[dict, list[dict]]:
    historical = manifest_ids(manifest_path)
    connection = sqlite3.connect(f"file:{db_path.resolve().as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    try:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        officers = {row["id"]: row["full_name"] for row in connection.execute(
            "SELECT id,full_name FROM authorized_officers")}
        canonical = {normalized(value) for value in officers.values()}
        users = {row["username"]: row["officer_id"] for row in connection.execute(
            "SELECT username,officer_id FROM auth_users WHERE active=1")}
        rows = list(connection.execute("""SELECT submission_id,review_officer
          FROM application_fields WHERE TRIM(COALESCE(review_officer,''))<>''"""))
    finally:
        connection.close()
    grouped = defaultdict(lambda: {"total": 0, "historical_manifest": 0, "pqm_era": 0,
                                  "canonical_officer": "", "status": ""})
    plans = []
    for row in rows:
        value = str(row["review_officer"] or "").strip()
        if normalized(value) in canonical:
            status, resolved = "canonical", value
        elif value in users and users[value] in officers:
            status, resolved = "login_resolved", display_name(officers[users[value]])
        elif value in users:
            status, resolved = "login_unresolved", ""
        else:
            status, resolved = "noncanonical_value", ""
        bucket = grouped[value]
        bucket["total"] += 1
        scope = "historical_manifest" if row["submission_id"] in historical else "pqm_era"
        bucket[scope] += 1
        bucket["canonical_officer"] = resolved
        bucket["status"] = status
        if status == "login_resolved":
            plans.append({"submission_id": row["submission_id"], "login": value,
                          "canonical_officer": resolved, "scope": scope})
    distinct = [{"value": value, **details} for value, details in sorted(grouped.items())]
    ambiguity = [item for item in distinct if item["status"] == "login_unresolved"]
    summary = {
        "mode": "READ_ONLY_AUDIT", "integrity_check": integrity,
        "nonempty_review_officer": len(rows),
        "distinct_values": distinct,
        "resolved_login_applications": len(plans),
        "historical_manifest_login_applications": sum(p["scope"] == "historical_manifest" for p in plans),
        "pqm_era_login_applications": sum(p["scope"] == "pqm_era" for p in plans),
        "unresolved_login_mappings": ambiguity,
        "safe_to_apply_pqm_era": integrity == "ok" and not ambiguity,
    }
    return summary, plans


def backup_database(db_path: Path, backup_dir: Path) -> dict:
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = backup_dir / f"pqm_before_review_officer_backfill_{stamp}.sqlite3"
    source, target = sqlite3.connect(db_path), sqlite3.connect(destination)
    try:
        source.backup(target)
    finally:
        target.close(); source.close()
    return {"path": str(destination), "sha256": sha256(destination), "size": destination.stat().st_size,
            "wal_present": db_path.with_name(db_path.name + "-wal").exists(),
            "shm_present": db_path.with_name(db_path.name + "-shm").exists()}


def apply(db_path: Path, plans: list[dict], backup_dir: Path) -> dict:
    targets = [row for row in plans if row["scope"] == "pqm_era"]
    backup = backup_database(db_path, backup_dir)
    connection = sqlite3.connect(db_path, timeout=60)
    stamp = datetime.now(timezone.utc).isoformat()
    changed = 0
    try:
        connection.execute("BEGIN IMMEDIATE")
        for row in targets:
            cursor = connection.execute("""UPDATE application_fields SET review_officer=?
              WHERE submission_id=? AND review_officer=?""", (
                row["canonical_officer"], row["submission_id"], row["login"]))
            if cursor.rowcount != 1:
                raise RuntimeError(f"Concurrent change detected: {row['submission_id']}")
            connection.execute("""INSERT INTO audit_log
              (submission_id,changed_at,changed_by,field_name,old_value,new_value)
              VALUES (?,?,?,?,?,?)""", (row["submission_id"], stamp, ACTOR, "review_officer",
              row["login"], row["canonical_officer"]))
            changed += 1
        connection.commit()
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    except Exception:
        connection.rollback(); raise
    finally:
        connection.close()
    if integrity != "ok":
        raise RuntimeError(f"Post-apply integrity_check failed: {integrity}")
    return {"backup": backup, "changed_pqm_era": changed, "historical_changed": 0,
            "integrity_check": integrity}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", choices=["BACKFILL_PQM_ERA_REVIEW_OFFICERS"])
    parser.add_argument("--writers-stopped", action="store_true")
    parser.add_argument("--backup-dir", type=Path)
    args = parser.parse_args()
    summary, plans = audit(args.db, args.manifest)
    result = {"summary": summary}
    if args.apply:
        if args.confirm != "BACKFILL_PQM_ERA_REVIEW_OFFICERS":
            raise SystemExit("APPLY BLOCKED: explicit --confirm is required")
        if not args.writers_stopped:
            raise SystemExit("APPLY BLOCKED: stop WEB writers and pass --writers-stopped")
        if not args.backup_dir:
            raise SystemExit("APPLY BLOCKED: --backup-dir is required")
        if not summary["safe_to_apply_pqm_era"]:
            raise SystemExit("APPLY BLOCKED: unresolved identity or integrity failure")
        result["apply"] = apply(args.db, plans, args.backup_dir)
        result["summary"]["mode"] = "APPLY_PQM_ERA_ONLY"
    raw = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(raw, encoding="utf-8")
    print(raw, end="")


if __name__ == "__main__":
    main()
