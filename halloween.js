/* Production Halloween decoration only. One bounded calendar timer, no API/profile writes. */
(()=>{
  if(document.documentElement.dataset.pqmHalloweenTarget!=='production')return;
  const title=document.querySelector('.prod-brand-copy strong');
  const key='pqm.halloween.cat.enabled.v1';
  let preferred=true,enabled=false,seasonTimer=null,input=null,hint=null,caption=null,catImage=null;
  try{preferred=localStorage.getItem(key)!=='0'}catch{/* Private storage may be unavailable. */}
  let refreshSpider=()=>{};
  let refreshHat=()=>{};
  let refreshQueueBackground=()=>{};
  const season=()=>globalThis.PqmHalloweenSeason?.state(new Date())||{available:false,nextTransitionAt:null};
  const synchronize=()=>{
    if(seasonTimer!==null)clearTimeout(seasonTimer);
    const current=season();enabled=current.available&&preferred;
    document.documentElement.dataset.pqmCat=preferred?'on':'off';
    document.documentElement.dataset.halloween=enabled?'on':'off';
    if(input){input.checked=preferred;input.title=current.available?'Керує Halloween-оформленням і котиком':'Керує видимістю котика PQM'}
    if(caption)caption.textContent=current.available?'Halloween · святкове оформлення':'Котик PQM';
    if(hint)hint.textContent=current.available?'Святкове оформлення й котик у цьому браузері':'Видимість котика в цьому браузері';
    if(catImage){const source=current.available?'assets/halloween-witch-cat.webp':'assets/pqm-cat-no-hat.png';if(!catImage.getAttribute('src')?.endsWith(source))catImage.src=source}
    refreshSpider();refreshHat();refreshQueueBackground();
    // Minute checks handle clock adjustments; the final callback targets midnight.
    const delay=Math.max(1,Math.min(60000,(current.nextTransitionAt??(Date.now()+60000))-Date.now()));
    seasonTimer=setTimeout(synchronize,delay);
  };
  synchronize();
  if(title){
  title.classList.add('halloween-title');
  catImage=document.createElement('img');catImage.className='halloween-cat';catImage.width=720;catImage.height=389;catImage.alt='';catImage.setAttribute('aria-hidden','true');catImage.draggable=false;
  catImage.src=season().available?'assets/halloween-witch-cat.webp':'assets/pqm-cat-no-hat.png';title.append(catImage);
  }
  const nav=document.querySelector('#mainNav');
  if(nav){
    const spider=document.createElement('span');spider.className='halloween-spider';
    spider.setAttribute('aria-hidden','true');spider.hidden=true;
    spider.innerHTML='<svg viewBox="0 0 12 12" focusable="false"><g fill="#101116" stroke="#8996a8" stroke-width=".65" stroke-linecap="round"><path d="M4 4L1 1M4 6L1 5M4 8L1 11M8 4L11 1M8 6L11 5M8 8L11 11"/><ellipse cx="6" cy="7" rx="3" ry="4"/><circle cx="6" cy="3" r="2.4"/></g><g fill="#ff9b32"><circle cx="5" cy="3" r=".65"/><circle cx="7" cy="3" r=".65"/></g></svg>';
    document.body.append(spider);
    refreshSpider=()=>{
      // Scale only the live digits' paint, retaining the original badge layout.
      for(const badge of nav.querySelectorAll('.action-count-badge')){
        if(!/^\d+$/.test(badge.textContent)||badge.firstElementChild?.classList.contains('halloween-count-number'))continue;
        const number=document.createElement('span');number.className='halloween-count-number';
        number.textContent=badge.textContent;badge.replaceChildren(number);
      }
      const button=nav.querySelector('button.nav-active');
      if(!enabled||!button){spider.hidden=true;return}
      const b=button.getBoundingClientRect(),n=nav.getBoundingClientRect();
      const zoom=parseFloat(getComputedStyle(document.body).zoom)||1;
      const width=button.clientWidth;
      // Geometry, never tab names: 38px icon button → 22px web; wide → 44px.
      button.style.setProperty('--halloween-web-width',Math.min(width-2,Math.max(20,Math.min(44,22+Math.max(0,width-72)*.5)))+'px');
      const content=document.createRange();content.selectNodeContents(button);
      const bounds=content.getBoundingClientRect();
      const topGap=Math.max(2,(bounds.top-b.top)/zoom-1);
      button.style.setProperty('--halloween-web-height',Math.min(14,topGap)+'px');
      const x=b.left+4;
      spider.hidden=!b.width||!b.height||x<n.left+2||x>n.right-8||b.top<0||b.bottom+22>innerHeight;
      if(spider.hidden)return;
      spider.style.left=(x/zoom-6)+'px';spider.style.top=((b.top+2)/zoom)+'px';
      spider.style.height=((b.height+19)/zoom)+'px';
    };
    let queued=false;
    const schedule=()=>{if(queued)return;queued=true;requestAnimationFrame(()=>{queued=false;refreshSpider()})};
    new MutationObserver(schedule).observe(nav,{attributes:true,attributeFilter:['class'],childList:true,subtree:true});
    new ResizeObserver(schedule).observe(nav);
    nav.addEventListener('scroll',schedule,{passive:true});
    window.addEventListener('resize',schedule,{passive:true});
    window.addEventListener('scroll',schedule,{passive:true,capture:true});
    if(window.visualViewport){visualViewport.addEventListener('resize',schedule,{passive:true});visualViewport.addEventListener('scroll',schedule,{passive:true})}
    document.fonts?.ready.then(schedule);
    refreshSpider();
  }
  const avatar=document.querySelector('#currentUserAvatar');
  if(avatar){
    const hat=document.createElement('span');hat.className='halloween-avatar-hat';
    hat.setAttribute('aria-hidden','true');hat.hidden=true;
    hat.innerHTML='<svg viewBox="0 0 56 40" focusable="false"><g stroke="#34313e" stroke-width=".8" stroke-linejoin="round"><path class="hat-silhouette" d="M13 30Q17 17 19 3Q27 9 33 4L31 10Q35 18 43 29Z" fill="#111117"/><path d="M15 23Q27 27 38 22L42 29Q29 34 13 29Z" fill="#7847a6"/><path d="M29 26L36 25L37 30L30 31Z" fill="#e79432" stroke="#be7125"/><path d="M31 27L34 26.7L34.6 28.9L31.6 29.2Z" fill="#352442" stroke="none"/><path class="hat-silhouette" d="M4 30Q26 34 48 26Q53 25 53 29Q35 41 7 36Q1 35 4 30Z" fill="#111117"/></g></svg>';
    document.body.append(hat);
    refreshHat=()=>{
      const b=avatar.getBoundingClientRect();
      hat.hidden=!enabled||avatar.hidden||!avatar.complete||!avatar.naturalWidth||!b.width||!b.height||b.top<0||b.right>innerWidth;
      if(hat.hidden)return;
      const zoom=parseFloat(getComputedStyle(document.body).zoom)||1;
      hat.style.left=(b.left/zoom-8)+'px';hat.style.top=(b.top/zoom-21)+'px';
    };
    let queued=false;
    const schedule=()=>{if(queued)return;queued=true;requestAnimationFrame(()=>{queued=false;refreshHat()})};
    new MutationObserver(schedule).observe(avatar,{attributes:true,attributeFilter:['hidden','src','class','style']});
    const size=new ResizeObserver(schedule);size.observe(avatar);size.observe(avatar.parentElement);
    avatar.addEventListener('load',schedule);avatar.addEventListener('error',schedule);
    window.addEventListener('resize',schedule,{passive:true});window.addEventListener('scroll',schedule,{passive:true,capture:true});
    if(window.visualViewport){visualViewport.addEventListener('resize',schedule,{passive:true});visualViewport.addEventListener('scroll',schedule,{passive:true})}
    document.fonts?.ready.then(schedule);refreshHat();
  }
  const workspaceIds=['workQueueView','applicationsView','historyView','suppliersView','edrMonitoringView','frameworkAnalyticsView','procurementsView','referencesView','requestsView','operationalTasksView','messagesView','administrationView'];
  const workspaces=workspaceIds.map(id=>document.querySelector('#'+id)).filter(Boolean);
  for(const view of workspaces)view.classList.add('halloween-workspace');
  if(workspaces.length){
    refreshQueueBackground=()=>{
      if(!enabled)return;
      const zoom=parseFloat(getComputedStyle(document.body).zoom)||1;
      for(const view of workspaces){
        if(view.hidden)continue;
        const box=view.getBoundingClientRect();
        // One viewport-sized scene, independent of rows and document scroll.
        const top=Math.max(0,box.top+window.scrollY);
        const height=Math.max(0,innerHeight-top)/zoom;
        view.style.setProperty('--halloween-workspace-height',height+'px');
      }
    };
    let queued=false;
    const schedule=()=>{if(queued)return;queued=true;requestAnimationFrame(()=>{queued=false;refreshQueueBackground()})};
    const size=new ResizeObserver(schedule),visibility=new MutationObserver(schedule);
    for(const view of workspaces){size.observe(view);visibility.observe(view,{attributes:true,attributeFilter:['hidden']})}
    window.addEventListener('resize',schedule,{passive:true});
    if(window.visualViewport)visualViewport.addEventListener('resize',schedule,{passive:true});
    document.fonts?.ready.then(schedule);refreshQueueBackground();
  }
  const form=document.querySelector('#accountSettingsForm');
  if(form){
    const label=document.createElement('label');label.className='halloween-preference';
    label.innerHTML='<input id="halloweenDecorationEnabled" type="checkbox"><span><span class="halloween-preference-caption"></span><small></small></span>';
    form.querySelector('footer').before(label);
    input=label.querySelector('input');hint=label.querySelector('small');caption=label.querySelector('.halloween-preference-caption');
    input.addEventListener('change',()=>{
      preferred=input.checked;try{localStorage.setItem(key,preferred?'1':'0')}catch{}
      synchronize();
    });
    synchronize();
  }
  document.addEventListener('visibilitychange',synchronize);
  window.addEventListener('focus',synchronize);
  window.addEventListener('pageshow',synchronize);
  window.addEventListener('pagehide',()=>{if(seasonTimer!==null)clearTimeout(seasonTimer);seasonTimer=null});
  synchronize();
})();
