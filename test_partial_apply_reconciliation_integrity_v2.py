"""Run the immutable v2 reconciliation contract on its exact baseline tree."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

FIXTURE = Path("partial_apply_reconciliation_v2_exact_2ece9de.zip")
FIXTURE_SHA256 = "644a3defd3b7df4fd2368557c565dd8b8d9086ef9ce1b0935d578d70c0429b07"

class PartialApplyReconciliationV2BaselineOverlay(unittest.TestCase):
    def test_historical_v2_contract_on_exact_baseline(self):
        root = Path(__file__).resolve().parent
        fixture = root / FIXTURE
        import hashlib
        self.assertEqual(hashlib.sha256(fixture.read_bytes()).hexdigest(), FIXTURE_SHA256)
        with tempfile.TemporaryDirectory(prefix="pqm-partial-v2-baseline-", dir=root) as temp:
            target = Path(temp).resolve()
            with zipfile.ZipFile(fixture) as archive:
                for member in archive.infolist():
                    output = (target / member.filename).resolve()
                    self.assertTrue(output.is_relative_to(target), "unsafe baseline fixture path")
                    if member.is_dir():
                        output.mkdir(parents=True, exist_ok=True)
                    else:
                        output.parent.mkdir(parents=True, exist_ok=True)
                        output.write_bytes(archive.read(member))
            env = os.environ.copy()
            env["PQM_RELEASE_SOURCE_ROOT"] = str(target)
            result = subprocess.run(
                [sys.executable, "-B", "-m", "unittest", "test_partial_apply_reconciliation_integrity_v2", "-v"],
                cwd=target, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
            self.assertEqual(result.returncode, 0, result.stdout)

if __name__ == "__main__":
    unittest.main()
