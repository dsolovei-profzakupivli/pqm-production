"""SANDBOX-only, read-only paired audit of factual Google E evidence."""
from collections import Counter
from datetime import date
import hashlib
import json
import re

import edr_sync_v2
from legacy_google_verification_preview import SANDBOX_SPREADSHEET_ID
import supplier_registry_integration


PATH = "/api/integrations/google/factual-edr/audit"
SPECIAL = frozenset({"Припинено", "В стані припинення",
                     "Порушено справу про банкрутство", "Банкрут"})
ITEM_KEYS = frozenset({"supplier_code", "source_tab", "source_row", "google_edr_status",
                       "google_prozorro_status", "verification_date", "verification_officer",
                       "formulas"})
FACTUAL_STATUSES = SPECIAL | {"Зареєстровано"}
STATUS_VOCABULARY = SPECIAL | {"Неактуально", "Зареєстровано", "Немає інформації"}


def _status_bucket(value):
    text = str(value or "").strip()
    return text if text in STATUS_VOCABULARY else "(other_or_blank)"


def source_digest(rows):
    keys = ("supplier_code", "source_tab", "source_row", "google_edr_status",
            "google_prozorro_status", "verification_date", "verification_officer", "formulas")
    raw = json.dumps([[row[key] for key in keys] for row in rows],
                     ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _date(value):
    value = str(value or "").strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return ""
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        return ""


def validate(payload):
    if not isinstance(payload, dict) or set(payload) != {"spreadsheet_id", "source_digest", "records"}:
        raise ValueError("AUDIT_SCHEMA_INVALID")
    if payload["spreadsheet_id"] != SANDBOX_SPREADSHEET_ID:
        raise ValueError("SANDBOX_SPREADSHEET_MISMATCH")
    rows = payload["records"]
    if not isinstance(rows, list) or not 1 <= len(rows) <= 100:
        raise ValueError("AUDIT_BATCH_LIMIT")
    if any(not isinstance(row, dict) or set(row) != ITEM_KEYS for row in rows):
        raise ValueError("AUDIT_ITEM_SCHEMA_INVALID")
    seen = set()
    for row in rows:
        if (not isinstance(row["supplier_code"], str) or not row["supplier_code"] or
            row["supplier_code"] != row["supplier_code"].strip() or
            row["source_tab"] not in {"ФОП", "ЮО"} or
            type(row["source_row"]) is not int or row["source_row"] < 2 or
            not isinstance(row["google_edr_status"], str) or row["google_edr_status"] not in SPECIAL or
            not isinstance(row["google_prozorro_status"], str) or
            row["google_prozorro_status"] not in {"Активний", "Неактивний", "Ще не в реєстрі", "Призупинений"} or
            not isinstance(row["verification_date"], str) or
            not isinstance(row["verification_officer"], str) or
            not isinstance(row["formulas"], list) or
            any(value not in {"e", "i", "l"} for value in row["formulas"])):
            raise ValueError("AUDIT_ITEM_INVALID")
        key = row["supplier_code"]
        if key in seen:
            raise ValueError("DUPLICATE_IDENTITY_IN_BATCH")
        seen.add(key)
    if payload["source_digest"] != source_digest(rows):
        raise ValueError("AUDIT_DIGEST_MISMATCH")
    return rows


def _factual_events(events):
    result = []
    for event in events:
        try:
            snapshot = json.loads(event.get("snapshot_json") or "{}")
        except (TypeError, ValueError):
            continue
        if not isinstance(snapshot, dict):
            continue
        status = str(snapshot.get("edr_status") or "").strip()
        day = _date(str(event.get("occurred_at") or "")[:10])
        if status in FACTUAL_STATUSES and day:
            result.append({"date": day, "status": status, "event_type": event["event_type"]})
    return sorted(result, key=lambda x: (x["date"], x["event_type"]))


def _legacy_event_has_factual_status(event):
    try:
        snapshot = json.loads(event.get("snapshot_json") or "{}")
    except (TypeError, ValueError):
        return False
    return isinstance(snapshot, dict) and str(snapshot.get("edr_status") or "").strip() in FACTUAL_STATUSES


def _historical_qualification_dates(con, codes):
    """Past registry contracts evidence an effective qualification, not current activity."""
    if not edr_sync_v2._table_exists(con, "registry_contracts") or not edr_sync_v2._table_exists(con, "qualifications"):
        return {}
    marks = ",".join("?" for _ in codes)
    result = {}
    for row in con.execute("SELECT rc.supplier_code,q.decision_date FROM registry_contracts rc "
                           "JOIN qualifications q ON q.id=rc.qualification_id "
                           "WHERE rc.supplier_code IN (" + marks + ") "
                           "AND rc.status IN ('active','terminated')", codes):
        day = _date(str(row["decision_date"] or "")[:10])
        code = row["supplier_code"]
        if day > result.get(code, ""):
            result[code] = day
    return result


def audit(con, payload):
    rows = validate(payload)
    if con.execute("PRAGMA query_only").fetchone()[0] != 1:
        raise ValueError("QUERY_ONLY_REQUIRED")
    codes = [row["supplier_code"] for row in rows]
    marks = ",".join("?" for _ in codes)
    profiles = {}
    for row in con.execute("SELECT supplier_code,source_sheet,edr_status,edr_checked_at "
                           "FROM supplier_edr_profiles WHERE supplier_code IN (" + marks + ")", codes):
        profiles.setdefault(row["supplier_code"], []).append(dict(row))
    known = {row[0] for row in con.execute(
        "SELECT supplier_code FROM submissions WHERE supplier_code IN (" + marks + ") "
        "UNION SELECT supplier_code FROM supplier_registry_summary WHERE supplier_code IN (" + marks + ")",
        codes + codes)}
    statuses = edr_sync_v2.canonical_prozorro_statuses(con, codes)
    qualification_dates = edr_sync_v2.active_qualification_dates(con)
    historical_qualification_dates = _historical_qualification_dates(con, codes)
    factual = supplier_registry_integration._factual_edr_events(con, codes)
    legacy = {}
    for event in con.execute("SELECT supplier_code,occurred_at,officer,snapshot_json FROM supplier_edr_verification_events "
                             "WHERE event_type='legacy_google_registry' AND supplier_code IN (" + marks + ")", codes):
        legacy.setdefault(event["supplier_code"], []).append(dict(event))
    legacy_total = con.execute("SELECT COUNT(*) FROM supplier_edr_verification_events "
                               "WHERE event_type='legacy_google_registry'").fetchone()[0]
    counts, by_status, risk, issues = Counter(), {}, Counter(), Counter()
    for row in rows:
        code = row["supplier_code"]
        category = by_status.setdefault(row["google_edr_status"], Counter())
        category["total"] += 1
        google_activity = "active" if row["google_prozorro_status"] == "Активний" else "non_active"
        category["google_" + google_activity] += 1
        activity = "google_" + google_activity  # identity-blocked rows have no PQM activity result
        def mark(bucket):
            counts["classified"] += 1
            counts[bucket] += 1
            category[bucket + "_" + activity] += 1
        candidates = profiles.get(code, [])
        if code not in known and not candidates:
            issues["missing_identity"] += 1
            risk["unresolved_identity"] += 1
            mark("E_blocked_identity")
            continue
        if len(candidates) > 1 or (candidates and candidates[0]["source_sheet"] in {"ФОП", "ЮО"} and
                                    candidates[0]["source_sheet"] != row["source_tab"]):
            issues["ambiguous_or_routing_identity"] += 1
            risk["unresolved_identity"] += 1
            mark("E_blocked_identity")
            continue
        profile = candidates[0] if candidates else {}
        counts["compared"] += 1
        current_status = statuses.get(code, "Ще не в реєстрі")
        activity = "active" if current_status == "Активний" else "non_active"
        category["pqm_" + activity] += 1
        category["pqm_prozorro_" + current_status] += 1
        if current_status != row["google_prozorro_status"]:
            issues["google_pqm_prozorro_mismatch"] += 1
        day = _date(row["verification_date"])
        officer = edr_sync_v2.normalize_person(row["verification_officer"])
        events = factual.get(code, [])
        factual_events = _factual_events(events)
        latest = factual_events[-1] if factual_events else None
        if latest:
            category["latest_pqm_factual_" + _status_bucket(latest["status"])] += 1
            category["latest_pqm_factual_event_type_" + latest["event_type"]] += 1
            if day:
                category["latest_pqm_factual_date_" + (
                    "newer" if latest["date"] > day else "same" if latest["date"] == day else "older")] += 1
        if profile.get("edr_status"):
            category["profile_status_" + _status_bucket(profile["edr_status"])] += 1
        qual_day = (qualification_dates.get(code, "") if current_status == "Активний" else
                    historical_qualification_dates.get(code, ""))
        if qual_day:
            category["qualification_date_present"] += 1
        displayed = edr_sync_v2.operational_edr_status(
            current_status, qual_day, events, str(profile.get("edr_status") or ""))
        risk["same" if displayed == row["google_edr_status"] else
             "to_registered" if displayed == "Зареєстровано" else
             "to_not_current" if displayed == "Неактуально" else "to_other"] += 1
        category["pqm_operational_" + _status_bucket(displayed)] += 1
        equivalent_items = [item for item in legacy.get(code, [])
                            if day and officer and _date(str(item["occurred_at"])[:10]) == day and
                            edr_sync_v2.normalize_person(item["officer"]) == officer]
        if legacy.get(code):
            counts["legacy_event_any"] += 1
            category["legacy_event_any"] += 1
            if any(not _legacy_event_has_factual_status(item) for item in legacy[code]):
                counts["legacy_event_without_factual_status_any"] += 1
                category["legacy_event_without_factual_status_any"] += 1
        if equivalent_items:
            counts["legacy_event_same_date_officer"] += 1
            category["legacy_pair_equivalent"] += 1
            if any(not _legacy_event_has_factual_status(item) for item in equivalent_items):
                counts["legacy_pair_without_factual_status"] += 1
                category["legacy_pair_without_factual_status"] += 1
        if row["formulas"]:
            issues["formula_review"] += 1
            mark("D_missing_or_unsafe_evidence")
        elif not day or not officer:
            issues["missing_or_invalid_date_officer"] += 1
            mark("D_missing_or_unsafe_evidence")
        elif qual_day and day < qual_day:
            mark("B_before_newer_qualification")
        elif latest and (latest["date"] > day or
                         latest["date"] == day and latest["status"] == row["google_edr_status"]):
            mark("C_equivalent_or_newer_pqm_factual")
        elif latest and latest["date"] == day:
            issues["same_day_conflicting_factual"] += 1
            mark("review_same_day_conflicting_factual")
        elif qual_day and day > qual_day:
            mark("A_after_latest_qualification")
        elif qual_day and day == qual_day:
            issues["same_day_qualification"] += 1
            mark("review_same_day_qualification")
        else:
            issues["no_effective_qualification_date"] += 1
            mark("review_no_effective_qualification_date")
    return {"dry_run": True, "db_writes": 0, "google_writes": 0, "query_only": 1,
            "received": len(rows), "counts": dict(counts), "legacy_event_db_total": legacy_total,
            "by_google_factual_status": {key: dict(value) for key, value in by_status.items()},
            "pqm_to_google_e_overwrite_risk": dict(risk), "issues": dict(issues)}
