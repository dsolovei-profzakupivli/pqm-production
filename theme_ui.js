/* Account-owned appearance only. No storage, auth, API or business state. */
(()=>{
  const normalize=value=>value==='dark'?'dark':'light';
  function apply(value){
    let theme=normalize(value);
    const sheet=document.getElementById('personalThemeStyles');
    const unavailable=theme==='dark'&&sheet&&!sheet.sheet;
    if(unavailable)theme='light';
    document.documentElement.dataset.theme=theme;
    if(document.body)document.body.dataset.theme=theme;
    for(const logo of document.querySelectorAll('img.prod-brand-initials')){
      logo.setAttribute('src',theme==='dark'?'/assets/pqm-brand-mark-prod-dark.svg':'/assets/pqm-brand-mark-prod.svg');
    }
    const status=document.getElementById('accountThemeStatus');
    if(status){status.hidden=!unavailable;status.textContent=unavailable?'Не вдалося завантажити темну тему. Залишено світле оформлення.':''}
    return theme;
  }
  function install(){
    if(document.getElementById('accountColorScheme'))return;
    const anchor=document.getElementById('accountDensity')?.closest('label');
    if(!anchor)return;
    const label=document.createElement('label');
    label.innerHTML='Тема оформлення<select id="accountColorScheme"><option value="light">Світла</option><option value="dark">Темна</option></select><small id="accountThemeStatus" role="status" hidden></small>';
    anchor.after(label);
  }
  globalThis.PqmThemeUI=Object.freeze({normalize,apply,install});
})();
