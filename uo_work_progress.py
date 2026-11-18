"""Read-only review progress projections used by the УО work queue API."""

from __future__ import annotations

import supplier_classification
import supplier_manual_classification
from uo_work_queue import _officer_label


STATUS_SQL = "CASE WHEN q.id IS NULL OR q.status IS NULL THEN 'pending' ELSE q.status END"
PROTOCOL_OFFICER_SQL = "COALESCE(NULLIF(af.protocol_officer,''),NULLIF(fo.officer,''),'')"


def work_queue_application_statistics(con, clause: str, args: list, *, review_progress: bool,
                                     group_by: str = "review_officer",
                                     entity_type: str = "", filters: dict | None = None) -> list[dict]:
    if entity_type:
        if entity_type not in supplier_classification.ENTITY_TYPES:
            raise ValueError("Невідомий тип постачальника")
        supplier_manual_classification.register_effective_entity_type_sql(con)
        clause = f"({clause}) AND SUPPLIER_ENTITY_TYPE(s.supplier_code)=?"
        args = [*args, entity_type]
    source = f''' FROM submissions s JOIN frameworks f ON f.id=s.framework_id
        LEFT JOIN qualifications q ON q.id=s.qualification_id
        LEFT JOIN application_fields af ON af.submission_id=s.id
        LEFT JOIN framework_officers fo ON fo.framework_id=s.framework_id WHERE {clause}'''
    if review_progress:
        if group_by == "protocol_officer":
            group_expr = "COALESCE(NULLIF(af.protocol_officer,''),NULLIF(fo.officer,''),'Не призначено')"
            group_key = "protocol_officer"
        else:
            # Preserve the existing response field and default grouping.
            group_expr = "COALESCE(af.review_officer,'')"
            group_key = "review_officer"
        sql = f"""SELECT {group_expr} {group_key},
            COUNT(DISTINCT s.id) total,
            COUNT(DISTINCT CASE WHEN af.protocol_decision IN ('admit','reject') THEN s.id END) reviewed,
            COUNT(DISTINCT CASE WHEN COALESCE(af.protocol_decision,'')='' THEN s.id END) pending"""
        rows = [dict(row) for row in con.execute(sql + source + ' GROUP BY 1 ORDER BY 1', args)]
        if group_by != "protocol_officer":
            return rows
        # Protocol cards merge officer spelling/case variants; progress must
        # use the same normalized groups so each card represents the same cohort.
        merged = {}
        for row in rows:
            label = _officer_label(row[group_key])
            key = label.casefold()
            target = merged.setdefault(key, {group_key: label, "total": 0, "reviewed": 0, "pending": 0})
            for field in ("total", "reviewed", "pending"):
                target[field] += int(row[field] or 0)
        return sorted(merged.values(), key=lambda item: item[group_key].casefold())
    officers = f"COALESCE(af.review_officer,'') review_officer, {PROTOCOL_OFFICER_SQL} protocol_officer"
    status = STATUS_SQL
    where = []
    values = list(args)
    filters = filters or {}
    dimensions = {
        "category": "COALESCE(fo.category,'')",
        "review_officer": "COALESCE(af.review_officer,'')",
        "protocol_officer": "COALESCE(NULLIF(af.protocol_officer,''),NULLIF(fo.officer,''),'')",
    }
    for key, expression in dimensions.items():
        value = str(filters.get(key) or "").strip()
        if value:
            where.append(f"{expression}=?")
            values.append("" if value == "__unassigned__" else value)
    dk_codes = list(dict.fromkeys(str(value) for value in filters.get("dk_code", []) if str(value)))
    if dk_codes:
        where.append(f"COALESCE(f.dk_code,'') IN ({','.join('?' for _ in dk_codes)})")
        values.extend(dk_codes)
    filtered_source = source + (" AND " + " AND ".join(where) if where else "")
    sql = f"SELECT {officers}, COALESCE(f.dk_code,'') dk_code, COALESCE(fo.category,'') category, {status} status, COUNT(DISTINCT s.id) total"
    return [dict(row) for row in con.execute(sql + filtered_source + ' GROUP BY 1,2,3,4,5', values)]


def work_queue_statistics_payload(con, clause: str, args: list, *, entity_type: str = "",
                                  filters: dict | None = None) -> dict:
    """Return one filtered snapshot for the statistics cards, table and trend."""
    if entity_type:
        if entity_type not in supplier_classification.ENTITY_TYPES:
            raise ValueError("Невідомий тип постачальника")
        supplier_manual_classification.register_effective_entity_type_sql(con)
        clause = f"({clause}) AND SUPPLIER_ENTITY_TYPE(s.supplier_code)=?"
        args = [*args, entity_type]

    source = """ FROM submissions s JOIN frameworks f ON f.id=s.framework_id
        LEFT JOIN qualifications q ON q.id=s.qualification_id
        LEFT JOIN application_fields af ON af.submission_id=s.id
        LEFT JOIN framework_officers fo ON fo.framework_id=s.framework_id WHERE """ + clause
    status = STATUS_SQL
    dimensions = {
        "category": "COALESCE(fo.category,'')",
        "review_officer": "COALESCE(af.review_officer,'')",
        "protocol_officer": PROTOCOL_OFFICER_SQL,
    }

    # Filter options are computed from the same date/type cohort, before the
    # individual dimension filters, so choices do not disappear while editing.
    options = {}
    for key, expression in dimensions.items():
        options[key] = [row[0] or "" for row in con.execute(
            f"SELECT DISTINCT {expression} value" + source + f" GROUP BY {expression} ORDER BY value", args)]
    options["dk_code"] = [row[0] or "" for row in con.execute(
        "SELECT DISTINCT COALESCE(f.dk_code,'') value" + source + " GROUP BY value ORDER BY value", args)]

    filters = filters or {}
    where, values = [], list(args)
    for key, expression in dimensions.items():
        value = str(filters.get(key) or "").strip()
        if value:
            where.append(f"{expression}=?")
            values.append("" if value == "__unassigned__" else value)
    dk_codes = list(dict.fromkeys(str(value) for value in filters.get("dk_code", []) if str(value)))
    if dk_codes:
        where.append(f"COALESCE(f.dk_code,'') IN ({','.join('?' for _ in dk_codes)})")
        values.extend(dk_codes)
    filtered_source = source + (" AND " + " AND ".join(where) if where else "")

    officers = f"COALESCE(af.review_officer,'') review_officer, {PROTOCOL_OFFICER_SQL} protocol_officer"
    sql = f"SELECT {officers}, COALESCE(f.dk_code,'') dk_code, COALESCE(fo.category,'') category, {status} status, COUNT(DISTINCT s.id) total"
    items = [dict(row) for row in con.execute(sql + filtered_source + ' GROUP BY 1,2,3,4,5 ORDER BY 1,2,3,4', values)]

    trend_sql = f"""SELECT SUBSTR(s.date_published,1,10) date,
        COUNT(DISTINCT s.id) submitted,
        COUNT(DISTINCT CASE WHEN {status}='active' THEN s.id END) active,
        COUNT(DISTINCT CASE WHEN {status}='unsuccessful' THEN s.id END) unsuccessful,
        COUNT(DISTINCT CASE WHEN {status}='pending' THEN s.id END) pending,
        COUNT(DISTINCT CASE WHEN q.id IS NOT NULL AND q.status IS NULL THEN s.id END) null_status,
        COUNT(DISTINCT CASE WHEN q.id IS NULL THEN s.id END) missing_qualification,
        COUNT(DISTINCT CASE WHEN q.id IS NOT NULL AND q.status='' THEN s.id END) empty_status,
        COUNT(DISTINCT CASE WHEN q.id IS NOT NULL AND q.status IS NOT NULL AND q.status<>''
          AND q.status NOT IN ('active','unsuccessful','pending') THEN s.id END) unknown_status
        """ + filtered_source + " GROUP BY SUBSTR(s.date_published,1,10) ORDER BY date"
    trend = [dict(row) for row in con.execute(trend_sql, values)]

    status_totals = {key: 0 for key in ("active", "unsuccessful", "pending")}
    totals = 0
    empty_status = 0
    unknown_status = 0
    unknown_values = {}
    for item in items:
        count = int(item["total"] or 0)
        totals += count
        if item["status"] in status_totals:
            status_totals[item["status"]] += count
        elif item["status"] == "":
            empty_status += count
        elif item["status"] is not None:
            unknown_status += count
            unknown_values[item["status"]] = unknown_values.get(item["status"], 0) + count
    diagnostics = {
        "empty_status": empty_status,
        "unknown_status": unknown_status,
        "unknown_values": [{"status": key, "total": value} for key, value in sorted(unknown_values.items())],
        "null_status": sum(int(row["null_status"] or 0) for row in trend),
        "missing_qualification": sum(int(row["missing_qualification"] or 0) for row in trend),
    }
    return {
        "items": items,
        "totals": {"total": totals, **status_totals},
        "trend": trend,
        "diagnostics": diagnostics,
        "filter_options": options,
    }
