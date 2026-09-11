"""Read-only full historical supplier registry for external integrations."""
from datetime import datetime, timezone

import supplier_activity


ENTITY_TYPES = {
    "individual_entrepreneur",
    "legal_entity",
    "foreign_legal_entity",
    "unknown",
}


def full_registry(con):
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
    profiles = {str(row["supplier_code"] or "").strip(): dict(row) for row in con.execute(
        "SELECT supplier_code,manager_name,source_sheet FROM supplier_edr_profiles")}
    managers = {}
    for row in con.execute("""SELECT supplier_code,manager_name FROM supplier_managers
      WHERE is_current=1 ORDER BY COALESCE(NULLIF(updated_at,''),created_at) DESC,id DESC"""):
        managers.setdefault(str(row["supplier_code"] or "").strip(), str(row["manager_name"] or "").strip())
    activity = {str(row["supplier_code"] or "").strip(): bool(row["is_active"])
      for row in con.execute(f"""SELECT rc.supplier_code,
        MAX(CASE WHEN {active} THEN 1 ELSE 0 END) is_active
        FROM registry_contracts rc LEFT JOIN frameworks f ON f.id=rc.framework_id
        WHERE TRIM(COALESCE(rc.supplier_code,''))<>'' GROUP BY rc.supplier_code""")}
    items = []
    for code in sorted(latest):
        application = latest[code]; acceptance = approved.get(code); profile = profiles.get(code, {})
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
        supplier_name = str(summaries.get(code, {}).get("supplier_name") or application.get("supplier_name") or "").strip()
        current_manager = (managers.get(code) or str(profile.get("manager_name") or "").strip()
          or str(application.get("application_manager_name") or "").strip())
        if not current_manager and entity_type == "individual_entrepreneur":
            current_manager = str(application.get("supplier_name") or "").strip()
        items.append({
            "supplier_code": code,
            "entity_type": entity_type,
            "supplier_name": supplier_name,
            "current_manager_name": current_manager,
            "prozorro_status": "🟢 Активний" if activity.get(code) else "🔴 Неактивний",
            "last_application_date": str(application.get("date_published") or "")[:10] or None,
            "last_approved_application_date": str(acceptance.get("date_published") or "")[:10] if acceptance else None,
            "last_approved_application_uo": (str(acceptance.get("protocol_officer") or "").strip()
              if acceptance else "") or "НЕ ВИЗНАЧЕНО",
        })
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(items),
        "items": items,
    }
