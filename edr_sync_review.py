"""Complete read-only operator review for permanent Google → PQM EDR sync."""
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
    """Every changed field, with exactly the same field decision as Apply."""
    result = []
    for plan in preview["items"]:
        incoming = plan["incoming"]
        old = plan["current_profile"]
        effective = edr_sync_v2.effective_profile_fields(plan, old)
        base = {"supplier_code": plan["supplier_code"],
                "supplier_name": incoming["full_name"] or old.get("full_name", ""),
                "source_sheet": plan["source_sheet"], "source_row": plan["source_row"],
                "row_state": plan.get("row_state", "eligible")}
        if plan.get("row_state") == "skipped":
            result.append({**base, "field": "row", "category": "skipped",
                "current_pqm_value": "", "google_value": incoming.get("edr_checked_at_source") or "",
                "planned_pqm_value": "", "action": "skip",
                "reason": plan.get("skip_reasons", []) or [plan.get("datetime_gate", {}).get("reason", "unverified_timestamp")]})
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
                continue
            current = (plan["current_manager_name"] if field == "manager_name"
                       else old.get(field, ""))
            google = incoming.get(field, "")
            planned = (current if plan["conflicts"] else
                       effective.get(field, "") if plan["apply_allowed"] else current)
            action = ("skipped_conflict" if plan["conflicts"] else
                      "skipped_ineligible" if not plan["apply_allowed"] else
                      "clear" if field in MIRROR_FIELDS and not google else "update")
            reason = ("google_owned_full_mirror" if field in MIRROR_FIELDS else
                      "fresh_google_evidence")
            result.append({**base, "field": field, "category": FIELD_GROUPS.get(field, "other"),
                "current_pqm_value": current or "", "google_value": google or "",
                "planned_pqm_value": planned or "", "action": action, "reason": reason})
        for change in plan.get("mirror_field_changes", []):
            if change.get("action") not in {"blocked", "skipped"}:
                continue
            field = change["field"]
            result.append({**base, "field": field, "category": "gjkm",
                "current_pqm_value": change.get("current", ""),
                "google_value": change.get("google", ""),
                "planned_pqm_value": change.get("planned", ""),
                "action": change["action"], "reason": change.get("reason", "")})
        if plan["current_supplier_name"] != plan["planned_supplier_name"]:
            result.append({**base, "field": "current_supplier_name", "category": "names_manager",
                "current_pqm_value": plan["current_supplier_name"],
                "google_value": incoming["full_name"],
                "planned_pqm_value": (plan["current_supplier_name"] if plan["conflicts"] or not plan["apply_allowed"] else plan["planned_supplier_name"]),
                "action": "skipped_conflict" if plan["conflicts"] else "update" if plan["apply_allowed"] else "skipped_ineligible",
                "reason": "name_projection"})
        if plan["conflicts"]:
            result.append({**base, "field": "conflict", "category": "conflicts",
                "current_pqm_value": "", "google_value": "", "planned_pqm_value": "",
                "action": "blocked", "reason": plan["conflicts"],
                "reason_label": [edr_sync_v2.conflict_reason_details(code)[0]
                                 for code in plan["conflicts"]]})
    return result


def summary_additions(preview: dict, rows: list[dict]) -> dict:
    changed = {item["supplier_code"] for item in preview["items"]
               if item["row_state"] == "eligible" and item["apply_allowed"]
               and item.get("apply_changes_expected")}
    blocked = {item["supplier_code"] for item in preview["items"] if item["conflicts"]}
    ready = [item for item in preview["items"]
             if item["row_state"] == "eligible" and item["apply_allowed"]]
    notes = [row for row in rows if row["field"] == "edr_notes"]
    return {"changed_suppliers": len(changed),
            "no_op_suppliers": len({item["supplier_code"] for item in ready
                                     if not item.get("apply_changes_expected")}),
            "ready_to_apply": len(ready),
            "ready_with_changes": sum(bool(item.get("apply_changes_expected")) for item in ready),
            "ready_unchanged": sum(not item.get("apply_changes_expected") for item in ready),
            "partial_apply_enabled": False,
            "blocked_suppliers": len(blocked),
            "eligible": int(preview["summary"].get("eligible", 0)),
            "skipped": int(preview["summary"].get("skipped", 0)),
            "conflict": int(preview["summary"].get("conflict", len(blocked))),
            "skipped_unverified_timestamp": int(preview["summary"].get("skipped_unverified_timestamp", 0)),
            "skipped_ineligible": int(preview["summary"].get("skipped_ineligible", 0)),
            "malformed_blocked": sum(1 for item in preview["items"]
                                     if any(reason.startswith("malformed_") for reason in item["conflicts"])),
            "m_note_updates": sum(row["action"] == "update" for row in notes),
            "m_note_clears": sum(row["action"] == "clear" for row in notes)}
