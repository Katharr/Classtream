import { state } from '/static/js/state.js';
import { adminLogout } from '/static/js/api.js';
import { toggleChat } from '/static/js/chat.js';
import { initTeacherShortcuts } from '/classroom-ui/teacher-shortcuts.js';

const $ = id => document.getElementById(id);
const teacher = document.documentElement.dataset.role === 'teacher';
initTeacherShortcuts();

const sidebar = $('sidebar');
const chat = $('chat-panel');
const menu = $('classroom-menu');
let drawerTrigger = null;
sidebar.classList.add('collapsed');

// Keep inherited action targets, but put only common actions in the dock.
if (teacher) {
  $('bottombar').append($('teacher-command-btn'));
  $('teacher-settings-btn').before($('teacher-help-btn'));
  $('classroom-more-btn').hidden = true;
} else {
  $('classroom-student-identity').append($('identity-btn'));
}

// Reuse the project's icon style without an external dependency.
function actionIcon(paths) {
  const svg = $('btn-fullscreen').querySelector('svg').cloneNode(true);
  svg.innerHTML = paths; svg.setAttribute('aria-hidden', 'true'); return svg;
}
const inviteText = document.createElement('span'); inviteText.textContent = '邀请学生';
$('classroom-invite-btn').replaceChildren(actionIcon('<path d="M10 13a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-2 2M14 11a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l2-2"/>'), inviteText);
$('classroom-settings-btn').replaceChildren(actionIcon('<path d="M4 7h16M4 17h16"/><circle cx="9" cy="7" r="3" fill="var(--bg)"/><circle cx="15" cy="17" r="3" fill="var(--bg)"/>'));
$('classroom-settings-btn').title = '课堂设置';

document.querySelectorAll('button[title]').forEach(el => el.setAttribute('aria-label', el.title));
for (const [id, label] of Object.entries({
  'admin-password':'教师密码', 'session-name-input':'课堂名称',
  'admin-display-name-input':'教师姓名', 'q-slider':'画面清晰度', 'cursor-cb':'显示老师的鼠标',
  'private-mode-cb':'暂时隐藏所有屏幕', 'chat-input':'课堂消息', 'chat-code-input':'分享代码',
  'voice-input-select':'麦克风', 'voice-output-select':'扬声器',
})) $(id)?.setAttribute('aria-label', label);
document.querySelectorAll('.modal-backdrop').forEach(el => {
  el.setAttribute('role', 'dialog'); el.setAttribute('aria-modal', 'true');
  if (!el.hasAttribute('aria-label')) el.setAttribute('aria-label', el.id === 'admin-modal' ? '教师登录' : '课堂地址');
});
document.querySelectorAll('.full-overlay').forEach(el => el.setAttribute('role', 'alert'));
$('conn-state').setAttribute('role', 'status');
$('chat-messages').setAttribute('role', 'log');
$('chat-messages').setAttribute('aria-label', '课堂讨论消息');
chat.setAttribute('role', 'region'); chat.setAttribute('aria-label', '课堂讨论');

function closeMenus(restore = false) {
  for (const [element, button] of [[menu, $('classroom-menu-btn')]]) {
    if (!element.hidden) {
      element.hidden = true; button.setAttribute('aria-expanded', 'false');
      if (restore) button.focus();
    }
  }
}
function closeSidebar(restore = false) {
  sidebar.classList.add('collapsed');
  if (restore) (drawerTrigger || $('classroom-settings-btn')).focus();
}
function closeChat(restore = false) {
  if (!chat.classList.contains('hidden')) toggleChat();
  if (restore) $('chat-toggle-btn').focus();
}
function openPanel(panel, trigger = $('classroom-settings-btn')) {
  closeMenus(); closeChat();
  sidebar.dataset.panel = panel;
  const label = {room:'课堂管理', settings:'课堂设置', members:'课堂成员'}[panel] || '课堂设置';
  $('classroom-drawer-title').textContent = label;
  sidebar.setAttribute('aria-label', label);
  sidebar.classList.remove('collapsed');
  sidebar.inert = false;
  drawerTrigger = trigger;
  $('classroom-sidebar-close').focus();
}
function togglePanel(panel, trigger) {
  if (!sidebar.classList.contains('collapsed') && sidebar.dataset.panel === panel) closeSidebar(true);
  else openPanel(panel, trigger);
}
function toggleMenu(element, button) {
  const open = element.hidden;
  closeMenus(); closeSidebar(); closeChat();
  if (open) {
    element.hidden = false; button.setAttribute('aria-expanded', 'true');
    const first = [...element.querySelectorAll('button')].find(x => !x.disabled && x.getClientRects().length);
    first?.focus();
  }
}
$('classroom-menu-btn').addEventListener('click', () => toggleMenu(menu, $('classroom-menu-btn')));
$('classroom-settings-btn').addEventListener('click', () => togglePanel('settings', $('classroom-settings-btn')));
$('classroom-more-btn').addEventListener('click', () => togglePanel('settings', $('classroom-more-btn')));
$('viewer-badge').addEventListener('click', () => togglePanel('members', $('viewer-badge')));
$('classroom-menu-members').addEventListener('click', () => openPanel('members', $('classroom-menu-btn')));
$('classroom-room-btn').addEventListener('click', () => openPanel('room', $('classroom-menu-btn')));
$('classroom-sidebar-close').addEventListener('click', () => closeSidebar(true));
$('classroom-chat-close').addEventListener('click', () => closeChat(true));
$('classroom-new-btn').addEventListener('click', () => { closeMenus(); $('new-session-btn').click(); });
$('classroom-invite-btn').addEventListener('click', () => $('copy-current-btn').click());
$('classroom-member-manage').addEventListener('click', () => {
  closeSidebar(); $('discussion-member-open')?.click();
});
document.addEventListener('classtream:open-panel', event => openPanel(event.detail.panel));

// Moderation must also work while the discussion drawer is closed.
const memberDialog = $('discussion-member-settings');
if (memberDialog) document.body.append(memberDialog);

function syncPanels() {
  const sideOpen = !sidebar.classList.contains('collapsed');
  sidebar.inert = !sideOpen;
  for (const [id, panel] of [['classroom-settings-btn', 'settings'], ['viewer-badge', 'members'], ['classroom-more-btn', 'settings']])
    $(id).setAttribute('aria-expanded', String(sideOpen && sidebar.dataset.panel === panel));
  $('sidebar-toggle-btn').setAttribute('aria-expanded', String(sideOpen));
  const chatOpen = !chat.classList.contains('hidden');
  chat.inert = !chatOpen;
  $('chat-toggle-btn').setAttribute('aria-expanded', String(chatOpen));
}
let sideWasOpen = false, chatWasOpen = false;
new MutationObserver(() => {
  const open = !sidebar.classList.contains('collapsed');
  if (open && !sideWasOpen) { closeChat(); closeMenus(); }
  sideWasOpen = open; syncPanels();
}).observe(sidebar, {attributes:true, attributeFilter:['class', 'data-panel']});
new MutationObserver(() => {
  const open = !chat.classList.contains('hidden');
  syncPanels();
  if (open && !chatWasOpen) { closeSidebar(); closeMenus(); $('chat-input').focus(); }
  chatWasOpen = open;
}).observe(chat, {attributes:true, attributeFilter:['class']});
$('chat-toggle-btn').setAttribute('aria-controls', 'chat-panel');
syncPanels();

document.addEventListener('click', e => {
  if (!e.target.closest('#classroom-menu,#classroom-menu-btn')) closeMenus();
  if (e.target.closest('#screen-area')) { closeSidebar(); closeChat(); }
});
const identity = $('identity-btn');
function updateIdentity() {
  identity.textContent = teacher ? '退出登录' : state.myName || '正在分配昵称';
  identity.title = teacher ? '退出教师登录' : '系统随机分配的课堂昵称';
  identity.disabled = !teacher;
  identity.classList.toggle('menu-danger', teacher);
  identity.setAttribute('aria-label', identity.title);
}
identity.addEventListener('click', async () => {
  if (!teacher) return;
  closeMenus();
  if (!confirm('退出后学生将无法继续观看，确定退出教师登录吗？')) { $('classroom-menu-btn').focus(); return; }
  try {
    const result = await adminLogout();
    if (!result.ok) throw new Error('logout');
    localStorage.removeItem('pystream_admin_token'); location.reload();
  } catch { alert('退出失败，请检查连接后重试'); }
});
document.addEventListener('classtream:name-changed', updateIdentity);
document.addEventListener('pystream:admin-ready', updateIdentity);
updateIdentity();
function updateTitle() {
  const title = $('session-name').textContent.trim() || '我的课堂';
  $('classroom-title').textContent = title;
  $('classroom-menu-name').textContent = title;
  $('classroom-menu-btn').title = title + ' · 课堂菜单';
}
new MutationObserver(updateTitle).observe($('session-name'), {childList:true, characterData:true, subtree:true});
updateTitle();

const conn = $('conn-state');
function updateStatus() {
  const phase = conn.dataset.phase || 'waiting';
  const connected = phase === 'live';
  const text = connected ? teacher && state.sharingFrozen ? '学生画面已冻结 · 教师预览实时更新' : teacher ? '正在向学生共享屏幕' : '正在观看老师的屏幕' : conn.dataset.message || '正在等待老师的画面…';
  $('stage-status').textContent = text;
  $('stage-status').dataset.frozen = String(teacher && state.sharingFrozen);
  const badge = {paused:'画面已暂停', frozen:'教师已冻结', source:'画面暂不可用', lagging:'画面落后',
    interrupted:'画面中断', reconnecting:'正在重连', ended:'连接已结束', waiting:'等待画面'};
  $('live-badge').textContent = '● ' + (connected ? '课堂进行中' : badge[phase] || '等待画面');
  $('btn-pause')?.setAttribute('aria-pressed', String(state.paused));
}
new MutationObserver(updateStatus).observe(conn, {childList:true, characterData:true, subtree:true, attributes:true, attributeFilter:['data-phase', 'data-message']});
window.addEventListener('classtream-pause', () => queueMicrotask(updateStatus));
window.addEventListener('classtream:sharing-status', updateStatus);
updateStatus();

document.addEventListener('keydown', e => {
  if (e.defaultPrevented) return;
  const dialog = [...document.querySelectorAll('.modal-backdrop:not(.hidden),dialog[open]')].at(-1);
  if (!dialog && e.key === 'Escape') {
    if (!menu.hidden) { e.preventDefault(); closeMenus(true); }
    else if (!sidebar.classList.contains('collapsed')) { e.preventDefault(); closeSidebar(true); }
    else if (!chat.classList.contains('hidden') && $('chat-code-panel').classList.contains('hidden') && $('chat-emoji-picker').classList.contains('hidden') && $('chat-reply-bar').classList.contains('hidden')) { e.preventDefault(); closeChat(true); }
  }
  if (!dialog || e.key !== 'Tab') return;
  const fields = [...dialog.querySelectorAll('button,input,textarea,select,a[href]')].filter(el => !el.disabled && el.getClientRects().length);
  const first = fields[0], last = fields.at(-1);
  if (e.shiftKey && (document.activeElement === first || !dialog.contains(document.activeElement))) { e.preventDefault(); last?.focus(); }
  else if (!e.shiftKey && (document.activeElement === last || !dialog.contains(document.activeElement))) { e.preventDefault(); first?.focus(); }
});
