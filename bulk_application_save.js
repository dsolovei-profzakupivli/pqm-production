/* Sequential, bounded, compare-and-set bulk editing. No implicit retries. */
(function(root){
  'use strict';
  const same=(a,b)=>Object.keys(a).every(key=>Object.hasOwn(b,key)&&String(b[key]??'')===a[key]);
  function create(items,changes){
    const desired=Object.freeze(Object.fromEntries(Object.entries(changes).map(([k,v])=>[k,String(v??'')])));
    return items.map(item=>({id:String(item.id),desired,expected:item.expected?Object.freeze({...item.expected}):null,
      status:'pending',attempts:0,detail:''}));
  }
  async function reconcile(item,read){
    try{
      const current=await read(item.id,Object.keys(item.desired));
      if(!current||Object.keys(item.desired).some(k=>!Object.hasOwn(current,k)||typeof current[k]!=='string'))throw new Error('invalid_readback');
      if(same(item.desired,current)){item.status='confirmed';item.detail='';return 'confirmed'}
      if(!item.expected){
        // Unseen selected rows must never silently adopt an existing number.
        if(Object.hasOwn(item.desired,'protocol_number')&&current.protocol_number!==''&&current.protocol_number!==item.desired.protocol_number){
          item.status='conflict';item.detail='Номер уже заповнений; потрібна перевірка УО';return 'conflict';
        }
        item.expected=Object.freeze({...current});
      }
      if(!same(item.expected,current)){item.status='conflict';item.detail='Дані змінилися; перезапис заблоковано';return 'conflict'}
      item.status='unconfirmed';item.detail='Звірено: потрібне значення ще не збережено';return 'retryable';
    }catch(error){item.status='unconfirmed';item.detail='Не вдалося звірити з БД; повторний запис не виконано';return 'unknown'}
  }
  async function run(items,transport,{retry=false}={}){
    for(const item of items){
      if(retry){
        if(item.status!=='unconfirmed'||item.attempts>=2)continue;
        if(await reconcile(item,transport.read)!=='retryable')continue;
      }else{
        if(item.status!=='pending')continue;
        if(!item.expected&&await reconcile(item,transport.read)!=='retryable')continue;
      }
      item.attempts++;
      try{
        const response=await transport.write(item.id,item.desired,item.expected);
        if(response?.saved===true){item.status='confirmed';item.detail=''}
        else await reconcile(item,transport.read);
      }catch(error){
        if(error.code==='bulk_value_conflict'){
          item.status='conflict';item.detail='Значення змінила інша УО; перезапис заблоковано';
        }else if(error.httpStatus>=400&&error.httpStatus<500&&![408,429].includes(error.httpStatus)){
          item.status='error';item.detail=error.message||'Запис відхилено';
        }else await reconcile(item,transport.read);
      }
    }
    return summary(items);
  }
  function summary(items){
    const counts={total:items.length,confirmed:0,unconfirmed:0,conflict:0,error:0};
    for(const item of items)counts[item.status==='pending'?'unconfirmed':item.status]++;
    return counts;
  }
  const api={create,run,summary,reconcile};
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
  else root.PqmBulkSave=api;
})(typeof globalThis!=='undefined'?globalThis:this);
