/* UI-001: the same URL/ID grouping as grouped_application_documents on the server.
 * Keep raw source positions separately; verification indexes address the grouped
 * server list, never the filtered select-option position. No requests or jobs. */
((root,factory)=>{const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.PqmApplicationDocuments=api})(globalThis,()=>{
  function groups(row){
    const seen=new Set(),result={supplier:[],decision:[]};let index=0;
    for(const [group,source] of [['supplier',row.supplierDocuments||[]],['decision',row.decisionDocuments||[]]]){
      source.forEach((document,sourceIndex)=>{
        const key=document.url||document.id;
        if(!key||seen.has(key))return;
        seen.add(key);result[group].push({document,sourceIndex,index:index++});
      });
    }
    return result;
  }
  const name=entry=>String(entry.document.title||entry.document.title_en||'').trim();
  const archive=entry=>/\.(?:zip|rar|7z|tar|gz)$/i.test(name(entry))||/(?:zip|rar|7z|tar|gzip)/i.test(entry.document.format||'');
  function candidates(grouped,category){
    return grouped.supplier.filter(entry=>!archive(entry)&&(category==='signature'
      ?name(entry).toLowerCase()==='sign.p7s'
      :String(entry.document.format||'').split(';')[0].trim().toLowerCase()==='application/pdf'||
        (/\.pdf$/i.test(name(entry))&&(!entry.document.format||/^application\/octet-stream$/i.test(entry.document.format)))));
  }
  function initialValue(entries,stored,category){
    if(category==='signature'&&entries.length===1&&!stored?._explicit)return String(entries[0].index);
    const saved=entries.filter(entry=>Array.isArray(stored?.[entry.index])&&stored[entry.index].includes(category));
    return saved.length===1?String(saved[0].index):'';
  }
  function selection(grouped,values){
    const result={};
    for(const category of ['signature','mvs']){
      const value=values[category];
      if(value!==''&&value!=null&&candidates(grouped,category).some(entry=>String(entry.index)===String(value)))
        (result[value]??=[]).push(category);
    }
    return result;
  }
  return{groups,candidates,initialValue,selection};
});
