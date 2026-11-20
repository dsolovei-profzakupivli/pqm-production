"""Run five actual sync cycles against generated pages and a disposable SQLite DB.

Extract unchanged sync functions only. Task/NAZK/contract background hooks are
stubs; the scheduled time, external services and real databases are not used.
"""
import ast
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import gc
import json
import logging
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import tracemalloc
from types import SimpleNamespace
import weakref

from memory_stage1_benchmark import ROOT, extract, open_connections, rss
import runtime_memory


class Payload(dict):
    pass


def run(variant, background=False):
    source = ROOT / 'server.py' if variant == 'after' else ROOT.parent / 'pqm-production-memory-audit-a53234f-20261120/source/server.py'
    tree = ast.parse(source.read_text(encoding='utf-8-sig'))
    references = []
    enqueue_counts = []

    def framework(url):
        identifier = url.rsplit('/', 1)[-1]
        item = Payload(id=identifier, prettyID=identifier, status='active')
        references.append(weakref.ref(item))
        return {'data': item}

    def pages(identifier, resource, cursor):
        if resource == 'submissions':
            for offset in (0, 50):
                batch = []
                for index in range(offset, offset + 50):
                    code = f'{int(identifier[1:]) * 100 + index:08d}'
                    item = Payload(id=f'{identifier}-s{index}', tenderers=[{
                        'name': 'SYNTHETIC', 'identifier': {'id': code}}],
                        datePublished='2026-11-20T00:00:00+00:00', status='active',
                        documents=[{'id': f'doc-{index}', 'hash': 'sha256:synthetic',
                                    'title': 'synthetic.pdf', 'url': 'https://example.test/document'}],
                        synthetic_payload=code * 1024)
                    references.append(weakref.ref(item))
                    batch.append(item)
                yield batch
        elif resource == 'qualifications':
            yield [dict(id=f'{identifier}-q{index}', submissionID=f'{identifier}-s{index}',
                        status='pending', date='2026-11-20T00:00:00+00:00') for index in range(100)]

    with tempfile.TemporaryDirectory(prefix='pqm-sync-memory-') as folder:
        path = Path(folder) / 'synthetic.sqlite3'
        with sqlite3.connect(path, factory=runtime_memory.ClosingConnection) as con:
            con.executescript('''
              CREATE TABLE frameworks(id PRIMARY KEY,pretty_id,status,dk_code DEFAULT '12340000');
              CREATE TABLE submissions(id PRIMARY KEY,framework_id,supplier_name,supplier_code,
                date_published,status,qualification_id,documents_json,raw_json,synced_at);
              CREATE INDEX supplier_lookup ON submissions(supplier_code,date_published);
              CREATE TABLE application_fields(submission_id PRIMARY KEY,protocol_officer DEFAULT '',
                manager_name DEFAULT '',manager_name_source DEFAULT '',manager_name_source_submission_id,
                updated_at,updated_by,document_check_status,document_check_summary,document_checked_at,
                document_check_result_json DEFAULT '');
              CREATE TABLE framework_service_directory(framework_id,responsible_officer);
              CREATE TABLE supplier_edr_profiles(supplier_code,manager_name,edr_checked_at);
              CREATE TABLE supplier_managers(supplier_code,manager_name,is_current,valid_from);
              CREATE TABLE qualifications(id PRIMARY KEY,framework_id,submission_id,status,
                decision_date,documents_json,raw_json,synced_at);
              CREATE TABLE registry_contracts(id PRIMARY KEY,qualification_id,status);
            ''')
            con.executemany('INSERT INTO frameworks(id,pretty_id,status) VALUES (?,?,?)', [(f'f{i}', f'f{i}', 'active') for i in range(8)])
        namespace = dict(
            sqlite3=sqlite3, runtime_memory=runtime_memory, DB_PATH=path, json=json, re=re,
            unicode_casefold=lambda value: str(value or '').casefold(),
            edr_sync_v2=SimpleNamespace(register_verification_sql_functions=lambda con: None),
            API_ROOT='https://example.test', api_get=framework, scoped_pages=pages,
            save_framework=lambda item: True, resource_cursor=lambda *args: None,
            now_iso=lambda: datetime.now(timezone.utc).isoformat(),
            ensure_submission_nazk_control=lambda *args: None,
            enqueue_contract_experience_search=lambda ids: enqueue_counts.append(len(ids)),
            sync_framework_officers=lambda: {'matched': 0},
            refresh_supplier_registry_summary=lambda: 800,
            reconcile_nazk_tasks_after_complete_prozorro_sync=lambda result: {},
            reconcile_prozorro_task_lifecycles=lambda: {}, rebuild_operational_tasks=lambda: None,
            SYNC_STATE={}, SANDBOX_MODE=False, datetime=datetime, timezone=timezone,
            SERVER_LOG=logging.getLogger('synthetic-sync'))
        for name in ('db', 'sync_one_framework', 'sync_incremental_active_frameworks', 'sync_incremental_worker'):
            extract(tree, name, namespace)
        executor = None
        cache = {}
        if background:
            executor = ThreadPoolExecutor(max_workers=2)
            cache = runtime_memory.ContractCache() if variant == 'after' else {}
            namespace.update(
                CONTRACT_EXPERIENCE_CACHE=cache, CONTRACT_EXPERIENCE_LOCK=threading.Lock(),
                CONTRACT_EXPERIENCE_PENDING=set(), CONTRACT_EXPERIENCE_PENDING_LOCK=threading.Lock(),
                CONTRACT_EXPERIENCE_EXECUTOR=executor, DOCUMENT_CHECK_LOCK=threading.Lock(),
                CONTRACT_EXPERIENCE_RETRY_ATTEMPTS={}, CONTRACT_EXPERIENCE_RETRY_PENDING=set(),
                CONTRACT_EXPERIENCE_ALGORITHM_VERSION=3, CONTRACT_EXPERIENCE_CACHE_TTL=21600,
                CONTRACT_EXPERIENCE_UNAVAILABLE_CACHE_TTL=60,
                CONTRACT_EXPERIENCE_EXACT_PAGE_LIMIT=3, CONTRACT_EXPERIENCE_FALLBACK_PAGE_LIMIT=20,
                CONTRACT_EXPERIENCE_MAX_CANDIDATES=3, time=time,
                _digits=lambda value: re.sub(r'\D', '', value),
                normalize_experience_cpv=lambda value: value,
                _contract_experience_cutoff=lambda value: datetime.fromisoformat(value),
                _discover_contract_summaries=lambda *args: ([], True))
            for name in ('document_check_category', 'document_check_status', 'merge_document_check_results',
                         '_store_document_check_result', '_stored_experience_is_fresh',
                         'search_supplier_contract_experience', 'contract_experience_worker',
                         'enqueue_contract_experience_search'):
                extract(tree, name, namespace)
        gc.collect()
        baseline = rss()
        tracemalloc.start()
        samples = []
        for cycle in range(1, 6):
            before = rss()
            begin = time.perf_counter()
            namespace['sync_incremental_worker']()
            elapsed = time.perf_counter() - begin
            result = namespace['SYNC_STATE']['last_result']
            assert not result['errors'] and result['completed'] == 8, result
            pending_at_sync_end = len(namespace.get('CONTRACT_EXPERIENCE_PENDING', set()))
            if background:
                deadline = time.monotonic() + 120
                while namespace['CONTRACT_EXPERIENCE_PENDING']:
                    if time.monotonic() > deadline:
                        raise RuntimeError('Synthetic background work did not drain')
                    time.sleep(.01)
            current, peak = tracemalloc.get_traced_memory()
            sample = dict(cycle=cycle, before=before, after=rss(), seconds=elapsed,
                          open_after=open_connections(), live_payloads=sum(ref() is not None for ref in references),
                          traced_current=current, traced_peak=peak,
                          result=dict(result), document_jobs=0, contract_cache_entries=len(cache),
                          pending_at_sync_end=pending_at_sync_end,
                          pending_after_drain=len(namespace.get('CONTRACT_EXPERIENCE_PENDING', set())))
            time.sleep(.1)  # Synthetic idle, not a simulated hour of external activity.
            sample['idle'] = rss()
            sample['open_idle'] = open_connections()
            gc.collect()
            sample['after_gc'] = rss()
            sample['open_after_gc'] = open_connections()
            samples.append(sample)
            print(f'sync {variant}: cycle {cycle} complete', file=sys.stderr, flush=True)
        tracemalloc.stop()
        if executor:
            executor.shutdown(wait=True)
        with sqlite3.connect(path, factory=runtime_memory.ClosingConnection) as con:
            counts = [con.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
                      for table in ('submissions', 'qualifications')]
            if background:
                assert con.execute("SELECT COUNT(*) FROM application_fields WHERE document_check_result_json<>''").fetchone()[0] == 800
        assert counts == [800, 800]
        return dict(variant=variant, baseline=baseline, samples=samples, counts=counts,
                    enqueue_counts=enqueue_counts,
                    background=background,
                    limitations='Synthetic pages; actual sync/SQLite functions. '
                    'Task/NAZK/summary hooks stubbed; no UI/API traffic. '
                    + ('Actual contract enqueue/worker/cache/persistence; discovery HTTP stubbed.' if background
                       else 'Contract background hook stubbed.'))


if __name__ == '__main__':
    if len(sys.argv) > 1:
        print(json.dumps(run(sys.argv[1], background='--background' in sys.argv)))
    else:
        results = []
        for variant in ('before', 'after'):
            results.append(json.loads(subprocess.check_output([
                sys.executable, '-X', 'utf8', '-B', __file__, variant], text=True)))
        evidence = ROOT / 'evidence'
        evidence.mkdir(exist_ok=True)
        (evidence / 'SYNC_BENCHMARK.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
        print(json.dumps(results, indent=2))
