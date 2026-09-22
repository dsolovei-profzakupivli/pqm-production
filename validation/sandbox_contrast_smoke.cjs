// Synthetic DOM/style test: no browser, HTTP, storage or business data.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../sandbox_contrast.js'),'utf8');
class Element {
  constructor(bg='rgba(0, 0, 0, 0)',tag='DIV') {
    this.tagName=tag;this.nodeType=1;this.children=[];this.parentElement=null;
    this.namespaceURI='http://www.w3.org/1999/xhtml';this.isConnected=true;this.attrs=new Set();
    this.style={backgroundColor:bg,backgroundImage:'none',display:'block'};
  }
  add(node) {node.parentElement=this;this.children.push(node);return node;}
  hasAttribute(k){return this.attrs.has(k);}
  toggleAttribute(k,on){on?this.attrs.add(k):this.attrs.delete(k);}
  contains(node){return this===node||this.children.some(c=>c.contains(node));}
}
function harness(env='sandbox') {
  const html=new Element('rgb(11, 23, 42)','HTML');html.dataset={pqmEnvironment:env};
  const body=html.add(new Element('rgb(11, 23, 42)','BODY'));
  const frames=[],listeners={};let callback,options,reads=0;
  const context={document:{documentElement:html,body,readyState:'complete',addEventListener:(k,f)=>listeners[k]=f},
    window:{addEventListener:(k,f)=>listeners[k]=f},getComputedStyle:n=>{reads++;return n.style;},
    requestAnimationFrame:f=>{frames.push(f);return frames.length;},
    MutationObserver:class {constructor(f){callback=f;}observe(n,o){options=o;}}};
  vm.runInNewContext(source,context);
  return {body,frames,listeners,flush(){while(frames.length)frames.shift()();},
    mutate(records){callback(records);},get options(){return options;},get reads(){return reads;}};
}
const h=harness(),white=h.body.add(new Element('rgb(255, 255, 255)'));
const text=white.add(new Element()),deep=text.add(new Element());
const dark=white.add(new Element('rgb(19, 40, 64)')),darkText=dark.add(new Element());
const pale=h.body.add(new Element('rgb(255, 248, 219)'));
const alpha=h.body.add(new Element('rgba(255, 255, 255, 0.95)'));
const image=h.body.add(new Element('rgb(255, 255, 255)','SVG'));image.namespaceURI='http://www.w3.org/2000/svg';
const gradient=h.body.add(new Element('rgb(255, 255, 255)'));gradient.style.backgroundImage='linear-gradient(black, white)';
h.flush();
for(const n of [white,text,deep,pale,alpha])assert(n.hasAttribute('data-pqm-light-ink'));
for(const n of [h.body,dark,darkText,image,gradient])assert(!n.hasAttribute('data-pqm-light-ink'));
assert(dark.hasAttribute('data-pqm-dark-ink'),'dark child must not inherit black ink');
assert(!h.options.attributeFilter.includes('data-pqm-light-ink'),'no observer feedback loop');
assert(!h.options.attributeFilter.includes('data-pqm-dark-ink'));
white.style.backgroundColor='rgb(19, 40, 64)';
h.mutate([{type:'attributes',target:white}]);h.flush();
for(const n of [white,text,deep,dark])assert(!n.hasAttribute('data-pqm-light-ink'));
assert(!dark.hasAttribute('data-pqm-dark-ink'),'remove stale boundary marker');
const modal=h.body.add(new Element('rgb(250, 250, 250)'));modal.style.display='none';
h.mutate([{type:'childList',addedNodes:[modal]}]);h.flush();assert(!modal.hasAttribute('data-pqm-light-ink'));
modal.style.display='block';h.mutate([{type:'attributes',target:modal}]);h.flush();assert(modal.hasAttribute('data-pqm-light-ink'));
const child=modal.add(new Element());const before=h.reads;
h.mutate([{type:'attributes',target:modal},{type:'attributes',target:child}]);
assert.equal(h.frames.length,1);h.flush();assert(child.hasAttribute('data-pqm-light-ink'));
assert.equal(h.reads-before,4,'overlapping roots scanned only once, including ancestors');
modal.style.backgroundColor='rgb(19, 40, 64)';h.listeners.pointerover({target:modal});h.flush();
assert(!modal.hasAttribute('data-pqm-light-ink'));
const prod=harness('production');assert.equal(prod.frames.length,0);assert.equal(prod.options,undefined);
console.log('Sandbox contrast PASS: white/pastel/alpha, transparent descendants, dark boundaries, dynamic/hidden/hover surfaces, batching, no feedback loop, production no-op');
