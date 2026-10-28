"""Offline audit replay and adversarial synthetic tests. Never imports the app."""
import ast
import copy
import gzip
import json
import logging
import sqlite3
import subprocess
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import zipfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

import contract_experience_v4 as v4

ROOT = Path(__file__).resolve().parent


def evidence():
    return json.loads(gzip.decompress((ROOT / "experience_v4_fixtures/audit.json.gz").read_bytes()))


class FakeClock:
    def __init__(self): self.now = 0.0
    def __call__(self): return self.now
    def sleep(self, seconds): self.now += seconds


def replay(case, fixture=None):
    fixture = fixture or evidence()
    clock, missing = FakeClock(), []
    def transport(url, payload, timeout):
        clock.sleep(0.4)
        key = json.dumps([url, payload], sort_keys=True, ensure_ascii=False)
        if key not in fixture["records"]:
            missing.append([url, payload])
            raise KeyError("fixture_not_recorded")
        return copy.deepcopy(fixture["records"][key])
    search = v4.Search(transport=transport, clock=clock, sleep=clock.sleep)
    result = search.run(case["supplier"], case["framework_cpv"], case["cutoff"])
    return result, missing


class AuditReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.fixture = evidence()

    def test_all_19_audited_cases_without_inventing_missing_persisted_metadata(self):
        for case in self.fixture["cases"]:
            with self.subTest(case=case["n"]):
                result, missing = replay(case, self.fixture)
                if case["n"] == 1:
                    self.assertEqual(result["status"], "unavailable")
                    self.assertEqual(result["reason"], "missing_input")
                    self.assertIsNone(case["framework_cpv"])
                    continue
                self.assertEqual(result["status"], "found", result)
                self.assertFalse(missing, missing)
                self.assertFalse(result["coverage"]["errors"])
                self.assertLessEqual(result["coverage"]["requests"], 64)
                self.assertEqual(result["algorithm_version"], 4)
                if not case["db_found"]:
                    self.assertIsNone(case["before_status"])
                    self.assertIsNone(case["before_version"])
                if 2 <= case["n"] <= 8:
                    self.assertTrue(set(case["persisted_ids"]) & {x["contract_id"] for x in result["candidates"]})

    def test_control_contracts_use_the_same_canonical_validator_in_every_route(self):
        records = self.fixture["records"]
        for case in self.fixture["cases"]:
            if case["n"] == 1: continue
            ids = list(case["controls"])
            if case["n"] == 16: ids = ["UA-2024-01-22-004308-a-b1"]  # API example, not a UO control.
            for public_id in ids:
                with self.subTest(case=case["n"], contract=public_id):
                    def get(url): return v4.body(records[json.dumps([url, None], sort_keys=True, ensure_ascii=False)])
                    detail = get(v4.PORTAL + public_id)
                    raw = get(v4.RAW + "contracts/" + detail["id"])
                    tender = get(v4.RAW + "tenders/" + raw["tender_id"])
                    result, reason = v4.canonical_candidate(detail, raw, tender, case["supplier"], case["framework_cpv"], v4.moment(case["cutoff"]))
                    self.assertEqual(reason, "accepted")
                    self.assertEqual(result["contract_id"], public_id)
                    if case["n"] == 6: self.assertEqual(result["lot_id"], "a55075c647dc46c39a407d8c261eda6f")
                    if case["n"] == 7: self.assertEqual(result["lot_id"], "4c35394e4e43437c955d3b015dda5760")

    def test_cyrillic_identifier_and_two_real_controls(self):
        case = self.fixture["cases"][18]
        result, _ = replay(case, self.fixture)
        self.assertEqual(result["supplier"], "ВО599107")
        self.assertEqual({x["contract_id"] for x in result["candidates"]}, {
            "UA-2022-11-25-011286-a-c1", "UA-2021-12-23-010412-c-c1"})
        self.assertEqual(v4.identifier(" 00123456 "), "00123456")
        self.assertNotEqual(v4.identifier("ВО599107"), "599107")
        self.assertNotEqual(v4.identifier("ВО599107"), "BO599107")
        self.assertFalse(v4.supplier_matches("ВО599107", [{"identifier": {"scheme": "UA-EDR", "id": "599107"}}]))
        self.assertFalse(v4.supplier_matches("00123456", [{"identifier": {"scheme": "UA-PASSPORT", "id": "00123456"}}], "UA-EDR"))


class BoundsTests(unittest.TestCase):
    def run_search(self, transport, **kwargs):
        clock = FakeClock()
        job = v4.Search(transport=transport, clock=clock, sleep=clock.sleep, **kwargs)
        return job, job.run("00123456", "03140000-4", "2026-10-20T12:00:00+03:00")

    @staticmethod
    def empty(url, payload, timeout): return {"data": [], "total": 0, "page": payload["page"], "per_page": 20}

    def test_none_requires_complete_supplier_fallback(self):
        job, result = self.run_search(self.empty)
        self.assertEqual(result["status"], "none")
        self.assertTrue(result["coverage"]["complete"])
        self.assertEqual(job.requests, 4)

    def test_supplier_boundary_or_cross_route_status_change_is_partial(self):
        calls = []
        def transport(url, payload, timeout):
            calls.append(payload)
            status = "active" if len(calls) == 1 else "terminated"
            return {"data": [{"contractID": "changed", "status": status}], "total": 1, "per_page": 20, "page": 1}
        _, result = self.run_search(transport)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["coverage"]["stop_reason"], "pagination_changed")
        count = [0]
        def boundary(url, payload, timeout):
            count[0] += 1
            if count[0] < 4: return self.empty(url, payload, timeout)
            return {"data": [{"contractID": "new", "status": "active"}], "total": 1, "per_page": 20, "page": 1}
        _, result = self.run_search(boundary)
        self.assertEqual(result["status"], "partial")
        self.assertFalse(result["coverage"]["complete"])

    def test_coverage_request_and_page_limits_are_partial_not_none(self):
        for limits in (v4.Limits(requests=1), v4.Limits(pages=1)):
            with self.subTest(limits=limits):
                _, result = self.run_search(self.empty, limits=limits)
                self.assertEqual(result["status"], "partial")
                self.assertFalse(result["coverage"]["complete"])
                self.assertEqual(result["message"], v4.PARTIAL_MESSAGE)

    def test_cyclic_overlapping_changed_or_short_pages_never_prove_none(self):
        for kind in ("cycle", "changed", "short", "overlap"):
            def transport(url, payload, timeout):
                page = payload["page"]
                rows = [{"contractID": str(i if kind != "overlap" else i + page), "status": "active"} for i in range(20)]
                return {"data": rows[:1] if kind == "short" else rows, "total": 100 + (page if kind == "changed" else 0), "per_page": 20, "page": page}
            with self.subTest(kind=kind):
                job, result = self.run_search(transport)
                self.assertNotEqual(result["status"], "none")
                self.assertLessEqual(job.requests, 3)

    def test_429_retry_after_numeric_and_http_date_and_5xx(self):
        self.assertEqual(v4.retry_after("Wed, 21 Oct 2015 07:28:00 GMT", 1445412470), 10)
        for code in (429, 500, 503):
            calls = []
            def transport(url, payload, timeout):
                calls.append(1)
                if len(calls) < 3: raise urllib.error.HTTPError(url, code, "temporary", {"Retry-After": "2"}, None)
                return {"ok": True}
            clock = FakeClock()
            job = v4.Search(transport=transport, clock=clock, sleep=clock.sleep)
            self.assertEqual(job.get(v4.SEARCH_URL), {"ok": True})
            self.assertEqual(job.requests, 3)
            self.assertGreaterEqual(clock.now, 4)

    def test_timeout_reset_and_permanent_error_have_bounded_attempts(self):
        for error, expected in ((TimeoutError(), 3), (ConnectionResetError(), 3),
                                (urllib.error.HTTPError(v4.SEARCH_URL, 422, "invalid", {}, None), 1)):
            call = Mock(side_effect=error)
            _, result = self.run_search(call)
            self.assertEqual(result["status"], "unavailable")
            self.assertEqual(call.call_count, expected)

    def test_retry_after_larger_than_deadline_stops_honestly(self):
        def fail(url, payload, timeout): raise urllib.error.HTTPError(url, 429, "rate", {"Retry-After": "300"}, None)
        job, result = self.run_search(fail, limits=v4.Limits(seconds=1))
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(job.requests, 1)
        self.assertEqual(result["coverage"]["stop_reason"], "time_limit")
        self.assertTrue(result["coverage"]["errors"])  # throttling remains visible as well.

    def test_stop_and_restart_are_explicit_and_start_from_first_page(self):
        _, stopped = self.run_search(self.empty, cancelled=lambda: True)
        self.assertEqual(stopped["status"], "partial")
        self.assertEqual(stopped["coverage"]["stop_reason"], "cancelled")
        _, restarted = self.run_search(self.empty)
        self.assertEqual(restarted["status"], "none")
        self.assertEqual(restarted["restart"]["mode"], "replay_from_first_page")

    def test_partial_detail_outage_is_technical_not_none(self):
        def transport(url, payload, timeout):
            if payload is not None: return {"data": [{"contractID": "x", "status": "terminated"}], "total": 1, "per_page": 20, "page": 1}
            raise TimeoutError()
        job, result = self.run_search(transport)
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(len(result["coverage"]["errors"]), 1)
        self.assertLessEqual(job.requests, 6)  # one detail, shared across routes.

    def test_concurrent_searches_have_one_active_transport(self):
        active, maximum, lock = 0, 0, threading.Lock()
        def transport(url, payload, timeout):
            nonlocal active, maximum
            with lock: active += 1; maximum = max(maximum, active)
            import time
            time.sleep(0.003)
            with lock: active -= 1
            return self.empty(url, payload, timeout)
        results = []
        threads = [threading.Thread(target=lambda: results.append(v4.search("00123456", "03140000-4", "2026-10-20T12:00:00+03:00", transport=transport))) for _ in range(4)]
        for thread in threads: thread.start()
        for thread in threads: thread.join(2)
        self.assertEqual(len(results), 4)
        self.assertEqual(maximum, 1)


class CanonicalSafetyTests(unittest.TestCase):
    def setUp(self):
        records = evidence()["records"]
        def get(url): return copy.deepcopy(v4.body(records[json.dumps([url, None], sort_keys=True)]))
        self.detail = get(v4.PORTAL + "UA-2026-02-19-014053-a-c1")
        self.raw = get(v4.RAW + "contracts/" + self.detail["id"])
        self.tender = get(v4.RAW + "tenders/" + self.raw["tender_id"])

    def validate(self):
        return v4.canonical_candidate(self.detail, self.raw, self.tender, "43643750", "39310000-8", v4.moment("2026-09-21T12:22:13.595740+03:00"))

    def test_wrong_supplier_and_wrong_award_cannot_be_accepted(self):
        self.raw["suppliers"][0]["identifier"]["id"] = "00000000"
        self.assertEqual(self.validate()[1], "supplier_identifier")
        self.setUp()
        award = next(x for x in self.tender["awards"] if x["id"] == self.raw["awardID"])
        award["suppliers"][0]["identifier"]["id"] = "00000000"
        self.assertEqual(self.validate()[1], "award_supplier_identifier")

    def test_conflicting_lot_cannot_be_assigned(self):
        for item in self.raw["items"]: item["relatedLot"] = "wrong-lot"
        with self.assertRaises(v4.EvidenceError): self.validate()

    def test_execution_and_date_rules_are_not_relaxed(self):
        self.raw["terminationDetails"] = "early termination"
        self.assertEqual(self.validate()[1], "termination_details")
        self.setUp(); self.raw["dateModified"] = "2026-10-28T12:00:00+00:00"
        self.assertEqual(self.validate()[1], "date_modified_cutoff")

    def test_incomplete_or_ambiguous_identity_never_becomes_conclusive_rejection(self):
        for parties in (None, [], [{"identifier": {"id": "43643750"}}],
                        [{"identifier": {"id": "43643750", "scheme": "UA-EDR"}},
                         {"identifier": {"id": "43643750", "scheme": "UA-PASSPORT"}}]):
            with self.subTest(parties=parties):
                self.raw["suppliers"] = parties
                with self.assertRaises(v4.EvidenceError): self.validate()
        self.setUp()
        award = next(x for x in self.tender["awards"] if x["id"] == self.raw["awardID"])
        award["suppliers"] = []
        with self.assertRaises(v4.EvidenceError): self.validate()


def isolated_worker_namespace(connection):
    """Compile real functions only; no server import/init/scheduler side effects."""
    names = {"contract_experience_worker", "_store_document_check_result", "merge_document_check_results",
             "document_check_category", "document_check_status", "document_check_category_summaries",
             "current_document_check_result", "experience_search_presentation"}
    tree = ast.parse((ROOT / "server.py").read_text(encoding="utf-8-sig"))
    @contextmanager
    def db():
        with connection: yield connection
    namespace = dict(json=json, db=db, datetime=datetime, timezone=timezone, urllib=urllib,
                     now_iso=lambda: datetime.now(timezone.utc).isoformat(), SERVER_LOG=logging.getLogger("test"),
                     DOCUMENT_CHECK_LOCK=threading.RLock(), CONTRACT_EXPERIENCE_PENDING_LOCK=threading.Lock(),
                     CONTRACT_EXPERIENCE_PENDING={"s"}, CONTRACT_EXPERIENCE_RETRY_ATTEMPTS={},
                     CONTRACT_EXPERIENCE_RETRY_PENDING=set(), CONTRACT_EXPERIENCE_ALGORITHM_VERSION=3,
                     _stored_experience_is_fresh=lambda result: False,
                     _schedule_contract_experience_retry=Mock())
    exec(compile(ast.Module([x for x in tree.body if isinstance(x, ast.FunctionDef) and x.name in names], type_ignores=[]), str(ROOT / "server.py"), "exec"), namespace)
    return namespace


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(":memory:")
        self.con.row_factory = sqlite3.Row
        self.con.executescript("""
        CREATE TABLE frameworks(id TEXT,dk_code TEXT,pretty_id TEXT);
        CREATE TABLE submissions(id TEXT,framework_id TEXT,supplier_name TEXT,supplier_code TEXT,date_published TEXT);
        CREATE TABLE application_fields(submission_id TEXT PRIMARY KEY,document_check_result_json TEXT,
          document_check_status TEXT,document_check_summary TEXT,document_checked_at TEXT,updated_at TEXT,updated_by TEXT,manual TEXT);
        INSERT INTO frameworks VALUES('f','03140000-4','UA-F');
        INSERT INTO submissions VALUES('s','f','synthetic','00123456','2026-10-20T12:00:00+03:00');
        INSERT INTO application_fields(submission_id,document_check_result_json,manual) VALUES('s','{}','keep');
        """)
        self.ns = isolated_worker_namespace(self.con)

    def tearDown(self): self.con.close()

    def stored(self): return json.loads(self.con.execute("SELECT document_check_result_json FROM application_fields").fetchone()[0])

    def test_partial_persists_coverage_api_message_neutral_summary_and_explicit_restart(self):
        result = v4.Search().result("partial", [], {"complete": False, "stop_reason": "cancelled"})
        self.ns["search_supplier_contract_experience"] = search = Mock(return_value=result)
        self.ns["contract_experience_worker"](["s"])
        stored = self.stored()
        self.assertEqual(stored["contract_experience"]["algorithm_version"], 4)
        check = stored["category_results"]["experience"]["checks"][0]
        self.assertEqual(check["search_status"], "partial")
        self.assertEqual(check["coverage"]["stop_reason"], "cancelled")
        self.assertEqual(self.ns["experience_search_presentation"](stored)["status"], "partial")
        self.assertEqual(self.ns["document_check_category_summaries"](stored)["experience"], "neutral")
        self.ns["_schedule_contract_experience_retry"].assert_not_called()
        self.ns["contract_experience_worker"](["s"])
        self.assertEqual(search.call_count, 1)
        self.ns["contract_experience_worker"](["s"], force=True)
        self.assertEqual(search.call_count, 2)
        self.assertEqual(search.call_args.kwargs["algorithm_version"], 4)
        self.assertEqual(self.con.execute("SELECT manual FROM application_fields").fetchone()[0], "keep")

    def test_old_v3_none_is_never_rewritten_automatically_even_if_expired(self):
        old = {"category_results": {"experience": {"checked_at": "2020-01-01", "checks": [
            {"key": "contract_experience", "search_status": "none", "algorithm_version": 3}]}}}
        raw = json.dumps(old)
        self.con.execute("UPDATE application_fields SET document_check_result_json=?", (raw,))
        self.ns["search_supplier_contract_experience"] = search = Mock()
        self.ns["contract_experience_worker"](["s"])
        search.assert_not_called()
        self.assertEqual(self.con.execute("SELECT document_check_result_json FROM application_fields").fetchone()[0], raw)

    def test_flat_historical_v3_and_malformed_presentation_remain_read_only(self):
        old = {"checks": [{"key": "contract_experience", "search_status": "none", "algorithm_version": 3}]}
        raw = json.dumps(old)
        self.con.execute("UPDATE application_fields SET document_check_result_json=?", (raw,))
        self.ns["search_supplier_contract_experience"] = call = Mock()
        self.ns["contract_experience_worker"](["s"])
        call.assert_not_called()
        self.assertEqual(self.con.execute("SELECT document_check_result_json FROM application_fields").fetchone()[0], raw)
        self.assertEqual(self.ns["experience_search_presentation"]([]), {})
        self.assertEqual(self.ns["experience_search_presentation"]({"category_results": [], "checks": []})["status"], "")

    def test_stop_persists_only_current_submission_and_preserves_other_categories(self):
        old = {"category_results": {"mvs": {"checks": [{"key": "mvs_name", "status": "ok"}], "status": "ok"}}}
        self.con.execute("UPDATE application_fields SET document_check_result_json=?", (json.dumps(old),))
        event = threading.Event()
        def search(*args, **kwargs):
            event.set()
            return v4.Search().result("partial", [], {"complete": False, "stop_reason": "cancelled"})
        self.ns["search_supplier_contract_experience"] = call = Mock(side_effect=search)
        self.ns["contract_experience_worker"](["s", "not-processed"], stop_event=event)
        self.assertEqual(call.call_count, 1)
        self.assertEqual(self.stored()["category_results"]["mvs"], old["category_results"]["mvs"])
        self.ns["_schedule_contract_experience_retry"].assert_not_called()


class CompatibilityAndUiTests(unittest.TestCase):
    def test_historical_v3_assertions_remain_ast_identical(self):
        relative = "validation/local_release_20260911/test_contract_experience_search.py"
        with zipfile.ZipFile(ROOT / "experience_v4_fixtures/parent_overrides.zip") as archive:
            old = ast.parse(archive.read(relative).decode("utf-8-sig"))
        current = ast.parse((ROOT / relative).read_text(encoding="utf-8-sig"))
        for node in ast.walk(current):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "search_supplier_contract_experience":
                version = next(x for x in node.keywords if x.arg == "algorithm_version")
                self.assertEqual(ast.literal_eval(version.value), 3)
                node.keywords.remove(version)
        self.assertEqual(ast.dump(current, include_attributes=False), ast.dump(old, include_attributes=False))

    def test_default_public_entry_is_v4_and_explicit_v3_is_compatible(self):
        tree = ast.parse((ROOT / "server.py").read_text(encoding="utf-8-sig"))
        function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "search_supplier_contract_experience")
        ns = {}
        exec(compile(ast.Module([function], type_ignores=[]), "isolated-entry", "exec"), ns)
        with patch.object(v4, "search", return_value={"algorithm_version": 4}) as call:
            self.assertEqual(ns[function.name]("ВО599107", "34350000-5", "2026-10-27T11:27:23+02:00")["algorithm_version"], 4)
            self.assertEqual(call.call_args.args[0], "ВО599107")

    def test_registry_and_card_render_partial_and_technical_states_separately(self):
        script = r'''
        const fs=require('node:fs'),assert=require('node:assert/strict');
        const source=fs.readFileSync('app.js','utf8');
        const branch=source.split('\n').find(s=>s.trim().startsWith("if(col.key==='dkCode')"));
        const esc=s=>String(s).replaceAll('&','&amp;').replaceAll('"','&quot;').replaceAll('<','&lt;').replaceAll('>','&gt;');
        const cell=new Function('row','col','attrs','esc',branch);
        const partial=cell({dkCode:'03140000-4',experienceSearch:'neutral',experienceSearchState:{status:'partial',message:'Пошук виконано частково. Відсутність договорів не підтверджена <safe>'}},{key:'dkCode'},()=>'',esc);
        assert(partial.includes('>…</span>'));assert(partial.includes('&lt;safe&gt;'));assert(!partial.includes('marker found'));
        const found=cell({dkCode:'03140000-4',experienceSearch:'ok',experienceSearchState:{status:'found'}},{key:'dkCode'},()=>'',esc);
        assert(found.includes('>+</span>'));assert(found.includes('marker found'));
        const legacy=cell({dkCode:'03140000-4',experienceSearch:'neutral'},{key:'dkCode'},()=>'',esc);
        assert(legacy.includes('>−</span>'));
        const technical=cell({dkCode:'03140000-4',experienceSearch:'neutral',experienceSearchState:{status:'unavailable',message:'Технічна помилка'}},{key:'dkCode'},()=>'',esc);
        assert(technical.includes('>−</span>'));assert(technical.includes('Технічна помилка'));
        const nodes={};const $=id=>nodes[id]??=( {open:false,showModal(){this.open=true;}} );
        const displayDate=x=>x;let lastDocumentCheck;
        eval(source.split('\n').find(s=>s.startsWith('function renderBusinessRows(')));
        eval(source.split('\n').find(s=>s.startsWith('function renderDocumentCheck(')));
        renderDocumentCheck({supplier_name:'Synthetic',supplier_code:'00123456',pretty_id:'UA-F',counts:{neutral:1},checks:[{key:'contract_experience',label:'Досвід',status:'neutral',search_status:'partial',detail:'Пошук виконано частково',rows:[]}]});
        assert(nodes['#documentCheckBody'].innerHTML.includes('<i>…</i>'));
        assert(nodes['#documentCheckBody'].innerHTML.includes('Пошук виконано частково'));
        '''
        result = subprocess.run(["node", "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__": unittest.main()
