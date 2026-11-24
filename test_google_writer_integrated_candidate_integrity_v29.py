"""Verify the immutable V29 candidate lineage through its exact snapshot runner."""
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parent


class CandidateV29HistoryTests(unittest.TestCase):
    def test_original_v29_contract_runs_from_its_pinned_commit(self):
        result = subprocess.run(
            [sys.executable, "-B", str(ROOT / "validation/run_integrated_writer_ui_v29_history.py")],
            cwd=ROOT, check=False,
        )
        self.assertEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
