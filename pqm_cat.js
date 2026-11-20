/* Permanent cat and fail-closed loading of the existing seasonal decoration. */
(()=>{
  const root=document.documentElement;
  if(root.dataset.pqmEnvironment!=='sandbox'||root.dataset.pqmCatController==='on')return;
  root.dataset.pqmCatController='on';root.dataset.halloween='off';root.dataset.pqmSeasonalState='off';
  const normal='assets/pqm-cat-no-hat.png',hat='assets/halloween-witch-cat.webp';
  const key='pqm.halloween.cat.enabled.v1';
  let preferred=true,timer=null,loading=false,ready=false,failed=false,epoch=0,hatEpoch=-1;
  try{preferred=localStorage.getItem(key)!=='0'}catch{/* Ordinary cat is the default. */}
  root.dataset.pqmCat=preferred?'on':'off';
  const title=document.querySelector('.sandbox-brand-copy strong');
  if(!title)return;
  title.classList.add('halloween-title');title.style.position='relative';
  let cat=title.querySelector('img.halloween-cat');
  if(!cat){
    cat=document.createElement('img');cat.className='halloween-cat';cat.src=normal;
    cat.width=180;cat.height=97;cat.alt='';cat.draggable=false;
    cat.setAttribute('aria-hidden','true');cat.style.cssText='position:absolute;pointer-events:none;max-width:none';
    title.append(cat);
  }
  let input=document.querySelector('#halloweenDecorationEnabled');
  if(!input){
    const form=document.querySelector('#accountSettingsForm');
    if(form){
      const label=document.createElement('label');label.className='halloween-preference';
      label.innerHTML='<input id="halloweenDecorationEnabled" type="checkbox"><span>Котик PQM<small>Котик PQM · лише в цьому браузері</small></span>';
      form.querySelector('footer').before(label);input=label.querySelector('input');
    }
  }
  const state=()=>{
    try{
      const value=globalThis.PqmHalloweenSeason?.state(new Date());
      if(value?.timeZone!=='Europe/Kyiv'||typeof value.available!=='boolean')throw Error('Invalid calendar policy');
      if(value.available&&!Number.isFinite(value.nextTransitionAt))throw Error('Invalid calendar boundary');
      return value;
    }catch{return{available:false,nextTransitionAt:null,timeZone:'Europe/Kyiv'}}
  };
  let baseCssReady=false;
  try{baseCssReady=!!document.querySelector('link[href="pqm_cat.css"]')?.sheet?.cssRules.length}catch{/* Failed CSS is not a seasonal opt-in. */}
  if(!baseCssReady){failed=true;root.dataset.pqmSeasonalState='failed'}
  const allowed=()=>!failed&&preferred&&state().available;
  const ordinary=()=>{
    root.dataset.halloween='off';
    if(cat.getAttribute('src')!==normal)cat.src=normal;
    document.querySelectorAll('.halloween-cat-eyes,.halloween-flight-lane,.halloween-spider,.halloween-avatar-hat').forEach(node=>{
      if(!node.classList.contains('halloween-cat-eyes'))node.hidden=true;
      for(const animation of (node.getAnimations?.({subtree:true})||[]))animation.cancel();
    });
  };
  const fail=()=>{failed=true;root.dataset.pqmSeasonalState='failed';epoch++;hatEpoch=-1;ordinary()};
  function resource(name,kind){
    return new Promise((resolve,reject)=>{
      if(!allowed())return reject(Error('Season is closed'));
      const node=document.createElement(kind==='css'?'link':'script');
      node.dataset.pqmSeasonalResource=name;
      if(kind==='css'){node.rel='stylesheet';node.href=name}else{node.src=name;node.async=false}
      node.onload=()=>allowed()?resolve():reject(Error('Season ended during load'));
      node.onerror=()=>reject(Error('Seasonal resource failed'));
      document.head.append(node);
    });
  }
  async function loadSeason(){
    if(loading||ready||!allowed())return;
    loading=true;root.dataset.pqmSeasonalState='loading';
    try{
      await resource('halloween.css','css');
      await resource('halloween_motion.css','css');
      await resource('halloween.js','js');
      await resource('halloween_motion.js','js');
      if(!allowed())throw Error('Season ended');
      ready=true;root.dataset.pqmSeasonalState='ready';
    }catch{fail()}
    finally{loading=false;synchronize()}
  }
  function synchronize(){
    if(timer!==null)clearTimeout(timer);
    const current=state();root.dataset.pqmCat=preferred?'on':'off';
    if(!allowed()){
      if(root.dataset.halloween!=='off'||cat.getAttribute('src')!==normal)epoch++;
      hatEpoch=-1;ordinary();
    }else if(!ready){ordinary();loadSeason()}
    else{
      root.dataset.pqmSeasonalState='ready';root.dataset.halloween='on';
      if(hatEpoch!==epoch){
        const ticket=epoch;hatEpoch=ticket;
        const image=new Image();
        image.onload=()=>{if(ticket===epoch&&allowed())cat.src=hat;else ordinary()};
        image.onerror=fail;
        if(allowed())image.src=hat;
      }
    }
    if(input){
      input.disabled=false;input.checked=preferred;
      const caption=input.nextElementSibling,hint=caption?.querySelector('small');
      if(caption?.firstChild)caption.firstChild.textContent=current.available?'Halloween · святкове оформлення':'Котик PQM';
      input.title=current.available?'Керування Halloween-оформленням і котиком':'Керування видимістю котика';
      if(hint)hint.textContent=current.available?'Сезонне оформлення та котик · лише в цьому браузері':'Котик PQM · лише в цьому браузері';
    }
    const until=current.nextTransitionAt-Date.now();
    timer=setTimeout(synchronize,Number.isFinite(until)&&until>0?Math.max(1,Math.min(60000,until)):60000);
  }
  document.addEventListener('change',event=>{
    if(event.target!==input)return;
    preferred=!!input.checked;epoch++;hatEpoch=-1;
    try{localStorage.setItem(key,preferred?'1':'0')}catch{/* Preference remains in memory. */}
    synchronize();queueMicrotask(synchronize);
  },true);
  window.addEventListener('error',event=>{
    if(/\/(?:halloween|halloween_motion|pqm_cat)\.js(?:[?#]|$)/.test(event.filename||''))fail();
  });
  document.addEventListener('visibilitychange',synchronize);
  window.addEventListener('focus',synchronize);window.addEventListener('pageshow',synchronize);
  window.addEventListener('pagehide',()=>{if(timer!==null)clearTimeout(timer);timer=null});
  synchronize();
})();
