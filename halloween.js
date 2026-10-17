/* Sandbox decoration only. No API calls, profile writes or seasonal timers. */
(()=>{
  const title=document.querySelector('.prod-brand-copy strong');
  if(!title)return;
  const key='pqm.halloween.cat.enabled.v1';
  let enabled=true;
  try{enabled=localStorage.getItem(key)!=='0'}catch{/* Private storage may be unavailable. */}
  let refreshSpider=()=>{};
  const apply=()=>{document.documentElement.dataset.halloween=enabled?'on':'off';refreshSpider()};
  apply();
  title.classList.add('halloween-title');
  title.insertAdjacentHTML('beforeend',`<svg class="halloween-cat" viewBox="0 0 156 57" aria-hidden="true" focusable="false" xmlns="http://www.w3.org/2000/svg">
    <g fill="#101116" stroke="#30323b" stroke-width=".8" stroke-linejoin="round">
      <path class="cat-tail" d="M111 23C135 15 164 18 187 25C201 29 207 37 205 47L208 49L203 50L201 55L196 52L192 55L191 49L187 47C193 37 183 35 169 33C147 29 133 34 114 32Z"/>
      <path transform="translate(0 -4)" d="M49 30C61 13 88 10 108 19L115 17L115 22L121 23L118 27L124 31L119 34L120 38L111 37C99 42 73 41 55 37Z"/>
      <path d="M27 25L23 6L35 13Q45 7 54 13L65 5L64 25L68 29L63 30L65 35L58 35Q44 43 29 34L24 35L26 30L21 28Z"/>
      <path d="M37 32Q32 37 33 48Q34 54 41 52Q45 51 43 46L46 34Z"/>
      <path d="M54 33Q51 39 53 48Q55 54 61 51Q65 49 62 44L63 34Z"/>
    </g>
    <path d="M28 12L30 23L35 17M60 12L54 17L61 23" fill="#38303b"/>
    <g class="cat-eyes" fill="#f5cf45"><path d="M30 23Q36 18 42 23Q37 29 30 23Z"/><path d="M47 23Q53 18 59 22Q54 29 47 23Z"/><g fill="#08090d"><ellipse cx="37" cy="23" rx="1.1" ry="4"/><ellipse cx="53" cy="23" rx="1.1" ry="4"/></g></g>
    <path d="M43 29L47 29L45 32Z" fill="#87717c"/>
    <path d="M45 32L42 34M45 32L48 34M35 30L23 28M35 32L22 33M55 30L67 28M55 32L68 34M36 48L36 51M39 48L39 51M56 47L57 50M59 47L60 50" fill="none" stroke="#777581" stroke-width=".7" stroke-linecap="round"/>
    <path d="M73 20Q88 14 102 21" fill="none" stroke="#34343e" stroke-width="1.2"/>
  </svg>`);
  const nav=document.querySelector('#mainNav');
  if(nav){
    const spider=document.createElement('span');spider.className='halloween-spider';
    spider.setAttribute('aria-hidden','true');spider.hidden=true;
    spider.innerHTML='<svg viewBox="0 0 12 12" focusable="false"><g fill="#101116" stroke="#8996a8" stroke-width=".65" stroke-linecap="round"><path d="M4 4L1 1M4 6L1 5M4 8L1 11M8 4L11 1M8 6L11 5M8 8L11 11"/><ellipse cx="6" cy="7" rx="3" ry="4"/><circle cx="6" cy="3" r="2.4"/></g><g fill="#ff9b32"><circle cx="5" cy="3" r=".65"/><circle cx="7" cy="3" r=".65"/></g></svg>';
    document.body.append(spider);
    refreshSpider=()=>{
      const button=nav.querySelector('button.nav-active');
      if(!enabled||!button){spider.hidden=true;return}
      const b=button.getBoundingClientRect(),n=nav.getBoundingClientRect();
      const zoom=parseFloat(getComputedStyle(document.body).zoom)||1;
      const width=button.clientWidth;
      // Geometry, never tab names: 38px icon button → 22px web; wide → 44px.
      button.style.setProperty('--halloween-web-width',Math.min(width-2,Math.max(20,Math.min(44,22+(width-38)*.32)))+'px');
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
  const form=document.querySelector('#accountSettingsForm');
  if(form){
    const label=document.createElement('label');label.className='halloween-preference';
    label.innerHTML='<input id="halloweenDecorationEnabled" type="checkbox"><span>Halloween · кіт і павутинка<small>Декоративне оформлення лише в цьому браузері</small></span>';
    form.querySelector('footer').before(label);
    const input=label.querySelector('input');input.checked=enabled;
    input.addEventListener('change',()=>{enabled=input.checked;apply();try{localStorage.setItem(key,enabled?'1':'0')}catch{}});
  }
})();
