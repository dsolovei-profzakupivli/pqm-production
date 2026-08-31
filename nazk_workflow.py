"""NАЗК workflow services shared by HTTP handlers, reconciliation and tests."""

from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter
from datetime import datetime, timezone


OPEN_WORKFLOW_STATUSES = {"needs_review", "request_to_supplier", "request_to_nazk", "waiting_response"}


def get_supplier_nazk_presentation_state(
    application_state: str | None, workflow_status: str | None,
    *, registry_match: bool, legacy_result: str | None = None,
) -> str:
    """Combine application work, transitional workflow and registry history for one badge."""
    application_state = str(application_state or "not_required")
    workflow_status = str(workflow_status or "")
    legacy_result = str(legacy_result or "").strip().casefold()
    if workflow_status == "waiting_response":
        return "waiting_response"
    if workflow_status in {"request_to_supplier", "request_to_nazk"}:
        return "on_request"
    if workflow_status == "needs_review":
        return "needs_supplier_review"
    # A completed supplier-level result describes the registry risk already
    # investigated. A new submission may still require its own document check,
    # but that must not erase or downgrade this supplier-level result. A truly
    # new registry risk is represented by a newer open workflow above.
    if legacy_result in {"підтверджено", "confirmed"}:
        return "confirmed"
    if legacy_result in {"спростовано", "ні", "refuted"}:
        return "refuted"
    if application_state in {"needs_check", "refuted", "confirmed"}:
        return application_state
    return "inactive" if registry_match else "not_required"


def mark_supplier_nazk_request_sent(
    con: sqlite3.Connection, check_id: int, *, changed_by: str,
    comment: str = "", timestamp: str | None = None,
) -> dict:
    """Record an externally sent request without creating a document workflow in PQM."""
    row = con.execute("SELECT * FROM supplier_nazk_checks WHERE id=?", (check_id,)).fetchone()
    if not row:
        raise ValueError("Supplier-level перевірку НАЗК не знайдено")
    if row["workflow_status"] == "waiting_response":
        return {"check": dict(row), "changed": False}
    if row["workflow_status"] != "needs_review":
        raise ValueError("Запит можна позначити направленим лише зі стану needs_review")
    timestamp = timestamp or now_iso()
    new_comment = str(comment or "").strip() or str(row["comment"] or "")
    con.execute(
        """UPDATE supplier_nazk_checks SET workflow_status='waiting_response',comment=?,
           updated_at=?,updated_by=? WHERE id=?""",
        (new_comment, timestamp, changed_by, check_id),
    )
    con.execute(
        """INSERT INTO supplier_nazk_check_events
           (check_id,event_type,event_at,event_by,old_workflow_status,new_workflow_status,details_json)
           VALUES (?,'request_sent_manually',?,?,?,'waiting_response',?)""",
        (check_id, timestamp, changed_by, row["workflow_status"],
         json.dumps({"comment": str(comment or "").strip()}, ensure_ascii=False)),
    )
    return {"check": dict(con.execute("SELECT * FROM supplier_nazk_checks WHERE id=?", (check_id,)).fetchone()),
            "changed": True}


def complete_supplier_nazk_check(
    con: sqlite3.Connection, check_id: int, *, result: str, evidence_date: str,
    document_url: str, checked_by: str, comment: str = "",
    document_title: str = "Відповідь за результатами перевірки НАЗК",
    timestamp: str | None = None,
) -> dict:
    """Finish a supplier-level check; never changes qualifications or submissions."""
    result = str(result or "").strip().lower()
    if result not in {"refuted", "confirmed"}:
        raise ValueError("Оберіть результат: Спростовано або Підтверджено")
    if not str(evidence_date or "").strip():
        raise ValueError("Зазначте дату документа/відповіді")
    if not str(document_url or "").strip():
        raise ValueError("Додайте посилання на документ/відповідь")
    row = con.execute("SELECT * FROM supplier_nazk_checks WHERE id=?", (check_id,)).fetchone()
    if not row:
        raise ValueError("Supplier-level перевірку НАЗК не знайдено")
    if row["workflow_status"] == "completed":
        if row["result"] == result:
            return {"check": dict(row), "changed": False}
        raise ValueError("Перевірку вже завершено з іншим результатом")
    if row["workflow_status"] != "waiting_response":
        raise ValueError("Завершити можна лише перевірку, що очікує відповідь")
    timestamp = timestamp or now_iso()
    con.execute(
        """UPDATE supplier_nazk_checks SET workflow_status='completed',result=?,completed_at=?,
           evidence_date=?,comment=?,updated_at=?,updated_by=? WHERE id=?""",
        (result, timestamp, str(evidence_date).strip(), str(comment or "").strip(),
         timestamp, checked_by, check_id),
    )
    con.execute(
        """INSERT INTO supplier_nazk_check_documents
           (check_id,document_type,document_date,title,url,source,created_at,created_by)
           VALUES (?,'supplier_response',?,?,?,'supplier_level_manual',?,?)""",
        (check_id, str(evidence_date).strip(), str(document_title or "").strip(),
         str(document_url).strip(), timestamp, checked_by),
    )
    con.execute(
        """INSERT INTO supplier_nazk_check_events
           (check_id,event_type,event_at,event_by,old_workflow_status,new_workflow_status,new_result,details_json)
           VALUES (?,'supplier_check_completed',?,?,'waiting_response','completed',?,?)""",
        (check_id, timestamp, checked_by, result,
         json.dumps({"evidence_date": str(evidence_date).strip(), "document_url": str(document_url).strip()},
                    ensure_ascii=False)),
    )
    return {"check": dict(con.execute("SELECT * FROM supplier_nazk_checks WHERE id=?", (check_id,)).fetchone()),
            "changed": True}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_name(value: str | None) -> str:
    return " ".join(re.sub(r"[’'`\-]+", " ", str(value or "").casefold()).split())


def registry_matches(con: sqlite3.Connection, manager_name: str) -> list[dict]:
    normalized = normalize_name(manager_name)
    if not normalized:
        return []
    return [dict(row) for row in con.execute(
        """SELECT source_id,full_name,offense_name,court_case_number,sentence_date,punishment_start,decision_url
           FROM nazk_registry WHERE NORMALIZE_NAME(full_name)=? ORDER BY sentence_date,source_id""",
        (normalized,),
    )]


def transitional_submission_backfill_dry_run(
    con: sqlite3.Connection, year: int = 2026,
) -> dict:
    """Find application-level NАЗК controls that may be created after approval.

    This function is intentionally read-only. Historical supplier checks are shown
    as context only and are never attached to an application automatically.
    """
    rows = con.execute(
        """SELECT s.id submission_id,s.supplier_code,s.supplier_name,s.date_published,
                  s.documents_json,s.raw_json,COALESCE(q.status,'') qualification_status,
                  COALESCE(f.pretty_id,f.id) framework_id,COALESCE(af.manager_name,'') manager_name,
                  ctrl.id control_id,COALESCE(ctrl.nazk_certificate_required,0) control_required,
                  COALESCE(ctrl.nazk_certificate_checked,0) control_checked
           FROM submissions s
           JOIN qualifications q ON q.id=s.qualification_id
           LEFT JOIN frameworks f ON f.id=s.framework_id
           LEFT JOIN application_fields af ON af.submission_id=s.id
           LEFT JOIN submission_nazk_controls ctrl ON ctrl.submission_id=s.id
           WHERE substr(COALESCE(s.date_published,''),1,4)=?
             AND lower(COALESCE(q.status,''))='active'
             AND COALESCE(af.manager_name,'')<>''
             AND COALESCE(ctrl.nazk_certificate_checked,0)=0
           ORDER BY s.date_published,s.id""",
        (str(year),),
    ).fetchall()
    registry_by_name: dict[str, list[dict]] = {}
    for registry_row in con.execute(
        """SELECT source_id,full_name,court_case_number,sentence_date,punishment_start,decision_url
           FROM nazk_registry ORDER BY sentence_date,source_id"""
    ):
        registry_by_name.setdefault(normalize_name(registry_row["full_name"]), []).append(dict(registry_row))
    candidates = []
    hints = ("довід", "назк", "коруп", "реєстр")
    for row in rows:
        item = dict(row)
        matches = registry_by_name.get(normalize_name(item["manager_name"]), [])
        if not matches:
            continue
        documents = []
        try:
            raw_documents = json.loads(item.pop("documents_json") or "[]")
        except (TypeError, json.JSONDecodeError):
            raw_documents = []
        for document in raw_documents:
            if not isinstance(document, dict):
                continue
            title = str(document.get("title") or "")
            documents.append({
                "id": str(document.get("id") or ""), "title": title,
                "url": str(document.get("url") or ""),
                "potential_certificate": any(hint in title.casefold() for hint in hints),
            })
        latest = con.execute(
            """SELECT id,workflow_status,result,evidence_date,covered_nazk_date,is_legacy,
                      completed_at,comment
               FROM supplier_nazk_checks
               WHERE supplier_code=? AND NORMALIZE_NAME(manager_name)=?
               ORDER BY COALESCE(completed_at,started_at,created_at) DESC,id DESC LIMIT 1""",
            (item["supplier_code"], normalize_name(item["manager_name"])),
        ).fetchone()
        item.pop("raw_json", None)
        item.update({
            "registry_match_count": len(matches), "registry_matches": matches,
            "documents": documents, "latest_supplier_check": dict(latest) if latest else None,
            "action": "would_create_control" if not item["control_id"] else "existing_unchecked_control",
        })
        candidates.append(item)
    return {
        "mode": "dry_run", "year": year, "candidate_count": len(candidates),
        "writes_performed": 0, "legacy_checks_modified": 0, "candidates": candidates,
    }


def _manager_id(con: sqlite3.Connection, supplier_code: str, manager_name: str) -> int | None:
    row = con.execute(
        """SELECT id FROM supplier_managers
           WHERE supplier_code=? AND normalized_name=?
           ORDER BY is_current DESC,id DESC LIMIT 1""",
        (supplier_code, normalize_name(manager_name)),
    ).fetchone()
    return int(row[0]) if row else None


def get_submission_nazk_control(con: sqlite3.Connection, submission_id: str) -> dict | None:
    row = con.execute(
        "SELECT * FROM submission_nazk_controls WHERE submission_id=?", (submission_id,)
    ).fetchone()
    return dict(row) if row else None


def get_submission_nazk_state(con: sqlite3.Connection, submission_id: str,
                              registry_names: set[str] | None = None) -> dict:
    """Return the authoritative, computed NАЗК state of one application.

    Old supplier-level reviews are deliberately excluded.  A completed result
    is valid only when it is linked to this application and to a document
    selected from this application's own Prozorro documents.
    """
    row = con.execute(
        """SELECT s.id submission_id,s.supplier_code,COALESCE(af.manager_name,'') application_manager,
                  ctrl.id control_id,COALESCE(ctrl.manager_name,'') control_manager,
                  COALESCE(ctrl.nazk_certificate_required,0) required,
                  COALESCE(ctrl.nazk_certificate_checked,0) checked,
                  ctrl.selected_document_id,ctrl.selected_document_url,ctrl.supplier_nazk_check_id,
                  ctrl.checked_at,ctrl.checked_by,COALESCE(ctrl.comment,'') comment,
                  chk.workflow_status,chk.result,chk.evidence_date
           FROM submissions s
           LEFT JOIN application_fields af ON af.submission_id=s.id
           LEFT JOIN submission_nazk_controls ctrl ON ctrl.submission_id=s.id
           LEFT JOIN supplier_nazk_checks chk ON chk.id=ctrl.supplier_nazk_check_id
           WHERE s.id=?""",
        (submission_id,),
    ).fetchone()
    if not row:
        raise KeyError(submission_id)
    item = dict(row)
    manager_name = item["control_manager"] or item["application_manager"]
    registry_match = (
        normalize_name(manager_name) in registry_names
        if manager_name and registry_names is not None
        else bool(registry_matches(con, manager_name)) if manager_name else False
    )
    required = bool(item["required"] or registry_match)
    base = {
        "submission_id": submission_id,
        "supplier_code": item["supplier_code"] or "",
        "manager_name": manager_name,
        "required": required,
        "checked": bool(item["checked"]),
        "control_id": item["control_id"],
        "check_id": item["supplier_nazk_check_id"],
        "selected_document_id": item["selected_document_id"] or "",
        "selected_document_url": item["selected_document_url"] or "",
        "checked_at": item["checked_at"] or "",
        "checked_by": item["checked_by"] or "",
        "comment": item["comment"],
        "evidence_date": item["evidence_date"] or "",
        "workflow_status": item["workflow_status"] or "",
        "result": item["result"] or "",
        "registry_match": registry_match,
    }
    if not required:
        return {**base, "state": "not_required", "can_approve": True, "reason": "not_required"}
    if not item["control_id"]:
        return {**base, "state": "needs_check", "can_approve": False, "reason": "control_missing"}

    selected_document_is_linked = False
    if item["supplier_nazk_check_id"] and (item["selected_document_id"] or item["selected_document_url"]):
        selected_document_is_linked = bool(con.execute(
            """SELECT 1 FROM supplier_nazk_check_documents
               WHERE check_id=? AND submission_id=?
                 AND ((COALESCE(prozorro_document_id,'')<>'' AND prozorro_document_id=?)
                   OR (COALESCE(url,'')<>'' AND url=?)) LIMIT 1""",
            (item["supplier_nazk_check_id"], submission_id,
             item["selected_document_id"] or "", item["selected_document_url"] or ""),
        ).fetchone())
    completed = (
        bool(item["checked"])
        and selected_document_is_linked
        and item["workflow_status"] == "completed"
        and item["result"] in {"refuted", "confirmed"}
    )
    if completed:
        state = item["result"]
        return {**base, "state": state, "can_approve": state == "refuted",
                "reason": "completed_submission_check", "selected_document_is_linked": True}
    return {**base, "state": "needs_check", "can_approve": False,
            "reason": "submission_check_incomplete",
            "selected_document_is_linked": selected_document_is_linked}


def get_submission_nazk_states(con: sqlite3.Connection, submission_ids: list[str],
                               registry_names: set[str] | None = None) -> dict[str, dict]:
    """Batch equivalent of :func:`get_submission_nazk_state` for one page.

    The state rules intentionally mirror the single-submission function.  Only
    the data access changes: controls/checks and linked evidence documents are
    loaded in two set-based queries instead of one or two queries per row.
    """
    ids = list(dict.fromkeys(str(value or "") for value in submission_ids if value))
    if not ids:
        return {}
    placeholders = ",".join("?" for _ in ids)
    rows = con.execute(
        f"""SELECT s.id submission_id,s.supplier_code,COALESCE(af.manager_name,'') application_manager,
                   ctrl.id control_id,COALESCE(ctrl.manager_name,'') control_manager,
                   COALESCE(ctrl.nazk_certificate_required,0) required,
                   COALESCE(ctrl.nazk_certificate_checked,0) checked,
                   ctrl.selected_document_id,ctrl.selected_document_url,ctrl.supplier_nazk_check_id,
                   ctrl.checked_at,ctrl.checked_by,COALESCE(ctrl.comment,'') comment,
                   chk.workflow_status,chk.result,chk.evidence_date
            FROM submissions s
            LEFT JOIN application_fields af ON af.submission_id=s.id
            LEFT JOIN submission_nazk_controls ctrl ON ctrl.submission_id=s.id
            LEFT JOIN supplier_nazk_checks chk ON chk.id=ctrl.supplier_nazk_check_id
            WHERE s.id IN ({placeholders})""",
        ids,
    ).fetchall()
    by_id = {row["submission_id"]: dict(row) for row in rows}
    linked: set[str] = set()
    check_ids = sorted({int(item["supplier_nazk_check_id"]) for item in by_id.values()
                        if item["supplier_nazk_check_id"]})
    if check_ids:
        check_placeholders = ",".join("?" for _ in check_ids)
        for document in con.execute(
            f"""SELECT check_id,submission_id,COALESCE(prozorro_document_id,'') prozorro_document_id,
                       COALESCE(url,'') url
                FROM supplier_nazk_check_documents
                WHERE check_id IN ({check_placeholders})
                  AND submission_id IN ({placeholders})""",
            (*check_ids, *ids),
        ):
            item = by_id.get(document["submission_id"])
            if not item or int(item["supplier_nazk_check_id"] or 0) != int(document["check_id"]):
                continue
            selected_id = item["selected_document_id"] or ""
            selected_url = item["selected_document_url"] or ""
            if ((selected_id and document["prozorro_document_id"] == selected_id)
                    or (selected_url and document["url"] == selected_url)):
                linked.add(document["submission_id"])

    result: dict[str, dict] = {}
    for submission_id in ids:
        item = by_id.get(submission_id)
        if not item:
            continue
        manager_name = item["control_manager"] or item["application_manager"]
        registry_match = (
            normalize_name(manager_name) in registry_names
            if manager_name and registry_names is not None
            else bool(registry_matches(con, manager_name)) if manager_name else False
        )
        required = bool(item["required"] or registry_match)
        base = {
            "submission_id": submission_id,
            "supplier_code": item["supplier_code"] or "",
            "manager_name": manager_name,
            "required": required,
            "checked": bool(item["checked"]),
            "control_id": item["control_id"],
            "check_id": item["supplier_nazk_check_id"],
            "selected_document_id": item["selected_document_id"] or "",
            "selected_document_url": item["selected_document_url"] or "",
            "checked_at": item["checked_at"] or "",
            "checked_by": item["checked_by"] or "",
            "comment": item["comment"],
            "evidence_date": item["evidence_date"] or "",
            "workflow_status": item["workflow_status"] or "",
            "result": item["result"] or "",
            "registry_match": registry_match,
        }
        if not required:
            result[submission_id] = {**base, "state": "not_required", "can_approve": True,
                                     "reason": "not_required"}
            continue
        if not item["control_id"]:
            result[submission_id] = {**base, "state": "needs_check", "can_approve": False,
                                     "reason": "control_missing"}
            continue
        selected_document_is_linked = submission_id in linked
        completed = (
            bool(item["checked"])
            and selected_document_is_linked
            and item["workflow_status"] == "completed"
            and item["result"] in {"refuted", "confirmed"}
        )
        if completed:
            state = item["result"]
            result[submission_id] = {**base, "state": state, "can_approve": state == "refuted",
                                     "reason": "completed_submission_check",
                                     "selected_document_is_linked": True}
        else:
            result[submission_id] = {**base, "state": "needs_check", "can_approve": False,
                                     "reason": "submission_check_incomplete",
                                     "selected_document_is_linked": selected_document_is_linked}
    return result


def get_submission_nazk_presentation_state(state: dict | None) -> str:
    """Map one application's authoritative state to its marker in a framework.

    Supplier-level checks/results are deliberately not accepted here. A registry
    match without a control is informational (``possible``), not an actionable
    submission check.
    """
    state = state or {}
    value = state.get("state") or "not_required"
    if state.get("control_id"):
        return value if value in {"needs_check", "refuted", "confirmed"} else ""
    if state.get("registry_match"):
        return "possible"
    return ""


def get_supplier_application_nazk_state(con: sqlite3.Connection, supplier_code: str,
                                        registry_names: set[str] | None = None) -> dict:
    """Return the newest *currently actionable* application-level NАЗК state.

    A registry name match alone is supplier history, not an operational task.
    Presentation state ``needs_check`` is therefore possible only for an
    existing submission control in a still-current framework/application.
    """
    rows = con.execute(
        """SELECT s.id,s.date_published,COALESCE(af.manager_name,'') manager_name,
                  COALESCE(ctrl.nazk_certificate_required,0) control_required
           FROM submissions s
           LEFT JOIN qualifications q ON q.id=s.qualification_id
           JOIN frameworks f ON f.id=s.framework_id
           LEFT JOIN application_fields af ON af.submission_id=s.id
           LEFT JOIN submission_nazk_controls ctrl ON ctrl.submission_id=s.id
           WHERE DIGITS(s.supplier_code)=DIGITS(?)
             AND ctrl.id IS NOT NULL
             AND ctrl.nazk_certificate_required=1
             AND LOWER(COALESCE(f.status,'')) IN ('active','active.tendering','active.enquiries')
             AND COALESCE(
                   SUBSTR(JSON_EXTRACT(f.raw_json,'$.qualificationPeriod.endDate'),1,10),
                   SUBSTR(JSON_EXTRACT(f.raw_json,'$.period.endDate'),1,10),
                   '9999-12-31')>=DATE('now')
             AND (
               LOWER(COALESCE(q.status,'pending'))='pending'
               OR (LOWER(COALESCE(q.status,''))='active' AND EXISTS (
                 SELECT 1 FROM registry_contracts rc
                 WHERE rc.qualification_id=q.id AND LOWER(COALESCE(rc.status,''))='active'
               ))
             )
           ORDER BY COALESCE(NULLIF(s.date_published,''),s.synced_at) DESC,s.id DESC""",
        (supplier_code,),
    ).fetchall()
    for row in rows:
        state = get_submission_nazk_state(con, row["id"], registry_names)
        if state["state"] != "not_required":
            return {**state, "date_published": row["date_published"] or ""}
    return {"state": "not_required", "can_approve": True, "required": False,
            "supplier_code": supplier_code, "submission_id": ""}


def ensure_submission_nazk_control(
    con: sqlite3.Connection, submission_id: str, manager_name: str | None = None,
    *, timestamp: str | None = None,
) -> dict:
    """Create/update one application-level control without consulting old check results."""
    source = con.execute(
        """SELECT s.supplier_code,
                  COALESCE(NULLIF(af.manager_name,''),NULLIF(edr.manager_name,''),'') manager_name
           FROM submissions s
           LEFT JOIN application_fields af ON af.submission_id=s.id
           LEFT JOIN supplier_edr_profiles edr ON DIGITS(edr.supplier_code)=DIGITS(s.supplier_code)
           WHERE s.id=?""",
        (submission_id,),
    ).fetchone()
    if not source:
        raise ValueError("Заявку не знайдено")
    supplier_code = str(source["supplier_code"] or "")
    name = " ".join(str(manager_name if manager_name is not None else source["manager_name"] or "").split())
    manager_id = _manager_id(con, supplier_code, name) if name else None
    required = int(bool(registry_matches(con, name))) if name else 0
    timestamp = timestamp or now_iso()
    current = get_submission_nazk_control(con, submission_id)
    if not current:
        con.execute(
            """INSERT INTO submission_nazk_controls
               (submission_id,supplier_code,manager_id,manager_name,nazk_certificate_required,
                nazk_certificate_checked,created_at,updated_at)
               VALUES (?,?,?,?,?,0,?,?)""",
            (submission_id, supplier_code, manager_id, name, required, timestamp, timestamp),
        )
    else:
        manager_changed = normalize_name(current.get("manager_name")) != normalize_name(name)
        if manager_changed:
            con.execute(
                """UPDATE submission_nazk_controls SET supplier_code=?,manager_id=?,manager_name=?,
                   nazk_certificate_required=?,nazk_certificate_checked=0,selected_document_id=NULL,
                   selected_document_url=NULL,supplier_nazk_check_id=NULL,checked_at=NULL,checked_by=NULL,
                   updated_at=? WHERE submission_id=?""",
                (supplier_code, manager_id, name, required, timestamp, submission_id),
            )
        else:
            con.execute(
                """UPDATE submission_nazk_controls SET supplier_code=?,manager_id=?,manager_name=?,
                   nazk_certificate_required=?,updated_at=? WHERE submission_id=?""",
                (supplier_code, manager_id, name, required, timestamp, submission_id),
            )
    return get_submission_nazk_control(con, submission_id) or {}


def _submission_documents(con: sqlite3.Connection, submission_id: str) -> list[dict]:
    row = con.execute(
        """SELECT s.documents_json,q.documents_json decision_documents
           FROM submissions s LEFT JOIN qualifications q ON q.submission_id=s.id WHERE s.id=?""",
        (submission_id,),
    ).fetchone()
    if not row:
        return []
    result = []
    for value in (row["documents_json"], row["decision_documents"]):
        try:
            documents = json.loads(value or "[]")
        except (TypeError, json.JSONDecodeError):
            documents = []
        result.extend(item for item in documents if isinstance(item, dict))
    return result


def complete_submission_nazk_check(
    con: sqlite3.Connection, submission_id: str, *, document_id: str, document_url: str,
    evidence_date: str, checked_by: str, comment: str = "", manager_tax_id: str = "",
    timestamp: str | None = None,
) -> dict:
    """Record an officer-confirmed certificate and finish a refuted manager check.

    covered_nazk_date intentionally remains NULL: the NАЗК API exposes both
    sentenceDate and punishmentStart and the legally controlling field has not
    yet been approved.
    """
    timestamp = timestamp or now_iso()
    control = ensure_submission_nazk_control(con, submission_id, timestamp=timestamp)
    if not control.get("manager_name"):
        raise ValueError("Не визначено ПІБ керівника")
    if not control.get("nazk_certificate_required"):
        raise ValueError("Для цього ПІБ довідка НАЗК не позначена як обов'язкова")
    existing_check_id = control.get("supplier_nazk_check_id")
    if control.get("nazk_certificate_checked") and existing_check_id:
        return {"control": control, "check_id": existing_check_id, "created": False,
                "coverage_status": "legal_date_field_unresolved"}
    documents = _submission_documents(con, submission_id)
    selected = next((item for item in documents if
                     (document_id and str(item.get("id") or "") == document_id) or
                     (document_url and str(item.get("url") or "") == document_url)), None)
    if not selected:
        raise ValueError("Обраний документ не знайдено серед документів заявки")
    if not evidence_date:
        raise ValueError("Зазначте дату довідки/офіційної відповіді")
    manager_id = control.get("manager_id")
    digits = re.sub(r"\D", "", manager_tax_id or "")
    if digits:
        if len(digits) != 10:
            raise ValueError("РНОКПП керівника повинен містити 10 цифр")
        if not manager_id:
            raise ValueError("Неможливо зберегти РНОКПП без надійного manager_id")
        con.execute(
            """UPDATE supplier_managers SET manager_tax_id=?,manager_tax_id_source='qualification_manual',
               manager_tax_id_verified_at=?,manager_tax_id_verified_by=?,updated_at=? WHERE id=?""",
            (digits, timestamp, checked_by, timestamp, manager_id),
        )
    cursor = con.execute(
        """INSERT INTO supplier_nazk_checks
           (supplier_code,manager_id,manager_name,workflow_status,result,started_at,completed_at,
            evidence_date,covered_nazk_date,comment,is_legacy,created_at,created_by,updated_at,updated_by)
            VALUES (?,?,?,'completed','refuted',?,?,?,NULL,?,0,?,?,?,?)""",
        (control["supplier_code"], manager_id, control["manager_name"], timestamp, timestamp,
         evidence_date, comment, timestamp, checked_by, timestamp, checked_by),
    )
    check_id = int(cursor.lastrowid)
    con.execute(
        """INSERT INTO supplier_nazk_check_documents
           (check_id,document_type,document_date,title,url,source,created_at,created_by,
            submission_id,prozorro_document_id)
           VALUES (?,'qualification_certificate',?,?,?,?,?,?,?,?)""",
        (check_id, evidence_date, str(selected.get("title") or ""), str(selected.get("url") or document_url),
         "prozorro_submission", timestamp, checked_by, submission_id, str(selected.get("id") or document_id)),
    )
    con.execute(
        """UPDATE submission_nazk_controls SET nazk_certificate_checked=1,selected_document_id=?,
           selected_document_url=?,supplier_nazk_check_id=?,checked_at=?,checked_by=?,comment=?,updated_at=?
           WHERE submission_id=?""",
        (str(selected.get("id") or document_id), str(selected.get("url") or document_url), check_id,
         timestamp, checked_by, comment, timestamp, submission_id),
    )
    for event_type in ("submission_nazk_certificate_checked", "check_completed_refuted"):
        con.execute(
            """INSERT INTO supplier_nazk_check_events
               (check_id,event_type,event_at,event_by,new_workflow_status,new_result,details_json)
               VALUES (?,?,?,?,'completed','refuted',?)""",
            (check_id, event_type, timestamp, checked_by,
             json.dumps({"submission_id": submission_id, "coverage_status": "legal_date_field_unresolved"},
                        ensure_ascii=False)),
        )
    return {"control": get_submission_nazk_control(con, submission_id), "check_id": check_id,
            "created": True, "coverage_status": "legal_date_field_unresolved"}


def get_supplier_nazk_state(con: sqlite3.Connection, supplier_code: str) -> dict:
    summary = con.execute(
        "SELECT active_count FROM supplier_registry_summary WHERE supplier_code=?", (supplier_code,)
    ).fetchone()
    active_count = int(summary[0] or 0) if summary else 0
    if active_count <= 0:
        return {"state": "inactive", "action": None, "active_count": active_count}
    manager = con.execute(
        "SELECT * FROM supplier_managers WHERE supplier_code=? AND is_current=1 ORDER BY id DESC LIMIT 1",
        (supplier_code,),
    ).fetchone()
    if not manager or not normalize_name(manager["manager_name"]):
        return {"state": "missing_manager", "action": None, "active_count": active_count}
    matches = registry_matches(con, manager["manager_name"])
    if not matches:
        return {"state": "no_matches", "action": None, "active_count": active_count,
                "manager_id": manager["id"], "manager_name": manager["manager_name"]}
    checks = con.execute(
        """SELECT * FROM supplier_nazk_checks WHERE supplier_code=? AND manager_id=?
           ORDER BY COALESCE(completed_at,started_at,created_at) DESC,id DESC""",
        (supplier_code, manager["id"]),
    ).fetchall()
    open_check = next((row for row in checks if row["workflow_status"] in OPEN_WORKFLOW_STATUSES), None)
    base = {"active_count": active_count, "manager_id": manager["id"],
            "manager_name": manager["manager_name"], "matches": len(matches)}
    if open_check:
        return {**base, "state": open_check["workflow_status"], "action": None, "check_id": open_check["id"]}
    latest = checks[0] if checks else None
    if latest and latest["workflow_status"] == "completed" and latest["result"] == "confirmed":
        return {**base, "state": "confirmed", "action": None, "check_id": latest["id"]}
    if latest and latest["workflow_status"] == "completed" and latest["result"] == "refuted":
        if not latest["covered_nazk_date"]:
            reason = "legacy_refuted_without_coverage" if latest["is_legacy"] else "refuted_without_coverage"
            return {**base, "state": "needs_review", "action": "create_needs_review",
                    "reason": reason, "previous_check_id": latest["id"]}
        return {**base, "state": "coverage_policy_unresolved", "action": None,
                "reason": "legal_registry_date_field_not_approved", "previous_check_id": latest["id"]}
    reason = "legacy_archived_current_match" if latest and latest["workflow_status"] == "legacy_archived" else "current_match_without_result"
    return {**base, "state": "needs_review", "action": "create_needs_review", "reason": reason,
            "previous_check_id": latest["id"] if latest else None}


def _supplier_state_from_prefetched(active_count: int, manager: dict | None,
                                    match_count: int, checks: list[dict]) -> dict:
    if active_count <= 0:
        return {"state": "inactive", "action": None, "active_count": active_count}
    if not manager or not normalize_name(manager.get("manager_name")):
        return {"state": "missing_manager", "action": None, "active_count": active_count}
    base = {"active_count": active_count, "manager_id": manager["id"],
            "manager_name": manager["manager_name"], "matches": match_count}
    if not match_count:
        return {**base, "state": "no_matches", "action": None}
    open_check = next((row for row in checks if row["workflow_status"] in OPEN_WORKFLOW_STATUSES), None)
    if open_check:
        return {**base, "state": open_check["workflow_status"], "action": None, "check_id": open_check["id"]}
    latest = checks[0] if checks else None
    if latest and latest["workflow_status"] == "completed" and latest["result"] == "confirmed":
        return {**base, "state": "confirmed", "action": None, "check_id": latest["id"]}
    if latest and latest["workflow_status"] == "completed" and latest["result"] == "refuted":
        if not latest.get("covered_nazk_date"):
            reason = "legacy_refuted_without_coverage" if latest.get("is_legacy") else "refuted_without_coverage"
            return {**base, "state": "needs_review", "action": "create_needs_review",
                    "reason": reason, "previous_check_id": latest["id"]}
        return {**base, "state": "coverage_policy_unresolved", "action": None,
                "reason": "legal_registry_date_field_not_approved", "previous_check_id": latest["id"]}
    reason = "legacy_archived_current_match" if latest and latest["workflow_status"] == "legacy_archived" else "current_match_without_result"
    return {**base, "state": "needs_review", "action": "create_needs_review", "reason": reason,
            "previous_check_id": latest["id"] if latest else None}


def reconcile_supplier_nazk(con: sqlite3.Connection, supplier_code: str, *, apply: bool = False,
                            timestamp: str | None = None) -> dict:
    state = get_supplier_nazk_state(con, supplier_code)
    if not apply or state.get("action") != "create_needs_review":
        return state
    existing = con.execute(
        """SELECT id FROM supplier_nazk_checks WHERE supplier_code=? AND manager_id=?
           AND workflow_status IN ('needs_review','request_to_supplier','request_to_nazk','waiting_response')
           ORDER BY id DESC LIMIT 1""",
        (supplier_code, state["manager_id"]),
    ).fetchone()
    if existing:
        return {**state, "check_id": existing["id"], "created": False}
    timestamp = timestamp or now_iso()
    cursor = con.execute(
        """INSERT INTO supplier_nazk_checks
           (supplier_code,manager_id,manager_name,workflow_status,result,started_at,comment,is_legacy,
            created_at,created_by,updated_at,updated_by)
           VALUES (?,?,?,'needs_review',NULL,?,'',0,?,'PQM SYSTEM',?,'PQM SYSTEM')""",
        (supplier_code, state["manager_id"], state["manager_name"], timestamp, timestamp, timestamp),
    )
    check_id = int(cursor.lastrowid)
    for match in registry_matches(con, state["manager_name"]):
        con.execute(
            """INSERT OR IGNORE INTO supplier_nazk_check_matches
               (check_id,nazk_source_id,match_status,created_at) VALUES (?,?,'candidate',?)""",
            (check_id, match["source_id"], timestamp),
        )
    event_type = {
        "legacy_refuted_without_coverage": "check_created_due_legacy_without_coverage",
        "legacy_archived_current_match": "check_created_due_reactivation",
    }.get(state.get("reason"), "check_created_due_current_match")
    con.execute(
        """INSERT INTO supplier_nazk_check_events
           (check_id,event_type,event_at,event_by,new_workflow_status,details_json)
           VALUES (?,?,?,'PQM SYSTEM','needs_review',?)""",
        (check_id, event_type, timestamp, json.dumps({"reason": state.get("reason")}, ensure_ascii=False)),
    )
    return {**state, "check_id": check_id, "created": True}


def reconcile_active_supplier_nazk(con: sqlite3.Connection, *, apply: bool = False) -> dict:
    counters = Counter()
    reasons = Counter()
    items = []
    suppliers = [dict(row) for row in con.execute(
        """SELECT s.supplier_code,s.active_count,m.id manager_id,m.manager_name
           FROM supplier_registry_summary s LEFT JOIN supplier_managers m
             ON m.supplier_code=s.supplier_code AND m.is_current=1
           WHERE s.active_count>0 ORDER BY s.supplier_code""")]
    registry_names = Counter(normalize_name(row[0]) for row in con.execute(
        "SELECT full_name FROM nazk_registry WHERE COALESCE(full_name,'')<>''"
    ))
    checks_by_supplier: dict[str, list[dict]] = {}
    for row in con.execute(
        """SELECT c.* FROM supplier_nazk_checks c
           JOIN supplier_managers m ON m.id=c.manager_id AND m.is_current=1
           JOIN supplier_registry_summary s ON s.supplier_code=c.supplier_code AND s.active_count>0
           ORDER BY c.supplier_code,COALESCE(c.completed_at,c.started_at,c.created_at) DESC,c.id DESC"""):
        checks_by_supplier.setdefault(row["supplier_code"], []).append(dict(row))
    for row in suppliers:
        manager = {"id": row["manager_id"], "manager_name": row["manager_name"]} if row["manager_id"] else None
        state = _supplier_state_from_prefetched(
            int(row["active_count"] or 0), manager,
            registry_names.get(normalize_name(row["manager_name"]), 0) if manager else 0,
            checks_by_supplier.get(row["supplier_code"], []),
        )
        if apply and state.get("action") == "create_needs_review":
            state = reconcile_supplier_nazk(con, row["supplier_code"], apply=True)
        counters[state["state"]] += 1
        if state.get("reason"):
            reasons[state["reason"]] += 1
        if state.get("action") == "create_needs_review":
            items.append({"supplier_code": row["supplier_code"], **state})
    return {"mode": "apply" if apply else "dry-run", "active_suppliers": sum(counters.values()),
            "states": dict(sorted(counters.items())), "reasons": dict(sorted(reasons.items())),
            "potential_needs_review": len(items), "items": items}
