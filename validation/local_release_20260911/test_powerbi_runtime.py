import tempfile,unittest
from pathlib import Path
from unittest.mock import patch,MagicMock
import server

class PowerbiTests(unittest.TestCase):
    def test_duplicate(self):
        with patch.dict(server.POWERBI_EXPORT_STATE,{'running':True}),patch.object(server.threading,'Thread') as thread:
            result,status=server.start_powerbi_export()
            self.assertEqual(status,409);self.assertEqual(result['error_code'],'already_running');thread.assert_not_called()
    def run_export(self,code):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);current=root/'powerbi_current';current.mkdir();(current/'old').write_text('saved')
            process=MagicMock();process.stdout=iter(['ModuleNotFoundError: requests\n'] if code else ['done\n']);process.wait.return_value=code;process.pid=12
            def launch(command,**kwargs):
                self.assertEqual(command[0],str(server.BIDS_PYTHON));self.assertEqual(command[1],str(server.BIDS_SCRIPT))
                if not code:
                    build=root/command[-1];build.mkdir();(build/'_COMPLETE.txt').write_text('ok')
                cm=MagicMock();cm.__enter__.return_value=process;return cm
            with patch.object(server,'POWERBI_OUTPUT_ROOT',root),patch.object(server,'POWERBI_CURRENT_PATH',current),patch.object(Path,'is_file',return_value=True),patch.object(server.subprocess,'Popen',side_effect=launch),patch.dict(server.POWERBI_EXPORT_STATE,{},clear=True):
                server.powerbi_export_worker()
                self.assertEqual(server.POWERBI_EXPORT_STATE['exit_code'],code)
                self.assertFalse(server.POWERBI_EXPORT_STATE['running'])
                if code:self.assertEqual((current/'old').read_text(),'saved');self.assertEqual(server.POWERBI_EXPORT_STATE['error_code'],'export_failed')
                else:self.assertEqual((Path(server.POWERBI_EXPORT_STATE['previous_path'])/'old').read_text(),'saved')
    def test_failure_preserves_current(self):self.run_export(1)
    def test_success_keeps_previous(self):self.run_export(0)
    def test_thread_start_failure_is_json(self):
        with patch.dict(server.POWERBI_EXPORT_STATE,{'running':False}),patch.object(server.threading,'Thread') as thread:
            thread.return_value.start.side_effect=RuntimeError('test start fault')
            result,status=server.start_powerbi_export()
            self.assertEqual(status,503);self.assertEqual(result['error_code'],'start_failed')
            self.assertFalse(server.POWERBI_EXPORT_STATE['running'])

if __name__=='__main__':unittest.main()
