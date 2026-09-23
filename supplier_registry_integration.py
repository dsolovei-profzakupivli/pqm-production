"""Read-only full historical supplier registry for external integrations."""
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import threading

import edr_sync_v2


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
    return re.sub(r"\D", "", str(value or ""))


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
    return {str(code).strip(): names.get(_identity_code(code)) for code in supplier_codes}


def _current_verification_events(con, supplier_codes):
    """Compatibility wrapper; selection is shared with EDR monitoring."""
    projected = edr_sync_v2.current_verification_projections(con, supplier_codes)
    return {code: item["selected_event"] or None for code, item in projected.items()}


def _factual_edr_events(con, supplier_codes):
    """Read the same persisted factual checks used by the EDR monitoring UI."""
    events = {}
    if not edr_sync_v2._table_exists(con, "supplier_edr_verification_events"):
        return events
    for batch in _chunks(supplier_codes):
        placeholders = ",".join("?" for _ in batch)
        for row in con.execute(f"""SELECT id,supplier_code,event_type,occurred_at,snapshot_json
          FROM supplier_edr_verification_events WHERE supplier_code IN ({placeholders})
          AND event_type IN ('manual_edr','google_clarity')""", batch):
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
    for raw in con.execute("""SELECT s.id,s.supplier_code,s.supplier_name,s.date_published,s.synced_at,
      NULLIF(TRIM(json_extract(s.raw_json,'$.tenderers[0].identifier.scheme')),'') identifier_scheme,
      NULLIF(TRIM(af.manager_name),'') application_manager_name,
      NULLIF(TRIM(af.protocol_officer),'') protocol_officer
        FROM submissions s LEFT JOIN application_fields af ON af.submission_id=s.id
      WHERE TRIM(COALESCE(s.supplier_code,''))<>''
        AND s.id=(SELECT sx.id FROM submissions sx WHERE sx.supplier_code=s.supplier_code
          ORDER BY sx.date_published DESC,sx.id DESC LIMIT 1)"""):
        row = dict(raw); code = str(row["supplier_code"] or "").strip()
        prior = latest.get(code)
        row_key = (str(row.get("date_published") or row.get("synced_at") or ""), str(row.get("id") or ""))
        prior_key = ((str(prior.get("date_published") or prior.get("synced_at") or ""), str(prior.get("id") or ""))
                     if prior else ("", ""))
        if row_key > prior_key:
            latest[code] = row
    for raw in con.execute("""SELECT s.id,s.supplier_code,s.date_published,
      NULLIF(TRIM(af.protocol_officer),'') protocol_officer
      FROM qualifications q JOIN submissions s ON s.id=q.submission_id
      LEFT JOIN application_fields af ON af.submission_id=s.id
      WHERE q.status='active' AND q.submission_id<>''
      ORDER BY s.date_published DESC,s.id DESC"""):
        row = dict(raw); code = str(row["supplier_code"] or "").strip()
        approved.setdefault(code, row)
    summaries = {str(row["supplier_code"] or "").strip(): dict(row) for row in con.execute(
        "SELECT supplier_code,supplier_name FROM supplier_registry_summary")}
    profile_columns = {row[1] for row in con.execute("PRAGMA table_info(supplier_edr_profiles)")}
    full_name_expr = "full_name" if "full_name" in profile_columns else "'' full_name"
    edr_status_expr = "edr_status" if "edr_status" in profile_columns else "'' edr_status"
    profiles = {str(row["supplier_code"] or "").strip(): dict(row) for row in con.execute(
        f"SELECT supplier_code,manager_name,source_sheet,{edr_status_expr},{full_name_expr} FROM supplier_edr_profiles")}
    # Profile codes may have lost passport characters while submissions retain
    # their literal representation.  Link only an unambiguous domestic pair;
    # literal identity always wins and foreign schemes can never use this path.
    profile_by_digits = {}
    for profile_code in profiles:
        digits = _identity_code(profile_code)
        if digits:
            profile_by_digits.setdefault(digits, []).append(profile_code)
    submission_by_digits = {}
    for submission_code, application in latest.items():
        digits = _identity_code(submission_code)
        scheme = str(application.get("identifier_scheme") or "").strip().upper()
        if digits and (not scheme or scheme in {"UA-EDR", "UA-IPN"}):
            submission_by_digits.setdefault(digits, []).append(submission_code)
    linked_profiles = {}
    for submission_code in latest:
        if submission_code in profiles:
            linked_profiles[submission_code] = profiles[submission_code]
            continue
        digits = _identity_code(submission_code)
        candidates = profile_by_digits.get(digits, []) if digits else []
        submission_candidates = submission_by_digits.get(digits, []) if digits else []
        if len(candidates) == 1 and len(submission_candidates) == 1:
            linked_profiles[submission_code] = profiles[candidates[0]]
    managers = {}
    for row in con.execute("""SELECT supplier_code,manager_name FROM supplier_managers
      WHERE is_current=1 ORDER BY COALESCE(NULLIF(updated_at,''),created_at) DESC,id DESC"""):
        managers.setdefault(str(row["supplier_code"] or "").strip(), str(row["manager_name"] or "").strip())
    statuses = edr_sync_v2.canonical_prozorro_statuses(con, latest)
    monitoring_codes = edr_sync_v2.monitoring_population_codes(con)
    names = _current_names(con, latest, profile_columns)
    verifications = edr_sync_v2.current_verification_projections(con, latest)
    qualification_dates = edr_sync_v2.active_qualification_dates(con)
    factual_edr_events = _factual_edr_events(con, latest)
    items = []
    for code in sorted(latest):
        application = latest[code]; acceptance = approved.get(code); profile = linked_profiles.get(code, {})
        canonical_status = statuses[code]
        scheme = str(application.get("identifier_scheme") or "").strip().upper()
        source = str(profile.get("source_sheet") or "").strip().upper()
        if scheme and scheme not in {"UA-EDR", "UA-IPN"}:
            entity_type = "foreign_legal_entity"
        elif source == "ФОП":
            entity_type = "individual_entrepreneur"
        elif source == "ЮО":
            entity_type = "legal_entity"
        elif scheme == "UA-IPN":
            entity_type = "individual_entrepreneur"
        else:
            entity_type = "unknown"
        supplier_name = names.get(code) or ""
        current_manager = (managers.get(code) or str(profile.get("manager_name") or "").strip()
          or str(application.get("application_manager_name") or "").strip())
        verification = verifications[code]
        if not current_manager and entity_type == "individual_entrepreneur":
            current_manager = str(application.get("supplier_name") or "").strip()
        items.append({
            "supplier_code": code,
            "entity_type": entity_type,
            "supplier_name": supplier_name,
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
            "freshness_marker": edr_sync_v2.marker_for_status(
                canonical_status, verification["verification_date"]),
            "last_application_date": str(application.get("date_published") or "")[:10] or None,
            "last_approved_application_date": str(acceptance.get("date_published") or "")[:10] if acceptance else None,
            "last_approved_application_uo": (str(acceptance.get("protocol_officer") or "").strip()
              if acceptance else "") or "НЕ ВИЗНАЧЕНО",
            "verification_date": verification["verification_date"],
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
