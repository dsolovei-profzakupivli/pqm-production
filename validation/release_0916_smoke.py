"""WEB-specific NEXT integration gates on synthetic data only."""
import unittest
from unittest.mock import patch
import web_smoke as web
s=web.server

class NextAcceptance(web.WebAcceptance):
    def test_20_new_module_permissions(self):
        for role in ('admin','officer','viewer'):
            self.assertEqual(200,self.request('/api/edr-monitoring',role)[0])
            self.assertEqual(200,self.request('/api/edr-monitoring/termination-exclusions/preview',role,'POST',{'supplier_codes':['00000000']})[0])
        self.assertEqual(403,self.request('/api/edr-monitoring/termination-exclusions/create','viewer','POST',{'supplier_codes':[]})[0])

    def test_21_safe_mode_overrides_persisted_enable_without_rewriting_it(self):
        with s.db() as con:
            original=[tuple(r) for r in con.execute('SELECT * FROM scheduler_job_settings')]
            for key in s.SCHEDULER_TARGETS:s.scheduler_runtime.save_enabled(con,key,True,'synthetic')
            before=[tuple(r) for r in con.execute('SELECT * FROM scheduler_job_settings')]
        try:
            with patch.object(s,'SAFE_MODE',True),patch.object(s,'register_scheduler_job') as start:
                self.assertTrue(all(not v for v in s.apply_scheduler_settings(catch_up=True).values()))
                start.assert_not_called()
                self.assertFalse(s.runtime_feature_state('google',True)['enabled'])
                self.assertEqual(s.rebuild_operational_tasks()['skipped'],'safe_mode')
                self.assertEqual(s.rebuild_nazk_tasks('synthetic',workflow='maintenance')['skipped'],'safe_mode')
                for path in ('/api/sync','/api/admin/runtime-features/google','/api/edr-monitoring/termination-exclusions/create'):
                    self.assertEqual(503,self.request(path,'admin','POST',{})[0])
                self.assertEqual(200,self.request('/api/edr-monitoring','viewer')[0])
                with self.assertRaises(ValueError):s.set_scheduler_job_enabled('prozorro',True,'synthetic')
            with s.db() as con:self.assertEqual(before,[tuple(r) for r in con.execute('SELECT * FROM scheduler_job_settings')])
        finally:
            with s.db() as con:
                con.execute('DELETE FROM scheduler_job_settings')
                con.executemany('INSERT INTO scheduler_job_settings VALUES (?,?,?,?)',original)

    def test_22_safe_nazk_control_read_does_not_materialize_missing_control(self):
        with s.db() as con:
            before=[tuple(row) for row in con.execute('SELECT * FROM submission_nazk_controls ORDER BY id')]
        with patch.object(s,'SAFE_MODE',True),patch.object(s,'get_submission_nazk_control',return_value=None),\
                patch.object(s,'ensure_submission_nazk_control') as create:
            status,payload,_=self.request('/api/applications/pending/nazk-control','admin')
            self.assertEqual(200,status)
            self.assertIsNone(payload['control'])
            create.assert_not_called()
        with s.db() as con:
            self.assertEqual(before,[tuple(row) for row in con.execute('SELECT * FROM submission_nazk_controls ORDER BY id')])

if __name__=='__main__':unittest.main(verbosity=2)
