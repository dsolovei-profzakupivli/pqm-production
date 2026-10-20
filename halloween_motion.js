/* Local Halloween visual prototype. Uses the existing Kyiv/calendar preference gate. */
(()=>{
  const root=document.documentElement;
  if(root.dataset.pqmHalloweenTarget!=='production')return;
  if(document.getElementById('pqmHalloweenHost'))return;
  const shell=document.querySelector('#applicationShell'),views=[...document.querySelectorAll('main')];
  const host=document.createElement('div');host.id='pqmHalloweenHost';host.className='halloween-flight-lane';
  host.setAttribute('aria-hidden','true');host.hidden=true;(shell||document.body).prepend(host);
  let surface={safe:false,reason:'no-active-view',view:null};
  const reduce=matchMedia('(prefers-reduced-motion: reduce)');
  const cat=document.querySelector('.halloween-cat');
  let timer=null,flight=null,variant=0,paused=false,blinkTimer=null,lookTimer=null;
  const eyeAnimations=[];
  let nextBlinkAt=0,nextWinkAt=0,lastWinkAt=-Infinity,lidsBusy=false,lidGeneration=0,reactionPending=false;
  const track=a=>{eyeAnimations.push(a);a.oncancel=a.onfinish=()=>{const i=eyeAnimations.indexOf(a);if(i>=0)eyeAnimations.splice(i,1)};return a};
  let eyes=null;
  if(cat){
    // The resting cat remains original. Only the clipped iris/pupil overlay moves.
    eyes=document.createElement('span');eyes.className='halloween-cat halloween-cat-eyes';
    eyes.setAttribute('aria-hidden','true');
    eyes.innerHTML='<svg viewBox="0 0 720 389" focusable="false"><defs><clipPath id="pqmCatEyeMask"><path d="M487 190C493 169 522 173 527 198C530 215 520 226 505 222C490 219 483 207 487 190ZM565 230C575 212 600 213 611 227C620 245 603 261 584 258C571 256 560 246 565 230Z"/></clipPath></defs><g clip-path="url(#pqmCatEyeMask)"><g class="pqm-cat-eye-art" opacity="0"><defs><linearGradient id="pqmCatIris" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#d4e65c"/><stop offset=".6" stop-color="#e5ef7e"/><stop offset="1" stop-color="#bacc4d"/></linearGradient></defs><path fill="url(#pqmCatIris)" d="M479 168H535V228H479ZM556 208H620V265H556Z"/><g class="pqm-cat-gaze" fill="#090d0b"><ellipse cx="510" cy="201" rx="9" ry="14" transform="rotate(25 510 201)"/><ellipse cx="581" cy="235" rx="9" ry="14" transform="rotate(25 581 235)"/><g fill="#ffffe9"><ellipse cx="508" cy="192" rx="3.5" ry="4"/><circle cx="513" cy="197" r="1.5"/><ellipse cx="578" cy="226" rx="3.5" ry="4"/><circle cx="583" cy="231" r="1.5"/></g></g></g></g><defs><clipPath id="pqmCatLidMask"><path transform="translate(507 199) scale(1.2) translate(-507 -199)" d="M487 190C493 169 522 173 527 198C530 215 520 226 505 222C490 219 483 207 487 190Z"/><path transform="translate(590 236) scale(1.2) translate(-590 -236)" d="M565 230C575 212 600 213 611 227C620 245 603 261 584 258C571 256 560 246 565 230Z"/></clipPath></defs><g clip-path="url(#pqmCatLidMask)"><g class="pqm-cat-lids"><path fill="#0b0c10" d="M479 168H535V228H479Z"/><path d="M486 194Q504 208 529 203" fill="none" stroke="#25232b" stroke-width="1.8" stroke-linecap="round"/></g><g class="pqm-cat-lids"><path fill="#0b0c10" d="M556 208H620V265H556Z"/><path d="M564 233Q586 246 614 238" fill="none" stroke="#25232b" stroke-width="1.8" stroke-linecap="round"/></g></g></svg>';
    cat.after(eyes);
  }
  const allowed=()=>!paused&&!document.hidden&&!reduce.matches&&root.dataset.halloween==='on'&&!!shell&&!shell.hidden;
  const catAllowed=()=>!paused&&!document.hidden&&!reduce.matches&&root.dataset.pqmCat==='on'&&!!shell&&!shell.hidden;
  // Cursor and automatic gaze share the existing clipped pupil group. The
  // original iris is fully covered while pupils move, avoiding ghost pupils.
  let cursorOwns=false,cursorEngaged=false,cursorJob=null,cursorIdle=null,cursorPoint=null,cursorEpoch=0;
  const cursorGaze=eyes?.querySelector('.pqm-cat-gaze'),cursorArt=eyes?.querySelector('.pqm-cat-eye-art');
  const stopCursor=()=>{
    clearTimeout(cursorJob);clearTimeout(cursorIdle);cursorJob=cursorIdle=null;cursorPoint=null;cursorOwns=cursorEngaged=false;cursorEpoch++;
    if(cursorGaze)for(const a of cursorGaze.getAnimations())a.cancel();
    if(cursorArt){for(const a of cursorArt.getAnimations())a.cancel();cursorArt.style.removeProperty('opacity')}
  };
  const moveCursorGaze=(x,y,centering=false)=>{
    if(!cursorGaze||!catAllowed())return;
    const from=getComputedStyle(cursorGaze).transform;
    const epoch=++cursorEpoch;cursorOwns=true;
    for(const a of cursorGaze.getAnimations())a.cancel();
    for(const a of cursorArt.getAnimations())a.cancel();
    cursorArt.style.opacity='1';
    const a=track(cursorGaze.animate([{transform:from==='none'?'translate(0px,0px)':from},{transform:`translate(${x}px,${y}px)`}],
      {duration:centering?360:180,easing:'ease-out',fill:'forwards'}));
    if(centering)a.addEventListener('finish',()=>{
      if(epoch!==cursorEpoch)return;a.cancel();cursorArt.style.removeProperty('opacity');cursorOwns=false;
    },{once:true});
  };
  const centerCursor=()=>{
    clearTimeout(cursorIdle);cursorIdle=null;
    if((cursorOwns||cursorGaze?.getAnimations().length)&&catAllowed())moveCursorGaze(0,0,true);
  };
  const applyCursor=()=>{
    cursorJob=null;if(!catAllowed()||!cursorPoint||!cursorGaze)return;
    const svg=eyes.querySelector('svg'),matrix=svg.getScreenCTM();if(!matrix)return;
    const point=svg.createSVGPoint();point.x=550;point.y=219;
    const origin=point.matrixTransform(matrix),dx=cursorPoint.x-origin.x,dy=cursorPoint.y-origin.y;
    const distance=Math.hypot(dx,dy),scale=Math.hypot(matrix.a,matrix.b);
    if(!scale)return;
    const radius=Math.max(220,Math.min(360,cat.getBoundingClientRect().width*2));
    const near=1-Math.min(1,distance/radius),strength=.78+.22*near;
    const maxX=Math.min(10,2.7/scale),maxY=Math.min(7,1.7/scale),denominator=Math.max(36,distance);
    moveCursorGaze(dx/denominator*maxX*strength,dy/denominator*maxY*strength);
    clearTimeout(cursorIdle);cursorIdle=setTimeout(centerCursor,4000);
  };
  document.addEventListener('pointermove',event=>{
    if(!catAllowed()||!eyes||event.pointerType==='touch')return;
    cursorEngaged=true;cursorPoint={x:event.clientX,y:event.clientY};
    if(cursorJob===null)cursorJob=setTimeout(applyCursor,32);
  },{passive:true});
  const leaveCursor=()=>{clearTimeout(cursorJob);cursorJob=null;cursorPoint=null;cursorEngaged=false;centerCursor()};
  document.addEventListener('pointerleave',leaveCursor,{passive:true});
  window.addEventListener('blur',leaveCursor,{passive:true});
  let stopTrail=null;
  const clearFlight=()=>{stopTrail?.stop();stopTrail=null;flight?.remove();flight=null};
  const clear=()=>{clearTimeout(timer);timer=null;clearFlight()};
  // One host below working surfaces, outside all hidden tab containers.
  const controlsSelector='button,input,select,textarea,a,[role="button"],summary';
  const workingSelector='table,.card,.table-card,.module-kpis,.kpi-row,.kpi,.kpi-card,.heading-metrics,.history-total,.operational-type-kpis,.work-queue-kpis';
  const foreground=view=>{
    const heading=view.querySelector(':scope > .module-heading,:scope > .page-heading,:scope > .history-heading');
    // Isolation changes painting order without creating a new containing block
    // for existing absolute/fixed children or changing layout geometry.
    for(const element of view.querySelectorAll(controlsSelector+','+workingSelector))if(!element.classList.contains('pqm-halloween-foreground'))element.classList.add('pqm-halloween-foreground');
    for(const child of heading?.children||[])if(!child.classList.contains('pqm-halloween-foreground'))child.classList.add('pqm-halloween-foreground');
    for(const child of view.children)if(child!==heading&&!child.classList.contains('pqm-halloween-foreground'))child.classList.add('pqm-halloween-foreground');
  };
  const findSurface=()=>{
    const view=views.find(v=>!v.hidden&&v.getBoundingClientRect().width&&v.getBoundingClientRect().height);
    if(!view)return{safe:false,reason:'no-active-view',view:null};
    if(!view.classList.contains('halloween-workspace'))return{safe:false,reason:'no-halloween-landscape',view};
    foreground(view);
    if(document.querySelector('dialog[open]'))return{safe:false,reason:'dialog-open',view};
    const zoom=parseFloat(getComputedStyle(document.body).zoom)||1,r=view.getBoundingClientRect();
    const top=Math.max(0,r.top,document.querySelector('.topbar')?.getBoundingClientRect().bottom||0)+2;
    const heading=view.querySelector(':scope > .module-heading,:scope > .page-heading,:scope > .history-heading');
    const skyBottom=Math.min(innerHeight,heading?.getBoundingClientRect().bottom||top+86*zoom);
    const amplitude=Math.max(0,Math.min(20,(skyBottom-top-86*zoom)/(2*zoom)));
    return{safe:true,reason:'clear-sky',view,top:top/zoom,zoom,width:innerWidth/zoom,amplitude};
  };
  const stopGaze=()=>{if(eyes&&!cursorOwns)for(const e of eyes.querySelectorAll('.pqm-cat-gaze,.pqm-cat-eye-art'))for(const a of e.getAnimations())a.cancel()};
  const refreshSurface=()=>{
    const zoom=parseFloat(getComputedStyle(document.body).zoom)||1;
    host.style.setProperty('--flight-viewport-width',(innerWidth/zoom)+'px');
    const previous=surface,wasSafe=surface.safe;surface=findSurface();host.dataset.view=surface.view?.id||'';host.dataset.reason=surface.reason;
    host.dataset.safe=String(surface.safe);host.style.visibility=surface.safe?'visible':'hidden';
    if(surface.safe){host.style.setProperty('--maneuver-amplitude',surface.amplitude+'px');host.style.top=surface.top+'px';host.style.setProperty('--flight-viewport-width',surface.width+'px');
      if(flight){host.style.setProperty('--flight-distance',(-surface.width-125)+'px');if(previous.view!==surface.view||previous.top!==surface.top)stopTrail?.pause();stopTrail?.resize();stopTrail?.resume();if(!wasSafe){const a=flight.getAnimations().find(a=>a.animationName==='pqm-witch-cross');if(a)gaze(true,a.effect.getTiming().duration,a.currentTime||0)}}
    }else{stopTrail?.pause();if(wasSafe&&flight)stopGaze()}
  };
  const startTrail=(lane,svg,second)=>{
    const canvas=document.createElement('canvas');canvas.className='halloween-broom-trail';
    lane.prepend(canvas);
    const ctx=canvas.getContext('2d');if(!ctx)return{stop:()=>canvas.remove(),pause(){},resume(){},resize(){}};
    let width=lane.clientWidth,height=lane.clientHeight;
    const dpr=Math.min(devicePixelRatio||1,2);
    const particles=[],point=svg.createSVGPoint();
    // Source-sheet coordinates at the straw tip, transformed with the SVG sway.
    point.x=second?1930:1005;point.y=second?630:625;
    let frame=null,last=0,lastBirth=0,stopped=false;
    const draw=now=>{
      if(stopped)return;
      frame=null;
      if(!allowed()){clear();stopGaze();return}
      if(!lane.isConnected){stop();return}
      if(!surface.safe)return;
      frame=requestAnimationFrame(draw);
      if(now-last<32)return;last=now;
      const matrix=svg.getScreenCTM(),bounds=canvas.getBoundingClientRect();
      if(matrix&&bounds.width&&now-lastBirth>=80){
        lastBirth=now;const tip=point.matrixTransform(matrix);
        const x=(tip.x-bounds.left)*width/bounds.width,y=(tip.y-bounds.top)*height/bounds.height;
        // Bounded population; birth positions are frozen in scene coordinates.
        if(x>=-8&&x<=width+8)for(let i=0;i<2&&particles.length<44;i++)particles.push({
          x,y:y+(Math.random()-.5)*3,born:now,life:950+Math.random()*850,
          vx:5+Math.random()*13,vy:-7+Math.random()*17,r:.55+Math.random()*1.05,
          phase:Math.random()*Math.PI*2,white:Math.random()<.22
        });
      }
      ctx.clearRect(0,0,width,height);
      const dark=root.dataset.theme==='dark';
      for(let i=particles.length-1;i>=0;i--){
        const p=particles[i],age=(now-p.born)/1000,t=age*1000/p.life;
        if(t>=1){particles.splice(i,1);continue}
        const x=p.x+p.vx*age,y=p.y+p.vy*age+2*age*age;
        const fade=Math.min(1,t*12)*(1-t)*(1-t),twinkle=.72+.28*Math.sin(age*13+p.phase)**2;
        ctx.globalAlpha=fade*twinkle*(dark?.64:.95);
        ctx.shadowBlur=dark?2:1;ctx.shadowColor='#edbb61';
        ctx.fillStyle=p.white?'#fff7d5':dark?'#edc777':'#ffe4a0';
        ctx.strokeStyle=dark?'#cda45d':'#a96b25';ctx.lineWidth=dark?.25:.65;
        ctx.beginPath();ctx.arc(x,y,p.r*(1-t*.45),0,Math.PI*2);ctx.fill();ctx.stroke();
        if(p.white&&t<.6){ctx.fillRect(x-2,y-.35,4,.7);ctx.fillRect(x-.35,y-2,.7,4)}
      }
      ctx.globalAlpha=1;ctx.shadowBlur=0;
    };
    const pause=()=>{cancelAnimationFrame(frame);frame=null;particles.length=0;ctx.clearRect(0,0,width,height)};
    const resize=()=>{const w=lane.clientWidth,h=lane.clientHeight;if(canvas.width===Math.ceil(w*dpr)&&canvas.height===Math.ceil(h*dpr))return;width=w;height=h;particles.length=0;canvas.width=Math.ceil(width*dpr);canvas.height=Math.ceil(height*dpr);ctx.scale(dpr,dpr)};
    const resume=()=>{if(!stopped&&surface.safe&&frame===null)frame=requestAnimationFrame(draw)};
    const stop=()=>{stopped=true;pause();canvas.remove()};
    resize();resume();return{stop,pause,resume,resize};
  };
  const stopEyes=()=>{stopCursor();clearTimeout(blinkTimer);clearTimeout(lookTimer);blinkTimer=lookTimer=null;lidGeneration++;lidsBusy=false;nextBlinkAt=nextWinkAt=0;reactionPending=false;for(const a of [...eyeAnimations])a.cancel();eyeAnimations.length=0;};
  const animateLids=indices=>{
    if(!eyes||!catAllowed()||lidsBusy)return;
    lidsBusy=true;const generation=lidGeneration;
    const lids=[...eyes.querySelectorAll('.pqm-cat-lids')];
    const animations=indices.map(i=>track(lids[i].animate([
      {opacity:0,transform:'scaleY(0)'},{opacity:1,transform:'scaleY(1)',offset:.45},
      {opacity:1,transform:'scaleY(1)',offset:.55},{opacity:0,transform:'scaleY(0)'}
    ],{duration:420,easing:'ease-in-out'})));
    Promise.all(animations.map(a=>a.finished.catch(()=>{}))).then(()=>{
      if(generation!==lidGeneration)return;lidsBusy=false;reactionPending=false;blink();
    });
  };
  const blink=()=>{
    if(!eyes||!catAllowed()||blinkTimer!==null||lidsBusy)return;
    const now=performance.now();
    if(!nextBlinkAt)nextBlinkAt=now+7000+Math.random()*9000;
    if(!nextWinkAt)nextWinkAt=now+40000+Math.random()*20000;
    // A single eyelid clock coordinates bilateral blinks and one-eye winks.
    blinkTimer=setTimeout(()=>{blinkTimer=null;if(!catAllowed())return;
      const now=performance.now();
      if(now>=nextWinkAt){lastWinkAt=now;nextWinkAt=now+40000+Math.random()*20000;
        nextBlinkAt=Math.max(nextBlinkAt,now+1800);animateLids([Math.random()<.5?0:1]);
      }else{nextBlinkAt=now+7000+Math.random()*9000;animateLids([0,1])}
    },Math.max(0,Math.min(nextBlinkAt,nextWinkAt)-now));
  };
  const reactAfterFlight=()=>{
    if(!eyes||!catAllowed()||lidsBusy||performance.now()-lastWinkAt<40000||Math.random()>=.35)return;
    // Tracking gaze finishes in the centre; then optionally wink. Reuse the
    // existing eyelid clock rather than creating a per-flight reaction timer.
    reactionPending=true;nextWinkAt=performance.now()+250;nextBlinkAt=Math.max(nextBlinkAt,nextWinkAt+1800);clearTimeout(blinkTimer);blinkTimer=null;blink();
  };
  const gaze=(tracking=false,flightDuration=13000,elapsed=0)=>{
    if(!eyes||!catAllowed()||cursorOwns||cursorEngaged)return;
    // SVG source units are scaled 4:1 in the 180px cat: the old 3-unit
    // movement was only 0.75 screen pixels and was practically invisible.
    const amplitude=10,x=tracking?amplitude:(Math.random()<.5?-amplitude:amplitude);
    for(const a of eyes.querySelector('.pqm-cat-gaze').getAnimations())a.cancel();
    for(const a of eyes.querySelector('.pqm-cat-eye-art').getAnimations())a.cancel();
    const art=track(eyes.querySelector('.pqm-cat-eye-art').animate([
      {opacity:0},{opacity:1,offset:.08},{opacity:1,offset:.92},{opacity:0}
    ],{duration:tracking?flightDuration:3200,easing:'linear'}));
    const a=eyes.querySelector('.pqm-cat-gaze').animate([
      {transform:'translateX(0)',easing:'ease-in-out'},{transform:`translateX(${x}px)`,offset:.2},
      {transform:`translateX(${tracking?-amplitude:x}px)`,offset:.85,easing:'ease-in-out'},{transform:'translateX(0)'}
    ],{duration:tracking?flightDuration:3200,easing:'linear'});
    track(a);
    if(tracking&&elapsed){art.currentTime=elapsed;a.currentTime=elapsed}
  };
  const look=()=>{if(!eyes||!catAllowed()||lookTimer!==null)return;lookTimer=setTimeout(()=>{
    lookTimer=null;if(!catAllowed())return;if(!flight&&!lidsBusy&&!reactionPending)gaze();look();
  },16000+Math.random()*12000)};
  const schedule=()=>{
    if(!allowed()||timer!==null||flight)return;
    timer=setTimeout(()=>{timer=null;if(!allowed())return;refreshSurface();if(!surface.safe){schedule();return}launchFlight();
    },20000+Math.random()*10000);
  };
  const launchFlight=()=>{
      const lane=host;
      const sprite=document.createElement('span');sprite.className='halloween-flight-sprite';
      const second=variant++%2!==0,box=second?'1050 0 933 793':'0 0 1050 793';
      // viewBox + xMidYMid meet leaves side gutters inside this viewport.
      // Explicitly clip the atlas frame so adjacent artwork cannot paint there.
      const frameId=second?'pqmWitchFrame2':'pqmWitchFrame1';
      sprite.dataset.witch=second?'2':'1';
      sprite.innerHTML=`<span class="halloween-witch-maneuver"><svg viewBox="${box}" focusable="false"><defs><clipPath id="${frameId}" clipPathUnits="userSpaceOnUse"><rect x="${second?1050:0}" y="0" width="${second?933:1050}" height="793"/></clipPath></defs><image clip-path="url(#${frameId})" href="assets/halloween-witches-sheet.png" width="1983" height="793"/></svg></span>`;
      lane.append(sprite);flight=sprite;
      // Translation is confined to this clipped sky lane, below all workspace content.
      lane.style.setProperty('--flight-distance',(-lane.clientWidth-125)+'px');
      // Extend the route across the heading without increasing travel speed.
      const previousDistance=surface.view.clientWidth*.63+125;
      const duration=13*(lane.clientWidth+125)/previousDistance;
      lane.style.setProperty('--flight-duration',duration+'s');
      gaze(true,duration*1000);
      stopTrail=startTrail(lane,sprite.querySelector('svg'),second);
      sprite.addEventListener('animationend',e=>{if(e.animationName!=='pqm-witch-cross')return;clearFlight();reactAfterFlight();schedule()});
  };
  const sync=()=>{
    refreshSurface();host.hidden=!allowed();
    if(!catAllowed())stopEyes();else{blink();look()}
    if(!allowed()){clear();stopGaze()}else schedule();
  };
  new MutationObserver(sync).observe(root,{attributes:true,attributeFilter:['data-halloween','data-pqm-cat']});
  const visibility=new MutationObserver(sync),size=new ResizeObserver(refreshSurface),content=new MutationObserver(refreshSurface);
  for(const view of views){visibility.observe(view,{attributes:true,attributeFilter:['hidden']});size.observe(view);
    const heading=view.querySelector(':scope > .module-heading,:scope > .page-heading,:scope > .history-heading');
    if(heading){size.observe(heading);content.observe(heading,{childList:true,subtree:true,characterData:true,attributes:true,attributeFilter:['hidden','class']})}
  }
  if(shell)visibility.observe(shell,{attributes:true,attributeFilter:['hidden']});
  for(const dialog of document.querySelectorAll('dialog'))visibility.observe(dialog,{attributes:true,attributeFilter:['open']});
  reduce.addEventListener('change',sync);document.addEventListener('visibilitychange',sync);
  window.addEventListener('pagehide',()=>{paused=true;clear();sync()});
  window.addEventListener('pageshow',()=>{paused=false;sync()});
  window.addEventListener('resize',refreshSurface,{passive:true});window.addEventListener('scroll',refreshSurface,{passive:true,capture:true});
  document.fonts?.ready.then(refreshSurface);
  sync();
})();
