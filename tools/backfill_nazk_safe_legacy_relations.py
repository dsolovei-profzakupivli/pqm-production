"""One-off, idempotent backfill for the approved single-fact NAZK checks.

This tool never runs reconciliation/builders and never changes check/task state.
Its input mapping is the immutable result of the 2026-09-12 read-only audit.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import nazk_workflow
import server


APPROVED = {
    "00476808": (122, "8373"), "14060129": (67, "449928"),
    "16286441": (87, "3077"), "1966202476": (1, "33737"),
    "2121506059": (2, "47121"), "2161814953": (53, "440921"),
    "2221102111": (4, "337146"), "2271104894": (5, "368715"),
    "22802562": (106, "11156"), "2288101199": (52, "29966"),
    "2309712034": (6, "521947"), "2317316516": (111, "546352"),
    "2345206327": (8, "8169"), "2391507349": (9, "22393"),
    "2399413836": (11, "62462"), "24149451": (159, "9665"),
    "2463403497": (119, "548869"), "2481311230": (63, "441360"),
    "2486309097": (12, "288629"), "2505414295": (13, "73303"),
    "25156973": (112, "37159"), "2524818138": (14, "336640"),
    "2549900307": (15, "265271"), "2630311134": (16, "303155"),
    "2644500312": (17, "6307"), "2646802774": (127, "338383"),
    "2713018531": (65, "539108"), "2715108852": (20, "102291"),
    "2755916567": (62, "535092"), "2771810862": (120, "550157"),
    "2795716601": (129, "555345"), "2800917020": (101, "543406"),
    "2810810029": (54, "13212"), "2829305043": (22, "48869"),
    "2869218446": (55, "535092"), "2914620311": (25, "23711"),
    "2928604521": (26, "55667"), "2931205191": (27, "35465"),
    "2935018014": (56, "382516"), "2942815673": (114, "547067"),
    "2971909094": (28, "299469"), "2972321439": (134, "557395"),
    "2979009835": (29, "13962"), "30284125": (115, "22495"),
    "3028508966": (31, "10616"), "3046104498": (32, "362985"),
    "30622511": (121, "305874"), "3074318905": (142, "547865"),
    "3105808631": (103, "544797"), "3131419872": (57, "70467"),
    "3147618478": (35, "525873"), "31485097": (68, "20637"),
    "3155111770": (36, "391640"), "3161021073": (37, "337599"),
    "31626517": (118, "547458"), "3163725539": (38, "331170"),
    "3243806695": (135, "556680"), "3265017794": (39, "395969"),
    "3266712172": (40, "123113"), "3280814945": (74, "539764"),
    "33006727": (104, "544580"), "33856421": (88, "325271"),
    "3410817614": (41, "4189"), "3439700226": (42, "508196"),
    "34539354": (136, "557778"), "3548206336": (105, "543149"),
    "3556600476": (43, "380803"), "35870266": (107, "362985"),
    "3629106310": (59, "521947"), "37351098": (147, "555676"),
    "37644861": (69, "343107"), "38109059": (137, "556022"),
    "3836801075": (45, "19739"), "39014885": (128, "553534"),
    "39910269": (99, "118738"), "40049880": (76, "458393"),
    "41275741": (138, "557395"), "41552981": (47, "17953"),
    "41602686": (160, "549313"), "42472703": (108, "10868"),
    "42499966": (78, "70467"), "42915052": (124, "552182"),
    "43370789": (95, "414650"), "43483543": (96, "39136"),
    "43521379": (97, "43590"), "43559643": (48, "87983"),
    "43804233": (61, "357172"), "44452558": (81, "55866"),
    "44605957": (90, "92538"), "44901654": (49, "17013"),
    "44929554": (141, "546052"), "44960154": (50, "316301"),
    "45166420": (117, "368722"), "45622439": (123, "383188"),
    "45668033": (72, "17873"), "46078434": (148, "402269"),
    "46078612": (150, "4189"), "46099847": (73, "88449"),
}

MULTI_FACT_GUARD = {
    "2195211336": 3, "2763019510": 21, "2830204938": 23,
    "32794258": 92, "3797607519": 44, "38602052": 60,
    "39795904": 89, "45053047": 84,
}


def _hash_rows(con: sqlite3.Connection, sql: str, params=()) -> str:
    rows = [tuple(row) for row in con.execute(sql, params)]
    return hashlib.sha256(repr(rows).encode("utf-8")).hexdigest()


def _snapshot(con: sqlite3.Connection) -> dict:
    approved_ids = [value[0] for value in APPROVED.values()]
    marks = ",".join("?" for _ in approved_ids)
    return {
        "checks": _hash_rows(con, f"SELECT * FROM supplier_nazk_checks WHERE id IN ({marks}) ORDER BY id", approved_ids),
        "documents": _hash_rows(con, f"SELECT * FROM supplier_nazk_check_documents WHERE check_id IN ({marks}) ORDER BY id", approved_ids),
        "tasks": _hash_rows(con, "SELECT * FROM operational_tasks ORDER BY id"),
        "task_events": _hash_rows(con, "SELECT * FROM operational_task_events ORDER BY id"),
        "managers": _hash_rows(con, "SELECT * FROM supplier_managers ORDER BY id"),
        "reviews": _hash_rows(con, "SELECT * FROM supplier_nazk_reviews ORDER BY supplier_code"),
        "registry": _hash_rows(con, "SELECT * FROM nazk_registry ORDER BY source_id"),
        "evidence": _hash_rows(con, "SELECT * FROM supplier_nazk_check_evidence ORDER BY id"),
    }


def _registry_by_name(con: sqlite3.Connection) -> dict[str, list[dict]]:
    result: dict[str, list[dict]] = {}
    for row in con.execute(
        """SELECT source_id,full_name,offense_name,court_case_number,sentence_date,
                  punishment_start,decision_url,raw_json FROM nazk_registry"""
    ):
        item = dict(row)
        result.setdefault(nazk_workflow.normalize_name(item["full_name"]), []).append(item)
    return result


def _registry_decision_dates(source: dict) -> set[str]:
    """Return canonical decision dates, excluding later effective/punishment dates."""
    values = {nazk_workflow._date_value(source.get("sentence_date"))}
    try:
        raw = json.loads(source.get("raw_json") or "{}")
    except (TypeError, ValueError):
        raw = {}

    def collect(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key in {"decision_date", "decisionDate", "decree_date", "decreeDate", "sentence_date", "sentenceDate"}:
                    values.add(nazk_workflow._date_value(child))
                collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)

    collect(raw)
    return {value for value in values if value}


def validate(con: sqlite3.Connection) -> tuple[list[dict], list[dict], list[dict]]:
    registry = _registry_by_name(con)
    valid, skipped, already = [], [], []
    for supplier_code, (check_id, expected_source_id) in sorted(APPROVED.items()):
        reasons = []
        check = con.execute("SELECT * FROM supplier_nazk_checks WHERE id=?", (check_id,)).fetchone()
        manager = con.execute(
            "SELECT * FROM supplier_managers WHERE supplier_code=? AND is_current=1 ORDER BY id DESC LIMIT 1",
            (supplier_code,),
        ).fetchone()
        if not check or check["supplier_code"] != supplier_code:
            reasons.append("check_missing_or_supplier_mismatch")
        if not manager:
            reasons.append("current_manager_missing")
        if reasons:
            skipped.append({"supplier_code": supplier_code, "check_id": check_id, "reasons": reasons})
            continue
        normalized = nazk_workflow.normalize_name(manager["manager_name"])
        if check["workflow_status"] != "completed":
            reasons.append("check_not_completed")
        if check["result"] not in {"confirmed", "refuted"}:
            reasons.append("check_not_factual")
        if int(check["manager_id"] or 0) != int(manager["id"]):
            reasons.append("manager_id_mismatch")
        if nazk_workflow.normalize_name(check["manager_name"]) != normalized:
            reasons.append("normalized_person_mismatch")
        sources = registry.get(normalized, [])
        if len(sources) != 1:
            reasons.append(f"current_exact_source_count:{len(sources)}")
            source = None
        else:
            source = sources[0]
            if str(source["source_id"]) != expected_source_id:
                reasons.append("approved_source_id_changed")
        fact_date = nazk_workflow.registry_fact_date(source) if source else ""
        completed_date = nazk_workflow._date_value(check["completed_at"])
        if not fact_date or not completed_date or fact_date > completed_date:
            reasons.append("fact_not_present_by_completion")

        provenance_type = ""
        provenance = {}
        if check["is_legacy"]:
            review = con.execute(
                "SELECT * FROM supplier_nazk_reviews WHERE source_row=?",
                (check["legacy_source_row"],),
            ).fetchone()
            if not review:
                reasons.append("legacy_source_row_missing")
            else:
                provenance_type = "legacy_supplier_nazk_review"
                provenance = {"original_source_row": review["source_row"]}
                if review["supplier_code"] != supplier_code:
                    reasons.append("legacy_supplier_mismatch")
                if nazk_workflow.normalize_name(review["manager_name"]) != normalized:
                    reasons.append("legacy_person_mismatch")
                review_decision_date = nazk_workflow._date_value(review["decision_date"])
                if review_decision_date and review_decision_date not in _registry_decision_dates(source or {}):
                    reasons.append("legacy_decision_date_mismatch")
                if not review_decision_date and not str(review["evidence_url"] or "").strip():
                    reasons.append("legacy_provenance_missing_date_and_evidence")
                legacy_result = str(review["result"] or "").strip().casefold()
                if legacy_result in {"спростовано", "ні", "refuted"}:
                    expected_result = "refuted"
                elif legacy_result in {"підтверджено", "так", "confirmed"}:
                    expected_result = "confirmed"
                else:
                    expected_result = ""
                    reasons.append("legacy_result_unknown")
                if expected_result != check["result"]:
                    reasons.append("legacy_result_mismatch")
        else:
            control = con.execute(
                "SELECT * FROM submission_nazk_controls WHERE supplier_nazk_check_id=?",
                (check_id,),
            ).fetchone()
            document = con.execute(
                """SELECT * FROM supplier_nazk_check_documents
                   WHERE check_id=? AND source='prozorro_submission'
                   ORDER BY id DESC LIMIT 1""",
                (check_id,),
            ).fetchone()
            if not control or not document or control["submission_id"] != document["submission_id"]:
                reasons.append("submission_document_provenance_missing")
            else:
                provenance_type = "submission_nazk_document"
                provenance = {
                    "submission_id": control["submission_id"],
                    "document_row_id": document["id"],
                    "prozorro_document_id": document["prozorro_document_id"],
                }

        tuple_item = {
            "supplier_code": supplier_code,
            "check_id": check_id,
            "manager_id": int(manager["id"]),
            "normalized_person": normalized,
            "source_id": expected_source_id,
            "fact_date": fact_date,
            "completed_at": check["completed_at"],
            "provenance_id": provenance,
            "provenance_type": provenance_type,
        }
        relation = con.execute(
            "SELECT 1 FROM supplier_nazk_check_matches WHERE check_id=? AND nazk_source_id=?",
            (check_id, expected_source_id),
        ).fetchone()
        if reasons:
            skipped.append({**tuple_item, "reasons": reasons})
        elif relation:
            already.append(tuple_item)
        else:
            valid.append(tuple_item)
    return valid, skipped, already


def strict_covered_count(con: sqlite3.Connection) -> int:
    registry = _registry_by_name(con)
    covered = 0
    for supplier_code, (check_id, _) in APPROVED.items():
        check = dict(con.execute(
            """SELECT c.*,GROUP_CONCAT(m.nazk_source_id) source_ids
               FROM supplier_nazk_checks c
               LEFT JOIN supplier_nazk_check_matches m ON m.check_id=c.id
               WHERE c.id=? GROUP BY c.id""", (check_id,)
        ).fetchone())
        matches = registry.get(nazk_workflow.normalize_name(check["manager_name"]), [])
        if nazk_workflow.find_covering_factual_check([check], matches):
            covered += 1
    return covered


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if len(APPROVED) != 98 or len(MULTI_FACT_GUARD) != 8:
        raise RuntimeError("Approved classification mapping has unexpected size")

    con = sqlite3.connect(server.DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    try:
        valid, skipped, already = validate(con)
        output = {
            "mode": "apply" if args.apply else "dry-run",
            "approved": len(APPROVED), "validated_pending": len(valid),
            "already_applied": len(already), "skipped": skipped,
            "strict_covered_before": strict_covered_count(con),
            "inserted_relations": 0, "inserted_events": 0,
        }
        if not args.apply or not valid:
            print(json.dumps(output, ensure_ascii=False, indent=2))
            return

        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        backup_dir = ROOT / "backups" / "nazk_safe_relation_backfill" / stamp
        backup_dir.mkdir(parents=True, exist_ok=False)
        backup_path = backup_dir / "pqm_before.sqlite3"
        with sqlite3.connect(backup_path) as target:
            con.backup(target)
        manifest = {
            "classification": "safe_relation_backfill",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "database": str(server.DB_PATH),
            "tuples": valid,
            "skipped": skipped,
        }
        manifest_text = json.dumps(manifest, ensure_ascii=False, indent=2)
        manifest_bytes = manifest_text.encode("utf-8")
        manifest_path = backup_dir / "manifest.json"
        manifest_path.write_bytes(manifest_bytes)
        manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()

        before = _snapshot(con)
        multi_before = {
            check_id: con.execute(
                "SELECT COUNT(*) FROM supplier_nazk_check_matches WHERE check_id=?", (check_id,)
            ).fetchone()[0]
            for check_id in MULTI_FACT_GUARD.values()
        }
        con.execute("BEGIN IMMEDIATE")
        inserted = events = 0
        event_at = datetime.now(timezone.utc).isoformat()
        for item in valid:
            cursor = con.execute(
                """INSERT OR IGNORE INTO supplier_nazk_check_matches
                   (check_id,nazk_source_id,match_status,created_at)
                   VALUES (?,?,'candidate',?)""",
                (item["check_id"], item["source_id"], event_at),
            )
            if cursor.rowcount != 1:
                continue
            inserted += 1
            details = {
                "source_id": item["source_id"],
                "classification": "safe_relation_backfill",
                "provenance_type": item["provenance_type"],
                **item["provenance_id"],
            }
            con.execute(
                """INSERT INTO supplier_nazk_check_events
                   (check_id,event_type,event_at,event_by,details_json)
                   VALUES (?,'legacy_registry_relation_backfilled',?,'PQM SYSTEM',?)""",
                (item["check_id"], event_at, json.dumps(details, ensure_ascii=False)),
            )
            events += 1
        after = _snapshot(con)
        if before != after:
            raise RuntimeError("Protected factual/task/business rows changed")
        multi_after = {
            check_id: con.execute(
                "SELECT COUNT(*) FROM supplier_nazk_check_matches WHERE check_id=?", (check_id,)
            ).fetchone()[0]
            for check_id in MULTI_FACT_GUARD.values()
        }
        if multi_before != multi_after:
            raise RuntimeError("Category B relations changed")
        duplicates = con.execute(
            """SELECT COUNT(*) FROM (
                 SELECT check_id,nazk_source_id,COUNT(*) n
                 FROM supplier_nazk_check_matches
                 GROUP BY check_id,nazk_source_id HAVING n>1)"""
        ).fetchone()[0]
        strict_after = strict_covered_count(con)
        if duplicates:
            raise RuntimeError("Duplicate check/source relations detected")
        if inserted != len(valid) or events != inserted:
            raise RuntimeError("Inserted relation/event count mismatch")
        if strict_after - output["strict_covered_before"] != inserted:
            raise RuntimeError("Strict coverage increase does not match inserted relations")
        con.commit()
        output.update({
            "backup": str(backup_path), "manifest": str(manifest_path),
            "manifest_sha256": manifest_hash,
            "inserted_relations": inserted, "inserted_events": events,
            "strict_covered_after": strict_after,
            "category_b_unchanged": multi_before == multi_after,
            "duplicate_relations": duplicates,
            "protected_rows_unchanged": before == after,
        })
        print(json.dumps(output, ensure_ascii=False, indent=2))
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


if __name__ == "__main__":
    main()
