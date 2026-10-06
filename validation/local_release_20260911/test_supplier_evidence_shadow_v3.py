"""Shadow adapter fixtures: ephemeral snapshots, no network/live DB."""
import copy
import sqlite3
import unittest
import json
import inspect
import itertools
import tracemalloc
from unittest.mock import patch
from tools import supplier_evidence_shadow_v3 as shadow
from tools import supplier_evidence_shadow_v3_stage2b as stage2b
import supplier_evidence_v3 as v3


def bundle():
    return {"codes":["2077003493"],"applications":[{"id":"application","supplier_code":"2077003493",
        "status":"active","date_published":"2026-09-18T10:00:00+03:00",
        "protocol_officer":"Тетяна ФЕДЧЕНКО","protocol_date":"","decision_date":"2026-09-21"}],
        "contracts":[{"id":"contract","supplier_code":"2077003493","status":"active",
        "framework_status":"active","framework_raw_json":"{}","milestones_json":"[]"}],
        "ledger":[],"profiles":[{"supplier_code":"2077003493","edr_status":"Неактуально"}],"db_read_ms":0}


class ShadowTests(unittest.TestCase):
    def test_2077003493_same_day_exact_source_chronology_and_replay(self):
        data=bundle()
        stamps=[("e3edb5e958144b61b9d3320d23d2a120","2026-09-18T17:04:21.589075+03:00"),
            ("c1939b79afce43cfbef0eadf3a0566ff","2026-09-18T15:59:34.798180+03:00"),
            ("d27925ea7ed24af7bb4c1ec5deff4eb0","2026-09-18T17:19:52.579134+03:00")]
        apps=[dict(data["applications"][0],id=identity,date_published=stamp) for identity,stamp in stamps]
        for order in itertools.permutations(apps):
            for replay in (False,True):
                data["applications"]=list(order)*(2 if replay else 1)
                full=shadow.evaluate(data,"2026-10-05")["rows"][0]["v3"]
                self.assertEqual(len(full["verification_history"]),3)
                self.assertEqual(len({e["source_event_id"] for e in full["verification_history"]}),3)
                with patch.object(shadow,"read_bundle",return_value=data):
                    row=shadow.stage_2a(None,{"manual_controls":["2077003493"]},"2026-10-05")["rows"][0]
                latest=row["latest_admission"]
                self.assertEqual(latest["source_event_id"],stamps[2][0])
                self.assertEqual(latest["source_event_at"],stamps[2][1])
                self.assertEqual(latest["event_id"],row["v3"]["current_event"]["event_id"])
                self.assertEqual(row["v3"]["visible_date"],"2026-09-18")
                self.assertIsNone(row["latest_admission_ambiguity"])
                self.assertEqual(row["verification_count"],3)

    def test_diagnostic_admission_ambiguous_without_exact_order_not_id_wins(self):
        for stamps,expected in ((["2026-09-18"]*2,"ambiguous_same_day_events"),
                (["2026-09-18T17:00:00+03:00"]*2,"ambiguous_same_timestamp")):
            data=bundle()
            data["applications"]=[dict(data["applications"][0],id=identity,date_published=stamp)
                for identity,stamp in zip(("zzz","aaa"),stamps)]
            for order in (data["applications"],list(reversed(data["applications"]))):
                fixture=dict(data,applications=order)
                with patch.object(shadow,"read_bundle",return_value=fixture):
                    row=shadow.stage_2a(None,{"manual_controls":["2077003493"]},"2026-10-05")["rows"][0]
                self.assertIsNone(row["latest_admission"])
                self.assertIsNone(row["v3"]["current_event"])
                self.assertEqual(row["latest_admission_ambiguity"],expected)

    def test_stage2a_cohort_and_sample_limits_fail_before_reads(self):
        with patch.object(shadow,"read_bundle",side_effect=AssertionError("must not read")):
            with self.assertRaisesRegex(ValueError,"cohort_limit"):
                shadow.stage_2a(None,{"too_many":[str(n) for n in range(38)]},"2026-10-05")
            with self.assertRaisesRegex(ValueError,"sample_limit"):
                shadow.stage_2a(None,{"suspended":[str(n) for n in range(6)]},"2026-10-05")

    def test_stage2a_no_old_population_projection_and_one_code_at_a_time(self):
        calls=[]
        def read(con,codes):
            calls.append(codes)
            data=bundle(); data["codes"]=codes
            for key in ("applications","contracts","profiles"):
                data[key][0]["supplier_code"]=codes[0]
            return data
        with patch.object(shadow,"read_bundle",side_effect=read), patch.object(
                shadow.old,"current_verification_projections",side_effect=AssertionError("old projection forbidden")):
            output=shadow.stage_2a(None,{"twelve":shadow.CONTROLS,"nine":shadow.NINE},"2026-10-05")
        self.assertTrue(all(len(c)==1 for c in calls))
        self.assertEqual(len(calls),21)
        self.assertNotIn("verification_history",json.dumps(output))
        self.assertNotIn("factual_snapshot",json.dumps(output))
        source=inspect.getsource(shadow.main)
        self.assertNotIn("population=",source)
        self.assertNotIn("_edr_monitoring_rows",source)
        self.assertNotIn("current_verification_projections",source)

    def test_source_budget_rejects_oversized_snapshot_before_fetch(self):
        con=memory_fixture(1)
        con.execute("UPDATE supplier_edr_verification_events SET snapshot_json=?",("x"*(shadow.MAX_SOURCE_BYTES+1),))
        with self.assertRaisesRegex(ValueError,"source_budget_exceeded"):
            shadow.read_bundle(con,["synthetic-0"])
        con.close()

    def test_stage2b_rejects_any_render_environment_before_opening_db(self):
        with patch.dict("os.environ",{"RENDER_SERVICE_ID":shadow.SANDBOX_ID}), patch.object(stage2b.sqlite3,"connect",side_effect=AssertionError("must not open")):
            with self.assertRaisesRegex(SystemExit,"offline only"):
                stage2b.main()

    def test_local_memory_profile_bounded_by_cohort_not_population(self):
        con=memory_fixture(500)
        peaks={}
        for count in (1,12,37):
            tracemalloc.start()
            result=shadow.stage_2a(con,{"synthetic":["synthetic-"+str(i) for i in range(count)]},"2026-10-05")
            _,peak=tracemalloc.get_traced_memory(); tracemalloc.stop()
            peaks[str(count)]=peak
            self.assertEqual(len(result["rows"]),count)
            self.assertLess(peak,8*1024*1024)
            del result
        tracemalloc.start()
        result=stage2b.benchmark(con,("synthetic-"+str(i) for i in range(500)),"2026-10-05")
        _,peak=tracemalloc.get_traced_memory();tracemalloc.stop()
        peaks["full_500_streamed_stage2b"]=peak
        self.assertEqual(result["suppliers"],500)
        self.assertLess(peak,8*1024*1024)
        print("LOCAL_PYTHON_PEAK_BYTES="+json.dumps(peaks,sort_keys=True))
        con.close()

    def test_stale_profile_does_not_win_and_submission_date_used(self):
        data=bundle(); before=copy.deepcopy(data)
        r=shadow.evaluate(data,"2026-10-05")["rows"][0]
        self.assertEqual(r["stored_profile_status"],"Неактуально")
        self.assertEqual(r["v3"]["edr_status_current"],"Зареєстровано")
        self.assertEqual(r["v3"]["last_verification_date"],"2026-09-18")
        self.assertEqual(r["v3"]["last_verification_officer"],"Тетяна ФЕДЧЕНКО")
        self.assertEqual(data,before)

    def test_missing_attribution_requires_verified_canonical_account(self):
        data=bundle();data["applications"][0]["protocol_officer"]=""
        a=shadow.evaluate(data,"2026-10-05")["rows"][0]
        self.assertTrue(a["adapter_gaps"])
        b=shadow.evaluate(data,"2026-10-05",v3.SANDBOX_OFFICER)["rows"][0]
        self.assertEqual(b["v3"]["last_verification_officer"],v3.SANDBOX_OFFICER)

    def test_ledger_date_officer_only_inherits_proven_admission_not_profile(self):
        data=bundle();data["ledger"]=[{"id":8627,"supplier_code":"2077003493",
            "event_type":"legacy_google_registry","occurred_at":"2026-09-22",
            "officer":"Світлана НАМЯСЕНКО","source":"legacy_google_registry","snapshot_json":"{}"}]
        r=shadow.evaluate(data,"2026-10-05")["rows"][0]
        self.assertEqual(r["v3"]["last_verification_date"],"2026-09-22")
        self.assertEqual(r["v3"]["edr_status_current"],"Зареєстровано")
        data["applications"]=[]
        r=shadow.evaluate(data,"2026-10-05")["rows"][0]
        self.assertIn("missing_factual_snapshot",str(r["adapter_gaps"]))

    def test_partial_contract_termination_no_supplier_level_exclusion(self):
        data=bundle();rc=copy.deepcopy(data["contracts"][0]);rc.update(id="terminated",status="terminated",
            milestones_json='[{"type":"activation","status":"met","dateMet":"2026-10-05T14:00:00+03:00"}]')
        data["contracts"].append(rc)
        p=shadow.evaluate(data,"2026-10-05",v3.SANDBOX_OFFICER)["rows"][0]["v3"]
        self.assertEqual(p["prozorro_status"],"Активний")
        self.assertEqual(p["visible_date"],"2026-09-18")

    def test_targeted_sql_does_not_read_unrequested_suppliers(self):
        con=sqlite3.connect(":memory:");con.row_factory=sqlite3.Row
        con.executescript('''CREATE TABLE submissions(id,supplier_code,date_published,supplier_name,qualification_id);
        CREATE TABLE application_fields(submission_id,protocol_officer,protocol_date);
        CREATE TABLE qualifications(id,submission_id,status,decision_date,synced_at);
        CREATE TABLE registry_contracts(id,supplier_code,framework_id,qualification_id,status,milestones_json);
        CREATE TABLE frameworks(id,status,raw_json);
        CREATE TABLE supplier_edr_verification_events(id,supplier_code,event_type,occurred_at,officer,source,snapshot_json,source_sheet,source_row,snapshot_hash);
        CREATE TABLE supplier_edr_profiles(supplier_code,edr_status);
        INSERT INTO supplier_edr_profiles VALUES('wanted','Зареєстровано'),('other','Неактуально');''')
        data=shadow.read_bundle(con,["wanted"])
        self.assertEqual([r["supplier_code"] for r in data["profiles"]],["wanted"])
        self.assertEqual(data["codes"],["wanted"])
        con.close()


def memory_fixture(count):
    con=sqlite3.connect(":memory:");con.row_factory=sqlite3.Row
    con.executescript('''CREATE TABLE submissions(id,supplier_code,date_published,supplier_name,qualification_id);
    CREATE TABLE application_fields(submission_id,protocol_officer,protocol_date);
    CREATE TABLE qualifications(id,submission_id,status,decision_date,synced_at);
    CREATE TABLE registry_contracts(id,supplier_code,framework_id,qualification_id,status,milestones_json,raw_json);
    CREATE TABLE frameworks(id,status,raw_json);
    CREATE TABLE supplier_edr_verification_events(id,supplier_code,event_type,occurred_at,officer,source,snapshot_json,source_sheet,source_row,snapshot_hash);
    CREATE TABLE supplier_edr_profiles(supplier_code,edr_status);''')
    for i in range(count):
        code="synthetic-"+str(i)
        con.execute("INSERT INTO submissions VALUES(?,?,?,?,?)",(code,code,"2026-09-18",code,code))
        con.execute("INSERT INTO qualifications VALUES(?,?,?,?,?)",(code,code,"active","2026-09-18","2026-09-18"))
        con.execute("INSERT INTO application_fields VALUES(?,?,?)",(code,"Тетяна ФЕДЧЕНКО",""))
        con.execute("INSERT INTO registry_contracts VALUES(?,?,?,?,?,?,?)",(code,code,code,code,"active","[]","unused"*1000))
        con.execute("INSERT INTO frameworks VALUES(?,?,?)",(code,"active",json.dumps({"unneeded":"z"*4000})))
        con.execute("INSERT INTO supplier_edr_profiles VALUES(?,?)",(code,"Неактуально"))
        for n in range(5):
            snap=json.dumps({"edr_status":"Зареєстровано","notes":"n"*512})
            con.execute("INSERT INTO supplier_edr_verification_events VALUES(?,?,?,?,?,?,?,?,?,?)",(i*5+n,code,"manual_edr","2026-09-"+str(20+n),"Тетяна ФЕДЧЕНКО","manual",snap,None,None,"hash"))
    return con


if __name__=="__main__":unittest.main()
