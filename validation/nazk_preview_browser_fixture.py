"""Emit minimized synthetic browser data; no real datasource or service startup."""
from pathlib import Path
import gc
import json
import tempfile
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server
import nazk_preview
from validation.nazk_preview_fixture import build

with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
    path = build(Path(directory) / 'synthetic.sqlite3')
    result = nazk_preview.snapshot(path, {'scope': ['all'], 'size': ['200']}, role='admin',
        permissions={'tasks.read', 'suppliers.read'}, risk_projector=server.supplier_risk_projection)
    print(json.dumps(result, ensure_ascii=True))
    gc.collect()
