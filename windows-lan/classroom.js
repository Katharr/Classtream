import { state } from '/static/js/state.js';
import { adminLogout } from '/static/js/api.js';
import { initTeacherShortcuts } from '/classroom-ui/teacher-shortcuts.js';

const teacher = document.documentElement.dataset.role === 'teacher';
if (teacher) {
  document.querySelector('.stage-heading h1').textContent='屏幕共享预览';
  document.querySelector('.eyebrow').textContent='教师工作台';
  document.querySelector('.stage-footer span').textContent='保持此页面在线，学生即可观看你的屏幕';
}
initTeacherShortcuts();
const sidebar = document.getElementById('sidebar');
if (!teacher || matchMedia('(max-width:760px)').matches) sidebar.classList.add('collapsed');
document.querySelectorAll('button[title]').forEach(el => el.setAttribute('aria-label',el.title));
for (const [id, label] of Object.entries({
  'admin-password':'教师密码', 'session-name-input':'课堂名称',
  'admin-display-name-input':'教师姓名', 'q-slider':'画面清晰度', 'cursor-cb':'显示老师的鼠标',
  'private-mode-cb':'暂时隐藏所有屏幕', 'chat-input':'课堂消息', 'chat-code-input':'分享代码',
  'voice-input-select':'麦克风', 'voice-output-select':'扬声器',
})) document.getElementById(id)?.setAttribute('aria-label',label);
document.querySelectorAll('.modal-backdrop').forEach(el => {
  el.setAttribute('role','dialog'); el.setAttribute('aria-modal','true');
  if(!el.hasAttribute('aria-label')) el.setAttribute('aria-label',el.id==='admin-modal'?'教师登录':'课堂地址');
});
document.querySelectorAll('.full-overlay').forEach(el => el.setAttribute('role','alert'));
document.getElementById('conn-state').setAttribute('role','status');
document.getElementById('chat-messages').setAttribute('role','log');
document.getElementById('chat-messages').setAttribute('aria-label','课堂讨论消息');

const identity = document.getElementById('identity-btn');
function updateIdentity() {
  identity.textContent = teacher ? '退出登录' : state.myName || '正在分配昵称';
  identity.title = teacher ? '退出教师登录' : '系统随机分配的课堂昵称';
  identity.disabled = !teacher;
  identity.setAttribute('aria-label', identity.title);
}
identity.addEventListener('click', async () => {
  if (teacher) {
    if (!confirm('退出后学生将无法继续观看，确定退出教师登录吗？')) return;
    try {
      const result = await adminLogout();
      if (!result.ok) throw new Error('logout');
      localStorage.removeItem('pystream_admin_token');
      location.reload();
    } catch { alert('退出失败，请检查连接后重试'); }
  }
});
document.addEventListener('classtream:name-changed', updateIdentity);
document.addEventListener('pystream:admin-ready', updateIdentity);
updateIdentity();

const conn = document.getElementById('conn-state');
const stageStatus = document.getElementById('stage-status');
const live = document.getElementById('live-badge');
function updateStatus() {
  const phase = conn.dataset.phase || 'waiting';
  const connected = phase === 'live';
  const text = connected ? teacher && state.sharingFrozen ? '学生画面已冻结' : '正在共享' : conn.dataset.message || '正在等待老师的画面…';
  stageStatus.textContent = text;
  const badge = { paused:'画面已暂停', frozen:'教师已冻结', source:'画面暂不可用', lagging:'画面落后',
    interrupted:'画面中断', reconnecting:'正在重连', ended:'连接已结束', waiting:'等待画面' };
  live.textContent = '● ' + (connected ? '课堂进行中' : badge[phase] || '等待画面');
  live.style.color = connected ? 'var(--green)' : 'var(--text-dim)';
  document.getElementById('btn-pause')?.setAttribute('aria-pressed',String(state.paused));
}
new MutationObserver(updateStatus).observe(conn,{childList:true,characterData:true,subtree:true,attributes:true,attributeFilter:['data-phase','data-message']});
window.addEventListener('classtream-pause',()=>queueMicrotask(updateStatus));
window.addEventListener('classtream:sharing-status',updateStatus);
updateStatus();

// Keep toggle state accessible for mouse, keyboard shortcuts and resize layouts.
for (const [panel, button, collapsed] of [['sidebar','sidebar-toggle-btn','collapsed'],['chat-panel','chat-toggle-btn','hidden']]) {
  const element = document.getElementById(panel);
  const toggle = document.getElementById(button);
  const sync = () => toggle.setAttribute('aria-expanded',String(!element.classList.contains(collapsed)));
  toggle.setAttribute('aria-controls',panel);
  new MutationObserver(sync).observe(element,{attributes:true,attributeFilter:['class']});
  sync();
}

// Trap keyboard focus inside active dialogs.
document.addEventListener('keydown',e=>{
  const dialog = [...document.querySelectorAll('.modal-backdrop:not(.hidden)')].at(-1);
  if (!dialog || e.key!=='Tab') return;
  const fields = [...dialog.querySelectorAll('button,input,textarea,select,a[href]')].filter(el=>!el.disabled && el.getClientRects().length);
  const first=fields[0], last=fields.at(-1);
  if(e.shiftKey && (document.activeElement===first || !dialog.contains(document.activeElement))){e.preventDefault();last?.focus();}
  else if(!e.shiftKey && (document.activeElement===last || !dialog.contains(document.activeElement))){e.preventDefault();first?.focus();}
});
