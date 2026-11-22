"""Keep the memory-job UI recovery probe in the ordinary Linux Python Gate."""
from pathlib import Path
import shutil
import subprocess
import unittest

class ProductionMemoryUI(unittest.TestCase):
    def test_job_recovery_and_authorization_errors_without_network(self):
        node=shutil.which('node')
        self.assertIsNotNone(node,'Node is required for the shipped UI regression')
        result=subprocess.run([node,'validation/memory_stage1_ui.cjs'],cwd=Path.cwd(),
                              capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('6 scenarios PASS',result.stdout)
