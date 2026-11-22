"""Profile key round-trips on disposable synthetic DB; no new storage/API."""
from contextlib import closing
import http.client
import json
from pathlib import Path
import subprocess
import unittest
import server
import test_bulk_protocol_save as fixtures


class ApplicationHeaderTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.BulkProtocolSaveTests();self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def call(self,method,path,payload=None):
        with closing(http.client.HTTPConnection('127.0.0.1',self.fixture.http.server_port,timeout=5)) as con:
            con.request(method,path,body=json.dumps(payload) if payload is not None else None,
                        headers={'Content-Type':'application/json','X-PQM-Local-Role':'admin'})
            response=con.getresponse();return response.status,json.loads(response.read())

    def create(self,keys):
        status,data=self.call('POST','/api/application-profiles',{'name':'Особистий UI','columns':[],'kpis':keys})
        self.assertEqual(201,status);return data['id']

    def test_existing_keys_only_and_no_individual_officer_preferences(self):
        keys=['applications','officers','suppliers']
        self.assertEqual(keys,server._validated_profile_kpis(keys+['officer:Дмитро САВВА','officer:Олена ЄРЬОМІНА','unknown',keys[0]]))
        self.assertEqual([],server._validated_profile_kpis([]))
        with self.assertRaises(ValueError):server._validated_profile_kpis('bad')

    def test_real_profile_endpoint_preserves_existing_group_order_after_reload(self):
        keys=['decision_no','officers','applications','suppliers']
        identity=self.create(keys)
        for _ in range(2):
            status,data=self.call('GET','/api/application-profiles')
            self.assertEqual(200,status)
            self.assertEqual(keys,next(p for p in data['items'] if p['id']==identity)['kpis'])
        updated=['suppliers','officers','decision_no']
        self.assertEqual(200,self.call('PATCH','/api/application-profiles/'+identity,{'kpis':updated})[0])
        self.assertEqual(updated,next(p for p in self.call('GET','/api/application-profiles')[1]['items'] if p['id']==identity)['kpis'])

    def test_deselected_kpis_are_not_forced_back(self):
        identity=self.create(['decision_yes','decision_no'])
        self.assertEqual(200,self.call('PATCH','/api/application-profiles/'+identity,{'kpis':[]})[0])
        self.assertEqual([],next(p for p in self.call('GET','/api/application-profiles')[1]['items'] if p['id']==identity)['kpis'])

    def test_existing_profile_ownership_guard_is_preserved(self):
        identity=self.create(['applications'])
        with closing(server.db()) as con:
            with con:con.execute('UPDATE application_view_profiles SET owner_key=? WHERE id=?',(server._profile_owner('another-user'),identity))
        self.assertEqual(403,self.call('PATCH','/api/application-profiles/'+identity,{'kpis':[]})[0])
        self.assertNotIn(identity,[p['id'] for p in self.call('GET','/api/application-profiles')[1]['items']])

    def test_normalization_and_ui_scope_contract(self):
        root=Path(__file__).resolve().parent
        code=r"""
const fs=require('fs'),vm=require('vm'),assert=require('node:assert/strict'),src=fs.readFileSync('app.js','utf8');
const c={profiles:[{kpis:[],columns:[]},{kpis:['suppliers','officers'],columns:[]}],columns:[],defaultKpis:()=>['applications']};
vm.createContext(c);vm.runInContext(src.split('\n').find(l=>l.startsWith('function normalizeProfiles()')),c);c.normalizeProfiles();
assert.deepEqual(Array.from(c.profiles[0].kpis),[]);assert.deepEqual(Array.from(c.profiles[1].kpis),['suppliers','officers']);
assert(!src.includes('data-officer-kpi'));assert(!src.includes('officerKpiItems'));
const css=fs.readFileSync('ui_improvements.css','utf8');assert(css.includes('flex-wrap:nowrap'));assert(!css.includes('>[data-kpi-card]:not('));assert(!css.slice(0,css.indexOf('.pqm-clear-wrap')).includes('overflow:hidden'));
const html=fs.readFileSync('index.html','utf8');assert.equal((html.match(/class="heading-action-row"/g)||[]).length,2);
console.log('HEADER_UNIT=PASS');
"""
        result=subprocess.run(['node','-e',code],cwd=root,capture_output=True,text=True,timeout=30)
        self.assertEqual(0,result.returncode,result.stdout+result.stderr)


if __name__=='__main__':unittest.main()
