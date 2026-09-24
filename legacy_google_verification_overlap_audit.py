"""SANDBOX-only paired Google B/I/L versus legacy verification ledger audit."""
from collections import Counter, defaultdict
import hashlib
import json

import edr_sync_v2
import legacy_google_verification_preview as verification
import supplier_registry_integration


PATH = "/api/integrations/google/verification-events/overlap-audit"
MAX_ROWS = 20000
IDENTITY_KEYS = frozenset({"supplier_code", "source_tab", "source_row"})
PAIR_KEYS = IDENTITY_KEYS | {"verification_date", "verification_officer"}


def source_digest(identities, records):
    raw = json.dumps({"identities": [[x["supplier_code"], x["source_tab"], x["source_row"]]
                                   for x in identities],
                      "records": [[x["supplier_code"], x["source_tab"], x["source_row"],
                                   x["verification_date"], x["verification_officer"]]
                                  for x in records]}, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _identity_valid(item):
    return (isinstance(item, dict) and set(item) == IDENTITY_KEYS and
            isinstance(item["supplier_code"], str) and bool(item["supplier_code"]) and
            item["supplier_code"] == item["supplier_code"].strip() and
            item["source_tab"] in {"ФОП", "ЮО"} and
            type(item["source_row"]) is int and item["source_row"] >= 2)


def validate(payload):
    if not isinstance(payload, dict) or set(payload) != {
            "spreadsheet_id", "source_digest", "identities", "records"}:
        raise ValueError("OVERLAP_SCHEMA_INVALID")
    if payload["spreadsheet_id"] != verification.SANDBOX_SPREADSHEET_ID:
        raise ValueError("SANDBOX_SPREADSHEET_MISMATCH")
    identities, records = payload["identities"], payload["records"]
    if (not isinstance(identities, list) or not 1 <= len(identities) <= MAX_ROWS or
            not isinstance(records, list) or len(records) > MAX_ROWS):
        raise ValueError("OVERLAP_SIZE_INVALID")
    if any(not _identity_valid(item) for item in identities):
        raise ValueError("OVERLAP_IDENTITY_INVALID")
    if any(not isinstance(item, dict) or set(item) != PAIR_KEYS or
           not _identity_valid({key: item[key] for key in IDENTITY_KEYS}) or
           not verification._iso_date(item["verification_date"]) or
           not verification._officer(item["verification_officer"]) for item in records):
        raise ValueError("OVERLAP_PAIR_INVALID")
    def order(item):
        return item["source_tab"], item["source_row"], item["supplier_code"]
    if identities != sorted(identities, key=order) or records != sorted(records, key=order):
        raise ValueError("OVERLAP_ORDER_INVALID")
    identity_rows = {(item["source_tab"], item["source_row"], item["supplier_code"])
                     for item in identities}
    if any((item["source_tab"], item["source_row"], item["supplier_code"]) not in identity_rows
           for item in records):
        raise ValueError("OVERLAP_PAIR_WITHOUT_IDENTITY")
    if payload["source_digest"] != source_digest(identities, records):
        raise ValueError("OVERLAP_DIGEST_MISMATCH")
    return identities, records


def audit(con, payload):
    identities, records = validate(payload)
    if con.execute("PRAGMA query_only").fetchone()[0] != 1:
        raise ValueError("QUERY_ONLY_REQUIRED")
    by_code, pair_by_row = defaultdict(list), defaultdict(list)
    for item in identities:
        by_code[item["supplier_code"]].append(item)
    for item in records:
        pair_by_row[(item["source_tab"], item["source_row"], item["supplier_code"])].append(item)
    counts = Counter(google_supplier_rows=len(identities), google_valid_date_officer=len(records))
    counts["ambiguous_google_identities"] = sum(len(rows) for rows in by_code.values() if len(rows) > 1)
    legacy = [dict(row) for row in con.execute(
        "SELECT supplier_code,event_type,occurred_at,officer,source_sheet,source_row,snapshot_json "
        "FROM supplier_edr_verification_events WHERE event_type=?", (verification.SOURCE,))]
    counts["legacy_event_total"] = len(legacy)
    ledger_pairs = Counter((row["supplier_code"], edr_sync_v2.normalized_date(row["occurred_at"]),
                            edr_sync_v2.normalize_person(row["officer"])) for row in legacy)
    counts["duplicate_legacy_event_pairs"] = sum(count - 1 for count in ledger_pairs.values()
                                                   if count > 1)
    registry = supplier_registry_integration._build_full_registry(con)
    projection = defaultdict(list)
    for item in registry["items"]:
        projection[str(item["supplier_code"])].append(item)
    for event in legacy:
        try:
            snapshot = json.loads(event["snapshot_json"] or "{}")
        except (TypeError, ValueError):
            snapshot = None
        if not isinstance(snapshot, dict):
            counts["malformed_legacy_snapshots"] += 1
        kind = "factual" if isinstance(snapshot, dict) and str(
            snapshot.get("factual_edr_status") or "").strip() else "il_only"
        counts["legacy_" + kind] += 1
        matches = by_code.get(event["supplier_code"], [])
        if not matches:
            counts["legacy_google_identity_missing"] += 1
            continue
        if len(matches) != 1:
            counts["legacy_ambiguous_google_identity"] += 1
            continue
        identity = matches[0]
        if identity["source_tab"] != event["source_sheet"]:
            counts["legacy_routing_changed"] += 1
            continue
        pairs = pair_by_row.get((identity["source_tab"], identity["source_row"],
                                event["supplier_code"]), [])
        if not pairs:
            counts["legacy_google_pair_missing"] += 1
            continue
        if len(pairs) != 1:
            counts["legacy_ambiguous_google_pair"] += 1
            continue
        pair = pairs[0]
        if not verification.equivalent_event([event], pair["verification_date"],
                                             pair["verification_officer"]):
            counts["legacy_google_pair_changed"] += 1
            continue
        counts["existing_exact_legacy_total"] += 1
        counts["existing_exact_" + kind] += 1
        projected = projection.get(event["supplier_code"], [])
        if len(projected) != 1:
            counts["exact_legacy_ambiguous_pqm_identity"] += 1
            continue
        current_raw = projected[0].get("verification_date") or ""
        current_day = edr_sync_v2.normalized_date(current_raw)
        if not current_day or pair["verification_date"] > current_day:
            counts["erroneous_phase1_candidates"] += 1
        category = verification.classify_evidence(current_raw,
                   pair["verification_date"], pair["verification_officer"], [event])
        counts["exact_legacy_classifier_" + category] += 1
        if category in {"incoming_newer", "initial"}:
            counts["backend_erroneous_phase1_candidates"] += 1
    for key in ("legacy_factual", "legacy_il_only", "legacy_google_identity_missing",
                "legacy_ambiguous_google_identity", "legacy_routing_changed",
                "legacy_google_pair_missing", "legacy_ambiguous_google_pair",
                "legacy_google_pair_changed",
                "existing_exact_legacy_total", "existing_exact_factual", "existing_exact_il_only",
                "exact_legacy_ambiguous_pqm_identity", "exact_legacy_classifier_equivalent_event",
                "erroneous_phase1_candidates", "backend_erroneous_phase1_candidates",
                "duplicate_legacy_event_pairs",
                "malformed_legacy_snapshots"):
        counts[key] += 0
    accounted = sum(counts[key] for key in (
        "legacy_google_identity_missing", "legacy_ambiguous_google_identity",
        "legacy_routing_changed", "legacy_google_pair_missing", "legacy_ambiguous_google_pair",
        "legacy_google_pair_changed", "existing_exact_legacy_total"))
    if accounted != counts["legacy_event_total"]:
        raise ValueError("OVERLAP_ACCOUNTING_FAILED")
    counts["changed_current_google_pair"] = counts["legacy_google_pair_changed"]
    counts["missing_google_pair"] = (counts["legacy_google_pair_missing"] +
                                     counts["legacy_google_identity_missing"])
    counts["ambiguous_identity"] = (counts["ambiguous_google_identities"] +
                                    counts["exact_legacy_ambiguous_pqm_identity"] +
                                    counts["legacy_ambiguous_google_pair"])
    return {"dry_run": True, "db_writes": 0, "google_writes": 0, "query_only": 1,
            "source_digest": payload["source_digest"], "counts": dict(counts),
            "acceptance_passed": counts["erroneous_phase1_candidates"] == 0 and
            counts["backend_erroneous_phase1_candidates"] == 0 and
            counts["ambiguous_identity"] == 0 and
            counts["duplicate_legacy_event_pairs"] == 0 and
            counts["malformed_legacy_snapshots"] == 0 and
            counts["exact_legacy_classifier_equivalent_event"] == counts["existing_exact_legacy_total"]}
