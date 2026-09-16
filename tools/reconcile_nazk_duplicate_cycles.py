"""Targeted one-off correction for the audited 110 NАЗК cycles (CURRENT LOCAL)."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sqlite3
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import nazk_workflow
import operational_tasks
import server


AUDIT_CSV = ROOT / "artifacts" / "NAZK_110_SAFE_HISTORICAL_CLASSIFICATION_READ_ONLY.csv"


def load_audit():
    with AUDIT_CSV.open("r", encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    counts = Counter(row["classification"] for row in rows)
    if len(rows) != 110 or counts != Counter({"already_factual": 108,
                                               "ambiguous_historical": 1,
                                               "still_needs_review": 1}):
        raise RuntimeError(f"Unexpected approved audit set: total={len(rows)}, classes={dict(counts)}")
    return rows


def snapshot(con, task_ids):
    marks = ",".join("?" for _ in task_ids)
    tasks = [dict(row) for row in con.execute(
        f"""SELECT id,supplier_code,status,resolution_code,source_context,metadata,version
             FROM operational_tasks WHERE id IN ({marks}) ORDER BY id""", task_ids)]
    check_ids = [int(json.loads(row["source_context"] or "{}").get("nazk_check_id") or 0) for row in tasks]
    checks = [dict(row) for row in con.execute(
        f"""SELECT id,supplier_code,manager_id,manager_name,workflow_status,result,completed_at,
                    evidence_date,covered_nazk_date,comment,is_legacy
             FROM supplier_nazk_checks WHERE id IN ({','.join('?' for _ in check_ids)}) ORDER BY id""",
        check_ids)]
    factual = [dict(row) for row in con.execute(
        """SELECT id,supplier_code,manager_id,manager_name,workflow_status,result,started_at,
                  completed_at,evidence_date,covered_nazk_date,comment,is_legacy
           FROM supplier_nazk_checks WHERE workflow_status='completed'
             AND result IN ('confirmed','refuted') ORDER BY id""")]
    factual_hash = hashlib.sha256(json.dumps(factual, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return {
        "task_counts": dict(Counter(f"{r['status']}:{r['resolution_code'] or '-'}" for r in tasks)),
        "linked_check_counts": dict(Counter(f"{r['workflow_status']}:{r['result'] or '-'}" for r in checks)),
        "factual_check_count": len(factual), "factual_checks_sha256": factual_hash,
        "tasks": tasks,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    rows = load_audit()
    all_ids = [row["task_id"] for row in rows]
    factual_ids = [row["task_id"] for row in rows if row["classification"] == "already_factual"]
    codes = sorted({row["supplier_code"] for row in rows})
    with server.db() as con:
        before = snapshot(con, all_ids)
        dry = operational_tasks.reconcile_duplicate_nazk_tasks(con, all_ids)
        con.rollback()
    output = {"approved_classes": dict(Counter(row["classification"] for row in rows)),
              "before": {key: value for key, value in before.items() if key != "tasks"}, "dry_run": dry}
    if not args.apply:
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return
    if dry["proposed"] != 108:
        raise RuntimeError(f"Guard recheck proposed {dry['proposed']} tasks instead of 108")
    backup_dir = ROOT / "backups" / f"nazk_duplicate_cycle_{datetime.now():%Y%m%d_%H%M%S}"
    backup_dir.mkdir(parents=True)
    with sqlite3.connect(server.DB_PATH) as source, sqlite3.connect(backup_dir / "pqm.sqlite3") as target:
        source.backup(target)
    with server.db() as con:
        con.execute("BEGIN IMMEDIATE")
        applied = operational_tasks.reconcile_duplicate_nazk_tasks(con, factual_ids, apply=True)
        if applied["changed"] != 108:
            raise RuntimeError(f"Applied {applied['changed']} tasks instead of 108")
        con.commit()
    rebuilds = []
    for number in (1, 2):
        with server.db() as con:
            con.execute("BEGIN IMMEDIATE")
            supplier_result = nazk_workflow.reconcile_active_supplier_nazk(
                con, apply=True, supplier_codes=codes)
            task_result = operational_tasks.materialize_nazk_tasks(
                con, f"PQM NАЗК safe correction rebuild {number}", supplier_codes=codes)
            con.commit()
            rebuilds.append({"supplier_reconciliation": supplier_result,
                             "task_materialization": task_result})
    with server.db() as con:
        repeat = operational_tasks.reconcile_duplicate_nazk_tasks(con, all_ids, apply=True)
        after = snapshot(con, all_ids)
        controls = {code: dict(con.execute(
            """SELECT id,supplier_code,status,resolution_code,source_context FROM operational_tasks
               WHERE supplier_code=? AND task_type='nazk_check' ORDER BY created_at DESC,id DESC LIMIT 1""",
            (code,)).fetchone()) for code in ("44911966", "45039148")}
    if before["factual_checks_sha256"] != after["factual_checks_sha256"]:
        raise RuntimeError("Canonical factual checks changed during correction")
    output.update({"backup": str(backup_dir / "pqm.sqlite3"), "applied": applied,
                   "rebuilds": rebuilds, "repeat": repeat,
                   "after": {key: value for key, value in after.items() if key != "tasks"},
                   "controls": controls})
    report = ROOT / "artifacts" / "NAZK_110_DUPLICATE_CYCLE_SAFE_CORRECTION.json"
    report.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
