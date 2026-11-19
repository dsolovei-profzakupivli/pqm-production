/* Sandbox-only bridge: keep the existing Halloween preference and animations,
   while allowing the cat to remain visible after the seasonal decorations end. */
(()=>{
  const root=document.documentElement;
  if(root.dataset.pqmEnvironment!=='sandbox'||root.dataset.pqmCatController==='on')return;
  root.dataset.pqmCatController='on';
  const key='pqm.halloween.cat.enabled.v1';
  const input=document.querySelector('#halloweenDecorationEnabled');
  const cat=document.querySelector('img.halloween-cat');
  if(!input||!cat)return;
  const caption=input.nextElementSibling;
  const hint=caption?.querySelector('small');
  let preferred=true,lastAvailable=null,timer=null,internalChange=false;
  try{preferred=localStorage.getItem(key)!=='0'}catch{/* Keep an in-memory choice for this page. */}
  const season=()=>globalThis.PqmHalloweenSeason?.state(new Date())||{available:false,nextTransitionAt:null};
  const save=()=>{try{localStorage.setItem(key,preferred?'1':'0')}catch{/* Storage may be unavailable. */}};
  const synchronize=()=>{
    if(timer!==null)clearTimeout(timer);
    const current=season(),available=!!current.available;
    const needsLegacySync=lastAvailable===false&&available&&input.checked!==preferred;
    root.dataset.pqmCat=preferred?'on':'off';
    const source=available?'assets/halloween-witch-cat.webp':'assets/pqm-cat-no-hat.png';
    if(cat.getAttribute('src')!==source)cat.setAttribute('src',source);
    input.disabled=false;
    if(input.checked!==preferred)input.checked=preferred;
    if(caption){
      const text=available?'Halloween · святкове оформлення':'Котик PQM';
      if(caption.firstChild?.nodeType===Node.TEXT_NODE)caption.firstChild.textContent=text;
      else caption.insertBefore(document.createTextNode(text),caption.firstChild);
    }
    input.title=available?'Керування Halloween-оформленням і котиком':'Керування видимістю котика';
    if(hint)hint.textContent=available?'Сезонне оформлення та котик · лише в цьому браузері':'Котик PQM · лише в цьому браузері';
    if(needsLegacySync&&!internalChange){
      internalChange=true;input.checked=preferred;input.dispatchEvent(new Event('change',{bubbles:true}));internalChange=false;
    }
    lastAvailable=available;
    const until=current.nextTransitionAt?current.nextTransitionAt-Date.now():60000;
    timer=setTimeout(synchronize,Math.max(1,Math.min(60000,until>0?until:60000)));
  };
  document.addEventListener('change',event=>{
    if(event.target!==input||internalChange)return;
    preferred=!!input.checked;save();synchronize();
    // The legacy Halloween handler runs after this capture listener and may
    // reset the checkbox outside October; restore the shared preference after it.
    queueMicrotask(synchronize);
  },true);
  new MutationObserver(synchronize).observe(root,{attributes:true,attributeFilter:['data-halloween']});
  new MutationObserver(synchronize).observe(input,{attributes:true,attributeFilter:['disabled']});
  document.addEventListener('visibilitychange',synchronize);
  window.addEventListener('focus',synchronize);
  window.addEventListener('pageshow',synchronize);
  window.addEventListener('pagehide',()=>{if(timer!==null)clearTimeout(timer);timer=null});
  synchronize();
})();
