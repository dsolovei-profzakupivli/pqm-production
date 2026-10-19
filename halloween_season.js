/* Pure calendar policy; no browser locale/zone assumptions, I/O or timers. */
(()=>{
  const timeZone='Europe/Kyiv';
  const parts=date=>Object.fromEntries(new Intl.DateTimeFormat('en-GB',{
    timeZone,year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'
  }).formatToParts(date).filter(p=>p.type!=='literal').map(p=>[p.type,Number(p.value)]));
  function midnight(year,month){
    const target=Date.UTC(year,month-1,1);let candidate=target;
    for(let i=0;i<4;i++){
      const p=parts(new Date(candidate));
      const delta=target-Date.UTC(p.year,p.month-1,p.day,p.hour,p.minute,p.second);
      if(!delta)return candidate;
      candidate+=delta;
    }
    throw new Error('Kyiv midnight could not be resolved');
  }
  function state(now=new Date()){
    try{
      const p=parts(now),available=p.month===10;
      const nextTransitionAt=p.month<10?midnight(p.year,10):available?midnight(p.year,11):midnight(p.year+1,10);
      return {available,nextTransitionAt,timeZone};
    }catch{return {available:false,nextTransitionAt:null,timeZone}}
  }
  globalThis.PqmHalloweenSeason=Object.freeze({state,timeZone});
})();
