import { state } from '/static/js/state.js';
import { toggleSidebar, toggleFullscreen, takeScreenshot, zoomIn, zoomOut, zoomReset } from '/static/js/controls.js';
import { toggleChat } from '/static/js/chat.js';
import { selectMonitor, selectAllGrid } from '/static/js/stream.js';
import { updateSettings, newSession } from '/static/js/api.js';
import { copyText } from '/static/js/browser-compat.js';

const $ = id => document.getElementById(id);
const storageKey = 'classtream_teacher_shortcuts_v1';
const defaults = {palette:'/', help:'?', hide:'h', restore:'Shift+h', link:'l', create:'n',
  sidebar:'b', chat:'c', type:'t', members:'u', grid:'g', fullscreen:'f', screenshot:'s',
  zoomIn:'+', zoomOut:'-', zoomReset:'0', quality:'q', cursor:'k'};
for (let i=1;i<=9;i++) defaults['screen'+i]=String(i);
let preferences = {enabled:true, keys:{...defaults}};
try {
  const saved=JSON.parse(localStorage.getItem(storageKey));
  if (saved && typeof saved.enabled==='boolean' && saved.keys && typeof saved.keys==='object') {
    preferences.enabled=saved.enabled;
    const used=new Set();
    for (const id of [...Object.keys(defaults),'permissions','name','file','code','stats','logout','voice','mute','devices']) {
      const key=saved.keys[id] ?? defaults[id] ?? '';
      if (typeof key==='string' && (!key || validKey(key)) && !used.has(keyIdentity(key))) {
        preferences.keys[id]=key; if(key) used.add(keyIdentity(key));
      } else preferences.keys[id]='';
    }
  }
} catch { /* A blocked or damaged preference store must not prevent class use. */ }
let commands=[], selected=0, filtered=[], returnFocus=null, record=null;
let server=null, revision=null, polling=false, busy=false, requestedFreeze=null, toastTimer;
let autoAttemptedToken=null;
const authenticated = () => state.myRole==='host' && !!state.myAdminToken;
const modal = () => [...document.querySelectorAll('.modal-backdrop:not(.hidden)')].at(-1);
const editable = target => target?.closest('input,textarea,select,button,summary,[contenteditable]:not([contenteditable="false"])');
function save() { document.documentElement.dataset.teacherKeys=preferences.enabled?'on':'off';
  try {localStorage.setItem(storageKey,JSON.stringify(preferences));} catch {toast('浏览器未允许保存快捷键设置',true);} }
function toast(text,error=false) {
  clearTimeout(toastTimer); $('teacher-toast').textContent=text;
  $('teacher-toast').classList.toggle('error',error); $('teacher-toast').hidden=false;
  if(!error) toastTimer=setTimeout(()=>$('teacher-toast').hidden=true,2400);
}
function focusSection(id) {
  document.dispatchEvent(new CustomEvent('classtream:open-panel', {detail:{panel:'settings'}}));
  $('sidebar').classList.remove('collapsed');
  const el=$(id); const details=el?.closest('details'); if(details)details.open=true;
  if(el){el.scrollIntoView({block:'nearest'});if(!el.matches('input,select,button,textarea'))el.tabIndex=-1;el.focus();}
}
function openChat() {if($('chat-panel').classList.contains('hidden'))toggleChat();}
function validKey(key) {
  if(key.toLowerCase()==='v' && window.__CLASSTREAM_VOICE_ENABLED__!==false)return false;
  return /^(Shift\+)?[a-z0-9]$/.test(key) || ['/', '?', '+', '-', '=', '.', ','].includes(key);
}
function keyIdentity(key) {return key==='='?'+':key;}
function eventKey(e) {
  if(e.ctrlKey||e.altKey||e.metaKey)return '';
  const key=e.key.toLowerCase();
  return e.shiftKey && /^[a-z0-9]$/.test(key) ? 'Shift+'+key : key;
}
function openDialog(id, focus) {
  returnFocus=document.activeElement;
  $(id).classList.remove('hidden'); $(focus).focus();
}
function restoreDialogFocus() {
  const visible=returnFocus?.isConnected && returnFocus.getClientRects().length &&
    !returnFocus.closest('[inert],.hidden,[hidden]');
  (visible?returnFocus:$('classroom-menu-btn'))?.focus();
}
function closeDialog(id, restore=true) {
  $(id).classList.add('hidden'); record=null;
  if(restore)restoreDialogFocus();
}
function syncFreeze(hidden) {
  state.sharingFrozen=hidden;
  $('teacher-privacy-banner').hidden=!hidden;
  $('teacher-hide-btn').lastChild.textContent=hidden?'恢复学生画面':'冻结学生画面';
  $('teacher-hide-btn').setAttribute('aria-pressed',String(hidden));
  window.dispatchEvent(new Event('classtream:sharing-status'));
}
async function freeze(hidden) {
  requestedFreeze=hidden;
  if(busy)return;
  busy=true;
  try { while(requestedFreeze!==null){
      const target=requestedFreeze;requestedFreeze=null;
      const response=await fetch('/api/screen/freeze',{method:'POST',headers:{'X-Admin-Token':state.myAdminToken,'Content-Type':'application/json'},body:JSON.stringify({enabled:target})});
      const result=await response.json();
      if(!result.ok)throw new Error('冻结状态修改失败，请检查登录和网络');
      syncFreeze(result.frozen);
      toast(target?'学生画面已冻结':'已解除冻结，学生画面自动继续');
    }
  } catch(e) {
    requestedFreeze=null;
    try {const actual=await api();if(actual.ok)syncFreeze(actual.frozen);} catch { /* Polling retries. */ }
    throw e;
  } finally {busy=false;}
}
async function api(method='GET',data) {
  const response=await fetch('/api/teacher-shortcuts',{method,
    headers:{'X-Admin-Token':state.myAdminToken,'Content-Type':'application/json'},
    ...(data?{body:JSON.stringify(data)}:{})});
  const result=await response.json();
  if(!response.ok || !result.ok)throw new Error(result.error || '快捷键服务不可用，请检查登录或连接');
  return result;
}
function renderServer(result, force=false) {
  const updateToggle=!server || force || $('teacher-settings-dialog').classList.contains('hidden');
  server=result; syncFreeze(result.frozen);
  if(updateToggle)$('teacher-global-enabled').checked=result.enabled;
  $('teacher-global-state').textContent=result.error || (!result.supported?'此系统不支持 Windows 全局快捷键':
    result.enabled?(result.online?'全局快捷键已启用，网页后台也可冻结/解除':'全局快捷键已注册，教师页面离线'):'全局快捷键未启用');
  $('teacher-global-enabled').disabled=!result.supported;
  if(revision!==null && result.revision!==revision && result.result)toast(result.result,!result.online);
  revision=result.revision;
}
async function poll() {
  if(!authenticated() || polling)return;
  polling=true;
  try {
    let result=await api();
    if(result.supported && result.auto_enable && result.ready && !result.enabled && autoAttemptedToken!==state.myAdminToken){
      autoAttemptedToken=state.myAdminToken;
      result=await api('POST',{enabled:true,bindings:result.bindings});
      toast('后台冻结/解除快捷键已自动启用');
    }
    renderServer(result);
  }
  catch(e){$('teacher-global-state').textContent=e.message;}
  finally {polling=false;}
}
function unavailable(command) {
  if(command.single && state.currentMode!=='single')return '请先选择单屏预览';
  if(command.screen && !state.monitors.filter(m=>m.id!==0)[command.screen-1])return '当前没有此编号的屏幕';
  return '';
}
async function run(command) {
  if(!authenticated() || !command)return;
  const reason=unavailable(command); if(reason){toast(reason,true);return;}
  try {await command.action();}catch(e){toast(e.message || '操作失败，请重试',true);}
}
function renderResults() {
  const query=$('teacher-command-search').value.trim().toLowerCase();
  filtered=commands.filter(c=>(c.label+' '+c.search+' '+(preferences.keys[c.id]||'')).toLowerCase().includes(query));
  selected=Math.max(0,Math.min(selected,filtered.length-1));
  $('teacher-command-results').replaceChildren();
  filtered.forEach((c,i)=>{
    const button=document.createElement('button');button.type='button';button.className='teacher-command';
    button.classList.toggle('selected',i===selected);button.dataset.command=c.id;
    const text=document.createElement('span');const reason=unavailable(c);
    text.textContent=c.label+(reason?' · '+reason:'');
    const key=document.createElement('kbd');key.textContent=preferences.enabled?(preferences.keys[c.id]||'未绑定'):'网页按键已关闭';
    button.append(text,key);button.setAttribute('aria-disabled',String(!!reason));
    button.addEventListener('click',()=>{closeDialog('teacher-command-dialog');run(c);});
    $('teacher-command-results').append(button);
  });
  if(!filtered.length)$('teacher-command-results').textContent='没有匹配功能，试试“共享”“讨论”或“截图”';
}
function palette() {openDialog('teacher-command-dialog','teacher-command-search');$('teacher-command-search').value='';selected=0;renderResults();}
function settings() {
  renderBindings();openDialog('teacher-settings-dialog','teacher-web-enabled');
  $('teacher-global-enabled').checked=server?.enabled || false;
  $('teacher-global-hide').value=server?.bindings.hide || 'Ctrl+Alt+Shift+H';
  $('teacher-global-restore').value=server?.bindings.restore || 'Ctrl+Alt+Shift+R';
  poll();
}
function renderBindings() {
  $('teacher-web-enabled').checked=preferences.enabled;
  $('teacher-binding-list').replaceChildren();
  for(const c of commands){
    const row=document.createElement('div');row.className='teacher-binding';
    const label=document.createElement('span');label.textContent=c.label;
    const button=document.createElement('button');button.textContent=preferences.keys[c.id]||'未绑定';
    button.setAttribute('aria-label','重新绑定：'+c.label);button.dataset.bind=c.id;
    button.onclick=()=>{record=c.id;button.textContent='请按键（Esc 取消）';};
    const clear=document.createElement('button');clear.textContent='禁用';clear.setAttribute('aria-label','禁用：'+c.label);
    clear.onclick=()=>{preferences.keys[c.id]='';save();renderBindings();};
    row.append(label,button,clear);$('teacher-binding-list').append(row);
  }
}

export function initTeacherShortcuts() {
  if(document.documentElement.dataset.role!=='teacher')return;
  document.documentElement.dataset.teacherKeys=preferences.enabled?'on':'off';
  $('btn-pause')?.remove();
  document.querySelectorAll('.shortcut-row').forEach(row=>{if(row.textContent.includes('暂停'))row.remove();});
  state.paused=false;
  const toolbar=document.createElement('div'); toolbar.id='teacher-actions';
  toolbar.innerHTML='<button id="teacher-hide-btn" class="btn" aria-pressed="false"><svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg><span>冻结学生画面</span></button><button id="teacher-command-btn" class="btn" aria-label="更多操作与快捷命令"><span aria-hidden="true">···</span><span>更多</span></button><button id="teacher-help-btn" class="host-btn" aria-label="快捷键帮助">快捷键帮助</button>';
  $('bottombar').prepend(toolbar);
  const ui=document.createElement('div');ui.id='teacher-shortcut-ui';
  ui.innerHTML=`
    <div id="teacher-privacy-banner" role="status" hidden>学生画面已冻结 · 学生停留在最后一帧 · 教师预览仍可继续</div>
    <div id="teacher-toast" role="status" aria-live="polite" hidden></div>
    <div id="teacher-command-dialog" class="modal-backdrop hidden" role="dialog" aria-modal="true" aria-label="快捷操作">
      <div class="modal-box teacher-dialog"><div class="teacher-dialog-heading"><h2>快捷操作</h2><button data-close="teacher-command-dialog">关闭 Esc</button></div>
      <input id="teacher-command-search" class="modal-input" aria-label="搜索快捷操作" placeholder="搜索功能、拼音首字母或按键…" autocomplete="off">
      <p>↑ ↓ 选择 · Enter 执行 · 预览操作只影响本机</p><div id="teacher-command-results"></div></div>
    </div>
    <div id="teacher-settings-dialog" class="modal-backdrop hidden" role="dialog" aria-modal="true" aria-label="快捷键设置与帮助">
      <div class="modal-box teacher-dialog"><div class="teacher-dialog-heading"><h2>快捷键设置与帮助</h2><button data-close="teacher-settings-dialog">关闭 Esc</button></div>
      <h3>Windows 全局快捷键</h3><p>网页在后台、最小化或正在使用 PPT 时也能冻结/解除。保持教师登录、管理页连接与服务运行。</p>
      <p id="teacher-global-state" role="status">正在检查全局快捷键…</p>
      <label>冻结共享 <input id="teacher-global-hide" aria-label="全局冻结共享按键" value="Ctrl+Alt+Shift+H"></label>
      <label>解除冻结 <input id="teacher-global-restore" aria-label="全局解除冻结按键" value="Ctrl+Alt+Shift+R"></label>
      <p>登录并连接课堂后自动启用；手动关闭会记住设置，重新启用仍需点击应用。</p>
      <label><input id="teacher-global-enabled" type="checkbox">启用全局快捷键</label><button id="teacher-global-save">应用全局设置</button>
      <h3>教师网页快捷键</h3><p id="teacher-web-state">网页按键仅在此页面获得焦点且未输入文字时生效。教师端不提供暂停观看。</p>
      <label><input id="teacher-web-enabled" type="checkbox">启用网页快捷键</label>
      <button id="teacher-bindings-reset">恢复网页默认按键</button><p>点击按键可重新绑定，支持字母、数字、Shift+字母及 / ? + - = . ,；不占用浏览器组合键。</p>
      <div id="teacher-binding-list"></div></div>
    </div>
    <div id="teacher-new-dialog" class="modal-backdrop hidden" role="dialog" aria-modal="true" aria-label="创建新课堂">
      <div class="modal-box teacher-dialog"><h2>创建新课堂</h2><p>已有课堂会失效，学生需要重新进入。确认后才创建。</p>
      <label>课堂名称<input id="teacher-new-name" class="modal-input" maxlength="80"></label>
      <div class="teacher-dialog-heading"><button data-close="teacher-new-dialog">取消</button><button id="teacher-new-confirm">确认创建</button></div></div>
    </div>`;
  document.body.append(ui);
  $('stage').insertBefore($('teacher-privacy-banner'),$('screen-area'));
  const configButton=document.createElement('button');configButton.className='host-btn';configButton.id='teacher-settings-btn';configButton.textContent='快捷键设置与帮助';
  document.querySelector('.advanced-settings').append(configButton);
  const add=(id,label,search,action,extra={})=>commands.push({id,label,search,action,...extra});
  add('palette','打开快捷操作','kjcz',palette); add('help','快捷键设置与帮助','kjj sz bz',settings);
  add('hide','冻结共享','dj gx',()=>freeze(true));add('restore','解除冻结（自动继续共享）','hf gx',()=>freeze(false));
  add('link','复制上课地址','fz sk dz',async()=>{
    const status=await fetch('/api/status').then(r=>r.json());if(!status.session_token)throw new Error('请先创建课堂');
    const info=await fetch('/lan-info').then(r=>r.json());await copyText(info.student_url);toast('已复制上课地址');
  });
  add('create','创建新课堂','cj kt',()=>{ $('teacher-new-name').value=$('session-name-input').value;openDialog('teacher-new-dialog','teacher-new-name');});
  add('sidebar','课堂面板','kt mb',toggleSidebar);add('chat','课堂讨论','kt tl',toggleChat);
  add('type','输入讨论消息','sr tl xx',()=>{openChat();$('chat-input').focus();});
  add('members','查看课堂成员','ck cy',()=>document.dispatchEvent(new CustomEvent('classtream:open-panel',{detail:{panel:'members'}})));
  add('grid','全部屏幕预览（本地）','qb pm yl',selectAllGrid);
  add('fullscreen','全屏预览（本地）','qp yl',toggleFullscreen);
  add('screenshot','保存截图（本地）','bc jt',takeScreenshot,{single:true});
  add('zoomIn','放大预览（本地）','fd yl',zoomIn,{single:true});add('zoomOut','缩小预览（本地）','sx yl',zoomOut,{single:true});
  add('zoomReset','还原预览大小（本地）','hy yl',zoomReset,{single:true});
  add('quality','设置画面清晰度','sz qxd',()=>focusSection('q-slider'));
  add('cursor','显示/隐藏共享鼠标','xs yc sb',async()=>{const enabled=!$('cursor-cb').checked;
    if(!(await updateSettings({show_cursor:enabled})).ok)throw new Error('鼠标显示设置失败');$('cursor-cb').checked=enabled;toast(enabled?'已显示共享鼠标':'已隐藏共享鼠标');});
  for(let i=1;i<=9;i++)add('screen'+i,`屏幕 ${i} 预览（本地）`,'pm yl',()=>selectMonitor(state.monitors.filter(m=>m.id!==0)[i-1].id),{screen:i});
  add('name','修改教师姓名','xg js xm',()=>focusSection('admin-display-name-input'));
  add('file','上传文件','sc wj',()=>{openChat();$('chat-file-btn').click();});
  add('code','分享代码','fx dm',()=>{openChat();if($('chat-code-panel').classList.contains('hidden'))$('chat-code-btn').click();$('chat-code-input').focus();});
  add('stats','查看连接详情','ck lj xq',()=>focusSection('stat-fps'));
  add('logout','退出教师登录','tc dl',()=>$('identity-btn').click());
  if(window.__CLASSTREAM_VOICE_ENABLED__!==false){
    add('voice','连接 / 断开语音','lj dk yy',()=>$('voice-connect-btn').click());
    add('mute','静音 / 取消静音','jy qx',()=>$('voice-mute-btn').click());
    add('devices','选择语音设备（按住 V 发言）','xz yy sb fy',()=>focusSection('voice-input-select'));
  }
  // Override existing controls in capture phase so mouse and keyboard share commands.
  for(const [id,command] of Object.entries({'teacher-hide-btn':'hide',
    'teacher-command-btn':'palette','teacher-help-btn':'help','teacher-settings-btn':'help',
    'new-session-btn':'create','copy-current-btn':'link','btn-fullscreen':'fullscreen',
    'btn-screenshot':'screenshot','btn-zoom-in':'zoomIn','btn-zoom-out':'zoomOut','btn-zoom-reset':'zoomReset'})){
    $(id)?.addEventListener('click',e=>{e.preventDefault();e.stopImmediatePropagation();hideTooltip();run(commands.find(c=>c.id===(id==='teacher-hide-btn' && state.sharingFrozen?'restore':command)));},true);
    if($(id))$(id).dataset.shortcutCommand=command;
  }
  for(const [id,command] of Object.entries({'sidebar-toggle-btn':'sidebar','chat-toggle-btn':'chat',
    'chat-file-btn':'file','chat-code-btn':'code','identity-btn':'logout','save-display-name-btn':'name'})){
    if($(id))$(id).dataset.shortcutCommand=command;
  }
  const tooltip=document.createElement('div');tooltip.id='teacher-shortcut-tooltip';
  tooltip.role='tooltip';tooltip.hidden=true;document.body.append(tooltip);
  let tooltipButton=null;
  const hideTooltip=()=>{tooltip.hidden=true;tooltipButton?.removeAttribute('aria-describedby');tooltipButton=null;};
  const showTooltip=button=>{
    const id=button.id==='teacher-hide-btn'?(state.sharingFrozen?'restore':'hide'):button.dataset.shortcutCommand;
    const command=commands.find(c=>c.id===id);if(!command)return;
    hideTooltip();tooltipButton=button;
    const key=preferences.enabled?(preferences.keys[id]||'未绑定'):'已关闭';
    tooltip.textContent=command.label+' · 网页：'+key;
    if(id==='hide'||id==='restore')tooltip.textContent+=' · 全局：'+(server?.enabled?server.bindings[id]:'未启用');
    button.setAttribute('aria-describedby',tooltip.id);tooltip.hidden=false;
    const rect=button.getBoundingClientRect();
    tooltip.style.left=Math.max(8,Math.min(rect.left,innerWidth-tooltip.offsetWidth-8))+'px';
    tooltip.style.top=(rect.top>tooltip.offsetHeight+16?rect.top-tooltip.offsetHeight-8:rect.bottom+8)+'px';
  };
  for(const button of document.querySelectorAll('[data-shortcut-command]')){
    button.addEventListener('mouseenter',()=>showTooltip(button));
    button.addEventListener('mouseleave',hideTooltip);
    button.addEventListener('focus',()=>showTooltip(button));
    button.addEventListener('blur',hideTooltip);
    button.addEventListener('click',hideTooltip);
    // The bubble includes the current binding instead of a stale native title.
    if(button.hasAttribute('title'))button.setAttribute('aria-label',commands.find(c=>c.id===button.dataset.shortcutCommand).label);
    button.removeAttribute('title');
  }
  window.addEventListener('resize',hideTooltip);
  document.addEventListener('scroll',hideTooltip,true);
  document.addEventListener('keydown',hideTooltip,true);
  ui.querySelectorAll('[data-close]').forEach(el=>el.onclick=()=>closeDialog(el.dataset.close));
  $('teacher-command-search').oninput=()=>{selected=0;renderResults();};
  $('teacher-web-enabled').onchange=e=>{preferences.enabled=e.target.checked;save();};
  $('teacher-bindings-reset').onclick=()=>{preferences={enabled:true,keys:{...defaults}};save();renderBindings();};
  $('teacher-global-save').onclick=async()=>{
    autoAttemptedToken=state.myAdminToken;
    $('teacher-global-save').disabled=true;
    try {renderServer(await api('POST',{enabled:$('teacher-global-enabled').checked,
      bindings:{hide:$('teacher-global-hide').value.trim(),restore:$('teacher-global-restore').value.trim()}}),true);toast('全局快捷键设置已更新');}
    catch(e){toast(e.message,true);await poll();}
    finally{$('teacher-global-save').disabled=false;}
  };
  $('teacher-new-confirm').onclick=async()=>{
    $('teacher-new-confirm').disabled=true;
    try{const result=await newSession($('teacher-new-name').value.trim()||'我的课堂');
      if(!result.ok)throw new Error('创建课堂失败，请检查连接');
      const info=await fetch('/lan-info').then(r=>r.json());
      $('session-name').textContent=result.name;$('session-name-input').value=result.name;
      $('current-session-link').textContent=info.student_url;$('link-modal-url').textContent=info.student_url;
      closeDialog('teacher-new-dialog',false);openDialog('link-modal','copy-link-btn');
    }catch(e){toast(e.message,true);}finally{$('teacher-new-confirm').disabled=false;}
  };
  document.addEventListener('keydown',e=>{
    if(!authenticated() || e.repeat || e.isComposing || e.keyCode===229)return;
    const dialog=modal();
    if(record && dialog?.id==='teacher-settings-dialog'){
      e.preventDefault();e.stopImmediatePropagation();
      if(e.key==='Escape'){record=null;renderBindings();return;}
      const key=eventKey(e);
      if(!validKey(key) || (key.toLowerCase()==='v' && window.__CLASSTREAM_VOICE_ENABLED__!==false)) {toast('此按键保留或不支持，请换一个按键',true);return;}
      if(Object.entries(preferences.keys).some(([id,k])=>id!==record&&keyIdentity(k)===keyIdentity(key))){toast('此按键已被其他操作占用',true);return;}
      preferences.keys[record]=key;record=null;save();renderBindings();return;
    }
    if(dialog){
      if(e.key==='Escape' && ['teacher-command-dialog','teacher-settings-dialog','teacher-new-dialog','link-modal'].includes(dialog.id)){
        e.preventDefault();closeDialog(dialog.id);return;
      }
      if(dialog.id==='teacher-command-dialog' && e.target===$('teacher-command-search') && ['ArrowDown','ArrowUp','Enter'].includes(e.key)){
        e.preventDefault();if(e.key==='Enter'){const command=filtered[selected];closeDialog(dialog.id);run(command);}
        else{selected=(selected+(e.key==='ArrowDown'?1:-1)+filtered.length)%Math.max(1,filtered.length);renderResults();
          $('teacher-command-results').children[selected]?.scrollIntoView({block:'nearest'});}
      }return;
    }
    if(e.key==='Escape') {
      if(!$('chat-code-panel').classList.contains('hidden')){$('chat-code-close').click();e.preventDefault();return;}
      for(const id of ['chat-reaction-picker','chat-emoji-picker']){
        if(!$(id).classList.contains('hidden')){$(id).classList.add('hidden');e.preventDefault();return;}
      }
      if(!$('chat-reply-bar').classList.contains('hidden')){$('chat-reply-cancel').click();e.preventDefault();return;}
    }
    if(!preferences.enabled || editable(e.target) || !document.hasFocus())return;
    const key=eventKey(e);const command=commands.find(c=>preferences.keys[c.id]===key || (c.id==='zoomIn' && key==='=' && preferences.keys.zoomIn==='+'));
    if(command){e.preventDefault();run(command);}
  },true);
  document.addEventListener('pystream:admin-ready',poll);
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)poll();});
  window.addEventListener('focus',()=>{poll();$('teacher-web-state').textContent='网页按键可用；输入文字、操作控件或打开弹窗时暂停响应。';});
  window.addEventListener('blur',()=>{$('teacher-web-state').textContent='网页快捷键暂不可用；已启用的全局冻结/解除仍可使用。';});
  setInterval(poll,2000);poll();
  // Preserve clipboard-modal focus after it closes through its existing button.
  $('close-link-modal').addEventListener('click',restoreDialogFocus);
}
