/* Sandbox decoration only. No API calls, profile writes or seasonal timers. */
(()=>{
  const title=document.querySelector('.prod-brand-copy strong');
  if(!title)return;
  const key='pqm.halloween.cat.enabled.v1';
  let enabled=true;
  try{enabled=localStorage.getItem(key)!=='0'}catch{/* Private storage may be unavailable. */}
  const apply=()=>{document.documentElement.dataset.halloween=enabled?'on':'off'};
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
  const form=document.querySelector('#accountSettingsForm');
  if(form){
    const label=document.createElement('label');label.className='halloween-preference';
    label.innerHTML='<input id="halloweenDecorationEnabled" type="checkbox"><span>Halloween · чорний кіт<small>Декоративне оформлення лише в цьому браузері</small></span>';
    form.querySelector('footer').before(label);
    const input=label.querySelector('input');input.checked=enabled;
    input.addEventListener('change',()=>{enabled=input.checked;apply();try{localStorage.setItem(key,enabled?'1':'0')}catch{}});
  }
})();
