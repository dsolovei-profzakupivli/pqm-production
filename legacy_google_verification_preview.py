"""SANDBOX-only read model for Google-initiated verification evidence Preview.

No Google client, mutation, or Apply path exists in this module.
"""
from collections import Counter
from datetime import date
import hashlib
import json
import re
import sqlite3
import urllib.parse

import edr_sync_v2
import supplier_registry_integration


SANDBOX_SPREADSHEET_ID = "1lZtneKmCTvFcEL0erlJbegVzTTLNA-IKnjempn1G8Ww"
SOURCE = "legacy_google_registry"
SOURCES = frozenset({SOURCE, "google_registry"})
PATH = "/api/integrations/google/verification-events/preview"
ITEM_KEYS = frozenset({"supplier_code", "verification_date", "verification_officer",
                       "source_tab", "source_row", "source"})
REQUEST_KEYS = frozenset({"spreadsheet_id", "source_digest", "records"})
INVALID_OFFICER = {"-", "—", "не визначено", "не призначено", "невідомо", "n/a", "null"}


def source_digest(items):
    rows = [[x["supplier_code"], x["source_tab"], x["source_row"],
             x["verification_date"], x["verification_officer"], x["source"]]
            for x in items]
    raw = json.dumps(rows, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


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
    for row in con.execute("SELECT supplier_code,occurred_at,officer FROM "
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
    return {"dry_run": True, "received": len(items), "source_digest": payload["source_digest"],
            "incoming_newer": counts["incoming_newer"], "initial": counts["initial"],
            "same_date": counts["same_date"], "older": counts["older"],
            "equivalent_event": counts["equivalent_event"],
            "ambiguous": counts["ambiguous_identity"],
            "blocked": sum(counts.values()) - counts["incoming_newer"] - counts["initial"] -
                       counts["same_date"] - counts["older"] - counts["equivalent_event"],
            "by_reason": dict(counts), "rows": results, "google_writes": 0, "db_writes": 0}
