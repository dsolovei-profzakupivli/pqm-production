/* Explicit selection snapshot, scoped to filters, independent of pagination. */
(function(root){
  'use strict';
  function signature(filters){
    return JSON.stringify(Object.keys(filters).filter(k=>!['page','size','sort','direction','sorts'].includes(k))
      .sort().map(k=>[k,String(filters[k]??'')]));
  }
  function create(selected=new Set()){
    let scope=null,revision=0;
    const snapshots=new Map();
    const clone=row=>JSON.parse(JSON.stringify(row));
    return {
      selected,get scope(){return scope},get revision(){return revision},
      sync(filters){const next=signature(filters);if(next===scope)return 0;
        const count=selected.size;selected.clear();snapshots.clear();scope=next;revision++;return count},
      toggle(row,on){if(on){if(!selected.has(row.id))snapshots.set(row.id,clone(row));selected.add(row.id)}
        else{selected.delete(row.id);snapshots.delete(row.id)}revision++},
      page(rows,on=true){for(const row of rows)this.toggle(row,on)},
      all(rows,expectedScope,expectedRevision){
        if(scope!==expectedScope||revision!==expectedRevision)return false;
        if(new Set(rows.map(row=>row.id)).size!==rows.length)throw new Error('duplicate_selection_ids');
        selected.clear();snapshots.clear();for(const row of rows)this.toggle(row,true);return true;
      },
      remember(rows){for(const row of rows)if(selected.has(row.id)&&!snapshots.has(row.id))snapshots.set(row.id,clone(row))},
      entries(){return [...selected].map(id=>snapshots.get(id)).filter(Boolean).map(clone)},
      remove(id){selected.delete(id);snapshots.delete(id);revision++}
    };
  }
  const api={signature,create};
  if(typeof module!=='undefined'&&module.exports)module.exports=api;else root.PqmApplicationSelection=api;
})(typeof globalThis!=='undefined'?globalThis:this);
