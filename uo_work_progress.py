"""Read-only review progress projections used by the УО work queue API."""

from __future__ import annotations

from uo_work_queue import _officer_label


def work_queue_application_statistics(con, clause: str, args: list, *, review_progress: bool,
                                     group_by: str = "review_officer") -> list[dict]:
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
    officers = "COALESCE(af.review_officer,'') review_officer, COALESCE(NULLIF(af.protocol_officer,''),NULLIF(fo.officer,''),'') protocol_officer"
    sql = f"SELECT {officers}, COALESCE(f.dk_code,'') dk_code, COALESCE(fo.category,'') category, q.status, COUNT(DISTINCT s.id) total"
    return [dict(row) for row in con.execute(sql + source + ' GROUP BY 1,2,3,4,5', args)]
