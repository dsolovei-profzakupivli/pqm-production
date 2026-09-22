"""Read-only full historical supplier registry for external integrations."""
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import threading

import supplier_activity
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
    """Set-based equivalent of supplier_identity.current_name for each code."""
    normalized = {_identity_code(code) for code in supplier_codes if _identity_code(code)}
    names = {}
    if "full_name" in profile_columns:
        for batch in _chunks(normalized):
            placeholders = ",".join("?" for _ in batch)
            for row in con.execute(f"""SELECT supplier_code,NULLIF(TRIM(full_name),'') full_name
              FROM supplier_edr_profiles WHERE supplier_code IN ({placeholders})""", batch):
                if row["full_name"]:
                    names[_identity_code(row["supplier_code"])] = row["full_name"]
    missing = normalized - set(names)
    for batch in _chunks(missing):
        placeholders = ",".join("?" for _ in batch)
        for row in con.execute(f"""SELECT supplier_code,supplier_name FROM (
          SELECT supplier_code,NULLIF(TRIM(supplier_name),'') supplier_name,
            ROW_NUMBER() OVER (PARTITION BY supplier_code ORDER BY
              CASE WHEN julianday(NULLIF(date_published,'')) IS NULL THEN 1 ELSE 0 END,
              julianday(NULLIF(date_published,'')) DESC,id DESC) row_number
          FROM submissions WHERE supplier_code IN ({placeholders})
            AND TRIM(COALESCE(supplier_name,''))<>'') WHERE row_number=1""", batch):
            if row["supplier_name"]:
                names[_identity_code(row["supplier_code"])] = row["supplier_name"]
    return {str(code).strip(): names.get(_identity_code(code)) for code in supplier_codes}


def _current_verification_events(con, supplier_codes):
    """Set-based equivalent of edr_sync_v2.current_verification_event."""
    codes = {edr_sync_v2.normalize_code(code) for code in supplier_codes if edr_sync_v2.normalize_code(code)}
    candidates = {code: [] for code in codes}
    if edr_sync_v2._table_exists(con, "supplier_edr_verification_events"):
        for batch in _chunks(codes):
            placeholders = ",".join("?" for _ in batch)
            for row in con.execute(f"SELECT * FROM supplier_edr_verification_events WHERE supplier_code IN ({placeholders})", batch):
                item = dict(row)
                code = edr_sync_v2.normalize_code(item.get("supplier_code"))
                if code in candidates:
                    candidates[code].append(item)
    if edr_sync_v2._table_exists(con, "supplier_edr_profiles"):
        for batch in _chunks(codes):
            placeholders = ",".join("?" for _ in batch)
            for row in con.execute(f"""SELECT supplier_code,edr_checked_at,edr_officer,source_sheet,source_row,synced_at
              FROM supplier_edr_profiles WHERE supplier_code IN ({placeholders})""", batch):
                code = edr_sync_v2.normalize_code(row["supplier_code"])
                occurred = edr_sync_v2.normalized_date(row["edr_checked_at"])
                if code in candidates and occurred:
                    candidates[code].append({"supplier_code": code, "event_type": "google_clarity_profile",
                      "occurred_at": occurred, "officer": row["edr_officer"] or "",
                      "source": "Google/Clarity profile snapshot", "source_submission_id": "",
                      "source_sheet": row["source_sheet"] or "", "source_row": int(row["source_row"] or 0),
                      "created_at": row["synced_at"] or ""})
    application_columns = edr_sync_v2._columns(con, "application_fields")
    if edr_sync_v2._table_exists(con, "submissions") and "protocol_decision" in application_columns:
        submission_columns = edr_sync_v2._columns(con, "submissions")
        qualification_link = "qualification_id" in submission_columns and edr_sync_v2._table_exists(con, "qualifications")
        qualification_date = ("NULLIF(q.decision_date,'')" if qualification_link and
                              "decision_date" in edr_sync_v2._columns(con, "qualifications") else "NULL")
        qualification_join = "LEFT JOIN qualifications q ON q.id=s.qualification_id" if qualification_link else ""
        for batch in _chunks(codes):
            placeholders = ",".join("?" for _ in batch)
            for row in con.execute(f"""SELECT s.id source_submission_id,
              COALESCE(NULLIF(af.protocol_date,''),{qualification_date},NULLIF(s.date_published,'')) occurred_at,
              COALESCE(NULLIF(af.protocol_officer,''),'') officer, s.supplier_code
              FROM submissions s JOIN application_fields af ON af.submission_id=s.id
              {qualification_join}
              WHERE DIGITS(s.supplier_code) IN ({placeholders}) AND af.protocol_decision='admit'""", batch):
                code = edr_sync_v2.normalize_code(row["supplier_code"])
                occurred = edr_sync_v2.normalized_date(row["occurred_at"])
                if code in candidates and occurred:
                    candidates[code].append({"supplier_code": code, "event_type": "admission",
                      "occurred_at": occurred, "officer": row["officer"] or "", "source": "PQM application",
                      "source_submission_id": row["source_submission_id"], "source_sheet": "", "source_row": 0})
    return {str(code).strip(): (max(candidates.get(edr_sync_v2.normalize_code(code), []),
      key=edr_sync_v2._verification_event_sort_key) if candidates.get(edr_sync_v2.normalize_code(code)) else None)
      for code in supplier_codes}


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
    active = supplier_activity.effective_active_sql("rc", "f")
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
    profiles = {str(row["supplier_code"] or "").strip(): dict(row) for row in con.execute(
        f"SELECT supplier_code,manager_name,source_sheet,{full_name_expr} FROM supplier_edr_profiles")}
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
    activity = {str(row["supplier_code"] or "").strip(): bool(row["is_active"])
      for row in con.execute(f"""SELECT rc.supplier_code,
        MAX(CASE WHEN {active} THEN 1 ELSE 0 END) is_active
        FROM registry_contracts rc LEFT JOIN frameworks f ON f.id=rc.framework_id
        WHERE TRIM(COALESCE(rc.supplier_code,''))<>'' GROUP BY rc.supplier_code""")}
    statuses = edr_sync_v2.prozorro_statuses(con)
    monitoring_codes = edr_sync_v2.monitoring_population_codes(con)
    names = _current_names(con, latest, profile_columns)
    verifications = _current_verification_events(con, latest)
    items = []
    for code in sorted(latest):
        application = latest[code]; acceptance = approved.get(code); profile = linked_profiles.get(code, {})
        canonical_status = statuses.get(code)
        if not canonical_status:
            canonical_status = "Активний" if activity.get(code) else "Неактивний"
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
        verification = verifications.get(code)
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
            "monitoring_eligible": code in monitoring_codes,
            "freshness_marker": edr_sync_v2.marker_for_status(
                canonical_status, (verification or {}).get("occurred_at", "")),
            "last_application_date": str(application.get("date_published") or "")[:10] or None,
            "last_approved_application_date": str(acceptance.get("date_published") or "")[:10] if acceptance else None,
            "last_approved_application_uo": (str(acceptance.get("protocol_officer") or "").strip()
              if acceptance else "") or "НЕ ВИЗНАЧЕНО",
            "verification_date": verification.get("occurred_at") if verification else None,
            "verification_officer": verification.get("officer") if verification else "",
            "verification_event_type": verification.get("event_type") if verification else None,
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
