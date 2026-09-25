"""Temporary, bounded, read-only PROD Google/PQM baseline comparator.

Google is read by Apps Script, never by this module. No Apply functions live here.
"""
from collections import Counter
from datetime import date
import hashlib
import json
import os
import re
import sqlite3
from pathlib import Path

import edr_sync_v2


PATH = "/api/integrations/google/baseline/audit"
ENABLE_ENV = "PQM_PROD_GOOGLE_BASELINE_ENABLED"
SPREADSHEET_ENV = "PQM_GOOGLE_REGISTRY_SPREADSHEET_ID"
MAX_ROWS = 500
MAX_BODY_BYTES = 1024 * 1024
SPECIAL = frozenset({"Припинено", "В стані припинення",
                     "Порушено справу про банкрутство", "Банкрут"})
VOCABULARY = SPECIAL | {"Зареєстровано", "Неактуально", "Немає інформації"}
FIELDS = {"g": "termination_decision_details", "j": "termination_record_date",
          "k": "termination_record_number", "m": "edr_notes"}
ITEM_KEYS = frozenset({"supplier_code", "source_tab", "source_row", "e", "i", "l",
                       "g", "j", "k", "m", "duplicate_google_identity"})


def enabled(environ=None):
    env = os.environ if environ is None else environ
    return str(env.get(ENABLE_ENV, "")).strip() == "1"


def open_read_only(path):
    uri = Path(path).resolve().as_uri() + "?mode=ro"
    con = sqlite3.connect(uri, uri=True, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA query_only=ON")
    return con


def digest(rows):
    raw = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def validate(payload, environ=None):
    env = os.environ if environ is None else environ
    expected = str(env.get(SPREADSHEET_ENV, "")).strip()
    if not expected:
        raise ValueError("AUTHORIZED_SPREADSHEET_NOT_CONFIGURED")
    if not isinstance(payload, dict) or set(payload) != {"spreadsheet_id", "source_digest", "records"}:
        raise ValueError("BASELINE_SCHEMA_INVALID")
    if payload["spreadsheet_id"] != expected:
        raise ValueError("SPREADSHEET_ID_MISMATCH")
    rows = payload["records"]
    if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_ROWS:
        raise ValueError("BASELINE_BATCH_LIMIT")
    if payload["source_digest"] != digest(rows):
        raise ValueError("SOURCE_DIGEST_MISMATCH")
    for row in rows:
        if (not isinstance(row, dict) or set(row) != ITEM_KEYS or
            any(not isinstance(row[key], str) for key in ITEM_KEYS - {"source_row", "duplicate_google_identity"}) or
            not row["supplier_code"] or row["supplier_code"] != row["supplier_code"].strip() or
            row["source_tab"] not in {"ФОП", "ЮО"} or
            type(row["source_row"]) is not int or row["source_row"] < 2 or
            type(row["duplicate_google_identity"]) is not bool):
            raise ValueError("BASELINE_ROW_INVALID")
    if len({(row["source_tab"], row["source_row"]) for row in rows}) != len(rows):
        raise ValueError("DUPLICATE_GOOGLE_ROW")
    return rows


def _day(value):
    value = str(value or "").strip()
    match = re.fullmatch(r"(\d{2})\.(\d{2})\.(\d{4})", value)
    if match:
        value = f"{match[3]}-{match[2]}-{match[1]}"
    try:
        return date.fromisoformat(value).isoformat() if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) else ""
    except ValueError:
        return ""


def _snapshot(event):
    try:
        value = json.loads(event["snapshot_json"] or "{}")
        return value if isinstance(value, dict) else {}
    except (TypeError, ValueError):
        return {}


def _field_bucket(google, pqm):
    if google and pqm:
        return "exact" if google == pqm else "different_nonblank"
    if google:
        return "google_present_pqm_missing"
    if pqm:
        return "google_blank_pqm_present"
    return "both_blank"


def _status(value):
    # Google E may carry a presentation emoji; the semantic value is compared.
    return re.sub(r"^[^\w]+", "", str(value or "").strip()).strip()


def audit(con, payload, environ=None):
    rows = validate(payload, environ)
    if con.execute("PRAGMA query_only").fetchone()[0] != 1:
        raise ValueError("QUERY_ONLY_REQUIRED")
    codes = sorted({r["supplier_code"] for r in rows})
    marks = ",".join("?" for _ in codes)
    profiles = {}
    for raw in con.execute("SELECT supplier_code,source_sheet,termination_decision_details,"
                           "termination_record_date,termination_record_number,edr_notes "
                           f"FROM supplier_edr_profiles WHERE supplier_code IN ({marks})", codes):
        profiles.setdefault(raw["supplier_code"], []).append(dict(raw))
    known = {r[0] for r in con.execute(
        f"SELECT supplier_code FROM submissions WHERE supplier_code IN ({marks}) UNION "
        f"SELECT supplier_code FROM supplier_registry_summary WHERE supplier_code IN ({marks})", codes + codes)}
    events = {code: [] for code in codes}
    for raw in con.execute("SELECT supplier_code,event_type,occurred_at,officer,source,source_sheet,"
                           "source_row,snapshot_json FROM supplier_edr_verification_events "
                           f"WHERE supplier_code IN ({marks})", codes):
        events[raw["supplier_code"]].append(dict(raw))
    statuses = edr_sync_v2.canonical_prozorro_statuses(con, codes)
    qualifications = edr_sync_v2.active_qualification_dates(con)
    projection = edr_sync_v2.current_verification_projections(con, codes)
    e, il, group = Counter(), Counter(), Counter()
    fields = {key: Counter() for key in FIELDS}
    special = Counter()
    within_batch = Counter(r["supplier_code"] for r in rows)
    for r in rows:
        code = r["supplier_code"]
        google_status = _status(r["e"])
        e[google_status if google_status in VOCABULARY else "other"] += 1
        special_row = google_status in SPECIAL
        if special_row:
            special["total"] += 1
        for key in FIELDS:
            fields[key]["google_present"] += bool(r[key].strip())
        if all(r[key].strip() for key in ("g", "j", "k")):
            group["complete"] += 1
        if r["duplicate_google_identity"] or within_batch[code] > 1:
            il["duplicate_google_identity"] += 1
            group["ambiguous"] += 1
            if special_row:
                special["ambiguous"] += 1
            continue
        candidate_profiles = profiles.get(code, [])
        if len(candidate_profiles) > 1:
            il["duplicate_pqm_identity"] += 1
            group["ambiguous"] += 1
            if special_row:
                special["ambiguous"] += 1
            continue
        if code not in known and not candidate_profiles:
            il["missing_pqm_identity"] += 1
            group["blocked_missing_profile"] += 1
            if special_row:
                special["blocked"] += 1
            continue
        p = candidate_profiles[0] if candidate_profiles else {}
        if not p:
            group["blocked_missing_profile"] += 1
        if p.get("source_sheet") in {"ФОП", "ЮО"} and p["source_sheet"] != r["source_tab"]:
            il["routing_mismatch"] += 1
            group["ambiguous"] += 1
            if special_row:
                special["ambiguous"] += 1
            continue
        status = statuses.get(code, "Ще не в реєстрі")
        if special_row:
            special["active" if status == "Активний" else "non_active"] += 1
        day, officer = _day(r["i"]), edr_sync_v2.normalize_person(r["l"])
        if r["i"].strip() and not day:
            il["invalid_date"] += 1
        elif day and not officer:
            il["missing_officer"] += 1
        elif day and officer:
            il["google_valid_date_officer"] += 1
        if special_row:
            if day and officer:
                special["valid_i_l"] += 1
            else:
                special["blocked"] += 1
        equivalent = []
        if day and officer:
            equivalent = [item for item in events[code]
                          if _day(str(item["occurred_at"])[:10]) == day and
                          edr_sync_v2.normalize_person(item["officer"]) == officer]
            if equivalent:
                il["equivalent_event"] += 1
                for item in equivalent:
                    if item["event_type"] == "legacy_google_registry":
                        factual = edr_sync_v2._legacy_google_factual_status(
                            item, _snapshot(item), day) in SPECIAL
                        il["existing_factual_overlap" if factual else "existing_il_only_overlap"] += 1
                        break
            else:
                current = projection.get(code, {}).get("verification_date") or ""
                current_day = _day(str(current)[:10])
                if not current_day:
                    il["pqm_missing_google_present"] += 1
                elif day > current_day:
                    il["google_newer_than_pqm"] += 1
                elif day == current_day:
                    il["same_date"] += 1
                else:
                    il["google_older"] += 1
        if special_row and day and officer:
            exact = any(
                _day(str(item["occurred_at"])[:10]) == day and
                edr_sync_v2.normalize_person(item["officer"]) == officer and
                (edr_sync_v2._legacy_google_factual_status(item, _snapshot(item), day)
                 if item["event_type"] == "legacy_google_registry" else
                 _snapshot(item).get("edr_status") if item["event_type"] in {"manual_edr", "google_clarity"}
                 else "") == google_status
                for item in events[code])
            special["existing_exact_factual" if exact else "missing_factual_evidence"] += 1
        if not p:
            continue  # Profile-backed G/J/K/M cannot be compared without a literal profile.
        for key, col in FIELDS.items():
            gv, pv = r[key].strip(), str(p.get(col) or "").strip()
            if key == "j":
                gv, pv = _day(gv) if gv else "", _day(pv) if pv else ""
            fields[key]["pqm_present"] += bool(pv)
            fields[key][_field_bucket(gv, pv)] += 1
        gg = [_day(r[key]) if key == "j" and r[key].strip() else r[key].strip()
              for key in ("g", "j", "k")]
        pp = [_day(p.get(FIELDS[key])) if key == "j" and str(p.get(FIELDS[key]) or "").strip()
              else str(p.get(FIELDS[key]) or "").strip() for key in ("g", "j", "k")]
        if all(gg):
            if not any(pp):
                group["complete_pqm_missing"] += 1
            elif gg == pp:
                group["complete_exact"] += 1
            else:
                group["complete_different"] += 1
        elif any(gg):
            group["partial"] += 1
    il["google_supplier_rows"] = len(rows)
    il["planned_phase1"] = il["google_newer_than_pqm"] + il["pqm_missing_google_present"]
    il["ambiguous"] = il["duplicate_google_identity"] + il["duplicate_pqm_identity"] + il["routing_mismatch"]
    status_keys = ("Зареєстровано", "Неактуально", "Припинено", "В стані припинення",
                   "Порушено справу про банкрутство", "Банкрут", "Немає інформації", "other")
    special_keys = ("total", "active", "non_active", "valid_i_l", "existing_exact_factual",
                    "missing_factual_evidence", "blocked", "ambiguous")
    il_keys = ("google_supplier_rows", "google_valid_date_officer", "google_newer_than_pqm",
               "pqm_missing_google_present", "planned_phase1", "same_date", "google_older",
               "missing_officer", "equivalent_event", "existing_factual_overlap",
               "existing_il_only_overlap", "invalid_date", "duplicate_google_identity",
               "duplicate_pqm_identity", "missing_pqm_identity", "routing_mismatch", "ambiguous")
    field_keys = ("google_present", "pqm_present", "exact", "google_present_pqm_missing",
                  "different_nonblank", "google_blank_pqm_present", "both_blank")
    group_keys = ("complete", "complete_exact", "complete_pqm_missing", "complete_different",
                  "partial", "blocked_missing_profile", "ambiguous")
    return {"factual_e": {"google_status_counts": {key: e[key] for key in status_keys},
                          "special": {key: special[key] for key in special_keys}},
            "verification": {key: il[key] for key in il_keys}, "termination_notes": {
                "fields": {key: {bucket: fields[key][bucket] for bucket in field_keys} for key in FIELDS},
                "block": {key: group[key] for key in group_keys}},
            "received": len(rows), "query_only": 1, "db_writes": 0, "google_writes": 0}
