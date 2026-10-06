"""Opt-in SANDBOX shadow adapters. No DDL, commits, network or population reads.

The caller owns the legacy transaction. A failed shadow savepoint is rolled back
and reported through structured ERROR logging; legacy success stays success.
Successful signals mean pending caller commit, not independently committed data.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
import logging
import os

import supplier_evidence_recording_v3 as recorder

LOG = logging.getLogger("pqm.evidence.shadow.v3")
FLAG = "PQM_SANDBOX_EVIDENCE_V3_SHADOW"
SANDBOX_ID = "srv-dalfd77f3r2c7392uub0"


def enabled():
    return (os.getenv(FLAG, "").lower() in {"1", "true"}
        and os.getenv("PQM_SANDBOX", "").lower() in {"1", "true"}
        and os.getenv("RENDER_SERVICE_ID", "") == SANDBOX_ID)


def _identity(*parts):
    return hashlib.sha256(json.dumps(parts, sort_keys=True,
        ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def _dict(row, cursor):
    return dict(zip((c[0] for c in cursor.description), row)) if row else None


def _one(con, sql, args):
    cur = con.execute(sql, args)
    return _dict(cur.fetchone(), cur)


def _stamp(value):
    try:
        parsed = datetime.fromisoformat(value or "")
        return value if parsed.tzinfo is not None else None
    except (ValueError, TypeError):
        return None


def _actor(kind, officer=""):
    actor = recorder.v3.attribution(provenance_kind=kind, officer=officer or "",
        environment="sandbox", canonical_sandbox_officer=recorder.v3.SANDBOX_OFFICER)
    if actor.get("officer_source")=="sandbox_fallback":
        actor["officer_login"]="sandbox.officer"  # Login, not a guessed directory ID.
    return actor


def _run(con, hook, code, action):
    if not enabled():
        return
    owned_transaction = con.in_transaction
    try:
        if not con.in_transaction:
            raise RuntimeError("Shadow hook requires caller-owned legacy transaction")
        # No schema probing/creation when OFF. Missing explicit migration is an
        # observable configuration failure when ON, not an implicit migration.
        with recorder.atomic(con):
            result = action()
        LOG.info("shadow_v3 %s", json.dumps(dict(hook=hook,subject_id=code,
            status="pending_legacy_commit",result=result), ensure_ascii=False))
    except Exception as error:
        if owned_transaction and not con.in_transaction:
            # SQLite fatal failures can invalidate the whole caller transaction.
            # Never pretend legacy success in that case; propagate explicitly.
            LOG.critical("shadow_v3 legacy_transaction_lost hook=%s supplier=%s",hook,code,exc_info=True)
            raise
        LOG.error("shadow_v3 %s", json.dumps(dict(hook=hook,subject_id=code,
            status="shadow_failed_legacy_unchanged",error_type=type(error).__name__,
            error=str(error)), ensure_ascii=False), exc_info=True)


def context(con, code, recorded_at):
    """Supplier-filtered current source context; never call monitoring rebuild."""
    as_of = recorded_at[:10]
    cur = con.execute("""SELECT r.id,r.status,f.status framework_status,
      json_extract(f.raw_json,'$.qualificationPeriod.endDate') end_at,
      json_extract(r.raw_json,'$.expiryDate') expiry_at,r.synced_at observed_at
      FROM registry_contracts r LEFT JOIN frameworks f ON f.id=r.framework_id
      WHERE r.supplier_code=?""", (code,))
    inclusions = []
    for raw in cur:
        row = _dict(raw, cur)
        expired = (_stamp(row["expiry_at"]) and
            datetime.fromisoformat(row["expiry_at"]) <= datetime.fromisoformat(recorded_at))
        state = ("suspended" if row["status"] == "suspended" and not expired else "active"
            if row["status"] == "active" and row["framework_status"] == "active"
            and not expired and (not row["end_at"] or row["end_at"][:10] >= as_of) else "inactive")
        inclusions.append(dict(supplier_code=code,inclusion_id=row["id"],state=state,
            observed_at=row["observed_at"]))
    latest_cur = con.execute("""SELECT s.id,s.date_published,s.supplier_name,q.status,
      COALESCE(a.protocol_officer,'') officer FROM submissions s
      LEFT JOIN qualifications q ON q.id=s.qualification_id
      LEFT JOIN application_fields a ON a.submission_id=s.id
      WHERE s.supplier_code=?""", (code,))
    applications = [_dict(r, latest_cur) for r in latest_cur]
    dated = [dict(effective_date=r["date_published"][:10],
        source_event_at=_stamp(r["date_published"]),row=r) for r in applications
        if r["date_published"] and r["date_published"][:10] <= as_of]
    latest, ambiguity = recorder.v3._latest(dated)
    last = None
    if latest:
        row = latest["row"]
        last = dict(id=row["id"],date_published=row["date_published"],
            supplier_name=row["supplier_name"],actor=_actor("rejection",row["officer"]))
    return dict(environment="sandbox",supplier_code=code,as_of=as_of,
        rebuilt_at=recorded_at,inclusions=inclusions,
        ever_admitted=bool(inclusions) or any(r["status"] == "active" for r in applications),
        last_application=last), ambiguity


def _gap(con, code, source, identity, recorded_at, payload, gap_type, reason,
         known_at="", actor="", history_only=False):
    try:
        day = recorder.v3.calendar_date(known_at[:10]) if known_at else ""
    except ValueError:
        day = ""
    source_id = payload.get("source_id") or payload.get("contract_id") or payload.get("submission_id") or identity
    return recorder.observe_gap(con,environment="sandbox",supplier_code=code,
        source_system="shadow_ingestion",source_object=source,source_id=identity,
        observed_at=recorded_at,payload=payload,gaps=[dict(gap_type=gap_type,
            gap_reason=reason,review_scope="history_only" if history_only else "active",
            remediation="provenance_review",known_event_date=day,
            known_actor=actor,source=dict(source_object=source,source_id=source_id,
                source_event_identity=identity,source_field=payload.get("source_field", ""),
                related_sources=payload.get("source_events", [])),
            recommended_action="Перевірити матеріали джерела та підтвердити provenance події.")])


def _project(con, code, recorded_at):
    ctx, ambiguity = context(con,code,recorded_at)
    if ambiguity:
        _gap(con,code,"latest_application",_identity(code,ambiguity),recorded_at,
            {},"chronology_ambiguity",ambiguity)
    projection = recorder.update_projection(con,**ctx)
    # Existing, proven verification history is read-only baseline evidence,
    # not a backfill. A new lifecycle must not erase the last legacy check.
    native = [recorder._row_event(row) for row in con.execute(recorder._EVENT_SELECT+
        " WHERE environment='sandbox' AND supplier_code=? AND effective_date<=?",(code,ctx["as_of"]))]
    native_ids = {event["event_id"] for event in native}
    baseline = _legacy_verification_baseline(con,code,native_ids,ctx["as_of"])
    if baseline:
        projection = recorder.v3.resolve(supplier_code=code,events=native+baseline,
            inclusions=ctx["inclusions"],as_of=ctx["as_of"],ever_admitted=ctx["ever_admitted"],
            last_application=ctx["last_application"])
        cached = {k:v for k,v in projection.items() if k!="verification_history"}
        # Foreign keys remain native-v3 only. External identities/provenance
        # live in projection JSON, backed by immutable existing ledger rows.
        current, last = projection["current_event"],projection["last_verification_event"]
        cached["legacy_baseline_refs"] = dict(current=(current or {}).get("provenance",{}).get("legacy_ledger_id"),
            last_verification=(last or {}).get("provenance",{}).get("legacy_ledger_id"))
        con.execute("""UPDATE supplier_evidence_current_v3 SET current_event_id=?,last_verification_event_id=?,
          projection_json=? WHERE environment='sandbox' AND supplier_code=?""",(
            current["event_id"] if current and current["event_id"] in native_ids else None,
            last["event_id"] if last and last["event_id"] in native_ids else None,
            recorder._json(cached),code))
    for gap in projection["gaps"]:
        if gap != "missing_verification_evidence":
            _gap(con,code,"projection",_identity(code,gap),recorded_at,
                {"projection_gap":gap},gap.split(":")[-1],gap)
    if "missing_verification_evidence" in projection["gaps"]:
        recorder.observe_gap(con,environment="sandbox",supplier_code=code,
            source_system="shadow_projection",source_object="supplier",
            source_id=_identity(code,"missing_verification_evidence"),observed_at=recorded_at,
            payload={"supplier_code":code},gaps=[dict(gap_type="missing_verification_evidence",
                gap_reason="Monitoring-eligible supplier lacks a complete verification",
                review_scope="active",remediation="factual_verification",
                recommended_action="Перевірити ЄДР; внести підтверджені дату, УО та факти в Google.")])
    elif projection["last_verification_event"] and projection["last_verification_event"]["event_id"] in native_ids:
        # Only this explicit factual gap is proved closed by a complete check.
        # Attribution/chronology gaps are NEVER blanket-cleared by verification.
        gaps = con.execute("""SELECT g.gap_id FROM supplier_evidence_gaps_v3 g
          JOIN supplier_evidence_observations_v3 o ON o.observation_id=g.observation_id
          LEFT JOIN supplier_evidence_gap_resolutions_v3 r ON r.gap_id=g.gap_id
          WHERE o.supplier_code=? AND o.environment='sandbox' AND r.gap_id IS NULL
            AND g.gap_type='missing_verification_evidence' AND g.review_scope='active'
            AND g.remediation='factual_verification'""",(code,)).fetchall()
        if gaps:
            recorder.reassess_verification_gaps(con,environment="sandbox",supplier_code=code,
                event_id=projection["last_verification_event"]["event_id"],assessed_at=recorded_at,
                assessments={r[0]:dict(closed=True,reason="Complete attributable factual verification recorded") for r in gaps})
    return projection


def _legacy_verification_baseline(con, code, native_ids, as_of):
    """Actual legacy verification rows only; never profile/date/officer guesses.

    No events, profile updates, migration or history copying. Admission uses the
    referenced source submission timestamp, never old qualification/protocol day.
    """
    if not con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='supplier_edr_verification_events'").fetchone():
        return []
    cur = con.execute("""SELECT e.id,e.event_type,e.occurred_at,e.officer,e.snapshot_json,
      e.created_at,e.source_sheet,e.source_row,e.source_submission_id,s.date_published
      FROM supplier_edr_verification_events e LEFT JOIN submissions s ON s.id=e.source_submission_id
      WHERE e.supplier_code=? AND e.event_type IN ('manual_edr','google_clarity','google_clarity_profile','admission')""",(code,))
    result = []
    for raw in cur:
        row = _dict(raw,cur)
        try:
            snapshot = json.loads(row["snapshot_json"] or "{}")
            if not isinstance(snapshot,dict) or not str(row["officer"] or "").strip():
                continue
            if snapshot.get("sandbox_historical_officer_normalization"):
                continue  # A technical normalization is not a check event.
            admission = row["event_type"]=="admission"
            stamp = row["date_published"] if admission else row["occurred_at"]
            if admission and (not _stamp(stamp) or not row["source_submission_id"]):
                continue
            if not stamp or stamp[:10]>as_of:
                continue
            if not admission and snapshot.get("edr_status") in {None,"","Неактуально"}:
                continue
            identity = row["source_submission_id"] if admission else str(row["id"])
            kind = "admission" if admission else "edr_check"
            actor = _actor(kind,row["officer"])
            event = recorder.v3.make_event(supplier_code=code,kind=kind,effective_date=stamp[:10],
                source_event_at=_stamp(stamp),recorded_at=row["created_at"] or "",environment="sandbox",
                source_system="application" if admission else "legacy_edr_ledger",
                source_event_id=recorder._json([kind,identity]),actor=actor,snapshot=snapshot,
                provenance=dict(legacy_ledger_id=row["id"],legacy_event_type=row["event_type"],
                    source_sheet=row["source_sheet"],source_row=row["source_row"],
                    submission_id=row["source_submission_id"] or "",projection_only=True))
            if event["event_id"] not in native_ids:
                result.append(event)
        except (ValueError,TypeError):
            continue  # Insufficient historical evidence is never fabricated.
    # One actual referenced application may have repeated legacy observations.
    unique = {}
    for event in result:
        if event["event_id"] in unique:
            previous = unique[event["event_id"]]
            left, right = recorder._event_payload(previous), recorder._event_payload(event)
            left.pop("provenance",None)
            right.pop("provenance",None)
            if left != right:
                raise recorder.SourceIdentityConflict(event["event_id"])
            refs = previous["provenance"].setdefault("legacy_ledger_ids",[previous["provenance"]["legacy_ledger_id"]])
            refs.append(event["provenance"]["legacy_ledger_id"])
            previous["provenance"]["legacy_ledger_ids"] = sorted(set(refs))
            continue
        unique[event["event_id"]] = event
    return list(unique.values())


def _record_gap(con, code, source, identity, recorded_at, payload, gap_type, reason, **known):
    observation = _gap(con,code,source,identity,recorded_at,payload,gap_type,reason,**known)
    # Current source state can be projected without fabricating the missing
    # event time/actor. Persist observation + shadow cache in one savepoint.
    _project(con,code,recorded_at)
    return observation


def _last_loss_event(con, code, inclusions, before, recorded_at):
    """The last lost inclusion is selected by chronology, never UPSERT order.

    Earlier inactive baseline rows need not be backfilled: a real observation
    before the selected transition proves they were already inactive. Without
    that proof retain an explicit gap, never fabricate supplier chronology.
    """
    groups = {}
    for row in con.execute("""SELECT inclusion_id,state_after,effective_date,
      source_event_at,source_event_id,source_system,payload_json
      FROM supplier_inclusion_history_v3 WHERE environment='sandbox' AND supplier_code=?""",(code,)):
        groups.setdefault(row[0],[]).append(dict(inclusion_id=row[0],state=row[1],
            effective_date=row[2],source_event_at=row[3],source_event_id=row[4],
            source_system=row[5],payload=json.loads(row[6])))
    def gap_payload(entries):
        # Deterministic audit representation only; IDs never select chronology.
        return dict(source_events=sorted([dict(inclusion_id=e["inclusion_id"],
            source_event_id=e["source_event_id"],source_event_at=e["source_event_at"],
            actor=e["payload"]["actor"],provenance=e["payload"]["provenance"]) for e in entries],
            key=lambda e:(e["inclusion_id"],e["source_event_id"])))
    terminals = {}
    for inclusion_id, entries in groups.items():
        latest, gap = recorder.v3._latest(entries)
        if gap:
            payload = gap_payload(entries)
            return _record_gap(con,code,"supplier_last_loss",_identity(code,gap,payload),recorded_at,
                payload,"chronology_ambiguity",gap)
        if latest["state"]=="inactive":
            terminals[inclusion_id] = latest
    selected, gap = recorder.v3._latest(list(terminals.values()))
    if gap or not selected or not _stamp(selected.get("source_event_at")):
        payload = gap_payload(list(terminals.values()))
        return _record_gap(con,code,"supplier_last_loss",_identity(code,gap or "unknown",payload),recorded_at,
            payload,"chronology_ambiguity",gap or "Exact last-inclusion transition not proven")
    for inclusion in inclusions:
        identity = inclusion["inclusion_id"]
        if identity not in terminals:
            baseline = next((i for i in before if i["inclusion_id"]==identity),None)
            stamp = _stamp((baseline or {}).get("observed_at"))
            if not baseline or baseline["state"]!="inactive" or not stamp or (
                    datetime.fromisoformat(stamp)>=datetime.fromisoformat(selected["source_event_at"])):
                return _record_gap(con,code,"supplier_last_loss",_identity(code,identity,selected["source_event_id"]),
                    recorded_at,{"source_id":identity},"transition_context_unproven",
                    "Inactive baseline not proven before last-inclusion transition")
    prov = dict(selected["payload"]["provenance"],supplier_level=True,
        inclusion_id=selected["inclusion_id"],effective_active_before=1,effective_active_after=0)
    kind = "expiry" if prov["time_evidence"]=="expiry_boundary" else "exclusion"
    return recorder.append_event(con,supplier_code=code,kind=kind,effective_date=selected["effective_date"],
        source_event_at=selected["source_event_at"],recorded_at=recorded_at,environment="sandbox",
        actor=selected["payload"]["actor"],source_system=selected["source_system"],
        source_event_id=selected["source_event_id"],snapshot={},provenance=prov)


def application_decision(con, submission_id, outcome, recorded_at):
    """Only called after persisted qualification/protocol decision, never Preview."""
    if not enabled() or outcome not in {"admit", "reject"}:
        return
    def action():
        row = _one(con,"""SELECT s.id,s.supplier_code,s.date_published,
          s.supplier_name,s.qualification_id,q.status qualification_status,COALESCE(a.protocol_officer,'') officer,
          COALESCE(a.manager_name,'') manager_name FROM submissions s
          LEFT JOIN application_fields a ON a.submission_id=s.id
          LEFT JOIN qualifications q ON q.id=s.qualification_id WHERE s.id=?""",
          (submission_id,))
        if not row:
            raise ValueError("Submission not available")
        code = row["supplier_code"]
        timestamp = _stamp(row["date_published"])
        prov = dict(submission_id=row["id"],qualification_id=row["qualification_id"],
            submission_date_published=row["date_published"],outcome=outcome,
            officer_source="application_protocol")
        ctx, _ = context(con,code,recorded_at)
        if outcome == "reject" or row["qualification_status"] != "active":
            prov["ever_admitted"] = ctx["ever_admitted"]
        if not timestamp or not row["qualification_id"]:
            return _record_gap(con,code,"submission",_identity(submission_id,outcome),
                recorded_at,prov,"admission_date_unproven" if outcome=="admit"
                else "decision_provenance_unproven","Missing exact submission timestamp/qualification",
                known_at=row["date_published"] or "",actor=row["officer"])
        # Rejection is a decision observation, NOT a verification/lifecycle event.
        if outcome == "reject" or row["qualification_status"] != "active":
            decision_kind = "rejection" if outcome=="reject" else "admission_pending_catalogue"
            actor = _actor("rejection" if outcome=="reject" else "admission",row["officer"])
            observation_id = _identity(decision_kind,submission_id,row["qualification_status"])
            body = dict(prov,actor=actor,qualification_status=row["qualification_status"])
            digest = _identity(body)
            previous = con.execute("SELECT payload_hash FROM supplier_evidence_observations_v3 WHERE observation_id=?",
                (observation_id,)).fetchone()
            if previous and previous[0] != digest:
                raise recorder.SourceIdentityConflict(observation_id)
            if not previous:
                con.execute("INSERT INTO supplier_evidence_observations_v3 VALUES (?,?,?,?,?,?,?,?,?)",
                    (observation_id,"sandbox",code,"application",decision_kind,
                     _identity(submission_id,row["qualification_status"]),
                     recorded_at,json.dumps(body,ensure_ascii=False,sort_keys=True),digest))
            _project(con,code,recorded_at)
            return dict(observation_id=observation_id,verification=False)
        event = dict(supplier_code=code,kind="admission",effective_date=timestamp[:10],
            source_event_at=timestamp,recorded_at=recorded_at,environment="sandbox",
            actor=_actor("admission",row["officer"]),source_system="application",
            source_event_id=submission_id,snapshot=dict(edr_status="Зареєстровано",
                full_name=row["supplier_name"],manager_name=row["manager_name"]),provenance=prov)
        inserted = recorder.append_event(con,**event)
        _project(con,code,recorded_at)
        return dict(inserted=inserted)
    _run(con,"application_decision",submission_id,action)


def verification(con, *, source_id, item, event_type, occurred_at, officer, recorded_at, snapshot):
    """Post legacy ledger INSERT: legacy ID is the immutable source check identity.

    No calendar-day/factual-hash identity is invented. Date-only source stays
    date-only. The import execution timestamp is NOT the check timestamp.
    """
    if not enabled() or event_type not in {"google_clarity", "manual_edr"}:
        return
    code = item["supplier_code"]
    def action():
        if not officer or officer.strip()==recorder.v3.SYSTEM_ACTOR or not occurred_at or not source_id:
            return _record_gap(con,code,"verification",str(source_id),recorded_at,snapshot,
                "verification_provenance_unproven","Missing actual check date/officer/identity",
                known_at=occurred_at or "",actor=officer or "")
        day = recorder.v3.calendar_date(occurred_at[:10])
        event = dict(supplier_code=code,kind="edr_check",effective_date=day,
            source_event_at=_stamp(occurred_at),recorded_at=recorded_at,
            environment="sandbox",actor=_actor("edr_check",officer),
            source_system="legacy_edr_ledger",source_event_id=str(source_id),
            snapshot=snapshot,provenance=dict(source_event_type=event_type,
                source_sheet=item.get("source_sheet",""),source_row=item.get("source_row"),
                actual_check_at=occurred_at))
        if snapshot.get("edr_status") in {None,"","Неактуально"}:
            return _record_gap(con,code,"verification",str(source_id),recorded_at,snapshot,
                "verification_facts_unproven","No source factual EDR status; no fallback")
        inserted = recorder.append_event(con,**event)
        _project(con,code,recorded_at)
        return dict(inserted=inserted)
    _run(con,"verification",code,action)


def transition_provenance(item, old_status, new_status):
    """Only explicit status history proves a transition. dateModified alone does not."""
    if old_status=="active" and new_status=="suspended":
        bans = [m for m in (item.get("milestones") or []) if m.get("type")=="ban"
            and m.get("status")=="met" and _stamp(m.get("dateMet"))]
        if bans:
            candidates = {_identity(item["id"],m.get("id"),"ban",m["dateMet"]):
                dict(effective_date=m["dateMet"][:10],source_event_at=m["dateMet"],milestone=m)
                for m in bans}
            selected, gap = recorder.v3._latest(list(candidates.values()))
            if gap:
                return {"ambiguity":gap}
            milestone = selected["milestone"]
            return dict(source_object="contract",source_id=item["id"],
                source_field="milestones.dateMet",milestone_id=milestone.get("id"),
                transition_at=milestone["dateMet"],source_event_id=_identity(item["id"],
                    milestone.get("id"),"ban",milestone["dateMet"]),automatic=True)
    candidates = {}
    for entry in item.get("statusHistory", []) or []:
        if (entry.get("from") == old_status and entry.get("to") == new_status
                and _stamp(entry.get("date"))):
            identity = entry.get("id") or _identity(item["id"],old_status,new_status,entry["date"])
            candidate = dict(effective_date=entry["date"][:10],source_event_at=entry["date"],
                proof=dict(source_object="contract",source_id=item["id"],
                source_field="statusHistory",transition_at=entry["date"],
                source_event_id=identity,
                automatic=entry.get("automatic"),officer=entry.get("officer", "")))
            if identity in candidates and candidates[identity] != candidate:
                return {"ambiguity":"conflicting_source_event_identity"}
            candidates[identity] = candidate
    latest, ambiguity = recorder.v3._latest(list(candidates.values()))
    return {"ambiguity":ambiguity} if ambiguity else latest["proof"] if latest else None


def capture_contract(con, item, recorded_at):
    """Before UPSERT; only targeted reads and only when opted in."""
    if not enabled():
        return None
    try:
        row = _one(con,"SELECT status,raw_json,synced_at FROM registry_contracts WHERE id=?",(item["id"],))
        code = ((item.get("suppliers") or [{}])[0].get("identifier") or {}).get("id", "")
        ctx, _ = context(con,code,recorded_at)
        return dict(row or {},before_inclusions=ctx["inclusions"])
    except Exception:
        LOG.exception("shadow_v3 capture_failed contract=%s",item.get("id"))
        return None


def capture_framework(con, framework_id):
    if not enabled():
        return None
    try:
        return _one(con,"SELECT status,raw_json,synced_at FROM frameworks WHERE id=?",(framework_id,))
    except Exception:
        LOG.exception("shadow_v3 capture_failed framework=%s",framework_id)
        return None


def framework_written(con, *, item, previous, recorded_at):
    """Metadata-only refresh is also an ingestion boundary.

    A qualificationPeriod.endDate by itself does NOT establish the agreed
    exact expiry instant/convention. Retain a gap rather than use poll time.
    Stream supplier codes belonging to this framework, never all suppliers.
    """
    if not enabled() or not previous:
        return
    transaction = con.in_transaction
    try:
        old = json.loads(previous.get("raw_json") or "{}")
        if not isinstance(old,dict):
            raise ValueError("Invalid previous framework source object")
        end = (item.get("qualificationPeriod") or {}).get("endDate")
        old_seen = _stamp(previous.get("synced_at"))
        newly_expired = (end and old_seen and old_seen[:10] <= end[:10] < recorded_at[:10])
        status_changed = previous.get("status") != item.get("status")
        if not newly_expired and not status_changed:
            return
        cursor = con.execute("SELECT DISTINCT supplier_code FROM registry_contracts WHERE framework_id=?",
            (item["id"],))
        for row in cursor:
            code = row[0]
            def action():
                identity = _identity(item["id"],previous.get("status"),item.get("status"),end)
                _gap(con,code,"framework",identity,recorded_at,
                    dict(source_object="framework",source_id=item["id"],
                        source_field="qualificationPeriod.endDate" if newly_expired else "status",
                        source_end=end,previous_end=(old.get("qualificationPeriod") or {}).get("endDate"),
                        old_status=previous.get("status"),new_status=item.get("status")),
                    "expiry_boundary_requires_explicit_source_convention" if newly_expired
                        else "transition_date_unproven",
                    "Exact lifecycle boundary/transition provenance not established",
                    actor=recorder.v3.SYSTEM_ACTOR if newly_expired else "")
                _project(con,code,recorded_at)
                return dict(gap=True)
            _run(con,"framework_metadata",code,action)
    except Exception:
        LOG.exception("shadow_v3 framework_source_read_failed framework=%s",item.get("id"))
        if transaction and not con.in_transaction:
            raise


def contract_written(con, *, item, previous, recorded_at, proof=None):
    """After contract UPSERT; proof may come from an attested manual decision.

    Unproven initial terminated rows remain history-only gaps. No historical
    backfill. Partial termination only appends inclusion history.
    """
    if not enabled():
        return
    code = ((item.get("suppliers") or [{}])[0].get("identifier") or {}).get("id", "")
    def action():
        old = (previous or {}).get("status")
        new = item.get("status")
        # A new, explicit source expiry boundary crossing. Never infer expiry
        # from poll time, a generic dateModified or an already-expired baseline.
        expiry = _stamp(item.get("expiryDate"))
        seen_at = _stamp((previous or {}).get("synced_at"))
        if (old==new=="active" and expiry and seen_at
                and datetime.fromisoformat(seen_at) < datetime.fromisoformat(expiry)
                <= datetime.fromisoformat(recorded_at)):
            return _record_expiry(con,code,item,previous,expiry,recorded_at)
        if old == new:
            return dict(no_transition=True)
        if new == "active":
            kind = "resumption" if old == "suspended" else "activation"
        elif new == "suspended":
            kind = "suspension"
        elif new == "terminated":
            kind = "termination"
        else:
            return dict(unsupported_status=new)
        evidence = proof or transition_provenance(item,old,new)
        if evidence and evidence.get("ambiguity"):
            return _record_gap(con,code,"contract",_identity(item["id"],old,new),recorded_at,evidence,
                "chronology_ambiguity",evidence["ambiguity"])
        if not evidence or not _stamp(evidence.get("transition_at")):
            return _record_gap(con,code,"contract",_identity(item["id"],old,new),recorded_at,
                dict(contract_id=item["id"],framework_id=item.get("frameworkID"),old_status=old,new_status=new),
                "termination_date_unproven" if kind=="termination" else "suspension_date_unproven"
                if kind=="suspension" else "transition_date_unproven",
                "No exact source status-transition timestamp",history_only=old is None)
        stamp = evidence["transition_at"]
        if datetime.fromisoformat(stamp)>datetime.fromisoformat(recorded_at):
            return _record_gap(con,code,"contract",evidence["source_event_id"],recorded_at,evidence,
                "transition_date_unproven","Source transition is ahead of observed ingestion time",known_at=stamp)
        if kind in {"termination","activation"} and type(evidence.get("automatic")) is not bool:
            return _record_gap(con,code,"contract",evidence["source_event_id"],recorded_at,evidence,
                "termination_date_unproven" if kind=="termination" else "missing_attribution",
                "Inclusion type/actor not proven",known_at=stamp)
        if kind == "termination" and evidence["automatic"]:
            boundary = _stamp(item.get("expiryDate"))
            if (not boundary or datetime.fromisoformat(boundary)>datetime.fromisoformat(recorded_at)):
                return _record_gap(con,code,"contract_supplier",evidence["source_event_id"],recorded_at,evidence,
                    "termination_date_unproven","Automatic termination lacks actual source expiryDate boundary",known_at=stamp)
            # The expiry instant is source expiryDate, never status dateModified
            # or a truthy marker named expiry_boundary.
            return _record_expiry(con,code,item,previous,boundary,recorded_at)
        manual = kind in {"termination","activation"} and not evidence["automatic"]
        actor = (_actor("exclusion" if kind=="termination" else "admission",evidence.get("officer", ""))
            if manual else _actor("expiry"))
        if manual and not evidence.get("officer"):
            return _record_gap(con,code,"contract",evidence["source_event_id"],recorded_at,evidence,
                "missing_attribution","Manual lifecycle officer not proven",known_at=stamp)
        prov = dict(evidence,old_status=old,new_status=new,time_evidence="source_transition",
            automatic_manual="manual" if manual else "automatic")
        state = "inactive" if kind=="termination" else "suspended" if kind=="suspension" else "active"
        recorder.append_inclusion(con,supplier_code=code,inclusion_id=item["id"],kind=kind,
            state_after=state,effective_date=stamp[:10],source_event_at=stamp,
            recorded_at=recorded_at,source_system="prozorro",source_event_id=evidence["source_event_id"],
            actor=actor,provenance=prov,environment="sandbox")
        ctx, _ = context(con,code,recorded_at)
        active_after = sum(i["state"] in {"active","suspended"} for i in ctx["inclusions"])
        before = (previous or {}).get("before_inclusions")
        if before is None:
            return _record_gap(con,code,"contract_supplier",evidence["source_event_id"],recorded_at,evidence,
                "transition_context_unproven","No proven pre-write inclusion state",known_at=stamp)
        active_before = sum(i["state"] in {"active","suspended"} for i in before)
        supplier_kind = "exclusion" if kind=="termination" else kind
        supplier_level = (kind=="termination" and active_before>0 and active_after==0 and old in {"active","suspended"}
            or kind=="suspension" and not any(i["state"]=="active" for i in ctx["inclusions"])
            or kind=="resumption" and old=="suspended" and not any(i["state"]=="active" for i in before))
        if supplier_level:
            prov.update(supplier_level=True,inclusion_id=item["id"],
                effective_active_before=active_before,effective_active_after=active_after)
            if supplier_kind=="expiry":
                prov["time_evidence"]="expiry_boundary"
            if kind=="termination":
                _last_loss_event(con,code,ctx["inclusions"],before,recorded_at)
            else:
                recorder.append_event(con,supplier_code=code,kind=supplier_kind,
                    effective_date=stamp[:10],source_event_at=stamp,recorded_at=recorded_at,
                    environment="sandbox",actor=actor,source_system="prozorro",
                    source_event_id=evidence["source_event_id"],snapshot={},provenance=prov)
        _project(con,code,recorded_at)
        return dict(inclusion=True,supplier_level=supplier_level)
    _run(con,"contract_transition",code,action)


def _record_expiry(con, code, item, previous, boundary, recorded_at):
    """Only an observed crossing of explicit contract.expiryDate, never backfill."""
    actor = _actor("expiry")
    identity = _identity(item["id"],"expiryDate",boundary)
    prov = dict(source_object="contract",source_id=item["id"],source_field="expiryDate",
        framework_id=item.get("frameworkID"),inclusion_id=item["id"],
        time_evidence="expiry_boundary",automatic_manual="automatic")
    recorder.append_inclusion(con,supplier_code=code,inclusion_id=item["id"],kind="expiry",
        state_after="inactive",effective_date=boundary[:10],source_event_at=boundary,
        recorded_at=recorded_at,source_system="prozorro",source_event_id=identity,
        actor=actor,provenance=prov,environment="sandbox")
    ctx, _ = context(con,code,recorded_at)
    # The explicit expired inclusion overrides its stale source 'active' status
    # in the shadow context only. Other effective inclusions remain untouched.
    for inclusion in ctx["inclusions"]:
        if inclusion["inclusion_id"]==item["id"]:
            inclusion["state"]="inactive"
    after = sum(i["state"] in {"active","suspended"} for i in ctx["inclusions"])
    before = (previous or {}).get("before_inclusions")
    if before is None:
        return _record_gap(con,code,"contract_supplier",identity,recorded_at,prov,
            "transition_context_unproven","No pre-expiry effective inclusion evidence",known_at=boundary)
    target = next((i for i in before if i["inclusion_id"]==item["id"]),None)
    if target is None or target["state"] not in {"active","suspended"}:
        return _record_gap(con,code,"contract_supplier",identity,recorded_at,prov,
            "transition_context_unproven","Source boundary does not prove last effective inclusion loss",known_at=boundary)
    supplier_level = after==0
    if supplier_level:
        prov.update(supplier_level=True,effective_active_before=sum(
            i["state"] in {"active","suspended"} for i in before),effective_active_after=0)
        _last_loss_event(con,code,ctx["inclusions"],before,recorded_at)
    _project(con,code,recorded_at)
    return dict(inclusion=True,supplier_level=supplier_level)


def manual_review_dataset(con, *, after_code="", limit=100):
    """Read-only export view, including known cached latest application names.

    No flag activation, rebuilding, event creation or gap reassessment here.
    The dataset is always explicitly SANDBOX-scoped; there is no PROD route.
    """
    dataset = recorder.manual_review_dataset(con,environment="sandbox",after_code=after_code,limit=limit)
    for row in dataset["rows"]:
        if not row["supplier_name"]:
            cached = con.execute("SELECT projection_json FROM supplier_evidence_current_v3 WHERE environment='sandbox' AND supplier_code=?",
                (row["supplier_code"],)).fetchone()
            if cached:
                row["supplier_name"] = ((json.loads(cached[0]).get("last_application") or {}).get("supplier_name") or "")
            if not row["supplier_name"]:
                candidates = [dict(effective_date=stamp[:10],source_event_at=stamp,name=name)
                    for name,stamp in con.execute("SELECT supplier_name,date_published FROM submissions WHERE supplier_code=?",
                        (row["supplier_code"],)) if _stamp(stamp)]
                selected, ambiguity = recorder.v3._latest(candidates)
                if selected and not ambiguity:
                    row["supplier_name"] = selected["name"] or ""
    return dataset
