"""SANDBOX-only bounded Preview and transactional factual Google E restoration."""
from collections import Counter
from datetime import date
from datetime import datetime, timezone
import hashlib
import json
import re
import time

import edr_sync_v2
import legacy_google_factual_edr_audit
import legacy_google_verification_preview as verification
import supplier_registry_integration


PATH = "/api/integrations/google/factual-edr/preview"
APPLY_PATH = "/api/integrations/google/factual-edr/apply"
MAX_BATCH = 50
APPLY_CONFIRMATION = "APPLY_SANDBOX_FACTUAL_EDR_BATCH_MAX_50"
SOURCE = "legacy_google_registry"
ITEM_KEYS = frozenset({"supplier_code", "source_tab", "source_row", "verification_date",
                       "verification_officer", "factual_edr_status", "source", "formulas"})
REQUEST_KEYS = frozenset({"spreadsheet_id", "source_digest", "records"})
FACTUAL_STATUSES = edr_sync_v2.LEGACY_GOOGLE_FACTUAL_STATUSES


def source_digest(records):
    keys = ("supplier_code", "source_tab", "source_row", "verification_date",
            "verification_officer", "factual_edr_status", "source", "formulas")
    raw = json.dumps([[item[key] for key in keys] for item in records],
                     ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _digest(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _day(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return ""
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        return ""


def _officer(value):
    return verification._officer(value) if isinstance(value, str) else ""


def validate(payload):
    if not isinstance(payload, dict) or set(payload) != REQUEST_KEYS:
        raise ValueError("FACTUAL_PREVIEW_SCHEMA_INVALID")
    if payload["spreadsheet_id"] != verification.SANDBOX_SPREADSHEET_ID:
        raise ValueError("SANDBOX_SPREADSHEET_MISMATCH")
    items = payload["records"]
    if not isinstance(items, list) or not 1 <= len(items) <= MAX_BATCH:
        raise ValueError("FACTUAL_PREVIEW_LIMIT")
    if any(not isinstance(item, dict) or set(item) != ITEM_KEYS for item in items):
        raise ValueError("FACTUAL_PREVIEW_ITEM_SCHEMA_INVALID")
    for item in items:
        if (not isinstance(item["supplier_code"], str) or not item["supplier_code"] or
            item["supplier_code"] != item["supplier_code"].strip() or
            not isinstance(item["source_tab"], str) or item["source_tab"] not in {"ФОП", "ЮО"} or
            type(item["source_row"]) is not int or item["source_row"] < 2 or
            not isinstance(item["verification_date"], str) or
            not isinstance(item["verification_officer"], str) or
            not isinstance(item["factual_edr_status"], str) or
            item["factual_edr_status"] not in FACTUAL_STATUSES or
            not isinstance(item["source"], str) or item["source"] != SOURCE or
            not isinstance(item["formulas"], list) or
            any(not isinstance(field, str) or field not in {"e", "i", "l"}
                for field in item["formulas"])):
            raise ValueError("FACTUAL_PREVIEW_ITEM_INVALID")
    if items != sorted(items, key=lambda item: (item["source_tab"], item["source_row"],
                                              item["supplier_code"])):
        raise ValueError("FACTUAL_PREVIEW_ORDER_INVALID")
    if payload["source_digest"] != source_digest(items):
        raise ValueError("FACTUAL_PREVIEW_DIGEST_MISMATCH")
    return items


def _event_status(item):
    try:
        snapshot = json.loads(item.get("snapshot_json") or "{}")
    except (TypeError, ValueError):
        return "!malformed"
    if not isinstance(snapshot, dict):
        return "!malformed"
    key = "factual_edr_status" if item["event_type"] == SOURCE else "edr_status"
    status = str(snapshot.get(key) or "").strip()
    if item["event_type"] == SOURCE and status:
        checked_day = edr_sync_v2.normalized_date(item.get("occurred_at"))
        return (status if edr_sync_v2._legacy_google_factual_status(item, snapshot, checked_day)
                else "!invalid_provenance")
    return status


def preview(con, payload, *, require_query_only=True):
    items = validate(payload)
    if require_query_only and con.execute("PRAGMA query_only").fetchone()[0] != 1:
        raise ValueError("QUERY_ONLY_REQUIRED")
    codes = [item["supplier_code"] for item in items]
    registry = supplier_registry_integration._build_full_registry(con)
    identity = {}
    for row in registry["items"]:
        identity.setdefault(str(row["supplier_code"]).strip(), []).append(row)
    statuses = edr_sync_v2.canonical_prozorro_statuses(con, codes)
    current_qualification = edr_sync_v2.active_qualification_dates(con)
    historical_qualification = legacy_google_factual_edr_audit._historical_qualification_dates(con, codes)
    verification_projection = edr_sync_v2.current_verification_projections(con, codes)
    marks = ",".join("?" for _ in codes)
    ledger = {code: [] for code in codes}
    for raw in con.execute("SELECT * FROM supplier_edr_verification_events WHERE supplier_code IN (" +
                           marks + ")", codes):
        ledger[raw["supplier_code"]].append(dict(raw))
    profiles = {}
    for raw in con.execute("SELECT supplier_code,source_sheet,edr_status,edr_checked_at "
                           "FROM supplier_edr_profiles WHERE supplier_code IN (" + marks + ")", codes):
        profiles.setdefault(raw["supplier_code"], []).append(dict(raw))
    duplicate_codes = {code for code, count in Counter(codes).items() if count > 1}
    duplicate_rows = {key for key, count in Counter(
        (item["source_tab"], item["source_row"]) for item in items).items() if count > 1}
    counts, by_status, by_activity = Counter(), Counter(), Counter()
    rows = []
    for item in items:
        code, status = item["supplier_code"], item["factual_edr_status"]
        matched = identity.get(code, [])
        day, officer = _day(item["verification_date"]), _officer(item["verification_officer"])
        officer_key = edr_sync_v2.normalize_person(officer)
        current_status = statuses.get(code, "Ще не в реєстрі")
        activity = "active" if current_status == "Активний" else "non_active"
        if code in duplicate_codes or (item["source_tab"], item["source_row"]) in duplicate_rows or len(matched) != 1:
            result = "ambiguous_identity"
        elif {"individual_entrepreneur": "ФОП", "legal_entity": "ЮО"}.get(
                matched[0]["entity_type"]) != item["source_tab"]:
            result = "routing_or_unsupported_identity"
        elif len(profiles.get(code, [])) > 1 or (profiles.get(code) and
                profiles[code][0]["source_sheet"] in {"ФОП", "ЮО"} and
                profiles[code][0]["source_sheet"] != item["source_tab"]):
            result = "ambiguous_profile_or_routing"
        elif item["formulas"]:
            result = "formula_evidence_review"
        elif not day or not officer:
            result = "invalid_date_or_officer"
        else:
            qualification_day = (current_qualification.get(code, "") if current_status == "Активний"
                                 else historical_qualification.get(code, ""))
            profile = (profiles.get(code) or [{}])[0]
            profile_checked = str(profile.get("edr_checked_at") or "").strip()
            profile_day = edr_sync_v2.normalized_date(profile_checked)
            profile_status = str(profile.get("edr_status") or "").strip()
            same_legacy = [event for event in ledger[code] if event["event_type"] == SOURCE and
                           edr_sync_v2.normalized_date(event["occurred_at"]) == day and
                           edr_sync_v2.normalize_person(event["officer"]) == officer_key]
            factual = [event for event in ledger[code] if event["event_type"] in
                       {"manual_edr", "google_clarity", SOURCE} and _event_status(event)]
            newer = [event for event in factual if
                     edr_sync_v2.normalized_date(event["occurred_at"]) > day]
            same_other = [event for event in factual if
                          edr_sync_v2.normalized_date(event["occurred_at"]) == day and
                          event not in same_legacy]
            same_other_equivalent = bool(same_other) and all(
                _event_status(event) == status and
                edr_sync_v2.normalize_person(event["officer"]) == officer_key
                for event in same_other)
            same_legacy_other_officer = any(event["event_type"] == SOURCE and
                edr_sync_v2.normalized_date(event["occurred_at"]) == day and
                event not in same_legacy for event in ledger[code])
            if not qualification_day or day <= qualification_day:
                result = "chronology_not_proven_after_qualification"
            elif profile_checked and not profile_day:
                result = "invalid_profile_chronology"
            elif profile_day >= day and profile_status in (FACTUAL_STATUSES | {"Зареєстровано"}):
                result = "newer_or_same_profile_factual_evidence"
            elif newer:
                result = "newer_pqm_factual_evidence"
            elif len(same_legacy) > 1:
                result = "ambiguous_equivalent_legacy_events"
            elif same_other and not same_other_equivalent:
                result = "same_date_evidence_review"
            elif same_other_equivalent and not same_legacy_other_officer:
                result = "equivalent_factual_evidence"
            elif same_legacy:
                existing_status = _event_status(same_legacy[0])
                if existing_status == status:
                    result = "equivalent_factual_evidence"
                elif existing_status:
                    result = "conflicting_existing_legacy_status"
                elif same_legacy_other_officer:
                    result = "same_date_evidence_review"
                else:
                    result = "existing_event_enrichment"
            elif same_legacy_other_officer:
                result = "same_date_evidence_review"
            else:
                result = "new_event_needed"
        counts[result] += 1
        by_status[status + ":" + result] += 1
        by_activity[activity + ":" + result] += 1
        rows.append({"source_tab": item["source_tab"], "source_row": item["source_row"],
                     "result": result})
    state_digest = _digest({"identity": {code: identity.get(code, []) for code in codes},
                            "current_qualification": {code: current_qualification.get(code, "") for code in codes},
                            "historical_qualification": historical_qualification,
                            "verification": {code: verification_projection.get(code, {}) for code in codes},
                            "profiles": profiles, "ledger": ledger})
    selection_digest = _digest({"spreadsheet_id": payload["spreadsheet_id"],
                                "source_digest": payload["source_digest"],
                                "state_digest": state_digest, "rows": rows})
    ticket = verification._preview_ticket("factual-e:" + selection_digest,
                                          int(time.time()) + verification._PREVIEW_TICKET_SECONDS)
    selected = counts["new_event_needed"] + counts["existing_event_enrichment"]
    return {"dry_run": True, "received": len(items), "selected": selected,
            "batch_apply_ready": selected == len(items),
            "source_digest": payload["source_digest"],
            "current_pqm_state_digest": state_digest, "selection_digest": selection_digest,
            "preview_ticket": ticket, "ticket_ttl_seconds": verification._PREVIEW_TICKET_SECONDS,
            "new_event_needed": counts["new_event_needed"],
            "existing_event_enrichment": counts["existing_event_enrichment"],
            "equivalent_factual_evidence": counts["equivalent_factual_evidence"],
            "ambiguous": sum(counts[key] for key in counts if "ambiguous" in key or "routing" in key),
            "blocked": len(items) - selected - counts["equivalent_factual_evidence"],
            "by_reason": dict(counts), "by_status_reason": dict(by_status),
            "by_activity_reason": dict(by_activity), "rows": rows,
            "db_writes": 0, "google_writes": 0, "query_only": 1}


def _event_key(item):
    return verification._digest({"identity": item["supplier_code"],
        "date": item["verification_date"],
        "officer": edr_sync_v2.normalize_person(item["verification_officer"]),
        "source": SOURCE})


def _factual_snapshot(snapshot, item, payload):
    updated = dict(snapshot)
    updated.update({"factual_edr_status": item["factual_edr_status"],
        "factual_source_digest": payload["source_digest"],
        "factual_spreadsheet_id": payload["spreadsheet_id"],
        "factual_source_tab": item["source_tab"],
        "factual_source_row": item["source_row"],
        "factual_provenance_version": 1})
    return updated


def _equivalent_after_apply(con, items, payload):
    for item in items:
        rows = [dict(row) for row in con.execute(
            "SELECT * FROM supplier_edr_verification_events WHERE supplier_code=? "
            "AND event_type=? AND occurred_at=?", (item["supplier_code"], SOURCE,
                                                 item["verification_date"]))
            if edr_sync_v2.normalize_person(row["officer"]) ==
               edr_sync_v2.normalize_person(item["verification_officer"])]
        if len(rows) != 1:
            return False
        row = rows[0]
        try:
            snapshot = json.loads(row["snapshot_json"] or "{}")
        except (ValueError, TypeError):
            return False
        if (not isinstance(snapshot, dict) or
            edr_sync_v2._legacy_google_factual_status(row, snapshot,
                edr_sync_v2.normalized_date(row["occurred_at"])) != item["factual_edr_status"] or
            snapshot.get("factual_source_digest") != payload["source_digest"] or
            snapshot.get("factual_spreadsheet_id") != payload["spreadsheet_id"] or
            snapshot.get("factual_source_tab") != item["source_tab"] or
            snapshot.get("factual_source_row") != item["source_row"]):
            return False
    return True


def apply(con, payload, *, after_write_hook=None):
    """Atomic max-50 factual insert/enrichment; caller enforces SANDBOX auth."""
    expected = REQUEST_KEYS | {"selection_digest", "preview_ticket", "confirmation"}
    if not isinstance(payload, dict) or set(payload) != expected:
        raise ValueError("FACTUAL_APPLY_SCHEMA_INVALID")
    if payload["confirmation"] != APPLY_CONFIRMATION:
        raise ValueError("EXPLICIT_CONFIRMATION_REQUIRED")
    source = {key: payload[key] for key in REQUEST_KEYS}
    items = validate(source)  # Includes hard max 50, literal identity, digest and vocabulary.
    if con.execute("PRAGMA query_only").fetchone()[0]:
        raise ValueError("READ_ONLY_CONNECTION_CANNOT_APPLY")
    if not verification._ticket_valid(payload["preview_ticket"],
            "factual-e:" + payload["selection_digest"]):
        raise ValueError("PREVIEW_TICKET_INVALID_OR_EXPIRED")
    con.execute("BEGIN IMMEDIATE")
    try:
        current = preview(con, source, require_query_only=False)
        if current["selection_digest"] != payload["selection_digest"]:
            if _equivalent_after_apply(con, items, source):
                con.rollback()
                return {"selected": len(items), "inserted": 0, "enriched": 0,
                    "verified": len(items), "duplicates_prevented": len(items),
                    "db_writes": 0, "google_writes": 0,
                    "transaction_status": "ALREADY_APPLIED"}
            raise ValueError("STALE_PREVIEW_OR_PQM_STATE")
        if current["selected"] != len(items) or any(row["result"] not in
                {"new_event_needed", "existing_event_enrichment"} for row in current["rows"]):
            raise ValueError("SELECTION_NOT_FULLY_ELIGIBLE")
        codes = sorted({item["supplier_code"] for item in items})
        protected_before = verification._protected_state(con, codes)
        before = con.total_changes
        inserted = enriched = 0
        for item, classified in zip(items, current["rows"]):
            day, officer = item["verification_date"], verification._officer(
                item["verification_officer"])
            if classified["result"] == "existing_event_enrichment":
                matches = [dict(row) for row in con.execute(
                    "SELECT * FROM supplier_edr_verification_events WHERE supplier_code=? "
                    "AND event_type=? AND occurred_at=?", (item["supplier_code"], SOURCE, day))
                    if edr_sync_v2.normalize_person(row["officer"]) ==
                       edr_sync_v2.normalize_person(officer)]
                if len(matches) != 1:
                    raise ValueError("AMBIGUOUS_ENRICHMENT_TARGET")
                row = matches[0]
                snapshot = json.loads(row["snapshot_json"] or "{}")
                if (not isinstance(snapshot, dict) or snapshot.get("factual_edr_status") or
                    row["source"] != SOURCE or row["source_sheet"] not in {"ФОП", "ЮО"}):
                    raise ValueError("ENRICHMENT_PROVENANCE_INVALID")
                updated = _factual_snapshot(snapshot, item, source)
                changed = set(json.loads(row["changed_fields"] or "[]"))
                changed.add("factual_edr_status")
                result = con.execute("UPDATE supplier_edr_verification_events "
                    "SET snapshot_json=?,changed_fields=? WHERE id=? AND snapshot_json=?",
                    (json.dumps(updated, ensure_ascii=False, sort_keys=True),
                     json.dumps(sorted(changed), ensure_ascii=False), row["id"],
                     row["snapshot_json"]))
                if result.rowcount != 1:
                    raise ValueError("ENRICHMENT_STALE")
                enriched += 1
            else:
                snapshot = {"verification_date": day, "verification_officer": officer,
                    "source": SOURCE, "spreadsheet_id": source["spreadsheet_id"],
                    "source_digest": source["source_digest"],
                    "source_tab": item["source_tab"], "source_row": item["source_row"]}
                snapshot = _factual_snapshot(snapshot, item, source)
                result = con.execute("""INSERT INTO supplier_edr_verification_events
                  (supplier_code,event_type,occurred_at,officer,source,source_submission_id,
                   source_sheet,source_row,changed_fields,snapshot_hash,snapshot_json,created_at)
                  VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""", (
                    item["supplier_code"], SOURCE, day, officer, SOURCE, "",
                    item["source_tab"], item["source_row"],
                    '["verification_date","verification_officer","factual_edr_status"]',
                    _event_key(item), json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
                    datetime.now(timezone.utc).isoformat()))
                if result.rowcount != 1:
                    raise ValueError("FACTUAL_INSERT_FAILED")
                inserted += 1
        if after_write_hook:
            after_write_hook(con)
        if not _equivalent_after_apply(con, items, source):
            raise ValueError("AFTER_VERIFICATION_FAILED")
        if verification._protected_state(con, codes) != protected_before:
            raise ValueError("PROTECTED_STATE_CHANGED")
        if con.total_changes - before != inserted + enriched:
            raise ValueError("UNEXPECTED_DB_MUTATION")
        con.commit()
        return {"selected": len(items), "inserted": inserted, "enriched": enriched,
            "verified": len(items), "duplicates_prevented": 0, "db_writes": inserted+enriched,
            "google_writes": 0, "transaction_status": "COMMITTED"}
    except Exception:
        con.rollback()
        raise
