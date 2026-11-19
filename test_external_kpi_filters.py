"""Actual navigation and selection functions; no runtime connections."""
import pathlib
import subprocess
import unittest


class ExternalKpiFiltersTests(unittest.TestCase):
    def test_external_navigation_replaces_filters_and_selection(self):
        root=pathlib.Path(__file__).resolve().parent
        result=subprocess.run(['node','validation/external_kpi_filters.cjs'],cwd=root,capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('EXTERNAL_KPI_FILTERS=PASS',result.stdout)
