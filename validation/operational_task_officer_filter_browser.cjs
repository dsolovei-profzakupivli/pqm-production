const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { chromium } = require('C:/Users/User/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');

const root = path.resolve(__dirname, '..');
const read = name => fs.readFileSync(path.join(root, name), 'utf8');
function block(source, startText, endText) {
  const start = source.indexOf(startText), end = source.indexOf(endText, start);
  assert(start >= 0 && end > start, `source block found: ${startText}`);
  return source.slice(start, end);
}

(async () => {
  const browser = await chromium.launch({
    headless: true,
    executablePath: 'C:/Users/User/AppData/Local/ms-playwright/chromium-1228/chrome-win64/chrome.exe',
    args: ['--no-sandbox']
  });
  try {
    const page = await browser.newPage({ viewport: { width: 1500, height: 960 }, timezoneId: 'Europe/Kyiv' });
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    const html = read('index.html').replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, '');
    await page.setContent(html);
    for (const name of ['styles.css', 'theme.css', 'modules.css', 'filters.css']) {
      await page.addStyleTag({ content: read(name) });
    }
    await page.evaluate(() => {
      document.querySelector('#loginGate')?.setAttribute('hidden', '');
      document.querySelector('#applicationShell')?.removeAttribute('hidden');
      document.querySelectorAll('main,[id$="View"]').forEach(node => {
        if (node.id !== 'operationalTasksView') node.hidden = true;
      });
      document.querySelector('#operationalTasksView')?.removeAttribute('hidden');
      window.$ = selector => document.querySelector(selector);
      window.$$ = selector => [...document.querySelectorAll(selector)];
      window.API = '/api';
      window.operationalTaskTypeLabels = {
        nazk_check: 'НАЗК · перевірка', amcu_exclusion: 'АМКУ · виключення',
        warning_block: 'Блокування за попередженнями', termination_exclusion: 'Припинення · виключення'
      };
      window.esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
      })[char]);
      window.formatOfficerName = value => value || '';
      window.displayDate = value => value || '';
      window.displayDateOnly = value => value || '';
      window.operationalActionColumnVisible = status => status !== 'completed';
      window.operationalTaskStatusLabel = item => item.status;
      window.operationalListAction = () => '';
      window.operationalTriggerHtml = () => '';
      window.operationalBasisHtml = () => '';
      window.operationalResultHtml = () => '';
      window.operationalDecisionHtml = () => '';
      window.operationalTaskEmptyMessage = () => 'Немає задач';
      window.__tasks = [
        { id: 'active-42', task_type: 'warning_block', status: 'new', officer: '42', assigned_officer_name: 'Ірина Мельник', supplier_name_snapshot: 'Активна задача', supplier_code: '10000001', created_at: '2026-10-18' },
        { id: 'active-43', task_type: 'warning_block', status: 'new', officer: '43', assigned_officer_name: 'Марина Шевченко', supplier_name_snapshot: 'Ще активна задача', supplier_code: '10000002', created_at: '2026-10-18' },
        { id: 'done-7', task_type: 'warning_block', status: 'completed', officer: '7', assigned_officer_name: 'Оксана Петренко', supplier_name_snapshot: 'Завершена задача', supplier_code: '10000003', created_at: '2026-10-17' },
        { id: 'nazk-9', task_type: 'nazk_check', status: 'new', officer: '9', assigned_officer_name: 'Тетяна Бондар', supplier_name_snapshot: 'НАЗК задача', supplier_code: '10000004', created_at: '2026-10-16' },
        { id: 'legacy', task_type: 'nazk_check', status: 'completed', officer: '__legacy_snapshot__:Олена Коваль', assigned_officer_name: 'Олена Коваль', supplier_name_snapshot: 'Історичне призначення', supplier_code: '10000005', created_at: '2026-10-15' },
        { id: 'unassigned', task_type: 'warning_block', status: 'new', officer: '__unassigned__', assigned_officer_name: '', supplier_name_snapshot: 'Без призначення', supplier_code: '10000006', created_at: '2026-10-14' }
      ];
      window.__officers = [
        { value: '42', full_name: 'Ірина Мельник' },
        { value: '43', full_name: 'Марина Шевченко' },
        { value: '7', full_name: 'Оксана Петренко', historical_snapshot: true },
        { value: '9', full_name: 'Тетяна Бондар' },
        { value: '__legacy_snapshot__:Олена Коваль', full_name: 'Олена Коваль', historical_snapshot: true }
      ];
      window.request = async url => {
        const params = new URL(url, 'http://pqm.local').searchParams;
        const group = params.get('status_group') || 'active';
        const officer = params.get('officer') || '';
        const type = params.get('type') || '';
        const items = __tasks.filter(item => {
          const byStatus = group === 'historical' ? ['completed', 'cancelled'].includes(item.status)
            : group === 'active' ? !['completed', 'cancelled'].includes(item.status) : item.status === group;
          return byStatus && (!officer || item.officer === officer) && (!type || item.task_type === type);
        });
        return { items, total: items.length, kpis: { active: 4, completed: 2 }, type_counts: { nazk_check: 2, warning_block: 4 }, status_group: group, officers: __officers };
      };
    });

    const app = read('app.js');
    const appSlice = [
      "let operationalTaskTimer=null;let operationalBasisDirection='';",
      block(app, 'function operationalTaskParams()', 'function operationalSummaryLink('),
      block(app, 'function operationalTaskTypeMarker(', 'function operationalTaskEmptyMessage('),
      block(app, 'function operationalTaskEmptyMessage()', 'let operationalListGeneration='),
      block(app, 'let operationalListGeneration=', "$('#operationalTasksNav').onclick=")
    ].join('\n');
    await page.addScriptTag({ content: appSlice });
    await page.addScriptTag({ content: read('operational_task_officers.js') });

    for (const theme of ['light', 'dark']) {
      for (const halloween of ['on', 'off']) {
        await page.evaluate(({ theme, halloween }) => {
          document.documentElement.dataset.theme = theme;
          document.documentElement.dataset.halloween = halloween;
        }, { theme, halloween });
        await page.locator('#operationalTaskStatus').selectOption('active');
        await page.locator('#operationalTaskOfficer').selectOption('');
        await page.evaluate(() => loadOperationalTasks());
        const labels = await page.locator('#operationalTaskOfficer option').allTextContents();
        assert.deepEqual(labels, ['Усі УО', 'Ірина Мельник', 'Марина Шевченко', 'Оксана Петренко · Історична УО', 'Тетяна Бондар', 'Олена Коваль · Історична УО', 'Не призначено']);
        for (const [value, expected] of [['42', 'active-42'], ['43', 'active-43'], ['9', 'nazk-9']]) {
          await page.locator('#operationalTaskOfficer').selectOption(value);
          await page.evaluate(() => loadOperationalTasks());
          assert.deepEqual(await page.locator('#operationalTasksBody tr[data-task-id]').evaluateAll(rows => rows.map(row => row.dataset.taskId)), [expected]);
        }
        await page.locator('#operationalTaskStatus').selectOption('completed');
        await page.locator('#operationalTaskOfficer').selectOption('7');
        await page.evaluate(() => loadOperationalTasks());
        assert.deepEqual(await page.locator('#operationalTasksBody tr[data-task-id]').evaluateAll(rows => rows.map(row => row.dataset.taskId)), ['done-7']);
        assert.equal(await page.locator('#operationalTaskOfficer').inputValue(), '7');
        await page.locator('#operationalTaskOfficer').selectOption('__legacy_snapshot__:Олена Коваль');
        await page.evaluate(() => loadOperationalTasks());
        assert.deepEqual(await page.locator('#operationalTasksBody tr[data-task-id]').evaluateAll(rows => rows.map(row => row.dataset.taskId)), ['legacy']);
        await page.locator('#operationalTaskOfficer').selectOption('__unassigned__');
        await page.locator('#operationalTaskStatus').selectOption('active');
        await page.evaluate(() => loadOperationalTasks());
        assert.deepEqual(await page.locator('#operationalTasksBody tr[data-task-id]').evaluateAll(rows => rows.map(row => row.dataset.taskId)), ['unassigned']);
      }
    }
    assert.deepEqual(errors, []);
    console.log('operational task officer browser regression: PASS (real application shell, light/dark, Halloween on/off, active/history/NAZK/unassigned filters)');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
