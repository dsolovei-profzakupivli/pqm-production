# Immutable CSV implementation from Production 98c7f8a; test namespace only.

EDR_EXPORT_HEADERS = ['Код ЄДРПОУ', 'Стара Назва', 'Старий Статус', 'Старий ПІБ Керівника', 'Фактична дата перевірки ЄДР']

def build_supplier_edr_export_rows(sheet_type: str, today=None, filters: dict | None = None) -> list[dict]:
    """Build the exact five-column ClarityChecker input without changing source data."""
    sheet_type = str(sheet_type or "").strip().upper()
    if sheet_type not in {"ФОП", "ЮО", "ALL"}:
        raise ValueError("Оберіть тип експорту: ФОП, ЮО або ALL")
    today = today or datetime.now().astimezone().date()
    profiles, latest, managers, admitted_dates, active, supplier_codes = {}, {}, {}, {}, {}, set()
    canonical_states = {}
    registry_member_codes = set()
    with db() as con:
        for raw in con.execute("SELECT * FROM supplier_edr_profiles"):
            item = dict(raw); code = _digits(item.get("supplier_code")); supplier_codes.add(code); profiles[code] = item
        for raw in con.execute("""SELECT s.supplier_code,s.supplier_name,s.date_published,s.synced_at,s.id,
          COALESCE(af.manager_name,'') manager_name FROM submissions s
          LEFT JOIN application_fields af ON af.submission_id=s.id
          ORDER BY COALESCE(NULLIF(s.date_published,''),s.synced_at) DESC,s.id DESC"""):
            item = dict(raw); code = _digits(item.get("supplier_code"))
            if code:
                supplier_codes.add(code); latest.setdefault(code, item)
        managers = {code: item.get("manager_name", "")
                    for code, item in edr_sync_v2.known_manager_map(con).items()}
        for raw in con.execute("""SELECT s.supplier_code,q.status,
          COALESCE(NULLIF(q.decision_date,''),s.date_published) event_date
          FROM submissions s LEFT JOIN qualifications q ON q.id=s.qualification_id"""):
            code = _digits(raw["supplier_code"])
            if not code:
                continue
            active[code] = active.get(code, 0) + (1 if raw["status"] == "active" else 0)
            if raw["status"] == "active" and str(raw["event_date"] or "") > admitted_dates.get(code, ""):
                admitted_dates[code] = str(raw["event_date"] or "")
        for raw in con.execute("""SELECT rc.supplier_code,q.status,
          COALESCE(NULLIF(q.decision_date,''),NULLIF(json_extract(rc.raw_json,'$.dateModified'),''),
                   NULLIF(json_extract(rc.raw_json,'$.date'),''),rc.synced_at) event_date
          FROM registry_contracts rc LEFT JOIN qualifications q ON q.id=rc.qualification_id
          WHERE COALESCE(rc.supplier_code,'')<>''"""):
            code = _digits(raw["supplier_code"])
            if not code:
                continue
            registry_member_codes.add(code)
            if raw["status"] == "active" and str(raw["event_date"] or "") > admitted_dates.get(code, ""):
                admitted_dates[code] = str(raw["event_date"] or "")
        has_code_filter = "supplier_codes" in (filters or {})
        requested_codes = {_digits(code) for code in (filters or {}).get("supplier_codes", set()) if _digits(code)}
        export_codes = requested_codes if has_code_filter else registry_member_codes
        canonical_states = edr_sync_v2.canonical_supplier_edr_states(con, export_codes, today=today)
    rows = []
    # The export contract is authoritative historical register membership, not
    # the current active count and not the potentially stale
    # submissions.qualification_id pointer.  This is the same population source
    # as the supplier KPI: registry_contracts -> qualifications.
    for code in sorted(requested_codes if has_code_filter else registry_member_codes):
        profile, last = profiles.get(code, {}), latest.get(code, {})
        rows.append({"code": code, "full_name": profile.get("full_name", ""),
          "short_name": profile.get("short_name", ""), "edr_manager": profile.get("manager_name", ""),
          "edr_status": edr_sync_v2.compatible_edr_status(profile.get("edr_status", "")),
          "edr_checked_at": profile.get("edr_checked_at", ""),
          "source_sheet": profile.get("source_sheet", ""),
          "termination_decision_details": profile.get("termination_decision_details", ""),
          "edr_officer": profile.get("edr_officer", ""), "edr_notes": profile.get("edr_notes", ""),
          "latest_name": last.get("supplier_name", ""), "latest_manager": last.get("manager_name", ""),
          "current_manager": managers.get(code, ""), "last_admit": admitted_dates.get(code, ""),
          "active_count": active.get(code, 0)})
    result = []
    for row in rows:
        source_type = str(row["source_sheet"] or "").strip().upper()
        name = str(row["full_name"] or row["latest_name"] or "")
        inferred_fop = bool(re.search(r"\bФОП\b|ФІЗИЧНА\s+ОСОБА[\s-]*ПІДПРИЄМЕЦЬ", name, re.I))
        canonical_type = supplier_entity_type(row["code"])
        actual_type = source_type if source_type in {"ФОП", "ЮО"} else (
            "ФОП" if canonical_type == "individual_entrepreneur" or inferred_fop else "ЮО")
        if sheet_type != "ALL" and actual_type != sheet_type:
            continue
        state = canonical_states.get(row["code"], {})
        verification = state.get("verification_event") or {}
        checked = _export_date(verification.get("occurred_at") or row["edr_checked_at"])
        effective_checked = checked
        prozorro_status = state.get("prozorro_status", "Неактивний")
        requested = filters or {}
        allowed_statuses = requested.get("prozorro_statuses") or (
            {"Активний", "Призупинений", "Неактивний", "Ще не в реєстрі"}
            if requested.get("selected_mode") else {"Активний", "Призупинений"})
        if prozorro_status not in allowed_statuses:
            continue
        if requested.get("freshness_bucket") and state.get("bucket") != requested["freshness_bucket"]:
            continue
        checked_iso = effective_checked.isoformat() if effective_checked else ""
        if requested.get("verification_from") and (not checked_iso or checked_iso < requested["verification_from"]):
            continue
        if requested.get("verification_to") and (not checked_iso or checked_iso > requested["verification_to"]):
            continue
        result.append(dict(zip(EDR_EXPORT_HEADERS, [
            row["code"], name, str(row["edr_status"] or ""),
            row["current_manager"] or row["edr_manager"] or row["latest_manager"],
            effective_checked.strftime("%Y-%m-%d 00:00:00") if effective_checked else "",
        ])))
    return result

def supplier_edr_export_csv(sheet_type: str, filters: dict | None = None) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=EDR_EXPORT_HEADERS, delimiter=",", lineterminator="\r\n")
    writer.writeheader()
    writer.writerows(build_supplier_edr_export_rows(sheet_type, filters=filters))
    return ("\ufeff" + stream.getvalue()).encode("utf-8")

def edr_monitoring_export_csv(supplier_codes) -> bytes:
    """Serialize the exact monitoring population with the established ClarityChecker contract."""
    requested = {str(code or "") for code in supplier_codes if str(code or "")}
    source = {row["supplier_code"]: row for row in _edr_monitoring_rows()}
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=EDR_EXPORT_HEADERS, delimiter=",", lineterminator="\r\n")
    writer.writeheader()
    for code in sorted(requested):
        row = source.get(code)
        if not row: continue
        writer.writerow(dict(zip(EDR_EXPORT_HEADERS, [
            code, row["supplier_name"], row["edr_status"], row["manager_name"],
            f"{row['verification_date']} 00:00:00" if row["verification_date"] else "",
        ])))
    return ("\ufeff" + stream.getvalue()).encode("utf-8")
