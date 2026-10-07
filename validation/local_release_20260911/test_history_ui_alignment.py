import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import unittest
from unittest.mock import patch

import server


class HistoryAlignmentApiTests(unittest.TestCase):
    def setUp(self):
        self.c = sqlite3.connect(':memory:')
        self.c.row_factory = sqlite3.Row
        self.c.create_function('CASEFOLD', 1, lambda x: str(x or '').casefold())
        self.c.executescript('''
          CREATE TABLE application_view_profiles(id TEXT PRIMARY KEY,owner_key TEXT,name TEXT,is_system INTEGER,columns_json TEXT,created_at TEXT,updated_at TEXT,created_by TEXT,updated_by TEXT);
          CREATE TABLE submissions(id TEXT,framework_id TEXT,qualification_id TEXT,supplier_code TEXT,supplier_name TEXT,date_published TEXT,documents_json TEXT);
          CREATE TABLE frameworks(id TEXT,pretty_id TEXT,title TEXT,dk_code TEXT);
          CREATE TABLE qualifications(id TEXT,submission_id TEXT,status TEXT,decision_date TEXT,synced_at TEXT,documents_json TEXT);
          CREATE TABLE registry_contracts(qualification_id TEXT,status TEXT,synced_at TEXT,milestones_json TEXT);
          CREATE TABLE application_fields(submission_id TEXT,protocol_decision TEXT,protocol_officer TEXT,review_officer TEXT,protocol_number TEXT,protocol_date TEXT,protocol_remarks TEXT,compliance_comments TEXT,contract_details TEXT,manager_name TEXT);
          INSERT INTO submissions VALUES('a','f','q','123','Test','2026-10-06','[]');
          INSERT INTO application_fields(submission_id,protocol_officer,review_officer) VALUES('a','Protocol officer','Actual reviewer');
        ''')
        self.db = patch.object(server, 'db', return_value=self.c)
        self.db.start()

    def tearDown(self):
        self.db.stop()
        self.c.close()

    def columns(self):
        return [dict(key=k, width=120, visible=True, pin='') for k in server.HISTORY_COLUMN_KEYS]

    def test_review_and_protocol_are_distinct_stored_fields(self):
        before = self.c.total_changes
        item = server.application_history({})['items'][0]
        self.assertEqual(item['review_officer'], 'Actual reviewer')
        self.assertEqual(item['protocol_officer'], 'Protocol officer')
        self.assertEqual(self.c.total_changes, before)

    def test_blank_review_never_falls_back_to_protocol(self):
        self.c.execute("UPDATE application_fields SET review_officer='' ")
        self.assertEqual(server.application_history({})['items'][0]['review_officer'], '')

    def test_review_sort_targets_review_field(self):
        self.assertIn('af.review_officer', server.history_order_sql('[{"key":"review_officer","direction":"asc"}]'))

    def test_old_profile_get_does_not_rewrite(self):
        old = [c for c in self.columns() if c['key'] != 'review_officer']
        old.reverse()
        old[0].update(width=444, visible=False)
        server.history_column_settings('first', old)
        before = self.c.total_changes
        self.assertEqual(server.history_column_settings('first')['columns'][0]['width'], 444)
        self.assertFalse(server.history_column_settings('first')['columns'][0]['visible'])
        self.assertEqual(self.c.total_changes, before)

    def test_pin_roundtrip_and_account_isolation(self):
        columns = self.columns()
        columns[0]['pin'] = 'left'
        server.history_column_settings('first', columns)
        self.assertEqual(server.history_column_settings('first')['columns'][0]['pin'], 'left')
        self.assertEqual(server.history_column_settings('second')['columns'], [])

    def test_legacy_eleven_exact_roundtrip_without_pin(self):
        columns = [dict(key=k, visible=True, width=160, order=i)
                   for i,k in enumerate(k for k in server.HISTORY_COLUMN_KEYS if k != 'review_officer')]
        server.history_column_settings('first', columns)
        self.assertEqual(server.history_column_settings('first')['columns'], columns)
        server.history_column_settings('first', server.history_column_settings('first')['columns'])
        self.assertEqual(server.history_column_settings('first')['columns'], columns)

    def test_explicit_empty_pin_roundtrip(self):
        columns = self.columns()
        server.history_column_settings('first', columns)
        self.assertEqual(server.history_column_settings('first')['columns'][0]['pin'], '')

    def test_right_pin_invalid_without_write(self):
        columns = self.columns()
        columns[0]['pin'] = 'right'
        before = self.c.total_changes
        with self.assertRaises(ValueError):
            server.history_column_settings('first', columns)
        self.assertEqual(self.c.total_changes, before)


class HistoryAlignmentJsTests(unittest.TestCase):
    def test_history_interactions_and_shared_drag(self):
        node = shutil.which('node') or str(Path(os.environ.get('LOCALAPPDATA', '')) / '../.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe')
        if not Path(node).is_file():
            node = str(Path.home() / '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe')
        script = r'''
const vm=require('node:vm'),fs=require('node:fs'),assert=require('node:assert/strict');
const nodes=new Map();let writes=0,dragInstalled=0,savedPayload;
function node(key){if(!nodes.has(key))nodes.set(key,{value:'',innerHTML:'',textContent:'',disabled:false,open:false,style:{},dataset:{},querySelector(s){return node(key+' '+s)},insertAdjacentHTML(){},showModal(){this.open=true},close(){this.open=false}});return nodes.get(key)}
const context={structuredClone,Set,Number,Math,document:{querySelector:node,body:node('body')},window:{installViewportDrag(){dragInstalled++}},esc:x=>String(x??''),formatOfficerName:x=>String(x||''),historicalApplicationMarker:()=>'',historyDateCell:x=>x,drawHistorySort(){},historyItems:[],request:async(path,options)=>{if(options){writes++;savedPayload=JSON.parse(options.body)}return {columns:[]}}};
vm.createContext(context);vm.runInContext(fs.readFileSync('history_columns.js','utf8'),context);
async function test(){
const run=s=>vm.runInContext(s,context);
assert.equal(dragInstalled,1);
assert.equal(run("historyReviewOfficer('')"),'—');
assert.equal(run("historyReviewOfficer('Actual')"),'Actual');
run("var old=historyColumnDefaults.filter(c=>c.key!=='review_officer').map(c=>({...c})).reverse();old[0].width=444;old[1].visible=false;var merged=mergeHistoryColumns(old)");
assert.equal(run('merged.length'),12);
assert.deepEqual(JSON.parse(run("JSON.stringify(merged.filter(c=>c.key!=='review_officer').map(c=>c.key))")),JSON.parse(run('JSON.stringify(old.map(c=>c.key))')));
assert.equal(run('merged[0].width'),444);assert.equal(run('merged[1].visible'),false);
assert.equal(run("merged.findIndex(c=>c.key==='review_officer')"),run("merged.findIndex(c=>c.key==='decision')")+1);
run("var legacy=old.map(c=>{const {pin,...rest}=c;return rest});var legacyMerged=mergeHistoryColumns(legacy)");
assert.equal(run("legacyMerged.filter(c=>c.key!=='review_officer').some(c=>Object.hasOwn(c,'pin'))"),false);
assert.equal(run("legacyMerged.find(c=>c.key==='review_officer').pin"),'');
run('historySettingsAvailable=true;historyColumns=legacyMerged');
node('#historyColumnSearch').value='';await node('#historyColumnsButton').onclick();assert.equal(writes,0);
node('#historyColumnCancel').onclick();assert.equal(writes,0);
await run('saveHistoryColumns(legacyMerged)');
assert.equal(savedPayload.columns.filter(c=>c.key!=='review_officer').some(c=>Object.hasOwn(c,'pin')),false);
assert.equal(savedPayload.columns.find(c=>c.key==='review_officer').pin,'');
writes=0;run('historyColumns=structuredClone(historyColumnDefaults)');
await node('#historyColumnsButton').onclick();assert.equal(writes,0);
run("historyDraft[0].visible=false;historyDraft[0].width=222;historyDraft[0].pin='left'");
node('#historyColumnCancel').onclick();assert.equal(writes,0);assert.equal(run('historyColumns[0].visible'),true);
await node('#historyColumnsButton').onclick();node('#historyColumnReset').onclick();node('#historyColumnClose').onclick();assert.equal(writes,0);
await node('#historyColumnsButton').onclick();
function change(selector,value,checked){node('#historyColumnList').onchange({target:{value,checked,closest:()=>({dataset:{key:'supplier'}}),matches:s=>s===selector}})}
change('.col-visible','',false);change('.col-width','222');change('.col-pin','left');
run('moveHistoryColumn(0,2)');assert.equal(run('historyDraft[2].key'),'supplier');
node('#historyColumnSearch').value='УО';node('#historyColumnSearch').oninput();
assert.ok(node('#historyColumnList').innerHTML.includes('review_officer'));assert.ok(!node('#historyColumnList').innerHTML.includes('data-key="supplier"'));assert.ok(node('#historyColumnList').innerHTML.includes('draggable="false"'));
let prevented=false;node('#historyColumnList').ondragstart({target:{matches:()=>true},preventDefault(){prevented=true}});assert.equal(prevented,true);
await node('#historyColumnSave').onclick();assert.equal(writes,1);assert.equal(run('historyColumns[2].width'),222);assert.equal(run('historyColumns[2].pin'),'left');assert.equal(run('historyColumns[2].visible'),false);
assert.equal(savedPayload.columns[2].pin,'left');
context.historyItems=[{supplier_name:'Test',documents:[],review_officer:'Actual reviewer',protocol_officer:'Protocol officer'}];run('renderHistoryTable()');
assert.ok(node('#historyRows').innerHTML.includes('>Actual reviewer</td>'));assert.ok(node('#historyRows').innerHTML.includes('>Protocol officer</td>'));
context.historyItems[0].review_officer='';run('renderHistoryTable()');assert.ok(node('#historyRows').innerHTML.includes('data-history-column="review_officer" class="" style="">—</td>'));
run("var pins=[{pin:'left',width:120},{pin:'',width:90},{pin:'left',width:80}]");assert.ok(run('historyPinnedStyle(pins[2],pins)').includes('left:120px'));
// Exercise the existing drag helper, not an alternate implementation.
const listeners={},headerListeners={},style={},header={dataset:{},classList:{add(){},remove(){}},addEventListener(k,f){headerListeners[k]=f},hasPointerCapture(){return true},releasePointerCapture(){},setPointerCapture(){}};
const dialog={open:true,style,addEventListener(k,f){listeners[k]=f},getBoundingClientRect(){return {left:100,top:100,width:500,height:300}}};
const dragContext={window:{addEventListener(){}},document:{getElementById(){return null}},innerWidth:800,innerHeight:600};vm.createContext(dragContext);vm.runInContext(fs.readFileSync('working_modal_drag.js','utf8'),dragContext);dragContext.window.installViewportDrag(dialog,dialog,header);
headerListeners.pointerdown({button:0,isPrimary:true,target:{closest:()=>({})}});assert.equal(style.left,undefined);
headerListeners.pointerdown({button:0,isPrimary:true,pointerId:1,clientX:110,clientY:110,target:{closest:()=>null},preventDefault(){}});
headerListeners.pointermove({pointerId:1,clientX:9999,clientY:9999});assert.equal(style.left,'292px');assert.equal(style.top,'508px');
headerListeners.pointermove({pointerId:1,clientX:-9999,clientY:-9999});assert.equal(style.left,'8px');assert.equal(style.top,'8px');listeners.close();
console.log('HISTORY UI + SHARED DRAG: PASS');
}
test().catch(e=>{console.error(e);process.exitCode=1});
'''
        result = subprocess.run([node, '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
