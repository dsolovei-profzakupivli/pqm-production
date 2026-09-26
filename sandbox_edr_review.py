"""Complete, read-only operator review for the narrow SANDBOX EDR flow."""
from __future__ import annotations

import edr_sync_v2


FIELD_GROUPS = {
    "edr_status": "edr_status", "edr_checked_at": "verification",
    "edr_officer": "verification", "full_name": "names_manager",
    "short_name": "names_manager", "manager_name": "names_manager",
    "current_supplier_name": "names_manager",
    "termination_decision_details": "gjkm", "termination_record_date": "gjkm",
    "termination_record_number": "gjkm", "edr_notes": "gjkm",
}
MIRROR_FIELDS = {"termination_decision_details", "termination_record_date",
                 "termination_record_number", "edr_notes"}


def details(preview: dict) -> list[dict]:
    """Every changed field, with the exact Apply field decision; never truncate."""
    result = []
    for plan in preview["items"]:
        incoming = plan["incoming"]
        old = plan["current_profile"]
        effective = edr_sync_v2.effective_profile_fields(plan, old)
        base = {"supplier_code": plan["supplier_code"],
                "supplier_name": incoming["full_name"] or old.get("full_name", ""),
                "source_sheet": plan["source_sheet"], "source_row": plan["source_row"]}
        if plan["verification_event_change"] and plan["verification_decision"] in {
                "newer_verification_accepted", "initial_verification_accepted",
                "same_date_officer_update_accepted"}:
            result.append({**base, "field": "verification_pair", "category": "verification",
                "current_pqm_value": {"date": plan["current_verification_date"],
                                      "officer": plan["current_verification_officer"]},
                "google_value": {"date": incoming["edr_checked_at"], "officer": incoming["edr_officer"]},
                "planned_pqm_value": {"date": incoming["edr_checked_at"], "officer": incoming["edr_officer"]},
                "action": "accept_google_pair", "reason": plan["verification_decision"]})
        for field in plan["changed_fields"]:
            if field in {"edr_checked_at", "edr_officer"}:
                continue  # I/L is presented only as one indivisible pair.
            current = (plan["current_manager_name"] if field == "manager_name"
                       else old.get(field, ""))
            google = incoming.get(field, "")
            planned = effective.get(field, "") if plan["apply_allowed"] else current
            action = ("skipped_ineligible" if not plan["apply_allowed"] else
                      "clear" if field in MIRROR_FIELDS and not google else "update")
            reason = ("google_owned_full_mirror" if field in MIRROR_FIELDS else
                      "fresh_google_evidence")
            result.append({**base, "field": field, "category": FIELD_GROUPS.get(field, "other"),
                "current_pqm_value": current or "", "google_value": google or "",
                "planned_pqm_value": planned or "", "action": action, "reason": reason})
        if plan["current_supplier_name"] != plan["planned_supplier_name"]:
            result.append({**base, "field": "current_supplier_name", "category": "names_manager",
                "current_pqm_value": plan["current_supplier_name"],
                "google_value": incoming["full_name"],
                "planned_pqm_value": (plan["planned_supplier_name"] if plan["apply_allowed"] else plan["current_supplier_name"]),
                "action": "update" if plan["apply_allowed"] else "skipped_ineligible",
                "reason": "name_projection"})
        if plan["conflicts"]:
            result.append({**base, "field": "conflict", "category": "conflicts",
                "current_pqm_value": "", "google_value": "", "planned_pqm_value": "",
                "action": "blocked", "reason": plan["conflicts"]})
    return result


def summary_additions(preview: dict, rows: list[dict]) -> dict:
    changed = {item["supplier_code"] for item in preview["items"]
               if item["apply_allowed"] and (item["changed_fields"] or item["verification_event_change"])}
    blocked = {item["supplier_code"] for item in preview["items"] if item["conflicts"]}
    notes = [row for row in rows if row["field"] == "edr_notes"]
    return {"changed_suppliers": len(changed),
            "no_op_suppliers": sum(1 for item in preview["items"]
                                   if item["apply_allowed"] and not item["changed_fields"]
                                   and not item["verification_event_change"] and not item["conflicts"]),
            "blocked_suppliers": len(blocked),
            "malformed_blocked": sum(1 for item in preview["items"]
                                     if any(reason.startswith("malformed_") for reason in item["conflicts"])),
            "m_note_updates": sum(row["action"] == "update" for row in notes),
            "m_note_clears": sum(row["action"] == "clear" for row in notes)}
