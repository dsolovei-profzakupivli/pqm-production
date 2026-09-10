"""Idempotent migration of the approved 141 legacy NАЗК reviews.

The command is read-only by default. Pass --apply to write the approved
historical checks. It deliberately does not run reconciliation and does not
create submission-level controls or structured requests.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime

import server


EXPECTED_RESULTS = {
    "спростовано": 121,
    "підтверджено": 7,
    "на запит": 10,
    "не актуально": 2,
    "": 1,
}
HISTORICAL_MANAGER_ROWS = {87, 110, 111}
UNRESOLVED_MANAGER_ROWS = {65}
SYSTEM_USER = "PQM SYSTEM"


def clean(value: object) -> str:
    return " ".join(str(value or "").split())


def normalized_name(value: object) -> str:
    return server.normalize_manager_name(clean(value))


def iso_date(value: object) -> str | None:
    text = clean(value)
    if not text:
        return None
    for pattern in ("%d.%m.%Y", "%Y-%m-%d", "%d.%m.%y"):
        try:
            return datetime.strptime(text, pattern).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return text


def legacy_key(row: sqlite3.Row) -> str:
    return f"nazk_google_sheet:{int(row['source_row'])}:{row['supplier_code']}"


def source_id_for_confirmed(row: sqlite3.Row, registry_by_name: dict[str, list[sqlite3.Row]]) -> str:
    candidates = registry_by_name.get(normalized_name(row["manager_name"]), [])
    case_number = re.sub(r"\s+", "", clean(row["case_number"]).casefold())
    decision_date = iso_date(row["decision_date"])
    strict = [
        item for item in candidates
        if re.sub(r"\s+", "", clean(item["court_case_number"]).casefold()) == case_number
        and iso_date(item["sentence_date"]) == decision_date
    ]
    if len(strict) != 1:
        raise RuntimeError(
            f"Legacy row {row['source_row']}: expected one strict NАЗК match, found {len(strict)}"
        )
    return str(strict[0]["source_id"])


def validate_source(con: sqlite3.Connection) -> tuple[list[sqlite3.Row], dict[str, list[sqlite3.Row]]]:
    rows = con.execute(
        "SELECT * FROM supplier_nazk_reviews ORDER BY source_row, supplier_code"
    ).fetchall()
    if len(rows) != 141:
        raise RuntimeError(f"Expected 141 legacy reviews, found {len(rows)}")
    actual = Counter(clean(row["result"]).casefold() for row in rows)
    if actual != Counter(EXPECTED_RESULTS):
        raise RuntimeError(f"Unexpected legacy result distribution: {dict(actual)}")
    if sum(bool(clean(row["evidence_url"])) for row in rows) != 129:
        raise RuntimeError("Expected exactly 129 legacy evidence URLs")

    registry_by_name: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for item in con.execute(
        "SELECT source_id, full_name, court_case_number, sentence_date FROM nazk_registry"
    ):
        registry_by_name[normalized_name(item["full_name"])].append(item)
    for row in rows:
        if clean(row["result"]).casefold() == "підтверджено":
            source_id_for_confirmed(row, registry_by_name)
    return rows, registry_by_name


def manager_for_row(con: sqlite3.Connection, row: sqlite3.Row, now: str, apply: bool) -> tuple[int | None, str]:
    source_row = int(row["source_row"])
    if source_row in UNRESOLVED_MANAGER_ROWS:
        return None, "unresolved"

    supplier_code = clean(row["supplier_code"])
    manager_name = clean(row["manager_name"])
    normalized = normalized_name(manager_name)
    current = con.execute(
        "SELECT id, normalized_name FROM supplier_managers WHERE supplier_code=? AND is_current=1",
        (supplier_code,),
    ).fetchone()
    if current and current["normalized_name"] == normalized:
        return int(current["id"]), "current_exact"

    if source_row not in HISTORICAL_MANAGER_ROWS:
        raise RuntimeError(f"Legacy row {source_row}: unexpected unresolved manager mismatch")
    historical = con.execute(
        """SELECT id FROM supplier_managers
           WHERE supplier_code=? AND normalized_name=? AND is_current=0
           ORDER BY id LIMIT 1""",
        (supplier_code, normalized),
    ).fetchone()
    if historical:
        return int(historical["id"]), "historical_existing"
    if not apply:
        return None, "historical_would_create"
    cursor = con.execute(
        """INSERT INTO supplier_managers
           (supplier_code, manager_name, normalized_name, manager_tax_id,
            valid_from, valid_to, is_current, source, created_at, updated_at)
           VALUES (?, ?, ?, NULL, NULL, NULL, 0, 'legacy_nazk_review', ?, ?)""",
        (supplier_code, manager_name, normalized, now, now),
    )
    return int(cursor.lastrowid), "historical_created"


def workflow_for(result: str) -> tuple[str, str | None]:
    mapping = {
        "спростовано": ("completed", "refuted"),
        "підтверджено": ("completed", "confirmed"),
        "на запит": ("waiting_response", None),
        "не актуально": ("legacy_archived", None),
        "": ("legacy_imported", None),
    }
    return mapping[result]


def insert_event_once(
    con: sqlite3.Connection, check_id: int, event_type: str, now: str, details: dict,
    workflow_status: str | None = None, result: str | None = None,
) -> bool:
    exists = con.execute(
        "SELECT 1 FROM supplier_nazk_check_events WHERE check_id=? AND event_type=? LIMIT 1",
        (check_id, event_type),
    ).fetchone()
    if exists:
        return False
    con.execute(
        """INSERT INTO supplier_nazk_check_events
           (check_id,event_type,event_at,event_by,new_workflow_status,new_result,details_json)
           VALUES (?,?,?,?,?,?,?)""",
        (check_id, event_type, now, SYSTEM_USER, workflow_status, result,
         json.dumps(details, ensure_ascii=False, sort_keys=True)),
    )
    return True


def migrate(apply: bool) -> dict:
    now = server.now_iso()
    con = server.db()
    try:
        rows, registry_by_name = validate_source(con)
        report = Counter()
        report["source_rows"] = len(rows)
        if apply:
            con.execute("BEGIN IMMEDIATE")

        for row in rows:
            raw_result = clean(row["result"]).casefold()
            workflow_status, result = workflow_for(raw_result)
            manager_id, manager_resolution = manager_for_row(con, row, now, apply)
            report[f"manager_{manager_resolution}"] += 1
            key = legacy_key(row)
            existing = con.execute(
                "SELECT id FROM supplier_nazk_checks WHERE legacy_key=?", (key,)
            ).fetchone()
            officer = clean(row["officer"]) or server.CURRENT_USER
            checked_date = iso_date(row["checked_at"])
            started_at = checked_date or now
            completed_at = checked_date if workflow_status in {"completed", "legacy_archived"} else None

            if existing:
                check_id = int(existing["id"])
                report["checks_existing"] += 1
                if not apply:
                    continue
            elif apply:
                cursor = con.execute(
                    """INSERT INTO supplier_nazk_checks
                       (supplier_code,manager_id,manager_name,workflow_status,result,
                        started_at,completed_at,evidence_date,covered_nazk_date,comment,
                        is_legacy,legacy_source_row,legacy_key,created_at,created_by,updated_at,updated_by)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        clean(row["supplier_code"]), manager_id, clean(row["manager_name"]),
                        workflow_status, result, started_at, completed_at, None, None,
                        clean(row["comment"]), 1, int(row["source_row"]), key,
                        now, officer, now, officer,
                    ),
                )
                check_id = int(cursor.lastrowid)
                report["checks_created"] += 1
            else:
                report["checks_would_create"] += 1
                continue

            event_details = {
                "legacy_source": "supplier_nazk_reviews",
                "legacy_source_row": int(row["source_row"]),
                "legacy_result": clean(row["result"]),
                "legacy_checked_at": clean(row["checked_at"]),
                "legacy_officer": clean(row["officer"]),
                "manager_resolution": manager_resolution,
            }
            if insert_event_once(
                con, check_id, "legacy_imported", now, event_details, workflow_status, result
            ):
                report["events_created"] += 1

            if int(row["source_row"]) in UNRESOLVED_MANAGER_ROWS:
                if insert_event_once(
                    con, check_id, "needs_manager_link_review", now,
                    {**event_details, "reason": "legacy full name differs from abbreviated current manager"},
                    workflow_status, result,
                ):
                    report["events_created"] += 1
            if not raw_result:
                if insert_event_once(
                    con, check_id, "legacy_requires_manual_review", now,
                    {**event_details, "reason": "legacy result is empty"}, workflow_status, result,
                ):
                    report["events_created"] += 1

            evidence_url = clean(row["evidence_url"])
            if evidence_url:
                document = con.execute(
                    """SELECT id FROM supplier_nazk_check_documents
                       WHERE check_id=? AND document_type='legacy_evidence'
                         AND url=? AND source='legacy_google_sheet' LIMIT 1""",
                    (check_id, evidence_url),
                ).fetchone()
                if document:
                    report["documents_existing"] += 1
                else:
                    con.execute(
                        """INSERT INTO supplier_nazk_check_documents
                           (check_id,document_type,document_date,document_number,title,url,source,created_at,created_by)
                           VALUES (?,'legacy_evidence',NULL,NULL,'',?,'legacy_google_sheet',?,?)""",
                        (check_id, evidence_url, now, officer),
                    )
                    report["documents_created"] += 1

            if result == "confirmed":
                source_id = source_id_for_confirmed(row, registry_by_name)
                match = con.execute(
                    """SELECT 1 FROM supplier_nazk_check_matches
                       WHERE check_id=? AND nazk_source_id=?""",
                    (check_id, source_id),
                ).fetchone()
                if match:
                    report["matches_existing"] += 1
                else:
                    con.execute(
                        """INSERT INTO supplier_nazk_check_matches
                           (check_id,nazk_source_id,match_status,created_at)
                           VALUES (?,?,'confirmed',?)""",
                        (check_id, source_id, now),
                    )
                    report["matches_created"] += 1

        if apply:
            con.commit()
        else:
            con.rollback()
        return dict(sorted(report.items()))
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def validation_report() -> dict:
    with server.db() as con:
        checks = con.execute(
            """SELECT workflow_status,result,COUNT(*) n FROM supplier_nazk_checks
               WHERE is_legacy=1 GROUP BY workflow_status,result ORDER BY workflow_status,result"""
        ).fetchall()
        legacy_ids = "SELECT id FROM supplier_nazk_checks WHERE is_legacy=1"
        return {
            "legacy_checks": sum(int(row["n"]) for row in checks),
            "check_distribution": [dict(row) for row in checks],
            "legacy_documents": con.execute(
                f"SELECT COUNT(*) FROM supplier_nazk_check_documents WHERE check_id IN ({legacy_ids})"
            ).fetchone()[0],
            "legacy_matches": con.execute(
                f"SELECT COUNT(*) FROM supplier_nazk_check_matches WHERE check_id IN ({legacy_ids})"
            ).fetchone()[0],
            "legacy_requests": con.execute(
                f"SELECT COUNT(*) FROM supplier_nazk_check_requests WHERE check_id IN ({legacy_ids})"
            ).fetchone()[0],
            "legacy_events": con.execute(
                f"SELECT COUNT(*) FROM supplier_nazk_check_events WHERE check_id IN ({legacy_ids})"
            ).fetchone()[0],
            "historical_managers": con.execute(
                "SELECT COUNT(*) FROM supplier_managers WHERE source='legacy_nazk_review' AND is_current=0"
            ).fetchone()[0],
            "unresolved_manager_links": con.execute(
                "SELECT COUNT(*) FROM supplier_nazk_checks WHERE is_legacy=1 AND manager_id IS NULL"
            ).fetchone()[0],
            "legacy_source_rows": con.execute("SELECT COUNT(*) FROM supplier_nazk_reviews").fetchone()[0],
            "submission_controls": con.execute("SELECT COUNT(*) FROM submission_nazk_controls").fetchone()[0],
            "integrity_check": con.execute("PRAGMA integrity_check").fetchone()[0],
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="write the approved legacy migration")
    args = parser.parse_args()
    server.init_db()
    report = migrate(args.apply)
    print(json.dumps({"mode": "apply" if args.apply else "dry-run", "migration": report}, ensure_ascii=False, indent=2))
    if args.apply:
        print(json.dumps({"validation": validation_report()}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
