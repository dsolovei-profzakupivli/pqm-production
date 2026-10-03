"""Shared, read-only supplier EDR business-state projection.

The environment policy changes officer availability, never event chronology.
This module deliberately does not migrate or write any persisted state.
"""

from __future__ import annotations

from datetime import date, datetime
import json
import re

import edr_sync_v2


def _day(value):
    text = str(value or "").strip()
    if not text:
        return ""
    if re.match(r"^\d{4}-\d{2}-\d{2}", text):
        return text[:10]
    match = re.match(r"^(\d{2})\.(\d{2})\.(\d{4})$", text)
    return f"{match[3]}-{match[2]}-{match[1]}" if match else ""


def _moment(value):
    text = str(value or "").strip()
    if not text or len(text) <= 10:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed
    except ValueError:
        return None


def _provenance(value=None, source_type=None, source_id=None, submission_id=None,
                qualification_id=None, event_date=None, event_datetime=None,
                confirmed=False, ambiguous=False, officer=None, officer_availability=None):
    result = {
        "value": value, "source_type": source_type, "source_id": source_id,
        "source_submission_id": submission_id,
        "source_qualification_id": qualification_id,
        "event_date": event_date, "event_datetime": event_datetime,
        "datetime_precision": "datetime" if event_datetime else "date" if event_date else None,
        "officer": officer, "confirmed": bool(confirmed), "ambiguous": bool(ambiguous),
    }
    if officer_availability is not None:
        result["officer_availability"] = officer_availability
    return result


def _equivalent(left, right):
    """A blank E in a Clarity cycle preserves the previous factual E."""
    if left.get("officer") and right.get("officer") and left["officer"] != right["officer"]:
        return False
    if left.get("edr_status") and right.get("edr_status") and left["edr_status"] != right["edr_status"]:
        return False
    return True


def _compare_events(left, right):
    if left["event_date"] != right["event_date"]:
        return 1 if left["event_date"] > right["event_date"] else -1
    first, second = _moment(left.get("event_datetime")), _moment(right.get("event_datetime"))
    if first and second and (first.tzinfo is None) == (second.tzinfo is None):
        return (first > second) - (first < second)
    if left["source_id"] == right["source_id"]:
        return 0
    if _equivalent(left, right):
        return 0
    return None


def _latest_event(events):
    if not events:
        return None, False
    latest_day = max(event["event_date"] for event in events)
    peers = [event for event in events if event["event_date"] == latest_day]
    if len(peers) == 1:
        return peers[0], False
    # A DATE-only business event cannot be ordered against a timestamped
    # event merely because its row was imported later.  Consider every peer,
    # not just the last comparison in the input sequence.
    equivalent = all(_equivalent(left, right)
                     for index, left in enumerate(peers) for right in peers[index + 1:])
    if equivalent:
        return min(peers, key=lambda event: (event["source_type"], event["source_id"])), False
    moments = [_moment(event.get("event_datetime")) for event in peers]
    if (all(moments) and len({moment.tzinfo is None for moment in moments}) == 1):
        newest = max(moments)
        winners = [event for event, moment in zip(peers, moments) if moment == newest]
        if len(winners) == 1 or all(_equivalent(left, right)
            for index, left in enumerate(winners) for right in winners[index + 1:]):
            return min(winners, key=lambda event: (event["source_type"], event["source_id"])), False
    return min(peers, key=lambda event: (event["source_type"], event["source_id"])), True


def project_supplier_facts(facts, officer_required=True, today=None):
    """Resolve one supplier from attested facts without mutating them.

    `facts` is the I/O boundary: submissions, qualifications, profile and ledger
    are already associated by literal supplier identity.  A derived admission
    profile is evidence of its qualification, not a second verification event.
    """
    code = str(facts["supplier_code"])
    status = facts.get("prozorro_status") or "Ще не в реєстрі"
    applications = sorted(facts.get("submissions") or [],
                          key=lambda row: (str(row.get("date_published") or ""), str(row.get("id") or "")))
    latest = applications[-1] if applications else {}
    conflicts = []
    events = []
    for row in facts.get("qualifications") or []:
        if row.get("status") != "active":
            continue
        checked = _day(row.get("decision_date"))
        protocol_day = _day(row.get("protocol_date"))
        if not checked or checked != protocol_day or not row.get("id") or not row.get("submission_id"):
            conflicts.append("qualification_event_provenance_incomplete")
            continue
        officer = str(row.get("protocol_officer") or "").strip() or None
        if officer == "НЕ ВИЗНАЧЕНО":
            officer = None
        if officer_required and not officer:
            conflicts.append("qualification_officer_missing_required")
            continue
        events.append({"source_type": "qualification_verification",
                       "source_id": "qualification:" + str(row["id"]),
                       "source_submission_id": str(row["submission_id"]),
                       "source_qualification_id": str(row["id"]),
                       "event_date": checked,
                       "event_datetime": str(row["decision_date"]) if _moment(row.get("decision_date")) else None,
                       "officer": officer, "edr_status": "Зареєстровано", "confirmed": True})
    for row in facts.get("verification_events") or []:
        kind = row.get("event_type")
        # Admission ledger/profile records are materializations of the qualification.
        if kind not in {"google_clarity", "manual_edr", "legacy_google_registry", "clarity_cycle"}:
            continue
        checked = _day(row.get("occurred_at"))
        if not checked:
            conflicts.append("verification_event_date_missing")
            continue
        snapshot = row.get("snapshot") or {}
        if isinstance(snapshot, str):
            try:
                snapshot = json.loads(snapshot)
            except ValueError:
                conflicts.append("verification_snapshot_invalid")
                continue
        officer = str(row.get("officer") or "").strip() or None
        if officer == "НЕ ВИЗНАЧЕНО":
            officer = None
        if officer_required and not officer:
            conflicts.append("verification_officer_missing_required")
            continue
        raw_edr = snapshot.get("edr_status")
        events.append({"source_type": "google_manual_verification" if kind == "manual_edr"
                       else "clarity_cycle" if kind in {"google_clarity", "clarity_cycle"}
                       else "legacy_google_verification",
                       "source_id": "verification:" + str(row.get("id") or row.get("source_id") or ""),
                       "source_submission_id": None, "source_qualification_id": None,
                       "event_date": checked,
                       "event_datetime": str(row["occurred_at"]) if _moment(row.get("occurred_at")) else None,
                       "officer": officer,
                       "edr_status": edr_sync_v2.compatible_edr_status(raw_edr) if raw_edr else None,
                       "confirmed": True,
                       "manager_confirmed": snapshot.get("manager_name") if kind == "manual_edr" else None})
    selected, ambiguous = _latest_event(events)
    if ambiguous:
        conflicts.append("same_day_verification_order_ambiguous")
    verification_date = selected["event_date"] if selected and not ambiguous else None
    verification_officer = selected["officer"] if selected and not ambiguous else None
    status_events = [event for event in events if event.get("edr_status")]
    latest_status, status_ambiguous = _latest_event(status_events)
    if status_ambiguous:
        conflicts.append("same_day_edr_status_order_ambiguous")
    edr_status = latest_status["edr_status"] if latest_status and not status_ambiguous else None

    profile = facts.get("profile") or {}
    profile_manager = str(profile.get("manager_name") or "").strip() or None
    application_manager = str(latest.get("application_manager_name") or "").strip() or None
    application_manager_source = str(latest.get("manager_name_source") or "").strip()
    manager_submission = latest
    if application_manager_source == "previous_application":
        manager_submission = next((row for row in applications
            if str(row.get("id")) == str(latest.get("manager_name_source_submission_id"))), {})
    application_manager_confirmed = bool(application_manager and (
        application_manager_source == "manual" or
        application_manager_source == "previous_application" and manager_submission))
    manager = profile_manager or application_manager
    manager_source = "legacy_google_manager" if profile_manager else "application_manager" if application_manager else None
    manager_source_id = ("profile:" + code if profile_manager else str(manager_submission.get("id"))) if manager_source else None
    app_moment = _moment(manager_submission.get("date_published"))
    selected_moment = _moment(selected.get("event_datetime")) if selected else None
    if application_manager and latest.get("id") and application_manager != manager:
        application_day = _day(manager_submission.get("date_published"))
        if selected and (application_day > selected["event_date"] or
                         application_day == selected["event_date"] and selected_moment and app_moment and
                         app_moment > selected_moment):
            manager, manager_source, manager_source_id = application_manager, "application_manager", str(manager_submission["id"])
        elif selected and application_day == selected["event_date"] and not (selected_moment and app_moment):
            conflicts.append("same_day_manager_order_ambiguous")
    if not profile_manager and application_manager:
        manager, manager_source, manager_source_id = application_manager, "application_manager", str(manager_submission.get("id"))

    def event_provenance(value, event, source_type=None):
        if not event or ambiguous:
            return _provenance(value, ambiguous=ambiguous)
        return _provenance(value, source_type or event["source_type"], event["source_id"],
                           event.get("source_submission_id"), event.get("source_qualification_id"),
                           event["event_date"], event.get("event_datetime"), event.get("confirmed"),
                           ambiguous, event.get("officer"))

    i_provenance = event_provenance(verification_date, selected)
    l_provenance = event_provenance(verification_officer, selected)
    l_provenance["officer_availability"] = ("available" if verification_officer else
        "missing_required" if officer_required else "unavailable_in_sandbox")
    manager_provenance = _provenance(manager, manager_source, manager_source_id,
        str(manager_submission.get("id")) if manager_source == "application_manager" else None,
        event_date=_day(manager_submission.get("date_published")) if manager_source == "application_manager" else _day(profile.get("edr_checked_at")),
        event_datetime=str(manager_submission.get("date_published")) if manager_source == "application_manager" and app_moment else None,
        confirmed=manager_source == "legacy_google_manager" and bool(profile.get("source_sheet")) or
            manager_source == "application_manager" and application_manager_confirmed,
        ambiguous="same_day_manager_order_ambiguous" in conflicts)
    h_date = _day(latest.get("date_published"))
    freshness = edr_sync_v2.freshness_state(status, verification_date or "", today or date.today())["marker"]
    return {"supplier_code": code, "supplier_name": str(profile.get("full_name") or "") or None,
            "latest_submission_name": str(latest.get("supplier_name") or "") or None,
            "working_supplier_name": facts.get("working_supplier_name"),
            "working_name_update_confirmed": bool(facts.get("working_name_update_confirmed")),
            "entity_type": facts.get("entity_type") or "unknown",
            "google_sync_eligible": bool(facts.get("google_sync_eligible")),
            "manager_for_verification": manager, "edr_status": edr_status,
            "prozorro_status": status, "last_application_date": h_date or None,
            "verification_date": verification_date, "verification_officer": verification_officer,
            "freshness_marker": freshness,
            "provenance": {"D": manager_provenance,
                "E": event_provenance(edr_status, latest_status),
                "I": i_provenance, "L": l_provenance,
                "H": _provenance(h_date or None, "latest_submission" if latest else None,
                    str(latest.get("id")) if latest else None, str(latest.get("id")) if latest else None,
                    event_date=h_date or None, event_datetime=str(latest.get("date_published")) if app_moment else None,
                    confirmed=bool(h_date))},
            "conflicts": sorted(set(conflicts))}


def resolve_supplier_edr_business_state(con, supplier_codes, environment_policy="prod",
                                        status_by_code=None, entity_by_code=None, today=None):
    """Read current PQM facts once and project the same state for UI and API.

    Raw supplier identifiers are never rewritten.  Outer whitespace is used
    only as a comparison key; collisions fail closed for the affected supplier.
    """
    if environment_policy not in {"prod", "sandbox"}:
        raise ValueError("Unknown officer environment policy")
    literal_requested = {str(code) for code in supplier_codes if str(code or "").strip()}
    requested = {code.strip() for code in literal_requested}
    facts = {code: {"supplier_code": code, "submissions": [], "qualifications": [],
                    "verification_events": []} for code in requested}
    raw_variants = {code: set() for code in requested}
    application_columns = edr_sync_v2._columns(con, "application_fields") if edr_sync_v2._table_exists(con, "application_fields") else set()
    manager_expr = "af.manager_name" if "manager_name" in application_columns else "''"
    source_expr = "af.manager_name_source" if "manager_name_source" in application_columns else "''"
    source_submission_expr = ("af.manager_name_source_submission_id"
        if "manager_name_source_submission_id" in application_columns else "''")
    application_join = "LEFT JOIN application_fields af ON af.submission_id=s.id" if application_columns else ""
    if requested and edr_sync_v2._table_exists(con, "submissions"):
        for row in con.execute(f"""SELECT s.id,s.supplier_code,s.supplier_name,s.date_published,
          {manager_expr} application_manager_name,{source_expr} manager_name_source,
          {source_submission_expr} manager_name_source_submission_id
          FROM submissions s {application_join}"""):
            code = str(row["supplier_code"] or "").strip()
            if code in requested:
                raw_variants[code].add(str(row["supplier_code"]))
                facts[code]["submissions"].append(dict(row))
    if requested and edr_sync_v2._table_exists(con, "qualifications"):
        protocol_date = "af.protocol_date" if "protocol_date" in application_columns else "''"
        protocol_officer = "af.protocol_officer" if "protocol_officer" in application_columns else "''"
        for row in con.execute(f"""SELECT s.supplier_code,s.id submission_id,q.id,q.status,
          q.decision_date,{protocol_date} protocol_date,{protocol_officer} protocol_officer
          FROM submissions s JOIN qualifications q ON q.id=s.qualification_id
          {application_join}
          WHERE q.status='active'"""):
            code = str(row["supplier_code"] or "").strip()
            if code in requested:
                raw_variants[code].add(str(row["supplier_code"]))
                facts[code]["qualifications"].append(dict(row))
    if requested and edr_sync_v2._table_exists(con, "supplier_edr_profiles"):
        profile_columns = edr_sync_v2._columns(con, "supplier_edr_profiles")
        selected = [column for column in ("supplier_code", "full_name", "manager_name", "edr_status",
                    "edr_checked_at", "edr_officer", "source_sheet", "source_row") if column in profile_columns]
        for row in con.execute("SELECT " + ",".join(selected) + " FROM supplier_edr_profiles"):
            code = str(row["supplier_code"] or "").strip()
            if code in requested:
                raw_variants[code].add(str(row["supplier_code"]))
                profile = dict(row)
                facts[code]["profile"] = profile
                if profile.get("source_sheet") and _day(profile.get("edr_checked_at")):
                    facts[code]["verification_events"].append({
                        "event_type": "legacy_google_registry", "source_id": "profile:" + code,
                        "occurred_at": profile["edr_checked_at"], "officer": profile.get("edr_officer"),
                        "snapshot": {"edr_status": profile.get("edr_status")}})
    if requested and edr_sync_v2._table_exists(con, "supplier_edr_verification_events"):
        event_columns = edr_sync_v2._columns(con, "supplier_edr_verification_events")
        event_fields = [field if field in event_columns else f"NULL AS {field}" for field in
                        ("id", "supplier_code", "event_type", "occurred_at", "officer",
                         "source_submission_id", "source_sheet", "source_row", "snapshot_json")]
        for row in con.execute("SELECT " + ",".join(event_fields) + " FROM supplier_edr_verification_events"):
            code = str(row["supplier_code"] or "").strip()
            if code in requested:
                raw_variants[code].add(str(row["supplier_code"]))
                facts[code]["verification_events"].append({**dict(row), "snapshot": row["snapshot_json"]})
    if edr_sync_v2._table_exists(con, "supplier_working_names"):
        for row in con.execute("SELECT supplier_code,working_name,source_type,source_id,event_date FROM supplier_working_names"):
            code = str(row["supplier_code"] or "").strip()
            if code in requested:
                facts[code]["working_supplier_name"] = str(row["working_name"] or "") or None
                facts[code]["working_name_update_confirmed"] = (
                    row["source_type"] == "google_verified_name" and bool(row["source_id"]))
    statuses = status_by_code if status_by_code is not None else edr_sync_v2.canonical_prozorro_statuses(con, requested)
    normalized_statuses = {}
    for raw_code, status in statuses.items():
        code = str(raw_code).strip()
        if code in requested:
            if code in normalized_statuses and normalized_statuses[code] != status:
                raise ValueError("Conflicting supplier statuses for one outer-whitespace identity")
            normalized_statuses[code] = status
    eligible = {str(code).strip() for code in edr_sync_v2.monitoring_population_codes(con)}
    result = {}
    for code, item in facts.items():
        item["prozorro_status"] = normalized_statuses.get(code, "Ще не в реєстрі")
        item["google_sync_eligible"] = code in eligible
        item["entity_type"] = (entity_by_code or {}).get(code, "unknown")
        projected = project_supplier_facts(item, officer_required=environment_policy == "prod", today=today)
        if len(raw_variants[code]) > 1:
            projected["conflicts"] = sorted(set(projected["conflicts"] + ["outer_whitespace_identity_collision"]))
        result[code] = projected
    # Callers index by the literal population identifier.  Outer whitespace is
    # only a comparison key, so expose every requested literal without losing
    # the collision guard or rewriting the supplier code in its projection.
    for literal in literal_requested:
        code = literal.strip()
        if literal != code:
            result[literal] = {**result[code], "supplier_code": literal}
    return result
