"""SANDBOX-only Google verification Preview and bounded transactional Apply.

The backend never reads or writes Google; only the explicit Apply path inserts
verification events after a signed, fresh Preview and state recheck.
"""
from collections import Counter
from datetime import date, datetime, timezone
import hashlib
import hmac
import json
import re
import secrets
import sqlite3
import time
import urllib.parse

import edr_sync_v2
import supplier_registry_integration


SANDBOX_SPREADSHEET_ID = "1lZtneKmCTvFcEL0erlJbegVzTTLNA-IKnjempn1G8Ww"
SOURCE = "legacy_google_registry"
SOURCES = frozenset({SOURCE, "google_registry"})
PATH = "/api/integrations/google/verification-events/preview"
APPLY_PATH = "/api/integrations/google/verification-events/apply"
APPLY_CONFIRMATION = "APPLY_LEGACY_GOOGLE_VERIFICATION_MAX_10"
ITEM_KEYS = frozenset({"supplier_code", "verification_date", "verification_officer",
                       "source_tab", "source_row", "source"})
REQUEST_KEYS = frozenset({"spreadsheet_id", "source_digest", "records"})
INVALID_OFFICER = {"-", "—", "не визначено", "не призначено", "невідомо", "n/a", "null"}
_PREVIEW_TICKET_KEY = secrets.token_bytes(32)  # process-local: restart invalidates old Preview
_PREVIEW_TICKET_SECONDS = 900


def source_digest(items):
    rows = [[x["supplier_code"], x["source_tab"], x["source_row"],
             x["verification_date"], x["verification_officer"], x["source"]]
            for x in items]
    raw = json.dumps(rows, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":"), default=str).encode("utf-8")).hexdigest()


def _preview_ticket(selection_digest, expires_at):
    message = (selection_digest + ":" + str(expires_at)).encode("ascii")
    return str(expires_at) + "." + hmac.new(_PREVIEW_TICKET_KEY, message, hashlib.sha256).hexdigest()


def _ticket_valid(ticket, selection_digest):
    if not isinstance(ticket, str) or not re.fullmatch(r"\d{10,12}\.[a-f0-9]{64}", ticket):
        return False
    expires_at = int(ticket.split(".", 1)[0])
    return time.time() <= expires_at <= time.time() + _PREVIEW_TICKET_SECONDS and hmac.compare_digest(
        ticket, _preview_ticket(selection_digest, expires_at))


def _iso_date(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return None
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        return None


def _officer(value):
    text = " ".join(str(value or "").split())
    return text if text and text.casefold() not in INVALID_OFFICER else ""


def validate_request(payload):
    if not isinstance(payload, dict) or set(payload) != REQUEST_KEYS:
        raise ValueError("REQUEST_SCHEMA_INVALID")
    if payload["spreadsheet_id"] != SANDBOX_SPREADSHEET_ID:
        raise ValueError("SANDBOX_SPREADSHEET_MISMATCH")
    items = payload["records"]
    if not isinstance(items, list) or not 1 <= len(items) <= 10:
        raise ValueError("CONTROLLED_PREVIEW_LIMIT")
    if any(not isinstance(x, dict) or set(x) != ITEM_KEYS for x in items):
        raise ValueError("ITEM_SCHEMA_INVALID")
    if any(not isinstance(x["supplier_code"], str) or not x["supplier_code"] or
           x["supplier_code"] != x["supplier_code"].strip() or
           not isinstance(x["verification_date"], str) or
           not isinstance(x["verification_officer"], str) or
           not isinstance(x["source_tab"], str) or
           not isinstance(x["source"], str) or
           x["source_tab"] not in {"ФОП", "ЮО"} or
           not isinstance(x["source_row"], int) or isinstance(x["source_row"], bool) or
           x["source_row"] < 2 or x["source"] not in SOURCES for x in items):
        raise ValueError("ITEM_IDENTITY_OR_SOURCE_INVALID")
    if items != sorted(items, key=lambda x: (x["source_tab"], x["source_row"], x["supplier_code"])):
        raise ValueError("ITEM_ORDER_INVALID")
    if (not isinstance(payload["source_digest"], str) or
        payload["source_digest"] != source_digest(items)):
        raise ValueError("SOURCE_DIGEST_MISMATCH")
    return items


def open_read_only(db_path):
    con = sqlite3.connect("file:" + urllib.parse.quote(str(db_path), safe="/") + "?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA query_only=ON")
    con.create_function("DIGITS", 1, lambda v: re.sub(r"\D", "", str(v or "")), deterministic=True)
    con.create_function("NORMALIZE_NAME", 1, lambda v: " ".join(re.sub(
        r"[’'`\-]+", " ", str(v or "").casefold()).split()), deterministic=True)
    return con


def preview(con, payload):
    items = validate_request(payload)
    registry = supplier_registry_integration._build_full_registry(con)
    identity = {}
    for row in registry["items"]:
        identity.setdefault(str(row["supplier_code"]).strip(), []).append(row)
    codes = [x["supplier_code"] for x in items]
    projection = edr_sync_v2.current_verification_projections(con, codes)
    events = {code: [] for code in codes}
    placeholders = ",".join("?" for _ in codes)
    for row in con.execute("SELECT * FROM "
                           "supplier_edr_verification_events WHERE supplier_code IN (" +
                           placeholders + ")", codes):
        events[row["supplier_code"]].append(row)
    duplicate_codes = {code for code, count in Counter(codes).items() if count > 1}
    duplicate_rows = {key for key, count in Counter(
        (x["source_tab"], x["source_row"]) for x in items).items() if count > 1}
    counts = Counter()
    results = []
    for item in items:
        code = item["supplier_code"]
        matched = identity.get(code, [])
        incoming_day = _iso_date(item["verification_date"])
        officer = _officer(item["verification_officer"])
        if code in duplicate_codes or (item["source_tab"], item["source_row"]) in duplicate_rows or len(matched) != 1:
            category = "ambiguous_identity"
        elif {"individual_entrepreneur": "ФОП", "legal_entity": "ЮО"}.get(
                matched[0]["entity_type"]) != item["source_tab"]:
            category = "routing_or_unsupported_identity"
        elif not incoming_day:
            category = "invalid_date"
        elif not officer:
            category = "missing_officer"
        else:
            current = projection.get(code, {})
            current_raw = current.get("verification_date") or ""
            current_day = edr_sync_v2.normalized_date(current_raw)
            if current_raw and not current_day:
                category = "invalid_pqm_date"
            elif any(edr_sync_v2.normalized_date(e["occurred_at"]) == incoming_day and
                     edr_sync_v2.normalize_person(e["officer"]) ==
                     edr_sync_v2.normalize_person(officer) for e in events[code]):
                category = "equivalent_event"
            elif not current_day:
                category = "initial"
            elif incoming_day > current_day:
                category = "incoming_newer"
            elif incoming_day == current_day:
                category = "same_date"
            else:
                category = "older"
        counts[category] += 1
        results.append({"source_tab": item["source_tab"], "source_row": item["source_row"],
                        "result": category})
    # Include the entire relevant ledger and selected projection in the state binding.
    # No identity or officer is exposed in the response; only SHA-256 digests.
    state_digest = _digest({"identity": {code: sorted(identity.get(code, []),
                                                        key=lambda row: _digest(row)) for code in codes},
                            "projection": projection,
                            "events": {code: sorted((dict(row) for row in events[code]),
                                                    key=lambda row: _digest(row)) for code in codes}})
    selection_digest = _digest({"spreadsheet_id": payload["spreadsheet_id"],
                                "source_digest": payload["source_digest"],
                                "state_digest": state_digest, "rows": results})
    ticket = _preview_ticket(selection_digest, int(time.time()) + _PREVIEW_TICKET_SECONDS)
    return {"dry_run": True, "received": len(items), "source_digest": payload["source_digest"],
            "current_pqm_state_digest": state_digest, "selection_digest": selection_digest,
            "preview_ticket": ticket,
            "incoming_newer": counts["incoming_newer"], "initial": counts["initial"],
            "same_date": counts["same_date"], "older": counts["older"],
            "equivalent_event": counts["equivalent_event"],
            "ambiguous": counts["ambiguous_identity"],
            "blocked": sum(counts.values()) - counts["incoming_newer"] - counts["initial"] -
                       counts["same_date"] - counts["older"] - counts["equivalent_event"],
            "by_reason": dict(counts), "rows": results, "google_writes": 0, "db_writes": 0}


def _protected_state(con, codes):
    """Read-only baseline for tables outside the one permitted event ledger."""
    protected = {}
    for table in ("supplier_edr_profiles", "supplier_registry_summary", "supplier_managers", "qualifications",
                  "submissions", "application_fields"):
        exists = con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                             (table,)).fetchone()
        if not exists:
            continue
        cols = {row[1] for row in con.execute("PRAGMA table_info(" + table + ")")}
        if "supplier_code" in cols:
            rows = con.execute("SELECT * FROM " + table + " WHERE supplier_code IN (" +
                               ",".join("?" for _ in codes) + ")", codes)
        elif table == "application_fields" and "submission_id" in cols:
            rows = con.execute("SELECT af.* FROM application_fields af JOIN submissions s "
                               "ON s.id=af.submission_id WHERE s.supplier_code IN (" +
                               ",".join("?" for _ in codes) + ")", codes)
        else:
            continue
        protected[table] = _digest(sorted((tuple(row) for row in rows), key=repr))
    return protected


def apply(con, payload, *, after_insert_hook=None):
    """Atomic max-10 insert; caller must enforce SANDBOX and Bearer auth."""
    if not isinstance(payload, dict) or set(payload) != {"spreadsheet_id", "source_digest",
                                                    "records", "selection_digest", "preview_ticket",
                                                    "confirmation"}:
        raise ValueError("APPLY_SCHEMA_INVALID")
    if payload["confirmation"] != APPLY_CONFIRMATION:
        raise ValueError("EXPLICIT_CONFIRMATION_REQUIRED")
    source = {key: payload[key] for key in REQUEST_KEYS}
    items = validate_request(source)
    if any(item["source"] != SOURCE for item in items):
        raise ValueError("APPLY_SOURCE_INVALID")
    if con.execute("PRAGMA query_only").fetchone()[0]:
        raise ValueError("READ_ONLY_CONNECTION_CANNOT_APPLY")
    con.execute("BEGIN IMMEDIATE")
    try:
        current = preview(con, source)
        if not _ticket_valid(payload["preview_ticket"], payload["selection_digest"]):
            raise ValueError("PREVIEW_TICKET_INVALID_OR_EXPIRED")
        if current["selection_digest"] != payload["selection_digest"]:
            # Exact replay is safe and idempotent; any mixed/stale batch fails closed.
            if current["equivalent_event"] == len(items) and all(
                con.execute("""SELECT 1 FROM supplier_edr_verification_events
                  WHERE supplier_code=? AND event_type=? AND occurred_at=? AND source=?
                  AND snapshot_hash=? AND source_sheet=? AND source_row=?""",
                  (item["supplier_code"], SOURCE, item["verification_date"], SOURCE,
                   _digest({"identity": item["supplier_code"], "date": item["verification_date"],
                            "officer": edr_sync_v2.normalize_person(item["verification_officer"]),
                            "source": SOURCE}), item["source_tab"], item["source_row"])).fetchone()
                for item in items):
                con.rollback()
                return {"selected": len(items), "eligible_before_write": 0, "inserted": 0,
                        "verified": 0, "duplicates_prevented": len(items), "blocked": 0,
                        "failures": 0, "db_writes": 0, "transaction_status": "ALREADY_APPLIED"}
            raise ValueError("STALE_PREVIEW_OR_PQM_STATE")
        eligible = current["incoming_newer"] + current["initial"]
        if eligible != len(items):
            raise ValueError("SELECTION_NOT_FULLY_ELIGIBLE")
        codes = sorted({item["supplier_code"] for item in items})
        protected_before = _protected_state(con, codes)
        changes_before = con.total_changes
        inserted = []
        for item in items:
            day = _iso_date(item["verification_date"])
            officer = _officer(item["verification_officer"])
            normalized = edr_sync_v2.normalize_person(officer)
            key = _digest({"identity": item["supplier_code"], "date": day,
                           "officer": normalized, "source": SOURCE})
            snapshot = {"verification_date": day, "verification_officer": officer,
                        "source": SOURCE, "spreadsheet_id": source["spreadsheet_id"],
                        "source_digest": source["source_digest"],
                        "source_tab": item["source_tab"], "source_row": item["source_row"]}
            cursor = con.execute("""INSERT INTO supplier_edr_verification_events
              (supplier_code,event_type,occurred_at,officer,source,source_submission_id,
               source_sheet,source_row,changed_fields,snapshot_hash,snapshot_json,created_at)
              VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
              (item["supplier_code"], SOURCE, day, officer, SOURCE, "", item["source_tab"],
               item["source_row"], '["verification_date","verification_officer"]', key,
               json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
               datetime.now(timezone.utc).isoformat()))
            if cursor.rowcount != 1:
                raise ValueError("INSERT_FAILED")
            inserted.append((item, key, normalized))
        if after_insert_hook:
            after_insert_hook(con)
        for item, key, normalized in inserted:
            row = con.execute("""SELECT * FROM supplier_edr_verification_events
              WHERE supplier_code=? AND event_type=? AND snapshot_hash=?""",
              (item["supplier_code"], SOURCE, key)).fetchone()
            if not row or row["occurred_at"] != item["verification_date"] or \
                    edr_sync_v2.normalize_person(row["officer"]) != normalized or \
                    row["source"] != SOURCE or row["source_sheet"] != item["source_tab"] or \
                    row["source_row"] != item["source_row"]:
                raise ValueError("AFTER_VERIFICATION_FAILED")
            snapshot = json.loads(row["snapshot_json"])
            if snapshot["spreadsheet_id"] != source["spreadsheet_id"] or \
                    snapshot["source_digest"] != source["source_digest"]:
                raise ValueError("AFTER_PROVENANCE_FAILED")
        if protected_before != _protected_state(con, codes):
            raise ValueError("PROTECTED_STATE_CHANGED")
        if con.total_changes - changes_before != len(inserted):
            raise ValueError("UNEXPECTED_DB_MUTATION")
        con.commit()
        return {"selected": len(items), "eligible_before_write": len(items),
                "inserted": len(items), "verified": len(items), "duplicates_prevented": 0,
                "blocked": 0, "failures": 0, "db_writes": len(items),
                "transaction_status": "COMMITTED"}
    except Exception:
        con.rollback()
        raise
