"""Canonical supplier identity values used by document contexts."""
import re


def _digits(value):
    return re.sub(r"\D", "", str(value or ""))


def _normalized_person(value):
    return " ".join(re.sub(r"[’'`\-]+", " ", str(value or "").casefold()).split())


def current_manager_rnokpp(con, supplier_code, manager):
    """Resolve a current person's RNOKPP from identity-proven canonical data.

    A saved manager-level value has priority. A ten-digit supplier identifier is
    usable only when the EDR profile explicitly identifies the supplier as FOP
    and its person is the same current manager. Nothing is persisted here.
    """
    code = _digits(supplier_code)
    manager_id = (manager or {}).get("id")
    manager_name = str((manager or {}).get("manager_name") or "")
    if not code or manager_id is None or not manager_name:
        return {"value": "", "source": "", "identity_confirmed": False}
    row = con.execute(
        """SELECT id,manager_name,manager_tax_id,manager_tax_id_source
           FROM supplier_managers
           WHERE id=? AND DIGITS(supplier_code)=? AND is_current=1""",
        (manager_id, code),
    ).fetchone()
    if not row or _normalized_person(row["manager_name"]) != _normalized_person(manager_name):
        return {"value": "", "source": "", "identity_confirmed": False}
    saved = _digits(row["manager_tax_id"])
    if saved:
        if len(saved) != 10:
            return {"value": "", "source": "invalid_manager_value", "identity_confirmed": True}
        return {
            "value": saved,
            "source": row["manager_tax_id_source"] or "supplier_managers.manager_tax_id",
            "identity_confirmed": True,
        }
    if len(code) != 10:
        return {"value": "", "source": "", "identity_confirmed": True}
    columns = {item[1] for item in con.execute("PRAGMA table_info(supplier_edr_profiles)")}
    if not {"supplier_code", "manager_name", "source_sheet"} <= columns:
        return {"value": "", "source": "", "identity_confirmed": True}
    edr = con.execute(
        """SELECT manager_name,source_sheet FROM supplier_edr_profiles
           WHERE DIGITS(supplier_code)=?""",
        (code,),
    ).fetchone()
    if not edr or str(edr["source_sheet"] or "").strip().casefold() != "фоп":
        return {"value": "", "source": "", "identity_confirmed": True}
    if _normalized_person(edr["manager_name"]) != _normalized_person(row["manager_name"]):
        return {"value": "", "source": "", "identity_confirmed": False}
    return {
        "value": code,
        "source": "supplier_edr_profiles.fop_identifier",
        "identity_confirmed": True,
    }


def document_name(con, supplier_code):
    """Current EDR full name, otherwise the latest submission name.

    The materialized supplier registry summary is deliberately not a source:
    its supplier name is an aggregate display value rather than current
    document identity data.
    """
    code = re.sub(r"\D", "", str(supplier_code or ""))
    row = con.execute("""SELECT NULLIF(TRIM(full_name),'')
      FROM supplier_edr_profiles WHERE DIGITS(supplier_code)=?""", (code,)).fetchone()
    if row and row[0]:
        return row[0]
    row = con.execute("""SELECT NULLIF(TRIM(supplier_name),'')
      FROM submissions
      WHERE DIGITS(supplier_code)=? AND TRIM(COALESCE(supplier_name,''))<>''
           ORDER BY CASE WHEN julianday(NULLIF(date_published,'')) IS NULL THEN 1 ELSE 0 END,
               julianday(NULLIF(date_published,'')) DESC,id DESC LIMIT 1""", (code,)).fetchone()
    return row[0] if row and row[0] else None


def document_short_name(con, supplier_code):
    """Current EDR short name; canonical document name is the sole fallback."""
    code = re.sub(r"\D", "", str(supplier_code or ""))
    row = con.execute("""SELECT NULLIF(TRIM(short_name),'')
      FROM supplier_edr_profiles WHERE DIGITS(supplier_code)=?""", (code,)).fetchone()
    return row[0] if row and row[0] else document_name(con, code)
