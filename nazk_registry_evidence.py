"""Durable registry evidence, separate from the replaceable current directory.

Schema creation is harmless at startup. Retargeting an existing FK is an
explicit, manifest-checked maintenance operation; never performed by startup.
Snapshots say when they were observed, not that a person was confirmed/refuted.
"""
import hashlib
import json
import sqlite3
from datetime import datetime, timezone

TABLE = "nazk_registry_evidence_sources"
MATCHES = "supplier_nazk_check_matches"
RECEIPTS = "nazk_registry_evidence_migrations"
FIELDS = ("source_id punishment_type_code punishment_type_name entity_type_code "
          "entity_type_name last_name first_name patronymic full_name offense_id "
          "offense_name punishment court_case_number sentence_date sentence_number "
          "punishment_start court_id court_name codex_articles decision_url raw_json").split()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def rows(con, sql, args=()):
    cursor = con.execute(sql, args)
    names = [col[0] for col in cursor.description]
    return [dict(zip(names, row)) for row in cursor]


def parent(con):
    return next((r[2] for r in con.execute(f"PRAGMA foreign_key_list({MATCHES})")
                 if r[3] == "nazk_source_id"), None)


def ensure_schema(con):
    """DDL only: no seeding, repairing, checks, tasks or workflow execution."""
    con.execute(f"""CREATE TABLE IF NOT EXISTS {TABLE} (
      source_id TEXT PRIMARY KEY, payload_json TEXT NOT NULL,
      observed_at TEXT NOT NULL, provenance_json TEXT NOT NULL)""")
    con.execute(f"""CREATE TABLE IF NOT EXISTS {RECEIPTS} (
      manifest_sha256 TEXT PRIMARY KEY, applied_at TEXT NOT NULL,
      details_json TEXT NOT NULL)""")
    for table in (TABLE, RECEIPTS):
        for action in ("UPDATE", "DELETE"):
            con.execute(f"""CREATE TRIGGER IF NOT EXISTS {table}_no_{action.lower()}
              BEFORE {action} ON {table} BEGIN
              SELECT RAISE(ABORT,'NAZK evidence is append-only'); END""")


def install_capture_trigger(con):
    if parent(con) != TABLE:
        return  # An old WEB DB requires explicit maintenance, not startup repair.
    payload = ",".join(f"'{field}',n.{field}" for field in FIELDS)
    con.execute(f"""CREATE TRIGGER IF NOT EXISTS nazk_capture_link_evidence
      BEFORE INSERT ON {MATCHES} BEGIN
      SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM {MATCHES}
          WHERE check_id=NEW.check_id AND nazk_source_id=NEW.nazk_source_id)
        AND NOT EXISTS(SELECT 1 FROM nazk_registry WHERE source_id=NEW.nazk_source_id)
        THEN RAISE(ABORT,'New NAZK relation requires a current registry source') END;
      INSERT OR IGNORE INTO {TABLE}(source_id,payload_json,observed_at,provenance_json)
        SELECT n.source_id,json_object({payload}),strftime('%Y-%m-%dT%H:%M:%fZ','now'),
          '{{"origin":"current_registry_at_explicit_link","not_a_factual_result":true}}'
        FROM nazk_registry n WHERE n.source_id=NEW.nazk_source_id;
      END""")


def source_state(con):
    return {
        "checks": rows(con, "SELECT * FROM supplier_nazk_checks ORDER BY id"),
        "matches": rows(con, f"SELECT rowid,* FROM {MATCHES} ORDER BY rowid"),
        "registry": rows(con, f"SELECT * FROM nazk_registry WHERE source_id IN "
                         f"(SELECT nazk_source_id FROM {MATCHES}) ORDER BY source_id"),
    }


def make_plan(con, recovery, observed_at):
    if parent(con) != "nazk_registry":
        raise ValueError("STOP: expected the original registry FK")
    state = source_state(con)
    current = {row["source_id"] for row in state["registry"]}
    missing = sorted({r["nazk_source_id"] for r in state["matches"]} - current)
    if sorted(recovery) != missing:
        raise ValueError("STOP: recovery must match exactly the missing source IDs")
    for source_id in missing:
        proof = recovery[source_id]
        record = proof["record"]
        if (set(record) != set(FIELDS) or record["source_id"] != source_id
                or not proof.get("artifact_sha256") or not proof.get("observed_at")):
            raise ValueError("STOP: incomplete historical WEB evidence")
        original = [{k: v for k, v in r.items() if k != "rowid"}
                    for r in state["matches"] if r["nazk_source_id"] == source_id]
        if sorted(original, key=lambda r: r["check_id"]) != sorted(
                proof["relations"], key=lambda r: r["check_id"]):
            raise ValueError("STOP: historical relations do not match WEB")
    expected_fk = [[MATCHES, r["rowid"], "nazk_registry", 0]
                   for r in state["matches"] if r["nazk_source_id"] in missing]
    actual_fk = [list(r) for r in con.execute("PRAGMA foreign_key_check")]
    if sorted(actual_fk) != sorted(expected_fk):
        raise ValueError("STOP: unexpected FK violation")
    return {"version": 1, "kind": "web_nazk_durable_evidence_fk",
            "observed_at": observed_at, "state_sha256": digest(state),
            "missing_source_ids": missing, "recovery": recovery,
            "expected_fk": expected_fk, "relation_count": len(state["matches"])}


def apply_plan(con, plan, expected_sha256):
    """Caller owns a fresh backup. One transaction; returns without workflow calls."""
    sha = digest(plan)
    if sha != expected_sha256 or plan.get("version") != 1 or plan.get("kind") != "web_nazk_durable_evidence_fk":
        raise ValueError("STOP: manifest hash/version mismatch")
    if con.in_transaction:
        raise ValueError("STOP: caller transaction is not allowed")
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("BEGIN IMMEDIATE")
    try:
        state = source_state(con)
        if digest(state) != plan["state_sha256"]:
            raise ValueError("STOP: manifest preconditions changed")
        existing_tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if parent(con) == TABLE:
            receipt = (con.execute(f"SELECT 1 FROM {RECEIPTS} WHERE manifest_sha256=?", (sha,)).fetchone()
                       if RECEIPTS in existing_tables else None)
            if not receipt or con.execute("PRAGMA foreign_key_check").fetchall():
                raise ValueError("STOP: unverified previous migration")
            con.rollback()
            return {"source_inserts": 0, "events": 0, "relation_changes": 0, "repeat": True}
        # Revalidate inside the writer lock, before any DDL/data change.
        if make_plan(con, plan["recovery"], plan["observed_at"]) != plan:
            raise ValueError("STOP: manifest preconditions changed")
        expected_columns = ["check_id", "nazk_source_id", "match_status", "created_at"]
        if [r[1] for r in con.execute(f"PRAGMA table_info({MATCHES})")] != expected_columns:
            raise ValueError("STOP: unexpected match schema")
        for table in existing_tables:
            if any(r[2] == MATCHES for r in con.execute('PRAGMA foreign_key_list("'+table.replace('"','""')+'")')):
                raise ValueError("STOP: incoming match-table FK requires separate review")
        if con.execute("SELECT 1 FROM sqlite_master WHERE type='trigger' AND tbl_name=?", (MATCHES,)).fetchone():
            raise ValueError("STOP: existing match trigger requires separate review")
        if [r[0] for r in con.execute("PRAGMA integrity_check")] != ["ok"]:
            raise ValueError("STOP: integrity check failed")
        indexes = [r[0] for r in con.execute("SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name=? AND sql IS NOT NULL", (MATCHES,))]
        ensure_schema(con)
        if con.execute(f"SELECT COUNT(*) FROM {TABLE}").fetchone()[0]:
            raise ValueError("STOP: unexpected existing evidence")
        records = {r["source_id"]: r for r in state["registry"]}
        records.update({k: v["record"] for k, v in plan["recovery"].items()})
        for source_id, record in sorted(records.items()):
            proof = plan["recovery"].get(source_id)
            provenance = {"origin": "web_backup" if proof else "current_web_snapshot",
                          "manifest_sha256": sha, "payload_sha256": digest(record),
                          "not_a_factual_result": True}
            if proof:
                provenance.update(artifact_sha256=proof["artifact_sha256"],
                                  artifact_name=proof["artifact_name"])
            con.execute(f"INSERT INTO {TABLE} VALUES(?,?,?,?)", (source_id, canonical(record),
                        proof["observed_at"] if proof else plan["observed_at"], canonical(provenance)))
        con.execute(f"""CREATE TABLE nazk_matches_fk_repair (
          check_id INTEGER NOT NULL REFERENCES supplier_nazk_checks(id) ON DELETE CASCADE,
          nazk_source_id TEXT NOT NULL REFERENCES {TABLE}(source_id),
          match_status TEXT NOT NULL DEFAULT 'candidate', created_at TEXT NOT NULL,
          PRIMARY KEY(check_id,nazk_source_id))""")
        con.execute(f"INSERT INTO nazk_matches_fk_repair(rowid,check_id,nazk_source_id,match_status,created_at) SELECT rowid,* FROM {MATCHES}")
        con.execute(f"DROP TABLE {MATCHES}")
        con.execute(f"ALTER TABLE nazk_matches_fk_repair RENAME TO {MATCHES}")
        for sql in indexes:
            con.execute(sql)
        install_capture_trigger(con)
        if digest(source_state(con)) != plan["state_sha256"] or con.execute("PRAGMA foreign_key_check").fetchall():
            raise ValueError("STOP: verification failed")
        result = {"source_inserts": len(records), "events": 1, "relation_changes": 0,
                  "recovered_historical_sources": len(plan["missing_source_ids"]), "repeat": False}
        con.execute(f"INSERT INTO {RECEIPTS} VALUES(?,?,?)", (sha, datetime.now(timezone.utc).isoformat(), canonical(result)))
        con.commit()
        return result
    except BaseException:
        con.rollback()
        raise


def registry_records(con, check_id):
    """Current projection plus explicitly labelled historical evidence, read-only."""
    evidence_exists = con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (TABLE,)).fetchone()
    result = []
    for relation in rows(con, f"SELECT * FROM {MATCHES} WHERE check_id=? ORDER BY nazk_source_id", (check_id,)):
        source_id = relation["nazk_source_id"]
        current = rows(con, "SELECT * FROM nazk_registry WHERE source_id=?", (source_id,))
        if current:
            item = current[0]
            item.update(current_registry_present=True, registry_source="current_registry")
        else:
            evidence = rows(con, f"SELECT * FROM {TABLE} WHERE source_id=?", (source_id,)) if evidence_exists else []
            item = json.loads(evidence[0]["payload_json"]) if evidence else {"source_id": source_id}
            item.update(current_registry_present=False, registry_source="historical_web_snapshot" if evidence else "missing_evidence")
            if evidence:
                item["evidence_observed_at"] = evidence[0]["observed_at"]
                item["registry_provenance"] = json.loads(evidence[0]["provenance_json"])
        item.pop("raw_json", None)
        item["match_status"] = relation["match_status"]
        result.append(item)
    return sorted(result, key=lambda r: (r.get("sentence_date") or "", r["source_id"]))
