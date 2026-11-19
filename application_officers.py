"""Shared read-only projections for protocol and review officer assignments."""

from __future__ import annotations


UNDEFINED_OFFICER = "Не визначено"


def _literal(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def protocol_officer_sql(*, submission_alias: str = "s", qualification_alias: str = "q",
                         application_alias: str = "af",
                         undefined: str = UNDEFINED_OFFICER) -> str:
    """Return the agreed effective protocol officer without changing stored data.

    The service directory is authoritative for the current framework default.
    A stored application value always wins. Only pending applications may use
    the current framework default when the stored value is empty.
    """
    fallback = _literal(undefined)
    status = f"COALESCE({qualification_alias}.status,'pending')"
    stored = f"NULLIF(TRIM({application_alias}.protocol_officer),'')"
    assigned = (
        "(SELECT NULLIF(TRIM(fsd.responsible_officer),'') "
        "FROM framework_service_directory fsd "
        f"WHERE fsd.framework_id={submission_alias}.framework_id "
        "ORDER BY CASE WHEN fsd.source='PQM' THEN 0 ELSE 1 END, "
        "fsd.synced_at DESC, fsd.pretty_id LIMIT 1)"
    )
    return (
        f"CASE WHEN {status}='pending' THEN COALESCE({stored},{assigned},{fallback}) "
        f"WHEN {status} IN ('active','unsuccessful') THEN COALESCE({stored},{fallback}) "
        f"ELSE {fallback} END"
    )


def review_officer_sql(*, application_alias: str = "af",
                       undefined: str = UNDEFINED_OFFICER) -> str:
    """Return the independent review/audit officer, never protocol assignment."""
    return f"COALESCE(NULLIF(TRIM({application_alias}.review_officer),''),{_literal(undefined)})"


PROTOCOL_OFFICER_SQL = protocol_officer_sql()
REVIEW_OFFICER_SQL = review_officer_sql()


def assigned_officer(con, framework_id: str) -> str:
    """Read the current assigned officer from the authoritative service directory."""
    row = con.execute(
        """SELECT NULLIF(TRIM(responsible_officer),'') FROM framework_service_directory
           WHERE framework_id=? ORDER BY CASE WHEN source='PQM' THEN 0 ELSE 1 END,
             synced_at DESC,pretty_id LIMIT 1""",
        (framework_id,),
    ).fetchone()
    return str(row[0] or "") if row else ""


def assign_default_protocol_officer(con, submission_id: str, framework_id: str,
                                    changed_at: str, changed_by: str = "PQM default from framework") -> bool:
    """Fill a blank application field once; any stored/manual value is immutable here."""
    value = assigned_officer(con, framework_id)
    if not value:
        return False
    cursor = con.execute(
        """UPDATE application_fields SET protocol_officer=?,updated_at=?,updated_by=?
           WHERE submission_id=? AND TRIM(COALESCE(protocol_officer,''))=''""",
        (value, changed_at, changed_by, submission_id),
    )
    return bool(cursor.rowcount)
