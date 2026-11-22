"""Paired synthetic workload in separate processes; no PQM import or real DB."""
import argparse
import ast
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import gc
import json
import logging
import os
from pathlib import Path
import re
import socket
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import tracemalloc
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import runtime_memory


def rss():
    class Counters(ctypes.Structure):
        _fields_ = [('cb', wintypes.DWORD), ('PageFaultCount', wintypes.DWORD)] + [
            (name, ctypes.c_size_t) for name in (
                'PeakWorkingSetSize', 'WorkingSetSize', 'QuotaPeakPagedPoolUsage',
                'QuotaPagedPoolUsage', 'QuotaPeakNonPagedPoolUsage', 'QuotaNonPagedPoolUsage',
                'PagefileUsage', 'PeakPagefileUsage', 'PrivateUsage')]
    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    api = ctypes.WinDLL('psapi', use_last_error=True).GetProcessMemoryInfo
    api.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
    if not api(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
        raise ctypes.WinError(ctypes.get_last_error())
    return {'rss_bytes': counters.WorkingSetSize, 'private_bytes': counters.PrivateUsage}


def extract(tree, name, namespace):
    node = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), '<pinned-function>', 'exec'), namespace)


def open_connections():
    count = 0
    for obj in gc.get_objects():
        if isinstance(obj, sqlite3.Connection):
            try:
                obj.execute('SELECT 1').fetchone()
                count += 1
            except sqlite3.ProgrammingError:
                pass
    return count


def worker(variant, scenario, profile=True):
    print(f'benchmark {scenario} {variant}: start', file=sys.stderr, flush=True)
    source = (ROOT / 'server.py' if variant == 'after' else
              ROOT.parent / 'pqm-production-memory-audit-a53234f-20261120/source/server.py')
    tree = ast.parse(source.read_text(encoding='utf-8-sig'))
    clock = SimpleNamespace(now=0)
    clock.monotonic = lambda: clock.now
    namespace = dict(runtime_memory=runtime_memory, sqlite3=sqlite3, re=re, json=json,
                     threading=threading, time=clock, SERVER_LOG=logging.getLogger('synthetic'),
                     DOCUMENT_CHECK_LOCK=threading.Lock(), now_iso=lambda: '2026-11-20T00:00:00+00:00',
                     unicode_casefold=lambda value: str(value or '').casefold(),
                     edr_sync_v2=SimpleNamespace(register_verification_sql_functions=lambda con: None))
    with tempfile.TemporaryDirectory(prefix='pqm-memory-synthetic-') as folder:
        path = Path(folder) / 'synthetic.sqlite3'
        namespace['DB_PATH'] = path
        extract(tree, 'db', namespace)
        db = namespace['db']
        connection = sqlite3.connect(path)
        connection.execute('''CREATE TABLE application_fields (
            submission_id TEXT PRIMARY KEY, document_check_status TEXT,
            document_check_summary TEXT, document_checked_at TEXT,
            document_check_result_json TEXT, updated_at TEXT, updated_by TEXT)''')
        connection.commit()
        connection.close()
        if scenario == 'documents':
            jobs = runtime_memory.DocumentJobs(clock=clock.monotonic) if variant == 'after' else {}
            namespace.update(DOCUMENT_CHECK_JOBS=jobs,
                             analyze_application_documents=lambda code, selection: {
                                 'selected_categories': ['signature'],
                                 'checks': [{'key': 'signer', 'status': 'ok', 'detail': code * 1024}]})
            for name in ('document_check_category', 'document_check_status', 'merge_document_check_results',
                         '_store_document_check_result', 'document_check_worker'):
                extract(tree, name, namespace)

            def operation(index):
                code = f'synthetic-{index:06d}'
                if variant == 'after':
                    assert jobs.start(code, code)
                else:
                    jobs[code] = {'job_id': code, 'submission_id': code, 'status': 'running'}
                namespace['document_check_worker'](code, code)
        elif scenario == 'contracts':
            jobs = runtime_memory.ContractCache(clock=clock.monotonic) if variant == 'after' else {}
            namespace.update(CONTRACT_EXPERIENCE_CACHE=jobs, CONTRACT_EXPERIENCE_LOCK=threading.Lock(),
                             CONTRACT_EXPERIENCE_ALGORITHM_VERSION=3, CONTRACT_EXPERIENCE_CACHE_TTL=21600,
                             CONTRACT_EXPERIENCE_UNAVAILABLE_CACHE_TTL=60,
                             CONTRACT_EXPERIENCE_EXACT_PAGE_LIMIT=3, CONTRACT_EXPERIENCE_FALLBACK_PAGE_LIMIT=20,
                             CONTRACT_EXPERIENCE_MAX_CANDIDATES=3,
                             _digits=lambda value: re.sub(r'\D', '', value),
                             normalize_experience_cpv=lambda value: value,
                             _contract_experience_cutoff=lambda value: datetime.fromisoformat(value),
                             _discover_contract_summaries=lambda *args: ([], True))
            extract(tree, 'search_supplier_contract_experience', namespace)

            def operation(index):
                result = namespace['search_supplier_contract_experience'](
                    f'{index:010d}', '12340000', '2026-11-20T00:00:00+00:00')
                assert result['status'] == 'none'
        else:
            jobs = {}

            def operation(index):
                with db() as con:
                    # Mimic per-request projection UDF payload held by SQLite.
                    payload = {str(index): 'x' * 16000}
                    con.create_function('PROJECTION', 0, lambda: len(payload))
                    assert con.execute('SELECT PROJECTION()').fetchone()[0] == 1

        gc.collect()
        before = rss()
        if profile:
            tracemalloc.start()
        initial = tracemalloc.get_traced_memory()[0]
        timings = []
        samples = []
        for index in range(1, 2001):
            started = time.perf_counter()
            operation(index)
            timings.append((time.perf_counter() - started) * 1000)
            if index in (100, 500, 1000, 2000):
                current, peak = tracemalloc.get_traced_memory()
                samples.append({'operations': index, 'entries': len(jobs),
                                'open_connections': open_connections(),
                                'traced_delta_bytes': current - initial, 'traced_peak_bytes': peak,
                                **rss()})
                print(f'benchmark {scenario} {variant}: {index}', file=sys.stderr, flush=True)
        count_before_gc = open_connections()
        gc.collect()
        after_gc = rss()
        count_after_gc = open_connections()
        persisted = None
        if scenario == 'documents':
            # A fresh interpreter reads the SQLite file, with no transient job state.
            output = subprocess.check_output([sys.executable, '-B', '-c',
                'import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); '
                'print(c.execute("SELECT COUNT(*) FROM application_fields").fetchone()[0]); c.close()',
                str(path)], text=True)
            persisted = int(output.strip())
            assert persisted == 2000
        if scenario in {'contracts', 'documents'}:
            clock.now = 21601
        idle_entries = len(jobs)
        current, peak = tracemalloc.get_traced_memory()
        if profile:
            tracemalloc.stop()
        return {'variant': variant, 'scenario': scenario, 'operations': 2000,
                'before': before, 'samples': samples, 'after_gc': after_gc,
                'open_before_gc': count_before_gc, 'open_after_gc': count_after_gc,
                'idle_entries': idle_entries, 'persisted_after_new_interpreter': persisted,
                'latency_ms': {'p50': statistics.median(timings),
                               'p95': sorted(timings)[int(len(timings) * .95) - 1]},
                'traced_final_delta_bytes': current - initial, 'traced_peak_bytes': peak}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--variant')
    parser.add_argument('--scenario')
    parser.add_argument('--latency', action='store_true')
    args = parser.parse_args()
    if args.variant:
        print(json.dumps(worker(args.variant, args.scenario, profile=not args.latency)))
    else:
        results = []
        for scenario in ('documents', 'contracts', 'sqlite'):
            for repeat in range(1 if args.latency else 3):
                for variant in ('before', 'after'):
                    command = [
                        sys.executable, '-X', 'utf8', '-B', __file__, '--variant', variant,
                        '--scenario', scenario]
                    if args.latency:
                        command.append('--latency')
                    output = subprocess.check_output(command, text=True)
                    result = json.loads(output)
                    result['repeat'] = repeat + 1
                    results.append(result)
        evidence = ROOT / 'evidence'
        evidence.mkdir(exist_ok=True)
        (evidence / ('LATENCY.json' if args.latency else 'BENCHMARK.json')).write_text(json.dumps(results, indent=2), encoding='utf-8')
        for scenario in ('documents', 'contracts', 'sqlite'):
            for variant in ('before', 'after'):
                runs = [item for item in results if item['scenario'] == scenario and item['variant'] == variant]
                print(scenario, variant, json.dumps({
                    'median_rss_delta_bytes': statistics.median(r['samples'][-1]['rss_bytes'] - r['before']['rss_bytes'] for r in runs),
                    'median_traced_delta_bytes': statistics.median(r['samples'][-1]['traced_delta_bytes'] for r in runs),
                    'entries': [r['samples'][-1]['entries'] for r in runs],
                    'idle_entries': [r['idle_entries'] for r in runs],
                    'open_before_gc': [r['open_before_gc'] for r in runs],
                    'open_after_gc': [r['open_after_gc'] for r in runs],
                    'median_p95_ms': statistics.median(r['latency_ms']['p95'] for r in runs)}))
