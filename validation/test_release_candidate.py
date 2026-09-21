import importlib.util
from pathlib import Path
import unittest
spec = importlib.util.spec_from_file_location('release_candidate', Path(__file__).resolve().parents[1] / 'tools/release_candidate.py')
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)


class ReleaseRecord(unittest.TestCase):
    def setUp(self):
        self.plan = {'candidate_sha': 'a' * 40, 'production_baseline_sha': 'b' * 40}
        self.evidence = tool.template(self.plan)
    def complete(self):
        for item in self.evidence['evidence'].values():
            item.update(passed=True, reference='synthetic-test-evidence')
        self.evidence['explicit_approval'].update(approved=True, candidate_sha='a' * 40, reference='synthetic-approval')
    def test_default_is_blocked(self):
        self.assertFalse(tool.check(self.plan, self.evidence)['record_complete'])
    def test_complete_record_never_deploys(self):
        self.complete()
        result = tool.check(self.plan, self.evidence)
        self.assertTrue(result['record_complete'])
        self.assertFalse(result['deployment_performed'])
    def test_changed_plan_invalidates_evidence(self):
        self.complete()
        self.plan['changes'] = ['unexpected']
        self.assertFalse(tool.check(self.plan, self.evidence)['record_complete'])
    def test_wrong_approval_sha_is_blocked(self):
        self.complete()
        self.evidence['explicit_approval']['candidate_sha'] = 'c' * 40
        self.assertFalse(tool.check(self.plan, self.evidence)['record_complete'])
    def test_missing_backup_is_blocked(self):
        self.complete()
        self.evidence['evidence']['production_backup']['reference'] = ''
        self.assertFalse(tool.check(self.plan, self.evidence)['record_complete'])


if __name__ == '__main__':
    unittest.main()
