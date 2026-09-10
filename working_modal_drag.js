/* Shared viewport dragging only; never submits, closes, reloads or mutates model data. */
window.installViewportDrag=function(dialog,target,header,{enabled=()=>true,resetOnClose=true}={}){
  if(!dialog||!target||!header||header.dataset.viewportDrag)return;
  header.dataset.viewportDrag='true';let drag=null,moved=false;
  const original={left:target.style.left,top:target.style.top,margin:target.style.margin,position:target.style.position};
  const position=(x,y)=>{const r=target.getBoundingClientRect();target.style.left=`${Math.max(8,Math.min(x,Math.max(8,innerWidth-r.width-8)))}px`;target.style.top=`${Math.max(8,Math.min(y,Math.max(8,innerHeight-Math.min(r.height,80)-8)))}px`};
  const end=e=>{if(drag&&header.hasPointerCapture(drag.id))header.releasePointerCapture(drag.id);drag=null;header.classList.remove('is-dragging')};
  header.addEventListener('pointerdown',e=>{
    if(!enabled()||e.button!==0||!e.isPrimary||e.target.closest('button,input,select,textarea,a,label,[contenteditable],[role="button"]'))return;
    const r=target.getBoundingClientRect();drag={id:e.pointerId,x:e.clientX-r.left,y:e.clientY-r.top};
    if(target===dialog){target.style.position='fixed';target.style.margin='0'}position(r.left,r.top);moved=true;
    header.setPointerCapture(e.pointerId);header.classList.add('is-dragging');e.preventDefault();
  });
  header.addEventListener('pointermove',e=>{if(drag&&e.pointerId===drag.id)position(e.clientX-drag.x,e.clientY-drag.y)});
  header.addEventListener('pointerup',end);header.addEventListener('pointercancel',end);header.addEventListener('lostpointercapture',()=>{drag=null;header.classList.remove('is-dragging')});
  window.addEventListener('resize',()=>{if(dialog.open&&moved&&enabled()){const r=target.getBoundingClientRect();position(r.left,r.top)}});
  dialog.addEventListener('close',()=>{end();if(resetOnClose){Object.assign(target.style,original);moved=false}});
};
for(const id of ['columnsDialog','remarksDialog']){
  const dialog=document.getElementById(id);if(!dialog)continue;
  dialog.classList.add('working-draggable-dialog');
  installViewportDrag(dialog,dialog,dialog.querySelector('form>header'));
}
