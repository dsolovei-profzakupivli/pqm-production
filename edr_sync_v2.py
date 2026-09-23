"""Controlled Google EDR preview/apply primitives.

The preview path is deliberately pure: it reads the supplied source snapshot and
the current SQLite state but never creates tables, writes audit rows, or changes
business data.  ``migrate`` and ``apply`` are called only from explicit write
paths.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime

import supplier_activity


SHEETS = ("ФОП", "ЮО")
HEADERS = (
    "Маркер актуальності", "Код ЄДРПОУ", "Найменування", "ПІБ для перевірки",
    "Статус в реєстрі (ЄДР)", "Статус (Prozorro)",
    "Реквізити рішення про припинення", "Дата останньої заявки", "Дата перевірки",
    "Дата запису", "Номер запису", "УО", "Примітки", "Повна назва з ЄДР",
    "Скорочена назва з ЄДР",
)
TRACKED_FIELDS = (
    "manager_name", "edr_status", "full_name", "short_name",
    "termination_decision_details", "termination_record_date", "termination_record_number",
)


def normalize_code(value) -> str:
    return re.sub(r"\D", "", str(value or ""))


def normalize_person(value) -> str:
    text = str(value or "").casefold().replace("’", "'").replace("`", "'")
    text = re.sub(r"\s*-\s*", "-", text)
    return " ".join(re.sub(r"[.,;:]+", " ", text).split())


def _abbreviated_person_signature(value) -> tuple[str, str, str] | None:
    """Return surname + two initials only for an unambiguous abbreviated form."""
    tokens = normalize_person(value).split()
    if len(tokens) != 3 or len(tokens[1]) != 1 or len(tokens[2]) != 1:
        return None
    if not all(token.isalpha() or "-" in token or "'" in token for token in tokens):
        return None
    return tokens[0], tokens[1], tokens[2]


def _full_person_signature(value) -> tuple[str, str, str] | None:
    """Return surname + given/patronymic initials only for a full three-part name."""
    tokens = normalize_person(value).split()
    if len(tokens) != 3 or len(tokens[1]) < 2 or len(tokens[2]) < 2:
        return None
    if not all(token.isalpha() or "-" in token or "'" in token for token in tokens):
        return None
    return tokens[0], tokens[1][0], tokens[2][0]


def classify_manager_identity(old_name, confirmed_name, evidence=()) -> dict:
    """Classify an exact change without fuzzy matching or global initials merging."""
    old_normalized = normalize_person(old_name)
    new_normalized = normalize_person(confirmed_name)
    if not new_normalized:
        return {"kind": "same", "conflicting_evidence": []}
    if not old_normalized:
        conflicts = sorted({clean(name) for name in evidence
            if _full_person_signature(name)
            and normalize_person(name) != new_normalized})
        return {"kind": "ambiguous_missing_current_manager" if conflicts else "missing_current_manager",
                "conflicting_evidence": conflicts}
    if old_normalized == new_normalized:
        return {"kind": "same", "conflicting_evidence": []}
    old_signature = _abbreviated_person_signature(old_name)
    new_signature = _full_person_signature(confirmed_name)
    if not old_signature or old_signature != new_signature:
        return {"kind": "real_identity_change", "conflicting_evidence": []}
    conflicts = sorted({clean(name) for name in evidence
        if _full_person_signature(name) == old_signature
        and normalize_person(name) != new_normalized})
    return {"kind": "real_identity_change" if conflicts else "representation_enrichment",
            "conflicting_evidence": conflicts}


def clean(value) -> str:
    return " ".join(str(value or "").split())


def valid_manager_name(value) -> bool:
    text = clean(value)
    return bool(text and text.casefold() not in {
        "-", "—", "не визначено", "невідомо", "n/a", "null",
    } and re.search(r"[A-Za-zА-Яа-яІіЇїЄєҐґ]", text))


def normalized_date(value) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    head = text[:10]
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", head):
        try:
            return date.fromisoformat(head).isoformat()
        except ValueError:
            return ""
    if re.fullmatch(r"\d{2}\.\d{2}\.\d{4}", head):
        try:
            return datetime.strptime(head, "%d.%m.%Y").date().isoformat()
        except ValueError:
            return ""
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text[:10], fmt).date().isoformat()
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return ""


def _header(values: list[list]) -> tuple[str, ...]:
    if not values:
        return ()
    return tuple(str(value or "").lstrip("\ufeff").strip() for value in values[0])


def source_snapshot(values_by_sheet: dict[str, list[list]]) -> dict:
    """Validate the exact source contract and produce a stable content hash."""
    missing = [sheet for sheet in SHEETS if sheet not in values_by_sheet]
    if missing:
        raise ValueError("Відсутні вкладки: " + ", ".join(missing))
    canonical = []
    rows = []
    for sheet in SHEETS:
        values = values_by_sheet[sheet]
        actual = _header(values)
        if actual != HEADERS:
            raise ValueError(
                f"Структура вкладки {sheet} не відповідає canonical mapping. "
                f"Очікується: {' | '.join(HEADERS)}"
            )
        sheet_values = [[str(cell) if cell is not None else "" for cell in row] for row in values]
        canonical.append([sheet, sheet_values])
        for row_number, raw in enumerate(values[1:], start=2):
            padded = [str(raw[index]).strip() if index < len(raw) and raw[index] is not None else ""
                      for index in range(len(HEADERS))]
            if not any(padded):
                continue
            item = dict(zip(HEADERS, padded))
            item.update(source_sheet=sheet, source_row=row_number,
                        supplier_code=normalize_code(item["Код ЄДРПОУ"]))
            rows.append(item)
    serialized = json.dumps(
        {"contract": 2, "spreadsheet_id": "1rqghaEduW8Aer4ri36aysMurEdK2UH5laXKw_Oo1FKA",
         "sheets": canonical}, ensure_ascii=False, separators=(",", ":"),
    ).encode("utf-8")
    return {"rows": rows, "source_fingerprint": hashlib.sha256(serialized).hexdigest(),
            "headers": list(HEADERS), "row_count": len(rows)}


def source_item(row: dict) -> dict:
    return {
        "supplier_code": normalize_code(row.get("supplier_code") or row.get("Код ЄДРПОУ")),
        "full_name": str(row.get("Повна назва з ЄДР") or "").strip(),
        "short_name": str(row.get("Скорочена назва з ЄДР") or "").strip(),
        "manager_name": str(row.get("ПІБ для перевірки") or "").strip(),
        "edr_status": str(row.get("Статус в реєстрі (ЄДР)") or "").strip(),
        "edr_checked_at": normalized_date(row.get("Дата перевірки")),
        "termination_decision_details": str(row.get("Реквізити рішення про припинення") or "").strip(),
        "termination_record_date": normalized_date(row.get("Дата запису")),
        "termination_record_number": str(row.get("Номер запису") or "").strip(),
        "edr_officer": clean(row.get("УО")),
        "edr_notes": str(row.get("Примітки") or "").strip(),
        "source_sheet": str(row.get("source_sheet") or ""),
        "source_row": int(row.get("source_row") or 0),
    }


def row_snapshot_hash(item: dict) -> str:
    """Stable business observation identity; source location is provenance only."""
    payload = {key: item.get(key, "") for key in (
        "supplier_code", *TRACKED_FIELDS, "edr_checked_at", "edr_officer"
    )}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def edr_status_kind(value) -> str:
    text = clean(value).casefold()
    if "зареєстровано" in text:
        return "registered"
    if "припинен" in text or "банкрут" in text:
        return "termination"
    return "other"


def current_supplier_name(full_name, application_name) -> str:
    return str(full_name or "").strip() or str(application_name or "").strip()


def freshness_state(prozorro_status: str, verification_date: str,
                    today: date | None = None) -> dict:
    """Canonical EDR freshness presentation for UI, filters and exports."""
    status = str(prozorro_status or "").strip()
    checked = normalized_date(verification_date)
    if status == "Неактивний":
        return {"bucket": "not_current", "marker": "🟣 Неактуально",
                "age_days": None, "monitored": False}
    if status == "Ще не в реєстрі":
        return {"bucket": "not_current", "marker": "🟣 Неактуально",
                "age_days": None, "monitored": False}
    if not checked:
        return {"bucket": "not_checked", "marker": "⚪ Не перевірено",
                "age_days": None, "monitored": status in {"Активний", "Призупинений"}}
    age = max(0, ((today or date.today()) - date.fromisoformat(checked)).days)
    if age < 30:
        bucket, marker = "lt30", "🟢 <30 днів"
    elif age < 60:
        bucket, marker = "gt30", "🟡 >30 днів"
    elif age < 90:
        bucket, marker = "gt60", "🟠 >60 днів"
    else:
        bucket, marker = "gt90", "🔴 >90 днів"
    return {"bucket": bucket, "marker": marker, "age_days": age,
            "monitored": status in {"Активний", "Призупинений"}}


def marker_for_status(prozorro_status: str, verification_date: str,
                      today: date | None = None) -> str:
    return freshness_state(prozorro_status, verification_date, today)["marker"]


def migrate(con) -> None:
    con.executescript("""
    CREATE TABLE IF NOT EXISTS supplier_edr_verification_events (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      supplier_code TEXT NOT NULL,
      event_type TEXT NOT NULL,
      occurred_at TEXT NOT NULL,
      officer TEXT NOT NULL DEFAULT '',
      source TEXT NOT NULL,
      source_submission_id TEXT NOT NULL DEFAULT '',
      source_sheet TEXT NOT NULL DEFAULT '',
      source_row INTEGER NOT NULL DEFAULT 0,
      changed_fields TEXT NOT NULL DEFAULT '[]',
      snapshot_hash TEXT NOT NULL,
      snapshot_json TEXT NOT NULL DEFAULT '{}',
      created_at TEXT NOT NULL,
      UNIQUE(supplier_code,event_type,occurred_at,source,snapshot_hash)
    );
    CREATE INDEX IF NOT EXISTS ix_supplier_edr_verification_events_current
      ON supplier_edr_verification_events(supplier_code,occurred_at DESC,id DESC);
    """)
    columns = {row[1] for row in con.execute("PRAGMA table_info(supplier_edr_profiles)")}
    for name in ("termination_record_date", "termination_record_number"):
        if name not in columns:
            con.execute(f"ALTER TABLE supplier_edr_profiles ADD COLUMN {name} TEXT DEFAULT ''")
    log_columns = {row[1] for row in con.execute("PRAGMA table_info(supplier_edr_sync_log)")}
    additions = {
        "source_fingerprint": "TEXT DEFAULT ''",
        "unchanged": "INTEGER DEFAULT 0",
        "details_json": "TEXT DEFAULT '{}'",
    }
    for name, definition in additions.items():
        if name not in log_columns:
            con.execute(f"ALTER TABLE supplier_edr_sync_log ADD COLUMN {name} {definition}")


def _table_exists(con, name: str) -> bool:
    return bool(con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone())


def _columns(con, table: str) -> set[str]:
    return {row[1] for row in con.execute(f"PRAGMA table_info({table})")}


MONITORING_POPULATION_SQL = """
SELECT supplier_code FROM supplier_edr_profiles WHERE supplier_code<>''
UNION SELECT supplier_code FROM supplier_registry_summary WHERE supplier_code<>''
UNION SELECT s.supplier_code FROM submissions s
  JOIN application_fields af ON af.submission_id=s.id
  WHERE s.supplier_code<>'' AND af.protocol_decision IN ('admit','reject')
"""


def monitoring_population_codes(con) -> set[str]:
    """EDR register population, not the recurring active-only freshness queue."""
    return {str(row[0]).strip() for row in con.execute(MONITORING_POPULATION_SQL)
            if str(row[0] or '').strip()}


def google_prozorro_presentation(status: str) -> str:
    """Ready-to-write Google status; canonical business state remains separate."""
    return {"Активний": "✅ Активний", "Неактивний": "⚪️ Неактивний",
            "Ще не в реєстрі": "➖ Ще не в реєстрі",
            "Призупинений": "🟠 Призупинений"}[status]


def _eligible_codes(con, supplier_codes=None) -> set[str]:
    if not _table_exists(con, "submissions") or not _table_exists(con, "application_fields") or "protocol_decision" not in _columns(con, "application_fields"):
        return set()
    requested = {normalize_code(code) for code in (supplier_codes or []) if normalize_code(code)}
    suffix, args = "", ()
    if requested:
        suffix = " AND s.supplier_code IN (" + ",".join("?" for _ in requested) + ")"
        args = tuple(requested)
    return {normalize_code(row[0]) for row in con.execute("""
      SELECT DISTINCT s.supplier_code FROM submissions s
      JOIN application_fields af ON af.submission_id=s.id
      WHERE af.protocol_decision IN ('admit','reject')
        AND TRIM(COALESCE(s.supplier_code,''))<>''""" + suffix, args) if normalize_code(row[0])}


def _latest_application_names(con) -> dict[str, str]:
    names = {}
    if not _table_exists(con, "submissions"):
        return names
    for row in con.execute("""SELECT supplier_code,supplier_name,date_published,id FROM submissions
      WHERE TRIM(COALESCE(supplier_code,''))<>''
      ORDER BY COALESCE(NULLIF(date_published,''),'') DESC,id DESC"""):
        code = normalize_code(row[0])
        if code and code not in names and str(row[1] or "").strip():
            names[code] = str(row[1]).strip()
    return names


def _code_filter(column: str, supplier_codes=None) -> tuple[str, tuple]:
    requested = tuple(sorted({normalize_code(code) for code in (supplier_codes or [])
                              if normalize_code(code)}))
    if not requested:
        return "", ()
    return f" WHERE {column} IN (" + ",".join("?" for _ in requested) + ")", requested


def _profiles(con, supplier_codes=None) -> dict[str, dict]:
    if not _table_exists(con, "supplier_edr_profiles"):
        return {}
    columns = _columns(con, "supplier_edr_profiles")
    rows = {}
    suffix, args = _code_filter("supplier_code", supplier_codes)
    for raw in con.execute("SELECT * FROM supplier_edr_profiles" + suffix, args):
        item = dict(raw)
        for key in ("termination_record_date", "termination_record_number"):
            if key not in columns:
                item[key] = ""
        code = normalize_code(item.get("supplier_code"))
        if code:
            rows[code] = item
    return rows


def _current_managers(con, supplier_codes=None) -> dict[str, dict]:
    if not _table_exists(con, "supplier_managers"):
        return {}
    rows = {}
    suffix, args = _code_filter("supplier_code", supplier_codes)
    condition = "is_current=1" + (" AND " + suffix.removeprefix(" WHERE ") if suffix else "")
    for raw in con.execute(f"""SELECT * FROM supplier_managers WHERE {condition}
      ORDER BY COALESCE(NULLIF(updated_at,''),created_at) DESC,id DESC""", args):
        item = dict(raw); code = normalize_code(item.get("supplier_code"))
        if code and code not in rows:
            rows[code] = item
    return rows


def _closed_manager_history(con) -> dict[str, list[dict]]:
    rows: dict[str, list[dict]] = {}
    if not _table_exists(con, "supplier_managers"):
        return rows
    for raw in con.execute("""SELECT * FROM supplier_managers WHERE is_current=0
      ORDER BY COALESCE(NULLIF(valid_to,''),NULLIF(updated_at,''),created_at) DESC,id DESC"""):
        item = dict(raw)
        code = normalize_code(item.get("supplier_code"))
        if code and valid_manager_name(item.get("manager_name")):
            rows.setdefault(code, []).append(item)
    return rows


def _latest_application_managers(con, supplier_codes=None) -> dict[str, dict]:
    rows = {}
    if not (_table_exists(con, "submissions") and _table_exists(con, "application_fields")) \
            or "manager_name" not in _columns(con, "application_fields"):
        return rows
    source_columns = _columns(con, "application_fields")
    submission_columns = _columns(con, "submissions")
    source_expr = "COALESCE(af.manager_name_source,'')" if "manager_name_source" in source_columns else "''"
    synced_expr = "COALESCE(s.synced_at,'')" if "synced_at" in submission_columns else "''"
    suffix, args = _code_filter("s.supplier_code", supplier_codes)
    for raw in con.execute(f"""SELECT s.supplier_code,af.manager_name,s.id,s.date_published,
      {synced_expr} synced_at,{source_expr} manager_name_source
      FROM submissions s JOIN application_fields af ON af.submission_id=s.id
      WHERE TRIM(COALESCE(af.manager_name,''))<>''
      {('AND ' + suffix.removeprefix(' WHERE ')) if suffix else ''}
      ORDER BY COALESCE(NULLIF(s.date_published,''),NULLIF({synced_expr},''),'') DESC,s.id DESC""", args):
        code = normalize_code(raw[0])
        if code and code not in rows and valid_manager_name(raw[1]):
            rows[code] = {"manager_name": clean(raw[1]), "source": "application",
                          "source_submission_id": raw[2], "observed_at": raw[3] or raw[4] or "",
                          "application_source": raw[5] or ""}
    return rows


def known_manager_map(con, supplier_codes=None) -> dict[str, dict]:
    """Resolve current known identity without materializing or mutating it."""
    result = {}
    for code, row in _current_managers(con, supplier_codes).items():
        if valid_manager_name(row.get("manager_name")):
            result[code] = {**row, "resolution_source": "supplier_managers"}
    for code, row in _profiles(con, supplier_codes).items():
        if code not in result and valid_manager_name(row.get("manager_name")):
            result[code] = {"manager_name": clean(row.get("manager_name")),
                            "source": f"Google Sheets: {row.get('source_sheet') or 'ЄДР'}",
                            "observed_at": row.get("edr_checked_at") or row.get("synced_at") or "",
                            "updated_at": row.get("synced_at") or "",
                            "resolution_source": "edr_profile"}
    for code, row in _latest_application_managers(con, supplier_codes).items():
        if code not in result:
            result[code] = {**row, "resolution_source": "application"}
    return result


def resolve_known_manager(con, supplier_code: str) -> dict:
    code = normalize_code(supplier_code)
    return known_manager_map(con, [code]).get(code, {})


def classify_manager_transition(current_row: dict, known: dict, confirmed_name, evidence=(), history=()) -> dict:
    """Classify source observation against current or the shared known fallback."""
    incoming = clean(confirmed_name)
    if not valid_manager_name(incoming):
        return {"kind": "same", "reason": "no_new_manager_observation",
                "previous_name": clean((current_row or {}).get("manager_name")),
                "conflicting_evidence": []}
    current_name = clean((current_row or {}).get("manager_name"))
    if valid_manager_name(current_name):
        result = classify_manager_identity(current_name, incoming, evidence)
        return {**result, "previous_name": current_name,
                "reason": "current_manager_comparison"}
    known_name = clean((known or {}).get("manager_name"))
    if valid_manager_name(known_name):
        comparison = classify_manager_identity(known_name, incoming, evidence)
        if comparison["kind"] in {"same", "representation_enrichment"}:
            return {"kind": "manager_reestablished",
                    "reason": f"same_known_identity_in_{(known or {}).get('resolution_source') or 'fallback'}",
                    "previous_name": known_name,
                    "conflicting_evidence": comparison["conflicting_evidence"]}
        return {"kind": "real_identity_change", "reason": "confirmed_manager_differs_from_known_identity",
                "previous_name": known_name, "conflicting_evidence": []}
    historical_names = [clean(row.get("manager_name")) for row in history
                        if valid_manager_name(row.get("manager_name"))]
    for historical_name in historical_names:
        comparison = classify_manager_identity(historical_name, incoming, evidence)
        if comparison["kind"] in {"same", "representation_enrichment"}:
            return {"kind": "manager_reestablished", "reason": "same_identity_in_closed_history",
                    "previous_name": historical_name,
                    "conflicting_evidence": comparison["conflicting_evidence"]}
    if historical_names:
        return {"kind": "real_identity_change", "reason": "confirmed_manager_differs_from_closed_history",
                "previous_name": historical_names[0], "conflicting_evidence": []}
    return {"kind": "missing_current_manager", "reason": "no_prior_manager_identity",
            "previous_name": "", "conflicting_evidence": []}


def _manager_identity_evidence(con) -> dict[str, set[str]]:
    """Collect supplier-scoped stronger identity evidence for conflict checks."""
    evidence: dict[str, set[str]] = {}
    queries = []
    if _table_exists(con, "supplier_managers"):
        queries.append("SELECT supplier_code,manager_name FROM supplier_managers")
    if _table_exists(con, "supplier_edr_profiles"):
        queries.append("SELECT supplier_code,manager_name FROM supplier_edr_profiles")
    if _table_exists(con, "submissions") and _table_exists(con, "application_fields") \
            and "manager_name" in _columns(con, "application_fields"):
        queries.append("""SELECT s.supplier_code,af.manager_name FROM submissions s
          JOIN application_fields af ON af.submission_id=s.id""")
    for query in queries:
        for supplier_code, manager_name in con.execute(query):
            code = normalize_code(supplier_code)
            name = clean(manager_name)
            if code and _full_person_signature(name):
                evidence.setdefault(code, set()).add(name)
    return evidence


def _existing_codes(con) -> set[str]:
    codes = set(_profiles(con))
    if _table_exists(con, "submissions"):
        codes.update(normalize_code(row[0]) for row in con.execute(
            "SELECT DISTINCT supplier_code FROM submissions WHERE TRIM(COALESCE(supplier_code,''))<>''"))
    return {code for code in codes if code}


def _event_exists(con, code: str, snapshot_hash: str) -> bool:
    if not _table_exists(con, "supplier_edr_verification_events"):
        return False
    return bool(con.execute("""SELECT 1 FROM supplier_edr_verification_events
      WHERE supplier_code=? AND event_type='google_clarity' AND snapshot_hash=?""",
      (code, snapshot_hash)).fetchone())


def _same(field: str, old, new) -> bool:
    if field == "manager_name":
        return normalize_person(old) == normalize_person(new)
    return str(old or "").strip() == str(new or "").strip()


def build_preview(con, snapshot: dict) -> dict:
    """Return a factual field-level diff without issuing any SQL write."""
    rows = snapshot["rows"]
    eligible = _eligible_codes(con)
    profiles = _profiles(con)
    managers = _current_managers(con)
    manager_history = _closed_manager_history(con)
    known_managers = known_manager_map(con)
    manager_evidence = _manager_identity_evidence(con)
    applications = _latest_application_names(con)
    existing = _existing_codes(con)
    occurrences = {}
    for row in rows:
        code = normalize_code(row.get("supplier_code"))
        if code:
            occurrences.setdefault(code, []).append((row.get("source_sheet"), row.get("source_row")))
    duplicate_codes = {code: places for code, places in occurrences.items() if len(places) > 1}
    summary = {key: 0 for key in (
        "total_rows", "matched", "unmatched", "legacy_ineligible", "manager_changes",
        "manager_identity_changes", "manager_representation_enrichments",
        "manager_reestablishments", "newly_established_managers", "manager_removals",
        "edr_status_changes", "full_name_changes", "short_name_changes",
        "current_supplier_name_changes", "verification_event_changes",
        "termination_changes", "conflicts",
    )}
    summary["total_rows"] = len(rows)
    items, conflicts = [], []
    for raw in rows:
        incoming = source_item(raw); code = incoming["supplier_code"]
        row_conflicts = []
        if not code:
            row_conflicts.append("missing_supplier_code")
        if code in duplicate_codes:
            row_conflicts.append("duplicate_supplier_code")
        matched = bool(code and code in existing)
        if matched: summary["matched"] += 1
        else: summary["unmatched"] += 1
        legacy = bool(code and code not in eligible)
        if legacy: summary["legacy_ineligible"] += 1
        old = profiles.get(code, {})
        current_manager = managers.get(code, {}).get("manager_name") or ""
        changes = []
        manager_classification = {"kind": "same", "conflicting_evidence": []}
        if incoming["manager_name"]:
            manager_classification = classify_manager_transition(
                managers.get(code, {}), known_managers.get(code, {}), incoming["manager_name"],
                manager_evidence.get(code, ()), manager_history.get(code, ()))
            if manager_classification["kind"] == "ambiguous_missing_current_manager":
                row_conflicts.append("ambiguous_missing_current_manager_evidence")
            elif manager_classification["kind"] != "same":
                changes.append("manager_name")
                if manager_classification["kind"] == "representation_enrichment":
                    summary["manager_representation_enrichments"] += 1
                elif manager_classification["kind"] == "manager_reestablished":
                    summary["manager_reestablishments"] += 1
                elif manager_classification["kind"] == "missing_current_manager":
                    summary["newly_established_managers"] += 1
                else:
                    summary["manager_identity_changes"] += 1
                    summary["manager_changes"] += 1
        if incoming["edr_status"] and not _same("edr_status", old.get("edr_status"), incoming["edr_status"]):
            changes.append("edr_status"); summary["edr_status_changes"] += 1
        if incoming["full_name"] and not _same("full_name", old.get("full_name"), incoming["full_name"]):
            changes.append("full_name"); summary["full_name_changes"] += 1
        if incoming["short_name"] and not _same("short_name", old.get("short_name"), incoming["short_name"]):
            changes.append("short_name"); summary["short_name_changes"] += 1
        old_current_name = current_supplier_name(old.get("full_name"), applications.get(code))
        new_current_name = current_supplier_name(incoming["full_name"] or old.get("full_name"), applications.get(code))
        if old_current_name != new_current_name:
            summary["current_supplier_name_changes"] += 1
        explicit_clear = (
            edr_status_kind(old.get("edr_status")) == "termination"
            and edr_status_kind(incoming["edr_status"]) == "registered"
            and not incoming["termination_decision_details"]
            and not incoming["termination_record_date"]
            and not incoming["termination_record_number"]
        )
        termination_fields = ("termination_decision_details", "termination_record_date", "termination_record_number")
        termination_field_changes = [field for field in termination_fields
            if (explicit_clear and bool(str(old.get(field) or "").strip()))
            or (not explicit_clear and incoming[field] and not _same(field, old.get(field), incoming[field]))]
        termination_changed = bool(termination_field_changes)
        if termination_changed:
            changes.extend(field for field in termination_field_changes if field not in changes)
            summary["termination_changes"] += 1
        snapshot_hash = row_snapshot_hash(incoming)
        event_changed = bool(incoming["edr_checked_at"] and incoming["edr_officer"]
                             and not _event_exists(con, code, snapshot_hash))
        if event_changed:
            summary["verification_event_changes"] += 1
        actionable = bool(changes or event_changed)
        if actionable and not incoming["edr_checked_at"]:
            row_conflicts.append("changed_values_without_verification_date")
        if actionable and not incoming["edr_officer"]:
            row_conflicts.append("changed_values_without_officer")
        if str(raw.get("Дата перевірки") or "").strip() and not incoming["edr_checked_at"]:
            row_conflicts.append("malformed_verification_date")
        if row_conflicts:
            conflicts.append({"supplier_code": code, "source_sheet": incoming["source_sheet"],
                              "source_row": incoming["source_row"], "reasons": sorted(set(row_conflicts))})
        items.append({"supplier_code": code, "source_sheet": incoming["source_sheet"],
                      "source_row": incoming["source_row"], "matched": matched,
                      "population": "eligible" if code in eligible else "legacy/needs_classification",
                      "existing_profile": code in profiles,
                      "apply_allowed": bool(code and (code in profiles or code in eligible)),
                      "changed_fields": sorted(set(changes)), "verification_event_change": event_changed,
                      "manager_change_kind": manager_classification["kind"],
                      "manager_change_reason": manager_classification.get("reason", ""),
                      "manager_previous_name": manager_classification.get("previous_name", current_manager),
                      "manager_resolution_source": known_managers.get(code, {}).get("resolution_source", ""),
                      "manager_conflicting_evidence": manager_classification["conflicting_evidence"],
                      "termination_explicit_clear": explicit_clear, "snapshot_hash": snapshot_hash,
                      "conflicts": sorted(set(row_conflicts)), "incoming": incoming})
    summary["conflicts"] = len(conflicts)
    return {"source_fingerprint": snapshot["source_fingerprint"], "summary": summary,
            "items": items, "conflicts": conflicts, "duplicate_codes": duplicate_codes,
            "previewed_at": datetime.now().astimezone().isoformat()}


def current_verification_event(con, supplier_code: str) -> dict | None:
    """Resolve date+officer from one event; never combine fields across events."""
    code = normalize_code(supplier_code)
    candidates = []
    if _table_exists(con, "supplier_edr_verification_events"):
        candidates.extend(dict(row) for row in con.execute("""SELECT *
          FROM supplier_edr_verification_events WHERE supplier_code=?""", (code,)))
    if _table_exists(con, "supplier_edr_profiles"):
        profile = con.execute("""SELECT supplier_code,edr_checked_at,edr_officer,source_sheet,source_row,synced_at
          FROM supplier_edr_profiles WHERE supplier_code=?""", (code,)).fetchone()
        if profile and normalized_date(profile["edr_checked_at"]):
            candidates.append({"supplier_code": code, "event_type": "google_clarity_profile",
              "occurred_at": normalized_date(profile["edr_checked_at"]),
              "officer": profile["edr_officer"] or "", "source": "Google/Clarity profile snapshot",
              "source_submission_id": "", "source_sheet": profile["source_sheet"] or "",
              "source_row": int(profile["source_row"] or 0), "created_at": profile["synced_at"] or ""})
    application_columns = _columns(con, "application_fields")
    if not _table_exists(con, "submissions") or "protocol_decision" not in application_columns:
        return max(candidates, key=_verification_event_sort_key) if candidates else None
    officer_expr = "COALESCE(NULLIF(af.protocol_officer,''),'')"
    qualification_link = "qualification_id" in _columns(con, "submissions") and _table_exists(con, "qualifications")
    qualification_date = "NULLIF(q.decision_date,'')" if qualification_link and "decision_date" in _columns(con, "qualifications") else "NULL"
    qualification_join = "LEFT JOIN qualifications q ON q.id=s.qualification_id" if qualification_link else ""
    for row in con.execute(f"""SELECT s.id source_submission_id,
      COALESCE(NULLIF(af.protocol_date,''),{qualification_date},NULLIF(s.date_published,'')) occurred_at,
      {officer_expr} officer FROM submissions s
      JOIN application_fields af ON af.submission_id=s.id
      {qualification_join}
      WHERE DIGITS(s.supplier_code)=? AND af.protocol_decision='admit'""", (code,)):
        occurred = normalized_date(row[1])
        if occurred:
            candidates.append({"supplier_code": code, "event_type": "admission",
              "occurred_at": occurred, "officer": row[2] or "", "source": "PQM application",
              "source_submission_id": row[0], "source_sheet": "", "source_row": 0})
    if not candidates:
        return None
    candidates.sort(key=_verification_event_sort_key, reverse=True)
    return candidates[0]


def _verification_event_sort_key(item: dict) -> tuple:
    event_type = str(item.get("event_type") or "")
    priority = {"admission": 1, "google_clarity_profile": 2, "google_clarity": 3,
                "manual_edr": 4}.get(event_type, 2)
    return (normalized_date(item.get("occurred_at")), priority, int(item.get("id") or 0))


def projected_verification_officer(con, value: str) -> str:
    """The UI's existing officer presentation rule, shared with integrations."""
    raw = " ".join(str(value or "").split())
    if not raw:
        return ""
    if raw.upper() in {"НЕ ВИЗНАЧЕНО", "НЕ ПРИЗНАЧЕНО"}:
        return "Не визначено"
    if not _table_exists(con, "authorized_officers"):
        return raw
    row = con.execute(
        "SELECT full_name FROM authorized_officers WHERE NORMALIZE_NAME(full_name)=NORMALIZE_NAME(?)",
        (raw,)).fetchone()
    if not row and _table_exists(con, "auth_users"):
        row = con.execute("""SELECT o.full_name FROM auth_users u
          JOIN authorized_officers o ON o.id=u.officer_id
          WHERE LOWER(u.username)=LOWER(?)""", (raw,)).fetchone()
    if not row:
        return raw
    parts = " ".join(str(row[0]).split()).split()
    return " ".join([*(part.lower().capitalize() for part in parts[:-1]), parts[-1].upper()])


def current_verification_projections(con, supplier_codes) -> dict[str, dict]:
    """UI-compatible current verification selection by literal supplier identity."""
    codes = {str(code or "").strip() for code in supplier_codes if str(code or "").strip()}
    candidates = {code: [] for code in codes}
    admissions = {}
    qualification_link = ("qualification_id" in _columns(con, "submissions")
                          and _table_exists(con, "qualifications"))
    qualification_join = "LEFT JOIN qualifications q ON q.id=s.qualification_id" if qualification_link else ""
    qualification_date = ("NULLIF(q.decision_date,'')" if qualification_link
                          and "decision_date" in _columns(con, "qualifications") else "NULL")
    for batch in (list(sorted(codes))[i:i + 500] for i in range(0, len(codes), 500)):
        placeholders = ",".join("?" for _ in batch)
        for row in con.execute(f"""SELECT * FROM supplier_edr_verification_events
          WHERE supplier_code IN ({placeholders})""", batch):
            item = dict(row)
            if normalized_date(item.get("occurred_at")):
                candidates[item["supplier_code"]].append(item)
        for row in con.execute(f"""SELECT supplier_code,edr_checked_at,edr_officer,synced_at
          FROM supplier_edr_profiles WHERE supplier_code IN ({placeholders})""", batch):
            checked = normalized_date(row["edr_checked_at"])
            if checked:
                candidates[row["supplier_code"]].append({
                    "event_type": "google_clarity_profile", "occurred_at": checked,
                    "officer": row["edr_officer"] or "", "source": "Google/Clarity profile snapshot",
                    "created_at": row["synced_at"] or ""})
        for row in con.execute(f"""SELECT s.supplier_code,s.id submission_id,
          COALESCE(NULLIF(af.protocol_date,''),{qualification_date},
                   NULLIF(s.date_published,'')) raw_date,
          COALESCE(af.protocol_officer,'') officer
          FROM submissions s JOIN application_fields af ON af.submission_id=s.id
          {qualification_join}
          WHERE af.protocol_decision='admit' AND s.supplier_code IN ({placeholders})""", batch):
            code, checked = row["supplier_code"], normalized_date(row["raw_date"])
            previous = admissions.get(code)
            if checked and (not previous or (checked, row["submission_id"]) >
                            (previous["occurred_at"], previous["submission_id"])):
                admissions[code] = {"occurred_at": checked, "submission_id": row["submission_id"],
                                    "officer": row["officer"] or ""}
    result = {}
    for code in codes:
        admission = admissions.get(code)
        if admission:
            candidates[code].append({"event_type": "admission", "occurred_at": admission["occurred_at"],
              "officer": admission["officer"], "source": "PQM application",
              "created_at": admission["submission_id"]})
        selected = max(candidates[code], key=_verification_event_sort_key) if candidates[code] else {}
        raw_officer = str(selected.get("officer") or "").strip()
        result[code] = {"verification_date": normalized_date(selected.get("occurred_at")),
          "verification_officer": projected_verification_officer(con, raw_officer),
          "verification_officer_raw": raw_officer,
          "verification_event_type": selected.get("event_type", ""),
          "verification_source": selected.get("source", ""),
          "last_admission_date": admission["occurred_at"] if admission else "",
          "selected_event": selected}
    return result


def active_edr_status(qualification_date: str, ledger: list[dict]) -> str:
    """Status-only read model for a currently active qualification.

    Qualification activity supplies the default. Only a recorded EDR check
    proven later than the active qualification can supersede it. Neither the
    profile snapshot nor admission metadata is used to manufacture a check.
    """
    qualified_day = normalized_date(qualification_date)
    checks = []
    if qualified_day:
        for item in ledger:
            kind = str(item.get("event_type") or "")
            if kind not in {"manual_edr", "google_clarity"}:
                continue
            checked_day = normalized_date(item.get("occurred_at"))
            if not checked_day or checked_day <= qualified_day:
                continue
            try:
                snapshot = json.loads(item.get("snapshot_json") or "{}")
            except (TypeError, ValueError):
                continue
            if not isinstance(snapshot, dict):
                continue
            status = clean(snapshot.get("edr_status"))
            if status:
                checks.append((checked_day, 2 if kind == "manual_edr" else 1,
                               int(item.get("id") or 0), status))
    return max(checks)[3] if checks else "Зареєстровано"


def operational_edr_status(prozorro_status: str, qualification_date: str,
                           ledger: list[dict], profile_status: str = "") -> str:
    """Current operational status; persisted factual evidence stays untouched."""
    if prozorro_status == "Активний":
        return active_edr_status(qualification_date, ledger)
    if prozorro_status in {"Неактивний", "Ще не в реєстрі"}:
        return "Неактуально"
    # The suspended-state rule is unchanged by the current business decision.
    return str(profile_status or "")


def active_qualification_dates(con) -> dict[str, str]:
    """Latest dated effective qualification, using the shared activity predicate."""
    dates = {}
    for row in con.execute(f"""SELECT rc.supplier_code,q.decision_date
      FROM registry_contracts rc JOIN frameworks f ON f.id=rc.framework_id
      LEFT JOIN qualifications q ON q.id=rc.qualification_id
      WHERE {supplier_activity.effective_active_sql('rc', 'f')}"""):
        qualified_day = normalized_date(row[1])
        code = str(row[0] or "")
        if qualified_day > dates.get(code, ""):
            dates[code] = qualified_day
    return dates


def prozorro_statuses(con, supplier_codes=None) -> dict[str, str]:
    """One shared four-state resolver for every supplier code in PQM."""
    requested = {normalize_code(code) for code in (supplier_codes or []) if normalize_code(code)}
    eligible = _eligible_codes(con, requested or None)
    ever, active, suspended = set(), set(), set()
    framework_columns = _columns(con, "frameworks")
    raw_expr = "COALESCE(json_extract(f.raw_json,'$.qualificationPeriod.endDate'),'')" \
        if "raw_json" in framework_columns else "''"
    registry_filter, registry_args = "", ()
    if requested:
        registry_filter = " AND rc.supplier_code IN (" + ",".join("?" for _ in requested) + ")"
        registry_args = tuple(requested)
    for row in con.execute(f"""SELECT rc.supplier_code,
      MAX(CASE WHEN rc.status='active' AND LOWER(COALESCE(f.status,''))='active'
        AND ({raw_expr}='' OR DATE(SUBSTR({raw_expr},1,10))>=DATE('now')) THEN 1 ELSE 0 END) effective_active,
      MAX(CASE WHEN rc.status='suspended' THEN 1 ELSE 0 END) suspended
      FROM registry_contracts rc LEFT JOIN frameworks f ON f.id=rc.framework_id
      WHERE TRIM(COALESCE(rc.supplier_code,''))<>''{registry_filter}
      GROUP BY rc.supplier_code""", registry_args):
        code = normalize_code(row[0]); ever.add(code)
        if row[1]: active.add(code)
        if row[2]: suspended.add(code)
    result = {}
    for code in ever | eligible:
        result[code] = ("Активний" if code in active else "Призупинений" if code in suspended
                        else "Неактивний" if code in ever else "Ще не в реєстрі")
    return result


def canonical_prozorro_statuses(con, supplier_codes) -> dict[str, str]:
    """The same literal-code resolver for EDR monitoring and full-registry."""
    codes = {str(code or "").strip() for code in supplier_codes if str(code or "").strip()}
    statuses = prozorro_statuses(con)
    active = supplier_activity.effective_active_sql("rc", "f")
    activity = {str(row["supplier_code"] or "").strip(): bool(row["is_active"])
      for row in con.execute(f"""SELECT rc.supplier_code,
        MAX(CASE WHEN {active} THEN 1 ELSE 0 END) is_active
        FROM registry_contracts rc LEFT JOIN frameworks f ON f.id=rc.framework_id
        WHERE TRIM(COALESCE(rc.supplier_code,''))<>'' GROUP BY rc.supplier_code""")}
    return {code: statuses.get(code) or ("Активний" if activity.get(code) else "Неактивний")
            for code in codes}


def canonical_supplier_edr_states(con, supplier_codes=None, today: date | None = None) -> dict[str, dict]:
    """Resolve coherent verification, Prozorro status and freshness in one place."""
    requested = {normalize_code(code) for code in (supplier_codes or []) if normalize_code(code)}
    statuses = prozorro_statuses(con, requested or None)
    codes = requested or set(statuses)
    events: dict[str, list[dict]] = {code: [] for code in codes}
    if _table_exists(con, "supplier_edr_verification_events"):
        event_filter, event_args = "", ()
        if requested:
            event_filter = " WHERE supplier_code IN (" + ",".join("?" for _ in requested) + ")"
            event_args = tuple(requested)
        for row in con.execute("SELECT * FROM supplier_edr_verification_events" + event_filter, event_args):
            item = dict(row); code = normalize_code(item.get("supplier_code"))
            if code in codes:
                events.setdefault(code, []).append(item)
    if _table_exists(con, "supplier_edr_profiles"):
        profile_filter, profile_args = "", ()
        if requested:
            profile_filter = " WHERE supplier_code IN (" + ",".join("?" for _ in requested) + ")"
            profile_args = tuple(requested)
        for row in con.execute("""SELECT supplier_code,edr_checked_at,edr_officer,source_sheet,
          source_row,synced_at FROM supplier_edr_profiles""" + profile_filter, profile_args):
            code = normalize_code(row[0]); occurred = normalized_date(row[1])
            if code in codes and occurred:
                events.setdefault(code, []).append({"supplier_code": code,
                  "event_type": "google_clarity_profile", "occurred_at": occurred,
                  "officer": row[2] or "", "source": "Google/Clarity profile snapshot",
                  "source_submission_id": "", "source_sheet": row[3] or "",
                  "source_row": int(row[4] or 0), "created_at": row[5] or ""})
    application_columns = _columns(con, "application_fields")
    if _table_exists(con, "submissions") and "protocol_decision" in application_columns:
        officer_expr = "COALESCE(NULLIF(af.protocol_officer,''),'')"
        qualification_link = "qualification_id" in _columns(con, "submissions") and _table_exists(con, "qualifications")
        qualification_date = "NULLIF(q.decision_date,'')" if qualification_link and "decision_date" in _columns(con, "qualifications") else "NULL"
        qualification_join = "LEFT JOIN qualifications q ON q.id=s.qualification_id" if qualification_link else ""
        admission_filter, admission_args = "", ()
        if requested:
            admission_filter = " AND s.supplier_code IN (" + ",".join("?" for _ in requested) + ")"
            admission_args = tuple(requested)
        raw_date = f"COALESCE(NULLIF(af.protocol_date,''),{qualification_date},NULLIF(s.date_published,''))"
        for row in con.execute(f"""WITH raw_admissions AS (
          SELECT s.supplier_code,s.id source_submission_id,{raw_date} raw_date,{officer_expr} officer
          FROM submissions s JOIN application_fields af ON af.submission_id=s.id
          {qualification_join} WHERE af.protocol_decision='admit'{admission_filter}
        ), normalized_admissions AS (
          SELECT *,CASE WHEN raw_date GLOB '[0-3][0-9].[0-1][0-9].[12][0-9][0-9][0-9]*'
            THEN SUBSTR(raw_date,7,4)||'-'||SUBSTR(raw_date,4,2)||'-'||SUBSTR(raw_date,1,2)
            ELSE SUBSTR(raw_date,1,10) END occurred_at FROM raw_admissions
        ), ranked_admissions AS (
          SELECT *,ROW_NUMBER() OVER (PARTITION BY supplier_code
            ORDER BY occurred_at DESC,source_submission_id DESC) row_number
          FROM normalized_admissions WHERE COALESCE(occurred_at,'')<>''
        ) SELECT supplier_code,source_submission_id,occurred_at,officer
          FROM ranked_admissions WHERE row_number=1""", admission_args):
            code = normalize_code(row[0]); occurred = normalized_date(row[2])
            if code in codes and occurred:
                events.setdefault(code, []).append({"supplier_code": code, "event_type": "admission",
                  "occurred_at": occurred, "officer": row[3] or "", "source": "PQM application",
                  "source_submission_id": row[1], "source_sheet": "", "source_row": 0})
    result = {}
    for code in codes:
        candidates = events.get(code, [])
        candidates.sort(key=_verification_event_sort_key, reverse=True)
        verification = candidates[0] if candidates else None
        admission_dates = [normalized_date(item.get("occurred_at")) for item in candidates
                           if item.get("event_type") == "admission"
                           and normalized_date(item.get("occurred_at"))]
        status = statuses.get(code, "Ще не в реєстрі")
        freshness = freshness_state(status, (verification or {}).get("occurred_at", ""), today)
        result[code] = {"prozorro_status": status, "verification_event": verification,
          "verification_date": (verification or {}).get("occurred_at", ""),
          "verification_officer": (verification or {}).get("officer", ""),
          "last_admission_date": max(admission_dates, default=""), **freshness}
    return result


def _insert_event(con, *, item: dict, event_type: str, occurred_at: str, officer: str,
                  source: str, changed_fields: list[str], snapshot: dict, created_at: str) -> bool:
    payload = json.dumps(snapshot, ensure_ascii=False, sort_keys=True)
    digest = (row_snapshot_hash(snapshot) if event_type == "google_clarity"
              else hashlib.sha256(payload.encode("utf-8")).hexdigest())
    cursor = con.execute("""INSERT OR IGNORE INTO supplier_edr_verification_events
      (supplier_code,event_type,occurred_at,officer,source,source_submission_id,source_sheet,
       source_row,changed_fields,snapshot_hash,snapshot_json,created_at)
      VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
      (item["supplier_code"], event_type, occurred_at, officer, source,
       item.get("source_submission_id", ""),
       item.get("source_sheet", ""), int(item.get("source_row") or 0),
       json.dumps(changed_fields, ensure_ascii=False), digest, payload, created_at))
    return bool(cursor.rowcount)


def record_admission_event(con, submission_id: str, created_at: str) -> bool:
    """Persist one coherent admission verification event, idempotently."""
    if not _table_exists(con, "supplier_edr_verification_events"):
        return False
    row = con.execute("""SELECT s.supplier_code,af.protocol_date,
      COALESCE(NULLIF(af.protocol_officer,''),'') officer
      FROM submissions s JOIN application_fields af ON af.submission_id=s.id
      WHERE s.id=? AND af.protocol_decision='admit'""", (submission_id,)).fetchone()
    if not row:
        return False
    occurred = normalized_date(row[1])
    if not occurred:
        return False
    item = {"supplier_code": normalize_code(row[0]), "source_submission_id": submission_id,
            "source_sheet": "", "source_row": 0}
    snapshot = {"submission_id": submission_id, "decision": "admit",
                "protocol_date": occurred, "officer": row[2] or ""}
    return _insert_event(con, item=item, event_type="admission", occurred_at=occurred,
      officer=row[2] or "", source="PQM application", changed_fields=["application_admission"],
      snapshot=snapshot, created_at=created_at)


def materialize_effective_admission(con, contract_id: str, created_at: str) -> bool:
    """Materialize a newly effective, protocol-proven admission in caller's transaction.

    Existing active contracts are deliberately not replayed as a historical backfill.
    The caller must invoke this only on an inactive/absent -> effective-active
    contract transition after persisting the contract and qualification.
    """
    row = con.execute("""SELECT s.id submission_id,s.supplier_code,
      af.protocol_number,af.protocol_date,af.protocol_officer,
      af.protocol_decision,af.marketplace_decision,af.generated_protocol_number,
      af.generated_protocol_date,af.generated_protocol_decision,af.protocol_generated_at,
      p.protocol_number confirmed_number,p.protocol_date confirmed_date,
      p.officer confirmed_officer
      FROM registry_contracts rc JOIN frameworks f ON f.id=rc.framework_id
      JOIN qualifications q ON q.id=rc.qualification_id
      JOIN submissions s ON s.id=q.submission_id AND s.framework_id=rc.framework_id
      JOIN application_fields af ON af.submission_id=s.id
      JOIN formed_protocol_members m ON m.submission_id=s.id AND m.active=1
      JOIN formed_protocols p ON p.id=m.protocol_id AND p.status='active'
      WHERE rc.id=? AND rc.status='active' AND LOWER(COALESCE(f.status,''))='active'
        AND q.status='active' AND rc.supplier_code=s.supplier_code
        AND (COALESCE(json_extract(f.raw_json,'$.qualificationPeriod.endDate'),'')=''
          OR date(substr(json_extract(f.raw_json,'$.qualificationPeriod.endDate'),1,10))>=date('now'))""",
      (contract_id,)).fetchone()
    if not row or not row["supplier_code"] or not row["protocol_number"]:
        return False
    submission_id = row["submission_id"]
    # Historical MedData is not part of the future-admission workflow.
    import historical_applications
    if historical_applications.provenance(submission_id):
        return False
    protocol_day = normalized_date(row["protocol_date"])
    officer = clean(row["confirmed_officer"])
    if not (protocol_day and officer and officer == clean(row["protocol_officer"])
            and row["protocol_decision"] == "admit"
            and row["marketplace_decision"] == "admit"
            and row["protocol_generated_at"]
            and row["generated_protocol_decision"] == "admit"
            and row["generated_protocol_number"] == row["protocol_number"]
            and row["confirmed_number"] == row["protocol_number"]
            and normalized_date(row["confirmed_date"]) == protocol_day
            and normalized_date(row["generated_protocol_date"]) == protocol_day):
        return False
    code = row["supplier_code"]
    profile = con.execute("""SELECT edr_status,edr_checked_at FROM supplier_edr_profiles
      WHERE supplier_code=?""", (code,)).fetchone()
    # Effective admission supersedes earlier EDR status evidence. Only a
    # contradictory status observed after the protocol date can block it.
    if profile:
        prior_status = clean(profile["edr_status"])
        prior_day = normalized_date(profile["edr_checked_at"])
        if (prior_status not in ("", "Зареєстровано")
                and prior_day > protocol_day):
            return False
        if prior_status == "Зареєстровано" and prior_day > protocol_day:
            return False
    newer = con.execute("""SELECT occurred_at,snapshot_json FROM supplier_edr_verification_events
      WHERE supplier_code=? AND event_type IN ('manual_edr','google_clarity','google_clarity_profile')
        AND substr(occurred_at,1,10)>?""", (code, protocol_day)).fetchall()
    for evidence in newer:
        try:
            snapshot = json.loads(evidence["snapshot_json"] or "{}")
        except (TypeError, ValueError):
            return False  # malformed newer authoritative evidence: fail closed
        if not isinstance(snapshot, dict):
            return False
        evidence_status = clean(snapshot.get("edr_status"))
        if evidence_status and evidence_status != "Зареєстровано":
            return False
    if profile and clean(profile["edr_status"]) == "Зареєстровано" and normalized_date(profile["edr_checked_at"]) == protocol_day:
        return False
    item = {"supplier_code": code, "source_submission_id": submission_id,
            "source_sheet": "", "source_row": 0}
    snapshot = {"submission_id": submission_id, "decision": "admit",
                "protocol_date": protocol_day, "officer": officer,
                "edr_status": "Зареєстровано"}
    _insert_event(con, item=item, event_type="admission", occurred_at=protocol_day,
                  officer=officer, source="PQM effective admission",
                  changed_fields=["edr_status", "verification_date", "verification_officer"],
                  snapshot=snapshot, created_at=created_at)
    con.execute("""INSERT INTO supplier_edr_profiles
      (supplier_code,edr_status,edr_checked_at,edr_officer,synced_at)
      VALUES (?,?,?,?,?) ON CONFLICT(supplier_code) DO UPDATE SET
      edr_status=excluded.edr_status,edr_checked_at=excluded.edr_checked_at,
      edr_officer=excluded.edr_officer,synced_at=excluded.synced_at""",
      (code, "Зареєстровано", protocol_day, officer, created_at))
    return True


def apply(con, snapshot: dict, expected_fingerprint: str, *, confirmed: bool, actor: str,
          synced_at: str, sync_manager=None, enrich_manager=None, establish_manager=None,
          reestablish_manager=None,
          refresh_manager_controls=None) -> dict:
    """Apply only a confirmed, unchanged snapshot; caller owns the transaction."""
    if not confirmed:
        raise PermissionError("Потрібне явне підтвердження застосування preview")
    if not re.fullmatch(r"[0-9a-f]{64}", str(expected_fingerprint or "")):
        raise ValueError("Некоректний source fingerprint")
    if snapshot["source_fingerprint"] != expected_fingerprint:
        raise RuntimeError("Google source змінився після preview. Виконайте новий preview")
    preview = build_preview(con, snapshot)
    if preview["conflicts"]:
        raise ValueError("Apply заблоковано: preview містить конфлікти")
    counts = {"inserted": 0, "updated_profiles": 0, "unchanged": 0,
              "manager_changes": 0, "manager_identity_changes": 0,
              "manager_representation_enrichments": 0, "newly_established_managers": 0,
              "manager_reestablishments": 0,
              "manager_removals": 0,
              "verification_events": 0,
              "termination_clears": 0, "termination_events": 0,
              "skipped_ineligible_new": 0, "changed_fields": {}}
    for plan in preview["items"]:
        item = plan["incoming"]
        if not plan["apply_allowed"]:
            counts["skipped_ineligible_new"] += 1
            continue
        existing = con.execute("SELECT * FROM supplier_edr_profiles WHERE supplier_code=?",
                               (item["supplier_code"],)).fetchone()
        old = dict(existing) if existing else {}
        if plan["termination_explicit_clear"] and old:
            historical = {key: old.get(key, "") for key in (
                "edr_status", "termination_decision_details", "termination_record_date",
                "termination_record_number", "edr_checked_at", "edr_officer")}
            if any(historical.get(key) for key in ("termination_decision_details",
                                                   "termination_record_date",
                                                   "termination_record_number")):
                counts["termination_events"] += int(_insert_event(
                    con, item=item, event_type="termination_historical",
                    occurred_at=normalized_date(old.get("edr_checked_at")) or synced_at[:10],
                    officer=str(old.get("edr_officer") or ""), source="PQM current snapshot before clear",
                    changed_fields=["termination_decision_details", "termination_record_date",
                                    "termination_record_number"], snapshot=historical, created_at=synced_at))
        effective = {}
        for field in ("full_name", "short_name", "manager_name", "edr_status", "edr_checked_at",
                      "termination_decision_details", "termination_record_date",
                      "termination_record_number", "edr_officer", "edr_notes"):
            value = item.get(field, "")
            if field.startswith("termination_") and plan["termination_explicit_clear"]:
                effective[field] = ""
            else:
                effective[field] = value if str(value or "").strip() else old.get(field, "")
        if not existing:
            columns = ["supplier_code", *effective, "source_sheet", "source_row", "synced_at"]
            con.execute(f"INSERT INTO supplier_edr_profiles ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                        [item["supplier_code"], *effective.values(), item["source_sheet"], item["source_row"], synced_at])
            counts["inserted"] += 1
        else:
            changed = [field for field, value in effective.items()
                       if str(old.get(field, "") or "") != str(value or "")]
            source_changed = (str(old.get("source_sheet") or "") != item["source_sheet"]
                              or int(old.get("source_row") or 0) != item["source_row"])
            if changed or source_changed:
                assignments = [f"{field}=?" for field in effective]
                con.execute(f"UPDATE supplier_edr_profiles SET {','.join(assignments)},source_sheet=?,source_row=?,synced_at=? WHERE supplier_code=?",
                            [*effective.values(), item["source_sheet"], item["source_row"], synced_at,
                             item["supplier_code"]])
                counts["updated_profiles"] += 1
            else:
                counts["unchanged"] += 1
        for field in plan["changed_fields"]:
            counts["changed_fields"][field] = counts["changed_fields"].get(field, 0) + 1
        if plan["termination_explicit_clear"]:
            counts["termination_clears"] += 1
        if plan["verification_event_change"]:
            # Hash/store the same source observation preview checked, not profile
            # fallback values (which may differ when the source cell is blank).
            event_snapshot = dict(item)
            counts["verification_events"] += int(_insert_event(
                con, item=item, event_type="google_clarity", occurred_at=item["edr_checked_at"],
                officer=item["edr_officer"], source=f"Google Sheets: {item['source_sheet']}",
                changed_fields=plan["changed_fields"], snapshot=event_snapshot, created_at=synced_at))
        if plan["manager_change_kind"] == "representation_enrichment" and enrich_manager:
            result = enrich_manager(con, item["supplier_code"], effective["manager_name"],
                                    f"Google Sheets: {item['source_sheet']}", item["edr_checked_at"])
            if result.get("enriched"):
                counts["manager_representation_enrichments"] += 1
        elif plan["manager_change_kind"] == "manager_reestablished" and (reestablish_manager or establish_manager):
            callback = reestablish_manager or establish_manager
            result = callback(con, item["supplier_code"], effective["manager_name"],
                              f"Google Sheets: {item['source_sheet']}", item["edr_checked_at"])
            if result.get("reestablished") or result.get("established"):
                counts["manager_reestablishments"] += 1
        elif plan["manager_change_kind"] == "missing_current_manager" and establish_manager:
            result = establish_manager(con, item["supplier_code"], effective["manager_name"],
                                       f"Google Sheets: {item['source_sheet']}", item["edr_checked_at"])
            if result.get("established"):
                counts["newly_established_managers"] += 1
        elif plan["manager_change_kind"] == "real_identity_change" and sync_manager:
            result = sync_manager(con, item["supplier_code"], effective["manager_name"],
                                  f"Google Sheets: {item['source_sheet']}", item["edr_checked_at"])
            if result.get("changed"):
                counts["manager_changes"] += 1
                counts["manager_identity_changes"] += 1
                if refresh_manager_controls:
                    refresh_manager_controls(con, item["supplier_code"])
    return {**counts, "source_fingerprint": expected_fingerprint,
            "processed": preview["summary"]["total_rows"], "preview_summary": preview["summary"]}
