"""Measure the real document-job HTTP handler, loopback only, synthetic DB."""
import gc
import json
import logging
import os
from pathlib import Path
import socket
import statistics
import subprocess
import sys
import zipfile
import shutil
import tempfile
import threading
import time
from http.server import ThreadingHTTPServer
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def run(variant):
    with tempfile.TemporaryDirectory(prefix='pqm-http-memory-') as folder:
        temp = Path(folder)
        source = ROOT
        if variant == 'before':
            source = temp / 'source'
            source.mkdir()
            for item in ROOT.glob('*.py'):
                shutil.copy2(item, source/item.name)
            with zipfile.ZipFile(ROOT/'validation/fixtures/production_memory_parent_a53234f.zip') as archive:
                (source/'server.py').write_bytes(archive.read('server.py'))
        os.environ.update(PQM_ENV='local', PQM_DATA_DIR=str(temp / 'data'),
            PQM_DB_PATH=str(temp / 'synthetic.sqlite3'), PQM_AUTH_ENABLED='0',
            PQM_ENABLE_SCHEDULER='0', PQM_ENABLE_GOOGLE='0', PQM_ENABLE_NAZK_WORKFLOW='0',
            PQM_ENABLE_PROZORRO_SCHEDULER='0', PQM_ENABLE_NAZK_SCHEDULER='0',
            PQM_ENABLE_VIOLATION_SCHEDULER='0', PQM_ENABLE_BROWSER='0',
            PQM_ENABLE_BIDS_UPDATE='0', PQM_ENABLE_POWERBI='0', PQM_USERS_JSON='')
        connect = socket.socket.connect
        def loopback(sock, address):
            if address[0] not in {'127.0.0.1', 'localhost', '::1'}:
                raise RuntimeError('External network forbidden')
            return connect(sock, address)
        socket.socket.connect = loopback
        socket.getfqdn = lambda name='': name or 'localhost'
        sys.path.insert(0, str(source))
        import server
        server.Handler.log_message = lambda *args: None
        with server.db() as con:
            server.auth_access.migrate(con)
        con.close()  # Bootstrap fixture ownership, outside the timed requests.
        docs = [('supplier', {'id': 'synthetic', 'hash': 'sha256:synthetic'})]
        checks = [{'key': 'signer', 'status': 'ok', 'detail': 'synthetic ' * 100}]
        result = {'counts': {'ok': 1, 'error': 0, 'warning': 0, 'neutral': 0},
                  'checks': checks, 'category_results': {'signature': {'status': 'ok', 'checks': checks}},
                  'ready': True, 'document_check_job_id':'job'}
        if variant == 'after':
            result['document_fingerprints'] = {'signature': server.document_source_fingerprint(docs)}
            server.DOCUMENT_CHECK_JOBS.start('job', 's')
            server.DOCUMENT_CHECK_JOBS.finish('job', {'status': 'complete', 'result': result})
        else:
            server.DOCUMENT_CHECK_JOBS['job'] = {'submission_id': 's', 'status': 'complete', 'result': result}
        with server.db() as con:
            con.execute('CREATE TABLE application_fields(submission_id TEXT PRIMARY KEY,document_check_result_json TEXT)')
            con.execute('INSERT INTO application_fields VALUES (?,?)',('s',json.dumps(result)))
        con.close()  # Fixture setup, outside the timed requests, including baseline.
        server.application_documents = lambda code: ('synthetic', docs)
        http = ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        thread = threading.Thread(target=http.serve_forever, daemon=True)
        thread.start()
        timings = []
        try:
            for index in range(220):
                started = time.perf_counter()
                with urllib.request.urlopen(f'http://127.0.0.1:{http.server_port}/api/document-check-jobs/job', timeout=5) as response:
                    payload = json.load(response)
                elapsed = (time.perf_counter() - started) * 1000
                assert payload['status'] == 'complete' and payload['result']['ready']
                if index >= 20:
                    timings.append(elapsed)
        finally:
            http.shutdown()
            thread.join()
            http.server_close()
        gc.collect()
        logging.shutdown()
        return {'variant': variant, 'requests': len(timings), 'warmup': 20,
                'endpoint': '/api/document-check-jobs/job',
                'p50_ms': statistics.median(timings), 'p95_ms': sorted(timings)[189]}


if __name__ == '__main__':
    if len(sys.argv) > 1:
        print(json.dumps(run(sys.argv[1])))
    else:
        result = [json.loads(subprocess.check_output([
            sys.executable, '-X', 'utf8', '-B', __file__, variant], text=True))
            for repeat in range(3) for variant in ('before', 'after')]
        (ROOT / 'evidence/PRODUCTION_HTTP_BENCHMARK.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        print(json.dumps(result, indent=2))
