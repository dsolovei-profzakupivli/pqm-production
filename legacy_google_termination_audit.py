"""SANDBOX-only, read-only paired Google registry G/J/K/M audit."""
from collections import Counter
from datetime import date
import hashlib
import json
import re

from legacy_google_verification_preview import SANDBOX_SPREADSHEET_ID


PATH = "/api/integrations/google/termination-notes/audit"
FIELDS = {"g": "termination_decision_details", "j": "termination_record_date",
          "k": "termination_record_number", "m": "edr_notes"}
ITEM_KEYS = {"supplier_code", "source_tab", "source_row", "g", "j", "k", "m", "formulas"}
TARGET = "2791715838"


def digest(records):
    values = [[r[key] for key in ("supplier_code", "source_tab", "source_row", "g", "j", "k", "m")]
              + [r["formulas"]] for r in records]
    return hashlib.sha256(json.dumps(values, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def _date(value):
    value = str(value or "").strip()
    if not value:
        return ""
    match = re.fullmatch(r"(\d{2})\.(\d{2})\.(\d{4})", value)
    if match:
        value = f"{match[3]}-{match[2]}-{match[1]}"
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        return "!invalid"


def validate(payload):
    if not isinstance(payload, dict) or set(payload) != {"spreadsheet_id", "source_digest", "records"}:
        raise ValueError("AUDIT_SCHEMA_INVALID")
    if payload["spreadsheet_id"] != SANDBOX_SPREADSHEET_ID:
        raise ValueError("SANDBOX_SPREADSHEET_MISMATCH")
    rows = payload["records"]
    if not isinstance(rows, list) or not 1 <= len(rows) <= 100:
        raise ValueError("AUDIT_BATCH_LIMIT")
    if any(not isinstance(r, dict) or set(r) != ITEM_KEYS for r in rows):
        raise ValueError("AUDIT_ITEM_SCHEMA_INVALID")
    for r in rows:
        if (not isinstance(r["supplier_code"], str) or not r["supplier_code"] or
            r["supplier_code"] != r["supplier_code"].strip() or
            not isinstance(r["source_tab"], str) or r["source_tab"] not in {"ФОП", "ЮО"} or
            type(r["source_row"]) is not int or r["source_row"] < 2 or
            any(not isinstance(r[key], str) for key in FIELDS) or
            not isinstance(r["formulas"], list) or
            any(key not in FIELDS for key in r["formulas"])):
            raise ValueError("AUDIT_ITEM_INVALID")
    if len({(r["source_tab"], r["source_row"]) for r in rows}) != len(rows) or \
            len({r["supplier_code"] for r in rows}) != len(rows):
        raise ValueError("DUPLICATE_AUDIT_IDENTITY")
    if payload["source_digest"] != digest(rows):
        raise ValueError("AUDIT_DIGEST_MISMATCH")
    return rows


def audit(con, payload):
    rows = validate(payload)
    if con.execute("PRAGMA query_only").fetchone()[0] != 1:
        raise ValueError("QUERY_ONLY_REQUIRED")
    codes = [r["supplier_code"] for r in rows]
    marks = ",".join("?" for _ in codes)
    profiles = {}
    for p in con.execute("SELECT supplier_code,source_sheet,termination_decision_details,"
                         "termination_record_date,termination_record_number,edr_notes "
                         "FROM supplier_edr_profiles WHERE supplier_code IN (" + marks + ")", codes):
        profiles.setdefault(p["supplier_code"], []).append(dict(p))
    known = {r[0] for r in con.execute("SELECT supplier_code FROM submissions WHERE supplier_code IN (" +
                                     marks + ") UNION SELECT supplier_code FROM supplier_registry_summary "
                                     "WHERE supplier_code IN (" + marks + ")", codes + codes)}
    field_counts = {key: Counter() for key in FIELDS}
    groups = Counter()
    issues = Counter()
    target = None
    for r in rows:
        code = r["supplier_code"]
        candidates = profiles.get(code, [])
        if code not in known and not candidates:
            issues["missing_pqm_identity"] += 1
            continue
        if len(candidates) > 1:
            issues["ambiguous_profile"] += 1
            continue
        p = candidates[0] if candidates else {}
        if p.get("source_sheet") in {"ФОП", "ЮО"} and p["source_sheet"] != r["source_tab"]:
            issues["routing_mismatch"] += 1
            continue
        if r["formulas"]:
            issues["formula_evidence"] += 1
            continue
        values = {}
        invalid = False
        for col, field in FIELDS.items():
            gv = str(r[col] or "").strip()
            pv = str(p.get(field) or "").strip()
            if col == "j":
                gv, pv = _date(gv), _date(pv)
                if gv == "!invalid" or pv == "!invalid":
                    invalid = True
            values[col] = (gv, pv)
        if invalid:
            issues["invalid_date"] += 1
            continue
        for col, (gv, pv) in values.items():
            bucket = ("both_blank" if not gv and not pv else
                      "google_only" if gv and not pv else
                      "pqm_only" if pv and not gv else
                      "exact" if gv == pv else "different")
            field_counts[col][bucket] += 1
        google_group = [values[c][0] for c in ("g", "j", "k")]
        pqm_group = [values[c][1] for c in ("g", "j", "k")]
        if all(google_group):
            if not any(pqm_group):
                groups["google_complete_pqm_missing"] += 1
            elif google_group == pqm_group:
                groups["google_complete_exact"] += 1
            elif not all(pqm_group):
                groups["google_complete_pqm_partial"] += 1
            else:
                groups["google_complete_different"] += 1
        elif any(google_group):
            groups["google_partial"] += 1
        elif any(pqm_group):
            groups["google_blank_pqm_present_preserved"] += 1
        else:
            groups["both_blank"] += 1
        if code == TARGET:
            alternate = []
            if not p and code.isdigit():
                alternate = [row[0] for row in con.execute(
                    "SELECT supplier_code FROM supplier_edr_profiles WHERE DIGITS(supplier_code)=? "
                    "AND supplier_code<>? LIMIT 2", (code, code))]
            link_kind = ("literal" if p else "digit_only_unlinked" if len(alternate) == 1 else
                         "ambiguous_digit_profiles" if len(alternate) > 1 else "missing_profile")
            target = {"identity_match": True, "profile_found": bool(p),
                      "profile_link_kind": link_kind,
                      "google_g_present": bool(values["g"][0]),
                      "google_j": values["j"][0],
                      "google_k_present": bool(values["k"][0]),
                      "google_m_present": bool(values["m"][0]),
                      "expected_block_matches_pqm": google_group == pqm_group,
                      "pqm_g_present": bool(values["g"][1]), "pqm_j": values["j"][1],
                      "pqm_k_present": bool(values["k"][1]),
                      "pqm_m_present": bool(values["m"][1]),
                      "termination_ui_projection_present": any(pqm_group),
                      "ui_blank_reason": ("no_literal_profile" if not p else
                                          "profile_termination_fields_blank" if not any(pqm_group) else
                                          "ui_not_blank_from_profile")}
    field_keys = ("google_only", "pqm_only", "exact", "different", "both_blank")
    group_keys = ("google_complete_pqm_missing", "google_complete_exact",
                  "google_complete_different", "google_complete_pqm_partial",
                  "google_partial", "google_blank_pqm_present_preserved", "both_blank")
    return {"dry_run": True, "db_writes": 0, "google_writes": 0, "query_only": 1,
            "received": len(rows), "compared": sum(field_counts["g"].values()),
            "fields": {key: {**{bucket: value[bucket] for bucket in field_keys},
                             "google_present": value["google_only"] + value["exact"] + value["different"],
                             "pqm_present": value["pqm_only"] + value["exact"] + value["different"],
                             "google_present_pqm_missing": value["google_only"],
                             "different_nonblank": value["different"],
                             "google_blank_pqm_present": value["pqm_only"]}
                       for key, value in field_counts.items()},
            "termination_group": {key: groups[key] for key in group_keys},
            "issues": dict(issues), "ambiguous_identities": issues["ambiguous_profile"] +
                      issues["routing_mismatch"],
            "missing_pqm_identities": issues["missing_pqm_identity"],
            "errors": issues["invalid_date"] + issues["formula_evidence"],
            "target_2791715838": target,
            "ownership": "google_nonblank_authoritative_blank_preserve"}
