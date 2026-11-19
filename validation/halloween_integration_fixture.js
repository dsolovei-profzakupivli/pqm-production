/* Presentation fixture only: no application scripts, API, DB or profile writes. */
globalThis.HalloweenIntegrationFixture={install({panel=true}={}){
  document.querySelector('#loginGate').hidden=true;document.querySelector('#applicationShell').hidden=false;
  document.querySelectorAll('main').forEach(e=>e.hidden=e.id!=='workQueueView');
  const applyTheme=value=>{PqmThemeUI.apply(value);if(location.protocol==='file:')for(const logo of document.querySelectorAll('img.sandbox-brand-initials'))logo.setAttribute('src',logo.getAttribute('src').replace(/^\/assets\//,'assets/'))};
  PqmThemeUI.install();applyTheme('light');
  const nav=document.querySelector('#mainNav');
  if(!nav.querySelector('button'))nav.innerHTML='<button class="nav-active">Робота УО</button><button>Реєстр заявок</button><button>База постачальників</button><button>Операційні задачі</button>';
  for(const [id,n] of Object.entries({queueKpiTotal:24,queueKpiNazk:8,queueKpiViolation:5,queueKpiWaiting:7,queueKpiOverdue:2,queueProtocolTotal:72,queueQualificationTotal:28}))document.getElementById(id).textContent=n;
  for(const id of ['queueQualificationCards','queueProtocolOfficerCards','queueCategoryCards','queueProtocolCategoryCards']){
    const category=id.includes('Category');document.getElementById(id).innerHTML=(category?['Продукти','Інше','Газ/ЕЕ','Пальне']:['Тестова УО 1','Тестова УО 2']).map((name,i)=>`<button type="button" class="qualification-summary-officer ${category?'qualification-summary-category':''}"><span>${name}</span><strong>${16-i*2}</strong><small>Демонстраційна вибірка</small></button>`).join('');
  }
  document.querySelector('#queuePublicationControl').innerHTML='<button data-publication-state="active"><span>Допущено</span><strong>48</strong></button><button data-publication-state="unsuccessful"><span>Відхилено</span><strong>7</strong></button><button data-publication-state="pending"><span>Все ще очікує рішення</span><strong>17</strong></button>';
  document.querySelector('#queueProtocolFrom').value='2026-10-01';document.querySelector('#queueProtocolTo').value='2026-10-19';
  if(panel){const el=document.createElement('aside');el.id='halloweenLocalPreview';el.style.cssText='position:fixed;right:12px;bottom:60px;z-index:100001;background:#fff;color:#172840;border:1px solid #8191a8;border-radius:10px;padding:12px;font:13px system-ui';
    el.innerHTML='Локальний Sandbox · демонстраційні дані <button id="previewLight">Світла</button> <button id="previewDark">Темна</button><label style="display:block"><input type="checkbox" id="previewHalloween" checked> Halloween</label><small>Одна відьма · пауза 20–30 с</small>';
    document.body.append(el);el.querySelector('#previewLight').onclick=()=>applyTheme('light');el.querySelector('#previewDark').onclick=()=>applyTheme('dark');el.querySelector('#previewHalloween').onchange=e=>{const input=document.querySelector('#halloweenDecorationEnabled');input.checked=e.target.checked;input.dispatchEvent(new Event('change'))};
  }
}};
