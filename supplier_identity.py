"""Canonical supplier identity values used by document contexts."""
import re


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
