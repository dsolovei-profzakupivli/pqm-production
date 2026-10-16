/* Presentation helpers shared by the UI and offline regression probes. */
(function(root){
  function compactOfficer(value){
    const parts=String(value||'').trim().split(/\s+/).filter(Boolean);
    if(/^(Не визначено|Не призначено)$/i.test(parts.join(' ')))return parts.join(' ');
    if(parts.length<2)return parts.join(' ');
    const surname=parts.at(-1).split('-').map(word=>word[0].toLocaleUpperCase('uk-UA')+word.slice(1).toLocaleLowerCase('uk-UA')).join('-');
    return `${parts.slice(0,-1).map(word=>word[0]+'.').join(' ')} ${surname}`;
  }
  function clearInput(input){
    input.value='';
    input.dispatchEvent(new Event('input',{bubbles:true}));
    input.focus();
  }
  const api={compactOfficer,clearInput,responseExpired:false};
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
  root.PqmUi=api;
})(typeof globalThis!=='undefined'?globalThis:this);
