"""Read-only CLI for a captured Google EDR values snapshot."""
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import edr_sync_v2


def main():
    if len(sys.argv) > 2:
        values = {}
        for source in sys.argv[1:]:
            sheet, filename = source.split("=", 1)
            values.setdefault(sheet, []).extend(json.loads(Path(filename).read_text(encoding="utf-8")))
    elif len(sys.argv) > 1:
        values = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    else:
        values = json.load(sys.stdin)
    snapshot = edr_sync_v2.source_snapshot(values)
    db_path = Path(__file__).resolve().parents[1] / "data" / "pqm.sqlite3"
    con = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    con.create_function("DIGITS", 1, edr_sync_v2.normalize_code, deterministic=True)
    con.execute("PRAGMA query_only=ON")
    try:
        result = edr_sync_v2.build_preview(con, snapshot)
    finally:
        con.close()
    print(json.dumps({
        "source_fingerprint": result["source_fingerprint"],
        "summary": result["summary"],
        "conflicts_total": len(result["conflicts"]),
        "conflicts_sample": result["conflicts"][:20],
        "duplicate_codes": result["duplicate_codes"],
        "manager_differences": [{
            "supplier_code": item["supplier_code"],
            "kind": item["manager_change_kind"],
            "classification_reason": item["manager_change_reason"],
            "known_identity_source": item["manager_resolution_source"],
            "old_manager": item["manager_previous_name"],
            "google_manager": item["incoming"]["manager_name"],
            "verification_date": item["incoming"]["edr_checked_at"],
            "officer": item["incoming"]["edr_officer"],
            "resulting_observed_at": item["incoming"]["edr_checked_at"],
            "conflicting_evidence": item["manager_conflicting_evidence"],
        } for item in result["items"] if item["manager_change_kind"] != "same"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
