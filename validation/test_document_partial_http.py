"""Real local HTTP selection parsing; disposable authenticated fixture database."""
import base64,http.client,json,unittest,urllib.parse
from unittest.mock import patch
import server
from validation.local_release_20260911 import test_sandbox_functionality_repair as original
class PartialHttp(unittest.TestCase):
 setUpClass=classmethod(original.SavedHistoryHTTPTests.setUpClass.__func__)
 def test_single_and_combined_selections_reach_job_unchanged(self):
  for selection in [{'0':['signature']},{'1':['mvs']},{'0':['signature'],'1':['mvs']}]:
   with self.subTest(selection=selection),patch.object(server,'launch_document_check_job',return_value=True) as launch:
    con=http.client.HTTPConnection('127.0.0.1',self.port,timeout=10)
    auth=base64.b64encode(('fixture-admin:'+self.web.PASSWORD).encode()).decode()
    con.request('GET','/api/applications/pending/verify-documents/start?selection='+urllib.parse.quote(json.dumps(selection)),headers={'Authorization':'Basic '+auth})
    response=con.getresponse();body=json.loads(response.read());con.close()
    self.assertEqual(response.status,202,body);self.assertEqual(launch.call_args.args[2],selection)
if __name__=='__main__':unittest.main()
