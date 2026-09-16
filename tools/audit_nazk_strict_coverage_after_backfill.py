"""Read-only strict-coverage impact report for the approved NAZK backfill."""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import nazk_workflow
import server
from tools.backfill_nazk_safe_legacy_relations import APPROVED, MULTI_FACT_GUARD


def main() -> None:
    uri = Path(server.DB_PATH).resolve().as_uri() + "?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row
    con.create_function(
        "NORMALIZE_NAME", 1,
        lambda value: " ".join(re.sub(r"[’'`\-]+", " ", str(value or "").casefold()).split()),
        deterministic=True,
    )
    rows = [dict(row) for row in con.execute(
        """SELECT s.supplier_code,s.active_count,m.id manager_id,m.manager_name
           FROM supplier_registry_summary s
           JOIN supplier_managers m ON m.supplier_code=s.supplier_code AND m.is_current=1
           WHERE s.active_count>0
           ORDER BY s.supplier_code"""
    )]
    registry_by_name = {}
    for registry_row in con.execute(
        """SELECT source_id,full_name,offense_name,court_case_number,sentence_date,punishment_start,
                  decision_url,raw_json FROM nazk_registry WHERE COALESCE(full_name,'')<>''"""
    ):
        registry_by_name.setdefault(nazk_workflow.normalize_name(registry_row["full_name"]), []).append(dict(registry_row))
    rows = [row for row in rows if nazk_workflow.normalize_name(row["manager_name"]) in registry_by_name]
    scoped_codes = {row["supplier_code"] for row in rows}
    checks_by_supplier = {}
    for check_row in con.execute(
        """SELECT c.*,GROUP_CONCAT(cm.nazk_source_id) source_ids FROM supplier_nazk_checks c
           JOIN supplier_managers m ON m.supplier_code=c.supplier_code AND m.is_current=1
             AND (m.id=c.manager_id OR (c.manager_id IS NULL AND NORMALIZE_NAME(c.manager_name)=m.normalized_name))
           LEFT JOIN supplier_nazk_check_matches cm ON cm.check_id=c.id
           GROUP BY c.id
           ORDER BY c.supplier_code,COALESCE(c.completed_at,c.started_at,c.created_at) DESC,c.id DESC"""
    ):
        if check_row["supplier_code"] in scoped_codes:
            checks_by_supplier.setdefault(check_row["supplier_code"], []).append(dict(check_row))
    states = []
    for row in rows:
        state = nazk_workflow._supplier_state_from_prefetched(
            int(row["active_count"] or 0),
            {"id": row["manager_id"], "manager_name": row["manager_name"]},
            registry_by_name.get(nazk_workflow.normalize_name(row["manager_name"]), []),
            checks_by_supplier.get(row["supplier_code"], []),
        )
        states.append({"supplier_code": row["supplier_code"], **state})

    fully = [row for row in states if row["state"] in {"confirmed", "refuted"}]
    needs = [row for row in states if row.get("action") == "create_needs_review"]
    open_rows = [
        row for row in states
        if row["state"] in nazk_workflow.OPEN_WORKFLOW_STATUSES and not row.get("action")
    ]
    category_b = []
    for supplier_code, check_id in MULTI_FACT_GUARD.items():
        relations = con.execute(
            "SELECT COUNT(*) FROM supplier_nazk_check_matches WHERE check_id=?", (check_id,)
        ).fetchone()[0]
        category_b.append({"supplier_code": supplier_code, "check_id": check_id, "relations": relations})
    ambiguous = [row for row in states if row["supplier_code"] == "44911966"]
    approved_covered = [row for row in fully if row["supplier_code"] in APPROVED]
    output = {
        "reconciliation_scope_current_exact_match": len(states),
        "fully_covered": len(fully),
        "fully_covered_supplier_codes_check_ids": [
            [row["supplier_code"], row.get("check_id")] for row in fully
        ],
        "approved_category_a_covered": len(approved_covered),
        "needs_review_due_missing_relation": len(needs),
        "needs_review_items": [[row["supplier_code"], row.get("previous_check_id"), row.get("reason")] for row in needs],
        "multi_fact_needs_provenance": len(category_b),
        "multi_fact_items": category_b,
        "ambiguous_historical": len(ambiguous),
        "ambiguous_items": ambiguous,
        "open_checks": len(open_rows),
        "open_items": [[row["supplier_code"], row.get("check_id"), row["state"]] for row in open_rows],
        "state_counts": dict(sorted(Counter(row["state"] for row in states).items())),
        "action_counts": dict(sorted(Counter(str(row.get("action")) for row in states).items())),
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    con.close()


if __name__ == "__main__":
    main()
