"""Bounded diagnostic only. Never a runtime consumer or historical backfill.

Natural lifecycle hooks remain LIVE_PENDING. Frozen audit annotations are not
SQLite events and never supply dates/actors to the accepted projection adapter.
"""
import argparse
from collections import Counter
from contextlib import closing
from datetime import datetime
import json
import os
from pathlib import Path
import sqlite3
import sys
import time
from urllib.parse import quote
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import edr_sync_v2 as legacy
import supplier_evidence_projection_v3 as adapter

COHORTS = {
    "c2": ["45054758"],
    "stale_active": "2077003493 2886810864 2981518432 3385014935 3602006515 3618208369 3624813159 30795712 39984849 41141768 45547692 46120124".split(),
    "exclusion": ["33345054"],
    "never_admitted": "00186520 00212831 00374048 00377163 004062589".split(),
    "suspended": ["44368854"],
    "multi_inclusion": "00377213 00379413 00380497 00381381 00445883".split(),
    "google_pending": "45054758 45088216 45101776 32800996 33860155 23098585 01756131 38229721 45431261".split(),
}
CODES = tuple(dict.fromkeys(c for cohort in COHORTS.values() for c in cohort))
MAX_SUPPLIERS = 37
MAX_OUTPUT_BYTES = 2 * 1024 * 1024
MANUAL_CONTROLS = {"2077003493": ("2026-09-18", "Тетяна ФЕДЧЕНКО"),
    "2886810864": ("2026-09-16", "Дмитро САВВА"),
    "2981518432": ("2026-09-22", "Дмитро САВВА")}


def guard():
    if (os.getenv("RENDER_SERVICE_ID") != adapter.SANDBOX_ID
        or os.getenv("PQM_SANDBOX", "").lower() not in {"1", "true"}):
        raise ValueError("STOP: exact SANDBOX guard required")
    if adapter.read_enabled():
        raise ValueError("STOP: parity requires authoritative read flag OFF")


def selected_codes(codes):
    result = tuple(dict.fromkeys(codes))
    if not result or len(result) > MAX_SUPPLIERS or any(c not in CODES for c in result):
        raise ValueError("STOP: only frozen bounded cohorts allowed")
    return result


def _source_budget(con, code):
    """Preflight raw rows before either consumer can materialize their contents."""
    reports = {}
    for table in ("submissions", "registry_contracts", "supplier_edr_profiles", "supplier_edr_verification_events", "supplier_evidence_events_v3"):
        columns = adapter._columns(con, table)
        if not columns:
            reports[table] = "not_available"
            continue
        # Names come exclusively from SQLite schema, quoted rather than interpolated raw.
        size = "+".join('COALESCE(length(CAST("' + c.replace('"', '""') + '" AS BLOB)),0)' for c in columns)
        environment_filter = " AND environment='sandbox'" if table == "supplier_evidence_events_v3" else ""
        n, b = con.execute(f'SELECT COUNT(*),COALESCE(SUM({size}),0) FROM {table} WHERE supplier_code=?' + environment_filter, (code,)).fetchone()
        if n > adapter.MAX_SOURCE_ROWS or b > adapter.MAX_SOURCE_BYTES:
            raise ValueError("STOP: source budget " + table + "/" + code)
        reports[table] = {"rows": n, "bytes": b}
    # Include joined qualification/application metadata before legacy reader.
    for table, join in (("qualifications", "t.id=s.qualification_id"), ("application_fields", "t.submission_id=s.id")):
        columns = adapter._columns(con, table)
        size = "+".join('COALESCE(length(CAST(t."' + c.replace('"', '""') + '" AS BLOB)),0)' for c in columns)
        n, b = con.execute(f'SELECT COUNT(*),COALESCE(SUM({size}),0) FROM submissions s JOIN {table} t ON {join} WHERE s.supplier_code=?', (code,)).fetchone()
        if n > adapter.MAX_SOURCE_ROWS or b > adapter.MAX_SOURCE_BYTES:
            raise ValueError("STOP: joined source budget " + table + "/" + code)
        reports[table] = {"rows": n, "bytes": b}
    return reports


def legacy_read(con, code, day):
    """Actual targeted verification reader; stored profile is labelled NOT live UI.

    Do not call canonical_prozorro_statuses/active_qualification_dates: they read
    the population. prozorro_statuses([code]) is actually supplier-filtered.
    """
    profile = adapter._rows(con, "SELECT * FROM supplier_edr_profiles WHERE supplier_code=?", (code,))
    profile = profile[0] if profile else {}
    apps = adapter._rows(con, "SELECT id,date_published FROM submissions WHERE supplier_code=?", (code,))
    last, ambiguity = adapter.resolver._latest([{"effective_date": r["date_published"][:10],
        "source_event_at": adapter._stamp(r["date_published"]), "row": r} for r in apps
        if r["date_published"] and r["date_published"][:10] <= day])
    result = {"edr_status": profile.get("edr_status"), "stored_profile_status": profile.get("edr_status"),
        "prozorro_status": None, "monitoring_eligible": None, "freshness": None,
        "current_event": None, "last_verification_date": None, "last_verification_officer": None,
        "last_application_date": last["row"]["date_published"] if last else None,
        "projection_source": "stored_profile_only_NOT_authoritative_UI",
        "unavailable": ["legacy_current_lifecycle", "legacy_current_event", "legacy_freshness"],
        "last_application_ambiguity": ambiguity}
    status = legacy.prozorro_statuses(con, [code]).get(code)
    if status:
        result.update(prozorro_status=status, monitoring_eligible=status in {"Активний", "Призупинений"})
        result["lifecycle_source"] = "prozorro_statuses([literal_code]); legacy SQLite DATE(now) boundary"
        result["unavailable"].remove("legacy_current_lifecycle")
    qualification_columns = adapter._columns(con, "qualifications")
    if status and "decision_date" in qualification_columns:
        dated = adapter._rows(con, """SELECT q.decision_date FROM registry_contracts rc
            JOIN frameworks f ON f.id=rc.framework_id
            LEFT JOIN qualifications q ON q.id=rc.qualification_id
            WHERE rc.supplier_code=? AND """ + legacy.supplier_activity.effective_active_sql("rc", "f"), (code,))
        qualified = max((legacy.normalized_date(r["decision_date"]) for r in dated), default="")
        ledger = adapter._rows(con, "SELECT * FROM supplier_edr_verification_events WHERE supplier_code=?", (code,))
        result["edr_status"] = legacy.operational_edr_status(status, qualified, ledger, profile.get("edr_status", ""))
        result["projection_source"] = "targeted_operational_edr_status; NOT full UI serialization"
    required = {"edr_checked_at", "edr_officer", "synced_at"}
    if (required <= adapter._columns(con, "supplier_edr_profiles")
        and "protocol_decision" in adapter._columns(con, "application_fields")):
        legacy.register_verification_sql_functions(con)
        verification = legacy.current_verification_projections(con, [code])[code]
        selected = verification["selected_event"]
        result.update(last_verification_date=verification["verification_date"] or None,
            last_verification_officer=verification["verification_officer"] or None,
            verification_identity={k: selected.get(k) for k in ("id", "event_type", "source", "source_submission_id")},
            verification_source="current_verification_projections([literal_code])")
        if status:
            result["freshness"] = legacy.freshness_state(status, verification["verification_date"], datetime.fromisoformat(day).date())
            result["unavailable"].remove("legacy_freshness")
    else:
        result["unavailable"].append("legacy_verification_reader_schema_not_available")
    return result


def compact_projection(p):
    def identity(e):
        return {k: e.get(k) for k in ("event_id", "source_system", "source_event_id", "semantic_type",
            "event_kind", "effective_date", "source_event_at")} if e else None
    return {"edr_status": p["edr_status_current"], "prozorro_status": p["prozorro_status"],
        "monitoring_eligible": p["monitoring_eligible"], "freshness": p["freshness"],
        "current_event_type": p["current_event_type"], "current_event_date": p["current_event_date"],
        "current_event_actor": p["current_event_actor"], "current_event": identity(p["current_event"]),
        "last_verification_date": p["last_verification_date"], "last_verification_officer": p["last_verification_officer"],
        "last_verification": identity(p["last_verification_event"]),
        "last_application_date": (p["last_application"] or {}).get("date_published"),
        "visible_date": p["visible_date"], "visible_actor": p["visible_actor"],
        "factual_snapshot": p["factual_snapshot"], "gaps": p["gaps"],
        "provenance_gaps": p.get("provenance_gaps", []),
        "logical_verification_count": p["logical_verification_count"],
        "logical_verification_identities": [identity(e) for e in p["verification_history"]],
        "legacy_native_links": p["legacy_native_links"]}


def officer_identity(con, value):
    """Diagnostic-only, bounded lookup; never infer an officer from assignment."""
    if not str(value or "").strip():
        return {"status": "missing", "id": None}
    if con is None or not adapter._columns(con, "authorized_officers"):
        return {"status": "unavailable", "id": None}
    legacy.register_verification_sql_functions(con)
    rows = adapter._rows(con, """SELECT id FROM authorized_officers
        WHERE active=1 AND NORMALIZE_NAME(full_name)=NORMALIZE_NAME(?)""", (value,))
    return {"status": "unique" if len(rows) == 1 else "ambiguous" if rows else "missing",
        "id": rows[0]["id"] if len(rows) == 1 else None}


def compare(code, old, new, *, con=None):
    labels, differences = [], []
    compared = []
    presentation, identity_gaps = [], []
    for field in ("edr_status", "prozorro_status", "monitoring_eligible", "last_verification_date", "last_verification_officer", "last_application_date"):
        # Unknown is not equality or a mismatch; retain it explicitly in source coverage.
        known_absence = field.startswith("last_verification_") and bool(old.get("verification_source"))
        if old.get(field) is None and not known_absence:
            continue
        compared.append(field)
        value = "Припинений" if field == "prozorro_status" and old[field] == "Призупинений" else old[field]
        reconstructed = ((new.get("last_verification") or {}).get("event_kind") == "admission"
            and (old.get("verification_identity", {}).get("event_type") == "admission"
                or code in COHORTS["stale_active"] and old.get(field) is None))
        identity_check = (value != new.get(field) or
            bool(str(value or "").strip()) and con is not None and bool(adapter._columns(con, "authorized_officers")))
        if field == "last_verification_officer" and identity_check and not reconstructed:
            left, right = officer_identity(con, value), officer_identity(con, new.get(field))
            identity = {"legacy": left, "v3": right}
            if left["status"] == right["status"] == "unique" and left["id"] == right["id"]:
                if value != new.get(field):
                    presentation.append({"field": field, "legacy": value, "v3": new.get(field),
                        "canonical_officer_id": left["id"], "identity_match": True})
                continue
            if left["status"] != "unique" or right["status"] != "unique":
                identity_gaps.append({"field": field, "gap_type": "officer_identity_unproven", **identity})
                labels.append("MISSING_PROVENANCE")
            differences.append({"field": field, "legacy": value, "v3": new.get(field),
                "classification": "UNEXPECTED_MISMATCH", "canonical_identity": identity})
            labels.append("UNEXPECTED_MISMATCH")
            continue
        if value == new.get(field):
            continue
        expected = (field == "edr_status" and old[field] == "Неактуально"
            and new["prozorro_status"] == "Активний" and new[field] == "Зареєстровано")
        admission = (new.get("last_verification") or {}).get("event_kind") == "admission"
        correction = expected or (field.startswith("last_verification_") and admission
            and (old.get("verification_identity", {}).get("event_type") == "admission"
                or code in COHORTS["stale_active"] and old.get(field) is None))
        category = "EXPECTED_V3_CORRECTION" if correction else "UNEXPECTED_MISMATCH"
        differences.append({"field": field, "legacy": old[field], "v3": new.get(field), "classification": category})
        labels.append(category)
        if expected:
            labels.append("LEGACY_STALE")
    if (old.get("stored_profile_status") == "Неактуально" and new["prozorro_status"] == "Активний"
        and new["edr_status"] == "Зареєстровано"):
        labels.append("LEGACY_STALE")  # Stored profile gap, even when legacy operational status corrects it.
    if old.get("freshness") is not None:
        compared.append("freshness")
        old_fresh = {k: old["freshness"][k] for k in ("bucket", "age_days")}
        new_fresh = {k: new["freshness"][k] for k in ("bucket", "age_days")}
        if old_fresh != new_fresh:
            correction = any(d["field"] == "last_verification_date" and d["classification"] == "EXPECTED_V3_CORRECTION" for d in differences)
            category = "EXPECTED_V3_CORRECTION" if correction else "UNEXPECTED_MISMATCH"
            differences.append({"field": "freshness", "legacy": old_fresh, "v3": new_fresh, "classification": category})
            labels.append(category)
    # Scope is evidence, not a guess from the gap's name. An explicitly archived
    # history-only gap cannot invalidate independent current/verification fields.
    scopes = {}
    for gap in new.get("provenance_gaps", []):
        scopes.setdefault(gap["gap_type"], set()).add(gap.get("review_scope"))
    history_only = [g for g in new["gaps"] if scopes.get(g) == {"history_only"}]
    unresolved = [g for g in new["gaps"] if g not in history_only]
    if new["gaps"]:
        labels.append("MISSING_PROVENANCE")
    frozen = []
    if code in COHORTS["google_pending"]:
        labels.append("GOOGLE_ONLY_NOT_IMPORTED")
        frozen.append({"source": "accepted_frozen_external_audit", "verification_date": "2026-10-05",
            "classification": "GOOGLE_ONLY_NOT_IMPORTED", "imported_by_runner": False,
            "superseded_by_current_verification": bool(new["last_verification_date"] and new["last_verification_date"] > "2026-10-05")})
    if code in COHORTS["multi_inclusion"]:
        frozen.append({"source": "accepted_stage_2a_historical_audit", "gap": "termination_date_unproven",
            "scope": "history_only", "not_materialized": True})
    if code == "33345054":
        frozen.append({"source": "approved_policy_NOT_materialized_event", "expected_lifecycle_date": "2026-10-05",
            "actor_policy": "decision officer, canonical SANDBOX fallback only if absent"})
    current_known = new["current_event"] is not None or new["prozorro_status"] == "Ще не в реєстрі"
    if not current_known:
        labels.append("MISSING_PROVENANCE")
    if not differences and compared and not unresolved and not identity_gaps and current_known:
        labels.append("TRUE_PARITY")  # Known overlapping fields ONLY, never a UI parity claim.
    return {"classifications": sorted(set(labels)), "differences": differences,
        "officer_presentation_differences": presentation, "officer_identity_gaps": identity_gaps,
        "comparison_scope": "known_overlap_only_NOT_UI_cutover_acceptance", "compared_fields": compared,
        "known_equal_fields": [f for f in compared if not any(d["field"] == f for d in differences)],
        "unresolved_evidence_gaps": unresolved, "history_only_gaps": history_only,
        "current_event_evidence_known": current_known,
        "frozen_audit_context": frozen}


def contract_checks(code, p):
    """No cohort whitelist hides a wrong result; gaps mean unresolved, not PASS."""
    checks = {}
    if code in COHORTS["stale_active"]:
        checks.update(active=p["prozorro_status"] == "Активний",
            registered=p["edr_status"] == "Зареєстровано",
            admission_evidence_present=bool(p["last_verification"]))
    if code in COHORTS["never_admitted"]:
        checks.update(never_admitted=p["prozorro_status"] == "Ще не в реєстрі",
            not_current=p["edr_status"] == "Неактуально", visible_i_blank=p["visible_date"] is None,
            no_verification=p["logical_verification_count"] == 0,
            last_application_present=bool(p["last_application_date"]), decision_actor_present=bool(p["visible_actor"]))
    if code in COHORTS["multi_inclusion"]:
        checks["partial_termination_still_active"] = p["prozorro_status"] == "Активний"
    if code == "44368854":
        checks.update(suspended=p["prozorro_status"] == "Припинений", monitoring=p["monitoring_eligible"],
            last_verification=p["last_verification_date"] == "2026-09-11" and p["last_verification_officer"] == "Світлана НАМЯСЕНКО",
            no_fabricated_date=bool(p["current_event_date"] is None or "suspension_date_unproven" not in p["gaps"]))
    if code == "33345054":
        checks.update(inactive=p["prozorro_status"] == "Неактивний", not_current=p["edr_status"] == "Неактуально",
            history_preserved=p["last_verification_date"] == "2026-09-17" and p["last_verification_officer"] == "Світлана НАМЯСЕНКО",
            lifecycle_date=p["current_event_date"] == "2026-10-05")
    if code == "45054758":
        mirror = [e for e in p["logical_verification_identities"] if e["source_system"] == "legacy_edr_ledger" and e["source_event_id"] == '["edr_check","8699"]']
        checks.update(one_8699_logical_verification=len(mirror) == 1,
            native_mirror_link_present=any(8699 in ids for ids in p["legacy_native_links"].values()),
            verification_date=p["last_verification_date"] == "2026-10-06",
            officer=p["last_verification_officer"] == "Світлана НАМЯСЕНКО",
            factual=p["edr_status"] == "Припинено", literal_dash=p["factual_snapshot"].get("short_name") == "—",
            freshness=p["freshness"]["bucket"] == "lt30", current_last_same=p["current_event"] == p["last_verification"])
    return checks


def run(con, codes, *, as_of_at):
    guard()
    if con.execute("PRAGMA query_only").fetchone()[0] != 1:
        raise ValueError("STOP: query_only connection required")
    codes = selected_codes(codes)
    assessment = datetime.fromisoformat(as_of_at)
    if assessment.tzinfo is None:
        raise ValueError("STOP: zoned assessment timestamp required")
    day = assessment.astimezone(ZoneInfo("Europe/Kyiv")).date().isoformat()
    before = con.total_changes
    rows = []
    start = time.perf_counter()
    for code in codes:
        t = time.perf_counter()
        budgets = _source_budget(con, code)
        t1 = time.perf_counter()
        old = legacy_read(con, code, day)
        t2 = time.perf_counter()
        new = compact_projection(adapter.project_supplier(con, code, as_of_at=as_of_at))
        t3 = time.perf_counter()
        row = {"supplier_code": code, "cohorts": [n for n, cs in COHORTS.items() if code in cs],
            "legacy": old, "v3": new, **compare(code, old, new, con=con), "source_budgets": budgets,
            "timing_ms": {"budget": (t1-t)*1000, "legacy": (t2-t1)*1000, "v3": (t3-t2)*1000, "total": (t3-t)*1000}}
        row["contract_checks"] = contract_checks(code, new)
        failed = [k for k, value in row["contract_checks"].items() if not value]
        # Missing lifecycle evidence does not prove a wrong date; still unresolved.
        unresolved = [k for k in failed if code == "33345054" and k == "lifecycle_date"
            and new["current_event_date"] is None and "missing_lifecycle_evidence" in new["gaps"]]
        row["unresolved_contract_checks"] = unresolved
        row["failed_contract_checks"] = [k for k in failed if k not in unresolved]
        if row["failed_contract_checks"]:
            row["classifications"] = sorted(set(row["classifications"] + ["UNEXPECTED_MISMATCH"]))
        if code in MANUAL_CONTROLS:
            row["manual_control_pass"] = (new["last_verification_date"], new["last_verification_officer"]) == MANUAL_CONTROLS[code]
            if not row["manual_control_pass"]:
                row["classifications"] = sorted(set(row["classifications"] + ["UNEXPECTED_MISMATCH"]))
        rows.append(row)
        if len(json.dumps(rows, ensure_ascii=False).encode()) > MAX_OUTPUT_BYTES:
            raise ValueError("STOP: compact output budget exceeded")
    if con.total_changes != before:
        raise ValueError("STOP: DB writes detected")
    return {"rows": rows, "unique_suppliers": len(rows), "classification_counts": dict(Counter(c for r in rows for c in r["classifications"])),
        "timing_ms": {"one_supplier": rows[0]["timing_ms"]["total"],
            "one_supplier_code": rows[0]["supplier_code"],
            "stale_controls": sum(r["timing_ms"]["total"] for r in rows if r["supplier_code"] in COHORTS["stale_active"]),
            "stale_controls_measured": sum(r["supplier_code"] in COHORTS["stale_active"] for r in rows),
            "bounded_cohort": (time.perf_counter()-start)*1000, "method": "one pass; sums, no repeated benchmark reads"},
        "DB_WRITES": 0, "RUNTIME_WIRING": "NO", "STAGE_2B": "NO", "SYNC_APPLY_BACKFILL": "NO",
        "natural_lifecycle_acceptance": "LIVE_PENDING", "as_of_at": as_of_at,
        "limitations": ["Legacy sources labelled per field; missing schema fields unavailable, not parity claims",
            "Legacy lifecycle uses current SQLite clock, v3 explicit assessment; historical as-of is not clock-replayed legacy parity",
            "Frozen Google and historical annotations do not supply projection evidence", "Real live cohort results require separately approved diagnostic deployment/run"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True)
    parser.add_argument("--as-of-at", required=True)
    parser.add_argument("--codes", nargs="+", default=CODES)
    args = parser.parse_args()
    guard()
    selected_codes(args.codes)
    with closing(sqlite3.connect("file:" + quote(str(Path(args.db).resolve()), safe="/:") + "?mode=ro", uri=True)) as con:
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA query_only=ON")
        con.execute("PRAGMA cache_size=-8192")
        con.execute("BEGIN")
        reads = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_RECURSIVE}
        con.set_authorizer(lambda action, a, b, *rest: sqlite3.SQLITE_OK if action in reads or
            (action == sqlite3.SQLITE_PRAGMA and (a == "table_info" or a == "query_only" and b is None)) else sqlite3.SQLITE_DENY)
        result = run(con, args.codes, as_of_at=args.as_of_at)
        con.set_authorizer(None)
        con.rollback()  # Release SELECT snapshot; no migration/commit.
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, sqlite3.Error, MemoryError, KeyError, adapter.SourceBudgetExceeded) as exc:
        print(json.dumps({"result": "STOP", "error": str(exc), "DB_WRITES": 0, "retry": False}, ensure_ascii=False))
        sys.exit(1)
