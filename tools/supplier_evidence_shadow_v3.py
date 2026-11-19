"""Read-only stage-2 shadow: no server import, migration, storage or network.

Run --db PATH --as-of YYYY-MM-DD. Live execution requires the known sandbox ID.
This adapter reconstructs ephemeral evidence, NEVER materializes it in SQLite.
"""
from __future__ import annotations
import argparse
from collections import defaultdict
from datetime import datetime
import json
import os
from pathlib import Path
import sqlite3
import sys
from time import perf_counter
from urllib.parse import quote

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import supplier_evidence_v3 as v3
import edr_sync_v2 as old

CONTROLS = "2077003493 2886810864 2981518432 3385014935 3602006515 3618208369 3624813159 30795712 39984849 41141768 45547692 46120124".split()
NINE = "45054758 45088216 45101776 32800996 33860155 23098585 01756131 38229721 45431261".split()
SANDBOX_ID = "srv-dalfd77f3r2c7392uub0"
MAX_COHORT_CODES = 37  # 12 + 1 + 9 + 3*5; duplicates only reduce this.
MAX_SOURCE_ROWS = 2000
MAX_SOURCE_BYTES = 2 * 1024 * 1024  # per supplier; fail, NEVER truncate evidence.


def decoded(value):
    try:
        return json.loads(value or "{}")
    except (ValueError, TypeError):
        return {}


def read_bundle(con, codes):
    """All business reads are restricted to the requested literal codes."""
    started = perf_counter()
    codes = list(dict.fromkeys(codes))
    if len(codes) > MAX_COHORT_CODES:
        raise ValueError("cohort_limit_exceeded: full population is Stage 2B only")
    if not codes:
        return {"codes": [], "applications": [], "contracts": [], "ledger": [],
                "profiles": [], "db_read_ms": 0}
    result = {"codes": codes, "applications": [], "contracts": [], "ledger": [], "profiles": []}
    # Stay below the conservative SQLite parameter limit, never N+1 supplier reads.
    for pos in range(0, len(codes), 400):
        batch = codes[pos:pos+400]
        marks = ",".join("?" for _ in batch)
        statements = {
            "applications": f"""SELECT s.id,s.supplier_code,s.date_published,
              s.supplier_name,q.status,q.id qualification_id,af.protocol_officer,
              af.protocol_date,q.decision_date
              FROM submissions s LEFT JOIN application_fields af ON af.submission_id=s.id
              LEFT JOIN qualifications q ON q.id=COALESCE((SELECT qx.id FROM qualifications qx
                WHERE qx.submission_id=s.id ORDER BY
                CASE qx.status WHEN 'active' THEN 3 WHEN 'unsuccessful' THEN 2 ELSE 1 END DESC,
                COALESCE(NULLIF(qx.decision_date,''),qx.synced_at) DESC,qx.id DESC LIMIT 1),s.qualification_id)
              WHERE s.supplier_code IN ({marks})""",
            "contracts": f"""SELECT rc.id,rc.supplier_code,rc.status,rc.milestones_json,
              f.status framework_status,
              json_object('qualificationPeriod',json_object('endDate',
                json_extract(f.raw_json,'$.qualificationPeriod.endDate'))) framework_raw_json,
              q.decision_date qualification_date
              FROM registry_contracts rc LEFT JOIN frameworks f ON f.id=rc.framework_id
              LEFT JOIN qualifications q ON q.id=rc.qualification_id
              WHERE rc.supplier_code IN ({marks})""",
            "ledger": f"SELECT id,supplier_code,event_type,occurred_at,officer,source,snapshot_json,source_sheet,source_row,snapshot_hash FROM supplier_edr_verification_events WHERE supplier_code IN ({marks})",
            "profiles": f"SELECT supplier_code,edr_status FROM supplier_edr_profiles WHERE supplier_code IN ({marks})",
        }
        for key, sql in statements.items():
            # Check projected byte sizes IN SQLite before fetching any large JSON.
            sizes = [r[0] for r in con.execute("SELECT * FROM ("+sql+") LIMIT 0", batch).description]
            size_expr = "+".join('COALESCE(length(CAST("'+name+'" AS BLOB)),0)' for name in sizes)
            count, size = con.execute("SELECT COUNT(*),COALESCE(SUM("+size_expr+"),0) FROM ("+sql+")", batch).fetchone()
            if count > MAX_SOURCE_ROWS or size > MAX_SOURCE_BYTES:
                raise ValueError("source_budget_exceeded:"+key+"; evidence not truncated")
            result[key].extend(dict(r) for r in con.execute(sql, batch))
    result["db_read_ms"] = round((perf_counter()-started)*1000, 3)
    return result


def evaluate(bundle, as_of, canonical_officer="", lifecycle_officers=None):
    started = perf_counter()
    groups = {key: defaultdict(list) for key in ("applications", "contracts", "ledger", "profiles")}
    for key in groups:
        for row in bundle[key]:
            groups[key][row["supplier_code"]].append(row)
    result = []
    for code in bundle["codes"]:
        events, gaps, inclusions, termination_dates = [], [], [], []
        apps = groups["applications"][code]
        admitted = [a for a in apps if a["status"] == "active"]
        for a in apps:
            if a["status"] not in {"active", "unsuccessful"}:
                continue
            kind = "admission" if a["status"] == "active" else "rejection"
            actor = v3.attribution(provenance_kind=kind, officer=a.get("protocol_officer") or "",
                environment="sandbox", canonical_sandbox_officer=canonical_officer)
            try:
                if kind == "admission":
                    events.append(v3.admission_event(submission={**a,"decision":"admit"},actor=actor,environment="sandbox"))
                else:
                    # Rejection decision chronology uses decision date, NOT a check date.
                    stamp = a.get("protocol_date") or a.get("decision_date")
                    day = old.normalized_date(stamp)
                    events.append(v3.make_event(supplier_code=code,kind=kind,effective_date=day,
                        actor=actor,environment="sandbox",source_system="application",
                        source_event_id=a["id"],provenance={"supplier_level":True,"submission_id":a["id"]}))
            except (ValueError, KeyError) as exc:
                gaps.append({"source":a["id"],"gap":str(exc)})
        # Factual ledger event must have its own snapshot; I/L-only evidence can
        # inherit a proven preceding admission snapshot, but not a stale profile.
        for raw in sorted(groups["ledger"][code],key=lambda e:old.normalized_date(e["occurred_at"])):
            if raw["event_type"] not in {"manual_edr","google_clarity","legacy_google_registry"}:
                gaps.append({"source":raw["id"],"gap":"unmapped_legacy_event_type"}); continue
            snap = decoded(raw.get("snapshot_json"))
            day = old.normalized_date(raw["occurred_at"])
            if not snap.get("edr_status"):
                prior = [e for e in events if e["semantic_type"]=="verification" and e["effective_date"]<day]
                previous, ambiguity = v3._latest(prior)
                if previous and not ambiguity:
                    snap = {**previous["snapshot"],**snap}
                    snap["edr_status"] = previous["snapshot"]["edr_status"]
                    snap["shadow_factual_snapshot_source_event_id"] = previous["event_id"]
                else:
                    gaps.append({"source":raw["id"],"gap":"missing_factual_snapshot"}); continue
            actor = v3.attribution(provenance_kind="edr_check",officer=raw.get("officer") or "",
                environment="sandbox",canonical_sandbox_officer="")  # Never blanket-normalize.
            try:
                events.append(v3.make_event(supplier_code=code,kind="edr_check",effective_date=day,
                    actor=actor,environment="sandbox",snapshot=snap,source_system=raw["source"],
                    source_event_id="legacy-ledger:"+str(raw["id"]),
                    provenance={"legacy_event_id":raw["id"],"legacy_type":raw["event_type"],
                        "source_sheet":raw.get("source_sheet"),"source_row":raw.get("source_row"),
                        "snapshot_hash":raw.get("snapshot_hash")},
                    source_event_at=snap.get("source_event_at")))
            except ValueError as exc:
                gaps.append({"source":raw["id"],"gap":str(exc)})
        for rc in groups["contracts"][code]:
            frame = decoded(rc.get("framework_raw_json"))
            end = (frame.get("qualificationPeriod") or {}).get("endDate")
            expired = bool(end and old.normalized_date(end)<as_of)
            active = rc["status"]=="active" and rc.get("framework_status")=="active" and not expired
            suspended = rc["status"]=="suspended" and rc.get("framework_status")=="active" and not expired
            inclusions.append({"state":"active" if active else "suspended" if suspended else "inactive"})
            milestones = decoded(rc.get("milestones_json") or "[]")
            if rc["status"]=="terminated":
                met = [m for m in milestones if m.get("type")=="activation" and m.get("status")=="met" and m.get("dateMet")]
                if len(met)==1:
                    termination_dates.append((met[0]["dateMet"],rc["id"],"exclusion",met[0]))
                else:gaps.append({"source":rc["id"],"gap":"termination_date_unproven"})
            elif expired and end:
                # Current predicate includes end calendar day; don't silently
                # pick midnight/end-of-day convention as factual event time.
                gaps.append({"source":rc["id"],"gap":"expiry_boundary_requires_explicit_source_convention","end":end})
            elif suspended:
                ban = [m for m in milestones if m.get("type")=="ban" and m.get("dateMet")]
                if len(ban)==1:
                    stamp=ban[0]["dateMet"]
                    events.append(v3.make_event(supplier_code=code,kind="suspension",
                        effective_date=stamp[:10],source_event_at=stamp,actor=v3.attribution(provenance_kind="suspension"),
                        environment="sandbox",source_system="prozorro",source_event_id=rc["id"]+":ban:"+stamp,
                        provenance={"supplier_level":not any(x["state"]=="active" for x in inclusions),"contract_id":rc["id"]}))
                else:gaps.append({"source":rc["id"],"gap":"suspension_date_unproven"})
        # Supplier-level exclusion must account for ALL inclusions, not just
        # the latest contract. Missing terminal chronology forbids fabrication.
        if termination_dates and not any(i["state"] in {"active","suspended"} for i in inclusions):
            if len(termination_dates)==len(inclusions):
                stamp,contract_id,kind,milestone=max(termination_dates,key=lambda t:datetime.fromisoformat(t[0]))
                officer=(lifecycle_officers or {}).get(code,"")
                actor=v3.attribution(provenance_kind=kind,officer=officer,environment="sandbox",canonical_sandbox_officer=canonical_officer)
                events.append(v3.make_event(supplier_code=code,kind=kind,effective_date=stamp[:10],
                    source_event_at=stamp,actor=actor,source_system="prozorro",environment="sandbox",
                    source_event_id=contract_id+":terminated:"+stamp,
                    provenance={"supplier_level":True,"contract_id":contract_id,"milestone":milestone,
                        "attribution_policy":"specific officer else canonical SANDBOX; stage-2 shadow only"}))
            else:gaps.append({"gap":"incomplete_last_inclusion_chronology"})
        last_app=max(apps,key=lambda a:(a.get("date_published") or "",a["id"])) if apps else None
        # Status-change on one suspended inclusion must not override another
        # active inclusion, irrespective of SQL row iteration order.
        if any(i["state"]=="active" for i in inclusions):
            for e in events:
                if e["event_kind"]=="suspension":
                    e["provenance"]["supplier_level"]=False
        projected=v3.resolve(supplier_code=code,events=events,inclusions=inclusions,as_of=as_of,
            ever_admitted=bool(admitted or groups["contracts"][code]),
            last_application={"id":last_app["id"],"date":last_app["date_published"][:10]} if last_app else None)
        # Strip repeated factual snapshots in presentation, retain history provenance.
        def summary(e):
            return {k:e[k] for k in ("event_id","event_kind","effective_date",
                "source_event_at","source_event_id","actor","provenance")} if e else None
        projected["current_event"]=summary(projected["current_event"])
        projected["last_verification_event"]=summary(projected["last_verification_event"])
        projected["verification_history"]=[summary(e) for e in projected["verification_history"]]
        result.append({"supplier_code":code,"stored_profile_status":(groups["profiles"][code] or [{}])[0].get("edr_status"),
            "v3":projected,"adapter_gaps":gaps,"inclusion_count":len(inclusions),
            "reconstructed_admissions":[summary(e) for e in events if e["event_kind"]=="admission"]})
    return {"rows":result,"resolver_ms":round((perf_counter()-started)*1000,3),"db_read_ms":bundle["db_read_ms"]}


def stage_2a(con, cohorts, as_of, canonical=""):
    """Bounded control-only run. Source and full projection live for ONE code."""
    codes = list(dict.fromkeys(code for values in cohorts.values() for code in values))
    if len(codes) > MAX_COHORT_CODES:
        raise ValueError("cohort_limit_exceeded")
    for name in ("suspended", "never_admitted", "multi_inclusion"):
        if len(cohorts.get(name, [])) > 5:
            raise ValueError("sample_limit_exceeded:"+name)
    rows, db_ms, resolver_ms = [], 0.0, 0.0
    for code in codes:
        bundle = read_bundle(con, [code])
        result = evaluate(bundle, as_of, canonical)
        db_ms += result["db_read_ms"]; resolver_ms += result["resolver_ms"]
        row = result["rows"][0]; projection = row["v3"]
        history = projection.pop("verification_history")
        row["verification_count"] = len(history)
        row["ledger_8627_preserved"] = any(e["provenance"].get("legacy_event_id")==8627 for e in history)
        row["clarity_20261005_present"] = any(e["event_kind"]=="edr_check" and e["effective_date"]=="2026-10-05" and e["actor"]["actor_display"]=="Світлана НАМЯСЕНКО" for e in history)
        admissions = row.pop("reconstructed_admissions")
        row["admission_count"] = len(admissions)
        # Stable identity deduplicates replay; NEVER breaks chronology ties.
        unique_admissions = {e["event_id"]:e for e in admissions}
        row["latest_admission"], ambiguity = v3._latest(list(unique_admissions.values()))
        row["latest_admission_ambiguity"] = ambiguity
        if ambiguity:
            row["adapter_gaps"].append({"gap":ambiguity,"selection":"latest_admission"})
        # No full factual payload/history/old projection retained in output.
        row["v3"] = {k: projection[k] for k in (
            "prozorro_status", "monitoring_eligible", "edr_status_current", "visible_date",
            "visible_actor", "current_event", "last_verification_event",
            "last_verification_date", "last_verification_officer", "freshness", "gaps")}
        row["gap_counts"] = {"adapter":len(row["adapter_gaps"]),"resolver":len(row["v3"]["gaps"])}
        row["adapter_gaps"] = row["adapter_gaps"][:10]
        row["v3"]["gaps"] = row["v3"]["gaps"][:10]
        for event in (row["latest_admission"],row["v3"]["current_event"],row["v3"]["last_verification_event"]):
            if event:
                event["provenance"] = {k:v for k,v in event["provenance"].items() if k != "milestone"}
        rows.append(row)
        del history, admissions, projection, result, bundle
    return {"stage":"2A", "codes":codes, "cohorts":cohorts, "rows":rows,
        "aggregates":{"suppliers":len(rows),"with_gaps":sum(any(r["gap_counts"].values()) for r in rows)},
        "timing_ms":{"db_read":round(db_ms,3),"resolver":round(resolver_ms,3)},
        "old_projection_calls":0,"full_population_run":False}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--db",required=True)
    parser.add_argument("--as-of",required=True)
    args=parser.parse_args()
    if os.getenv("RENDER_SERVICE_ID")!=SANDBOX_ID:
        raise SystemExit("STOP: live shadow requires confirmed SANDBOX service")
    c=sqlite3.connect("file:"+quote(str(Path(args.db).resolve()),safe="/:\\")+"?mode=ro",uri=True)
    c.row_factory=sqlite3.Row;c.execute("PRAGMA query_only=ON")
    initial_version=c.execute("PRAGMA data_version").fetchone()[0]
    old.register_verification_sql_functions(c)
    # Reject write opcodes even if accidentally introduced later.
    reads={sqlite3.SQLITE_SELECT,sqlite3.SQLITE_READ,sqlite3.SQLITE_FUNCTION,sqlite3.SQLITE_RECURSIVE}
    def authorize(action,arg1,arg2,*_):
        if action in reads or (action==sqlite3.SQLITE_PRAGMA and arg1 in {"table_info","data_version"}):
            return sqlite3.SQLITE_OK
        return sqlite3.SQLITE_DENY
    c.set_authorizer(authorize)
    # Lookup account without old.canonical_sandbox_officer(), which uses PRAGMA.
    account=c.execute("SELECT o.full_name FROM auth_users u JOIN authorized_officers o ON o.id=u.officer_id WHERE u.username='sandbox.officer' AND u.active=1 AND u.role='officer' AND o.active=1 AND o.role='УО'").fetchone()
    canonical=account[0] if account and account[0]==v3.SANDBOX_OFFICER else ""
    cohorts={"twelve":CONTROLS,"33345054":["33345054"],"nine":NINE}
    cohorts["suspended"]= [r[0] for r in c.execute("SELECT DISTINCT supplier_code FROM registry_contracts WHERE status='suspended' ORDER BY supplier_code LIMIT 5")]
    cohorts["never_admitted"]=[r[0] for r in c.execute("SELECT s.supplier_code FROM submissions s JOIN qualifications q ON q.id=s.qualification_id GROUP BY s.supplier_code HAVING SUM(q.status='active')=0 AND SUM(q.status='unsuccessful')>0 ORDER BY s.supplier_code LIMIT 5")]
    cohorts["multi_inclusion"]=[r[0] for r in c.execute("SELECT supplier_code FROM registry_contracts GROUP BY supplier_code HAVING COUNT(*)>1 ORDER BY (SUM(status='active')>0 AND SUM(status='terminated')>0) DESC,supplier_code LIMIT 5")]
    output={"read_only":True,"as_of":args.as_of,"DB_WRITES":0,"SYNC_RUN":"NO","APPLY_RUN":"NO"}
    output["targeted_query_plans"]={t:[list(r) for r in c.execute(
        "EXPLAIN QUERY PLAN SELECT * FROM "+t+" WHERE supplier_code=?",(CONTROLS[0],))]
        for t in ("submissions","registry_contracts","supplier_edr_verification_events","supplier_edr_profiles")}
    output.update(stage_2a(c,cohorts,args.as_of,canonical))
    expected={"2077003493":("2026-09-18","Тетяна ФЕДЧЕНКО"),"2886810864":("2026-09-16","Дмитро САВВА"),"2981518432":("2026-09-22","Дмитро САВВА")}
    output["manual_controls"]=[{"supplier_code":r["supplier_code"],"expected":expected[r["supplier_code"]],
        "pass":bool(r["latest_admission"]) and
            (r["latest_admission"]["effective_date"],r["latest_admission"]["actor"]["actor_display"])==expected[r["supplier_code"]]}
        for r in output["rows"] if r["supplier_code"] in expected]
    output["nine_clarity_checks"]=[{"supplier_code":r["supplier_code"],"found":r["clarity_20261005_present"]}
        for r in output["rows"] if r["supplier_code"] in NINE]
    final_version=c.execute("PRAGMA data_version").fetchone()[0]
    output["consistent_read_observation"]={"start_data_version":initial_version,
        "end_data_version":final_version,"pass":initial_version==final_version,
        "note":"If concurrent DB change detected, do not use this comparison as acceptance"}
    output["limitations"]=["No events persisted; reconstructions are shadow only",
        "Nine Clarity checks absent from SQLite require source snapshot; absence is not PASS",
        "Reactivation timestamps cannot be inferred from generic dateModified",
        "No automatic 90-day transition is manufactured without source proof"]
    print(json.dumps(output,ensure_ascii=False,separators=(",",":")))
    c.close()


if __name__=="__main__":
    try:
        main()
    except (sqlite3.Error, KeyError, ValueError) as exc:
        print(json.dumps({"not_available":str(exc),"STAGE_2_PASS":False,"DB_WRITES":0,
                          "SYNC_RUN":"NO","APPLY_RUN":"NO"},ensure_ascii=False))
        sys.exit(1)
