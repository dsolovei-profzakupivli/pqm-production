"""Type KPI filter is additive and only toggles its own selection."""
import subprocess
import unittest


class TaskTypeFilterTests(unittest.TestCase):
    def test_actual_click_handler_preserves_status_and_shared_filters(self):
        result = subprocess.run(['node', 'validation/task_type_filter_unit.cjs'],
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
