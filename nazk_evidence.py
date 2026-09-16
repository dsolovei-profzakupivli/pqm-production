"""Canonical evidence/provenance storage for one supplier NAZK check cycle."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
import nazk_registry_evidence


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _columns(con: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in con.execute(f"PRAGMA table_info({table})")}


def migrate(con: sqlite3.Connection) -> None:
    """Add canonical check-level storage and import legacy task evidence once."""
    if "supplier_nazk_checks" not in {
        str(row[0]) for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }:
        return

    additions = {
        "person_tax_id": "TEXT NOT NULL DEFAULT ''",
        "responsible_officer_id": "INTEGER REFERENCES authorized_officers(id)",
        "responsible_officer_name": "TEXT NOT NULL DEFAULT ''",
        "result_at": "TEXT",
        "result_by": "TEXT NOT NULL DEFAULT ''",
    }
    current = _columns(con, "supplier_nazk_checks")
    for field, definition in additions.items():
        if field not in current:
            con.execute(f"ALTER TABLE supplier_nazk_checks ADD COLUMN {field} {definition}")

    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS supplier_nazk_check_channels (
          check_id INTEGER NOT NULL REFERENCES supplier_nazk_checks(id) ON DELETE CASCADE,
          channel TEXT NOT NULL CHECK(channel IN ('supplier','nazk')),
          status TEXT NOT NULL DEFAULT 'not_sent',
          sent_at TEXT,
          document_number TEXT NOT NULL DEFAULT '',
          evidence_url TEXT NOT NULL DEFAULT '',
          comment TEXT NOT NULL DEFAULT '',
          recorded_at TEXT,
          recorded_by TEXT NOT NULL DEFAULT '',
          source_task_id TEXT,
          PRIMARY KEY(check_id,channel)
        );
        CREATE TABLE IF NOT EXISTS supplier_nazk_check_evidence (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          check_id INTEGER NOT NULL REFERENCES supplier_nazk_checks(id) ON DELETE CASCADE,
          evidence_type TEXT NOT NULL DEFAULT 'response',
          source TEXT NOT NULL DEFAULT 'other',
          evidence_date TEXT,
          document_number TEXT NOT NULL DEFAULT '',
          short_summary TEXT NOT NULL DEFAULT '',
          uploaded_document_name TEXT NOT NULL DEFAULT '',
          uploaded_document_url TEXT NOT NULL DEFAULT '',
          evidence_url TEXT NOT NULL DEFAULT '',
          comment TEXT NOT NULL DEFAULT '',
          information_result TEXT NOT NULL DEFAULT 'neutral',
          post_close INTEGER NOT NULL DEFAULT 0,
          recorded_at TEXT NOT NULL,
          recorded_by TEXT NOT NULL,
          updated_at TEXT,
          updated_by TEXT NOT NULL DEFAULT '',
          source_task_id TEXT,
          legacy_task_response_id INTEGER UNIQUE
        );
        CREATE INDEX IF NOT EXISTS ix_nazk_check_evidence_check
          ON supplier_nazk_check_evidence(check_id,recorded_at,id);
        """
    )

    channel_columns = _columns(con, "supplier_nazk_check_channels")
    if "source_task_id" not in channel_columns:
        con.execute("ALTER TABLE supplier_nazk_check_channels ADD COLUMN source_task_id TEXT")
    evidence_columns = _columns(con, "supplier_nazk_check_evidence")
    for field, definition in {
        "updated_at": "TEXT", "updated_by": "TEXT NOT NULL DEFAULT ''", "source_task_id": "TEXT"
    }.items():
        if field not in evidence_columns:
            con.execute(f"ALTER TABLE supplier_nazk_check_evidence ADD COLUMN {field} {definition}")

    tables = {str(row[0]) for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    check_columns = _columns(con, "supplier_nazk_checks")

    # Stable person snapshot: only the manager identity explicitly linked to this check.
    if "supplier_managers" in tables and "manager_id" in check_columns:
        manager_columns = _columns(con, "supplier_managers")
        if {"id", "manager_tax_id"} <= manager_columns:
            con.execute(
                """UPDATE supplier_nazk_checks AS c SET person_tax_id=COALESCE((
                     SELECT NULLIF(sm.manager_tax_id,'') FROM supplier_managers sm WHERE sm.id=c.manager_id
                   ),'') WHERE COALESCE(c.person_tax_id,'')='' AND c.manager_id IS NOT NULL"""
            )
    if {"result", "completed_at", "updated_by"} <= check_columns:
        con.execute(
            """UPDATE supplier_nazk_checks SET result_at=completed_at,result_by=updated_by
               WHERE result IN ('confirmed','refuted') AND result_at IS NULL"""
        )
    if {"operational_tasks", "operational_task_channels"} <= tables:
        con.execute(
            """INSERT INTO supplier_nazk_check_channels
               (check_id,channel,status,sent_at,document_number,evidence_url,comment,recorded_at,recorded_by,source_task_id)
               SELECT CAST(json_extract(t.source_context,'$.nazk_check_id') AS INTEGER),c.channel,c.status,
                      c.sent_at,COALESCE(c.outgoing_number,''),COALESCE(c.reference_url,''),
                      COALESCE(c.comment,''),c.recorded_at,COALESCE(c.recorded_by,''),t.id
               FROM operational_task_channels c JOIN operational_tasks t ON t.id=c.task_id
               WHERE t.task_type='nazk_check'
                 AND json_extract(t.source_context,'$.nazk_check_id') IS NOT NULL
               ON CONFLICT(check_id,channel) DO UPDATE SET
                 status=excluded.status,sent_at=excluded.sent_at,document_number=excluded.document_number,
                 evidence_url=excluded.evidence_url,comment=excluded.comment,recorded_at=excluded.recorded_at,
                 recorded_by=excluded.recorded_by,source_task_id=excluded.source_task_id
               WHERE supplier_nazk_check_channels.status='not_sent'
                 AND supplier_nazk_check_channels.recorded_at IS NULL"""
        )
        con.execute(
            """INSERT OR IGNORE INTO supplier_nazk_check_channels(check_id,channel)
               SELECT c.id,v.channel FROM supplier_nazk_checks c
               CROSS JOIN (SELECT 'supplier' channel UNION ALL SELECT 'nazk') v"""
        )

    if {"operational_tasks", "operational_task_responses"} <= tables:
        # Filter already imported responses before INSERT: OR IGNORE alone still
        # consumes AUTOINCREMENT IDs on conflicts during every shared task build.
        con.execute(
            """INSERT OR IGNORE INTO supplier_nazk_check_evidence
               (check_id,evidence_type,source,evidence_date,document_number,short_summary,
                uploaded_document_name,evidence_url,comment,information_result,post_close,
                recorded_at,recorded_by,source_task_id,legacy_task_response_id)
               SELECT CAST(json_extract(t.source_context,'$.nazk_check_id') AS INTEGER),'response',r.source,
                      r.response_date,COALESCE(r.incoming_number,''),COALESCE(r.summary,''),
                      COALESCE(r.document_reference,''),COALESCE(r.reference_url,''),'',
                      r.information_result,r.post_close,r.recorded_at,r.recorded_by,t.id,r.id
               FROM operational_task_responses r JOIN operational_tasks t ON t.id=r.task_id
               WHERE t.task_type='nazk_check'
                 AND json_extract(t.source_context,'$.nazk_check_id') IS NOT NULL
                 AND NOT EXISTS (
                   SELECT 1 FROM supplier_nazk_check_evidence e
                   WHERE e.legacy_task_response_id=r.id
                 )"""
        )

    if "operational_tasks" in tables and "authorized_officers" in tables:
        task_columns = _columns(con, "operational_tasks")
        officer_columns = _columns(con, "authorized_officers")
        if not ({"assigned_officer_id", "source_context", "task_type", "updated_at", "id"} <= task_columns
                and {"id", "full_name"} <= officer_columns):
            return
        con.execute(
            """UPDATE supplier_nazk_checks AS c SET
                 responsible_officer_id=COALESCE(c.responsible_officer_id,(
                   SELECT t.assigned_officer_id FROM operational_tasks t
                   WHERE t.task_type='nazk_check'
                     AND CAST(json_extract(t.source_context,'$.nazk_check_id') AS INTEGER)=c.id
                     AND t.assigned_officer_id IS NOT NULL
                   ORDER BY t.updated_at DESC,t.id DESC LIMIT 1)),
                 responsible_officer_name=CASE WHEN COALESCE(c.responsible_officer_name,'')<>''
                   THEN c.responsible_officer_name ELSE COALESCE((
                     SELECT ao.full_name FROM operational_tasks t
                     JOIN authorized_officers ao ON ao.id=t.assigned_officer_id
                     WHERE t.task_type='nazk_check'
                       AND CAST(json_extract(t.source_context,'$.nazk_check_id') AS INTEGER)=c.id
                     ORDER BY t.updated_at DESC,t.id DESC LIMIT 1),'') END"""
        )


def check_id_for_task(task: dict) -> int:
    source = task.get("source_context") or {}
    check_id = int(source.get("nazk_check_id") or 0)
    if not check_id:
        raise ValueError("Задачу не пов’язано з canonical НАЗК-перевіркою")
    return check_id


def get(con: sqlite3.Connection, check_id: int) -> dict:
    row = con.execute(
        """SELECT c.*,COALESCE(o.full_name,c.responsible_officer_name,'') responsible_uo_name
           FROM supplier_nazk_checks c LEFT JOIN authorized_officers o ON o.id=c.responsible_officer_id
           WHERE c.id=?""",
        (check_id,),
    ).fetchone()
    if not row:
        raise KeyError(check_id)
    result = dict(row)
    result["nazk_check_id"] = result["id"]
    result["person_name"] = result.get("manager_name") or ""
    result["person_rnokpp"] = result.get("person_tax_id") or ""
    result["result_actor"] = result.get("result_by") or ""
    result["responsible_officer"] = {
        "id": result.get("responsible_officer_id"),
        "name": result.get("responsible_uo_name") or "",
    }
    result["registry_records"] = nazk_registry_evidence.registry_records(con, check_id)
    result["registry_facts"] = result["registry_records"]
    result["registry_source_ids"] = [item["source_id"] for item in result["registry_records"]]
    result["channels"] = {item["channel"]: dict(item) for item in con.execute(
        "SELECT * FROM supplier_nazk_check_channels WHERE check_id=? ORDER BY channel", (check_id,)
    )}
    for channel_name, channel in result["channels"].items():
        channel["provenance"] = {
            "original_task_id": channel.get("source_task_id"),
            "original_channel": channel_name,
        }
    result["evidence"] = [dict(item) for item in con.execute(
        """SELECT * FROM supplier_nazk_check_evidence WHERE check_id=?
           ORDER BY recorded_at DESC,id DESC""", (check_id,)
    )]
    for evidence in result["evidence"]:
        evidence["source_response_id"] = evidence.get("legacy_task_response_id")
        evidence["provenance"] = {
            "canonical_evidence_id": evidence.get("id"),
            "original_task_id": evidence.get("source_task_id"),
            "original_response_id": evidence.get("legacy_task_response_id"),
        }
    result["responses_info"] = result["evidence"]
    result["documents"] = [dict(item) for item in con.execute(
        """SELECT * FROM supplier_nazk_check_documents WHERE check_id=?
           ORDER BY created_at DESC,id DESC""", (check_id,)
    )]
    tables = {str(item[0]) for item in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    tasks = []
    if "operational_tasks" in tables:
        tasks = [dict(item) for item in con.execute(
            """SELECT id task_id,task_key,status,resolution_code,assigned_officer_id
               FROM operational_tasks WHERE task_type='nazk_check'
                 AND CAST(json_extract(source_context,'$.nazk_check_id') AS INTEGER)=?
               ORDER BY created_at,id""", (check_id,))]
    task_ids = [item["task_id"] for item in tasks]
    task_events = []
    if task_ids and "operational_task_events" in tables:
        marks = ",".join("?" for _ in task_ids)
        task_events = [dict(item) for item in con.execute(
            f"SELECT id event_id,task_id,event_type,created_at,actor FROM operational_task_events WHERE task_id IN ({marks}) ORDER BY id",
            task_ids)]
    check_events = ([dict(item) for item in con.execute(
        "SELECT id event_id,event_type,event_at,event_by FROM supplier_nazk_check_events WHERE check_id=? ORDER BY id",
        (check_id,))] if "supplier_nazk_check_events" in tables else [])
    result["provenance"] = {
        "operational_tasks": tasks,
        "task_response_ids": [item.get("legacy_task_response_id") for item in result["evidence"]
                              if item.get("legacy_task_response_id") is not None],
        "channel_sources": [{"channel": key, "task_id": value.get("source_task_id")}
                            for key, value in result["channels"].items() if value.get("source_task_id")],
        "task_events": task_events,
        "check_events": check_events,
    }
    return result


def event(con: sqlite3.Connection, check_id: int, event_type: str, actor: str, details: dict | None = None) -> None:
    con.execute(
        """INSERT INTO supplier_nazk_check_events
           (check_id,event_type,event_at,event_by,details_json) VALUES (?,?,?,?,?)""",
        (check_id,event_type,now_iso(),actor,json.dumps(details or {},ensure_ascii=False)),
    )


def set_responsible_officer(
    con: sqlite3.Connection, check_id: int, officer_id: int | None, actor: str, timestamp: str | None = None
) -> None:
    stamp = timestamp or now_iso()
    officer = None
    if officer_id:
        officer = con.execute(
            "SELECT id,full_name FROM authorized_officers WHERE id=? AND active=1", (officer_id,)
        ).fetchone()
        if not officer:
            raise ValueError("Оберіть активну УО")
    old = con.execute(
        "SELECT responsible_officer_id,responsible_officer_name FROM supplier_nazk_checks WHERE id=?", (check_id,)
    ).fetchone()
    if not old:
        raise KeyError(check_id)
    new_id = int(officer["id"]) if officer else None
    new_name = str(officer["full_name"]) if officer else ""
    if old["responsible_officer_id"] == new_id and str(old["responsible_officer_name"] or "") == new_name:
        return
    con.execute(
        """UPDATE supplier_nazk_checks SET responsible_officer_id=?,responsible_officer_name=?,
           updated_at=?,updated_by=? WHERE id=?""", (new_id, new_name, stamp, actor, check_id)
    )
    con.execute(
        """INSERT INTO supplier_nazk_check_events
           (check_id,event_type,event_at,event_by,details_json) VALUES (?,?,?,?,?)""",
        (check_id, "responsible_uo_changed", stamp, actor,
         json.dumps({"old_officer_id": old["responsible_officer_id"], "new_officer_id": new_id,
                     "old_name": old["responsible_officer_name"], "new_name": new_name}, ensure_ascii=False)),
    )


def set_person_tax_id(
    con: sqlite3.Connection, check_id: int, value: str, actor: str, timestamp: str | None = None
) -> None:
    stamp = timestamp or now_iso()
    con.execute(
        "UPDATE supplier_nazk_checks SET person_tax_id=?,updated_at=?,updated_by=? WHERE id=?",
        (value, stamp, actor, check_id),
    )
    con.execute(
        """INSERT INTO supplier_nazk_check_events
           (check_id,event_type,event_at,event_by,details_json) VALUES (?,?,?,?,?)""",
        (check_id, "person_tax_id_recorded", stamp, actor,
         json.dumps({"person_tax_id": value}, ensure_ascii=False)),
    )


def record_channel(
    con: sqlite3.Connection, check_id: int, channel: str, payload: dict, actor: str,
    source_task_id: str | None = None,
) -> None:
    stamp = now_iso()
    con.execute(
        """INSERT INTO supplier_nazk_check_channels
           (check_id,channel,status,sent_at,document_number,evidence_url,comment,recorded_at,recorded_by,source_task_id)
           VALUES (?,?,'waiting',?,?,?,?,?,?,?) ON CONFLICT(check_id,channel) DO UPDATE SET
           status='waiting',sent_at=excluded.sent_at,document_number=excluded.document_number,
           evidence_url=excluded.evidence_url,comment=excluded.comment,
           recorded_at=excluded.recorded_at,recorded_by=excluded.recorded_by,
           source_task_id=COALESCE(excluded.source_task_id,supplier_nazk_check_channels.source_task_id)""",
        (check_id, channel, str(payload.get("sent_at") or "").strip(),
         str(payload.get("outgoing_number") or "").strip(),
         str(payload.get("reference_url") or "").strip(),
         str(payload.get("comment") or "").strip(), stamp, actor, source_task_id),
    )


def add_evidence(
    con: sqlite3.Connection, check_id: int, payload: dict, actor: str, *, post_close: bool,
    source_task_id: str | None = None,
) -> int:
    stamp = now_iso()
    cursor = con.execute(
        """INSERT INTO supplier_nazk_check_evidence
           (check_id,evidence_type,source,evidence_date,document_number,short_summary,
            uploaded_document_name,uploaded_document_url,evidence_url,comment,information_result,
            post_close,recorded_at,recorded_by,source_task_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (check_id, str(payload.get("evidence_type") or "response").strip(),
         str(payload.get("source") or "other").strip(), str(payload.get("response_date") or "").strip(),
         str(payload.get("incoming_number") or "").strip(), str(payload.get("summary") or "").strip(),
         str(payload.get("uploaded_document_name") or payload.get("document_reference") or "").strip(),
         str(payload.get("uploaded_document_url") or "").strip(),
         str(payload.get("reference_url") or "").strip(), str(payload.get("comment") or "").strip(),
         str(payload.get("information_result") or "neutral").strip(), int(post_close), stamp, actor,
         source_task_id),
    )
    return int(cursor.lastrowid)


def update_evidence(
    con: sqlite3.Connection, check_id: int, evidence_id: int, payload: dict, actor: str
) -> tuple[dict, dict]:
    row = con.execute(
        "SELECT * FROM supplier_nazk_check_evidence WHERE id=? AND check_id=?", (evidence_id, check_id)
    ).fetchone()
    if not row:
        raise KeyError(evidence_id)
    old = dict(row)
    values = {
        "source": str(payload.get("source", old["source"]) or "").strip(),
        "evidence_date": str(payload.get("response_date", old["evidence_date"]) or "").strip(),
        "document_number": str(payload.get("incoming_number", old["document_number"]) or "").strip(),
        "short_summary": str(payload.get("summary", old["short_summary"]) or "").strip(),
        "uploaded_document_name": str(payload.get("document_reference", old["uploaded_document_name"]) or "").strip(),
        "evidence_url": str(payload.get("reference_url", old["evidence_url"]) or "").strip(),
        "comment": str(payload.get("comment", old["comment"]) or "").strip(),
        "information_result": str(payload.get("information_result", old["information_result"]) or "neutral").strip(),
    }
    con.execute(
        """UPDATE supplier_nazk_check_evidence SET source=?,evidence_date=?,document_number=?,
           short_summary=?,uploaded_document_name=?,evidence_url=?,comment=?,information_result=?,
           updated_at=?,updated_by=? WHERE id=? AND check_id=?""",
        (*values.values(), now_iso(), actor, evidence_id, check_id),
    )
    return old, dict(con.execute(
        "SELECT * FROM supplier_nazk_check_evidence WHERE id=?", (evidence_id,)
    ).fetchone())
