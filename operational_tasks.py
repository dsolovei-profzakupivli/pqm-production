"""Block 3 operational tasks built from canonical LOCAL PQM data."""
from __future__ import annotations

import json
import re
import uuid
import calendar
from urllib.parse import urlsplit
import supplier_activity
import nazk_evidence
from supplier_identity import current_manager_rnokpp
from datetime import date, datetime, timedelta, timezone

TASK_TYPES = {"amcu_exclusion", "nazk_check", "warning_block", "manual",
              "fop_termination_exclusion", "legal_entity_bankruptcy_exclusion"}
IMPLEMENTED_TYPES = {"amcu_exclusion", "nazk_check", "warning_block"}
STATUSES = {"new", "in_progress", "awaiting_response", "waiting_external", "ready_for_document",
            "awaiting_publication", "awaiting_sync", "active_blocking", "completed", "cancelled"}
TERMINAL = {"completed", "cancelled"}
STATUS_GROUPS = {
    "active": STATUSES - TERMINAL,
    "needs_action": {"new", "in_progress", "ready_for_document"},
    "awaiting_response": {"awaiting_response", "waiting_external"},
    "ready_for_document": {"ready_for_document"},
    "awaiting_sync": {"awaiting_sync"},
    "completed": {"completed"},
    "cancelled": {"cancelled"},
    "historical": TERMINAL,
}
TRANSITIONS = {
    "new": {"in_progress", "awaiting_response", "waiting_external", "ready_for_document", "cancelled"},
    "in_progress": {"awaiting_response", "waiting_external", "ready_for_document", "cancelled"},
    "awaiting_response": {"in_progress", "ready_for_document", "completed", "cancelled"},
    "waiting_external": {"in_progress", "ready_for_document", "completed", "cancelled"},
    "ready_for_document": {"in_progress", "awaiting_publication", "cancelled"},
    "awaiting_publication": {"awaiting_sync", "cancelled"},
    "awaiting_sync": {"completed", "in_progress", "cancelled"},
    "active_blocking": {"completed"}, "completed": set(), "cancelled": set(),
}
RESOLUTIONS = {"completed", "not_applicable", "cancelled", "nazk_refuted",
               "nazk_confirmed", "nazk_not_relevant", "nazk_not_current", "amcu_excluded",
               "supplier_blocked", "blocking_completed", "legacy_blocking_confirmed", "no_active_qualifications", "manager_changed", "nazk_record_no_longer_present",
               "duplicate_cycle_existing_factual", "covered_by_later_qualification", ""}


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def migrate(con):
    con.executescript("""
    CREATE TABLE IF NOT EXISTS operational_tasks (
      id TEXT PRIMARY KEY, task_key TEXT NOT NULL UNIQUE,
      task_type TEXT NOT NULL, supplier_code TEXT NOT NULL,
      supplier_name_snapshot TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'new',
      priority TEXT NOT NULL DEFAULT 'normal', assigned_officer_id INTEGER REFERENCES authorized_officers(id),
      created_at TEXT NOT NULL, updated_at TEXT NOT NULL, due_at TEXT,
      ready_for_document_at TEXT, protocol_number TEXT DEFAULT '', protocol_date TEXT DEFAULT '',
      protocol_reference TEXT DEFAULT '', published_at TEXT, published_reference TEXT DEFAULT '',
      resolved_at TEXT, resolved_by TEXT, resolution_code TEXT DEFAULT '', resolution_text TEXT DEFAULT '',
      source_context TEXT NOT NULL DEFAULT '{}', document_context TEXT NOT NULL DEFAULT '{}',
      metadata TEXT NOT NULL DEFAULT '{}', version INTEGER NOT NULL DEFAULT 1
    );
    CREATE INDEX IF NOT EXISTS ix_operational_tasks_state ON operational_tasks(status,task_type);
    CREATE INDEX IF NOT EXISTS ix_operational_tasks_supplier ON operational_tasks(supplier_code,created_at);
    CREATE INDEX IF NOT EXISTS ix_operational_tasks_officer ON operational_tasks(assigned_officer_id,status);
    CREATE TABLE IF NOT EXISTS operational_task_applications (
      task_id TEXT NOT NULL REFERENCES operational_tasks(id) ON DELETE CASCADE,
      application_id TEXT NOT NULL REFERENCES submissions(id), relation_type TEXT NOT NULL,
      PRIMARY KEY(task_id,application_id,relation_type)
    );
    CREATE TABLE IF NOT EXISTS operational_task_warnings (
      task_id TEXT NOT NULL REFERENCES operational_tasks(id) ON DELETE CASCADE,
      violation_report_id TEXT NOT NULL REFERENCES violation_reports(id), warning_date TEXT NOT NULL,
      sequence_no INTEGER NOT NULL, PRIMARY KEY(task_id,violation_report_id)
    );
    CREATE INDEX IF NOT EXISTS ix_operational_task_warnings_report ON operational_task_warnings(violation_report_id);
    CREATE TABLE IF NOT EXISTS operational_task_amcu_decisions (
      task_id TEXT NOT NULL REFERENCES operational_tasks(id) ON DELETE CASCADE,
      amcu_decision_id TEXT NOT NULL REFERENCES amcu_registry(row_key), extract_url TEXT NOT NULL DEFAULT '',
      created_at TEXT NOT NULL, updated_at TEXT NOT NULL, updated_by TEXT NOT NULL,
      PRIMARY KEY(task_id,amcu_decision_id)
    );
    CREATE TABLE IF NOT EXISTS operational_task_events (
      id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL REFERENCES operational_tasks(id) ON DELETE CASCADE,
      event_type TEXT NOT NULL, created_at TEXT NOT NULL, actor TEXT NOT NULL,
      old_value TEXT, new_value TEXT, metadata TEXT NOT NULL DEFAULT '{}'
    );
    CREATE INDEX IF NOT EXISTS ix_operational_task_events ON operational_task_events(task_id,created_at,id);
    CREATE TABLE IF NOT EXISTS operational_task_channels (
      task_id TEXT NOT NULL REFERENCES operational_tasks(id) ON DELETE CASCADE,
      channel TEXT NOT NULL CHECK(channel IN ('supplier','nazk')),
      status TEXT NOT NULL DEFAULT 'not_sent', sent_at TEXT, outgoing_number TEXT DEFAULT '',
      reference_url TEXT DEFAULT '', comment TEXT DEFAULT '', recorded_at TEXT,
      recorded_by TEXT DEFAULT '', PRIMARY KEY(task_id,channel)
    );
    CREATE TABLE IF NOT EXISTS operational_task_responses (
      id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL REFERENCES operational_tasks(id) ON DELETE CASCADE,
      source TEXT NOT NULL CHECK(source IN ('supplier','nazk','other')), response_date TEXT,
      incoming_number TEXT DEFAULT '', reference_url TEXT DEFAULT '', document_reference TEXT DEFAULT '',
      summary TEXT DEFAULT '', information_result TEXT NOT NULL DEFAULT 'neutral',
      post_close INTEGER NOT NULL DEFAULT 0, recorded_at TEXT NOT NULL, recorded_by TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS ix_operational_task_responses_task ON operational_task_responses(task_id,recorded_at,id);
    CREATE TABLE IF NOT EXISTS operational_task_blocking_decisions (
      task_id TEXT PRIMARY KEY REFERENCES operational_tasks(id) ON DELETE CASCADE,
      decision_date TEXT NOT NULL DEFAULT '', protocol_number TEXT NOT NULL DEFAULT '',
      prozorro_url TEXT NOT NULL DEFAULT '', document_url TEXT NOT NULL DEFAULT '', officer_note TEXT NOT NULL DEFAULT '',
      attached_at TEXT, attached_by TEXT DEFAULT '', used_for_blocking INTEGER NOT NULL DEFAULT 0
    );
    """)
    response_sql=(con.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='operational_task_responses'").fetchone() or [""])[0] or ""
    if "'other'" not in response_sql:
        con.executescript("""ALTER TABLE operational_task_responses RENAME TO operational_task_responses_legacy;
        CREATE TABLE operational_task_responses (
          id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL REFERENCES operational_tasks(id) ON DELETE CASCADE,
          source TEXT NOT NULL CHECK(source IN ('supplier','nazk','other')), response_date TEXT,
          incoming_number TEXT DEFAULT '', reference_url TEXT DEFAULT '', document_reference TEXT DEFAULT '',
          summary TEXT DEFAULT '', information_result TEXT NOT NULL DEFAULT 'neutral', post_close INTEGER NOT NULL DEFAULT 0,
          recorded_at TEXT NOT NULL, recorded_by TEXT NOT NULL);
        INSERT INTO operational_task_responses SELECT * FROM operational_task_responses_legacy;
        DROP TABLE operational_task_responses_legacy;
        CREATE INDEX ix_operational_task_responses_task ON operational_task_responses(task_id,recorded_at,id);""")
    nazk_evidence.migrate(con)


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _loads(value):
    try:
        return json.loads(value or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}


def _digits(value):
    return re.sub(r"\D", "", str(value or ""))


def _supplier_name(con, code):
    row = con.execute("""SELECT COALESCE(NULLIF(e.full_name,''),NULLIF(e.short_name,''),
      (SELECT s.supplier_name FROM submissions s WHERE DIGITS(s.supplier_code)=? ORDER BY s.date_published DESC LIMIT 1),'')
      FROM supplier_edr_profiles e WHERE DIGITS(e.supplier_code)=?""", (code, code)).fetchone()
    if row and row[0]: return row[0]
    row = con.execute("SELECT supplier_name FROM submissions WHERE DIGITS(supplier_code)=? ORDER BY date_published DESC LIMIT 1", (code,)).fetchone()
    return row[0] if row else ""


def _supplier_name_map(con):
    names = {}
    for row in con.execute("""SELECT supplier_code,supplier_name FROM submissions
      WHERE COALESCE(supplier_name,'')<>'' ORDER BY date_published DESC"""):
        code = _digits(row[0])
        if code and code not in names:
            names[code] = row[1]
    for row in con.execute("SELECT supplier_code,full_name,short_name FROM supplier_edr_profiles"):
        code = _digits(row[0])
        edr_name = row[1] or row[2]
        if code and edr_name:
            names[code] = edr_name
    return names


def _active_applications(con, code):
    return [dict(row) for row in con.execute("""SELECT DISTINCT s.id,s.framework_id,s.date_published,
      COALESCE(NULLIF(f.pretty_id,''),f.id) framework_pretty_id,f.dk_code,f.title framework_title
      FROM submissions s JOIN qualifications q ON q.submission_id=s.id
      LEFT JOIN frameworks f ON f.id=s.framework_id
      WHERE DIGITS(s.supplier_code)=? AND LOWER(COALESCE(q.status,''))='active'
      ORDER BY s.date_published DESC,s.id""", (code,))]


def _active_application_map(con):
    """Load the same current active qualifications used by the supplier registry.

    Historical qualification rows are deliberately insufficient: an active
    registry contract only counts while its framework/qualification period is
    still current.
    """
    grouped = {}
    rows = con.execute(f"""SELECT DISTINCT DIGITS(rc.supplier_code) supplier_code,
      s.id,s.framework_id,s.date_published,
      COALESCE(NULLIF(f.pretty_id,''),f.id) framework_pretty_id,f.dk_code,f.title framework_title
      FROM registry_contracts rc
      JOIN qualifications q ON q.id=rc.qualification_id
      JOIN submissions s ON s.id=q.submission_id
      JOIN frameworks f ON f.id=rc.framework_id
      WHERE {supplier_activity.effective_active_sql('rc','f')}
        AND DIGITS(rc.supplier_code)<>''
      ORDER BY DIGITS(rc.supplier_code),s.date_published DESC,s.id""")
    for row in rows:
        item = dict(row)
        code = item.pop("supplier_code")
        grouped.setdefault(code, []).append(item)
    return grouped


def _effective_active_applications(con, code):
    """Current effective qualifications for one supplier, using the shared predicate."""
    sql=f"""SELECT DISTINCT s.id,s.framework_id,s.date_published,
      COALESCE(NULLIF(f.pretty_id,''),f.id) framework_pretty_id,f.dk_code,f.title framework_title
      FROM registry_contracts rc
      JOIN qualifications q ON q.id=rc.qualification_id
      JOIN submissions s ON s.id=q.submission_id
      JOIN frameworks f ON f.id=rc.framework_id
      WHERE {{supplier_condition}} AND {supplier_activity.effective_active_sql('rc','f')}
      ORDER BY s.date_published DESC,s.id"""
    normalized=_digits(code)
    rows=con.execute(sql.format(supplier_condition="rc.supplier_code=?"),(normalized,)).fetchall()
    exact_code_exists=bool(rows) or bool(con.execute(
        "SELECT 1 FROM registry_contracts WHERE supplier_code=? LIMIT 1",(normalized,)).fetchone())
    if not exact_code_exists:  # Preserve support for the few historical formatted supplier codes.
        rows=con.execute(sql.format(supplier_condition="DIGITS(rc.supplier_code)=?"),(normalized,)).fetchall()
    return [dict(row) for row in rows]


def reconcile_stale_nazk_tasks(con, actor="PQM task builder", supplier_codes=None, active_applications=None):
    """Cancel non-terminal NAZK tasks whose supplier has no effective qualification."""
    allowed={_digits(code) for code in supplier_codes or [] if _digits(code)} if supplier_codes is not None else None
    active=active_applications if active_applications is not None else _active_application_map(con)
    rows=con.execute("""SELECT id,supplier_code,status FROM operational_tasks
      WHERE task_type='nazk_check' AND status NOT IN ('completed','cancelled')""").fetchall()
    stamp=now_iso(); cancelled=[]
    for row in rows:
        code=_digits(row["supplier_code"])
        if (allowed is not None and code not in allowed) or active.get(code): continue
        cursor=con.execute("""UPDATE operational_tasks SET status='cancelled',resolution_code='no_active_qualifications',
          resolution_text='Відсутні активні кваліфікації',resolved_at=?,resolved_by=?,updated_at=?,version=version+1
          WHERE id=? AND status NOT IN ('completed','cancelled')""",(stamp,actor,stamp,row["id"]))
        if cursor.rowcount:
            _event(con,row["id"],"cancelled_no_active_qualifications",actor,row["status"],"cancelled",
                   {"reason_code":"no_active_qualifications","effective_active_count":0})
            cancelled.append(row["id"])
    return {"cancelled":len(cancelled),"task_ids":cancelled}


def reconcile_irrelevant_nazk_managers(con, actor="PQM task builder", supplier_codes=None):
    """Cancel active NAZK work when its historical person is no longer current."""
    allowed={_digits(code) for code in supplier_codes or [] if _digits(code)} if supplier_codes is not None else None
    rows=con.execute("""SELECT t.id,t.supplier_code,t.status,t.source_context,c.manager_id,c.manager_name,
      sm.id current_manager_id,sm.manager_name current_manager_name
      FROM operational_tasks t
      LEFT JOIN supplier_nazk_checks c ON c.id=CAST(json_extract(t.source_context,'$.nazk_check_id') AS INTEGER)
      LEFT JOIN supplier_managers sm ON DIGITS(sm.supplier_code)=DIGITS(t.supplier_code) AND sm.is_current=1
      WHERE t.task_type='nazk_check' AND t.status NOT IN ('completed','cancelled')""").fetchall()
    stamp=now_iso(); cancelled=[]
    for row in rows:
        code=_digits(row["supplier_code"])
        if allowed is not None and code not in allowed: continue
        same=(row["manager_id"] is not None and row["current_manager_id"]==row["manager_id"])
        if row["manager_id"] is None:
            same=bool(row["current_manager_name"] and con.execute(
                "SELECT NORMALIZE_NAME(?)=NORMALIZE_NAME(?)",(row["manager_name"],row["current_manager_name"])).fetchone()[0])
        if same: continue
        cursor=con.execute("""UPDATE operational_tasks SET status='cancelled',resolution_code='manager_changed',
          resolution_text='Скасовано — зникла підстава для виключення. Особа, щодо якої виявлено НАЗК, більше не є поточним керівником постачальника.',resolved_at=?,resolved_by=?,updated_at=?,version=version+1
          WHERE id=? AND status NOT IN ('completed','cancelled')""",(stamp,actor,stamp,row["id"]))
        if cursor.rowcount:
            _event(con,row["id"],"cancelled_manager_changed",actor,row["status"],"cancelled",
                   {"reason_code":"manager_changed","task_person":row["manager_name"],"current_manager":row["current_manager_name"]})
            cancelled.append(row["id"])
    return {"cancelled":len(cancelled),"task_ids":cancelled}


def _event(con, task_id, kind, actor="PQM task builder", old=None, new=None, metadata=None):
    con.execute("INSERT INTO operational_task_events(task_id,event_type,created_at,actor,old_value,new_value,metadata) VALUES (?,?,?,?,?,?,?)",
                (task_id, kind, now_iso(), actor, old, new, _json(metadata or {})))


def _create(con, key, task_type, code, priority, source, document, status="new", supplier_name=""):
    existing = con.execute("SELECT id FROM operational_tasks WHERE task_key=?", (key,)).fetchone()
    if existing: return existing[0], False
    task_id = uuid.uuid4().hex; stamp = now_iso()
    con.execute("""INSERT INTO operational_tasks(id,task_key,task_type,supplier_code,supplier_name_snapshot,
      status,priority,created_at,updated_at,source_context,document_context)
      VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
      (task_id,key,task_type,code,supplier_name or _supplier_name(con,code),status,priority,stamp,stamp,_json(source),_json(document)))
    _event(con, task_id, "created", metadata={"trigger_reason": source.get("trigger_reason")})
    if task_type=="nazk_check":
        check_id=int(source.get("nazk_check_id") or 0)
        if not check_id: raise ValueError("НАЗК-задачу не пов’язано з canonical check")
        con.executemany("INSERT OR IGNORE INTO supplier_nazk_check_channels(check_id,channel) VALUES (?,?)",
                        [(check_id,"supplier"),(check_id,"nazk")])
    return task_id, True


def materialize_nazk_tasks(con, actor="PQM task builder", *, supplier_codes=None,
                           active_applications=None, supplier_names=None):
    """Create only NAZK operational tasks from existing supplier-level checks."""
    migrate(con)
    allowed={_digits(code) for code in supplier_codes or [] if _digits(code)} if supplier_codes is not None else None
    active_applications = active_applications if active_applications is not None else _active_application_map(con)
    supplier_names = supplier_names if supplier_names is not None else _supplier_name_map(con)
    counts={"created":0,"existing":0,"completed":0,"nazk":0}
    checks=[dict(r) for r in con.execute("""SELECT c.*,GROUP_CONCAT(m.nazk_source_id) source_ids
      FROM supplier_nazk_checks c
      JOIN supplier_managers sm ON DIGITS(sm.supplier_code)=DIGITS(c.supplier_code) AND sm.is_current=1
        AND ((c.manager_id IS NOT NULL AND c.manager_id=sm.id)
          OR (c.manager_id IS NULL AND NORMALIZE_NAME(c.manager_name)=sm.normalized_name))
      LEFT JOIN supplier_nazk_check_matches m ON m.check_id=c.id
      GROUP BY c.id ORDER BY c.id""")]
    for check in checks:
        code=_digits(check["supplier_code"])
        if allowed is not None and code not in allowed: continue
        apps=active_applications.get(code, [])
        # Imported waiting history without a verified registry cycle is audit
        # evidence, not permission to manufacture another request/task.
        if str(check.get('legacy_key') or '').startswith('web_nazk_history:v1:') and not check.get('source_ids'):
            continue
        if check.get("result")=="refuted":
            for task in con.execute("""SELECT id FROM operational_tasks WHERE task_type='nazk_check'
              AND supplier_code=? AND status NOT IN ('completed','cancelled')
              AND CAST(json_extract(source_context,'$.nazk_check_id') AS INTEGER)=?""",(code,check["id"])):
                con.execute("UPDATE operational_tasks SET status='completed',resolution_code='nazk_refuted',resolved_at=?,updated_at=?,version=version+1 WHERE id=?",(now_iso(),now_iso(),task["id"])); _event(con,task["id"],"nazk_refuted",actor)
                counts["completed"]+=1
            continue
        actionable=check["workflow_status"] in {"needs_review","waiting_response"} or check.get("result")=="confirmed"
        if not actionable or not apps: continue
        record_key=(check.get("source_ids") or str(check["id"])).split(",")[0]
        key=f"nazk_check:{code}:{check['manager_id'] or check['manager_name']}:{record_key}"
        existing_cycle=con.execute("""SELECT task_key FROM operational_tasks WHERE task_type='nazk_check'
          AND supplier_code=? AND CAST(json_extract(source_context,'$.nazk_check_id') AS INTEGER)=?
          AND status NOT IN ('completed','cancelled') ORDER BY created_at,id LIMIT 1""",(code,check['id'])).fetchone()
        if existing_cycle:
            key=existing_cycle['task_key']
        elif not check.get('source_ids') and con.execute("""SELECT 1 FROM operational_tasks
          WHERE task_type='nazk_check' AND supplier_code=?
          AND CAST(json_extract(source_context,'$.nazk_check_id') AS INTEGER)=?
          AND resolution_code='nazk_record_no_longer_present'""",(code,check['id'])).fetchone():
            continue
        status="awaiting_response" if check["workflow_status"]=="waiting_response" else "in_progress"
        source={"source_type":"nazk_registry","supplier_code":code,"person_name":check["manager_name"],"nazk_check_id":check["id"],"nazk_record_ids":(check.get("source_ids") or "").split(",") if check.get("source_ids") else [],"detected_at":now_iso(),"active_application_ids":[x["id"] for x in apps],"active_application_count":len(apps),"trigger_reason":"person_match_requires_verification"}
        document={"document_type":"supplier_exclusion","legal_basis":"пп. 3 п. 40","supplier":{"code":code,"name":supplier_names.get(code,"")},"officer":{},"protocol":{"number":"","date":""},"nazk":{"person_name":check["manager_name"],"check_id":check["id"]}}
        _,created=_create(con,key,"nazk_check",code,"critical" if check.get("result")=="confirmed" else "high",source,document,status,supplier_name=supplier_names.get(code,""))
        counts["created" if created else "existing"]+=1; counts["nazk"]+=1
    return counts


def reconcile_duplicate_nazk_tasks(con, task_ids, actor="PQM NАЗК safe correction", *, apply=False):
    """Cancel only explicitly selected redundant cycles covered by another factual check."""
    import nazk_workflow
    result = {"mode": "apply" if apply else "dry-run", "selected": len(set(task_ids)),
              "proposed": 0, "changed": 0, "skipped": 0, "items": []}
    for task_id in dict.fromkeys(task_ids):
        task = con.execute("SELECT * FROM operational_tasks WHERE id=? AND task_type='nazk_check'", (task_id,)).fetchone()
        if not task:
            result["skipped"] += 1
            continue
        source = _loads(task["source_context"])
        check_id = int(source.get("nazk_check_id") or 0)
        check = con.execute("SELECT * FROM supplier_nazk_checks WHERE id=?", (check_id,)).fetchone()
        manager = con.execute("""SELECT * FROM supplier_managers WHERE supplier_code=? AND is_current=1
          ORDER BY id DESC LIMIT 1""", (task["supplier_code"],)).fetchone()
        if not check or not manager or not (
            (check["manager_id"] is not None and int(check["manager_id"]) == int(manager["id"])) or
            (check["manager_id"] is None and nazk_workflow.normalize_name(check["manager_name"]) ==
             nazk_workflow.normalize_name(manager["manager_name"]))
        ):
            result["skipped"] += 1
            continue
        matches = nazk_workflow.registry_matches(con, manager["manager_name"])
        checks = [dict(row) for row in con.execute("""SELECT c.*,GROUP_CONCAT(cm.nazk_source_id) source_ids
          FROM supplier_nazk_checks c LEFT JOIN supplier_nazk_check_matches cm ON cm.check_id=c.id
          WHERE c.supplier_code=? AND (c.manager_id=? OR
            (c.manager_id IS NULL AND NORMALIZE_NAME(c.manager_name)=?))
          GROUP BY c.id""", (task["supplier_code"], manager["id"],
                              nazk_workflow.normalize_name(manager["manager_name"]))).fetchall()]
        covering = nazk_workflow.find_covering_factual_check(checks, matches, exclude_check_id=check_id)
        if not covering:
            result["skipped"] += 1
            result["items"].append({"task_id": task_id, "supplier_code": task["supplier_code"],
                                    "transition": "unchanged", "reason": "no_covering_factual_check"})
            continue
        if task["resolution_code"] == "duplicate_cycle_existing_factual":
            result["skipped"] += 1
            continue
        if not apply:
            result["proposed"] += 1
            result["items"].append({"task_id": task_id, "supplier_code": task["supplier_code"],
                                    "transition": "cancelled", "covering_check_id": covering["check_id"]})
            continue
        stamp = now_iso()
        old_status, old_resolution = task["status"], task["resolution_code"]
        source["duplicate_cycle_provenance"] = covering
        metadata = _loads(task["metadata"])
        metadata["duplicate_cycle_provenance"] = covering
        con.execute("""UPDATE operational_tasks SET status='cancelled',resolution_code=?,resolution_text=?,
          source_context=?,metadata=?,resolved_at=?,resolved_by=?,updated_at=?,version=version+1 WHERE id=?""",
          ("duplicate_cycle_existing_factual",
           "Скасовано — цей самий факт НАЗК уже має канонічний фактичний результат.",
           _json(source), _json(metadata), stamp, actor, stamp, task_id))
        _event(con, task_id, "duplicate_cycle_reconciled_to_existing_factual", actor,
               f"{old_status}:{old_resolution}", "cancelled:duplicate_cycle_existing_factual",
               {"covering_factual_check": covering, "redundant_check_id": check_id})
        nazk_workflow.archive_duplicate_nazk_checks(con, [check_id], covering, actor=actor, timestamp=stamp)
        result["changed"] += 1
        result["items"].append({"task_id": task_id, "supplier_code": task["supplier_code"],
                                "transition": "cancelled", "covering_check_id": covering["check_id"]})
    return result


def _link_apps(con, task_id, applications, relation="active_application"):
    con.executemany("INSERT OR IGNORE INTO operational_task_applications VALUES (?,?,?)",
                    [(task_id,item["id"],relation) for item in applications])


def _warning_date(value):
    text = str(value or "")[:10]
    try: return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError: return None


def subtract_calendar_months(value, months_back):
    index = value.year * 12 + value.month - 1 - months_back
    year, month = divmod(index, 12)
    month += 1
    return date(year, month, min(value.day, calendar.monthrange(year, month)[1]))


def _warning_events(rows, moment=None):
    """Return the one current rolling-window threshold, if any."""
    today = moment or date.today()
    parsed = [(row, _warning_date(row.get("decision_date"))) for row in rows]
    parsed = [(row, day) for row,day in parsed if day and day <= today]
    parsed.sort(key=lambda pair: (pair[1], pair[0]["id"]))
    one_month=[pair for pair in parsed if subtract_calendar_months(today,1) <= pair[1] <= today]
    three_months=[pair for pair in parsed if subtract_calendar_months(today,3) <= pair[1] <= today]
    if len(one_month) >= 3:
        selected=one_month[-3:]
        return [("3_in_1_rolling_month",selected[-1][0],selected[-1][1],selected)]
    if len(three_months) >= 5:
        selected=three_months[-5:]
        return [("5_in_3_rolling_months",selected[-1][0],selected[-1][1],selected)]
    return []


def _next_warning_event(rows, used_ids=(), moment=None):
    available = [row for row in rows if row["id"] not in set(used_ids)]
    events = _warning_events(available, moment)
    return events[0] if events else None


def build(con, actor="PQM task builder", *, include_nazk=False):
    """Generic materialization is NAZK-free unless explicitly opted in."""
    migrate(con); counts={"created":0,"existing":0,"completed":0,"amcu":0,"nazk":0,"warning":0}
    active_applications = _active_application_map(con)
    if include_nazk:
        counts["completed"] += reconcile_stale_nazk_tasks(
            con, actor, active_applications=active_applications)["cancelled"]
        counts["completed"] += reconcile_irrelevant_nazk_managers(con, actor)["cancelled"]
    supplier_names = _supplier_name_map(con)
    amcu_decisions = {}
    for row in con.execute("SELECT * FROM amcu_registry ORDER BY decision_date,row_key"):
        item = dict(row)
        amcu_decisions.setdefault(_digits(item.get("offender_code")), []).append(item)
    # AMCU: one active task per supplier; decisions and applications remain canonical links.
    codes={_digits(row[0]) for row in con.execute(
        "SELECT DISTINCT offender_code FROM amcu_registry WHERE COALESCE(offender_code,'')<>''")}
    codes.intersection_update(active_applications)
    stamp = now_iso()
    for stale in con.execute("""SELECT id,supplier_code FROM operational_tasks
      WHERE task_type='amcu_exclusion' AND status NOT IN ('completed','cancelled')""").fetchall():
        if _digits(stale["supplier_code"]) in codes:
            continue
        con.execute("""UPDATE operational_tasks SET status='cancelled',resolution_code='no_active_qualifications',
          resolution_text='Постачальник не має поточних активних кваліфікацій',resolved_at=?,
          resolved_by=?,updated_at=?,version=version+1 WHERE id=?""",
          (stamp,actor,stamp,stale["id"]))
        _event(con,stale["id"],"cancelled_no_active_qualifications",actor,
               "active","cancelled",{"canonical_source":"supplier_activity.effective_active_sql"})
        counts["completed"] += 1
    for code in filter(None,codes):
        apps=active_applications.get(code, [])
        active=con.execute("SELECT id,status FROM operational_tasks WHERE task_type='amcu_exclusion' AND supplier_code=? AND status NOT IN ('completed','cancelled')",(code,)).fetchone()
        if not apps:
            if active and active["status"]=="awaiting_sync":
                con.execute("UPDATE operational_tasks SET status='completed',resolution_code='amcu_excluded',resolved_at=?,updated_at=?,version=version+1 WHERE id=?",(now_iso(),now_iso(),active["id"])); _event(con,active["id"],"completed",actor); counts["completed"]+=1
            continue
        decisions=amcu_decisions.get(code, [])
        base_key=f"amcu_exclusion:{code}"
        prior=con.execute("SELECT status FROM operational_tasks WHERE task_key=?",(base_key,)).fetchone()
        key=(f"{base_key}:{apps[0]['id']}" if prior and prior["status"] in TERMINAL else base_key)
        source={"source_type":"amcu_registry","supplier_code":code,"detected_at":now_iso(),"active_application_ids":[x["id"] for x in apps],"active_application_count":len(apps),"amcu_decision_ids":[x["row_key"] for x in decisions],"trigger_reason":"supplier_in_amcu_registry_with_active_applications"}
        document={"document_type":"supplier_exclusion","legal_basis":"пп. 7 п. 40","supplier":{"code":code,"name":supplier_names.get(code,"")},"officer":{},"protocol":{"number":"","date":""},"amcu_decisions":[]}
        task_id,created=_create(con,key,"amcu_exclusion",code,"high",source,document,supplier_name=supplier_names.get(code,""))
        counts["created" if created else "existing"]+=1; counts["amcu"]+=1; _link_apps(con,task_id,apps)
        stamp=now_iso(); con.executemany("INSERT OR IGNORE INTO operational_task_amcu_decisions VALUES (?,?, '',?,?,?)",[(task_id,x["row_key"],stamp,stamp,actor) for x in decisions])
    if include_nazk:
        nazk_counts=materialize_nazk_tasks(con,actor,active_applications=active_applications,
                                          supplier_names=supplier_names)
        counts["created"]+=nazk_counts["created"]
        counts["existing"]+=nazk_counts["existing"]
        counts["completed"]+=nazk_counts["completed"]
        counts["nazk"]+=nazk_counts["nazk"]
    # Warning threshold: rolling calendar-month windows and immutable references.
    supplier_codes=[row[0] for row in con.execute("SELECT DISTINCT defendant_code FROM violation_reports WHERE status='satisfied' AND COALESCE(decision_date,'')<>''")]
    for raw_code in supplier_codes:
        code=_digits(raw_code); rows=[dict(r) for r in con.execute("""SELECT id,report_id,date_published,decision_date,tender_pretty_id,author_name
          FROM violation_reports WHERE DIGITS(defendant_code)=? AND status='satisfied' AND COALESCE(decision_date,'')<>'' ORDER BY decision_date,id""",(code,))]
        tasks=[dict(r) for r in con.execute("""SELECT * FROM operational_tasks
          WHERE task_type='warning_block' AND supplier_code=? ORDER BY created_at,id""",(code,))]
        task_warning_ids={task["id"]:{r[0] for r in con.execute(
            "SELECT violation_report_id FROM operational_task_warnings WHERE task_id=?",(task["id"],))}
            for task in tasks}
        current_event=(_warning_events(rows) or [None])[0]
        current_ids={r["id"] for r,_ in current_event[3]} if current_event else set()
        active_tasks=[task for task in tasks if task["status"] not in TERMINAL]
        matching_active=next((task for task in active_tasks if task_warning_ids[task["id"]]==current_ids),None)
        if matching_active:
            threshold=current_event[0]
            source=_loads(matching_active["source_context"])
            if matching_active["status"]=="new" and source.get("threshold_type")!=threshold:
                old_threshold=source.get("threshold_type") or ""
                source.update(threshold_type=threshold,rolling_window_to=date.today().isoformat(),
                              rolling_window_from=subtract_calendar_months(
                                  date.today(),1 if threshold.startswith("3_") else 3).isoformat())
                con.execute("UPDATE operational_tasks SET source_context=?,updated_at=?,version=version+1 WHERE id=?",
                            (_json(source),now_iso(),matching_active["id"]))
                _event(con,matching_active["id"],"threshold_reconciled_to_rolling",actor,
                       old_threshold,threshold,{"warning_ids":sorted(current_ids)})
            counts["existing"]+=1; counts["warning"]+=1
            continue
        # Only untouched auto-created tasks are safe to reconcile automatically.
        stamp=now_iso()
        for task in active_tasks:
            user_events=con.execute("""SELECT COUNT(*) FROM operational_task_events
              WHERE task_id=? AND event_type<>'created'""",(task["id"],)).fetchone()[0]
            if task["status"]!="new" or user_events:
                counts["existing"]+=1; counts["warning"]+=1
                matching_active=task
                break
            con.execute("""UPDATE operational_tasks SET status='cancelled',resolution_code='not_applicable',
              resolution_text='Поточний rolling-поріг попереджень не підтверджено',resolved_at=?,
              resolved_by=?,updated_at=?,version=version+1 WHERE id=?""",(stamp,actor,stamp,task["id"]))
            _event(con,task["id"],"cancelled_false_rolling_threshold",actor,"new","cancelled",
                   {"warning_ids":sorted(task_warning_ids[task["id"]])})
            counts["completed"]+=1
        if matching_active:
            continue
        used_ids=set().union(*(task_warning_ids[task["id"]] for task in tasks
                              if task["status"]=="completed")) if tasks else set()
        next_event=_next_warning_event(rows,used_ids)
        for threshold,trigger,trigger_day,selected in ([next_event] if next_event else []):
            key=f"warning_block:{code}:{threshold}:{trigger['report_id'] or trigger['id']}"
            start=trigger_day; end=start+timedelta(days=90)
            refs=[{"id":r["id"],"report_id":r["report_id"],"report_date":r["date_published"],"decision_date":r["decision_date"],"procurement_id":r["tender_pretty_id"],"customer_name":r["author_name"],"url":""} for r,_ in selected]
            source={"source_type":"supplier_warnings","supplier_code":code,"threshold_type":threshold,"threshold_reached_at":start.isoformat(),"warning_ids":[x["report_id"] for x in refs],"warning_count":len(refs),"block_days":90,"blocking_start_date":start.isoformat(),"blocking_end_date":end.isoformat(),"trigger_reason":"warning_threshold_reached"}
            document={"document_type":"supplier_blocking","legal_basis":"п. 52 Порядку № 822","supplier":{"code":code,"name":supplier_names.get(code,"")},"officer":{},"protocol":{"number":"","date":start.isoformat()},"warning_references":refs,"blocking_period":{"days":90,"start_date":start.isoformat(),"end_date":end.isoformat()}}
            task_id,created=_create(con,key,"warning_block",code,"critical",source,document,supplier_name=supplier_names.get(code,""))
            counts["created" if created else "existing"]+=1; counts["warning"]+=1
            if created:
                con.executemany("INSERT INTO operational_task_warnings VALUES (?,?,?,?)",[(task_id,r["id"],r["decision_date"],i+1) for i,(r,_) in enumerate(selected)])
    return counts


def _task(con,row,detail=False):
    item=dict(row); item["source_context"]=_loads(item["source_context"]); item["document_context"]=_loads(item["document_context"]); item["metadata"]=_loads(item["metadata"])
    item["overdue"]=bool(item.get("due_at") and item["due_at"]<now_iso() and item["status"] not in TERMINAL)
    item["needs_action"]=item["status"] in {"new","in_progress","ready_for_document"}
    if "_assigned_officer_name" in item:
        item["assigned_officer_name"]=item.pop("_assigned_officer_name") or ""
    else:
        officer=con.execute("SELECT full_name FROM authorized_officers WHERE id=?",(item.get("assigned_officer_id"),)).fetchone(); item["assigned_officer_name"]=officer[0] if officer else ""
    canonical_officer_id=item.pop("_nazk_responsible_officer_id",None)
    if item.get("task_type")=="nazk_check" and canonical_officer_id is not None:
        item["assigned_officer_id"]=canonical_officer_id
    effective_apps=_effective_active_applications(con,item["supplier_code"]) if detail else None
    item["effective_active_count"]=(len(effective_apps) if detail else int(item["source_context"].get("active_application_count") or 0))
    item["active_application_count"]=item["effective_active_count"]  # backward-compatible API alias
    has_preloaded_nazk="_nazk_id" in item
    preloaded_nazk={key.removeprefix("_nazk_"):item.pop(key) for key in tuple(item) if key.startswith("_nazk_") and item[key] is not None}
    for key in tuple(item):
        if key.startswith("_nazk_"): item.pop(key)
    if item.get("task_type")=="nazk_check":
        if has_preloaded_nazk:
            item["nazk_current_state"]=preloaded_nazk
        else:
            check_id=item["source_context"].get("nazk_check_id")
            check=con.execute("SELECT id,workflow_status,result,manager_name,completed_at,updated_at FROM supplier_nazk_checks WHERE id=?",(check_id,)).fetchone()
            item["nazk_current_state"]=dict(check) if check else {}
    if detail:
        item["effective_applications"]=effective_apps
        item["applications"]=[dict(r) for r in con.execute("""SELECT a.relation_type,s.id,COALESCE(NULLIF(f.pretty_id,''),f.id) framework_id,f.dk_code,f.title
          FROM operational_task_applications a JOIN submissions s ON s.id=a.application_id LEFT JOIN frameworks f ON f.id=s.framework_id WHERE a.task_id=? ORDER BY f.dk_code,s.date_published DESC""",(item["id"],))]
        item["warnings"]=([dict(r) for r in con.execute("""SELECT w.sequence_no,w.warning_date,v.report_id,v.contract_pretty_id,v.date_published,v.decision_date,v.tender_pretty_id,v.author_name
          FROM operational_task_warnings w JOIN violation_reports v ON v.id=w.violation_report_id WHERE w.task_id=? ORDER BY w.sequence_no""",(item["id"],))]
          if item["task_type"]=="warning_block" else [])
        item["amcu_decisions"]=([dict(r) for r in con.execute("""SELECT a.row_key,a.decision_no,a.decision_date,a.authority,a.court_case_no,l.extract_url
          FROM operational_task_amcu_decisions l JOIN amcu_registry a ON a.row_key=l.amcu_decision_id WHERE l.task_id=? ORDER BY a.decision_date,a.row_key""",(item["id"],))]
          if item["task_type"]=="amcu_exclusion" else [])
        item["events"]=[{**dict(r),"metadata":_loads(r["metadata"])} for r in con.execute("SELECT * FROM operational_task_events WHERE task_id=? ORDER BY id",(item["id"],))]
        item["channels"]={r["channel"]:dict(r) for r in con.execute(
            "SELECT * FROM operational_task_channels WHERE task_id=? ORDER BY channel",(item["id"],))}
        item["responses"]=[dict(r) for r in con.execute(
            "SELECT * FROM operational_task_responses WHERE task_id=? ORDER BY recorded_at DESC,id DESC",(item["id"],))]
        if item["task_type"]=="nazk_check":
            current=con.execute("""SELECT id,manager_name,manager_tax_id FROM supplier_managers
              WHERE DIGITS(supplier_code)=? AND is_current=1""",(_digits(item["supplier_code"]),)).fetchone()
            item["current_manager"]=dict(current) if current else {}
            check_id=item["source_context"].get("nazk_check_id")
            evidence=nazk_evidence.get(con,int(check_id))
            item["nazk_check_id"]=int(check_id)
            item["nazk_evidence"]=evidence
            item["nazk_current_state"]={**item.get("nazk_current_state",{}),**{
              key:evidence.get(key) for key in ("id","workflow_status","result","manager_name","person_tax_id",
                "evidence_date","result_at","result_by","completed_at","responsible_officer_id","responsible_uo_name")}}
            item["nazk_records"]=evidence["registry_records"]
            item["channels"]={key:{**value,"outgoing_number":value.get("document_number",""),
              "reference_url":value.get("evidence_url","")} for key,value in evidence["channels"].items()}
            item["responses"]=[{**value,"response_date":value.get("evidence_date"),
              "incoming_number":value.get("document_number","")+"","reference_url":value.get("evidence_url",""),
              "document_reference":value.get("uploaded_document_name","")+"","summary":value.get("short_summary","")}
              for value in evidence["evidence"]]
            item["assigned_officer_id"]=evidence.get("responsible_officer_id")
            item["assigned_officer_name"]=evidence.get("responsible_uo_name") or ""
            check_manager=item.get("nazk_current_state",{}).get("manager_name") or item["source_context"].get("person_name") or ""
            check_manager_id=con.execute("SELECT manager_id FROM supplier_nazk_checks WHERE id=?",(check_id,)).fetchone()
            item["task_person_is_current"]=bool(current and ((check_manager_id and check_manager_id[0] is not None and check_manager_id[0]==current["id"])
                or (check_manager_id and check_manager_id[0] is None and con.execute("SELECT NORMALIZE_NAME(?)=NORMALIZE_NAME(?)",(check_manager,current["manager_name"])).fetchone()[0])))
            resolved_rnokpp=(current_manager_rnokpp(con,item["supplier_code"],item["current_manager"])
              if item["task_person_is_current"] else {"value":"","source":"","identity_confirmed":False})
            if resolved_rnokpp["value"]:
                item["current_manager"]["manager_tax_id"]=resolved_rnokpp["value"]
                item["current_manager"]["manager_tax_id_resolved_source"]=resolved_rnokpp["source"]
                person_rnokpp=evidence.get("person_rnokpp") or resolved_rnokpp["value"]
                evidence["person_rnokpp"]=person_rnokpp
                evidence["person_rnokpp_source"]=("supplier_nazk_checks.person_tax_id"
                  if evidence.get("person_tax_id") else resolved_rnokpp["source"])
                item["nazk_current_state"]["person_rnokpp"]=person_rnokpp
        elif item["task_type"]=="warning_block":
            decision=con.execute("SELECT * FROM operational_task_blocking_decisions WHERE task_id=?",(item["id"],)).fetchone()
            item["blocking_decision"]=dict(decision) if decision else {}
            blocked=con.execute("""SELECT COUNT(*) FROM registry_contracts
              WHERE DIGITS(supplier_code)=? AND LOWER(COALESCE(status,'')) IN ('suspended','blocked')""",(_digits(item["supplier_code"]),)).fetchone()[0]
            item["blocking_factual_state"]="blocked" if blocked else "not_confirmed"
            end=(item.get("source_context") or {}).get("blocking_end_date") or ""
            item["highlighting_active"]=bool(item.get("blocking_decision",{}).get("used_for_blocking") and end>=date.today().isoformat())
        item["document_context"]=build_document_context(item)
    return item




def build_document_context(item):
    """Return reusable structured context only; document rendering belongs to Block 4."""
    context=dict(item.get("document_context") or {})
    context["supplier"]={"code":item.get("supplier_code") or "","name":item.get("supplier_name_snapshot") or ""}
    context["officer"]={"id":item.get("assigned_officer_id"),"name":item.get("assigned_officer_name") or ""}
    if item.get("task_type")=="amcu_exclusion":
        context["effective_active_qualifications"]=item.get("effective_applications") or []
        context["amcu_decisions"]=[{**decision,
          "displayed_text":f"від {decision.get('decision_date') or ''} № {decision.get('decision_no') or ''}",
          "hyperlink":decision.get("extract_url") or ""} for decision in item.get("amcu_decisions") or []]
    elif item.get("task_type")=="warning_block":
        source=item.get("source_context") or {}
        context.update({"threshold_type":source.get("threshold_type"),"warning_count":source.get("warning_count"),
          "protocol_date":source.get("threshold_reached_at"),"blocking_start_date":source.get("blocking_start_date"),
          "blocking_end_date":source.get("blocking_end_date"),"blocking_days":source.get("block_days") or 90,
          "legal_basis":"п. 52 Порядку № 822","warning_references":item.get("warnings") or [],
          "protocol":item.get("blocking_decision") or {}})
    elif item.get("task_type")=="nazk_check":
        context["nazk"]={"person":item.get("source_context",{}).get("person_name") or "",
          "records":item.get("nazk_records") or [],"channels":item.get("channels") or {}}
    return context


def list_tasks(con,params):
    where=[]; args=[]
    def value(key):
        raw=params.get(key,[""]); return (raw[0] if isinstance(raw,list) else raw).strip()
    if value("type"): where.append("task_type=?"); args.append(value("type"))
    if value("officer"): where.append("CAST(assigned_officer_id AS TEXT)=?"); args.append(value("officer"))
    group=value("status_group") or "active"
    if group not in STATUS_GROUPS: raise ValueError("Невідома група статусів")
    grouped=sorted(STATUS_GROUPS[group]); where.append("status IN (%s)" % ",".join("?" for _ in grouped)); args.extend(grouped)
    search=value("search").casefold()
    if search:
        search_predicates=["INSTR(CASEFOLD(COALESCE(supplier_name_snapshot,'')),?)>0"]
        search_args=[search]
        search_digits=_digits(search)
        if search_digits:
            search_predicates.append("INSTR(supplier_code,?)>0")
            search_args.append(search_digits)
        where.append("("+" OR ".join(search_predicates)+")")
        args.extend(search_args)
    if value("date_from"): where.append("SUBSTR(created_at,1,10)>=?"); args.append(value("date_from"))
    clause=" WHERE "+" AND ".join(where) if where else ""
    projection="""SELECT t.*,COALESCE(nuo.full_name,c.responsible_officer_name,o.full_name) _assigned_officer_name,
      c.responsible_officer_id _nazk_responsible_officer_id,
      c.id _nazk_id,c.workflow_status _nazk_workflow_status,c.result _nazk_result,
      c.manager_name _nazk_manager_name,c.completed_at _nazk_completed_at,c.updated_at _nazk_updated_at
      FROM operational_tasks t LEFT JOIN authorized_officers o ON o.id=t.assigned_officer_id
      LEFT JOIN supplier_nazk_checks c ON c.id=CAST(json_extract(t.source_context,'$.nazk_check_id') AS INTEGER)
      LEFT JOIN authorized_officers nuo ON nuo.id=c.responsible_officer_id"""
    qualified_clause=clause.replace("status", "t.status").replace("task_type", "t.task_type").replace("assigned_officer_id", "COALESCE(c.responsible_officer_id,t.assigned_officer_id)").replace("supplier_name_snapshot", "t.supplier_name_snapshot").replace("supplier_code", "t.supplier_code").replace("created_at", "t.created_at")
    rows=con.execute(projection+qualified_clause+" ORDER BY CASE t.priority WHEN 'critical' THEN 0 WHEN 'high' THEN 1 ELSE 2 END,t.created_at DESC",args).fetchall()
    items=[_task(con,row) for row in rows]
    all_rows=con.execute("SELECT status FROM operational_tasks").fetchall()
    kpis={key:sum(r[0] in statuses for r in all_rows) for key,statuses in STATUS_GROUPS.items()}
    return {"items":items,"total":len(items),"kpis":kpis,"status_group":group}


def detail(con,task_id):
    row=con.execute("""SELECT t.*,COALESCE(nuo.full_name,c.responsible_officer_name,o.full_name) _assigned_officer_name,
      c.responsible_officer_id _nazk_responsible_officer_id,
      c.id _nazk_id,c.workflow_status _nazk_workflow_status,c.result _nazk_result,
      c.manager_name _nazk_manager_name,c.completed_at _nazk_completed_at,c.updated_at _nazk_updated_at
      FROM operational_tasks t LEFT JOIN authorized_officers o ON o.id=t.assigned_officer_id
      LEFT JOIN supplier_nazk_checks c ON c.id=CAST(json_extract(t.source_context,'$.nazk_check_id') AS INTEGER)
      LEFT JOIN authorized_officers nuo ON nuo.id=c.responsible_officer_id
      WHERE t.id=?""",(task_id,)).fetchone()
    if not row: raise KeyError(task_id)
    return _task(con,row,True)


def update(con,task_id,payload,actor):
    current=detail(con,task_id); fields=[]; args=[]
    status=str(payload.get("status") or current["status"])
    if status not in STATUSES: raise ValueError("Невідомий статус задачі")
    if status!=current["status"] and status not in TRANSITIONS[current["status"]]: raise ValueError("Недопустимий перехід статусу")
    resolution=str(payload.get("resolution_code",current.get("resolution_code") or ""))
    if resolution not in RESOLUTIONS: raise ValueError("Невідомий результат задачі")
    officer=payload.get("assigned_officer_id",current.get("assigned_officer_id")) or None
    if current['status'] in TERMINAL and str(officer or '') != str(current.get('assigned_officer_id') or ''):
        raise ValueError('У завершеній задачі відповідальна УО доступна лише для перегляду')
    if officer and not con.execute("SELECT 1 FROM authorized_officers WHERE id=? AND active=1",(officer,)).fetchone(): raise ValueError("Оберіть активну УО")
    if status=="ready_for_document" and not officer: raise ValueError("Призначте відповідальну УО")
    if status=="ready_for_document" and current["task_type"]=="amcu_exclusion" and any(
            not str(x.get("extract_url") or "").strip() for x in current.get("amcu_decisions") or []):
        raise ValueError("Додайте посилання на витяг для всіх рішень АМКУ")
    stamp=now_iso(); resolved=stamp if status=="completed" else current.get("resolved_at")
    task_officer=officer
    if current["task_type"]=="nazk_check":
        check_id=nazk_evidence.check_id_for_task(current)
        nazk_evidence.set_responsible_officer(con,check_id,officer,actor,stamp)
        task_officer=None  # responsible UO is canonical on supplier_nazk_checks
    cursor=con.execute("""UPDATE operational_tasks SET status=?,assigned_officer_id=?,resolution_code=?,resolution_text=?,
      protocol_number=?,protocol_date=?,protocol_reference=?,published_reference=?,resolved_at=?,resolved_by=?,updated_at=?,version=version+1 WHERE id=? AND version=?""",
      (status,task_officer,resolution,str(payload.get("resolution_text",current.get("resolution_text") or "")),str(payload.get("protocol_number",current.get("protocol_number") or "")),str(payload.get("protocol_date",current.get("protocol_date") or "")),str(payload.get("protocol_reference",current.get("protocol_reference") or "")),str(payload.get("published_reference",current.get("published_reference") or "")),resolved,actor if resolved else current.get("resolved_by"),stamp,task_id,current["version"]))
    if cursor.rowcount==0: raise ValueError("Задачу вже змінив інший користувач; оновіть сторінку")
    if status!=current["status"]: _event(con,task_id,"status_changed",actor,current["status"],status)
    if officer!=current.get("assigned_officer_id"): _event(con,task_id,"assigned",actor,str(current.get("assigned_officer_id") or ""),str(officer or ""))
    return detail(con,task_id)


def set_amcu_extract(con,task_id,decision_id,url,actor):
    if not con.execute("SELECT 1 FROM operational_task_amcu_decisions WHERE task_id=? AND amcu_decision_id=?",(task_id,decision_id)).fetchone(): raise KeyError(decision_id)
    old=con.execute("SELECT extract_url FROM operational_task_amcu_decisions WHERE task_id=? AND amcu_decision_id=?",(task_id,decision_id)).fetchone()[0]
    con.execute("UPDATE operational_task_amcu_decisions SET extract_url=?,updated_at=?,updated_by=? WHERE task_id=? AND amcu_decision_id=?",(str(url or "").strip(),now_iso(),actor,task_id,decision_id)); _event(con,task_id,"amcu_extract_url_added",actor,old,str(url or "").strip(),{"decision_id":decision_id})
    return detail(con,task_id)


CHANNEL_STATES={"not_sent","document_prepared","waiting","response_received","closed","cancelled"}
INFORMATION_RESULTS={"neutral","refutes","confirms"}
NAZK_RESULTS={"confirmed","refuted","insufficient","not_current"}


def record_channel_sent(con,task_id,channel,payload,actor):
    current=detail(con,task_id)
    if current["task_type"]!="nazk_check" or channel not in {"supplier","nazk"}: raise ValueError("Невідомий канал запиту")
    if current["status"] in TERMINAL: raise ValueError("Закриту задачу не можна перевести в очікування")
    sent_at=str(payload.get("sent_at") or "").strip()
    if not sent_at: raise ValueError("Зазначте дату направлення")
    check_id=nazk_evidence.check_id_for_task(current)
    nazk_evidence.record_channel(con,check_id,channel,payload,actor,source_task_id=task_id)
    con.execute("""UPDATE supplier_nazk_checks SET workflow_status='waiting_response',updated_at=?,updated_by=?
      WHERE id=? AND workflow_status NOT IN ('completed','legacy_archived')""",(now_iso(),actor,check_id))
    if current["status"]!="waiting_external":
        con.execute("UPDATE operational_tasks SET status='waiting_external',updated_at=?,version=version+1 WHERE id=?",(now_iso(),task_id))
    _event(con,task_id,"request_sent",actor,current.get("channels",{}).get(channel,{}).get("status","not_sent"),"waiting",{"channel":channel,"sent_at":sent_at})
    nazk_evidence.event(con,check_id,"request_sent",actor,{"task_id":task_id,"channel":channel,"sent_at":sent_at})
    return detail(con,task_id)


def add_response(con,task_id,payload,actor):
    current=detail(con,task_id); source=str(payload.get("source") or "")
    if current["task_type"]!="nazk_check" or source not in {"supplier","nazk","other"}: raise ValueError("Оберіть джерело інформації")
    result=str(payload.get("information_result") or "neutral")
    if result not in INFORMATION_RESULTS: raise ValueError("Невідомий результат інформації")
    post_close=int(current["status"] in TERMINAL)
    check_id=nazk_evidence.check_id_for_task(current)
    evidence_id=nazk_evidence.add_evidence(
        con,check_id,payload,actor,post_close=bool(post_close),source_task_id=task_id)
    if source in {"supplier","nazk"}:
        con.execute("UPDATE supplier_nazk_check_channels SET status='response_received',recorded_at=?,recorded_by=? WHERE check_id=? AND channel=?",
                    (now_iso(),actor,check_id,source))
    if not post_close:
        if result in {"refutes","confirms"}:
            factual="refuted" if result=="refutes" else "confirmed"
            stamp=now_iso()
            con.execute("""UPDATE supplier_nazk_checks SET result=?,workflow_status='completed',completed_at=?,
              result_at=?,result_by=?,evidence_date=COALESCE(NULLIF(?,''),evidence_date),updated_at=?,updated_by=? WHERE id=?""",
                        (factual,stamp,stamp,actor,str(payload.get("response_date") or "").strip(),stamp,actor,check_id))
            next_status="completed" if factual=="refuted" else ("ready_for_document" if current["effective_active_count"] else "cancelled")
            resolution="nazk_refuted" if factual=="refuted" else ("nazk_confirmed" if next_status!="cancelled" else "no_active_qualifications")
            con.execute("UPDATE operational_tasks SET status=?,resolution_code=?,resolved_at=?,resolved_by=?,updated_at=?,version=version+1 WHERE id=?",
                        (next_status,resolution,now_iso() if next_status in TERMINAL else None,actor if next_status in TERMINAL else None,now_iso(),task_id))
    details={"task_id":task_id,"evidence_id":evidence_id,"source":source,"information_result":result}
    _event(con,task_id,"post_close_information" if post_close else "response_received",actor,metadata=details)
    nazk_evidence.event(con,check_id,"post_close_information" if post_close else "response_received",actor,details)
    return detail(con,task_id)


def update_response(con,task_id,evidence_id,payload,actor):
    current=detail(con,task_id)
    if current["task_type"]!="nazk_check": raise ValueError("Дія доступна лише для НАЗК-перевірки")
    if current["status"] in TERMINAL: raise ValueError("У завершеній задачі інформація доступна лише для перегляду")
    source=str(payload.get("source") or "")
    if source not in {"supplier","nazk","other"}: raise ValueError("Оберіть джерело інформації")
    information_result=str(payload.get("information_result") or "neutral")
    if information_result not in INFORMATION_RESULTS: raise ValueError("Невідомий результат інформації")
    check_id=nazk_evidence.check_id_for_task(current)
    old,new=nazk_evidence.update_evidence(con,check_id,int(evidence_id),payload,actor)
    changes={key:{"old":old.get(key),"new":new.get(key)} for key in (
        "source","evidence_date","document_number","short_summary","uploaded_document_name",
        "evidence_url","comment","information_result") if old.get(key)!=new.get(key)}
    if changes:
        details={"task_id":task_id,"evidence_id":int(evidence_id),"changes":changes}
        _event(con,task_id,"response_information_edited",actor,metadata=details)
        nazk_evidence.event(con,check_id,"response_information_edited",actor,details)
    return detail(con,task_id)


def set_nazk_result(con,task_id,result,actor,comment=""):
    current=detail(con,task_id)
    if current["task_type"]!="nazk_check" or current["status"] in TERMINAL: raise ValueError("Результат недоступний для цієї задачі")
    if result not in NAZK_RESULTS: raise ValueError("Оберіть результат перевірки")
    check_id=current.get("source_context",{}).get("nazk_check_id")
    factual=result if result in {"confirmed","refuted"} else ("needs_review" if result=="insufficient" else None)
    workflow="completed" if result in {"confirmed","refuted"} else ("not_current" if result=="not_current" else "in_progress")
    stamp=now_iso()
    con.execute("""UPDATE supplier_nazk_checks SET result=?,workflow_status=?,completed_at=?,result_at=?,result_by=?,
      updated_at=?,updated_by=? WHERE id=?""",
                (factual,workflow,stamp if workflow=="completed" else None,stamp if workflow=="completed" else None,
                 actor if workflow=="completed" else "",stamp,actor,check_id))
    waiting=any(x.get("status")=="waiting" for x in current.get("channels",{}).values())
    if result=="not_current": status,resolution="completed","nazk_not_current"
    elif result=="refuted": status,resolution="completed","nazk_refuted"
    elif result=="confirmed" and current["effective_active_count"]: status,resolution="ready_for_document","nazk_confirmed"
    elif result=="confirmed": status,resolution="cancelled","no_active_qualifications"
    else: status,resolution=("waiting_external" if waiting else "in_progress"),""
    terminal=status in TERMINAL
    con.execute("UPDATE operational_tasks SET status=?,resolution_code=?,resolved_at=?,resolved_by=?,updated_at=?,version=version+1 WHERE id=?",
                (status,resolution,now_iso() if terminal else None,actor if terminal else None,now_iso(),task_id))
    if result=="not_current" and "resolution_text" in {row[1] for row in con.execute("PRAGMA table_info(operational_tasks)")}:
        con.execute("UPDATE operational_tasks SET resolution_text=? WHERE id=?",("НАЗК · Не актуально",task_id))
    metadata={"result":result}
    if comment.strip(): metadata["comment"]=comment.strip()
    task_event={"confirmed":"nazk_result_confirmed","refuted":"nazk_result_refuted","insufficient":"nazk_result_insufficient","not_current":"nazk_result_not_current"}[result]
    check_event={"confirmed":"result_confirmed","refuted":"result_refuted","insufficient":"result_insufficient","not_current":"result_not_current"}[result]
    _event(con,task_id,task_event,actor,metadata=metadata)
    nazk_evidence.event(con,check_id,check_event,actor,{"task_id":task_id,**metadata})
    return detail(con,task_id)


def set_task_manager_tax_id(con,task_id,value,actor):
    current=detail(con,task_id)
    if current["task_type"]!="nazk_check" or current["status"] in TERMINAL: raise ValueError("РНОКПП недоступний для редагування")
    digits=_digits(value)
    if len(digits)!=10: raise ValueError("РНОКПП повинен містити 10 цифр")
    manager=current.get("current_manager") or {}
    if not manager.get("id"): raise ValueError("Поточного керівника не визначено")
    con.execute("""UPDATE supplier_managers SET manager_tax_id=?,manager_tax_id_source='operational_manual',
      manager_tax_id_verified_at=?,manager_tax_id_verified_by=?,updated_at=? WHERE id=? AND is_current=1""",
      (digits,now_iso(),actor,now_iso(),manager["id"]))
    # Runtime NAZK tasks always carry nazk_check_id. Keep isolated legacy/import
    # rows compatible without inventing a canonical relation for them.
    check_id=int((current.get("source_context") or {}).get("nazk_check_id") or 0)
    if check_id:
        nazk_evidence.set_person_tax_id(con,check_id,digits,actor)
    _event(con,task_id,"manager_tax_id_added",actor,metadata={"manager_id":manager["id"]})
    return detail(con,task_id)


def attach_blocking_decision(con,task_id,payload,actor):
    current=detail(con,task_id)
    if current["task_type"]!="warning_block": raise ValueError("Дія доступна лише для задачі блокування")
    if current['status'] in TERMINAL: raise ValueError('Реквізити завершеної задачі доступні лише для перегляду')
    values=[str(payload.get(k) or "").strip() for k in ("decision_date","protocol_number","prozorro_url","document_url","officer_note")]
    if not values[0]: raise ValueError("Зазначте дату рішення")
    try: date.fromisoformat(values[0])
    except ValueError: raise ValueError('Зазначте коректну дату рішення')
    if not values[1]: raise ValueError("Зазначте № рішення / протоколу")
    try:
        url=urlsplit(values[2]); host=(url.hostname or '').lower()
        valid=url.scheme in ('http','https') and (host=='prozorro.gov.ua' or host.endswith('.prozorro.gov.ua')) and not any(x.isspace() for x in values[2]) and not url.username
    except ValueError: valid=False
    if not valid: raise ValueError("Зазначте валідне посилання на рішення в Prozorro")
    previous=con.execute('SELECT * FROM operational_task_blocking_decisions WHERE task_id=?',(task_id,)).fetchone()
    if previous and previous['used_for_blocking'] and all(previous[k]==v for k,v in zip(('decision_date','protocol_number','prozorro_url','document_url','officer_note'),values)):
        return current
    con.execute("""INSERT INTO operational_task_blocking_decisions(task_id,decision_date,protocol_number,prozorro_url,document_url,officer_note,attached_at,attached_by,used_for_blocking)
      VALUES(?,?,?,?,?,?,?,?,1) ON CONFLICT(task_id) DO UPDATE SET decision_date=excluded.decision_date,protocol_number=excluded.protocol_number,
      prozorro_url=excluded.prozorro_url,document_url=excluded.document_url,officer_note=excluded.officer_note,attached_at=excluded.attached_at,attached_by=excluded.attached_by,used_for_blocking=1""",
      (task_id,*values,now_iso(),actor))
    _event(con,task_id,"protocol_decision_attached",actor,metadata={"protocol_number":values[1],"decision_date":values[0]})
    return detail(con,task_id)


def complete_legacy_blocking(con,task_id,actor):
    current=detail(con,task_id); d=current.get("blocking_decision") or {}
    if current["task_type"]!="warning_block" or current["status"] in TERMINAL: raise ValueError("Задачу не можна завершити")
    if current.get("blocking_factual_state")!="blocked": raise ValueError("Фактичний стан блокування не підтверджено")
    if not d.get("decision_date") or not d.get("protocol_number") or not re.match(r"^https?://",d.get("prozorro_url") or "",re.I):
        raise ValueError("Заповніть дату, номер і валідне посилання на рішення")
    stamp=now_iso(); con.execute("UPDATE operational_tasks SET status='completed',resolution_code='legacy_blocking_confirmed',resolved_at=?,resolved_by=?,updated_at=?,version=version+1 WHERE id=?",(stamp,actor,stamp,task_id))
    _event(con,task_id,"legacy_blocking_confirmed",actor)
    return detail(con,task_id)


def warning_marker_map(con, today=None):
    today=today or date.today().isoformat()
    return {row["report_id"]:{"task_id":row["task_id"],"status":row["status"],"blocking_end_date":row["blocking_end_date"],
      "blocking_start_date":row["blocking_start_date"],"protocol_number":row["protocol_number"],"protocol_date":row["protocol_date"],"used_for_blocking":True,
      "highlighting_active":bool(row["blocking_start_date"] and row["blocking_end_date"] and row["blocking_start_date"]<=today<=row["blocking_end_date"])} for row in con.execute("""SELECT v.report_id,w.task_id,t.status,
      JSON_EXTRACT(t.source_context,'$.blocking_start_date') blocking_start_date,
      JSON_EXTRACT(t.source_context,'$.blocking_end_date') blocking_end_date,d.protocol_number,d.decision_date protocol_date
      FROM operational_task_warnings w JOIN violation_reports v ON v.id=w.violation_report_id
      JOIN operational_tasks t ON t.id=w.task_id JOIN operational_task_blocking_decisions d ON d.task_id=t.id
      WHERE d.used_for_blocking=1""")}
