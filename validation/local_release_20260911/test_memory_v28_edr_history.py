"""Keep the absent Production EDR exact-byte assertions on their pinned inputs."""
import importlib.util
import os
from pathlib import Path
import unittest
from validation.memory_v28_history import snapshot_root

def load_tests(loader, tests, pattern):
    root = snapshot_root('edr')
    path = root / 'validation/local_release_20260911/test_production_edr_display_toasts_integrity.py'
    spec = importlib.util.spec_from_file_location('memory_edr_historical_assertions', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    original = module.ProductionEdrDisplayToastsIntegrityTests if hasattr(module, 'ProductionEdrDisplayToastsIntegrityTests') else next(
        item for item in vars(module).values() if isinstance(item, type) and issubclass(item, unittest.TestCase))
    class HistoricalAssertions(original):
        def setUp(self):
            self.previous = Path.cwd()
            os.chdir(root)
            self.addCleanup(os.chdir, self.previous)
    return loader.loadTestsFromTestCase(HistoricalAssertions)
