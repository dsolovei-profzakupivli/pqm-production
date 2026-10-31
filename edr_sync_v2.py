"""Controlled Google EDR preview/apply primitives.

The preview path is deliberately pure: it reads the supplied source snapshot and
the current SQLite state but never creates tables, writes audit rows, or changes
business data.  ``migrate`` and ``apply`` are called only from explicit write
paths.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
from datetime import date, datetime, timezone

import supplier_activity
import supplier_evidence_shadow_hooks_v3 as evidence_shadow
from google_verification_contract import (incoming_verification_gate, verification_timestamp,
    google_verification_timestamp, verification_instant, verified_admission_signature,
    decision_datetime_precision, KYIV)


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
UNVERIFIED_TIMESTAMP_REASONS = frozenset({
    "verification_date_required", "current_verification_date_missing",
    "changed_values_without_verification_date", "changed_values_without_officer",
    "verification_timestamp_required",
    "manager_change_requires_strictly_newer_verification_timestamp",
    "mirror_change_requires_strictly_newer_verification_timestamp",
})
SKIPPABLE_TIMESTAMP_GATE_REASONS = frozenset({"incoming_blank", "incoming_date_only"})


def normalize_code(value) -> str:
    return re.sub(r"\D", "", str(value or ""))


def normalize_person(value) -> str:
    text = str(value or "").casefold().replace("’", "'").replace("`", "'")
    text = re.sub(r"\s*-\s*", "-", text)
    return " ".join(re.sub(r"[.,;:]+", " ", text).split())


def register_verification_sql_functions(con) -> None:
    """Register the UI's deterministic officer lookup function on this connection."""
    con.create_function(
        "NORMALIZE_NAME", 1,
        lambda value: " ".join(re.sub(r"[’'`\-]+", " ", str(value or "").casefold()).split()),
        deterministic=True,
    )


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


EDR_PRESENTATION_PREFIXES = {
    "✅ Зареєстровано": "Зареєстровано",
    "⚪ Неактуально": "Неактуально",
    "⚪️ Неактуально": "Неактуально",
    "⚪ Немає інформації": "Немає інформації",
    "⚪️ Немає інформації": "Немає інформації",
    "🟡 В стані припинення": "В стані припинення",
    "🟡 Порушено справу про банкрутство": "Порушено справу про банкрутство",
    "🔴 Припинено": "Припинено",
    "🔴 Банкрут": "Банкрут",
}


def canonical_edr_status(value) -> str:
    """Remove known UI presentation before EDR facts enter Preview or the DB."""
    status = clean(value)
    if status in EDR_PRESENTATION_PREFIXES:
        return EDR_PRESENTATION_PREFIXES[status]
    for presented, canonical in EDR_PRESENTATION_PREFIXES.items():
        prefix = presented.split(" ", 1)[0]
        if status.startswith(prefix) and status[len(prefix):].strip() == canonical:
            return canonical
    if status and unicodedata.category(status[0]) == "So":
        raise ValueError("Невідомий presentation prefix статусу ЄДР")
    return status


def compatible_edr_status(value) -> str:
    """Canonicalize known legacy presentation; preserve unknown facts for review."""
    try:
        return canonical_edr_status(value)
    except ValueError:
        return clean(value)


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


def source_snapshot(values_by_sheet: dict[str, list[list]], *,
                    spreadsheet_id: str = "1rqghaEduW8Aer4ri36aysMurEdK2UH5laXKw_Oo1FKA") -> dict:
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
        sheet_values = [[(cell if column == 8 and number > 0 and
                              isinstance(cell, (int, float)) and not isinstance(cell, bool)
                              else str(cell) if cell is not None else "")
                         for column, cell in enumerate(row)] for number, row in enumerate(values)]
        canonical.append([sheet, sheet_values])
        for row_number, raw in enumerate(values[1:], start=2):
            padded = [str(raw[index]).strip() if index < len(raw) and raw[index] is not None else ""
                      for index in range(len(HEADERS))]
            if not any(padded):
                continue
            item = dict(zip(HEADERS, padded))
            item["_source_present_columns"] = min(len(raw), len(HEADERS))
            # A truncated source row is not evidence that omitted cells are blank.
            if len(raw) > 8 and isinstance(raw[8], (int, float)) and not isinstance(raw[8], bool):
                item[HEADERS[8]] = raw[8]
            item.update(source_sheet=sheet, source_row=row_number,
                        supplier_code=normalize_code(item["Код ЄДРПОУ"]))
            rows.append(item)
    serialized = json.dumps(
        {"contract": 3, "spreadsheet_id": spreadsheet_id,
         "sheets": canonical}, ensure_ascii=False, separators=(",", ":"),
    ).encode("utf-8")
    return {"rows": rows, "source_fingerprint": hashlib.sha256(serialized).hexdigest(),
            "headers": list(HEADERS), "row_count": len(rows)}


def source_item(row: dict) -> dict:
    status = canonical_edr_status(row.get("Статус в реєстрі (ЄДР)"))
    return {
        "supplier_code": normalize_code(row.get("supplier_code") or row.get("Код ЄДРПОУ")),
        "full_name": str(row.get("Повна назва з ЄДР") or "").strip(),
        "short_name": str(row.get("Скорочена назва з ЄДР") or "").strip(),
        "manager_name": str(row.get("ПІБ для перевірки") or "").strip(),
        # This Google-owned placeholder is not factual EDR evidence.
        "edr_status": "" if status == "Немає інформації" else status,
        "edr_checked_at": google_verification_timestamp(row.get("Дата перевірки")),
        "edr_checked_at_source": row.get("Дата перевірки"),
        "source_present_columns": int(row.get("_source_present_columns", len(HEADERS))),
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
    age = ((today or date.today()) - date.fromisoformat(checked)).days
    if age < 0:
        return {"bucket": "not_checked", "marker": "⚪ Не перевірено",
                "age_days": None, "monitored": status in {"Активний", "Призупинений"}}
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
    CREATE TABLE IF NOT EXISTS supplier_google_receipts (
      supplier_code TEXT PRIMARY KEY, received_at TEXT NOT NULL, actor TEXT NOT NULL,
      source_sheet TEXT NOT NULL, source_row INTEGER NOT NULL, source_fingerprint TEXT NOT NULL
    );
    """)
    columns = {row[1] for row in con.execute("PRAGMA table_info(supplier_edr_profiles)")}
    for name in ("termination_record_date", "termination_record_number", "last_google_received_at"):
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


DECIDED_APPLICATIONS_SQL = """
SELECT s.id,s.supplier_code,s.date_published,q.status
FROM submissions s JOIN qualifications q ON q.id=s.qualification_id
WHERE TRIM(COALESCE(s.supplier_code,''))<>''
  AND q.status IN ('active','unsuccessful')
"""

MONITORING_ELIGIBILITY_SQL = """
SELECT supplier_code,
  MAX(CASE WHEN status='active' THEN 1 ELSE 0 END) has_admitted,
  MAX(CASE WHEN status='unsuccessful' THEN 1 ELSE 0 END) has_rejected
FROM (
""" + DECIDED_APPLICATIONS_SQL + """
) GROUP BY supplier_code
HAVING has_admitted=1 OR has_rejected=1
"""

MONITORING_POPULATION_SQL = "SELECT supplier_code FROM (" + MONITORING_ELIGIBILITY_SQL + ")"


def monitoring_eligibility(con) -> dict[str, str]:
    """One literal supplier code and Google status per decided application group."""
    return {row[0]: ("Активний" if row[1] else "Ще не в реєстрі")
            for row in con.execute(MONITORING_ELIGIBILITY_SQL)}


def monitoring_population_codes(con) -> set[str]:
    """The same qualification-status population used by Google sync."""
    return set(monitoring_eligibility(con))


def google_prozorro_presentation(status: str) -> str:
    """Ready-to-write Google status; canonical business state remains separate."""
    return {"Активний": "✅ Активний", "Неактивний": "⚪️ Неактивний",
            "Ще не в реєстрі": "➖ Ще не в реєстрі",
            "Призупинений": "🟠 Призупинений"}[status]


def _eligible_codes(con, supplier_codes=None) -> set[str]:
    if not _table_exists(con, "submissions") or not _table_exists(con, "qualifications"):
        return set()
    requested = {normalize_code(code) for code in (supplier_codes or []) if normalize_code(code)}
    suffix, args = "", ()
    if requested:
        suffix = " AND s.supplier_code IN (" + ",".join("?" for _ in requested) + ")"
        args = tuple(requested)
    link = "q.id=s.qualification_id" if "qualification_id" in _columns(con, "submissions") else "q.submission_id=s.id"
    return {normalize_code(row[0]) for row in con.execute(f"""
      SELECT DISTINCT s.supplier_code FROM submissions s
      JOIN qualifications q ON {link}
      WHERE q.status IN ('active','unsuccessful')
        AND TRIM(COALESCE(s.supplier_code,''))<>''""" + suffix, args) if normalize_code(row[0])}


def _latest_application_names(con) -> dict[str, str]:
    names = {}
    if not _table_exists(con, "submissions") or not _table_exists(con, "qualifications"):
        return names
    link = "q.id=s.qualification_id" if "qualification_id" in _columns(con, "submissions") else "q.submission_id=s.id"
    for row in con.execute(f"""SELECT s.supplier_code,s.supplier_name,s.date_published,s.id FROM submissions s
      JOIN qualifications q ON {link}
      WHERE q.status IN ('active','unsuccessful') AND TRIM(COALESCE(s.supplier_code,''))<>''
      ORDER BY COALESCE(NULLIF(s.date_published,''),'') DESC,s.id DESC"""):
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
    if field == "edr_status":
        return compatible_edr_status(old) == compatible_edr_status(new)
    return str(old or "").strip() == str(new or "").strip()


def _protected_factual_at_or_after(ledger: list[dict], day: str) -> str:
    """A controlled factual observation cannot be displaced by an older/same-day one."""
    if not day:
        return ""
    protected = []
    for event in ledger:
        if event.get("event_type") != "legacy_google_registry":
            continue
        event_day = normalized_date(event.get("occurred_at"))
        if not event_day or event_day < day:
            continue
        try:
            evidence = json.loads(event.get("snapshot_json") or "{}")
        except (TypeError, ValueError):
            continue
        if isinstance(evidence, dict):
            status = _legacy_google_factual_status(event, evidence, event_day)
            if status:
                protected.append((event_day, int(event.get("id") or 0), status))
    return max(protected)[2] if protected else ""


def canonical_sandbox_officer(con) -> str:
    """Read an existing active SANDBOX identity; never create an officer/user."""
    if not _table_exists(con, "auth_users") or not _table_exists(con, "authorized_officers"):
        return ""
    rows = con.execute("""SELECT o.full_name FROM auth_users u
      JOIN authorized_officers o ON o.id=u.officer_id
      WHERE u.username='sandbox.officer' AND u.active=1 AND u.role='officer'
        AND o.active=1 AND o.role='УО'""").fetchall()
    if len(rows) != 1 or normalize_person(rows[0][0]) != normalize_person("Тестова УО SANDBOX"):
        return ""
    return rows[0][0]


def build_preview(con, snapshot: dict, *, sandbox_mode: bool = False) -> dict:
    """Return a factual field-level diff without issuing any SQL write."""
    if tuple(snapshot.get("headers") or ()) != HEADERS:
        raise ValueError("Google EDR source columns do not match the canonical A:O structure")
    rows = snapshot["rows"]
    eligible = _eligible_codes(con)
    profiles = _profiles(con)
    managers = _current_managers(con)
    manager_history = _closed_manager_history(con)
    known_managers = known_manager_map(con)
    manager_evidence = _manager_identity_evidence(con)
    applications = _latest_application_names(con)
    existing = _existing_codes(con)
    codes = {normalize_code(row.get("supplier_code")) for row in rows}
    verifications = current_verification_projections(con, codes)
    ledger = {}
    for batch in (list(sorted(codes))[i:i + 500] for i in range(0, len(codes), 500)):
        if batch:
            placeholders = ",".join("?" for _ in batch)
            for event in con.execute(f"SELECT * FROM supplier_edr_verification_events WHERE supplier_code IN ({placeholders})", batch):
                ledger.setdefault(event["supplier_code"], []).append(dict(event))
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
        "termination_changes", "conflicts", "newer_verification_accepted",
        "initial_verification_accepted", "same_date_same_officer_equivalent",
        "same_datetime_officer_preserved",
        "same_date_officer_update_accepted", "same_date_conflict",
        "older_verification_preserved",
        "blank_verification_preserved", "date_only_verification_preserved",
        "current_date_only_same_day_blocked", "factual_status_protected",
        "google_mirror_updates", "google_mirror_clears",
        "eligible", "skipped", "conflict", "skipped_unverified_timestamp",
        "skipped_ineligible",
    )}
    summary["total_rows"] = len(rows)
    sandbox_officer = canonical_sandbox_officer(con) if sandbox_mode else ""
    if sandbox_mode:
        summary["sandbox_historical_officer_normalizations"] = 0
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
        current = verifications.get(code, {})
        incoming_day = incoming["edr_checked_at"]
        current_day = current.get("verification_date", "")
        current_officer = current.get("verification_officer_raw", "")
        current_gate_value = (current.get("selected_event") or {}).get("occurred_at") or current_day
        source_checked_at = raw.get("Дата перевірки")
        gate_checked_at = source_checked_at if str(source_checked_at or "").strip() else None
        datetime_gate = incoming_verification_gate(gate_checked_at, current_gate_value,
                                                   require_time=True)
        source_present_columns = incoming["source_present_columns"]
        source_missing_fields = [HEADERS[index] for index in (6, 8, 9, 10, 12)
                                 if source_present_columns <= index]
        current_manager = managers.get(code, {}).get("manager_name") or old.get("manager_name", "")
        fact_values = (
            ("manager_name", incoming["manager_name"], current_manager),
            ("edr_status", incoming["edr_status"], old.get("edr_status", "")),
            ("full_name", incoming["full_name"], old.get("full_name", "")),
            ("short_name", incoming["short_name"], old.get("short_name", "")),
            ("termination_decision_details", incoming["termination_decision_details"], old.get("termination_decision_details", "")),
            ("termination_record_date", incoming["termination_record_date"], old.get("termination_record_date", "")),
            ("termination_record_number", incoming["termination_record_number"], old.get("termination_record_number", "")),
            ("edr_notes", incoming["edr_notes"], old.get("edr_notes", "")),
            ("edr_officer", incoming["edr_officer"], current_officer),
        )
        changed_facts = [name for name, value, previous in fact_values
                         if str(value or "").strip() and not _same(name, previous, value)]
        incoming_manager_changed = bool(incoming["manager_name"] and current_manager and
            normalize_person(incoming["manager_name"]) != normalize_person(current_manager))
        has_existing_facts = bool(current_manager or any(
            str(old.get(field) or "").strip() for field in (
                "manager_name", "edr_status", "full_name", "short_name",
                "termination_decision_details", "termination_record_date",
                "termination_record_number", "edr_notes", "edr_officer")))
        sandbox_officer_incoming = bool(sandbox_mode and
            normalize_person(incoming["edr_officer"]) == normalize_person("Тестова УО SANDBOX"))
        if sandbox_officer_incoming and not sandbox_officer:
            row_conflicts.append("sandbox_officer_identity_unavailable")
        historical_normalization = bool(sandbox_officer_incoming and sandbox_officer
            and datetime_gate['reason'] == 'equal' and not clean(current_officer))
        if historical_normalization:
            summary["sandbox_historical_officer_normalizations"] += 1
            # The date is the SAME existing observation. Google L normalization
            # does not turn it into a new check or retroactively assign its author.
            incoming["historical_normalization_officer"] = sandbox_officer
            incoming["edr_officer"] = current_officer
        if datetime_gate["reason"] in {"incoming_blank", "incoming_invalid", "current_invalid"}:
            verification_decision = "blank_verification_preserved"
        elif datetime_gate["reason"] == "incoming_date_only":
            verification_decision = "date_only_verification_preserved"
        elif datetime_gate["reason"] == "older":
            verification_decision = "older_verification_preserved"
        elif datetime_gate["reason"] == "current_date_only_not_newer_by_day":
            verification_decision = "current_date_only_same_day_blocked"
        elif datetime_gate["reason"] == "equal":
            verification_decision = ("same_date_same_officer_equivalent"
                if normalize_person(incoming["edr_officer"]) == normalize_person(current_officer)
                else "same_datetime_officer_preserved")
        else:
            verification_decision = "newer_verification_accepted" if current_day else "initial_verification_accepted"
        if not datetime_gate["accepted"] and incoming_manager_changed:
            row_conflicts.append("manager_change_requires_strictly_newer_verification_timestamp")
        if not incoming_day and changed_facts:
            row_conflicts.append("verification_date_required")
        elif not current_day and has_existing_facts and changed_facts:
            row_conflicts.append("current_verification_date_missing")
        older = not datetime_gate["accepted"]
        protected_status = _protected_factual_at_or_after(ledger.get(code, []), normalized_date(incoming_day))
        status_protected = bool(not datetime_gate["accepted"] and incoming["edr_status"] and protected_status
                                and not _same("edr_status", incoming["edr_status"], protected_status))
        summary[verification_decision] += 1
        summary["factual_status_protected"] += int(status_protected)
        changes = []
        manager_classification = {"kind": "same", "conflicting_evidence": []}
        if incoming["manager_name"] and not older:
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
        if incoming["edr_status"] and not older and not status_protected and not _same("edr_status", old.get("edr_status"), incoming["edr_status"]):
            changes.append("edr_status"); summary["edr_status_changes"] += 1
        if incoming["full_name"] and not older and not _same("full_name", old.get("full_name"), incoming["full_name"]):
            changes.append("full_name"); summary["full_name_changes"] += 1
        if incoming["short_name"] and not older and not _same("short_name", old.get("short_name"), incoming["short_name"]):
            changes.append("short_name"); summary["short_name_changes"] += 1
        old_current_name = current_supplier_name(old.get("full_name"), applications.get(code))
        new_current_name = current_supplier_name((incoming["full_name"] if not older else "") or old.get("full_name"), applications.get(code))
        if old_current_name != new_current_name:
            summary["current_supplier_name_changes"] += 1
        termination_fields = ("termination_decision_details", "termination_record_date", "termination_record_number")
        mirror_fields = (*termination_fields, "edr_notes")
        mirror_columns = {"termination_decision_details": 6, "termination_record_date": 9,
                          "termination_record_number": 10, "edr_notes": 12}
        mirror_field_changes = []
        termination_field_changes = []
        mirror_clear_fields = []
        for field in mirror_fields:
            header_index = mirror_columns[field]
            # A row may be shorter because Sheets omits trailing empty cells.
            # Canonical A:O headers were validated by source_snapshot; absent
            # row cells are therefore blank values in the Sandbox source.
            # Preserve the legacy strict row-width handling outside Sandbox.
            if source_present_columns <= header_index and not sandbox_mode:
                mirror_field_changes.append({"field": field, "current": old.get(field, "") or "",
                    "google": "", "planned": old.get(field, "") or "", "action": "blocked",
                    "reason": "missing_source_column"})
                continue
            raw_value = raw.get(HEADERS[header_index], "")
            value = incoming.get(field, "")
            # Invalid non-empty J data must never be mistaken for an intentional clear.
            if field == "termination_record_date" and str(raw_value or "").strip() and not value:
                mirror_field_changes.append({"field": field, "current": old.get(field, "") or "",
                    "google": str(raw_value).strip(), "planned": old.get(field, "") or "",
                    "action": "blocked", "reason": "malformed_termination_record_date"})
                continue
            current_value = old.get(field, "") or ""
            if _same(field, current_value, value):
                continue
            if not datetime_gate["accepted"]:
                mirror_field_changes.append({"field": field, "current": current_value,
                    "google": value or "", "planned": current_value, "action": "blocked",
                    "reason": "verification_timestamp_not_newer"})
                continue
            action = "clear" if not value else "update"
            mirror_field_changes.append({"field": field, "current": current_value,
                "google": value or "", "planned": value or "", "action": action,
                "reason": "newer_google_verification"})
            changes.append(field)
            if field in termination_fields:
                termination_field_changes.append(field)
            if action == "clear" and current_value:
                mirror_clear_fields.append(field)
        explicit_clear = any(field in termination_fields for field in mirror_clear_fields)
        if termination_field_changes:
            summary["termination_changes"] += 1
        summary["google_mirror_updates"] += sum(change["action"] == "update"
                                                  for change in mirror_field_changes)
        summary["google_mirror_clears"] += sum(change["action"] == "clear"
                                                 for change in mirror_field_changes)
        snapshot_hash = row_snapshot_hash(incoming)
        pair_accepted = datetime_gate["accepted"]
        event_changed = bool(pair_accepted and not historical_normalization
                             and incoming["edr_checked_at"] and incoming["edr_officer"]
                             and not _event_exists(con, code, snapshot_hash))
        if event_changed:
            summary["verification_event_changes"] += 1
        evidence_changes = any(field not in (*termination_fields, "edr_notes") for field in changes) or event_changed
        if historical_normalization and (evidence_changes or
                (incoming['edr_status'] and not _same('edr_status',old.get('edr_status'),incoming['edr_status']))):
            row_conflicts.append("historical_normalization_cannot_attest_factual_changes")
        if evidence_changes and not incoming["edr_checked_at"]:
            row_conflicts.append("changed_values_without_verification_date")
        if evidence_changes and not incoming["edr_officer"]:
            row_conflicts.append("changed_values_without_officer")
        if str(raw.get("Дата перевірки") or "").strip() and not incoming["edr_checked_at"]:
            row_conflicts.append("verification_timestamp_required" if datetime_gate["reason"] == "incoming_date_only"
                                 else "malformed_verification_date")
        if datetime_gate["reason"] == "current_invalid":
            row_conflicts.append("malformed_current_verification_datetime")
        if not sandbox_mode:
            for missing_header in source_missing_fields:
                row_conflicts.append("missing_source_column:" + missing_header)
        if any(change["action"] == "blocked" and change["reason"] == "verification_timestamp_not_newer"
               for change in mirror_field_changes):
            row_conflicts.append("mirror_change_requires_strictly_newer_verification_timestamp")
        if str(raw.get("Дата запису") or "").strip() and not incoming["termination_record_date"]:
            row_conflicts.append("malformed_termination_record_date")

        skip_reasons = []
        if sandbox_mode and datetime_gate["reason"] in SKIPPABLE_TIMESTAMP_GATE_REASONS:
            skip_reasons.append("verification_timestamp_unavailable")
            # These describe why this row cannot contribute a business update.
            # They are not data conflicts and must not stop independent rows.
            row_conflicts = [reason for reason in row_conflicts
                             if reason not in UNVERIFIED_TIMESTAMP_REASONS]
        if not (code and (code in profiles or code in eligible)):
            skip_reasons.append("supplier_not_apply_eligible")
        if row_conflicts:
            row_state = "conflict"
            summary["conflict"] += 1
        elif skip_reasons:
            row_state = "skipped"
            summary["skipped"] += 1
            summary["skipped_unverified_timestamp"] += int(
                "verification_timestamp_unavailable" in skip_reasons)
            summary["skipped_ineligible"] += int("supplier_not_apply_eligible" in skip_reasons)
        else:
            row_state = "eligible"
            summary["eligible"] += 1
        if row_conflicts:
            conflicts.append({"supplier_code": code, "source_sheet": incoming["source_sheet"],
                              "source_row": incoming["source_row"], "reasons": sorted(set(row_conflicts))})
        items.append({"supplier_code": code, "source_sheet": incoming["source_sheet"],
                      "source_row": incoming["source_row"], "matched": matched,
                      "population": "eligible" if code in eligible else "legacy/needs_classification",
                      "existing_profile": code in profiles,
                      "apply_allowed": bool(code and (code in profiles or code in eligible)),
                      "row_state": row_state, "skip_reasons": sorted(set(skip_reasons)),
                      "changed_fields": sorted(set(changes)), "verification_event_change": event_changed,
                      "datetime_gate": datetime_gate,
                      "manager_change_kind": manager_classification["kind"],
                      "manager_change_reason": manager_classification.get("reason", ""),
                      "manager_previous_name": manager_classification.get("previous_name", current_manager),
                      "manager_resolution_source": known_managers.get(code, {}).get("resolution_source", ""),
                      "manager_conflicting_evidence": manager_classification["conflicting_evidence"],
                      "termination_explicit_clear": explicit_clear,
                      "mirror_field_changes": mirror_field_changes,
                      "mirror_clear_fields": mirror_clear_fields, "snapshot_hash": snapshot_hash,
                      "verification_decision": verification_decision,
                      "sandbox_historical_officer_normalization": historical_normalization,
                      "current_verification_date": current_day,
                      "current_verification_officer": current_officer,
                      "current_profile": old, "current_manager_name": current_manager,
                      "current_supplier_name": old_current_name,
                      "planned_supplier_name": new_current_name,
                      "factual_status_protected": status_protected,
                      "conflicts": sorted(set(row_conflicts)), "incoming": incoming})
    summary["conflicts"] = len(conflicts)
    summary["conflict"] = len(conflicts)
    return {"source_fingerprint": snapshot["source_fingerprint"], "summary": summary,
            "items": items, "conflicts": conflicts, "duplicate_codes": duplicate_codes,
            "previewed_at": datetime.now().astimezone().isoformat()}


def _is_verification_event(item):
    return item.get('event_type') in {
        'admission', 'manual_edr', 'google_clarity', 'google_clarity_profile',
        'legacy_google_registry', 'exclusion', 'block90', 'announcement_complete'}


def _admission_projection_sql(con):
    """Reuse persisted PQM protocol/Prozorro decision sources, not submission or sync time."""
    linked = 'qualification_id' in _columns(con, 'submissions') and _table_exists(con, 'qualifications')
    if not linked:
        return '', "af.protocol_decision='admit'", "NULLIF(af.protocol_date,'')"
    joined = 'LEFT JOIN qualifications q ON q.id=s.qualification_id'
    # A contradictory pending/rejected provider status cannot become admission
    # merely because an internal UO control says admit. Historic unlinked records survive.
    condition = "(af.protocol_decision='admit' AND (q.status='active' OR q.id IS NULL))"
    date_field = ("COALESCE(NULLIF(af.protocol_date,''),NULLIF(q.decision_date,''))"
                  if 'decision_date' in _columns(con, 'qualifications') else "NULLIF(af.protocol_date,'')")
    return joined, condition, date_field


def current_verification_event(con, supplier_code: str) -> dict | None:
    """Resolve date+officer from one event; never combine fields across events."""
    code = normalize_code(supplier_code)
    candidates = []
    if _table_exists(con, "supplier_edr_verification_events"):
        candidates.extend(item for row in con.execute("""SELECT *
          FROM supplier_edr_verification_events WHERE supplier_code=?""", (code,))
                          if _is_verification_event(item := dict(row)))
    if _table_exists(con, "supplier_edr_profiles"):
        profile = con.execute("""SELECT supplier_code,edr_checked_at,edr_officer,source_sheet,source_row,synced_at
          FROM supplier_edr_profiles WHERE supplier_code=?""", (code,)).fetchone()
        if profile and normalized_date(profile["edr_checked_at"]):
            candidates.append({"supplier_code": code, "event_type": "google_clarity_profile",
              "occurred_at": verification_timestamp(profile["edr_checked_at"]),
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
    qualification_join, admission_condition, admission_date = _admission_projection_sql(con)
    for row in con.execute(f"""SELECT s.id source_submission_id,
      {admission_date} occurred_at,
      {officer_expr} officer FROM submissions s
      JOIN application_fields af ON af.submission_id=s.id
      {qualification_join}
      WHERE DIGITS(s.supplier_code)=? AND {admission_condition}""", (code,)):
        occurred = row[1] if verification_timestamp(row[1]) else ''
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
    if event_type == "google_clarity":
        try:
            evidence = json.loads(item.get("snapshot_json") or "{}")
        except (TypeError, ValueError):
            evidence = {}
        if (isinstance(evidence, dict) and evidence.get("same_day_officer_update") is True
                and str(item.get("source") or "").startswith("Google Sheets: ")):
            priority = 5
    parsed = verification_instant(item.get("occurred_at"))
    instant = parsed["value"].isoformat() if parsed["kind"] == "datetime" else ""
    return (instant, priority, int(item.get("id") or 0))


def projected_verification_officer(con, value: str, event_type: str = '') -> str:
    """The UI's existing officer presentation rule, shared with integrations."""
    raw = " ".join(str(value or "").split())
    if event_type == 'announcement_complete':
        return 'ЕСЗ'
    if not raw:
        if event_type in {'exclusion', 'block90', 'announcement_complete'}:
            return 'ЕСЗ'
        if event_type == 'admission':
            return ('Тестова УО SANDBOX' if os.getenv('PQM_SANDBOX','').lower() in {'1','true'}
                    else 'Не визначено')
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


def _has_edr_checking_officer(value: str) -> bool:
    normalized = clean(value).casefold()
    return bool(normalized) and normalized not in {"не визначено", "не призначено"}


def current_verification_projections(con, supplier_codes) -> dict[str, dict]:
    """UI-compatible current verification selection by literal supplier identity."""
    codes = {str(code) for code in supplier_codes if str(code or "").strip()}
    candidates = {code: [] for code in codes}
    admissions = {}
    edr_admissions = {}
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
            if _is_verification_event(item) and normalized_date(item.get("occurred_at")):
                candidates[item["supplier_code"]].append(item)
        for row in con.execute(f"""SELECT supplier_code,edr_checked_at,edr_officer,synced_at
          FROM supplier_edr_profiles WHERE supplier_code IN ({placeholders})""", batch):
            checked = str(row["edr_checked_at"] or "").strip()
            if verification_timestamp(checked):
                candidates[row["supplier_code"]].append({
                    "event_type": "google_clarity_profile", "occurred_at": checked,
                    "officer": row["edr_officer"] or "", "source": "Google/Clarity profile snapshot",
                    "created_at": row["synced_at"] or ""})
        qualification_join, admission_condition, admission_date = _admission_projection_sql(con)
        for row in con.execute(f"""SELECT s.supplier_code,s.id submission_id,
          {admission_date} raw_date,
          COALESCE(af.protocol_officer,'') officer
          FROM submissions s JOIN application_fields af ON af.submission_id=s.id
          {qualification_join}
          WHERE {admission_condition} AND s.supplier_code IN ({placeholders})""", batch):
            code, checked = row["supplier_code"], row["raw_date"] if verification_timestamp(row["raw_date"]) else ''
            previous = admissions.get(code)
            if checked and (not previous or (verification_instant(checked)['value'], row["submission_id"]) >
                            (verification_instant(previous["occurred_at"])['value'], previous["submission_id"])):
                admissions[code] = {"occurred_at": checked, "submission_id": row["submission_id"],
                                    "officer": row["officer"] or ""}
            previous_edr = edr_admissions.get(code)
            if (checked and _has_edr_checking_officer(row["officer"] or "") and
                (not previous_edr or (verification_instant(checked)['value'], row["submission_id"]) >
                 (verification_instant(previous_edr["occurred_at"])['value'], previous_edr["submission_id"]))):
                edr_admissions[code] = {"occurred_at": checked, "submission_id": row["submission_id"],
                                        "officer": row["officer"] or ""}
    result = {}
    for code in codes:
        admission = admissions.get(code)
        edr_admission = edr_admissions.get(code)
        if admission:
            candidates[code].append({"event_type": "admission", "occurred_at": admission["occurred_at"],
              "officer": admission["officer"], "source": "PQM application",
              "created_at": admission["submission_id"]})
        selected = max(candidates[code], key=_verification_event_sort_key) if candidates[code] else {}
        raw_officer = str(selected.get("officer") or "").strip()
        selected_raw = str(selected.get('occurred_at') or '')
        verified_signed_at = verified_admission_signature(selected)
        precision = decision_datetime_precision(selected_raw)
        result[code] = {"verification_date": verification_timestamp(selected.get("occurred_at")),
          "verification_datetime_precision":precision,
          "signature_timestamp_available":bool(verified_signed_at),
          "signature_timestamp_source":'verified_protocol_signature' if verified_signed_at else 'NOT_AVAILABLE',
          "verification_officer": projected_verification_officer(con, raw_officer, selected.get('event_type','')),
          "verification_officer_raw": raw_officer,
          "verification_event_type": selected.get("event_type", ""),
          "verification_source": selected.get("source", ""),
          "last_admission_date": admission["occurred_at"] if admission else "",
          "last_admission_officer": admission["officer"] if admission else "",
          "edr_admission_date": edr_admission["occurred_at"] if edr_admission else "",
          "edr_admission_officer": edr_admission["officer"] if edr_admission else "",
          "selected_event": selected}
    return result


LEGACY_GOOGLE_FACTUAL_STATUSES = frozenset({
    "Припинено", "В стані припинення", "Порушено справу про банкрутство", "Банкрут"})
LEGACY_GOOGLE_FACTUAL_SPREADSHEET_ID_ENV = "PQM_GOOGLE_REGISTRY_SPREADSHEET_ID"


def _legacy_google_factual_status(item: dict, snapshot: dict, checked_day: str) -> str:
    """Accept only a complete, attributable Google date/officer/status evidence pair."""
    authorized_spreadsheet_id = os.environ.get(
        LEGACY_GOOGLE_FACTUAL_SPREADSHEET_ID_ENV, "").strip()
    if not authorized_spreadsheet_id:
        return ""
    status = compatible_edr_status(snapshot.get("factual_edr_status"))
    if status not in LEGACY_GOOGLE_FACTUAL_STATUSES:
        return ""
    officer = normalize_person(item.get("officer"))
    tab = str(item.get("source_sheet") or "")
    try:
        row = int(item.get("source_row") or 0)
        snapshot_row = int(snapshot.get("source_row") or 0)
    except (TypeError, ValueError):
        return ""
    if (str(item.get("source") or "") != "legacy_google_registry" or
        str(snapshot.get("source") or "") != "legacy_google_registry" or
        normalized_date(snapshot.get("verification_date")) != checked_day or
        not officer or normalize_person(snapshot.get("verification_officer")) != officer or
        tab not in {"ФОП", "ЮО"} or snapshot.get("source_tab") != tab or
        row < 2 or snapshot_row != row or
        snapshot.get("factual_spreadsheet_id") != authorized_spreadsheet_id or
        snapshot.get("factual_source_tab") != tab or
        type(snapshot.get("factual_source_row")) is not int or
        snapshot["factual_source_row"] < 2 or
        snapshot.get("factual_provenance_version") != 1 or
        not re.fullmatch(r"[0-9a-f]{64}", str(snapshot.get("source_digest") or "")) or
        not re.fullmatch(r"[0-9a-f]{64}", str(snapshot.get("factual_source_digest") or ""))):
        return ""
    return status


def active_edr_status(qualification_date: str, ledger: list[dict], profile_status: str = "",
                      profile_checked_at: str = "", admission_date: str = "",
                      admission_officer: str = "") -> str:
    """Resolve EDR status from the latest established status event.

    Active qualifications determine Prozorro activity; they are not an EDR
    status event. A dated admission protocol with a responsible officer records
    the admission-time EDR check as "Зареєстровано". Otherwise keep the newest
    valid factual check/profile status, or report no information.
    """
    candidates = []
    for item in ledger or []:
        kind = str(item.get("event_type") or "")
        if kind not in {"manual_edr", "google_clarity", "legacy_google_registry"}:
            continue
        checked_day = normalized_date(item.get("occurred_at"))
        if not checked_day:
            continue
        try:
            snapshot = json.loads(item.get("snapshot_json") or "{}")
        except (TypeError, ValueError):
            continue
        if not isinstance(snapshot, dict):
            continue
        if kind == "legacy_google_registry":
            status = _legacy_google_factual_status(item, snapshot, checked_day)
            if not status:
                continue  # I/L-only or invalid legacy evidence never changes E.
        else:
            status = compatible_edr_status(snapshot.get("edr_status"))
        if status and status != "Немає інформації":
            candidates.append({**item, "event_type": kind, "occurred_at": item.get("occurred_at"),
                               "resolved_edr_status": status})

    stored_status = compatible_edr_status(profile_status)
    profile_day = normalized_date(profile_checked_at)
    if stored_status and stored_status != "Немає інформації" and profile_day:
        candidates.append({"event_type": "google_clarity_profile", "occurred_at": profile_checked_at,
                           "resolved_edr_status": stored_status})

    admission_day = normalized_date(admission_date)
    if admission_day and _has_edr_checking_officer(admission_officer):
        candidates.append({"event_type": "admission", "occurred_at": admission_date,
                           "resolved_edr_status": "Зареєстровано"})

    if candidates:
        # Date is compared first; existing event priority resolves same-day
        # evidence, with a recorded check taking precedence over an admission.
        latest = max(candidates, key=lambda item: (
            normalized_date(item.get("occurred_at")),
            *_verification_event_sort_key(item),
        ))
        return compatible_edr_status(latest["resolved_edr_status"])
    if stored_status:
        return stored_status
    return "Немає інформації"


def operational_edr_status(prozorro_status: str, qualification_date: str,
                           ledger: list[dict], profile_status: str = "",
                           profile_checked_at: str = "", admission_date: str = "",
                           admission_officer: str = "") -> str:
    """Current operational status; persisted factual evidence stays untouched."""
    if prozorro_status == "Активний":
        return active_edr_status(qualification_date, ledger, profile_status,
                                 profile_checked_at, admission_date, admission_officer)
    if prozorro_status in {"Неактивний", "Ще не в реєстрі"}:
        return "Неактуально"
    # The suspended-state rule is unchanged by the current business decision.
    return compatible_edr_status(profile_status)


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
    codes = {str(code) for code in supplier_codes if str(code or "").strip()}
    statuses = prozorro_statuses(con)
    active = supplier_activity.effective_active_sql("rc", "f")
    activity = {str(row["supplier_code"] or "").strip(): bool(row["is_active"])
      for row in con.execute(f"""SELECT rc.supplier_code,
        MAX(CASE WHEN {active} THEN 1 ELSE 0 END) is_active
        FROM registry_contracts rc LEFT JOIN frameworks f ON f.id=rc.framework_id
        WHERE TRIM(COALESCE(rc.supplier_code,''))<>'' GROUP BY rc.supplier_code""")}
    return {code: statuses.get(code.strip()) or ("Активний" if activity.get(code.strip()) else "Неактивний")
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
            if code in codes and _is_verification_event(item):
                events.setdefault(code, []).append(item)
    profile_states = {}
    if _table_exists(con, "supplier_edr_profiles"):
        profile_filter, profile_args = "", ()
        if requested:
            profile_filter = " WHERE supplier_code IN (" + ",".join("?" for _ in requested) + ")"
            profile_args = tuple(requested)
        profile_columns = _columns(con, "supplier_edr_profiles")
        status_expr = "edr_status" if "edr_status" in profile_columns else "'' edr_status"
        for row in con.execute("""SELECT supplier_code,edr_checked_at,edr_officer,source_sheet,
          source_row,synced_at,""" + status_expr + " FROM supplier_edr_profiles" + profile_filter, profile_args):
            code = normalize_code(row[0]); occurred = verification_timestamp(row[1])
            profile_states[code] = {"edr_checked_at": row[1] or "", "edr_status": row[6] or ""}
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
        qualification_join, admission_condition, raw_date = _admission_projection_sql(con)
        for row in con.execute(f"""WITH raw_admissions AS (
          SELECT s.supplier_code,s.id source_submission_id,{raw_date} raw_date,{officer_expr} officer
          FROM submissions s JOIN application_fields af ON af.submission_id=s.id
          {qualification_join} WHERE {admission_condition}{admission_filter}
        ), normalized_admissions AS (
          SELECT *,CASE WHEN raw_date GLOB '[0-3][0-9].[0-1][0-9].[12][0-9][0-9][0-9]*'
            THEN SUBSTR(raw_date,7,4)||'-'||SUBSTR(raw_date,4,2)||'-'||SUBSTR(raw_date,1,2)
            ELSE SUBSTR(raw_date,1,10) END occurred_at FROM raw_admissions
        ), ranked_admissions AS (
          SELECT *,ROW_NUMBER() OVER (PARTITION BY supplier_code
            ORDER BY occurred_at DESC,source_submission_id DESC) row_number
          FROM normalized_admissions WHERE COALESCE(occurred_at,'')<>''
        ) SELECT supplier_code,source_submission_id,raw_date,officer
          FROM ranked_admissions""", admission_args):
            code = normalize_code(row[0]); occurred = (verification_timestamp(row[2])
                if decision_datetime_precision(row[2]) == 'instant' else normalized_date(row[2]))
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
        latest_admission = max((item for item in candidates if item.get("event_type") == "admission"
                                and normalized_date(item.get("occurred_at"))
                                and _has_edr_checking_officer(item.get("officer", ""))),
                               key=_verification_event_sort_key, default={})
        status = statuses.get(code, "Ще не в реєстрі")
        freshness = freshness_state(status, (verification or {}).get("occurred_at", ""), today)
        profile = profile_states.get(code, {})
        edr_status_current = operational_edr_status(
            status, "", candidates, profile.get("edr_status", ""),
            profile.get("edr_checked_at", ""), latest_admission.get("occurred_at", ""),
            latest_admission.get("officer", ""))
        result[code] = {"prozorro_status": status, "edr_status_current": edr_status_current,
          "verification_event": verification,
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
    if cursor.rowcount:
        evidence_shadow.verification(con, source_id=cursor.lastrowid, item=item,
            event_type=event_type, occurred_at=occurred_at, officer=officer,
            recorded_at=created_at, snapshot=snapshot)
    return bool(cursor.rowcount)


def _status_event_time(value):
    """An explicit, timezone-aware source instant, never a deadline/sync fallback."""
    if not isinstance(value, str) or not re.fullmatch(
            r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})', value):
        return None
    # Prozorro can serialize microseconds. Keep them in immutable source evidence;
    # do not extend the Google/manual datetime contract implicitly.
    offset = re.search(r'([+-])(\d{2}):(\d{2})$', value)
    if offset and (int(offset[2]) > 14 or int(offset[3]) > 59 or
                   (int(offset[2]) == 14 and int(offset[3]) != 0)):
        return None
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(timezone.utc)
    except (ValueError, OverflowError):
        return None


def _record_prozorro_status_event(con, kind, code, identity, instant, created_at):
    """Append-only identity: mutable documents, officers and sync time are excluded."""
    proof = {**identity, 'event_type': kind, 'source_timestamp': instant.isoformat(),
             'provenance_version': 1, 'officer_basis': 'no_structured_uo', 'officer': 'ЕСЗ'}
    event_id = hashlib.sha256(json.dumps(proof, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    source = 'Prozorro status event:' + event_id
    # Existing SQLite uniqueness also covers the deterministic immutable snapshot.
    # The importer calls this inside its current transaction; replay never edits history.
    if con.execute('''SELECT 1 FROM supplier_edr_verification_events
      WHERE supplier_code=? AND event_type=? AND source=?''', (code, kind, source)).fetchone():
        return {'created': 0, 'reason': 'already_recorded'}
    created = _insert_event(con, item={'supplier_code': code}, event_type=kind,
        # Same millisecond representation as the existing Sheets/read-model contract.
        # proof.source_timestamp above retains the exact original source instant.
        occurred_at=instant.astimezone(KYIV).isoformat(timespec='milliseconds'), officer='ЕСЗ', source=source,
        changed_fields=['prozorro_status_verification'], snapshot=proof, created_at=created_at)
    return {'created': int(created), 'reason': 'recorded' if created else 'already_recorded'}


def record_prozorro_contract_status_event(con, framework_id, agreement_id, previous, current, created_at):
    """Only a newly observed status transition with causal milestone evidence.

    Official Prozorro source c05cbed1595b335cd950179bfce1d86ed324e3b9:
    MilestoneState.on_post sets contract.date at ban creation; on_patch(met)
    sets milestone.dateMet and contract.date at termination. Document edits can
    change dateModified without changing contract.date, so they are not a clock.
    """
    skipped = lambda reason: {'created': 0, 'reason': reason}
    if not previous:
        return skipped('no_previous_status_no_backfill')
    before, after = previous.get('status'), current.get('status')
    if before == after:
        return skipped('status_unchanged')
    if before not in {'active', 'suspended'} or after not in {'suspended', 'terminated'}:
        return skipped('not_a_verification_transition')
    if not _table_exists(con, 'supplier_edr_verification_events'):
        return skipped('verification_ledger_unavailable')
    suppliers = current.get('suppliers')
    if not isinstance(suppliers, list) or len(suppliers) != 1 or not isinstance(suppliers[0], dict):
        return skipped('ambiguous_supplier_identity')
    code = str((suppliers[0].get('identifier') or {}).get('id') or '').strip()
    if (not framework_id or not agreement_id or not current.get('id') or not current.get('qualificationID') or
            previous.get('id') != current['id'] or previous.get('framework_id') != framework_id or
            previous.get('qualification_id') != current.get('qualificationID') or
            str(previous.get('supplier_code') or '').strip() != code or not code):
        return skipped('identity_mismatch')
    linked = con.execute('SELECT agreement_id FROM frameworks WHERE id=?', (framework_id,)).fetchone()
    if not linked or linked[0] != agreement_id:
        return skipped('agreement_identity_mismatch')
    instant = _status_event_time(current.get('date'))
    if instant is None:
        return skipped('missing_or_invalid_status_timestamp')
    try:
        old_status_time = _status_event_time(json.loads(previous.get('raw_json') or '{}').get('date'))
    except (TypeError, ValueError, AttributeError):
        return skipped('invalid_previous_status_evidence')
    if old_status_time is not None and instant <= old_status_time:
        return skipped('non_increasing_status_timestamp')
    milestones = current.get('milestones')
    if not isinstance(milestones, list) or not milestones or any(not isinstance(m, dict) for m in milestones):
        return skipped('missing_milestone_evidence')
    ids = [m.get('id') for m in milestones]
    if any(not isinstance(mid, str) or not mid for mid in ids) or len(set(ids)) != len(ids):
        return skipped('ambiguous_milestone_identity')
    if after == 'terminated':
        causal = [m for m in milestones if m.get('type') in {'activation', 'ban'} and
                  m.get('status') == 'met' and _status_event_time(m.get('dateMet')) == instant]
        kind, timestamp_source = 'exclusion', 'milestone.dateMet'
    else:
        # ban is a documented 90-calendar-day suspension. Its dueDate is NOT its start.
        causal = [m for m in milestones if m.get('type') == 'ban' and m.get('status') == 'scheduled' and
                  _status_event_time(m.get('dateModified')) == instant and not m.get('dateMet') and
                  _status_event_time(m.get('dueDate')) is not None and _status_event_time(m['dueDate']) > instant]
        kind, timestamp_source = 'block90', 'contract.date_at_ban_creation'
    if len(causal) != 1:
        return skipped('status_timestamp_not_proven_by_milestone')
    milestone = causal[0]
    return _record_prozorro_status_event(con, kind, code, {
        'framework_id': framework_id, 'agreement_id': agreement_id, 'contract_id': current['id'],
        'qualification_id': current['qualificationID'], 'milestone_id': milestone['id'],
        'milestone_type': milestone['type'], 'milestone_status': milestone['status'],
        'status': after, 'timestamp_source': timestamp_source}, instant, created_at)


def record_prozorro_framework_status_event(con, previous, current, created_at):
    """Framework.date is assigned by update_status_change_revision, not dateModified.

    Require an observed active→complete transition, a later status-specific date,
    and a passed qualification period. A locally computed expiry is not completion.
    """
    skipped = lambda reason: {'created': 0, 'reason': reason}
    if not previous:
        return skipped('no_previous_status_no_backfill')
    if previous.get('status') == current.get('status'):
        return skipped('status_unchanged')
    if previous.get('status') != 'active' or current.get('status') != 'complete':
        return skipped('not_a_verification_transition')
    if (not current.get('id') or previous.get('id') != current['id'] or
            current.get('frameworkType') != 'electronicCatalogue'):
        return skipped('identity_mismatch')
    try:
        old = json.loads(previous.get('raw_json') or '{}')
    except (TypeError, ValueError):
        return skipped('invalid_previous_status_evidence')
    instant = _status_event_time(current.get('date'))
    old_instant = _status_event_time(old.get('date'))
    end = _status_event_time((current.get('qualificationPeriod') or {}).get('endDate'))
    if instant is None or old_instant is None or end is None or instant <= old_instant or instant < end:
        return skipped('missing_or_invalid_status_timestamp')
    if not _table_exists(con, 'supplier_edr_verification_events'):
        return skipped('verification_ledger_unavailable')
    # Completed announcements affect their still-active/suspended memberships,
    # not suppliers already excluded earlier from every qualification.
    members = {str(r[0] or '').strip() for r in con.execute('''SELECT supplier_code
      FROM registry_contracts WHERE framework_id=? AND status IN ('active','suspended')''', (current['id'],))}
    count = 0
    for code in sorted(members - {''}):
        result = _record_prozorro_status_event(con, 'announcement_complete', code, {
            'framework_id': current['id'], 'status': 'complete', 'timestamp_source': 'framework.date'}, instant, created_at)
        count += result['created']
    return {'created': count, 'reason': 'recorded' if count else 'no_affected_members_or_already_recorded'}


def record_admission_event(con, submission_id: str, created_at: str) -> bool:
    """Persist one coherent admission verification event, idempotently."""
    if not _table_exists(con, "supplier_edr_verification_events"):
        return False
    joined, condition, date_field = _admission_projection_sql(con)
    row = con.execute(f"""SELECT s.supplier_code,{date_field},
      COALESCE(NULLIF(af.protocol_officer,''),'') officer
      FROM submissions s JOIN application_fields af ON af.submission_id=s.id
      {joined} WHERE s.id=? AND {condition}""", (submission_id,)).fetchone()
    if not row:
        return False
    occurred = (verification_timestamp(row[1]) if decision_datetime_precision(row[1]) == 'instant'
                else normalized_date(row[1]))
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
        prior_status = compatible_edr_status(profile["edr_status"])
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
        evidence_status = compatible_edr_status(snapshot.get("edr_status"))
        if evidence_status and evidence_status != "Зареєстровано":
            return False
    if profile and compatible_edr_status(profile["edr_status"]) == "Зареєстровано" and normalized_date(profile["edr_checked_at"]) == protocol_day:
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


def effective_profile_fields(plan: dict, old: dict) -> dict:
    """The one canonical field decision shared by Apply and SANDBOX review."""
    item = plan["incoming"]
    if plan.get("datetime_gate", {}).get("accepted") is False:
        return {field: old.get(field, "") for field in (
            "full_name", "short_name", "manager_name", "edr_status", "edr_checked_at",
            "termination_decision_details", "termination_record_date", "termination_record_number",
            "edr_officer", "edr_notes")}
    effective = {}
    for field in ("full_name", "short_name", "manager_name", "edr_status", "edr_checked_at",
                  "termination_decision_details", "termination_record_date",
                  "termination_record_number", "edr_officer", "edr_notes"):
        value = item.get(field, "")
        if field in {"edr_checked_at", "edr_officer"} and plan["verification_decision"] == "older_verification_preserved":
            effective[field] = (plan["current_verification_date"] if field == "edr_checked_at"
                                else plan["current_verification_officer"])
        elif field in {"full_name", "short_name", "manager_name", "edr_status"} and (
                plan["verification_decision"] == "older_verification_preserved" or
                (field == "edr_status" and plan["factual_status_protected"])):
            effective[field] = old.get(field, "")
        elif field in {"termination_decision_details", "termination_record_date",
                       "termination_record_number", "edr_notes"}:
            # These four fields are a Google-owned full mirror when and only when
            # the verification timestamp passed the strict freshness gate.
            effective[field] = value
        elif field == "edr_status" and old.get(field) and _same(field, old.get(field), value):
            effective[field] = old[field]  # Legacy spelling is not migrated by an ordinary Apply.
        else:
            # Empty Google cells never erase a previously confirmed PQM value.
            effective[field] = value if str(value or "").strip() else old.get(field, "")
    return effective


def preview_state_digest(preview: dict) -> str:
    """Bind reviewed decisions to current PQM state without returning that state in a token."""
    business = [{key: plan.get(key) for key in (
        "supplier_code", "current_profile", "current_manager_name", "current_verification_date",
        "current_verification_officer", "verification_decision", "factual_status_protected",
        "changed_fields", "verification_event_change", "conflicts", "incoming", "datetime_gate",
        "row_state", "skip_reasons")}
        for plan in preview["items"]]
    encoded = json.dumps(business, ensure_ascii=False, sort_keys=True, default=str,
                         separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def apply(con, snapshot: dict, expected_fingerprint: str, *, confirmed: bool, actor: str,
          synced_at: str, sync_manager=None, enrich_manager=None, establish_manager=None,
          reestablish_manager=None,
          refresh_manager_controls=None, reconcile_manager_nazk=None,
          expected_state_digest: str | None = None,
          sandbox_mode: bool = False) -> dict:
    """Apply only a confirmed, unchanged snapshot; caller owns the transaction."""
    if not confirmed:
        raise PermissionError("Потрібне явне підтвердження застосування preview")
    if not re.fullmatch(r"[0-9a-f]{64}", str(expected_fingerprint or "")):
        raise ValueError("Некоректний source fingerprint")
    if snapshot["source_fingerprint"] != expected_fingerprint:
        raise RuntimeError("Google source змінився після preview. Виконайте новий preview")
    preview = build_preview(con, snapshot, sandbox_mode=sandbox_mode)
    if expected_state_digest is not None and preview_state_digest(preview) != expected_state_digest:
        raise RuntimeError("PQM state changed after reviewed preview")
    if preview["conflicts"] and not sandbox_mode:
        raise ValueError("Apply заблоковано: preview містить конфлікти")
    counts = {"inserted": 0, "updated_profiles": 0, "unchanged": 0,
              "received_suppliers": 0,
              "manager_changes": 0, "manager_identity_changes": 0,
              "manager_representation_enrichments": 0, "newly_established_managers": 0,
              "manager_reestablishments": 0,
              "manager_removals": 0,
              "verification_events": 0,
              "google_mirror_clears": 0, "google_mirror_clear_events": 0,
              "nazk_manager_reconciliations": 0,
              "termination_clears": 0, "termination_events": 0,
              "skipped_no_verification_timestamp": 0,
              "skipped_conflicts": 0,
              "skipped_ineligible_new": 0, "changed_fields": {}}
    for plan in preview["items"]:
        item = plan["incoming"]
        if sandbox_mode and plan.get("row_state") == "conflict":
            counts["skipped_conflicts"] += 1
            continue
        if plan.get("row_state") == "skipped":
            counts["skipped_no_verification_timestamp"] += int(
                "verification_timestamp_unavailable" in plan.get("skip_reasons", []))
            counts["skipped_ineligible_new"] += int(not plan["apply_allowed"])
            # Undated rows leave profiles, receipts, history, and NAZK tasks untouched.
            continue
        if not plan["apply_allowed"]:
            counts["skipped_ineligible_new"] += 1
            continue
        # Receipt is technical provenance of a real matched source row, not an I/L event.
        # It is inside the caller's successful Apply transaction; Preview never records it.
        con.execute("""INSERT INTO supplier_google_receipts(supplier_code,received_at,actor,source_sheet,source_row,source_fingerprint)
          VALUES(?,?,?,?,?,?) ON CONFLICT(supplier_code) DO UPDATE SET received_at=excluded.received_at,
          actor=excluded.actor,source_sheet=excluded.source_sheet,source_row=excluded.source_row,
          source_fingerprint=excluded.source_fingerprint""",
          (item["supplier_code"],synced_at,actor,item["source_sheet"],item["source_row"],expected_fingerprint))
        counts["received_suppliers"] += 1
        con.execute('UPDATE supplier_edr_profiles SET last_google_received_at=? WHERE supplier_code=?',
                    (synced_at,item["supplier_code"]))
        if not plan["datetime_gate"]["accepted"]:
            counts["unchanged"] += 1
            continue
        existing = con.execute("SELECT * FROM supplier_edr_profiles WHERE supplier_code=?",
                               (item["supplier_code"],)).fetchone()
        old = dict(existing) if existing else {}
        if plan.get("mirror_clear_fields") and old:
            previous_values = {field: old.get(field, "") or ""
                               for field in plan["mirror_clear_fields"]}
            clear_snapshot = {
                "event_type": "google_mirror_clear",
                "verification_timestamp": item["edr_checked_at"],
                "previous_values": previous_values,
                "new_values": {field: "" for field in plan["mirror_clear_fields"]},
                "source_fingerprint": expected_fingerprint,
            }
            counts["google_mirror_clears"] += len(plan["mirror_clear_fields"])
            counts["google_mirror_clear_events"] += int(_insert_event(
                con, item=item, event_type="google_mirror_clear",
                occurred_at=item["edr_checked_at"], officer=str(item.get("edr_officer") or ""),
                source=f"Google Sheets: {item['source_sheet']}",
                changed_fields=list(plan["mirror_clear_fields"]), snapshot=clear_snapshot,
                created_at=synced_at))
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
        effective = effective_profile_fields(plan, old)
        effective["last_google_received_at"] = synced_at
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
                # Do not re-write unchanged legacy fields during an unrelated row move.
                assignments = [f"{field}=?" for field in changed]
                assignments.extend(("source_sheet=?", "source_row=?", "synced_at=?"))
                con.execute(f"UPDATE supplier_edr_profiles SET {','.join(assignments)} WHERE supplier_code=?",
                            [*(effective[field] for field in changed), item["source_sheet"], item["source_row"], synced_at,
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
            if plan["verification_decision"] == "same_date_officer_update_accepted":
                event_snapshot["same_day_officer_update"] = True
            if plan["factual_status_protected"]:
                event_snapshot["edr_status"] = ""  # The same-day event carries I/L only.
            counts["verification_events"] += int(_insert_event(
                con, item=item, event_type="google_clarity", occurred_at=item["edr_checked_at"],
                officer=item["edr_officer"], source=f"Google Sheets: {item['source_sheet']}",
                changed_fields=plan["changed_fields"], snapshot=event_snapshot, created_at=synced_at))
        if plan["manager_change_kind"] == "representation_enrichment" and enrich_manager:
            result = enrich_manager(con, item["supplier_code"], effective["manager_name"],
                                    f"Google Sheets: {item['source_sheet']}", normalized_date(item["edr_checked_at"]))
            if result.get("enriched"):
                counts["manager_representation_enrichments"] += 1
        elif plan["manager_change_kind"] == "manager_reestablished" and (reestablish_manager or establish_manager):
            callback = reestablish_manager or establish_manager
            result = callback(con, item["supplier_code"], effective["manager_name"],
                              f"Google Sheets: {item['source_sheet']}", normalized_date(item["edr_checked_at"]))
            if result.get("reestablished") or result.get("established"):
                counts["manager_reestablishments"] += 1
        elif plan["manager_change_kind"] == "missing_current_manager" and establish_manager:
            result = establish_manager(con, item["supplier_code"], effective["manager_name"],
                                       f"Google Sheets: {item['source_sheet']}", normalized_date(item["edr_checked_at"]))
            if result.get("established"):
                counts["newly_established_managers"] += 1
        elif plan["manager_change_kind"] == "real_identity_change" and sync_manager:
            result = sync_manager(con, item["supplier_code"], effective["manager_name"],
                                  f"Google Sheets: {item['source_sheet']}", normalized_date(item["edr_checked_at"]))
            if result.get("changed"):
                counts["manager_changes"] += 1
                counts["manager_identity_changes"] += 1
                if refresh_manager_controls:
                    refresh_manager_controls(con, item["supplier_code"])
                if reconcile_manager_nazk:
                    reconcile_manager_nazk(con, item["supplier_code"])
                    counts["nazk_manager_reconciliations"] += 1
    return {**counts, "source_fingerprint": expected_fingerprint,
            "processed": preview["summary"]["total_rows"], "preview_summary": preview["summary"]}
