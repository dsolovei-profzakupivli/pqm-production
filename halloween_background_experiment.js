/* Local prototype only. No API, data, preference or application-state writes. */
(()=>{
  const workspaces=[...document.querySelectorAll('#applicationsView,#operationalTasksView,#suppliersView')];
  const refresh=()=>{
    const zoom=parseFloat(getComputedStyle(document.body).zoom)||1;
    for(const view of workspaces){
      if(view.hidden)continue;
      const box=view.getBoundingClientRect();
      view.style.setProperty('--halloween-experiment-height',Math.max(box.height,innerHeight-box.top)/zoom+'px');
    }
  };
  let queued=false;
  const schedule=()=>{if(queued)return;queued=true;requestAnimationFrame(()=>{queued=false;refresh()})};
  const resize=new ResizeObserver(schedule),visibility=new MutationObserver(schedule);
  for(const view of workspaces){resize.observe(view);visibility.observe(view,{attributes:true,attributeFilter:['hidden']})}
  window.addEventListener('resize',schedule,{passive:true});
  window.visualViewport?.addEventListener('resize',schedule,{passive:true});
  document.fonts?.ready.then(schedule);
  refresh();
})();
