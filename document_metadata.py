"""Configurable metadata attached to generated document versions."""
import json
import re
from datetime import datetime, timezone

from protocol_template import TOKEN

ASKOD_SHORT_SUMMARY = "askod_short_summary"
PROTOCOL_SUBJECT = "protocol_subject"
VIOLATION_REVIEW_PROTOCOL = "violation_review_protocol"
KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


class MetadataConflict(ValueError):
    pass


DEFAULTS = {
    "nazk_supplier_request": {ASKOD_SHORT_SUMMARY: {
        "label": "Короткий зміст АСКОД",
        "description": "Короткий зміст сформованого запиту для зовнішньої реєстрації.",
        "template_text": "Запит до {{supplier.short_name}} щодо надання довідки з Реєстру НАЗК",
    }},
    VIOLATION_REVIEW_PROTOCOL: {PROTOCOL_SUBJECT: {
        "label": "Тема протоколу / короткий зміст",
        "description": "Тема сформованого протоколу розгляду звернення.",
        "template_text": (
            "Розгляд звернення {{report_id}} по закупівлі {{tender_id}} "
            "{{customer.short_name}} (на {{supplier.short_name}}; {{supplier.code}})"
        ),
    }},
}


def _columns(con, table):
    return {row[1] for row in con.execute(f"PRAGMA table_info({table})")}


def migrate(con):
    con.executescript("""CREATE TABLE IF NOT EXISTS document_metadata_templates (
      document_type TEXT NOT NULL, metadata_key TEXT NOT NULL, label TEXT NOT NULL,
      template_text TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1,
      updated_at TEXT NOT NULL, updated_by TEXT NOT NULL,
      description TEXT NOT NULL DEFAULT '', active INTEGER NOT NULL DEFAULT 1,
      created_at TEXT NOT NULL DEFAULT '', created_by TEXT NOT NULL DEFAULT '',
      PRIMARY KEY(document_type,metadata_key));
      CREATE TABLE IF NOT EXISTS document_metadata_template_events (
      id INTEGER PRIMARY KEY AUTOINCREMENT, document_type TEXT NOT NULL,
      metadata_key TEXT NOT NULL, old_template_text TEXT, new_template_text TEXT NOT NULL,
      changed_at TEXT NOT NULL, changed_by TEXT NOT NULL,
      action TEXT NOT NULL DEFAULT 'updated', old_config_json TEXT, new_config_json TEXT);
    """)
    for name, definition in {
        "description": "TEXT NOT NULL DEFAULT ''", "active": "INTEGER NOT NULL DEFAULT 1",
        "created_at": "TEXT NOT NULL DEFAULT ''", "created_by": "TEXT NOT NULL DEFAULT ''",
    }.items():
        if name not in _columns(con, "document_metadata_templates"):
            con.execute(f"ALTER TABLE document_metadata_templates ADD COLUMN {name} {definition}")
    for name, definition in {
        "action": "TEXT NOT NULL DEFAULT 'updated'", "old_config_json": "TEXT", "new_config_json": "TEXT",
    }.items():
        if name not in _columns(con, "document_metadata_template_events"):
            con.execute(f"ALTER TABLE document_metadata_template_events ADD COLUMN {name} {definition}")
    stamp = datetime.now(timezone.utc).isoformat()
    for document_type, metadata in DEFAULTS.items():
        for key, item in metadata.items():
            con.execute("""INSERT OR IGNORE INTO document_metadata_templates
              (document_type,metadata_key,label,description,template_text,active,version,
               created_at,created_by,updated_at,updated_by)
              VALUES(?,?,?,?,?,1,1,?,'system-default',?,'system-default')""",
              (document_type, key, item["label"], item.get("description", ""),
               item["template_text"], stamp, stamp))
            con.execute("""UPDATE document_metadata_templates SET description=?,
              created_at=COALESCE(NULLIF(created_at,''),updated_at),
              created_by=COALESCE(NULLIF(created_by,''),updated_by)
              WHERE document_type=? AND metadata_key=? AND TRIM(description)=''""",
              (item.get("description", ""), document_type, key))


def _field_index(fields):
    return {field["key"]: field for field in fields}


def validate_template(template_text, fields, document_type):
    text = str(template_text or "").strip()
    if not text:
        raise ValueError("Шаблон тексту не може бути порожнім")
    keys = [match.group(1) for match in TOKEN.finditer(text)]
    remainder = TOKEN.sub("", text)
    if "{{" in remainder or "}}" in remainder:
        raise ValueError("Непідтримуваний або незбалансований placeholder у метаданих")
    index = _field_index(fields)
    for key in keys:
        field = index.get(key)
        if not field:
            raise ValueError(f"Невідоме поле метаданих: {key}")
        if field.get("binding_status") != "VALID" or field.get("source_binding", {}).get("source_type") == "unbound":
            raise ValueError(f"Поле не має runtime binding: {key}")
        if not field.get("active") or field.get("deprecated"):
            raise ValueError(f"Поле неактивне: {key}")
        if document_type not in field.get("available_for", []):
            raise ValueError(f"Поле недоступне для цього типу документа: {key}")
    return sorted(set(keys))


def validate_definition(document_type, metadata_key, label, template_text, fields, runtime_document_types):
    document_type, metadata_key, label = (str(value or "").strip()
                                           for value in (document_type, metadata_key, label))
    if document_type not in set(runtime_document_types):
        raise ValueError("Тип документа не зареєстрований у runtime")
    if not KEY_RE.fullmatch(metadata_key):
        raise ValueError("Key має починатися з малої латинської літери та містити лише a–z, 0–9 і _")
    if not label:
        raise ValueError("Назва метаданих не може бути порожньою")
    return validate_template(template_text, fields, document_type)


def templates(con, document_type=None, active_only=False):
    where, args = [], []
    if document_type:
        where.append("document_type=?"); args.append(document_type)
    if active_only:
        where.append("active=1")
    sql = "SELECT * FROM document_metadata_templates"
    if where:
        sql += " WHERE " + " AND ".join(where)
    # rowid is the persisted creation order for configs without display_order.
    sql += " ORDER BY document_type,COALESCE(NULLIF(created_at,''),updated_at),rowid"
    return [dict(row) for row in con.execute(sql, tuple(args))]


def render(template_text, values):
    def replacement(match):
        key = match.group(1)
        value = values.get(key)
        if value is None or not str(value).strip():
            raise ValueError(f"Не заповнено поле метаданих: {key}")
        return str(value)
    return TOKEN.sub(replacement, template_text)


def resolve_all(con, document_type, fields, resolver):
    result = {}
    for item in templates(con, document_type, active_only=True):
        keys = validate_template(item["template_text"], fields, document_type)
        values = resolver(keys)
        result[item["metadata_key"]] = {
            "label": item["label"], "value": render(item["template_text"], values),
            "config_version": item["version"],
        }
    return result


def resolved_items(metadata):
    """Normalize persisted per-document metadata for generic card rendering."""
    if not isinstance(metadata, dict):
        return []
    result = []
    for order, (metadata_key, raw) in enumerate(metadata.items()):
        item = raw if isinstance(raw, dict) else {}
        value = item.get("value", item.get("resolved_text"))
        if value is None or not str(value).strip():
            continue
        try:
            version = int(item.get("config_version") or item.get("version") or 1)
        except (TypeError, ValueError):
            version = 1
        result.append({
            "metadata_key": str(metadata_key),
            "label": str(item.get("label") or metadata_key),
            "resolved_text": str(value),
            "version": version,
            "display_order": order,
        })
    return result


def registered_document_types(runtime_templates):
    result = set(DEFAULTS)
    for key, config in dict(runtime_templates or {}).items():
        result.add(str(config.get("document_type") or key))
    return result


def document_type_catalog(runtime_templates):
    labels = {"nazk_supplier_request": "НАЗК — запит постачальнику",
              VIOLATION_REVIEW_PROTOCOL: "Протокол розгляду звернення"}
    result = []
    for key in sorted(registered_document_types(runtime_templates)):
        config = next((value for name, value in dict(runtime_templates or {}).items()
                       if str(value.get("document_type") or name) == key), {})
        result.append({"key": key, "label": str(config.get("name") or labels.get(key) or key)})
    return result


def _metadata_used(con, document_type, metadata_key):
    tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "generated_documents" in tables:
        for row in con.execute("SELECT metadata_json FROM generated_documents WHERE document_type=?", (document_type,)):
            try:
                if metadata_key in json.loads(row[0] or "{}"):
                    return True
            except (TypeError, json.JSONDecodeError):
                pass
    if (document_type == VIOLATION_REVIEW_PROTOCOL and "violation_report_reviews" in tables
            and "generated_protocol_metadata_json" in _columns(con, "violation_report_reviews")):
        for row in con.execute("SELECT generated_protocol_metadata_json FROM violation_report_reviews"):
            try:
                if metadata_key in json.loads(row[0] or "{}"):
                    return True
            except (TypeError, json.JSONDecodeError):
                pass
    return False


def _public_item(con, item, fields):
    result = dict(item)
    result["used"] = _metadata_used(con, item["document_type"], item["metadata_key"])
    result["fields"] = [{"key": field["key"], "label": field["label"],
      "description": field.get("description", ""), "group": field.get("group", "")}
      for field in fields if field.get("binding_status") == "VALID" and field.get("active")
      and not field.get("deprecated") and item["document_type"] in field.get("available_for", [])]
    try:
        result["used_fields"] = validate_template(item["template_text"], fields, item["document_type"])
        result["validation_error"] = ""
    except ValueError as exc:
        result["used_fields"], result["validation_error"] = [], str(exc)
    return result


def admin_catalog(con, fields, runtime_templates):
    types = document_type_catalog(runtime_templates)
    allowed = {item["key"] for item in types}
    return {"document_types": types,
            "items": [_public_item(con, item, fields) for item in templates(con)
                      if item["document_type"] in allowed]}


def _event(con, old, new, actor, action):
    con.execute("""INSERT INTO document_metadata_template_events
      (document_type,metadata_key,old_template_text,new_template_text,changed_at,changed_by,
       action,old_config_json,new_config_json) VALUES(?,?,?,?,?,?,?,?,?)""",
      (new["document_type"], new["metadata_key"], old.get("template_text") if old else None,
       new["template_text"], datetime.now(timezone.utc).isoformat(), actor, action,
       json.dumps(old, ensure_ascii=False) if old else None, json.dumps(new, ensure_ascii=False)))


def create(con, payload, fields, runtime_document_types, actor):
    document_type = str(payload.get("document_type") or "").strip()
    metadata_key = str(payload.get("metadata_key") or "").strip()
    label = str(payload.get("label") or "").strip()
    description = str(payload.get("description") or "").strip()
    text = str(payload.get("template_text") or "").strip()
    active = 1 if payload.get("active", True) else 0
    used_fields = validate_definition(document_type, metadata_key, label, text, fields, runtime_document_types)
    if con.execute("SELECT 1 FROM document_metadata_templates WHERE document_type=? AND metadata_key=?",
                   (document_type, metadata_key)).fetchone():
        raise MetadataConflict("Метадані з таким key уже існують для цього типу документа")
    stamp = datetime.now(timezone.utc).isoformat()
    con.execute("""INSERT INTO document_metadata_templates
      (document_type,metadata_key,label,description,template_text,active,version,
       created_at,created_by,updated_at,updated_by) VALUES(?,?,?,?,?,?,1,?,?,?,?)""",
      (document_type, metadata_key, label, description, text, active, stamp, actor, stamp, actor))
    item = dict(con.execute("SELECT * FROM document_metadata_templates WHERE document_type=? AND metadata_key=?",
                            (document_type, metadata_key)).fetchone())
    _event(con, None, item, actor, "created")
    return item, used_fields


def update(con, document_type, metadata_key, changes, fields, runtime_document_types, actor):
    if document_type not in set(runtime_document_types):
        raise ValueError("Тип документа не зареєстрований у runtime")
    row = con.execute("SELECT * FROM document_metadata_templates WHERE document_type=? AND metadata_key=?",
                      (document_type, metadata_key)).fetchone()
    if not row:
        raise KeyError(metadata_key)
    old = dict(row)
    label = str(changes.get("label", old["label"]) or "").strip()
    description = str(changes.get("description", old.get("description", "")) or "").strip()
    text = str(changes.get("template_text", old["template_text"]) or "").strip()
    active = int(bool(changes.get("active", bool(old.get("active", 1)))))
    used_fields = validate_definition(document_type, metadata_key, label, text, fields, runtime_document_types)
    if (label, description, text, active) == (old["label"], old.get("description", ""),
                                               old["template_text"], int(old.get("active", 1))):
        return old, False, used_fields
    stamp = datetime.now(timezone.utc).isoformat()
    version = int(old["version"]) + 1
    con.execute("""UPDATE document_metadata_templates SET label=?,description=?,template_text=?,active=?,
      version=?,updated_at=?,updated_by=? WHERE document_type=? AND metadata_key=?""",
      (label, description, text, active, version, stamp, actor, document_type, metadata_key))
    item = dict(con.execute("SELECT * FROM document_metadata_templates WHERE document_type=? AND metadata_key=?",
                            (document_type, metadata_key)).fetchone())
    action = ("deactivated" if old.get("active", 1) and not active else
              "activated" if not old.get("active", 1) and active else "updated")
    _event(con, old, item, actor, action)
    return item, True, used_fields


def save(con, document_type, metadata_key, template_text, fields, runtime_document_types, actor):
    item, changed, _ = update(con, document_type, metadata_key, {"template_text": template_text},
                              fields, runtime_document_types, actor)
    return item, changed
