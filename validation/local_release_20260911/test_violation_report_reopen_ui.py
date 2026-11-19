"""The generated protocol must reopen its report without a page reload."""

import shutil
import subprocess
import unittest
from pathlib import Path


class ViolationReportReopenUiTests(unittest.TestCase):
    def test_document_flag_save_preserves_unsaved_fields_and_handles_api_failure(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js is unavailable")
        local = Path(__file__).with_name("app.js")
        app = local if local.exists() else Path(__file__).parents[2] / "app.js"
        script = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(process.argv[1], 'utf8');
const start = source.indexOf('async function saveViolationDocumentReview(');
const end = source.indexOf('function downloadFilenameFromDisposition(', start);
assert.ok(start >= 0 && end > start);
let fail = false, calls = 0;
const form = {innerHTML:'synthetic form remains untouched'};
const row = {
  state:null,
  querySelector(selector){
    if(selector==='.violation-document-unavailable')return this.state;
    if(selector==='a')return {after:(...nodes)=>{this.state=nodes.at(-1)}};
    return null;
  }
};
const input = {checked:true,disabled:false,
  dataset:{violationDocumentSource:'customer',violationDocumentId:'doc-1'},
  closest:()=>row};
const item = {id:'synthetic-report',evidence_documents:[{id:'doc-1',title:'Доказ.pdf',file_unavailable:false}]};
const notices=[];
const context = {
  API:'/api', document:{createElement:()=>({remove(){row.state=null}}),createTextNode:value=>({textContent:value})},
  $:selector=>selector==='#requestDetailsBody'?form:null,
  request:async(url,options)=>{calls++;assert.equal(url,'/api/violation-reports/synthetic-report/documents/customer/doc-1');assert.equal(JSON.parse(options.body).file_unavailable,input.checked);if(fail)throw new Error('synthetic API error');return{}},
  toast:message=>notices.push(message),
};
vm.createContext(context);
vm.runInContext(source.slice(start,end),context);
(async()=>{
  await context.saveViolationDocumentReview(item,input);
  assert.equal(calls,1);assert.equal(input.checked,true);assert.equal(input.disabled,false);
  assert.equal(item.evidence_documents[0].file_unavailable,true);
  assert.equal(row.state.textContent,'Недоступний');
  assert.equal(form.innerHTML,'synthetic form remains untouched');
  input.checked=false;
  await context.saveViolationDocumentReview(item,input);
  assert.equal(calls,2);assert.equal(item.evidence_documents[0].file_unavailable,false);
  assert.equal(row.state,null);assert.equal(form.innerHTML,'synthetic form remains untouched');
  input.checked=true;fail=true;
  await context.saveViolationDocumentReview(item,input);
  assert.equal(calls,3);assert.equal(input.checked,false);assert.equal(input.disabled,false);
  assert.equal(form.innerHTML,'synthetic form remains untouched');
  assert.equal(notices.at(-1),'synthetic API error');
})().catch(error=>{console.error(error);process.exitCode=1});
"""
        result = subprocess.run([node, "-e", script, str(app)], text=True,
                                capture_output=True, timeout=20, check=False)
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_protocol_review_notes_confirmation_is_a_separate_responsive_row(self):
        local = Path(__file__).with_name("app.js")
        app = local if local.exists() else Path(__file__).parents[2] / "app.js"
        styles = app.with_name("styles.css")
        source = app.read_text(encoding="utf-8")
        css = styles.read_text(encoding="utf-8")
        self.assertIn("violation-review-notes-confirmation", source)
        self.assertIn("controls.insertBefore(confirmation,main.nextSibling)", source)
        self.assertIn("preview.textContent=`«${notesInput.value}»`", source)
        self.assertIn("grid-template-columns:minmax(0,1fr) auto", css)
        self.assertIn("@media(max-width:700px){.protocol-supplier-name-provenance dl>div{grid-template-columns:1fr;gap:4px}.violation-review-notes-confirmation", css)

    def test_individual_protocol_sends_explicit_type_and_confirmed_current_notes(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js is unavailable")
        local = Path(__file__).with_name("app.js")
        app = local if local.exists() else Path(__file__).parents[2] / "app.js"
        script = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(process.argv[1], 'utf8');
const start = source.indexOf('async function generateViolationProtocol(');
const end = source.indexOf('async function completeViolationReview(', start);
assert.ok(start >= 0 && end > start);
const calls = [];
const elements = {
  '#generateViolationProtocol': {disabled:false,textContent:'Сформувати протокол'},
  '#violationProtocolType': {value:'decline_individual_review'},
  '#confirmReviewNotes': {checked:true},
  '#violationProtocolReasons': {hidden:true,textContent:''},
};
const context = {
  API:'/api', $:selector=>elements[selector],
  collectViolationReview:()=>({protocol_number:'SYN-1',protocol_date:'2026-10-20',review_notes:'Актуальний коментар УО'}),
  request:async (url,options)=>{calls.push({url,body:JSON.parse(options.body)});return {ok:true}},
  unresolvedDeclensionsByReport:new Map(), toast:()=>{}, openViolationReportById:async()=>{},
};
vm.createContext(context);
vm.runInContext(source.slice(start,end),context);
(async()=>{
 await context.generateViolationProtocol({id:'synthetic',protocol_readiness:{ready:false},protocol_readiness_individual:{ready:true}});
 assert.equal(calls[0].url,'/api/violation-reports/synthetic/review');
 assert.equal(calls[0].body.review_notes,'Актуальний коментар УО');
 assert.equal(calls[1].url,'/api/violation-reports/synthetic/protocol/generate');
 assert.equal(calls[1].body.protocol_type,'decline_individual_review');
 assert.equal(calls[1].body.confirm_review_notes,true);
 assert.equal(calls[1].body.confirmed_review_notes,'Актуальний коментар УО');
})().catch(error=>{console.error(error);process.exitCode=1});
"""
        result = subprocess.run(
            [node, "-e", script, str(app)], text=True, capture_output=True,
            timeout=20, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_generate_reopens_fresh_report_with_document_actions(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js is unavailable")
        local = Path(__file__).with_name("app.js")
        app = local if local.exists() else Path(__file__).parents[2] / "app.js"
        script = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(process.argv[1], 'utf8');
const between = (start, end) => {
  const from = source.indexOf(start), to = source.indexOf(end, from + start.length);
  assert.ok(from >= 0 && to > from, `missing runtime function: ${start}`);
  return source.slice(from, to);
};
const opener = between('async function openViolationReportById(', 'async function syncViolationReports(');
const generator = between('async function generateViolationProtocol(', 'async function completeViolationReview(');
const calls = [], notices = [];
let generated = false, bound = 0, modalOpens = 0;
const elements = {
  '#generateViolationProtocol': {disabled:false, textContent:'Сформувати протокол'},
  '#requestDetailsDialog': {open:true, showModal(){modalOpens++; this.open=true}},
  '#requestDetailsTitle': {textContent:''},
  '#requestDetailsSubtitle': {textContent:''},
  '#requestDetailsBody': {innerHTML:''},
};
const context = {
  API:'/api', violationReports:[], $:selector=>elements[selector],
  request:async (url, options={})=>{
    calls.push(`${options.method||'GET'} ${url}`);
    if(url.endsWith('/protocol/generate')){generated=true; return {ok:true}}
    if((options.method||'GET')==='GET')return {
      id:'report-1', report_id:'UA-D-2026-09-23-000001',
      date_published:'2026-09-23', status:'pending',
      review:{generated_protocol_filename:generated?'739.docx':''}
    };
    return {ok:true};
  },
  collectViolationReview:()=>({protocol_number:'739',protocol_date:'2026-09-30'}),
  unresolvedDeclensionsByReport:new Map(),
  toast:(message)=>notices.push(message),
  violationDetailHtml:item=>item.review.generated_protocol_filename
    ? '<a href="/api/protocol/files/739.docx">DOCX</a><a href="/api/violation-reports/report-1/protocol/pdf">PDF</a>'
    : 'No protocol',
  bindViolationReview:()=>{bound++},
  displayDate:value=>value, requestLabel:value=>value,
  requestStatusLabels:{}, esc:value=>value,
};
vm.createContext(context);
vm.runInContext(opener + '\n' + generator, context);
(async()=>{
  await context.generateViolationProtocol({id:'report-1',protocol_readiness:{ready:true}});
  assert.deepEqual(calls,[
    'PATCH /api/violation-reports/report-1/review',
    'POST /api/violation-reports/report-1/protocol/generate',
    'GET /api/violation-reports/report-1',
  ]);
  assert.equal(modalOpens,0,'an already-open dialog must not be reopened');
  assert.equal(bound,1);
  assert.match(elements['#requestDetailsBody'].innerHTML,/739\.docx/);
  assert.match(elements['#requestDetailsBody'].innerHTML,/protocol\/pdf/);
  assert.equal(notices.length,1);
})().catch(error=>{console.error(error);process.exitCode=1});
"""
        result = subprocess.run(
            [node, "-e", script, str(app)], text=True, capture_output=True,
            timeout=20, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)


if __name__ == "__main__":
    unittest.main()
