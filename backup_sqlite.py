#!/usr/bin/env python3
"""Create a consistent SQLite backup from PQM_DATA_DIR."""
import os, sqlite3, zipfile
from datetime import datetime, timezone
from pathlib import Path

root = Path(os.environ.get("PQM_DATA_DIR", "./data")).expanduser().resolve()
db_path = root / "pqm.sqlite3"
out_dir = root / "backups"
out_dir.mkdir(parents=True, exist_ok=True)
if not db_path.exists():
    raise SystemExit(f"Database not found: {db_path}")
stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
tmp = out_dir / f"pqm-{stamp}.sqlite3"
zip_path = out_dir / f"pqm-{stamp}.zip"
source = sqlite3.connect(db_path)
target = sqlite3.connect(tmp)
try:
    source.backup(target)
finally:
    target.close(); source.close()
with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
    z.write(tmp, tmp.name)
tmp.unlink()
print(zip_path)
