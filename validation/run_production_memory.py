"""Targeted current/history suite, isolated files and network, both Gate paths."""
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.environ.update(PQM_SANDBOX='0',PQM_TEST_NETWORK_ISOLATION='1')
from validation.run_local_release import main

if __name__ == '__main__':
    if len(sys.argv) == 1:
        sys.argv.append('test_production_memory*.py')
    raise SystemExit(main())
