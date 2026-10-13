/* Read-only operator review list. No Google snapshot or planner mutation is involved. */
var PQM_PROD_UNKNOWN_REVIEW_CHUNK_SIZE = 50;

function pqmProdUnknownEligibleReviewList_(chunkIndex) {
  if (!Number.isInteger(chunkIndex) || chunkIndex < 0) {
    throw new Error('PQM PROD: invalid review chunk; no writes.');
  }
  var body = pqmProdFetchRegistry_();
  var rows = body.items.filter(function(item) {
    return item.google_sync_eligible === true && item.entity_type === 'unknown';
  }).map(function(item) {
    return {
      supplier_code: item.supplier_code,
      supplier_name: item.supplier_name || '',
      google_sync_last_decided_application_date:
        item.google_sync_last_decided_application_date || ''
    };
  });
  rows.sort(function(a, b) {
    if (a.supplier_code < b.supplier_code) return -1;
    if (a.supplier_code > b.supplier_code) return 1;
    if (a.supplier_name < b.supplier_name) return -1;
    if (a.supplier_name > b.supplier_name) return 1;
    return a.google_sync_last_decided_application_date < b.google_sync_last_decided_application_date ? -1 :
      a.google_sync_last_decided_application_date > b.google_sync_last_decided_application_date ? 1 : 0;
  });
  var uniqueCodes = new Set(rows.map(function(row) { return row.supplier_code; })).size;
  var totalChunks = Math.ceil(rows.length / PQM_PROD_UNKNOWN_REVIEW_CHUNK_SIZE);
  if (chunkIndex >= Math.max(1, totalChunks)) {
    throw new Error('PQM PROD: review chunk is out of range; no writes.');
  }
  var start = chunkIndex * PQM_PROD_UNKNOWN_REVIEW_CHUNK_SIZE;
  var result = {
    dry_run: true, google_writes: 0, db_writes: 0,
    rows: rows.length, unique_codes: uniqueCodes, duplicates: rows.length - uniqueCodes,
    chunk_index: chunkIndex, chunk_size: PQM_PROD_UNKNOWN_REVIEW_CHUNK_SIZE,
    total_chunks: totalChunks, returned_rows: rows.slice(start, start + PQM_PROD_UNKNOWN_REVIEW_CHUNK_SIZE)
  };
  console.log(JSON.stringify(result));
  return result;
}

/* Select these no-argument functions in the Apps Script editor, in order. */
function pqmProdUnknownEligibleReviewList() { return pqmProdUnknownEligibleReviewList_(0); }
function pqmProdUnknownEligibleReviewList1() { return pqmProdUnknownEligibleReviewList_(1); }
function pqmProdUnknownEligibleReviewList2() { return pqmProdUnknownEligibleReviewList_(2); }
function pqmProdUnknownEligibleReviewList3() { return pqmProdUnknownEligibleReviewList_(3); }
function pqmProdUnknownEligibleReviewList4() { return pqmProdUnknownEligibleReviewList_(4); }
function pqmProdUnknownEligibleReviewList5() { return pqmProdUnknownEligibleReviewList_(5); }
