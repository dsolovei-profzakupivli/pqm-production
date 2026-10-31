"""Read-only full historical supplier registry for external integrations."""
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import threading

import edr_sync_v2
import supplier_classification


ENTITY_TYPES = {
    "individual_entrepreneur",
    "legal_entity",
    "foreign_legal_entity",
    "unknown",
}


_CACHE_LOCK = threading.Lock()
_FULL_REGISTRY_CACHE = {"revision": None, "payload": None}
_BATCH_SIZE = 500


def _chunks(values):
    values = list(values)
    for index in range(0, len(values), _BATCH_SIZE):
        yield values[index:index + _BATCH_SIZE]


def _identity_code(value):
    return str(value or "")


def _current_names(con, supplier_codes, profile_columns):
    """Verified EDR full names only; never promote an application-name fallback."""
    normalized = {_identity_code(code) for code in supplier_codes if _identity_code(code)}
    names = {}
    if "full_name" in profile_columns:
        for batch in _chunks(normalized):
            placeholders = ",".join("?" for _ in batch)
            for row in con.execute(f"""SELECT supplier_code,NULLIF(TRIM(full_name),'') full_name
              FROM supplier_edr_profiles WHERE supplier_code IN ({placeholders})""", batch):
                if row["full_name"]:
                    names[_identity_code(row["supplier_code"])] = row["full_name"]
    return {str(code): names.get(_identity_code(code)) for code in supplier_codes}


def _current_verification_events(con, supplier_codes):
    """Compatibility wrapper; selection is shared with EDR monitoring."""
    projected = edr_sync_v2.current_verification_projections(con, supplier_codes)
    return {code: item["selected_event"] or None for code, item in projected.items()}


def _factual_edr_events(con, supplier_codes):
    """Read the same persisted factual checks used by the EDR monitoring UI."""
    events = {}
    if not edr_sync_v2._table_exists(con, "supplier_edr_verification_events"):
        return events
    columns = edr_sync_v2._columns(con, "supplier_edr_verification_events")
    provenance_fields = ",".join(
        name if name in columns else f"NULL AS {name}"
        for name in ("officer", "source", "source_sheet", "source_row", "snapshot_json")
    )
    for batch in _chunks(supplier_codes):
        placeholders = ",".join("?" for _ in batch)
        for row in con.execute(f"""SELECT id,supplier_code,event_type,occurred_at,{provenance_fields}
          FROM supplier_edr_verification_events WHERE supplier_code IN ({placeholders})
          AND event_type IN ('manual_edr','google_clarity','legacy_google_registry')""", batch):
            item = dict(row)
            events.setdefault(item["supplier_code"], []).append(item)
    return events


def _file_revision(path):
    try:
        stat = path.stat()
        return (stat.st_ino, stat.st_size, stat.st_mtime_ns)
    except FileNotFoundError:
        return None


def database_revision(con):
    """Revision key covers SQLite main DB and its WAL without writing either file."""
    main = next((row[2] for row in con.execute("PRAGMA database_list") if row[1] == "main"), "")
    if not main:
        return None
    path = Path(main)
    return (str(path.resolve()), _file_revision(path), _file_revision(Path(str(path) + "-wal")))


def reset_full_registry_cache():
    with _CACHE_LOCK:
        _FULL_REGISTRY_CACHE.update(revision=None, payload=None)


def _build_full_registry(con):
    """One stable scalar row per non-empty supplier identifier ever submitted."""
    latest = {}
    approved = {}
    decided = {}
    decided_names = {}
    for raw in con.execute("""SELECT s.id,s.supplier_code,s.supplier_name,s.date_published,s.synced_at,
      NULLIF(TRIM(json_extract(s.raw_json,'$.tenderers[0].identifier.scheme')),'') identifier_scheme,
      NULLIF(TRIM(af.manager_name),'') application_manager_name,
      NULLIF(TRIM(af.protocol_officer),'') protocol_officer
        FROM submissions s LEFT JOIN application_fields af ON af.submission_id=s.id
      WHERE TRIM(COALESCE(s.supplier_code,''))<>''
        AND s.id=(SELECT sx.id FROM submissions sx WHERE sx.supplier_code=s.supplier_code
          ORDER BY sx.date_published DESC,sx.id DESC LIMIT 1)"""):
        row = dict(raw); code = str(row["supplier_code"] or "")
        prior = latest.get(code)
        row_key = (str(row.get("date_published") or row.get("synced_at") or ""), str(row.get("id") or ""))
        prior_key = ((str(prior.get("date_published") or prior.get("synced_at") or ""), str(prior.get("id") or ""))
                     if prior else ("", ""))
        if row_key > prior_key:
            latest[code] = row
    for raw in con.execute("""SELECT s.id,s.supplier_code,s.date_published,
      NULLIF(TRIM(af.protocol_officer),'') protocol_officer
      FROM qualifications q JOIN submissions s ON q.id=s.qualification_id
      LEFT JOIN application_fields af ON af.submission_id=s.id
      WHERE q.status='active'
      ORDER BY s.date_published DESC,s.id DESC"""):
        row = dict(raw); code = str(row["supplier_code"] or "")
        approved.setdefault(code, row)
    for raw in con.execute(edr_sync_v2.DECIDED_APPLICATIONS_SQL
                           + " ORDER BY s.date_published DESC,s.id DESC"):
        row = dict(raw); code = str(row["supplier_code"] or "")
        decided.setdefault(code, row)
    for row in con.execute("""SELECT s.supplier_code,s.supplier_name FROM submissions s
      JOIN qualifications q ON q.id=s.qualification_id
      WHERE q.status IN ('active','unsuccessful')
      ORDER BY s.date_published DESC,s.id DESC"""):
        decided_names.setdefault(str(row["supplier_code"] or ""), str(row["supplier_name"] or "").strip())
    # Decision provenance is separate from the latest submission and current
    # qualification aggregate. The Google writer needs it to distinguish a
    # first rejection from a rejection after an admission.
    latest_decisions = {}
    admission_history = set()
    last_rejection_officers = {}
    submission_columns = {row[1] for row in con.execute("PRAGMA table_info(submissions)")}
    qualification_columns = {row[1] for row in con.execute("PRAGMA table_info(qualifications)")}
    application_columns = {row[1] for row in con.execute("PRAGMA table_info(application_fields)")}
    decision_date_expr = "NULLIF(q.decision_date,'')" if "decision_date" in qualification_columns else "NULL"
    protocol_date_expr = "NULLIF(af.protocol_date,'')" if "protocol_date" in application_columns else "NULL"
    protocol_decision_expr = "LOWER(TRIM(COALESCE(af.protocol_decision,'')))" if "protocol_decision" in application_columns else "''"
    protocol_officer_expr = "NULLIF(TRIM(af.protocol_officer),'')" if "protocol_officer" in application_columns else "NULL"
    decided_link = "q.id=s.qualification_id" if "qualification_id" in submission_columns else "q.submission_id=s.id"
    for raw in con.execute(f"""SELECT s.supplier_code,s.id,s.date_published,q.status,
      {protocol_decision_expr} protocol_decision,{decision_date_expr} qualification_decision_date,
      {protocol_date_expr} protocol_date,{protocol_officer_expr} protocol_officer
      FROM submissions s JOIN qualifications q ON {decided_link}
      LEFT JOIN application_fields af ON af.submission_id=s.id
      WHERE TRIM(COALESCE(s.supplier_code,''))<>''
      ORDER BY COALESCE(NULLIF(s.date_published,''),'') DESC,s.id DESC"""):
        event = dict(raw)
        code = str(event.get("supplier_code") or "")
        if not code:
            continue
        raw_decision = str(event.get("protocol_decision") or "").lower()
        decision = ("" if event.get("status") == "pending" else
                    "admit" if event.get("status") == "active" else
                    "reject" if event.get("status") == "unsuccessful" else
                    raw_decision if raw_decision in {"admit", "reject"} else "")
        if not decision:
            continue
        event_at = event.get("protocol_date") or event.get("qualification_decision_date") or ""
        projected = {
            "decision": decision,
            "application_date": str(event.get("date_published") or "")[:10] or None,
            "protocol_at": str(event_at or ""),
            "officer": str(event.get("protocol_officer") or "").strip(),
            "submission_id": str(event.get("id") or ""),
        }
        latest_decisions.setdefault(code, projected)
        if decision == "admit":
            admission_history.add(code)
        elif code not in last_rejection_officers:
            last_rejection_officers[code] = projected["officer"]
    summaries = {str(row["supplier_code"] or ""): dict(row) for row in con.execute(
        "SELECT supplier_code,supplier_name FROM supplier_registry_summary")}
    profile_columns = {row[1] for row in con.execute("PRAGMA table_info(supplier_edr_profiles)")}
    full_name_expr = "full_name" if "full_name" in profile_columns else "'' full_name"
    edr_status_expr = "edr_status" if "edr_status" in profile_columns else "'' edr_status"
    profiles = {str(row["supplier_code"] or ""): dict(row) for row in con.execute(
        f"SELECT supplier_code,manager_name,source_sheet,{edr_status_expr},{full_name_expr} FROM supplier_edr_profiles")}
    linked_profiles = {code: profiles[code] for code in latest if code in profiles}
    supplier_types = supplier_classification.build_index(con)
    managers = {}
    for row in con.execute("""SELECT supplier_code,manager_name FROM supplier_managers
      WHERE is_current=1 ORDER BY COALESCE(NULLIF(updated_at,''),created_at) DESC,id DESC"""):
        managers.setdefault(str(row["supplier_code"] or ""), str(row["manager_name"] or "").strip())
    statuses = edr_sync_v2.canonical_prozorro_statuses(con, latest)
    google_statuses = {}
    eligibility_raw_codes = {}
    for raw_code, status in edr_sync_v2.monitoring_eligibility(con).items():
        code = str(raw_code)
        if code in eligibility_raw_codes and raw_code != eligibility_raw_codes[code]:
            raise ValueError(f"Ambiguous supplier code after outer whitespace strip: {code!r}")
        eligibility_raw_codes[code] = raw_code
        google_statuses[code] = status
    monitoring_codes = set(google_statuses)
    names = _current_names(con, latest, profile_columns)
    verifications = edr_sync_v2.current_verification_projections(con, latest)
    qualification_dates = edr_sync_v2.active_qualification_dates(con)
    factual_edr_events = _factual_edr_events(con, latest)
    items = []
    for code in sorted(latest):
        application = latest[code]; acceptance = approved.get(code); profile = linked_profiles.get(code, {})
        canonical_status = statuses[code]
        classification = supplier_classification.resolve(supplier_types, code)
        entity_type = classification["entity_type"]
        latest_decision = latest_decisions.get(code, {})
        supplier_name = names.get(code) or decided_names.get(code, "")
        current_manager = (managers.get(code) or str(profile.get("manager_name") or "").strip()
          or str(application.get("application_manager_name") or "").strip())
        verification = verifications[code]
        if not current_manager and entity_type == "individual_entrepreneur":
            current_manager = str(application.get("supplier_name") or "").strip()
        items.append({
            "supplier_code": code,
            **supplier_classification.public_fields(classification),
            "supplier_name": supplier_name,
            "latest_submission_name": decided_names.get(code, ""),
            "current_manager_name": current_manager,
            "prozorro_status": ({"Активний": "🟢 Активний", "Неактивний": "🔴 Неактивний",
              "Призупинений": "🟠 Призупинений", "Ще не в реєстрі": "Ще не в реєстрі"}
              [canonical_status]),
            "prozorro_status_canonical": canonical_status,
            "prozorro_status_google": edr_sync_v2.google_prozorro_presentation(canonical_status),
            "edr_status_current": edr_sync_v2.operational_edr_status(
                canonical_status, qualification_dates.get(code, ""),
                factual_edr_events.get(code, []), str(profile.get("edr_status") or "")),
            "monitoring_eligible": code in monitoring_codes,
            "google_sync_eligible": code in google_statuses,
            "google_writer_eligible": bool(latest_decision),
            "google_sync_has_active_qualification": code in qualification_dates,
            "google_sync_has_admission_history": code in admission_history,
            "freshness_marker": edr_sync_v2.marker_for_status(
                canonical_status, verification["verification_date"]),
            "last_application_date": str(decided.get(code, {}).get("date_published") or "")[:10] or None,
            "google_sync_last_decided_application_date": (
                latest_decision.get("application_date") or str(decided.get(code, {}).get("date_published") or "")[:10] or None),
            "google_sync_last_decided_application_decision": latest_decision.get("decision", ""),
            "google_sync_last_decided_protocol_at": latest_decision.get("protocol_at", ""),
            "google_sync_last_decided_protocol_officer": latest_decision.get("officer", ""),
            "google_sync_last_decided_submission_id": latest_decision.get("submission_id", ""),
            "google_sync_latest_rejection_officer": last_rejection_officers.get(code, ""),
            "last_approved_application_date": str(acceptance.get("date_published") or "")[:10] if acceptance else None,
            "last_approved_application_uo": (str(acceptance.get("protocol_officer") or "").strip()
              if acceptance else "") or "НЕ ВИЗНАЧЕНО",
            "verification_date": verification["verification_date"],
            "verification_datetime_precision": verification["verification_datetime_precision"],
            "signature_timestamp_available": verification["signature_timestamp_available"],
            "verification_officer": verification["verification_officer"],
            "verification_event_type": verification["verification_event_type"] or None,
        })
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(items),
        "items": items,
    }


def full_registry(con):
    """Return an immutable cached JSON snapshot while its SQLite revision is unchanged."""
    before = database_revision(con)
    if before is not None:
        with _CACHE_LOCK:
            if _FULL_REGISTRY_CACHE["revision"] == before:
                return json.loads(_FULL_REGISTRY_CACHE["payload"])
    result = _build_full_registry(con)
    payload = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
    after = database_revision(con)
    if before is not None and before == after:
        with _CACHE_LOCK:
            _FULL_REGISTRY_CACHE.update(revision=after, payload=payload)
    return json.loads(payload)


def eligible_full_registry(con):
    """Expose only the shared qualification-status population to Google."""
    result = full_registry(con)
    items = [item for item in result["items"] if item.get("google_writer_eligible")]
    return {"generated_at": result["generated_at"], "count": len(items), "items": items}
