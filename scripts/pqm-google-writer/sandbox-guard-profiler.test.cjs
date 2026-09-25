const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');
const vm = require('node:vm');
const crypto = require('node:crypto');

const source = ['PqmSandboxPreviewDependencies.gs', 'PqmSandboxPreview.gs',
  'PqmSandboxControlledApply.gs', 'PqmSandboxFullApply.gs']
  .map(name => fs.readFileSync(__dirname + '/' + name, 'utf8')).join('\n');
const clone = value => JSON.parse(JSON.stringify(value));

function fixture(settings = {}) {
  const calls = [], logs = [];
  const rowCount = settings.rowCount || 3;
  const context = {Date, Map, Set, console: {log: value => logs.push(value)}};
  vm.createContext(context);
  vm.runInContext(source, context);
  const id = context.PQM_SANDBOX_CONTROLLED_SPREADSHEET_ID;
  context.SpreadsheetApp = {getActiveSpreadsheet: () => ({getId: () => id})};
  context.Utilities = {DigestAlgorithm: {SHA_256: 'SHA_256'}, Charset: {UTF_8: 'UTF_8'},
    computeDigest: (_, value) => crypto.createHash('sha256').update(value).digest(),
    base64EncodeWebSafe: value => Buffer.from(value).toString('base64url'), sleep: () => {}};
  const row = code => {
    const values = Array(15).fill('');
    values[0] = 'untouched-marker'; values[1] = code;
    values[2] = 'Verified'; values[5] = 'Active'; values[7] = 46287;
    return values;
  };
  const tabNames = ['ФОП', 'ЮО'];
  const rows = {'ФОП': row('1000000000'), 'ЮО': row('12345678')};
  const formulas = settings.formulas || {};
  const displays = settings.displays || {};
  const formulaCell = (name, column) => ({userEnteredValue: formulas[name]?.[column]
    ? {formulaValue: formulas[name][column]} : {}});
  context.Sheets = {Spreadsheets: {
    get: (_id, options) => {
      calls.push({api: 'Spreadsheets.get', options: clone(options)});
      if (options.includeGridData === false) return {sheets: tabNames.map((name, index) => ({
        properties: {title: name, sheetId: index + 1, gridProperties: {rowCount}},
        merges: [], protectedRanges: [], conditionalFormats: []
      }))};
      const match = /^'(ФОП|ЮО)'!([A-Z])(\d+):([A-Z])(\d+)$/.exec(options.ranges[0]);
      assert.ok(match);
      if (match[2] === 'H') {
        assert.ok(options.ranges.length <= 8);
        assert.ok(options.ranges.every(range => /^'(ФОП|ЮО)'![HI]\d+:[HI]\d+$/.test(range)));
        assert.doesNotMatch(options.fields, /formattedValue|effectiveValue|dataValidation|note/);
        return {sheets: [{data: options.ranges.map(range => {
          const m = /^'(ФОП|ЮО)'!([HI])(\d+):[HI](\d+)$/.exec(range);
          const column = m[2] === 'H' ? 7 : 8;
          const dateData = Number(m[3]) === 2 ? [{values: [{...formulaCell(m[1], column),
            userEnteredFormat: {numberFormat: {pattern: settings.dateFormats?.[m[1]] || 'dd.MM.yyyy'}}}]}] : [];
          return {startRow: Number(m[3]) - 1, startColumn: column, rowData: dateData};
        })}]};
      }
      if (options.fields.includes('formulaValue')) {
        assert.doesNotMatch(options.fields, /formattedValue|effectiveValue|dataValidation|note/);
        return {sheets: [{data: Array.from(options.ranges, range => {
          const letter = range.split('!')[1][0], column = {A: 0, B: 1, C: 2, E: 4, F: 5, L: 11}[letter];
          assert.ok(column !== undefined);
          return {startRow: Number(match[3]) - 1, startColumn: column,
            rowData: Number(match[3]) === 2 ? [{values: [formulaCell(match[1], column)]}] : []};
        })}]};
      }
      assert.equal(options.ranges[0], `'${match[1]}'!A2:A2`);
      return {sheets: [{data: [{startRow: 1, rowMetadata: [{pixelSize: 25}]}]}]};
    },
    Values: {get: (_id, range, options) => {
      calls.push({api: 'Values.get', range, options: clone(options)});
      const name = /^'(ФОП|ЮО)'!/.exec(range)[1];
      if (range.endsWith('A1:O1')) return {values: [Array.from(context.PQM_GOOGLE_HEADERS)]};
      if (/!B\d+:B\d+$/.test(range)) return {values: range.includes('!B2:') ? [[displays[name] || rows[name][1]]] : []};
      assert.match(range, new RegExp(`^'${name}'!A\\d+:O\\d+$`));
      return {values: range.includes('!A2:') ? [rows[name]] : []};
    }, batchGet: (_id, options) => {
      calls.push({api: 'Values.batchGet', options: clone(options)});
      return {valueRanges: options.ranges.map(range => {
        const m = /^'(ФОП|ЮО)'!([A-O])(\d+):([A-O])(\d+)$/.exec(range);
        assert.ok(m);
        const name = m[1], start = Number(m[3]);
        if (range.endsWith('A1:O1')) return {values: [Array.from(context.PQM_GOOGLE_HEADERS)]};
        if (options.valueRenderOption === 'UNFORMATTED_VALUE') {
          assert.equal(m[2], 'A'); assert.equal(m[4], 'O');
          return {values: start === 2 ? [rows[name]] : []};
        }
        if (options.valueRenderOption === 'FORMATTED_VALUE') {
          assert.equal(m[2], 'B'); assert.equal(m[4], 'B');
          return {values: start === 2 ? [[displays[name] || rows[name][1]]] : []};
        }
        assert.equal(options.valueRenderOption, 'FORMULA');
        const column = {A: 0, B: 1, C: 2, E: 4, F: 5, L: 11}[m[2]];
        assert.ok(column !== undefined);
        return {values: start === 2 ? [[formulas[name]?.[column] || rows[name][column]]] : []};
      })};
    }}
  }};
  context.pqmSandboxFetchRegistry_ = () => ({count: 2, items: tabNames.map((name, index) => ({
    supplier_code: displays[name] || String(rows[name][1]), entity_type: index ? 'legal_entity' : 'individual_entrepreneur',
    monitoring_eligible: true, google_sync_eligible: true,
    freshness_marker: 'fresh', supplier_name: 'Verified',
    edr_status_current: null, verification_date: null, verification_officer: null,
    prozorro_status_google: 'Active', last_application_date: '2026-09-22',
    google_sync_last_decided_application_date: '2026-09-22'
  }))});
  return {context, calls, logs, id, rows, formulas, displays};
}

test('profiler repeats the exact initial Google read paths and never invokes a write API', () => {
  const f = fixture();
  const loaded = f.context.pqmSandboxFullLoad_(f.id);
  const loadCalls = clone(f.calls);
  f.calls.length = 0;
  const diagnostic = f.context.pqmSandboxProfileInitialGoogleGuard();
  assert.deepEqual(f.calls, loadCalls);
  assert.equal(diagnostic.google_writes, 0);
  assert.equal(diagnostic.dry_run, true);
  assert.equal(f.calls.length, 11);
  assert.equal(diagnostic.phases.sheet_metadata.calls, 1);
  assert.equal(diagnostic.phases.header_values_A1_O1, undefined);
  assert.equal(diagnostic.phases.data_values_A_O.calls, 2);
  assert.equal(diagnostic.phases.formatted_code_B.calls, 2);
  assert.equal(diagnostic.phases.formula_values_A_B_C_E_F_L.calls, 2);
  assert.equal(diagnostic.phases.grid_metadata_H_I.calls, 2);
  assert.equal(diagnostic.phases.template_row_height.calls, 2);
  assert.equal(diagnostic.phases.data_values_A_O.requested_cells, 90);
  assert.equal(diagnostic.phases.grid_metadata_H_I.requested_cells, 8);
  assert.equal(diagnostic.phases.formula_disambiguation_A_B_C_E_F_L, undefined);
  assert.ok(f.calls.every(call => !JSON.stringify(call).includes('!A2:H3')));
  assert.equal(typeof diagnostic.phases.google_state_digest.total_ms, 'number');
  assert.equal(f.logs.length, 1);
  assert.equal(f.logs[0].includes('1000000000'), false);
  assert.equal(f.logs[0].includes('Verified'), false);
  assert.equal(loaded.timing_ms.initial_google_phases.sheet_metadata.calls, 1);
});

test('narrow snapshot preserves formatted B, exact formulas and H format with old contract parity', () => {
  const formulaMap = {'ФОП': {0: '=NOW()', 1: '=TEXT(1)', 2: '=LOWER("X")',
    5: '=UPPER("active")', 7: '=DATE(2026,9,22)'}};
  const f = fixture({formulas: formulaMap, displays: {'ЮО': '00001234'}});
  f.rows['ЮО'][1] = 1234;
  const phases = {}, tabs = f.context.pqmGoogleSnapshot_(f.id, phases);
  const fop = tabs['ФОП'].rows[0], legal = tabs['ЮО'].rows[0];
  assert.equal(legal.values[1], 1234);
  assert.equal(legal.codeDisplay, '00001234');
  assert.equal(fop.dateFormat, 'dd.MM.yyyy');
  assert.deepEqual(Array.from(fop.formulas).filter(Boolean),
    ['=NOW()', '=TEXT(1)', '=LOWER("X")', '=UPPER("active")', '=DATE(2026,9,22)']);
  assert.equal(phases.grid_metadata_H_I.calls, 2);
  assert.equal(phases.formula_disambiguation_A_B_C_E_F_L.calls, 1);
  assert.equal(phases.formula_disambiguation_A_B_C_E_F_L.requested_cells, 8);

  const expected = {};
  ['ФОП', 'ЮО'].forEach((name, index) => {
    const formulas = Array(15).fill('');
    Object.entries(formulaMap[name] || {}).forEach(([column, formula]) => {formulas[Number(column)] = formula;});
    expected[name] = {id: index + 1, maxRows: 3, headers: Array.from(f.context.PQM_GOOGLE_HEADERS),
      rows: [{values: f.rows[name], formulas, codeDisplay: f.displays[name] || String(f.rows[name][1]),
        dateFormat: 'dd.MM.yyyy', verificationDateFormat: 'dd.MM.yyyy'}], templateRowHeight: 25,
      merges: [], protectedRanges: [], conditionalFormats: []};
  });
  assert.deepEqual(clone(tabs), expected);
  const body = f.context.pqmSandboxFetchRegistry_();
  assert.deepEqual(clone(f.context.pqmGooglePlan_(body, tabs)), clone(f.context.pqmGooglePlan_(body, expected)));
  assert.deepEqual(clone(f.context.pqmSandboxFullState_(body, tabs, f.context.pqmGooglePlan_(body, tabs))),
    clone(f.context.pqmSandboxFullState_(body, expected, f.context.pqmGooglePlan_(body, expected))));
});

test('literal text beginning with equal sign is disambiguated and never mistaken for a formula', () => {
  const f = fixture();
  f.rows['ФОП'][2] = '=literal text';
  const phases = {}, tabs = f.context.pqmGoogleSnapshot_(f.id, phases);
  assert.equal(tabs['ФОП'].rows[0].values[2], '=literal text');
  assert.equal(tabs['ФОП'].rows[0].formulas[2], '');
  assert.equal(phases.formula_disambiguation_A_B_C_E_F_L.calls, 1);
  assert.equal(phases.formula_disambiguation_A_B_C_E_F_L.requested_cells, 2);
});

test('optimized snapshot detects E/I/L formulas and planner fails closed', () => {
  for (const column of [4, 8, 11]) {
    const formulas = {'ФОП': {[column]: '=NA()'}};
    const f = fixture({formulas});
    const tabs = f.context.pqmGoogleSnapshot_(f.id);
    assert.equal(tabs['ФОП'].rows[0].formulas[column], '=NA()');
    const plan = f.context.pqmGooglePlan_(f.context.pqmSandboxFetchRegistry_(), tabs);
    assert.equal(plan.counts.conflicts, 1);
    assert.equal(plan.changes.some(change => change.tab === 'ФОП'), false);
  }
});

test('B literal text beginning with equal sign triggers only targeted clarification', () => {
  const f = fixture();
  f.rows['ФОП'][1] = '=literal-code';
  const phases = {}, tabs = f.context.pqmGoogleSnapshot_(f.id, phases);
  assert.equal(tabs['ФОП'].rows[0].codeDisplay, '=literal-code');
  assert.equal(tabs['ФОП'].rows[0].formulas[1], '');
  assert.equal(phases.formula_disambiguation_A_B_C_E_F_L.calls, 1);
  assert.equal(phases.formula_disambiguation_A_B_C_E_F_L.requested_cells, 2);
  assert.equal(phases.grid_metadata_H_I.calls, 2);
});

test('H serial, dd.MM.yyyy and ISO values compare by calendar date while custom format stays in digest', () => {
  for (const dateValue of [46287, '22.09.2026', '2026-09-22']) {
    const f = fixture({dateFormats: {'ФОП': 'yyyy-mm-dd'}});
    f.rows['ФОП'][7] = dateValue;
    const tabs = f.context.pqmGoogleSnapshot_(f.id);
    assert.equal(tabs['ФОП'].rows[0].dateFormat, 'yyyy-mm-dd');
    const body = f.context.pqmSandboxFetchRegistry_();
    const plan = f.context.pqmGooglePlan_(body, tabs);
    assert.equal(plan.changes.some(change => change.tab === 'ФОП' && '7' in change.cells), false);
    const digest = f.context.pqmSandboxFullState_(body, tabs, plan).google_digest;
    tabs['ФОП'].rows[0].dateFormat = 'dd.MM.yyyy';
    assert.notEqual(f.context.pqmSandboxFullState_(body, tabs, plan).google_digest, digest);
  }
});

test('large tabs keep mandatory grid reads bounded to H and avoid broad append-template metadata', () => {
  const f = fixture({rowCount: 7500});
  const phases = {}, tabs = f.context.pqmGoogleSnapshot_(f.id, phases);
  assert.equal(phases.grid_metadata_H_I.calls, 4);
  assert.equal(phases.grid_metadata_H_I.requested_cells, (7500 - 1) * 4);
  assert.equal(phases.grid_metadata_H_I.requested_ranges, 32);
  assert.equal(phases.formula_disambiguation_A_B_C_E_F_L, undefined);
  assert.equal(tabs['ФОП'].rows.length, 1);
  const grids = f.calls.filter(call => call.api === 'Spreadsheets.get' && call.options.includeGridData === true);
  assert.ok(grids.every(call => call.options.ranges.every(range =>
    /![HI]\d+:[HI]\d+$/.test(range) || /!A2:A2$/.test(range))));
  assert.equal(grids.filter(call => call.options.ranges.some(range => /!A2:A2$/.test(range))).length, 2,
    'only cheap targeted row-height metadata remains for guard digest parity');
});

test('optional profiling preserves the exact snapshot and Google guard digest', () => {
  const f = fixture(), plain = f.context.pqmGoogleSnapshot_(f.id), phases = {};
  const profiled = f.context.pqmGoogleSnapshot_(f.id, phases);
  assert.deepEqual(clone(profiled), clone(plain));
  const body = f.context.pqmSandboxFetchRegistry_();
  const plan = f.context.pqmGooglePlan_(body, plain);
  const plainState = f.context.pqmSandboxFullState_(body, plain, plan);
  const profiledState = f.context.pqmSandboxFullState_(body, profiled, plan, phases);
  assert.deepEqual(clone(profiledState), clone(plainState));
  assert.equal(f.context.pqmSandboxFullDigest_(profiledState), f.context.pqmSandboxFullDigest_(plainState));
});

test('large snapshot batches reads into at most 17 bounded requests', () => {
  const f = fixture({rowCount: 7500});
  f.context.pqmGoogleSnapshot_(f.id);
  assert.equal(f.calls.length, 17);
  assert.equal(f.calls.filter(call => call.api === 'Values.get').length, 0);
  const values = f.calls.filter(call => call.api === 'Values.batchGet');
  assert.equal(values.length, 10);
  assert.ok(values.filter(call => call.options.valueRenderOption === 'UNFORMATTED_VALUE')
    .every(call => call.options.ranges.length <= 4));
  assert.ok(values.filter(call => call.options.valueRenderOption === 'FORMULA')
    .every(call => call.options.ranges.length <= 48));
  const grids = f.calls.filter(call => call.api === 'Spreadsheets.get' &&
    call.options.includeGridData && call.options.ranges[0].includes('!H'));
  assert.equal(grids.length, 4);
  assert.ok(grids.every(call => call.options.ranges.length <= 8));
  assert.ok(grids.every(call => call.options.ranges.every(range => /![HI]\d+:[HI]\d+$/.test(range))));
});

test('only read quota errors retry; semantic errors never retry', () => {
  const f = fixture();
  let attempts = 0, sleeps = 0;
  f.context.Utilities.sleep = () => { sleeps++; };
  const value = f.context.pqmGoogleReadRetry_(() => {
    if (++attempts < 3) throw new Error("Quota exceeded for quota metric 'Read requests'");
    return 'ok';
  });
  assert.equal(value, 'ok'); assert.equal(attempts, 3); assert.equal(sleeps, 2);
  attempts = 0;
  assert.throws(() => f.context.pqmGoogleReadRetry_(() => {
    attempts++; throw new Error('PQM: header mismatch');
  }), /header mismatch/);
  assert.equal(attempts, 1);
});

test('exhausted read quota fails closed without invoking any write API', () => {
  const f = fixture();
  let attempts = 0;
  f.context.Sheets.Spreadsheets.get = () => {
    attempts++; throw new Error("Quota exceeded for quota metric 'Read requests'");
  };
  f.context.Sheets.Spreadsheets.batchUpdate = () => assert.fail('write must not happen');
  assert.throws(() => f.context.pqmSandboxFullLoad_(f.id), /Quota exceeded/);
  assert.equal(attempts, 4);
});
