"""Local visual review only; consumes browser evidence, never touches runtime data."""
import html
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
out = root / 'evidence/halloween-maneuvers'
matrix = json.loads((root / 'evidence/halloween-shared/MATRIX.json').read_text(encoding='utf-8'))
eyes = json.loads((out / 'cat-eye-checks.json').read_text(encoding='utf-8'))
labels = dict(workQueueView='Робота УО', applicationsView='Реєстр заявок', historyView='Історія',
              suppliersView='База постачальників', edrMonitoringView='ЄДР', frameworkAnalyticsView='Відбори',
              referencesView='Довідники', frameworksView='Відбори (legacy)', procurementsView='Закупівлі',
              messagesView='Повідомлення', administrationView='Адміністрування', requestsView='Звернення',
              operationalTasksView='Операційні задачі')
parts = ['''<!doctype html><html lang="uk"><meta charset="utf-8"><title>Halloween — маневри та підморгування</title>
<style>body{font:16px/1.5 system-ui;margin:30px auto;padding:0 20px;max-width:1280px;background:#f4f6fa;color:#172840}video{width:100%;background:#102239;border-radius:10px}section{background:white;padding:20px;border-radius:12px;margin:20px 0}h1,h2{line-height:1.2}a{color:#075bb1}table{border-collapse:collapse;width:100%}td,th{border:1px solid #a8b6c6;padding:10px;text-align:left}.frames{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,480px),1fr));gap:16px}.frames img{width:100%;height:auto}figure{margin:0}figcaption{font-weight:600;margin:8px 0}</style>
<h1>Хвилеподібні маневри й хитре підморгування</h1>
<p>Локальний прототип від <code>d3f9965ba13ec199aa6323a7c46fd41f6e9ad408</code>. Без commit, push, merge, deploy або restart.</p>
<p><a href="../halloween-shared/index.html">Відкрити інтерактивний прототип із перемикачем вкладок і тем</a></p>
<section><h2>Обидві відьми</h2><p>Перша: підйом → зниження → повторний підйом. Друга: зниження → підйом → зниження. Амплітуда 0–20 CSS px за висотою заголовкового неба; на «Історії» — пряма траєкторія. Горизонтальна швидкість, розмір, силуети, повний вихід за лівий край та золотий шлейф збережені.</p>
<p>Для запису скорочено лише очікування між польотами. Самі польоти записані зі звичайною швидкістю. У прототипі паузи залишаються 20–30 секунд.</p>''']
for theme, label in [('light', 'Світла тема'), ('dark', 'Темна тема')]:
    parts.append(f'<h3>{label}</h3><video controls preload="metadata" src="{theme}-both-witches.webm"></video>')
parts.append('</section><section><h2>Очі котика — збільшені браузерні кадри</h2><p>Оригінальний WebP не змінювався. Одне око закривається на 420 мс, друге залишається відкритим. Один спільний таймер повік узгоджує підморгування та звичайне моргання. Підморгування — раз на 40–60 с; випадкова реакція після польоту має захист від надто частого повторення.</p><p>Для кадрів тестовий годинник переводить контролер до потрібного моменту; закриту повіку зафіксовано посеред справжньої анімації. Сам прототип працює зі звичайними інтервалами. Ліве/праве — з боку глядача.</p>')
states = [('open', 'Обидва ока відкриті'), ('wink-left', 'Ліве око підморгує'),
          ('wink-right', 'Праве око підморгує'), ('both-blink', 'Звичайне моргання обома очима'),
          ('tracks-witch', 'Проводжає відьму поглядом'), ('return-center', 'Погляд повернувся в центр'),
          ('after-flight-wink', 'Підморгування після польоту')]
for theme, label in [('light', 'Світла тема'), ('dark', 'Темна тема')]:
    parts.append(f'<h3>{label}</h3><div class="frames">')
    for key, caption in states:
        name = f'{theme}-cat-{key}.png'
        parts.append(f'<figure><figcaption>{caption}</figcaption><a href="{name}"><img src="{name}" alt="{caption}"></a></figure>')
    parts.append('</div>')
parts.append('</section><section><h2>Матриця вкладок</h2><p>78 комбінацій: 13 вкладок × 2 теми × (1440 px / 100%, 1440 px / 125%, 390 px / 100%). Нижче — амплітуда за ширини 1440 px, масштаб 100%.</p><table><tr><th>Вкладка</th><th>Світла</th><th>Темна</th></tr>')
for view, label in labels.items():
    parts.append('<tr><th>' + html.escape(label) + '</th>')
    for theme in ['light', 'dark']:
        x = next(x for x in matrix['matrix'] if x['view'] == view and x['theme'] == theme and x['width'] == 1440 and x['zoom'] == 1)
        if x['safe']:
            amp = round((x['host'][3] / x['zoom'] - 86) / 2, 1)
            text = f'Політ: {amp:g} px' if amp else 'Політ: пряма траєкторія'
        else:
            text = 'Немає Halloween-пейзажу'
        parts.append(f'<td><a href="../halloween-shared/{theme}-{view}.png">{text}</a></td>')
    parts.append('</tr>')
parts.append('''</table><p>PASS: геометрія, кольори й прокручування без змін; кнопки та KPI поверх декоративного шару; один host, один цикл, не більше одного canvas/RAF. Переходи між вкладками не скидають паузу чи поточний політ. Перевірені Halloween on/off, Europe/Kyiv та reduced motion.</p>
<p>PASS: підморгування обох очей окремо, звичайне моргання, інтервали 40–60 с, повернення погляду перед реакцією, випадковий пропуск реакції, захист від частого повторення, один таймер повік на всіх вкладках, скасування активних повік при reduced motion. 10 адресних тестів контрактів інтеграції та персональних тем — PASS.</p>
<p>Бізнес-скрипти в браузерній демонстрації заблоковані. Повний Release Gate для цих локальних змін не запускався. Опублікований candidate та Live не змінені.</p>
<p><a href="cat-eye-checks.json">Перевірки котика</a> · <a href="motion-checks.json">Вибірки траєкторій</a> · <a href="../halloween-shared/MATRIX.json">Повна матриця</a> · <a href="../halloween-shared/BUTTON-LAYERS.json">Порядок шарів</a></p></section></html>''')
(out / 'index.html').write_text(''.join(parts), encoding='utf-8')
print(out / 'index.html')
