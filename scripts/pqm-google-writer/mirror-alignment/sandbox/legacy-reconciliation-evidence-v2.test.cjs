const assert=require('node:assert/strict');
const crypto=require('node:crypto');
const fs=require('node:fs');
const path=require('node:path');
const test=require('node:test');
const vm=require('node:vm');

const dir=__dirname;
const requestId='592128d9837d4b71bbeb330ef8aabf4b';
const fingerprint='816c6424279bff220878b0c4';
const expectedDigest='fZMBd2VUbFFwRrZ67z4ODWzcoSA2yWVOPw8jAFEGmss';

function loadSandboxSource() {
  const context=vm.createContext({Date,Map,Set,JSON,Math,Object,Array,String,Number,RegExp,Error,
    console:{log(){}},Logger:{log(){}}});
  for(const file of fs.readdirSync(dir).filter(name=>name.endsWith('.gs')))
    vm.runInContext(fs.readFileSync(path.join(dir,file),'utf8'),context,{filename:file});
  context.Utilities={
    DigestAlgorithm:{SHA_256:'sha256'},Charset:{UTF_8:'utf8'},
    computeDigest:(algorithm,value,charset)=>Array.from(
      crypto.createHash(algorithm).update(value,charset||'utf8').digest()),
    base64EncodeWebSafe:bytes=>Buffer.from(bytes).toString('base64url')
  };
  return context;
}

test('active legacy profile is exact evidence v2 and matches its canonical digest',()=>{
  const context=loadSandboxSource();
  const profile=context.pqmSandboxPartialReconciliationProfile_(fingerprint);
  assert.ok(profile);
  assert.equal(profile.expectedRequestId,requestId);
  assert.equal(profile.profileVersion,2);
  assert.deepEqual(JSON.parse(JSON.stringify(profile.evidence)),{
    evidence_version:2,
    request_id:requestId,
    plan_scope:'APPEND_ONLY',
    initial_plan:{append:326,update:2,conflict:2},
    attempted_chunk:0,
    checkpoint_present:false,
    saved_preview_source_digest:{present:false,historical_schema:'PRE_SOURCE_DIGEST',substitute_used:false},
    audit_type:'READ_ONLY_SAVED_PREVIEW_AND_LIVE_SHEETS',
    audit:{rows_found:25,full_matches:25,partial_rows:0,
      partial_operation_numbers:[],partial_columns:{I:0},missing:0,duplicates:0,
      wrong_tab:0,formula_a_matches:25,protected_cell_mutations:0,
      saved_preview_binding:'PASS',writes_performed:0},
    recovery_disposition:'FULL_FIRST_CHUNK_MATCH_NO_REAPPEND_NEW_PREVIEW_REQUIRED'
  });
  assert.equal(context.pqmSandboxReconciliationDigest_(profile.evidence),expectedDigest);
  assert.deepEqual(JSON.parse(JSON.stringify(profile.resultCounts)),{
    rows_found:25,fully_matching_rows:25,partial_rows:0,
    unverified_column_i_rows:0,checkpoint_receipts:0
  });
  assert.deepEqual(JSON.parse(JSON.stringify(profile.receiptFields)),{
    checkpointPresent:false,resumeAuthorized:false,nextAction:'NEW_PREVIEW_REQUIRED',
    partialOperationNumbers:[]
  });
  assert.equal(context.pqmSandboxPartialReconciliationProfile_('0'.repeat(24)),null);
});

test('historic v1 20+5 remains archived and is not the active execution profile',()=>{
  const context=loadSandboxSource();
  const archived=context.pqmSandboxPartialReconciliationLegacy20261108V1Archive_();
  assert.equal(archived.status,'RETIRED_INVALID_DATE_NORMALIZATION_EVIDENCE');
  assert.equal(archived.profile.evidence.evidence_version,1);
  assert.equal(archived.profile.evidence.audit.full_matches,20);
  assert.equal(archived.profile.evidence.audit.partial_rows,5);
  assert.deepEqual(Array.from(archived.profile.evidence.audit.partial_operation_numbers),[6,12,14,17,25]);
  assert.equal(context.pqmSandboxPartialReconciliationProfile_(fingerprint).evidence.evidence_version,2);
});
