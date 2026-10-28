import { state } from '/static/js/state.js';

let moderation = { all_muted: false, muted: false, muted_viewer_ids: [] };
let pending = false;
let ready = false;

export function discussionAllowed() {
  return state.myRole === 'host' || !moderation.muted;
}

export function refreshDiscussionInputs() {
  const muted = !discussionAllowed();
  for (const id of ['chat-input', 'chat-send-btn', 'chat-file-btn', 'chat-file-input',
    'chat-code-btn', 'chat-code-input', 'chat-code-send', 'chat-emoji-btn']) {
    const element = document.getElementById(id);
    if (element) element.disabled = muted;
  }
  document.getElementById('chat-input').placeholder = muted
    ? '老师已禁言，你仍可查看课堂讨论' : '向老师或同学提问…';
  if (muted) {
    for (const id of ['chat-code-panel', 'chat-emoji-picker', 'chat-reaction-picker'])
      document.getElementById(id)?.classList.add('hidden');
  }
}

export function initDiscussion() {
  const panel = document.createElement('div');
  panel.id = 'discussion-controls';
  panel.innerHTML = `<div id="discussion-status" role="status">课堂讨论已开启</div>
    <div id="discussion-teacher-controls" hidden>
      <button id="discussion-mute-all" type="button" aria-pressed="false">全体禁言</button>
      <details id="discussion-member-settings"><summary>学员禁言管理</summary>
        <p>单独禁言会在解除全体禁言后继续生效。</p>
        <div id="discussion-member-list"></div>
      </details>
    </div><div id="discussion-error" role="alert"></div>`;
  document.getElementById('chat-messages').before(panel);
  document.getElementById('discussion-mute-all').addEventListener('click', () =>
    updatePermission({ scope: 'all', muted: !moderation.all_muted }));
  // Existing reaction buttons can be present when a mute arrives.
  document.getElementById('chat-panel').addEventListener('click', event => {
    if (!discussionAllowed() && event.target.closest('.act-react,.reaction-pill')) {
      event.preventDefault();
      event.stopImmediatePropagation();
    }
  }, true);
  ready = true;
  render();
}

export function handleModeration(data) {
  if (!['chat:moderation', 'chat:blocked'].includes(data.type)) return false;
  moderation = data;
  render();
  return true;
}

function render() {
  if (!ready) return;
  const teacher = state.myRole === 'host';
  document.getElementById('discussion-teacher-controls').hidden = !teacher;
  document.getElementById('discussion-status').textContent = teacher
    ? moderation.all_muted ? '全体学员已禁言 · 教师可继续发言' : '课堂讨论已开启 · 学员可自由发言'
    : moderation.muted ? moderation.all_muted ? '老师已开启全体禁言，你仍可查看讨论' : '老师已将你禁言，你仍可查看讨论'
      : '课堂讨论已开启';
  const button = document.getElementById('discussion-mute-all');
  button.textContent = moderation.all_muted ? '解除全体禁言' : '全体禁言';
  button.setAttribute('aria-pressed', String(moderation.all_muted));
  button.disabled = pending;
  refreshDiscussionInputs();
  renderDiscussionMembers();
}

export function renderDiscussionMembers() {
  const list = document.getElementById('discussion-member-list');
  if (!list) return;
  list.replaceChildren();
  if (state.myRole !== 'host') return;
  const students = state.viewerList.filter(viewer => viewer.role !== 'host');
  if (!students.length) list.textContent = '等待学员加入';
  for (const student of students) {
    const muted = (moderation.muted_viewer_ids || []).includes(student.id);
    const row = document.createElement('div');
    row.className = 'discussion-member';
    const label = document.createElement('span');
    label.textContent = student.name;
    const button = document.createElement('button');
    button.type = 'button';
    button.textContent = muted ? '解除禁言' : '禁言';
    button.dataset.viewerId = student.id;
    button.setAttribute('aria-label', `${button.textContent}：${student.name}`);
    button.setAttribute('aria-pressed', String(muted));
    button.disabled = pending;
    button.addEventListener('click', () => updatePermission({ scope: 'student', viewer_id: student.id, muted: !muted }));
    row.append(label, button);
    list.append(row);
  }
}

async function updatePermission(change) {
  if (pending) return;
  pending = true;
  document.getElementById('discussion-error').textContent = '';
  render();
  try {
    const response = await fetch('/api/discussion', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Admin-Token': state.myAdminToken },
      body: JSON.stringify(change),
    });
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error(data.reason || '设置失败，请检查教师登录状态后重试');
    moderation = { ...moderation, ...data, muted: false };
  } catch (error) {
    document.getElementById('discussion-error').textContent = error.message || '设置失败，请检查连接后重试';
  } finally {
    pending = false;
    render();
  }
}
