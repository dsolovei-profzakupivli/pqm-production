"""Read-only projection of actionable PQM workflows for the УО work queue."""

from __future__ import annotations

from datetime import date, timedelta
import math


OPEN_SUPPLIER_NAZK = {
    "needs_review",
    "request_to_supplier",
    "request_to_nazk",
    "waiting_response",
}


def _text(value) -> str:
    return str(value or "").strip()


def default_protocol_period(today_value: date | None = None) -> tuple[str, str]:
    """Previous business day through the calendar day immediately before today."""
    current = today_value or date.today()
    period_to = current - timedelta(days=1)
    period_from = period_to
    while period_from.weekday() >= 5:
        period_from -= timedelta(days=1)
    return period_from.isoformat(), period_to.isoformat()


def _working_day_deadline(value: str, days: int) -> str:
    try:
        current = date.fromisoformat(_date_part(value))
    except (TypeError, ValueError):
        return ""
    added = 0
    while added < days:
        current += timedelta(days=1)
        if current.weekday() < 5:
            added += 1
    return current.isoformat()


def _date_part(value) -> str:
    return _text(value)[:10]


def _is_true(value) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _latest_nazk_dates(con) -> dict[str, str]:
    """Return one normalized latest NACP decision date per person."""
    return {
        _text(row["manager_key"]): _date_part(row["decision_date"])
        for row in con.execute(
            """SELECT NORMALIZE_NAME(full_name) manager_key,MAX(sentence_date) decision_date
               FROM nazk_registry
               WHERE COALESCE(full_name,'')<>'' AND COALESCE(sentence_date,'')<>''
               GROUP BY NORMALIZE_NAME(full_name)"""
        )
        if _text(row["manager_key"]) and _date_part(row["decision_date"])
    }


def _officer_label(value) -> str:
    parts = " ".join(_text(value).split()).split()
    if not parts:
        return "Не призначено"
    return " ".join([*[part.lower().capitalize() for part in parts[:-1]], parts[-1].upper()])


def _add_officer_count(target: dict, value, count: int) -> None:
    label = _officer_label(value)
    key = label.casefold()
    if key not in target:
        target[key] = {"officer": label, "applications": 0}
    target[key]["applications"] += int(count or 0)


def _qualification_tasks(con) -> list[dict]:
    rows = con.execute(
        """SELECT s.id submission_id,s.supplier_name,s.supplier_code,s.date_published,
          f.pretty_id,f.dk_code,COALESCE(fo.category,'') category,
          COALESCE(NULLIF(af.protocol_officer,''),NULLIF(fo.officer,''),'') responsible_user
          FROM submissions s
          JOIN frameworks f ON f.id=s.framework_id
          LEFT JOIN qualifications q ON q.id=s.qualification_id
          LEFT JOIN application_fields af ON af.submission_id=s.id
          LEFT JOIN framework_officers fo ON fo.framework_id=s.framework_id
          WHERE COALESCE(q.status,'pending')='pending'"""
    ).fetchall()
    return [{
        "task_id": f"qualification:{row['submission_id']}:review",
        "task_type": "qualification", "action_type": "review_application",
        "source_id": row["submission_id"], "title": "Розглянути заявку",
        "subject_name": row["supplier_name"] or "", "subject_code": row["supplier_code"] or "",
        "person_name": "", "tax_id_present": None,
        "object_label": "Заявка", "object_pretty_id": row["pretty_id"] or row["submission_id"],
        "dk_code": row["dk_code"] or "", "reason": "Кваліфікація очікує рішення УО",
        "category": row["category"] or "",
        "status": "pending", "created_at": row["date_published"] or "", "deadline_date": "",
        "responsible_user": row["responsible_user"] or "", "priority": "normal",
        "source_view": "applications", "source_params": {"submission_id": row["submission_id"]},
    } for row in rows]


def get_current_qualification_summary(con, filters: dict | None = None) -> dict:
    """Operational qualification dashboard, kept separate from the service task queue."""
    today = date.today().isoformat()
    filters = filters or {}
    default_from, default_to = default_protocol_period()
    protocol_from = _text(filters.get("protocol_from")) or default_from
    protocol_to = _text(filters.get("protocol_to")) or default_to
    try:
        current_from = (date.fromisoformat(protocol_to) + timedelta(days=1)).isoformat()
    except ValueError:
        protocol_to = (date.today() - timedelta(days=1)).isoformat()
        current_from = today
    selected_officer = _text(filters.get("officer"))
    selected_category = _text(filters.get("category"))
    extra, filter_args = [], []
    if selected_officer:
        extra.append("CASEFOLD(COALESCE(NULLIF(af.protocol_officer,''),NULLIF(fo.officer,''),'Не призначено'))=CASEFOLD(?)")
        filter_args.append(selected_officer)
    if selected_category:
        extra.append("COALESCE(fo.category,'')=?")
        filter_args.append(selected_category)
    suffix = (" AND " + " AND ".join(extra)) if extra else ""
    rows = con.execute(
        f"""SELECT COALESCE(NULLIF(af.protocol_officer,''),NULLIF(fo.officer,''),'Не призначено') officer,
          COALESCE(NULLIF(fo.category,''),'Без категорії') category,COUNT(*) applications
          FROM submissions s
          JOIN frameworks f ON f.id=s.framework_id
          LEFT JOIN qualifications q ON q.id=s.qualification_id
          LEFT JOIN application_fields af ON af.submission_id=s.id
          LEFT JOIN framework_officers fo ON fo.framework_id=s.framework_id
          WHERE COALESCE(q.status,'pending')='pending'
            AND SUBSTR(s.date_published,1,10)>=?
            AND LOWER(COALESCE(f.status,''))='active'
            AND COALESCE(SUBSTR(JSON_EXTRACT(f.raw_json,'$.qualificationPeriod.endDate'),1,10),'9999-12-31')>=? {suffix}
          GROUP BY COALESCE(NULLIF(af.protocol_officer,''),NULLIF(fo.officer,''),'Не призначено'),COALESCE(NULLIF(fo.category,''),'Без категорії')
          ORDER BY applications DESC, officer""",
        [current_from, today, *filter_args],
    ).fetchall()
    officers, categories = {}, {}
    for row in rows:
        _add_officer_count(officers, row["officer"], row["applications"])
        categories[row["category"]] = categories.get(row["category"], 0) + int(row["applications"] or 0)
    protocol_rows = con.execute(
        f"""SELECT COALESCE(NULLIF(af.protocol_officer,''),NULLIF(fo.officer,''),'Не призначено') officer,
          COALESCE(NULLIF(fo.category,''),'Без категорії') category,COUNT(*) applications
          FROM submissions s JOIN frameworks f ON f.id=s.framework_id
          LEFT JOIN qualifications q ON q.id=s.qualification_id
          LEFT JOIN application_fields af ON af.submission_id=s.id
          LEFT JOIN framework_officers fo ON fo.framework_id=s.framework_id
          WHERE SUBSTR(s.date_published,1,10) BETWEEN ? AND ? {suffix}
          GROUP BY COALESCE(NULLIF(af.protocol_officer,''),NULLIF(fo.officer,''),'Не призначено'),
                   COALESCE(NULLIF(fo.category,''),'Без категорії')
          ORDER BY applications DESC,officer""", [protocol_from, protocol_to, *filter_args]).fetchall()
    protocol_officers, protocol_categories = {}, {}
    for row in protocol_rows:
        _add_officer_count(protocol_officers, row["officer"], row["applications"])
        protocol_categories[row["category"]] = protocol_categories.get(row["category"], 0) + int(row["applications"] or 0)
    control = dict(con.execute(
        f"""SELECT
          SUM(CASE WHEN COALESCE(q.status,'pending')='active' THEN 1 ELSE 0 END) admitted,
          SUM(CASE WHEN COALESCE(q.status,'pending')='unsuccessful' THEN 1 ELSE 0 END) rejected,
          SUM(CASE WHEN COALESCE(q.status,'pending') NOT IN ('active','unsuccessful') THEN 1 ELSE 0 END) awaiting_sync
          FROM submissions s
          JOIN frameworks f ON f.id=s.framework_id
          LEFT JOIN qualifications q ON q.id=s.qualification_id
          LEFT JOIN application_fields af ON af.submission_id=s.id
          LEFT JOIN framework_officers fo ON fo.framework_id=s.framework_id
          WHERE SUBSTR(s.date_published,1,10) BETWEEN ? AND ? {suffix}""",
        [protocol_from, protocol_to, *filter_args],
    ).fetchone())
    return {"total": sum(item["applications"] for item in officers.values()),
            "from": current_from, "to": "", "date": current_from,
            "officers": list(officers.values()),
            "categories": [{"category": key, "applications": value} for key, value in categories.items()],
            "protocol": {"from": protocol_from, "to": protocol_to,
                         "total": sum(item["applications"] for item in protocol_officers.values()),
                         "officers": list(protocol_officers.values()),
                         "categories": [{"category": key, "applications": value} for key, value in protocol_categories.items()]},
            "publication_control": {key: int(value or 0) for key, value in control.items()}}


def _submission_nazk_tasks(con) -> list[dict]:
    rows = con.execute(
        """SELECT c.id control_id,c.submission_id,c.supplier_code,c.manager_name,c.created_at,
          NORMALIZE_NAME(c.manager_name) manager_key,s.date_published,
          s.supplier_name,f.pretty_id,f.dk_code,COALESCE(fo.category,'') category,sm.manager_tax_id,
          COALESCE(NULLIF(af.protocol_officer,''),NULLIF(fo.officer,''),'') responsible_user
          FROM submission_nazk_controls c
          JOIN submissions s ON s.id=c.submission_id
          JOIN frameworks f ON f.id=s.framework_id
          LEFT JOIN application_fields af ON af.submission_id=s.id
          LEFT JOIN framework_officers fo ON fo.framework_id=s.framework_id
          LEFT JOIN supplier_managers sm ON sm.id=c.manager_id
          LEFT JOIN qualifications q ON q.id=s.qualification_id
          WHERE c.nazk_certificate_required=1 AND c.nazk_certificate_checked=0
            AND LOWER(COALESCE(f.status,'')) IN ('active','active.tendering','active.enquiries')
            AND COALESCE(
              SUBSTR(JSON_EXTRACT(f.raw_json,'$.qualificationPeriod.endDate'),1,10),
              SUBSTR(JSON_EXTRACT(f.raw_json,'$.period.endDate'),1,10),
              '9999-12-31')>=DATE('now')
            -- Application-level work belongs only to a current undecided
            -- application. An already admitted historical application is
            -- handled by the supplier-level workflow and must not be reopened.
            AND LOWER(COALESCE(q.status,'pending'))='pending'"""
    ).fetchall()
    latest_nazk_dates = _latest_nazk_dates(con)
    rows = [row for row in rows
            if latest_nazk_dates.get(_text(row["manager_key"]), "")
            > _date_part(row["date_published"])]
    return [{
        "task_id": f"submission_nazk:{row['submission_id']}:check_certificate",
        "task_type": "submission_nazk", "action_type": "check_certificate",
        "source_id": row["submission_id"], "title": "Перевірити довідку НАЗК",
        "subject_name": row["supplier_name"] or "", "subject_code": row["supplier_code"] or "",
        "person_name": row["manager_name"] or "", "tax_id_present": bool(row["manager_tax_id"]),
        "object_label": "Заявка", "object_pretty_id": row["pretty_id"] or row["submission_id"],
        "dk_code": row["dk_code"] or "", "reason": "НАЗК · перевірити довідку цієї заявки",
        "category": row["category"] or "",
        "status": "needs_document_check", "created_at": row["created_at"] or "", "deadline_date": "",
        "responsible_user": row["responsible_user"] or "", "priority": "high",
        "source_view": "applications",
        "source_params": {"submission_id": row["submission_id"], "nazk_control": True},
    } for row in rows]


def _supplier_nazk_tasks(con) -> list[dict]:
    placeholders = ",".join("?" for _ in OPEN_SUPPLIER_NAZK)
    rows = con.execute(
        f"""SELECT sc.id check_id,sc.supplier_code,sc.manager_name,sc.workflow_status,
          NORMALIZE_NAME(sc.manager_name) manager_key,
          sc.started_at,sc.manager_id,srs.supplier_name,sm.manager_tax_id
          FROM supplier_nazk_checks sc
          JOIN supplier_registry_summary srs ON srs.supplier_code=sc.supplier_code
          LEFT JOIN supplier_managers sm ON sm.id=sc.manager_id
          WHERE sc.workflow_status IN ({placeholders}) AND srs.active_count>0""",
        tuple(sorted(OPEN_SUPPLIER_NAZK)),
    ).fetchall()
    latest_nazk_dates = _latest_nazk_dates(con)
    codes = sorted({_text(row["supplier_code"]) for row in rows if _text(row["supplier_code"])})
    application_dates = {}
    if codes:
        code_placeholders = ",".join("?" for _ in codes)
        application_dates = {
            _text(row["supplier_code"]): _date_part(row["application_date"])
            for row in con.execute(
                f"""SELECT supplier_code,MIN(date_published) application_date
                    FROM submissions WHERE supplier_code IN ({code_placeholders})
                    GROUP BY supplier_code""",
                tuple(codes),
            )
        }
    rows = [row for row in rows
            if latest_nazk_dates.get(_text(row["manager_key"]), "")
            > application_dates.get(_text(row["supplier_code"]), "")]
    labels = {
        "needs_review": "Потребує перевірки",
        "request_to_supplier": "Опрацювати запит постачальнику",
        "request_to_nazk": "Опрацювати запит до НАЗК",
        "waiting_response": "Очікується відповідь",
    }
    return [{
        "task_id": f"supplier_nazk:{row['check_id']}:{row['workflow_status']}",
        "task_type": "supplier_nazk", "action_type": row["workflow_status"],
        "source_id": str(row["check_id"]), "title": labels.get(row["workflow_status"], "Перевірити НАЗК"),
        "subject_name": row["supplier_name"] or "", "subject_code": row["supplier_code"] or "",
        "person_name": row["manager_name"] or "", "tax_id_present": bool(row["manager_tax_id"]),
        "object_label": "Постачальник", "object_pretty_id": row["supplier_code"] or "",
        "dk_code": "", "reason": ("НАЗК · Потрібно визначити подальшу дію"
          if row["workflow_status"] == "needs_review"
          else f"НАЗК · {labels.get(row['workflow_status'], row['workflow_status'])}"),
        "status": row["workflow_status"], "created_at": row["started_at"] or "", "deadline_date": "",
        "responsible_user": "", "priority": "high" if row["workflow_status"] == "needs_review" else "normal",
        "source_view": "suppliers",
        "source_params": {"supplier_code": row["supplier_code"], "nazk_check_id": row["check_id"]},
    } for row in rows]


def _violation_tasks(con) -> list[dict]:
    rows = con.execute(
        """SELECT vr.id,vr.report_id,vr.date_published,vr.defendant_period_end,
          vr.author_name,vr.author_code,vr.defendant_name,vr.defendant_code,vr.reason,
          COALESCE(vrr.review_status,'not_reviewed') review_status,
          COALESCE(vrr.assigned_officer,'') assigned_officer
          FROM violation_reports vr
          LEFT JOIN violation_report_reviews vrr ON vrr.report_id=vr.id
          WHERE COALESCE(json_array_length(json_extract(vr.raw_json,'$.decisions')),0)=0
            AND COALESCE(vrr.review_status,'not_reviewed') NOT IN ('reviewed','completed','closed')"""
    ).fetchall()
    today = date.today().isoformat()
    tasks = []
    for row in rows:
        supplier_deadline = _date_part(row["defendant_period_end"]) or _working_day_deadline(row["date_published"], 3)
        deadline = _working_day_deadline(row["date_published"], 10)
        overdue = bool(deadline and deadline < today)
        supplier_ready = bool(supplier_deadline and supplier_deadline < today)
        tasks.append({
            "task_id": f"violation_report:{row['id']}:review",
            "task_type": "violation_report", "action_type": "review_violation_report",
            "source_id": row["id"], "title": "Розглянути звернення",
            "subject_name": row["defendant_name"] or "",
            "subject_code": row["defendant_code"] or "",
            "customer_name": row["author_name"] or "",
            "person_name": "", "tax_id_present": None,
            "object_label": "Звернення", "object_pretty_id": row["report_id"] or row["id"],
            "dk_code": "", "reason": (("Строк постачальника сплив · " if supplier_ready else "Очікуємо пояснення постачальника · ")
                                             + (row["reason"] or "Звернення очікує розгляду")),
            "status": row["review_status"], "created_at": row["date_published"] or "",
            "deadline_date": deadline, "responsible_user": row["assigned_officer"] or "",
            "priority": "urgent" if overdue else ("high" if supplier_ready else "normal"), "overdue": overdue,
            "source_view": "requests", "source_params": {"report_id": row["id"]},
        })
    return tasks


def _all_tasks(con) -> list[dict]:
    # Qualification work remains in the native application register. Including
    # it here duplicates the primary workflow and mixes current applications
    # with historical pending anomalies from completed/legacy frameworks.
    tasks = (_submission_nazk_tasks(con) + _supplier_nazk_tasks(con)
             + _violation_tasks(con))
    seen, unique = set(), []
    for task in tasks:
        task.setdefault("overdue", False)
        task.setdefault("customer_name", "")
        if task["task_id"] not in seen:
            seen.add(task["task_id"]); unique.append(task)
    return unique


def _filter_tasks(tasks: list[dict], filters: dict, current_user: str) -> list[dict]:
    search = _text(filters.get("search")).casefold()
    task_type = _text(filters.get("type"))
    status = _text(filters.get("status"))
    responsible = _text(filters.get("responsible_user"))
    mine = _is_true(filters.get("mine"))
    date_from, date_to = _text(filters.get("date_from")), _text(filters.get("date_to"))
    dk_code = _text(filters.get("dk_code"))
    category = _text(filters.get("category"))
    overdue_only = _is_true(filters.get("overdue"))
    result = []
    for task in tasks:
        haystack = " ".join(_text(task.get(key)) for key in (
            "title", "subject_name", "subject_code", "customer_name", "person_name", "object_pretty_id", "reason", "dk_code"
        )).casefold()
        created = _date_part(task.get("created_at"))
        if search and search not in haystack: continue
        if task_type == "nazk" and task["task_type"] not in {"submission_nazk", "supplier_nazk"}: continue
        if task_type and task_type != "nazk" and task["task_type"] != task_type: continue
        if status and task["status"] != status: continue
        if mine and task.get("responsible_user") != current_user: continue
        if responsible == "__unassigned__" and task.get("responsible_user"): continue
        if responsible and responsible != "__unassigned__" and task.get("responsible_user") != responsible: continue
        if date_from and created < date_from: continue
        if date_to and created > date_to: continue
        if dk_code and task.get("dk_code") != dk_code: continue
        if category and task.get("category") != category: continue
        if overdue_only and not task.get("overdue"): continue
        result.append(task)
    priority_order = {"urgent": 0, "high": 1, "normal": 2, "low": 3}
    result.sort(key=lambda task: (
        priority_order.get(task.get("priority"), 9),
        _date_part(task.get("deadline_date")) or "9999-12-31",
        _text(task.get("created_at")), task["task_id"],
    ))
    return result


def get_uo_work_queue_kpi(tasks: list[dict]) -> dict:
    return {
        "total": len(tasks),
        "qualification": sum(task["task_type"] == "qualification" for task in tasks),
        "nazk": sum(task["task_type"] in {"submission_nazk", "supplier_nazk"} for task in tasks),
        "violation_report": sum(task["task_type"] == "violation_report" for task in tasks),
        "other": sum(task["task_type"] not in {"qualification", "submission_nazk", "supplier_nazk", "violation_report"} for task in tasks),
        "waiting_response": sum(task["status"] == "waiting_response" for task in tasks),
        "overdue": sum(bool(task.get("overdue")) for task in tasks),
    }


def get_uo_work_queue(con, filters: dict | None = None, current_user: str = "") -> dict:
    filters = filters or {}
    all_tasks = _all_tasks(con)
    filtered = _filter_tasks(all_tasks, filters, current_user)
    page = max(1, int(filters.get("page") or 1))
    size = min(200, max(10, int(filters.get("size") or 50)))
    total = len(filtered); pages = max(1, math.ceil(total / size))
    page = min(page, pages); start = (page - 1) * size
    responsible_users = sorted({task["responsible_user"] for task in all_tasks if task["responsible_user"]})
    return {
        "items": filtered[start:start + size], "total": total, "page": page, "pages": pages, "size": size,
        "kpi": get_uo_work_queue_kpi(filtered), "current_user": current_user,
        "responsible_users": responsible_users,
        "statuses": sorted({task["status"] for task in all_tasks}),
        "task_types": sorted({task["task_type"] for task in all_tasks}),
        "qualification_summary": get_current_qualification_summary(con, filters),
    }
