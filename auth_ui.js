/* Managed accounts extend the existing WEB authentication and session model. */
(() => {
  document.querySelector('#administrationView .reference-tabs').insertAdjacentHTML('beforeend', '<button type="button" id="accessTab" data-admin-tab="access" hidden>Ролі та доступи</button>');
  document.querySelector('#administrationView').insertAdjacentHTML('beforeend', `<section id="accessPanel" class="admin-panel" hidden>
    <h2>Ролі та доступи</h2><p>Керовані ролі та права доступу для облікових записів WEB TEST.</p>
    <label>Роль <select id="accessRole"></select></label><button id="accessNewRole">Нова роль</button>
    <label>Код <input id="accessCode"></label><label>Назва <input id="accessLabel"></label>
    <label>Базова роль <select id="accessBase"><option value="officer">УО</option><option value="viewer">Перегляд</option><option value="admin">Адміністратор</option></select></label>
    <div id="accessPermissions"></div><button id="accessSaveRole">Зберегти роль</button>
    <h3>Користувачі</h3><select id="accessUser"><option value="">Новий користувач</option></select>
    <label>Логін <input id="accessUsername" autocomplete="off"></label><label>Ім’я <input id="accessName"></label>
    <label>Роль <select id="accessUserRole"></select></label><label>УО <select id="accessOfficer"></select></label>
    <label>Новий пароль <input type="password" id="accessPassword" autocomplete="new-password"></label>
    <label><input type="checkbox" id="accessActive" checked> Активний</label><button id="accessSaveUser">Зберегти користувача</button><p id="accessMessage" role="status"></p>
  </section>`);
  let roles=[],functions=[],users=[];
  const q=id=>document.getElementById(id);
  const previousCapabilities=applyRoleCapabilities;
  applyRoleCapabilities=function(me){
    previousCapabilities(me);
    q('accessTab').hidden=!me?.permissions||me.role!=='admin';
    if(!me?.permissions)return;
    const controls={applicationsNav:'applications.read',historyNav:'applications.read',suppliersNav:'suppliers.read',requestsNav:'appeals.read',workQueueNav:'work.read',frameworksNav:'frameworks.read'};
    Object.entries(controls).forEach(([id,key])=>{const el=q(id);if(el)el.disabled=me.permissions[key]===false});
    const actions={resetBtn:'prozorro.update',frameworksRefresh:'prozorro.update',requestsRefresh:'appeals.update',refNazkRefresh:'references.update',refAmcuUploadBtn:'references.update'};
    Object.entries(actions).forEach(([id,key])=>{const el=q(id);if(!el)return;const allowed=me.permissions[key]===true;el.dataset.roleDisabled=allowed?'0':'1';el.disabled=!allowed||el.dataset.runtimeDisabled==='1';if(!allowed)el.title='Дія недоступна для вашої ролі';else if(el.dataset.runtimeDisabled!=='1')el.title=''});
  };
  const option=(value,label)=>`<option value="${esc(value)}">${esc(label)}</option>`;
  function drawPermissions(rights={}) {
    const base=q('accessBase').value;
    const modules=[...new Set(functions.map(f=>f.module))];
    q('accessPermissions').innerHTML=modules.map(m=>`<fieldset><legend>${esc(m)}</legend>${functions.filter(f=>f.module===m).map(f=>`<label style="display:inline-flex;gap:6px;margin:6px 18px 6px 0"><input type="checkbox" data-permission="${esc(f.key)}" ${rights[f.key]?'checked':''} ${(base==='admin'||base==='viewer'&&f.mutation)?'disabled':''}>${esc(f.label)}</label>`).join('')}</fieldset>`).join('');
  }
  function drawRole(){const r=roles.find(r=>r.code===q('accessRole').value);if(!r)return;q('accessCode').value=r.code;q('accessCode').disabled=true;q('accessLabel').value=r.label;q('accessBase').value=r.base_role;q('accessBase').disabled=true;drawPermissions(r.permissions)}
  async function load(){
    const [r,u,o]=await Promise.all([request('/api/admin/access-roles'),request('/api/admin/users'),request('/api/admin/officers?active=1')]);
    roles=r.roles;functions=r.functions;users=u.items;
    q('accessRole').innerHTML=roles.map(r=>option(r.code,r.label)).join('');
    q('accessUserRole').innerHTML=roles.filter(r=>r.active).map(r=>option(r.code,r.label)).join('');
    q('accessUser').innerHTML=option('','Новий користувач')+users.map(u=>option(u.username,u.display_name||u.username)).join('');
    q('accessOfficer').innerHTML=option('','—')+(o.items||[]).map(o=>option(o.id,o.full_name)).join('');drawRole();
  }
  const prior=setAdminTab;setAdminTab=function(name){q('accessPanel').hidden=name!=='access';if(name!=='access')return prior(name);document.querySelectorAll('#administrationView .admin-panel').forEach(p=>p.hidden=p.id!=='accessPanel');document.querySelectorAll('[data-admin-tab]').forEach(p=>p.classList.toggle('active',p.dataset.adminTab==='access'));load().catch(()=>q('accessMessage').textContent='Не вдалося завантажити налаштування доступу')};
  q('accessTab').onclick=()=>setAdminTab('access');q('accessRole').onchange=drawRole;
  q('accessNewRole').onclick=()=>{q('accessCode').disabled=false;q('accessCode').value='';q('accessLabel').value='';q('accessBase').disabled=false;q('accessBase').value='officer';drawPermissions(roles.find(r=>r.code==='officer')?.permissions)};
  q('accessBase').onchange=()=>drawPermissions(roles.find(r=>r.code===q('accessBase').value)?.permissions);
  q('accessUser').onchange=()=>{const u=users.find(u=>u.username===q('accessUser').value)||{};q('accessUsername').value=u.username||'';q('accessUsername').disabled=!!u.username;q('accessName').value=u.display_name||'';q('accessUserRole').value=u.role_code||'officer';q('accessOfficer').value=u.officer_id||'';q('accessActive').checked=u.active!==0;q('accessPassword').value=''};
  async function save(path,data){try{await request(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});q('accessPassword').value='';await load();q('accessMessage').textContent='Збережено'}catch(e){q('accessMessage').textContent=e.message}}
  q('accessSaveRole').onclick=()=>save('/api/admin/access-roles',{code:q('accessCode').value,label:q('accessLabel').value,base_role:q('accessBase').value,permissions:Object.fromEntries([...q('accessPermissions').querySelectorAll('[data-permission]')].map(x=>[x.dataset.permission,x.checked]))});
  q('accessSaveUser').onclick=()=>save('/api/admin/users',{username:q('accessUsername').value,display_name:q('accessName').value,role_code:q('accessUserRole').value,officer_id:q('accessOfficer').value||null,password:q('accessPassword').value,active:q('accessActive').checked});
})();
