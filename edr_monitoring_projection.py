"""Single set-based source for EDR table and synchronization comparison values.

No cache, writes, network, application startup, or business-policy duplication.
"""
import re
import edr_sync_v2
import supplier_classification
import supplier_manual_classification

def display_name(value):
    name = str(value or '').strip()
    return '' if name.casefold() in {'—', 'null'} else name

def build(con, supplier_codes=None, *, sync_only=False, eligible_codes=None):
    if sync_only and supplier_codes is not None and not supplier_codes:
        return {'rows':[],'profiles':{},'ledger':{},'verifications':{},'monitoring_codes':set(),
            'manager_current_codes':set(),'event_hashes':set(),'submission_codes':set()}
    profiles = {row["supplier_code"]: dict(row) for row in con.execute(
        "SELECT * FROM supplier_edr_profiles WHERE supplier_code<>''")}
    registry = {row["supplier_code"]: dict(row) for row in con.execute(
        "SELECT supplier_code,supplier_name FROM supplier_registry_summary WHERE supplier_code<>''")}
    latest_app = {row["supplier_code"]: dict(row) for row in con.execute("""SELECT * FROM (
      SELECT s.supplier_code,s.supplier_name,COALESCE(af.manager_name,'') manager_name,
        COALESCE(s.date_published,'') latest_application_date,
        ROW_NUMBER() OVER(PARTITION BY s.supplier_code ORDER BY
          COALESCE(s.date_published,'') DESC,s.id DESC) rank
      FROM submissions s LEFT JOIN application_fields af ON af.submission_id=s.id
      JOIN qualifications q ON q.id=s.qualification_id
      WHERE s.supplier_code<>'' AND q.status IN ('active','unsuccessful')) WHERE rank=1""")}
    active_qualification_dates = edr_sync_v2.active_qualification_dates(con)
    managers = {row["supplier_code"]: row["manager_name"] for row in con.execute("""SELECT supplier_code,manager_name FROM (
      SELECT supplier_code,manager_name,ROW_NUMBER() OVER(PARTITION BY supplier_code ORDER BY
        COALESCE(updated_at,created_at,'') DESC,id DESC) rank FROM supplier_managers
       WHERE is_current=1 AND TRIM(COALESCE(manager_name,''))<>'') WHERE rank=1""")}
    ledger = {};event_hashes = set()
    for raw in con.execute("SELECT * FROM supplier_edr_verification_events"):
        item = dict(raw); code = item["supplier_code"]
        if sync_only and item['event_type']=='google_clarity':
            event_hashes.add((code,item.get('snapshot_hash')))
        if edr_sync_v2.normalized_date(item.get("occurred_at")):
            ledger.setdefault(code, []).append(item)
    monitoring = (set(eligible_codes) if eligible_codes is not None else edr_sync_v2.monitoring_population_codes(con))
    population = monitoring if supplier_codes is None else set(supplier_codes)
    supplier_types = {} if sync_only else supplier_classification.build_index(con)
    manual_types = {} if sync_only else supplier_manual_classification.build_index(con)
    card_identities = set() if sync_only else set(profiles) | set(registry) | set(latest_app)
    card_variants = {}
    for literal in card_identities:
        normalized = re.sub(r"\D", "", literal)
        if normalized:
            card_variants.setdefault(normalized, set()).add(literal)
    verifications = edr_sync_v2.current_verification_projections(con, population, profiles=profiles, ledger=ledger)
    canonical_statuses = edr_sync_v2.canonical_prozorro_statuses(con, population,
        identity=edr_sync_v2.literal_supplier_code, eligible_codes=monitoring)
    rows = []
    for code in population:
        profile, reg, application = profiles.get(code, {}), registry.get(code, {}), latest_app.get(code, {})
        verification = verifications[code]
        status = canonical_statuses[code]
        checked = verification["verification_date"]
        officer_raw = verification["verification_officer_raw"]
        displayed_edr_status = edr_sync_v2.operational_edr_status(
            status, active_qualification_dates.get(code, ""), ledger.get(code, []),
            profile.get("edr_status", ""), profile.get("edr_checked_at", ""),
            verification.get("edr_admission_date", ""),
            verification.get("edr_admission_officer", ""))
        rows.append({"supplier_code": code,
          **({} if sync_only else supplier_classification.public_fields(supplier_manual_classification.apply_effective(
              supplier_classification.resolve(supplier_types, code), manual_types.get(code)))),
          "supplier_card_available": not sync_only and bool(re.fullmatch(r"[0-9]+", code) and code in card_identities
              and card_variants.get(code) == {code}),
          "supplier_name": profile.get("full_name") or application.get("supplier_name") or reg.get("supplier_name", ""),
          "edr_full_name": display_name(profile.get("full_name")),
          "edr_short_name": display_name(profile.get("short_name")),
          "manager_name": managers.get(code) or profile.get("manager_name") or application.get("manager_name", ""),
          "edr_status": edr_sync_v2.compatible_edr_status(displayed_edr_status), "prozorro_status": status,
          "termination_details": str(profile.get("termination_decision_details") or "").strip(),
          "termination_record_date": str(profile.get("termination_record_date") or "").strip(),
          "termination_record_number": str(profile.get("termination_record_number") or "").strip(),
          "last_admission_date": verification["last_admission_date"],
          "latest_application_date": '' if sync_only else edr_sync_v2.normalized_date(application.get("latest_application_date")),
          "verification_date": checked,
          "verification_datetime_precision": verification['verification_datetime_precision'],
          "verification_officer": verification["verification_officer"],
          "verification_officer_raw": officer_raw,
          "verification_event_type": verification["verification_event_type"],
          "verification_source": verification["verification_source"],
          "google_note": str(profile.get("edr_notes") or "").strip(),
          "freshness": '' if sync_only else edr_sync_v2.freshness_state(status, checked)["bucket"]})
    return {'rows': rows, 'profiles': profiles, 'ledger': ledger,
            'verifications': verifications, 'monitoring_codes': monitoring,
            'manager_current_codes':set(managers),
            'event_hashes':event_hashes,
            'submission_codes':({row[0] for row in con.execute("SELECT DISTINCT supplier_code FROM submissions WHERE TRIM(COALESCE(supplier_code,''))<>''")} if sync_only else set())}

FIELD_MAP = {'manager_name':'manager_name', 'edr_status':'edr_status',
    'full_name':'edr_full_name','short_name':'edr_short_name',
    'edr_checked_at':'verification_date','edr_officer':'verification_officer',
    'edr_notes':'google_note','termination_decision_details':'termination_details',
    'termination_record_date':'termination_record_date',
    'termination_record_number':'termination_record_number'}

def comparison_values(row):
    return {field: row.get(key, '') for field, key in FIELD_MAP.items()}
