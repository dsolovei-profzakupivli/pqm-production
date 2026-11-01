"""Audited manual supplier classification, layered over automatic v3 evidence."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import supplier_classification

SUBJECT_TYPES = frozenset({
    "individual_entrepreneur", "legal_entity", "branch", "representative_office",
    "joint_activity", "association", "other", "unknown",
})
RESIDENCIES = frozenset({"UA", "nonresident", "unknown"})
GROUPS = frozenset({"fop", "legal_other", "nonresident", "unresolved"})
LEGAL_OTHER_TYPES = SUBJECT_TYPES - {"individual_entrepreneur", "unknown"}

SUBJECT_LABELS = {
    "individual_entrepreneur": "ФОП", "legal_entity": "Юридична особа",
    "branch": "Філія / відокремлений підрозділ",
    "representative_office": "Представництво",
    "joint_activity": "Спільна діяльність за договором",
    "association": "Об'єднання учасників", "other": "Інший суб'єкт",
    "unknown": "Не визначено",
}
RESIDENCY_LABELS = {"UA": "Україна", "nonresident": "Нерезидент", "unknown": "Не визначено"}
GROUP_LABELS = {"fop": "ФОП", "legal_other": "ЮО та інші",
                "nonresident": "Нерезиденти", "unresolved": "Потребує уточнення"}


def ensure_schema(con) -> None:
    """Add two append-only audit tables; safe to call on every application start."""
    con.executescript("""
      CREATE TABLE IF NOT EXISTS supplier_manual_classifications (
        supplier_code TEXT PRIMARY KEY,
        subject_type TEXT NOT NULL,
        residency TEXT NOT NULL,
        google_group TEXT NOT NULL,
        revision INTEGER NOT NULL CHECK(revision > 0),
        is_active INTEGER NOT NULL CHECK(is_active IN (0,1)),
        changed_by TEXT NOT NULL,
        changed_officer_id INTEGER NOT NULL,
        changed_officer_name TEXT NOT NULL,
        changed_at TEXT NOT NULL,
        prior_value_json TEXT NOT NULL DEFAULT '{}'
      );
      CREATE TABLE IF NOT EXISTS supplier_manual_classification_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        supplier_code TEXT NOT NULL,
        revision INTEGER NOT NULL,
        action TEXT NOT NULL CHECK(action IN ('set','change','cancel')),
        old_value_json TEXT NOT NULL,
        new_value_json TEXT NOT NULL,
        changed_by TEXT NOT NULL,
        changed_officer_id INTEGER NOT NULL,
        changed_officer_name TEXT NOT NULL,
        changed_at TEXT NOT NULL,
        UNIQUE(supplier_code, revision)
      );
      CREATE INDEX IF NOT EXISTS ix_supplier_manual_classification_events_code
        ON supplier_manual_classification_events(supplier_code, revision);
    """)


def derive_group(subject_type: str, residency: str) -> str:
    if subject_type not in SUBJECT_TYPES or residency not in RESIDENCIES:
        raise ValueError("Невідомий тип суб'єкта або статус резидентства")
    if residency == "nonresident":
        return "nonresident"
    if residency != "UA" or subject_type == "unknown":
        return "unresolved"
    return "fop" if subject_type == "individual_entrepreneur" else "legal_other"


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_code(value) -> str:
    if not isinstance(value, str):
        raise ValueError("Код постачальника має бути текстом")
    code = value
    if not code or code != code.strip() or len(code) > 64 or any(ord(ch) < 32 for ch in code):
        raise ValueError("Некоректний текстовий код постачальника")
    return code


def _json_value(row) -> dict | None:
    if not row or not row["is_active"]:
        return None
    return {"subject_type": row["subject_type"], "residency": row["residency"],
            "google_group": row["google_group"], "revision": int(row["revision"]),
            "changed_by": row["changed_by"], "changed_officer_id": int(row["changed_officer_id"]),
            "changed_officer_name": row["changed_officer_name"], "changed_at": row["changed_at"]}


def _automatic_value(automatic: dict) -> dict:
    subject = "individual_entrepreneur" if automatic.get("subject_nature") == "fop" else (
        "legal_entity" if automatic.get("subject_nature") == "not_fop" else "unknown")
    residency = "UA" if automatic.get("registration_country") == "UA" else (
        "nonresident" if automatic.get("classification_status") == "nonresident" else "unknown")
    return {"subject_type": subject, "residency": residency,
            "google_group": derive_group(subject, residency), "source": "automatic_v3"}


def current_record(con, supplier_code: str):
    return con.execute("SELECT * FROM supplier_manual_classifications WHERE supplier_code=?",
                       (_clean_code(supplier_code),)).fetchone()


def build_index(con) -> dict[str, dict]:
    tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "supplier_manual_classifications" not in tables:
        return {}
    result = {}
    for raw in con.execute("SELECT * FROM supplier_manual_classifications"):
        row = dict(raw)
        result[row["supplier_code"]] = row
    return result


def apply_effective(automatic: dict, manual_row: dict | None) -> dict:
    """Preserve v3 output as automatic_* and expose an effective legacy writer route."""
    out = dict(automatic)
    if manual_row is not None and not isinstance(manual_row, dict):
        manual_row = dict(manual_row)
    manual = _json_value(manual_row) if manual_row else None
    revision = int((manual_row or {}).get("revision", 0))
    out.update({
        "automatic_entity_type": automatic.get("entity_type", "unknown"),
        "automatic_classification_status": automatic.get("classification_status", "needs_review"),
        "automatic_classification_reason": automatic.get("classification_reason", ""),
        "automatic_subject_nature": automatic.get("subject_nature", "unknown"),
        "automatic_registration_country": automatic.get("registration_country", ""),
        "manual_classification": manual,
        "manual_classification_revision": revision,
        "classification_source": "manual" if manual else "automatic_v3",
    })
    if not manual:
        subject = ("individual_entrepreneur" if automatic.get("subject_nature") == "fop" else
                   "legal_entity" if automatic.get("subject_nature") == "not_fop" else "unknown")
        residency = ("UA" if automatic.get("registration_country") == "UA" else
                     "nonresident" if automatic.get("classification_status") == "nonresident" else "unknown")
        group = derive_group(subject, residency)
        out.update(effective_subject_type=subject, residency_status=residency,
                   google_sheet_group=group, google_sheet_group_label=GROUP_LABELS[group],
                   effective_subject_type_label=SUBJECT_LABELS[subject],
                   residency_label=RESIDENCY_LABELS[residency])
        return out

    subject = manual["subject_type"]
    residency = manual["residency"]
    group = derive_group(subject, residency)
    # Fail closed if persisted derived routing was corrupted or is from an
    # unsupported future contract; the operator must re-save a current decision.
    if manual["google_group"] != group:
        group = "unresolved"
    out.update(effective_subject_type=subject, residency_status=residency,
               google_sheet_group=group, google_sheet_group_label=GROUP_LABELS[group],
               effective_subject_type_label=SUBJECT_LABELS[subject],
               residency_label=RESIDENCY_LABELS[residency])
    if group == "fop":
        out.update(entity_type="individual_entrepreneur", classification_status="resolved",
                   classification_reason="manual_classification_confirmed", target_sheet="ФОП",
                   append_allowed=True, subject_nature="fop")
    elif group == "legal_other":
        out.update(entity_type="legal_entity", classification_status="resolved",
                   classification_reason="manual_classification_confirmed", target_sheet="ЮО",
                   append_allowed=True, subject_nature="not_fop")
    elif group == "nonresident":
        out.update(entity_type="foreign_legal_entity", classification_status="nonresident",
                   classification_reason="manual_nonresident_append_blocked", target_sheet=None,
                   append_allowed=False)
    else:
        out.update(entity_type="unknown", classification_status="needs_review",
                   classification_reason="manual_classification_incomplete", target_sheet=None,
                   append_allowed=False)
    return out


def detail(automatic: dict, manual_row: dict | None) -> dict:
    effective = apply_effective(automatic, manual_row)
    manual = effective["manual_classification"]
    return {
        "automatic": {
            "subject_type": effective["automatic_entity_type"],
            "subject_nature": effective["automatic_subject_nature"],
            "status": effective["automatic_classification_status"],
            "reason": effective["automatic_classification_reason"],
            "reason_label": effective.get("classification_reason_label", ""),
            "residency": effective["automatic_registration_country"] or "unknown",
        },
        "manual": manual,
        "effective": {
            "subject_type": effective["effective_subject_type"],
            "subject_type_label": effective["effective_subject_type_label"],
            "residency": effective["residency_status"],
            "residency_label": effective["residency_label"],
            "google_group": effective["google_sheet_group"],
            "google_group_label": effective["google_sheet_group_label"],
            "target_sheet": effective.get("target_sheet"),
            "append_allowed": bool(effective.get("append_allowed")),
            "source": effective["classification_source"],
            "revision": effective["manual_classification_revision"],
        },
        "history": [],
    }


def history(con, supplier_code: str) -> list[dict]:
    code = _clean_code(supplier_code)
    rows = con.execute("""SELECT revision,action,old_value_json,new_value_json,changed_by,
      changed_officer_id,changed_officer_name,changed_at
      FROM supplier_manual_classification_events WHERE supplier_code=? ORDER BY revision DESC""", (code,))
    result = []
    for row in rows:
        item = dict(row)
        item["old_value"] = json.loads(item.pop("old_value_json"))
        item["new_value"] = json.loads(item.pop("new_value_json"))
        result.append(item)
    return result


def known_codes(con) -> set[str]:
    codes = set()
    for table in ("submissions", "supplier_edr_profiles", "supplier_registry_summary", "registry_contracts"):
        if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
            codes.update(row[0] for row in con.execute(
                f"SELECT DISTINCT supplier_code FROM {table} WHERE supplier_code IS NOT NULL AND supplier_code<>''"))
    return codes


def preview_many(con, supplier_codes: list[str], subject_type: str, residency: str) -> list[dict]:
    if not isinstance(supplier_codes, list) or not supplier_codes or len(supplier_codes) > 1000:
        raise ValueError("Потрібно вибрати від 1 до 1000 постачальників")
    if subject_type not in SUBJECT_TYPES or residency not in RESIDENCIES:
        raise ValueError("Невідомий тип суб'єкта або статус резидентства")
    group = derive_group(subject_type, residency)
    codes = [_clean_code(code) for code in supplier_codes]
    if len(codes) != len(set(codes)):
        raise ValueError("У списку є повторні коди постачальників")
    known = known_codes(con)
    automatic_index = supplier_classification.build_index(con)
    manual_index = build_index(con)
    result = []
    for code in codes:
        if code not in known:
            raise KeyError(code)
        current = manual_index.get(code)
        revision = int(current["revision"]) if current else 0
        automatic = supplier_classification.resolve(automatic_index, code)
        old = apply_effective(automatic, current)
        result.append({
            "supplier_code": code,
            "expected_revision": revision,
            "previous_type": old["effective_subject_type"],
            "previous_type_label": old["effective_subject_type_label"],
            "previous_group": old["google_sheet_group"],
            "previous_group_label": old["google_sheet_group_label"],
            "manual_decision_exists": bool(current and current["is_active"]),
            "new_type": subject_type,
            "new_type_label": SUBJECT_LABELS[subject_type],
            "new_residency": residency,
            "new_residency_label": RESIDENCY_LABELS[residency],
            "new_group": group,
            "new_group_label": GROUP_LABELS[group],
        })
    return result


def save_many(con, decisions: list[dict], *, actor: str, officer_id: int,
              officer_name: str, confirm_replace: bool = False, cancel: bool = False) -> list[dict]:
    if not isinstance(decisions, list) or not decisions or len(decisions) > 1000:
        raise ValueError("Потрібно вибрати від 1 до 1000 постачальників")
    if not actor or not isinstance(actor, str) or not isinstance(officer_name, str) or not officer_name.strip():
        raise ValueError("Не вдалося достовірно визначити УО")
    try:
        officer_id = int(officer_id)
    except (TypeError, ValueError):
        raise ValueError("Не вдалося достовірно визначити УО") from None
    seen = set()
    normalized = []
    for item in decisions:
        if not isinstance(item, dict):
            raise ValueError("Некоректний список рішень")
        code = _clean_code(item.get("supplier_code"))
        if code in seen:
            raise ValueError("Постачальник повторюється у списку")
        seen.add(code)
        expected = item.get("expected_revision")
        if type(expected) is not int or expected < 0:
            raise ValueError("Потрібна актуальна ревізія кожного рішення")
        if cancel:
            normalized.append({"supplier_code": code, "expected_revision": expected})
            continue
        subject, residency = item.get("subject_type"), item.get("residency")
        if subject not in SUBJECT_TYPES or residency not in RESIDENCIES:
            raise ValueError("Невідомий тип суб'єкта або статус резидентства")
        normalized.append({"supplier_code": code, "expected_revision": expected,
                           "subject_type": subject, "residency": residency,
                           "google_group": derive_group(subject, residency)})

    if not con.in_transaction:
        con.execute("BEGIN IMMEDIATE")
    officer = con.execute("SELECT full_name,active FROM authorized_officers WHERE id=?", (officer_id,)).fetchone()
    if not officer or not officer["active"] or officer["full_name"] != officer_name:
        raise ValueError("УО не знайдено або її обліковий запис неактивний")
    known = known_codes(con)
    automatic_index = supplier_classification.build_index(con)
    for item in normalized:
        if item["supplier_code"] not in known:
            raise KeyError(item["supplier_code"])
        current = con.execute("SELECT * FROM supplier_manual_classifications WHERE supplier_code=?",
                              (item["supplier_code"],)).fetchone()
        revision = int(current["revision"]) if current else 0
        if revision != item["expected_revision"]:
            raise RevisionConflict(item["supplier_code"], revision)
        if not cancel and current and current["is_active"] and not confirm_replace:
            raise ExistingManualDecision(item["supplier_code"])

    results = []
    for item in normalized:
        code = item["supplier_code"]
        current = con.execute("SELECT * FROM supplier_manual_classifications WHERE supplier_code=?", (code,)).fetchone()
        old_manual = _json_value(current) if current else None
        old_value = old_manual or _automatic_value(supplier_classification.resolve(automatic_index, code))
        revision = int(current["revision"]) if current else 0
        if cancel:
            if not current or not current["is_active"]:
                results.append({"supplier_code": code, "revision": revision, "changed": False})
                continue
            next_revision = revision + 1
            now = _stamp()
            prior = json.dumps(old_value, ensure_ascii=False, sort_keys=True)
            con.execute("""UPDATE supplier_manual_classifications SET revision=?,is_active=0,
              changed_by=?,changed_officer_id=?,changed_officer_name=?,changed_at=?,prior_value_json=?
              WHERE supplier_code=? AND revision=?""",
              (next_revision, actor, officer_id, officer_name.strip(), now, prior, code, revision))
            new_value = None
            action = "cancel"
        else:
            same = bool(current and current["is_active"] and
                        current["subject_type"] == item["subject_type"] and
                        current["residency"] == item["residency"] and
                        current["google_group"] == item["google_group"])
            if same:
                results.append({"supplier_code": code, "revision": revision, "changed": False})
                continue
            next_revision = revision + 1
            now = _stamp()
            prior = json.dumps(old_value, ensure_ascii=False, sort_keys=True)
            con.execute("""INSERT INTO supplier_manual_classifications
              (supplier_code,subject_type,residency,google_group,revision,is_active,changed_by,
               changed_officer_id,changed_officer_name,changed_at,prior_value_json)
              VALUES (?,?,?,?,?,1,?,?,?,?,?)
              ON CONFLICT(supplier_code) DO UPDATE SET subject_type=excluded.subject_type,
               residency=excluded.residency,google_group=excluded.google_group,revision=excluded.revision,
               is_active=1,changed_by=excluded.changed_by,changed_officer_id=excluded.changed_officer_id,
               changed_officer_name=excluded.changed_officer_name,changed_at=excluded.changed_at,
               prior_value_json=excluded.prior_value_json""",
              (code, item["subject_type"], item["residency"], item["google_group"], next_revision,
               actor, officer_id, officer_name.strip(), now, prior))
            new_value = {"subject_type": item["subject_type"], "residency": item["residency"],
                         "google_group": item["google_group"], "revision": next_revision,
                         "changed_by": actor, "changed_officer_id": officer_id,
                         "changed_officer_name": officer_name.strip(), "changed_at": now}
            action = "change" if old_manual else "set"
        old_json = json.dumps(old_value, ensure_ascii=False, sort_keys=True)
        new_json = json.dumps(new_value, ensure_ascii=False, sort_keys=True) if new_value else "{}"
        con.execute("""INSERT INTO supplier_manual_classification_events
          (supplier_code,revision,action,old_value_json,new_value_json,changed_by,
           changed_officer_id,changed_officer_name,changed_at) VALUES (?,?,?,?,?,?,?,?,?)""",
          (code, next_revision, action, old_json, new_json, actor, officer_id, officer_name.strip(), now))
        results.append({"supplier_code": code, "revision": next_revision, "changed": True})
    return results


class RevisionConflict(ValueError):
    def __init__(self, supplier_code: str, current_revision: int):
        super().__init__(f"Рішення для постачальника {supplier_code} вже змінено; оновіть картку")
        self.supplier_code, self.current_revision = supplier_code, current_revision


class ExistingManualDecision(ValueError):
    def __init__(self, supplier_code: str):
        super().__init__(f"Для постачальника {supplier_code} вже є ручне рішення; підтвердіть його заміну")
        self.supplier_code = supplier_code
