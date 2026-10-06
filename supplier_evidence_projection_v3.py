"""Supplier-scoped, read-only contract-v3 adapter; not wired to runtime readers.

No DDL, DML, commits, clock, cache writes, network or population rebuild. The
caller supplies a consistent read snapshot and an explicit zoned assessment time.
The read gate is independent of the recording gate and fails closed outside the
exact SANDBOX service. Existing readers are untouched.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import json
import os
from zoneinfo import ZoneInfo

import supplier_evidence_recording_v3 as recording
import supplier_evidence_v3 as resolver

READ_FLAG = "PQM_SANDBOX_EVIDENCE_V3_READ"
SANDBOX_ID = "srv-dalfd77f3r2c7392uub0"
API_VERSION = "supplier-projection.v3"
MAX_SOURCE_ROWS = 2000
MAX_SOURCE_BYTES = 2 * 1024 * 1024


class SourceBudgetExceeded(RuntimeError):
    pass


def read_enabled():
    return (os.getenv(READ_FLAG, "").lower() in {"1", "true"}
            and os.getenv("PQM_SANDBOX", "").lower() in {"1", "true"}
            and os.getenv("RENDER_SERVICE_ID", "") == SANDBOX_ID)


def read_or_legacy(con, supplier_code, *, as_of_at, legacy_reader):
    """Future integration primitive: OFF calls only the existing reader."""
    if not read_enabled():
        return legacy_reader(con, supplier_code)
    return project_supplier(con, supplier_code, as_of_at=as_of_at)


def _rows(con, sql, args=()):
    cur = con.execute(sql, args)
    result, size = [], 0
    for raw in cur:
        size += len(json.dumps(tuple(raw), ensure_ascii=False).encode())
        if len(result) >= MAX_SOURCE_ROWS or size > MAX_SOURCE_BYTES:
            raise SourceBudgetExceeded("Supplier source exceeds 2000 rows / 2 MiB")
        result.append(dict(zip((c[0] for c in cur.description), raw)))
    return result


def _columns(con, table):
    # Table names are module constants, never supplier-controlled identifiers.
    return {r[1] for r in con.execute("PRAGMA table_info(" + table + ")")}


def _stamp(value):
    try:
        return value if datetime.fromisoformat(value).tzinfo is not None else None
    except (TypeError, ValueError):
        return None


def _actor(kind, officer):
    actor = resolver.attribution(provenance_kind=kind, officer=officer or "",
        environment="sandbox", canonical_sandbox_officer=resolver.SANDBOX_OFFICER)
    if actor.get("officer_source") == "sandbox_fallback":
        actor["officer_login"] = "sandbox.officer"
    return actor


def _key(event):
    return (event["environment"], event["source_system"],
            event["source_event_id"], event["supplier_code"], event["semantic_type"])


def _business(event):
    return (event["event_kind"], event["effective_date"], event["source_event_at"],
            event["actor"]["actor_type"], event["actor"]["actor_display"], event["snapshot"])


def _reconcile(events, gaps):
    """Native mirror wins representation, never conflicting factual content."""
    unique, refs, conflicting = {}, {}, set()
    for event in events:  # Native events precede external read-only evidence.
        key = _key(event)
        if key in unique and _business(unique[key]) != _business(event):
            gaps.append("conflicting_source_event_identity:" + event["source_event_id"])
            conflicting.add(key)
        else:
            unique.setdefault(key, event)
        legacy_id = event["provenance"].get("legacy_ledger_id")
        if legacy_id is not None:
            refs.setdefault(unique[key]["event_id"], set()).add(legacy_id)
    return [event for key, event in unique.items() if key not in conflicting], {k: sorted(v) for k, v in refs.items()}


def project_supplier(con, supplier_code, *, as_of_at):
    """Diagnostic callable; gated dispatch is read_or_legacy, not runtime wiring.

    Only SANDBOX is supported in this stage. No guessed admission/profile facts.
    SQL datasets are supplier-filtered and bounded, including histories and gaps.
    """
    if not (os.getenv("PQM_SANDBOX", "").lower() in {"1", "true"}
            and os.getenv("RENDER_SERVICE_ID", "") == SANDBOX_ID):
        raise PermissionError("Projection v3 requires exact SANDBOX service")
    if not isinstance(supplier_code, str) or not supplier_code.isascii() or not supplier_code.isdigit():
        raise ValueError("Literal supplier code required")
    assessment = datetime.fromisoformat(as_of_at)
    if assessment.tzinfo is None:
        raise ValueError("Explicit zoned assessment time required")
    day = assessment.astimezone(ZoneInfo("Europe/Kyiv")).date().isoformat()
    gaps, events = [], []
    native_columns = _columns(con, "supplier_evidence_events_v3")
    if native_columns:
        for row in _rows(con, recording._EVENT_SELECT +
                " WHERE environment=? AND supplier_code=?", ("sandbox", supplier_code)):
            events.append(recording._row_event(tuple(row.values())))

    app_columns = _columns(con, "application_fields")
    decision = "a.protocol_decision" if "protocol_decision" in app_columns else "NULL"
    manager = "COALESCE(a.manager_name,'')" if "manager_name" in app_columns else "''"
    applications = _rows(con, """SELECT s.id,s.date_published,s.supplier_name,
        s.qualification_id,q.status,COALESCE(a.protocol_officer,'') officer,""" +
        decision + " decision," + manager + """ manager_name FROM submissions s
        LEFT JOIN qualifications q ON q.id=s.qualification_id
        LEFT JOIN application_fields a ON a.submission_id=s.id
        WHERE s.supplier_code=?""", (supplier_code,))
    app_by_id = {r["id"]: r for r in applications}
    admitted = [r for r in applications if (r["status"] == "active" or r["decision"] == "admit")
        and r["date_published"] and r["date_published"][:10] <= day]
    reconstructed = []
    for row in admitted:
        stamp = row["date_published"]
        if not _stamp(stamp):
            gaps.append("admission_date_unproven:" + row["id"])
            continue
        reconstructed.append(resolver.make_event(supplier_code=supplier_code, kind="admission",
            effective_date=stamp[:10], source_event_at=stamp, actor=_actor("admission", row["officer"]),
            source_system="application", source_event_id=recording._json(["admission", row["id"]]),
            environment="sandbox", snapshot={"edr_status": "Зареєстровано",
                "full_name": row["supplier_name"], "manager_name": row["manager_name"]},
            provenance={"submission_id": row["id"], "qualification_id": row["qualification_id"],
                "date_source": "submission.date_published", "projection_only": True}))

    if _columns(con, "supplier_edr_verification_events"):
        ledger = _rows(con, """SELECT id,event_type,occurred_at,officer,snapshot_json,
            created_at,source_submission_id FROM supplier_edr_verification_events
            WHERE supplier_code=?""", (supplier_code,))
        for row in ledger:
            if row["event_type"] not in {"manual_edr", "google_clarity", "google_clarity_profile", "admission"}:
                continue
            try:
                snapshot = json.loads(row["snapshot_json"] or "{}")
                if not isinstance(snapshot, dict):
                    raise ValueError("Invalid snapshot")
                if snapshot.get("sandbox_historical_officer_normalization"):
                    continue
                kind = "admission" if row["event_type"] == "admission" else "edr_check"
                app = app_by_id.get(row["source_submission_id"])
                stamp = app["date_published"] if kind == "admission" and app else row["occurred_at"]
                if kind == "admission" and (not app or not _stamp(stamp)):
                    raise ValueError("Unproven admission source")
                if not str(row["officer"] or "").strip():
                    raise ValueError("Unproven verification officer")
                identity = row["source_submission_id"] if kind == "admission" else str(row["id"])
                events.append(resolver.make_event(supplier_code=supplier_code, kind=kind,
                    effective_date=stamp[:10], source_event_at=_stamp(stamp),
                    recorded_at=row["created_at"] or "", actor=_actor(kind, row["officer"]),
                    source_system="application" if kind == "admission" else "legacy_edr_ledger",
                    source_event_id=recording._json([kind, identity]), environment="sandbox",
                    snapshot=snapshot, provenance={"legacy_ledger_id": row["id"], "projection_only": True}))
            except (ValueError, TypeError, KeyError):
                gaps.append("legacy_verification_provenance_unproven:" + str(row["id"]))

    # Referenced native/ledger admission carries the actual recorded snapshot.
    # Source-only admission is a read-only baseline, never an extra check.
    recorded_keys = {_key(e) for e in events}
    for event in reconstructed:
        if _key(event) not in recorded_keys:
            events.append(event)
        else:
            for actual in events:
                if _key(actual) == _key(event) and _business(actual)[:5] != _business(event)[:5]:
                    gaps.append("conflicting_source_event_identity:" + event["source_event_id"])

    contracts = _rows(con, """SELECT r.id,r.status,f.status framework_status,
        json_extract(r.raw_json,'$.expiryDate') expiry_at,
        json_extract(f.raw_json,'$.qualificationPeriod.endDate') end_at
        FROM registry_contracts r LEFT JOIN frameworks f ON f.id=r.framework_id
        WHERE r.supplier_code=?""", (supplier_code,))
    inclusions = []
    for row in contracts:
        expiry, end = row["expiry_at"], row["end_at"]
        expired = bool(_stamp(expiry) and datetime.fromisoformat(expiry) <= assessment)
        framework_ended = bool(end and end[:10] < day)
        if row["status"] in {"active", "suspended"} and row["framework_status"] == "active" and not expired and not framework_ended:
            state = "suspended" if row["status"] == "suspended" else "active"
        else:
            state = "inactive"
        if expiry and not _stamp(expiry):
            gaps.append("invalid_inclusion_expiry:" + row["id"])
        inclusions.append({"inclusion_id": row["id"], "state": state})

    dated = []
    for row in applications:
        try:
            effective = resolver.calendar_date(row["date_published"][:10])
        except (ValueError, TypeError):
            gaps.append("application_date_unproven:" + row["id"])
            continue
        if effective <= day:
            dated.append({"effective_date": effective, "source_event_at": _stamp(row["date_published"]), "row": row})
    latest, ambiguity = resolver._latest(dated)
    if ambiguity:
        gaps.append("latest_application:" + ambiguity)
    last = None
    if latest:
        row = latest["row"]
        decided = row["decision"] in {"admit", "reject"} or row["status"] in {"active", "unsuccessful"}
        last = {"id": row["id"], "date_published": row["date_published"],
            "supplier_name": row["supplier_name"],
            "actor": _actor("rejection", row["officer"]) if decided else None,
            "outcome": row["decision"] or row["status"]}
    decisions = [e for e in dated if e["row"]["decision"] in {"admit", "reject"}
        or e["row"]["status"] in {"active", "unsuccessful"}]
    latest_decision, decision_ambiguity = resolver._latest(decisions)
    if decision_ambiguity:
        gaps.append("latest_decision:" + decision_ambiguity)
    last_decision = None
    if latest_decision:
        row = latest_decision["row"]
        last_decision = {"submission_id": row["id"], "date_published": row["date_published"],
            "actor": _actor("rejection", row["officer"]), "outcome": row["decision"] or row["status"]}
    logical, links = _reconcile(events, gaps)
    for event in logical:
        if event["effective_date"] > day:
            gaps.append("future_evidence:" + event["source_event_id"])
    result = resolver.resolve(supplier_code=supplier_code, events=logical,
        inclusions=inclusions, as_of=day, ever_admitted=bool(admitted or contracts), last_application=last)
    unproven_suspension = (result["prozorro_status"] == "Припинений" and not any(
        e["event_kind"] == "suspension" and e["effective_date"] <= day
        and e["provenance"].get("supplier_level") for e in logical))
    if unproven_suspension:
        gaps.append("suspension_date_unproven")
    persisted_gaps = []
    if _columns(con, "supplier_evidence_gaps_v3"):
        persisted_gaps = _rows(con, """SELECT g.gap_id,g.gap_type,g.gap_reason,
            CASE WHEN r.disposition='history_only' THEN 'history_only' ELSE g.review_scope END review_scope,
            g.remediation,g.known_event_date,g.known_actor,g.source_json
            FROM supplier_evidence_gaps_v3 g
            JOIN supplier_evidence_observations_v3 o ON o.observation_id=g.observation_id
            LEFT JOIN supplier_evidence_gap_resolutions_v3 r ON r.gap_id=g.gap_id
            WHERE o.environment=? AND o.supplier_code=?
            AND (r.gap_id IS NULL OR r.disposition='history_only')""", ("sandbox", supplier_code))
    result["gaps"] = sorted(set(result["gaps"] + gaps + [g["gap_type"] for g in persisted_gaps]))
    result["provenance_gaps"] = persisted_gaps
    result["legacy_native_links"] = links
    result["last_application_decision"] = last_decision
    if unproven_suspension or any(g.startswith(("conflicting_source_event_identity:", "latest_application:")) for g in gaps):
        for name in ("current_event", "current_event_type", "current_event_date", "current_event_actor", "current_event_provenance", "visible_date", "visible_actor"):
            result[name] = None
    if result["prozorro_status"] == "Ще не в реєстрі":
        result["visible_date"] = None
        result["visible_actor"] = last_decision["actor"]["actor_display"] if last_decision else None
    result["api_version"] = API_VERSION
    result["as_of_date"] = day
    result["assessed_at"] = as_of_at  # Read assessment metadata, NEVER an event timestamp.
    result["read_only"] = True
    result["logical_verification_count"] = len(result["verification_history"])
    return result


def api_fields(projection):
    """Additive future API namespace; existing verification fields not repurposed."""
    keys = ("supplier_code", "as_of_date", "assessed_at", "prozorro_status", "monitoring_eligible", "edr_status_current",
        "factual_snapshot", "current_event", "current_event_type", "current_event_date",
        "current_event_actor", "current_event_provenance", "last_verification_event",
        "last_verification_date", "last_verification_officer", "last_verification_provenance",
        "visible_date", "visible_actor", "last_application", "last_application_decision", "freshness", "gaps",
        "provenance_gaps", "legacy_native_links", "logical_verification_count")
    return {"supplier_evidence_v3": {"version": API_VERSION,
        **{k: deepcopy(projection[k]) for k in keys},
        "visible_date_semantics": "current_state_event_not_verification_only"}}
