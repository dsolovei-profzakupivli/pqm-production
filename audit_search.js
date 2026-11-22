/* One active search per window, latest pending query only. No global user lock. */
(function(root){
  function create({request,params,render,clear,error,clientId}){
    let generation=0,wire=0,active=null,pending=null;
    function invalidate(){
      generation++;clear();
      if(pending){pending.resolve();pending=null}
      if(active&&!active.cancelSent){active.cancelSent=true;request(new URLSearchParams({client_id:clientId,request_id:String(++wire),cancel:'1'})).catch(()=>{})}
    }
    async function pump(){
      if(active||!pending)return;
      const task=pending;pending=null;active=task;
      const query=new URLSearchParams(task.query);query.set('client_id',clientId);query.set('request_id',String(++wire));
      try{const data=await request(query);if(task.generation===generation)render(data)}
      catch(exc){if(task.generation===generation)error(exc)}
      finally{task.resolve();active=null;pump()}
    }
    function load(){invalidate();return new Promise(resolve=>{pending={generation,query:params(),resolve};pump()})}
    return {load,invalidate};
  }
  root.PqmAuditSearch={create};
})(typeof module==='object'?module.exports:globalThis);
