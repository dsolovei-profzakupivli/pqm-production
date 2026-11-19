/* Local review controls only; never included by the Sandbox decorator. */
(()=>{
  const panel=document.querySelector('#halloweenLocalPreview'),host=document.querySelector('#pqmHalloweenHost');if(!panel||!host)return;
  const labels={workQueueView:'Робота УО',applicationsView:'Реєстр заявок',historyView:'Історія',suppliersView:'База постачальників',edrMonitoringView:'ЄДР',frameworkAnalyticsView:'Відбори',referencesView:'Довідники',frameworksView:'Відбори (legacy)',procurementsView:'Закупівлі',messagesView:'Повідомлення',administrationView:'Адміністрування',requestsView:'Звернення',operationalTasksView:'Операційні задачі'};
  const reasons={'clear-sky':'Політ позаду кнопок і KPI','no-halloween-landscape':'Призупинено: тут немає Halloween-пейзажу','sky-too-short':'Призупинено: недостатня висота наявного неба','working-elements-in-sky':'Призупинено: у смузі неба розміщені робочі елементи','dialog-open':'Призупинено: відкрите діалогове вікно','no-active-view':'Призупинено: немає активної сторінки'};
  const select=document.createElement('select');select.id='previewView';select.style.cssText='display:block;width:100%;margin:8px 0';
  select.innerHTML=Object.entries(labels).map(([id,label])=>`<option value="${id}">${label}</option>`).join('');panel.prepend(select);
  select.onchange=()=>document.querySelectorAll('main').forEach(e=>e.hidden=e.id!==select.value);
  const status=document.createElement('p');status.style.cssText='max-width:420px;margin:8px 0';panel.append(status);
  const detail=document.createElement('p');detail.style.cssText='max-width:360px;margin:8px 0';detail.textContent='Два плавні маневри · адаптивна амплітуда 0–20 px. Котик підморгує одним оком раз на 40–60 с та іноді після польоту.';panel.append(detail);
  const review=document.createElement('a');review.href='evidence/halloween-maneuvers/index.html';review.textContent='Відео польотів і збільшені кадри котика';panel.append(review);
  const render=()=>{status.textContent=document.documentElement.dataset.halloween!=='on'?'Halloween вимкнено':reasons[host.dataset.reason]||'Перевірка безпечної зони'};
  new MutationObserver(render).observe(host,{attributes:true,attributeFilter:['data-reason','data-view']});new MutationObserver(render).observe(document.documentElement,{attributes:true,attributeFilter:['data-halloween']});render();
})();
