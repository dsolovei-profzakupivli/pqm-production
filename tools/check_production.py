#!/usr/bin/env python3
"""Small pre-deploy smoke test for the PQM production container/runtime."""
import os, subprocess, sys

required = ["server.py", "index.html", "app.js", "protocol_docx.py", "reference_directories.py", "requirements.txt"]
missing = [p for p in required if not os.path.isfile(p)]
if missing:
    raise SystemExit("Missing files: " + ", ".join(missing))
subprocess.run([sys.executable, "-m", "py_compile", "server.py", "protocol_docx.py", "reference_directories.py"], check=True)
print("PQM production smoke check: OK")
