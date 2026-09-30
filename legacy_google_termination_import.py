"""Bounded SANDBOX Google-owned termination/notes Preview and Apply."""
from collections import Counter
import hashlib
import json
import time

import legacy_google_termination_audit as audit
import legacy_google_verification_preview as binding


PREVIEW_PATH = "/api/integrations/google/termination-notes/preview"
APPLY_PATH = "/api/integrations/google/termination-notes/apply"
MAX_BATCH = 500
CONFIRMATION = "APPLY_SANDBOX_TERMINATION_NOTES_BATCH_MAX_500"
FIELDS = audit.FIELDS
ITEM_KEYS = audit.ITEM_KEYS
REQUEST_KEYS = frozenset({"spreadsheet_id", "source_digest", "records"})


def source_digest(records):
    return audit.digest(records)


def validate(payload):
    if not isinstance(payload, dict) or set(payload) != REQUEST_KEYS:
        raise ValueError("IMPORT_SCHEMA_INVALID")
    if payload["spreadsheet_id"] != audit.SANDBOX_SPREADSHEET_ID:
        raise ValueError("SANDBOX_SPREADSHEET_MISMATCH")
    records = payload["records"]
    if not isinstance(records, list) or not 1 <= len(records) <= MAX_BATCH:
        raise ValueError("IMPORT_BATCH_LIMIT")
    if any(not isinstance(row, dict) or set(row) != ITEM_KEYS for row in records):
        raise ValueError("IMPORT_ITEM_SCHEMA_INVALID")
    for row in records:
        if (not isinstance(row["supplier_code"], str) or not row["supplier_code"] or
            row["supplier_code"] != row["supplier_code"].strip() or
            row["source_tab"] not in {"ФОП", "ЮО"} or
            type(row["source_row"]) is not int or row["source_row"] < 2 or
            any(not isinstance(row[col], str) for col in FIELDS) or
            not isinstance(row["formulas"], list) or
            any(col not in FIELDS for col in row["formulas"])):
            raise ValueError("IMPORT_ITEM_INVALID")
    if records != sorted(records, key=lambda r: (r["source_tab"], r["source_row"], r["supplier_code"])):
        raise ValueError("IMPORT_ORDER_INVALID")
    if (len({r["supplier_code"] for r in records}) != len(records) or
        len({(r["source_tab"], r["source_row"]) for r in records}) != len(records)):
        raise ValueError("IMPORT_DUPLICATE_IDENTITY")
    if payload["source_digest"] != source_digest(records):
        raise ValueError("IMPORT_SOURCE_DIGEST_MISMATCH")
    return records


def _profiles(con, records):
    codes = [row["supplier_code"] for row in records]
    marks = ",".join("?" for _ in codes)
    found = {code: [] for code in codes}
    for row in con.execute("SELECT * FROM supplier_edr_profiles WHERE supplier_code IN (" + marks + ")", codes):
        found[row["supplier_code"]].append(dict(row))
    return found


def _normalize(col, value):
    value = str(value or "").strip()
    if col == "j" and value:
        value = audit._date(value)
        if value == "!invalid":
            raise ValueError("IMPORT_INVALID_DATE")
    return value


def _plan(con, payload, *, require_query_only):
    records = validate(payload)
    if require_query_only and con.execute("PRAGMA query_only").fetchone()[0] != 1:
        raise ValueError("QUERY_ONLY_REQUIRED")
    profiles = _profiles(con, records)
    counts, columns = Counter(), Counter()
    rows, changes = [], []
    for item in records:
        candidates = profiles[item["supplier_code"]]
        if len(candidates) != 1:
            reason = "ambiguous" if candidates else "blocked_missing_profile"
            updates = {}
        elif candidates[0].get("source_sheet") in {"ФОП", "ЮО"} and candidates[0]["source_sheet"] != item["source_tab"]:
            reason, updates = "ambiguous_routing", {}
        elif item["formulas"]:
            reason, updates = "blocked_formula", {}
        else:
            updates = {}
            for col, field in FIELDS.items():
                google = _normalize(col, item[col])
                pqm = _normalize(col, candidates[0].get(field))
                if google and google != pqm:
                    updates[field] = google
                    columns[col] += 1
            reason = "selected" if updates else "equivalent"
        counts[reason] += 1
        if reason == "selected":
            group = [item[col].strip() for col in ("g", "j", "k")]
            counts["complete_termination_blocks" if all(group) else
                   "partial_termination_blocks" if any(group) else "notes_only"] += 1
            if item["m"].strip():
                counts["notes"] += 1
            changes.append((item["supplier_code"], updates))
        rows.append({"source_tab": item["source_tab"], "source_row": item["source_row"],
                     "result": reason})
    state = binding._digest(profiles)
    selection = binding._digest({"spreadsheet_id": payload["spreadsheet_id"],
                                 "source_digest": payload["source_digest"],
                                 "state_digest": state, "rows": rows})
    return records, profiles, changes, counts, columns, rows, state, selection


def preview(con, payload):
    records, _, changes, counts, columns, rows, state, selection = _plan(
        con, payload, require_query_only=True)
    ticket = binding._preview_ticket("termination-notes:" + selection,
                                     int(time.time()) + binding._PREVIEW_TICKET_SECONDS)
    return {"dry_run": True, "received": len(records), "selected": len(changes),
            "field_writes": {col: columns[col] for col in FIELDS},
            "complete_termination_blocks": counts["complete_termination_blocks"],
            "partial_termination_blocks": counts["partial_termination_blocks"],
            "notes": counts["notes"], "blocked": sum(v for k, v in counts.items() if k.startswith("blocked")),
            "ambiguous": sum(v for k, v in counts.items() if k.startswith("ambiguous")),
            "equivalent": counts["equivalent"], "rows": rows,
            "source_digest": payload["source_digest"], "current_pqm_state_digest": state,
            "selection_digest": selection, "preview_ticket": ticket,
            "ticket_ttl_seconds": binding._PREVIEW_TICKET_SECONDS,
            "batch_apply_ready": len(changes) == len(records), "query_only": 1,
            "db_writes": 0, "google_writes": 0}


def _protected(con, codes):
    """Fingerprint all non-target profile columns and related protected tables."""
    marks = ",".join("?" for _ in codes)
    profile_columns = [r[1] for r in con.execute("PRAGMA table_info(supplier_edr_profiles)")
                       if r[1] not in FIELDS.values()]
    result = {"profiles": [tuple(r) for r in con.execute(
        "SELECT " + ",".join(profile_columns) + " FROM supplier_edr_profiles WHERE supplier_code IN (" + marks + ") ORDER BY supplier_code", codes)]}
    for table in ("supplier_edr_verification_events", "supplier_notes", "supplier_managers",
                  "qualifications", "submissions", "supplier_registry_summary"):
        if not con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
            continue
        columns = {r[1] for r in con.execute("PRAGMA table_info(" + table + ")")}
        if "supplier_code" in columns:
            result[table] = sorted((tuple(r) for r in con.execute(
                "SELECT * FROM " + table + " WHERE supplier_code IN (" + marks + ")", codes)), key=repr)
    if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='application_fields'").fetchone():
        columns = {r[1] for r in con.execute("PRAGMA table_info(application_fields)")}
        if "submission_id" in columns:
            result["application_fields"] = sorted((tuple(r) for r in con.execute(
                "SELECT af.* FROM application_fields af JOIN submissions s ON s.id=af.submission_id "
                "WHERE s.supplier_code IN (" + marks + ")", codes)), key=repr)
    return binding._digest(result)


def apply(con, payload, *, after_write_hook=None):
    if not isinstance(payload, dict) or set(payload) != REQUEST_KEYS | {
            "selection_digest", "preview_ticket", "confirmation"}:
        raise ValueError("IMPORT_APPLY_SCHEMA_INVALID")
    if payload["confirmation"] != CONFIRMATION:
        raise ValueError("EXPLICIT_CONFIRMATION_REQUIRED")
    source = {key: payload[key] for key in REQUEST_KEYS}
    records = validate(source)  # 501 rejected before BEGIN or writes
    if con.execute("PRAGMA query_only").fetchone()[0]:
        raise ValueError("READ_ONLY_CONNECTION_CANNOT_APPLY")
    if not binding._ticket_valid(payload["preview_ticket"],
                                 "termination-notes:" + str(payload["selection_digest"])):
        raise ValueError("PREVIEW_TICKET_INVALID_OR_EXPIRED")
    con.execute("BEGIN IMMEDIATE")
    try:
        _, _, changes, counts, _, _, _, selection = _plan(con, source, require_query_only=False)
        if selection != payload["selection_digest"]:
            if counts["equivalent"] == len(records):
                con.rollback()
                return {"selected": len(records), "updated": 0, "verified": 0,
                        "db_writes": 0, "google_writes": 0,
                        "transaction_status": "ALREADY_APPLIED"}
            raise ValueError("STALE_PREVIEW_OR_PQM_STATE")
        if len(changes) != len(records):
            raise ValueError("SELECTION_NOT_FULLY_ELIGIBLE")
        codes = [r["supplier_code"] for r in records]
        protected_before = _protected(con, codes)
        writes_before = con.total_changes
        for code, updates in changes:
            fields = list(updates)
            cursor = con.execute("UPDATE supplier_edr_profiles SET " +
                                 ",".join(field + "=?" for field in fields) +
                                 " WHERE supplier_code=?", [updates[field] for field in fields] + [code])
            if cursor.rowcount != 1:
                raise ValueError("PROFILE_WRITE_FAILED")
        if after_write_hook:
            after_write_hook(con)
        current = _profiles(con, records)
        for code, updates in changes:
            if len(current[code]) != 1 or any(
                    _normalize(next(col for col, name in FIELDS.items() if name == field),
                               current[code][0][field]) != value for field, value in updates.items()):
                raise ValueError("AFTER_READBACK_FAILED")
        if _protected(con, codes) != protected_before:
            raise ValueError("PROTECTED_DATA_CHANGED")
        if con.total_changes - writes_before != len(changes):
            raise ValueError("UNEXPECTED_DB_MUTATION")
        con.commit()
        return {"selected": len(records), "updated": len(changes), "verified": len(changes),
                "db_writes": len(changes), "google_writes": 0, "transaction_status": "COMMITTED"}
    except Exception:
        con.rollback()
        raise
