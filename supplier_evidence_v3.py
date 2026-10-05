"""Stage-1 pure contract-v3 resolver. No database, clock, server or network I/O.

Callers supply inclusion state, immutable evidence and an explicit as-of date.
The legacy ledger is intentionally NOT automatically reclassified or backfilled.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime
import hashlib
import json

SANDBOX_OFFICER = "Тестова УО SANDBOX"
SYSTEM_ACTOR = "ЕСЗ"
KINDS = {"admission": "verification", "edr_check": "verification",
         "rejection": "lifecycle", "suspension": "lifecycle",
         "resumption": "lifecycle", "exclusion": "lifecycle", "expiry": "lifecycle"}


def calendar_date(value: str) -> str:
    """No guessed calendar dates and no wall-clock fallback."""
    return date.fromisoformat(value).isoformat()


def attribution(*, provenance_kind: str, officer: str = "",
                environment: str = "prod", canonical_sandbox_officer: str = "") -> dict:
    if environment not in {"prod", "sandbox"}:
        raise ValueError("Unknown environment")
    if provenance_kind in {"suspension", "resumption", "expiry"}:
        return {"actor_type": "system", "actor_display": SYSTEM_ACTOR,
                "officer_source": "prozorro"}
    if provenance_kind not in {"admission", "edr_check", "exclusion", "rejection"}:
        return {"gap": "insufficient_attribution_provenance"}
    if officer.strip():
        return {"actor_type": "officer", "actor_display": officer.strip(),
                "officer_source": "application_protocol" if provenance_kind == "admission"
                else "source_decision"}
    if environment == "sandbox" and canonical_sandbox_officer == SANDBOX_OFFICER:
        return {"actor_type": "officer", "actor_display": SANDBOX_OFFICER,
                "officer_source": "sandbox_fallback"}
    return {"gap": "missing_officer"}


def make_event(*, supplier_code: str, kind: str, effective_date: str,
               actor: dict, source_system: str, source_event_id: str,
               environment: str = "prod", snapshot: dict | None = None,
               provenance: dict | None = None, source_event_at: str | None = None,
               recorded_at: str = "") -> dict:
    """Identity is source-event based, NEVER factual hash or day/officer based."""
    if kind not in KINDS or environment not in {"prod", "sandbox"}:
        raise ValueError("Unknown event kind/environment")
    if not all(str(v).strip() for v in (supplier_code, source_system, source_event_id)):
        raise ValueError("Missing source identity")
    day = calendar_date(effective_date)
    if source_event_at:
        dt = datetime.fromisoformat(source_event_at)
        if dt.tzinfo is None or dt.date().isoformat() != day:
            raise ValueError("Source timestamp must be zoned and match business date")
    if actor.get("gap") or actor.get("actor_type") not in {"officer", "system"} or not actor.get("actor_display", "").strip():
        raise ValueError("Missing attributable actor")
    if KINDS[kind] == "verification" and actor["actor_type"] != "officer":
        raise ValueError("Verification requires officer")
    if kind in {"suspension", "resumption", "expiry"} and (
            actor["actor_type"] != "system" or actor["actor_display"] != SYSTEM_ACTOR):
        raise ValueError("Automatic lifecycle requires ЕСЗ")
    if kind in {"exclusion", "rejection"} and actor["actor_type"] != "officer":
        raise ValueError("Manual decision requires officer")
    facts = deepcopy(snapshot or {})
    if kind == "admission":
        facts["edr_status"] = "Зареєстровано"
    if KINDS[kind] == "verification" and facts.get("edr_status") in {"Неактуально", "" , None}:
        raise ValueError("Verification requires factual EDR status")
    identity = [environment, source_system, source_event_id, supplier_code, KINDS[kind]]
    return {"event_id": hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode()).hexdigest(),
            "supplier_code": supplier_code, "semantic_type": KINDS[kind], "event_kind": kind,
            "effective_date": day, "source_event_at": source_event_at, "recorded_at": recorded_at,
            "environment": environment, "source_system": source_system,
            "source_event_id": source_event_id, "actor": deepcopy(actor),
            "snapshot": facts,
            "snapshot_hash": hashlib.sha256(json.dumps(facts, ensure_ascii=False,
                sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
            "schema_version": 3, "provenance": deepcopy(provenance or {})}


def admission_event(*, submission: dict, actor: dict, environment: str = "prod") -> dict:
    """Explicit admitted application: never use qualification/protocol date."""
    if submission.get("decision") != "admit":
        raise ValueError("Not an admitted application")
    stamp = submission["date_published"]
    return make_event(supplier_code=submission["supplier_code"], kind="admission",
        effective_date=calendar_date(stamp[:10]), actor=actor,
        source_system="application", source_event_id=submission["id"],
        source_event_at=stamp if "T" in stamp else None, environment=environment,
        provenance={"submission_id": submission["id"], "date_source": "submission.date_published"})


def _latest(events: list[dict]) -> tuple[dict | None, str | None]:
    if not events:
        return None, None
    day = max(e["effective_date"] for e in events)
    same_day = [e for e in events if e["effective_date"] == day]
    if len(same_day) == 1:
        return same_day[0], None
    if any(not e.get("source_event_at") for e in same_day):
        return None, "ambiguous_same_day_events"
    stamps = [(datetime.fromisoformat(e["source_event_at"]), e) for e in same_day]
    latest = max(t for t, _ in stamps)
    winners = [e for t, e in stamps if t == latest]
    return (winners[0], None) if len(winners) == 1 else (None, "ambiguous_same_timestamp")


def freshness(*, monitored: bool, verification_date: str | None, as_of: str) -> dict:
    today = date.fromisoformat(calendar_date(as_of))
    if not monitored:
        return {"bucket": "not_current", "marker": "Неактуально", "age_days": None}
    if not verification_date:
        return {"bucket": "not_checked", "marker": "Не перевірено", "age_days": None}
    age = (today - date.fromisoformat(calendar_date(verification_date))).days
    if age < 0:
        return {"bucket": "gap", "marker": "future_verification", "age_days": None}
    bucket, marker = ("lt30", "<30") if age < 30 else ("gt30", ">30") if age < 60 else (
        "gt60", ">60") if age < 90 else ("gt90", ">90")
    return {"bucket": bucket, "marker": marker, "age_days": age}


def resolve(*, supplier_code: str, events: list[dict], inclusions: list[dict],
            as_of: str, ever_admitted: bool = False,
            last_application: dict | None = None) -> dict:
    """Input inclusions carry effective active/suspended/inactive state as-of.

    Adapters (stage 2+) must prove inclusion dates/state, not infer from profiles.
    Status changes affecting only one still-active supplier inclusion do not
    replace supplier-level current monitoring evidence.
    """
    calendar_date(as_of)
    if any(i.get("state") not in {"active", "suspended", "inactive"} for i in inclusions):
        raise ValueError("Unresolved inclusion state")
    unique, gaps = {}, []
    for raw in events:
        if raw["supplier_code"] != supplier_code:
            continue
        e = deepcopy(raw)
        if e["effective_date"] > as_of:
            continue
        if e["event_id"] in unique:
            # Re-observation time is not evidence identity. Conflicting business
            # content for the same source ID is not silently accepted.
            before = {k: val for k, val in unique[e["event_id"]].items() if k != "recorded_at"}
            after = {k: val for k, val in e.items() if k != "recorded_at"}
            if before != after:
                gaps.append("conflicting_source_event_identity")
        unique[e["event_id"]] = e
    evidence = list(unique.values())
    admitted = ever_admitted or any(e["event_kind"] == "admission" for e in evidence)
    if any(i["state"] == "active" for i in inclusions):
        status, monitored = "Активний", True
    elif any(i["state"] == "suspended" for i in inclusions):
        status, monitored = "Припинений", True
    else:
        status, monitored = ("Неактивний" if admitted else "Ще не в реєстрі"), False
    # A suspended/active inclusion also proves historical admission.
    if monitored:
        admitted = True
    verifications = [e for e in evidence if e["semantic_type"] == "verification"]
    verification, gap = _latest(verifications)
    if gap:
        gaps.append("verification:" + gap)
    lifecycle_kinds = ({"suspension"} if status == "Припинений" else
        {"resumption"} if status == "Активний" else
        {"exclusion", "expiry"} if status == "Неактивний" else {"rejection"})
    lifecycle = [e for e in evidence if e["event_kind"] in lifecycle_kinds
                 and e["provenance"].get("supplier_level", False)]
    current_candidates = verifications + lifecycle if monitored else lifecycle
    current, gap = _latest(current_candidates)
    if gap:
        gaps.append("current:" + gap)
    if gaps:
        current = None  # Do not falsely claim a matched, unambiguous projection.
    factual = deepcopy(verification["snapshot"]) if verification else {}
    if monitored and not verification:
        gaps.append("missing_verification_evidence")
    if not monitored and status == "Неактивний" and not current:
        gaps.append("missing_lifecycle_evidence")
    return {"supplier_code": supplier_code, "ever_admitted": admitted,
        "prozorro_status": status, "monitoring_eligible": monitored,
        "edr_status_current": factual.get("edr_status") if monitored else "Неактуально",
        "factual_snapshot": factual,
        "current_event": deepcopy(current),
        "current_event_type": current["semantic_type"] if current else None,
        "current_event_date": current["effective_date"] if current else None,
        "current_event_actor": deepcopy(current["actor"]) if current else None,
        "current_event_provenance": deepcopy(current["provenance"]) if current else None,
        "last_verification_event": deepcopy(verification),
        "last_verification_date": verification["effective_date"] if verification else None,
        "last_verification_officer": verification["actor"]["actor_display"] if verification else None,
        "last_verification_provenance": deepcopy(verification["provenance"]) if verification else None,
        "visible_date": current["effective_date"] if current and status != "Ще не в реєстрі" else None,
        "visible_actor": current["actor"]["actor_display"] if current else None,
        "last_application": deepcopy(last_application),
        "freshness": freshness(monitored=monitored,
            verification_date=verification["effective_date"] if verification else None, as_of=as_of),
        "verification_history": deepcopy(verifications), "gaps": gaps}


def normalization_proposal(*, observation_id: str, provenance_kind: str,
                           historical_date: str, officer: str = "",
                           canonical_sandbox_officer: str = "") -> dict:
    """Pure proposal only: no blanket date+blank-officer attribution or events."""
    if not observation_id.strip():
        return {"gap": "missing_historical_identity"}
    if provenance_kind not in {"admission", "exclusion", "expiry", "suspension", "resumption"}:
        return {"gap": "insufficient_attribution_provenance"}
    actor = attribution(provenance_kind=provenance_kind, officer=officer,
        environment="sandbox", canonical_sandbox_officer=canonical_sandbox_officer)
    if actor.get("gap"):
        return actor
    return {"historical_observation_id": observation_id,
        "effective_date": calendar_date(historical_date), "actor": actor,
        "creates_verification_event": False, "proposal_only": True}
