"""The generated protocol must reopen its report without a page reload."""

import shutil
import subprocess
import unittest
from pathlib import Path


class ViolationReportReopenUiTests(unittest.TestCase):
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
