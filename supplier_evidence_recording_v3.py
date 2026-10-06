"""Standalone Stage 3 primitives. No runtime imports, DDL, commits or network.

All writes are explicit caller actions on a caller-owned connection/transaction.
No historical reconstruction, ingestion hooks or authoritative cutover occurs here.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
import csv
import hashlib
import io
import json
from uuid import uuid4

import supplier_evidence_v3 as v3


class SourceIdentityConflict(ValueError):
    """Same immutable source event identity, different business content."""


PROVENANCE_GAP_TYPES = frozenset({"suspension_date_unproven", "termination_date_unproven",
    "missing_attribution", "missing_officer", "insufficient_attribution_provenance",
    "ambiguous_same_day_events", "ambiguous_same_timestamp", "chronology_ambiguity"})


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _identity(*parts):
    return hashlib.sha256(_json(parts).encode()).hexdigest()


def _text(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Missing " + field)
    return value


def _stamp(value):
    dt = datetime.fromisoformat(_text(value, "timestamp"))
    if dt.tzinfo is None:
        raise ValueError("Timestamp must include timezone")
    return dt


def _environment(value):
    if value not in ("sandbox", "prod"):
        raise ValueError("Invalid environment")
    return value


def _sandbox_actor(actor):
    return (str(actor.get("actor_display") or "").strip().casefold() == v3.SANDBOX_OFFICER.casefold()
        or str(actor.get("officer_id") or "").strip().casefold() == "sandbox.officer"
        or str(actor.get("officer_source") or "").strip() == "sandbox_fallback")


def _validate_actor(actor):
    display = _text(actor.get("actor_display"), "actor_display")
    if actor.get("actor_type") not in ("officer", "system"):
        raise ValueError("Explicit officer/system actor required")
    if actor["actor_type"] == "officer" and display.strip() == v3.SYSTEM_ACTOR:
        raise ValueError("ЕСЗ is a system source, not a verification officer")


@contextmanager
def atomic(con):
    """Rollback this operation on failure; NEVER commit the caller's work.

    Start a transaction if necessary; even a successful operation remains pending
    until the caller explicitly commits. Safe when nested or using autocommit.
    """
    if not con.in_transaction:
        con.execute("BEGIN IMMEDIATE")
    name = "evidence_" + uuid4().hex
    con.execute("SAVEPOINT " + name)
    try:
        yield
    except BaseException:
        con.execute("ROLLBACK TO " + name)
        con.execute("RELEASE " + name)
        raise
    else:
        con.execute("RELEASE " + name)


def prepare_event(*, supplier_code, kind, effective_date, actor, source_system,
                  source_event_id, recorded_at, environment="prod", snapshot=None,
                  provenance=None, source_event_at=None):
    """Kind-namespaced source identity; no date/officer/snapshot deduplication."""
    _stamp(recorded_at)
    _validate_actor(actor)
    provenance = dict(provenance or {})
    if "_recording_actor" in provenance:
        raise ValueError("Reserved provenance key")
    _text(source_event_id, "source_event_id")
    _text(source_system, "source_system")
    if environment == "prod" and _sandbox_actor(actor):
        raise ValueError("SANDBOX attribution forbidden in PROD")
    if kind in ("admission", "rejection"):
        for key in ("submission_id", "qualification_id", "submission_date_published"):
            _text(provenance.get(key), key)
        _stamp(provenance["submission_date_published"])
        if kind == "admission" and source_event_at != provenance["submission_date_published"]:
            raise ValueError("Admission chronology must be submission.date_published")
        if kind == "rejection":
            if provenance.get("outcome") != "reject" or not isinstance(provenance.get("ever_admitted"), bool):
                raise ValueError("Rejection requires outcome and ever_admitted context")
    if kind in ("suspension", "resumption", "exclusion", "expiry"):
        for key in ("source_object", "source_id", "source_field"):
            _text(provenance.get(key), key)
        if provenance.get("time_evidence") not in ("source_transition", "expiry_boundary"):
            raise ValueError("Unproven transition time; record observation/gap instead")
        if kind != "expiry" and not source_event_at:
            raise ValueError("Exact transition timestamp required")
        if kind != "expiry" and provenance["time_evidence"] != "source_transition":
            raise ValueError("Not a source transition")
        if kind == "expiry" and provenance["time_evidence"] != "expiry_boundary":
            raise ValueError("Expiry requires source boundary")
        if not isinstance(provenance.get("supplier_level"), bool):
            raise ValueError("Explicit supplier-level scope required")
        if kind in ("exclusion", "expiry"):
            if provenance.get("supplier_level") is not True:
                raise ValueError("Partial termination belongs in inclusion history")
            before = provenance.get("effective_active_before")
            after = provenance.get("effective_active_after")
            if type(before) is not int or before < 1 or type(after) is not int or after != 0:
                raise ValueError("Last effective inclusion loss must be proven")
            _text(provenance.get("inclusion_id"), "inclusion_id")
    # Separate identities for kinds on one source object; preserve original ID.
    provenance["external_source_event_id"] = source_event_id
    event = v3.make_event(supplier_code=supplier_code, kind=kind,
        effective_date=effective_date, actor=actor, source_system=source_system,
        source_event_id=_json([kind, source_event_id]), environment=environment,
        snapshot=snapshot, provenance=provenance, source_event_at=source_event_at,
        recorded_at=recorded_at)
    return event


def _event_payload(event):
    return {k: v for k, v in event.items() if k != "recorded_at"}


def _row_event(row):
    # No dependency on connection.row_factory.
    (event_id, code, semantic, kind, day, stamp, recorded, actor_type, officer_id,
     display, environment, system, source_id, snapshot, provenance) = row
    prov = json.loads(provenance)
    # Stage 1 schema rows can be read without rewriting/enriching their provenance.
    actor = prov.pop("_recording_actor", None)
    if actor is None:
        actor = {"actor_type":actor_type, "actor_display":display}
        if officer_id:
            actor["officer_id"] = officer_id
    return dict(event_id=event_id, supplier_code=code, semantic_type=semantic,
        event_kind=kind, effective_date=day, source_event_at=stamp, recorded_at=recorded,
        actor=actor, environment=environment, source_system=system,
        source_event_id=source_id, snapshot=json.loads(snapshot),
        snapshot_hash=_identity_snapshot(json.loads(snapshot)), provenance=prov,
        schema_version=3)


def _identity_snapshot(snapshot):
    return hashlib.sha256(_json(snapshot).encode()).hexdigest()


_EVENT_SELECT = """SELECT event_id,supplier_code,semantic_type,event_kind,effective_date,
 source_event_at,recorded_at,actor_type,officer_id,actor_display,environment,
 source_system,source_event_id,factual_snapshot_json,provenance_json
 FROM supplier_evidence_events_v3"""


def append_event(con, **kwargs):
    """Validate and append one immutable event; True=new, False=exact replay."""
    event = prepare_event(**kwargs)
    with atomic(con):
        row = con.execute(_EVENT_SELECT + " WHERE event_id=?", (event["event_id"],)).fetchone()
        if row:
            if _event_payload(_row_event(row)) != _event_payload(event):
                raise SourceIdentityConflict(event["event_id"])
            return False
        actor, prov = event["actor"], dict(event["provenance"])
        prov["_recording_actor"] = actor
        con.execute("""INSERT INTO supplier_evidence_events_v3
          (event_id,supplier_code,semantic_type,event_kind,effective_date,source_event_at,
           recorded_at,actor_type,officer_id,actor_display,environment,source_system,
           source_event_id,submission_id,qualification_id,contract_id,factual_snapshot_json,
           snapshot_hash,provenance_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
          (event["event_id"],event["supplier_code"],event["semantic_type"],event["event_kind"],
           event["effective_date"],event["source_event_at"],event["recorded_at"],
           actor["actor_type"],actor.get("officer_id"),actor["actor_display"],
           event["environment"],event["source_system"],event["source_event_id"],
           prov.get("submission_id"),prov.get("qualification_id"),prov.get("contract_id"),
           _json(event["snapshot"]),event["snapshot_hash"],_json(prov)))
        return True


def append_inclusion(con, *, supplier_code, inclusion_id, kind, state_after,
                     effective_date, source_event_at, recorded_at, source_system,
                     source_event_id, actor, provenance, environment="prod"):
    """Inclusion history only. Never creates supplier lifecycle/verification."""
    expected = {"activation":"active", "suspension":"suspended", "resumption":"active",
                "termination":"inactive", "expiry":"inactive"}
    if expected.get(kind) != state_after:
        raise ValueError("Inclusion kind/state mismatch")
    _environment(environment)
    _validate_actor(actor)
    for value, field in ((supplier_code,"supplier_code"),(inclusion_id,"inclusion_id"),
                         (source_system,"source_system"),(source_event_id,"source_event_id")):
        _text(value, field)
    _stamp(recorded_at)
    v3.calendar_date(effective_date)
    if source_event_at:
        if _stamp(source_event_at).date().isoformat() != effective_date:
            raise ValueError("Inclusion timestamp/date mismatch")
    elif kind != "expiry":
        raise ValueError("Inclusion transition timestamp missing")
    for field in ("source_object", "source_id", "source_field"):
        _text(provenance.get(field), field)
    if provenance.get("time_evidence") != ("expiry_boundary" if kind == "expiry" else "source_transition"):
        raise ValueError("Unproven inclusion time")
    mode = provenance.get("automatic_manual")
    if mode not in ("automatic", "manual"):
        raise ValueError("Unproven automatic/manual attribution")
    if mode == "automatic":
        if actor.get("actor_type") != "system" or actor.get("actor_display") != v3.SYSTEM_ACTOR:
            raise ValueError("Automatic inclusion requires ЕСЗ")
    elif actor.get("actor_type") != "officer" or not actor.get("actor_display", "").strip():
        raise ValueError("Manual inclusion requires decision officer")
    if kind in ("suspension", "resumption", "expiry") and mode != "automatic":
        raise ValueError("System event requires automatic attribution")
    if environment == "prod" and _sandbox_actor(actor):
        raise ValueError("SANDBOX attribution forbidden in PROD")
    identity = _identity(environment,supplier_code,inclusion_id,kind,source_system,source_event_id)
    payload = dict(actor=actor, provenance=provenance)
    digest = _identity(effective_date,source_event_at,state_after,payload)
    with atomic(con):
        row = con.execute("SELECT payload_hash FROM supplier_inclusion_history_v3 WHERE event_id=?", (identity,)).fetchone()
        if row:
            if row[0] != digest:
                raise SourceIdentityConflict(identity)
            return False
        con.execute("""INSERT INTO supplier_inclusion_history_v3 VALUES
          (?,?,?,?,?,?,?,?,?,?,?,?,?)""", (identity,environment,supplier_code,inclusion_id,
          kind,state_after,effective_date,source_event_at,recorded_at,source_system,
          source_event_id,_json(payload),digest))
        return True


def observe_gap(con, *, environment, supplier_code, source_system, source_object,
                source_id, observed_at, payload, gaps):
    """Immutable incomplete observation; unknown date/actor stays empty.

    Caller explicitly distinguishes actionable gaps from history-only provenance.
    A verification cannot resolve provenance_review gaps by itself.
    """
    _environment(environment)
    for value in (supplier_code,source_system,source_object,source_id):
        _text(value, "observation identity")
    _stamp(observed_at)
    identity = _identity(environment,supplier_code,source_system,source_object,source_id)
    normalized = []
    for gap in gaps:
        g = dict(gap)
        for key in ("gap_type","gap_reason","recommended_action"):
            _text(g.get(key), key)
        if g.get("review_scope") not in ("active","history_only") or g.get("remediation") not in ("factual_verification","provenance_review"):
            raise ValueError("Explicit gap scope/remediation required")
        if (g["gap_type"] in PROVENANCE_GAP_TYPES or "ambigu" in g["gap_type"]
                or g["gap_type"].endswith("_date_unproven")) and g["remediation"] != "provenance_review":
            raise ValueError("Historical chronology/attribution is not proved by a new verification")
        g["known_event_date"] = g.get("known_event_date") or ""
        g["known_actor"] = g.get("known_actor") or ""
        g.setdefault("source", {})
        if g["known_event_date"]:
            v3.calendar_date(g["known_event_date"])
        if not isinstance(g["known_actor"], str):
            raise ValueError("Known actor must be text or blank")
        normalized.append(g)
    if not normalized or len({g["gap_type"] for g in normalized}) != len(normalized):
        raise ValueError("Observation requires distinct gaps")
    normalized.sort(key=lambda g:g["gap_type"])
    # Persist all supplied metadata in immutable observation, not just its hash.
    body = _json({"payload":payload,"gaps":normalized})
    digest = hashlib.sha256(body.encode()).hexdigest()
    with atomic(con):
        row = con.execute("SELECT payload_hash FROM supplier_evidence_observations_v3 WHERE observation_id=?", (identity,)).fetchone()
        if row:
            if row[0] != digest:
                raise SourceIdentityConflict(identity)
            return identity
        con.execute("INSERT INTO supplier_evidence_observations_v3 VALUES (?,?,?,?,?,?,?,?,?)",
            (identity,environment,supplier_code,source_system,source_object,source_id,observed_at,body,digest))
        for g in normalized:
            con.execute("INSERT INTO supplier_evidence_gaps_v3 VALUES (?,?,?,?,?,?,?,?,?,?)",
                (_identity(identity,g["gap_type"]),identity,g["gap_type"],g["gap_reason"],
                 g["review_scope"],g["remediation"],g["known_event_date"],g["known_actor"],
                 _json(g["source"]),g["recommended_action"]))
    return identity


def archive_legacy_gap(con, *, environment, supplier_code, gap_id, assessed_at,
                       assessment):
    """Explicit reviewed history-only disposition; never claims facts were proved."""
    _environment(environment)
    _stamp(assessed_at)
    for key in ("reason", "reviewed_by", "source_reference"):
        _text(assessment.get(key), key)
    if assessment.get("current_manual_action_required") is not False:
        raise ValueError("Remaining current manual action cannot be archived")
    with atomic(con):
        row = con.execute("""SELECT g.remediation FROM supplier_evidence_gaps_v3 g
          JOIN supplier_evidence_observations_v3 o ON o.observation_id=g.observation_id
          WHERE g.gap_id=? AND o.environment=? AND o.supplier_code=?""",
          (gap_id,environment,supplier_code)).fetchone()
        if not row or row[0] != "provenance_review":
            raise ValueError("Explicit legacy provenance gap required")
        previous = con.execute("SELECT disposition,assessment_json FROM supplier_evidence_gap_resolutions_v3 WHERE gap_id=?", (gap_id,)).fetchone()
        if previous:
            if tuple(previous) != ("history_only",_json(assessment)):
                raise SourceIdentityConflict(gap_id)
            return False
        con.execute("INSERT INTO supplier_evidence_gap_resolutions_v3 VALUES (?,?,?,?,?)",
                    (gap_id,"history_only",None,assessed_at,_json(assessment)))
        return True


def inclusion_states(con, *, environment, supplier_code, as_of):
    """Supplier-scoped inclusion chronology; identities never break time ties."""
    _environment(environment)
    v3.calendar_date(as_of)
    groups = {}
    for identity,inclusion_id,state,day,stamp in con.execute("""SELECT event_id,
      inclusion_id,state_after,effective_date,source_event_at FROM supplier_inclusion_history_v3
      WHERE environment=? AND supplier_code=? AND effective_date<=?""",
      (environment,supplier_code,as_of)):
        groups.setdefault(inclusion_id,[]).append(dict(event_id=identity,state=state,
            effective_date=day,source_event_at=stamp))
    states, gaps = [], []
    for inclusion_id, events in sorted(groups.items()):
        event, gap = v3._latest(events)
        if gap:
            gaps.append(dict(inclusion_id=inclusion_id,gap_type=gap))
        else:
            states.append(dict(supplier_code=supplier_code,inclusion_id=inclusion_id,
                               state=event["state"],source_event_id=event["event_id"]))
    return {"inclusions":states,"gaps":gaps,"complete":not gaps}


def reassess_verification_gaps(con, *, environment, supplier_code, event_id,
                              assessed_at, assessments):
    """Explicit per-gap reassessment, not blanket queue clearing on new check.

    assessments: {gap_id: {closed: bool, reason: str}}. Historical chronology /
    attribution cannot be closed by an EDR check; other active gaps remain.
    """
    _environment(environment)
    _stamp(assessed_at)
    with atomic(con):
        row = con.execute(_EVENT_SELECT + " WHERE event_id=? AND environment=? AND supplier_code=?",
                          (event_id,environment,supplier_code)).fetchone()
        if not row or row[2] != "verification":
            raise ValueError("Matching complete verification required")
        event = _row_event(row)
        for gap_id, assessment in assessments.items():
            if type(assessment.get("closed")) is not bool:
                raise ValueError("Explicit closure assessment required")
            _text(assessment.get("reason"), "assessment reason")
            g = con.execute("""SELECT g.review_scope,g.remediation,g.known_event_date
              FROM supplier_evidence_gaps_v3 g JOIN supplier_evidence_observations_v3 o
              ON o.observation_id=g.observation_id WHERE g.gap_id=? AND o.environment=?
              AND o.supplier_code=?""", (gap_id,environment,supplier_code)).fetchone()
            if not g:
                raise ValueError("Unknown/scope-mismatched gap")
            if not assessment["closed"]:
                continue
            if g[0] != "active" or g[1] != "factual_verification":
                raise ValueError("Verification cannot prove historical provenance")
            if g[2] and event["effective_date"] < g[2]:
                raise ValueError("Older verification cannot close newer evidence gap")
            previous = con.execute("SELECT evidence_event_id,assessment_json FROM supplier_evidence_gap_resolutions_v3 WHERE gap_id=?", (gap_id,)).fetchone()
            if previous:
                if tuple(previous) != (event_id,_json(assessment)):
                    raise SourceIdentityConflict(gap_id)
                continue
            con.execute("INSERT INTO supplier_evidence_gap_resolutions_v3 VALUES (?,?,?,?,?)",
                (gap_id,"resolved",event_id,assessed_at,_json(assessment)))


def update_projection(con, *, environment, supplier_code, as_of, rebuilt_at,
                      inclusions, ever_admitted=False, last_application=None):
    """Targeted cache only. Caller supplies proven inclusion context; no scanning.

    No events are created by a projection update; legacy tables never touched.
    """
    _environment(environment)
    _stamp(rebuilt_at)
    if any(i.get("supplier_code", supplier_code) != supplier_code for i in inclusions):
        raise ValueError("Cross-supplier inclusion context")
    with atomic(con):
        events = [_row_event(r) for r in con.execute(_EVENT_SELECT +
            " WHERE environment=? AND supplier_code=? AND effective_date<=?",
            (environment,supplier_code,as_of))]
        projection = v3.resolve(supplier_code=supplier_code, events=events,
            inclusions=inclusions, as_of=as_of, ever_admitted=ever_admitted,
            last_application=last_application)
        current = projection["current_event"]
        verification = projection["last_verification_event"]
        # History belongs in the ledger, not duplicated in every cache/export row.
        cached_projection = {k:v for k,v in projection.items() if k != "verification_history"}
        con.execute("""INSERT INTO supplier_evidence_current_v3 VALUES (?,?,?,?,?,?,?)
          ON CONFLICT(environment,supplier_code) DO UPDATE SET
          current_event_id=excluded.current_event_id,
          last_verification_event_id=excluded.last_verification_event_id,
          projection_json=excluded.projection_json,as_of_date=excluded.as_of_date,
          rebuilt_at=excluded.rebuilt_at""", (environment,supplier_code,
          current["event_id"] if current else None,verification["event_id"] if verification else None,
          _json(cached_projection),as_of,rebuilt_at))
        return projection


def append_and_project(con, *, event, projection_context):
    """Atomic event append + targeted projection; caller commits or rolls back."""
    if (event["supplier_code"],event.get("environment","prod")) != (
        projection_context["supplier_code"],projection_context["environment"]):
        raise ValueError("Event/projection scope mismatch")
    with atomic(con):
        inserted = append_event(con, **event)
        projection = update_projection(con, **projection_context)
        return {"inserted":inserted,"projection":projection}


MANUAL_REVIEW_COLUMNS = ("supplier_code","supplier_name","prozorro_status",
    "current_edr_projection","gap_types","gap_reasons","known_event_dates",
    "known_actors_sources","last_verification_date","last_verification_officer",
    "source_objects_ids","recommended_manual_action")


def manual_review_dataset(con, *, environment, after_code="", limit=100, supplier_names=None):
    """Read-only keyset page; one supplier per row, all unresolved active gaps.

    No automatic history-to-active promotion, no events, no projection rebuild.
    Values not present in the evidence/cache remain blank.
    """
    _environment(environment)
    if type(limit) is not int or not 1 <= limit <= 500:
        raise ValueError("Page size must be 1..500")
    names = supplier_names or {}
    codes = [r[0] for r in con.execute("""SELECT DISTINCT o.supplier_code
      FROM supplier_evidence_observations_v3 o JOIN supplier_evidence_gaps_v3 g
      ON g.observation_id=o.observation_id LEFT JOIN supplier_evidence_gap_resolutions_v3 x
      ON x.gap_id=g.gap_id WHERE o.environment=? AND o.supplier_code>?
      AND g.review_scope='active' AND x.gap_id IS NULL ORDER BY o.supplier_code LIMIT ?""",
      (environment,after_code,limit))]
    rows = []
    for code in codes:
        gaps = []
        for r in con.execute("""SELECT g.gap_id,g.gap_type,g.gap_reason,g.known_event_date,
          g.known_actor,g.source_json,g.recommended_action,o.source_system,o.source_object,o.source_id
          FROM supplier_evidence_gaps_v3 g JOIN supplier_evidence_observations_v3 o
          ON o.observation_id=g.observation_id LEFT JOIN supplier_evidence_gap_resolutions_v3 x
          ON x.gap_id=g.gap_id WHERE o.environment=? AND o.supplier_code=?
          AND g.review_scope='active' AND x.gap_id IS NULL ORDER BY g.gap_id""", (environment,code)):
            gaps.append(dict(gap_id=r[0],gap_type=r[1],gap_reason=r[2],known_event_date=r[3],
                known_actor=r[4],source=json.loads(r[5]),recommended_manual_action=r[6],
                source_system=r[7],source_object=r[8],source_id=r[9]))
        cached = con.execute("SELECT projection_json FROM supplier_evidence_current_v3 WHERE environment=? AND supplier_code=?",
                             (environment,code)).fetchone()
        p = json.loads(cached[0]) if cached else {}
        rows.append(dict(supplier_code=code,supplier_name=names.get(code) or p.get("factual_snapshot",{}).get("full_name") or "",
            prozorro_status=p.get("prozorro_status") or "",current_edr_projection=p.get("edr_status_current") or "",
            gap_types=sorted({g["gap_type"] for g in gaps}),gap_reasons=[g["gap_reason"] for g in gaps],
            known_event_dates=[g["known_event_date"] for g in gaps],
            known_actors_sources=[dict(actor=g["known_actor"],source=g["source_system"]) for g in gaps],
            last_verification_date=p.get("last_verification_date") or "",
            last_verification_officer=p.get("last_verification_officer") or "",
            source_objects_ids=[dict(object=g["source_object"],id=g["source_id"],details=g["source"]) for g in gaps],
            recommended_manual_action=list(dict.fromkeys(g["recommended_manual_action"] for g in gaps)),gaps=gaps))
    return {"rows":rows,"next_after_code":codes[-1] if codes else None,
            "read_only":True,"historical_gap_strategy":"FLAG → MANUAL UO REVIEW → GOOGLE → NORMAL SYNC"}


def manual_review_csv(dataset):
    """Export to a returned string only; no files, Google calls or writes.

    CSV cells are spreadsheet-formula safe; JSON dataset retains exact values.
    """
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(MANUAL_REVIEW_COLUMNS)
    for row in dataset["rows"]:
        values = []
        for key in MANUAL_REVIEW_COLUMNS:
            value = row.get(key, "")
            value = _json(value) if isinstance(value,(dict,list)) else str(value)
            if value.lstrip().startswith(("=","+","-","@")) or value.startswith(("\t","\r","\n")):
                value = "'" + value
            values.append(value)
        writer.writerow(values)
    return stream.getvalue()
