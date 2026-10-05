"""Shadow adapter fixtures: ephemeral snapshots, no network/live DB."""
import copy
import sqlite3
import unittest
from tools import supplier_evidence_shadow_v3 as shadow
import supplier_evidence_v3 as v3


def bundle():
    return {"codes":["2077003493"],"applications":[{"id":"application","supplier_code":"2077003493",
        "status":"active","date_published":"2026-09-18T10:00:00+03:00",
        "protocol_officer":"Тетяна ФЕДЧЕНКО","protocol_date":"","decision_date":"2026-09-21"}],
        "contracts":[{"id":"contract","supplier_code":"2077003493","status":"active",
        "framework_status":"active","framework_raw_json":"{}","milestones_json":"[]"}],
        "ledger":[],"profiles":[{"supplier_code":"2077003493","edr_status":"Неактуально"}],"db_read_ms":0}


class ShadowTests(unittest.TestCase):
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
        CREATE TABLE registry_contracts(id,supplier_code,framework_id,qualification_id,status);
        CREATE TABLE frameworks(id,status,raw_json);
        CREATE TABLE supplier_edr_verification_events(supplier_code);
        CREATE TABLE supplier_edr_profiles(supplier_code,edr_status);
        INSERT INTO supplier_edr_profiles VALUES('wanted','Зареєстровано'),('other','Неактуально');''')
        data=shadow.read_bundle(con,["wanted"])
        self.assertEqual([r["supplier_code"] for r in data["profiles"]],["wanted"])
        self.assertEqual(data["codes"],["wanted"])
        con.close()


if __name__=="__main__":unittest.main()
