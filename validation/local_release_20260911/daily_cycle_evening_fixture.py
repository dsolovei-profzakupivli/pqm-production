"""Isolated bridge for the real evening Preview/Apply in the daily-cycle test."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import edr_sync_v2 as sync
from test_edr_sync_v2 import database, row, snapshot


def run(payload):
    con = database()
    sync.register_verification_sql_functions(con)
    code = "12345678"
    day, officer = payload["pqm_date"], payload["pqm_officer"]
    con.execute("""INSERT INTO supplier_edr_profiles
      (supplier_code,edr_status,edr_checked_at,edr_officer,termination_decision_details,
       termination_record_date,termination_record_number,edr_notes,synced_at)
      VALUES (?,?,?,?,?,?,?,?,?)""", (code, payload.get("pqm_status", "Зареєстровано"),
      day, officer, *payload.get("pqm_gjkm", ["", "", "", ""]), "old"))
    if payload.get("factual"):
        evidence = {"source": "legacy_google_registry", "verification_date": day,
          "verification_officer": officer, "source_tab": "ФОП", "source_row": 2,
          "factual_edr_status": payload["factual"],
          "factual_spreadsheet_id": "SYNTHETIC_AUTHORIZED", "factual_source_tab": "ФОП",
          "factual_source_row": 2, "factual_provenance_version": 1,
          "source_digest": "a" * 64, "factual_source_digest": "b" * 64}
        sync._insert_event(con, item={"supplier_code": code, "source_sheet": "ФОП", "source_row": 2},
          event_type="legacy_google_registry", occurred_at=day, officer=officer,
          source="legacy_google_registry", changed_fields=[], snapshot=evidence, created_at="old")
    google = payload["google"]
    values = row(code=code, checked=google["i"], officer=google["l"],
                 status=google["e"], manager="")
    for index, key in [(6, "g"), (9, "j"), (10, "k"), (12, "m")]:
        values[index] = google[key]
    source = snapshot(values)
    first = sync.build_preview(con, source)
    if first["conflicts"]:
        raise AssertionError(first["conflicts"])
    sync.apply(con, source, source["source_fingerprint"], confirmed=True,
               actor="fixture", synced_at="2026-09-25T12:00:00")
    second = sync.build_preview(con, source)
    second_apply = sync.apply(con, source, source["source_fingerprint"], confirmed=True,
                              actor="fixture", synced_at="2026-09-25T12:01:00")
    current = sync.current_verification_projections(con, [code])[code]
    profile = dict(con.execute("SELECT * FROM supplier_edr_profiles WHERE supplier_code=?", (code,)).fetchone())
    events = [dict(x) for x in con.execute("SELECT * FROM supplier_edr_verification_events")]
    status = sync.active_edr_status("2026-01-01", events)
    return {"first": first["summary"], "second": second["summary"],
      "second_apply": second_apply, "date": current["verification_date"],
      "officer": current["verification_officer"], "status": status,
      "gjkm": [profile[x] for x in ("termination_decision_details", "termination_record_date",
                                "termination_record_number", "edr_notes")],
      "events": len(events)}


if __name__ == "__main__":
    print(json.dumps(run(json.load(sys.stdin)), ensure_ascii=False))
