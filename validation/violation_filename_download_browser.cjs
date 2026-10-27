/** Native Chromium download: real server header + actual PQM link renderer. */
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),crypto=require('node:crypto'),{execFileSync}=require('node:child_process');
const {chromium}=require('playwright');const root=path.resolve(__dirname,'..');
const fixture=JSON.parse(execFileSync(process.env.PQM_PYTHON||(process.platform==='win32'?'python':'python3'),['-X','utf8','-B','-c',`import tempfile,os,json,io,base64,sqlite3,gc,logging
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
from docx import Document
with tempfile.TemporaryDirectory() as tmp:
 os.environ.update(PQM_ENV='local',PQM_DATA_DIR=tmp,PQM_DB_PATH=tmp+'/synthetic.sqlite3',PQM_ENABLE_SCHEDULER='0',PQM_ENABLE_GOOGLE='0',PQM_AUTH_ENABLED='0',PQM_RELEASE_SCHEMA_ONLY='1')
 import server
 item={'report_id':'UA-D-2026-10-21-000001','author_name':'КНП "ОКОЦ КОР"','defendant_name':'ПРАТ "ЮРІЯ"','defendant_code':'00447853','review':{'customer_verified_short_name':'КНП "ОКОЦ КОР"'},'supplier_verified':{'short_name':'ПРАТ "ЮРІЯ"'}}
 server.init_db();item['tender_pretty_id']='UA-2026-10-06-006715-a'
 metadata=server._resolve_violation_protocol_metadata(item,{'report_id':item['report_id'],'supplier_code':item['defendant_code'],'supplier_short_name':item['supplier_verified']['short_name'],'supplier_name':item['defendant_name']})
 import document_metadata
 name=server._violation_protocol_filename(item,{'protocol_number':'810','protocol_type':'warning'})
 source=Path(tmp)/'violation-synthetic.docx';doc=Document();doc.add_paragraph('Незмінний текст документа «ОКОЦ КОР»');doc.save(source);headers={};body=io.BytesIO()
 con=sqlite3.connect(':memory:');con.execute('CREATE TABLE violation_report_reviews(generated_protocol_filename TEXT,generated_protocol_metadata_json TEXT)');con.execute('INSERT INTO violation_report_reviews VALUES (?,?)',(source.name,json.dumps({'protocol_download':{'filename':name}})))
 req=SimpleNamespace(path='/api/protocol/files/'+source.name,send_response=lambda code:None,send_header=lambda k,v:headers.update({k:v}),end_headers=lambda:None,wfile=body)
 with patch.object(server,'PROTOCOLS_DIR',Path(tmp)),patch.object(server,'db',return_value=con):server.Handler._do_GET(req)
 con.close();print(json.dumps({'filename':name,'headers':headers,'body':base64.b64encode(body.getvalue()).decode(),'metadata_items':document_metadata.resolved_items(metadata),'protocol_subject':metadata['protocol_subject']['value']}));gc.collect();logging.shutdown()`],{cwd:root,encoding:'utf8'}));
const source=fs.readFileSync(path.join(root,'app.js'),'utf8');const start=source.indexOf('function protocolDocumentActions(');const end=source.indexOf('\n}',start)+2;assert(start>=0&&end>start);
(async()=>{const browser=await chromium.launch({headless:true,executablePath:process.env.PQM_TEST_BROWSER});let server;try{
 const page=await browser.newPage({acceptDownloads:true});const bytes=Buffer.from(fixture.body,'base64');
 const http=require('node:http');server=http.createServer((req,res)=>{if(req.url==='/'){res.writeHead(200,{'Content-Type':'text/html'});res.end('<html><body><main id="links"></main></body></html>')}else if(req.url==='/api/protocol/files/violation-synthetic.docx'){res.writeHead(200,fixture.headers);res.end(bytes)}else{res.writeHead(404);res.end()}});await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 await page.goto(`http://127.0.0.1:${server.address().port}/`);await page.addScriptTag({content:source.split(/\r?\n/).find(line=>line.startsWith('const esc='))+'\nwindow.operationalActionIcon=()=>"DOCX";'+source.slice(start,end)});
 await page.evaluate(()=>document.querySelector('#links').innerHTML=protocolDocumentActions({docxUrl:'/api/protocol/files/violation-synthetic.docx'}));
 const event=page.waitForEvent('download');await page.getByRole('link',{name:'Завантажити DOCX'}).click();const download=await event;
 assert.equal(download.suggestedFilename(),fixture.filename,JSON.stringify(fixture.headers));assert.match(download.suggestedFilename(),/КНП «ОКОЦ КОР»/);assert(!download.suggestedFilename().includes('КНП -ОКОЦ КОР-'));
 fs.mkdirSync(path.join(root,'evidence'),{recursive:true});const target=path.join(root,'evidence/downloaded-synthetic.docx');await download.saveAs(target);assert.equal(await download.failure(),null);assert(fs.readFileSync(target).equals(bytes));
 const metadataStart=source.indexOf('function resolvedDocumentMetadataHtml('),metadataEnd=source.indexOf('function operationalSupplierDocumentHtml(',metadataStart);assert(metadataEnd>metadataStart);
 await page.addScriptTag({content:'window.copyText=value=>window.copiedMetadata=value;'+source.slice(metadataStart,metadataEnd)});
 await page.evaluate(items=>{const box=document.createElement('section');box.id='metadata';box.innerHTML=resolvedDocumentMetadataHtml(items);document.body.append(box);bindResolvedDocumentMetadata(box)},fixture.metadata_items);
 assert.match(fixture.protocol_subject,/КНП «ОКОЦ КОР»/);assert.match(fixture.protocol_subject,/ПРАТ «ЮРІЯ»/);assert(!fixture.protocol_subject.includes('"'));
 assert.equal(await page.locator('#metadata .document-resolved-metadata-row span').textContent(),fixture.protocol_subject);await page.getByRole('button',{name:'Копіювати',exact:true}).click();assert.equal(await page.evaluate(()=>copiedMetadata),fixture.protocol_subject);
 fs.writeFileSync(path.join(root,'evidence/filename-browser-results.json'),JSON.stringify({status:'PASS',protocol_subject:fixture.protocol_subject,metadata_copy_exact:true,suggested_filename:download.suggestedFilename(),header:fixture.headers['Content-Disposition'],body_sha256:crypto.createHash('sha256').update(bytes).digest('hex'),live_requests:0},null,2));console.log('PASS: native Chromium receives exact DOCX filename from actual server Content-Disposition; original bytes preserved; rendered/copied protocol subject uses guillemets');
 }finally{if(server)await new Promise(resolve=>server.close(resolve));await browser.close()}})().catch(e=>{console.error(e);process.exit(1)});
