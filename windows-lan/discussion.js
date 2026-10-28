import { state } from '/static/js/state.js';

let moderation = { all_muted: false, muted: false, muted_viewer_ids: [] };
let pending = false;
let ready = false;
let feedbackTimer;

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
  panel.innerHTML = `<div class="discussion-status-row">
      <div id="discussion-status" role="status">学员可自由发言</div>
      <button id="discussion-member-open" type="button" aria-haspopup="dialog" hidden>学员管理 <span aria-hidden="true">›</span></button>
    </div>
    <div id="discussion-feedback" role="status"></div>
    <div id="discussion-error" role="alert"></div>
    <dialog id="discussion-member-settings" aria-labelledby="discussion-member-title">
      <div class="discussion-drawer-heading"><h2 id="discussion-member-title">学员发言管理</h2>
        <button id="discussion-member-close" type="button" aria-label="关闭学员管理">×</button></div>
      <p id="discussion-member-rule" hidden>关闭全员禁言后，单独禁言的学员仍无法发言。</p>
      <input id="discussion-member-search" type="search" placeholder="搜索学员…" aria-label="搜索学员">
      <div class="discussion-filters" role="group" aria-label="学员筛选">
        <button type="button" data-filter="all" aria-pressed="true">全部</button>
        <button type="button" data-filter="muted" aria-pressed="false">已禁言</button>
      </div>
      <div class="discussion-list-heading"><span>学员</span><span>发言限制</span></div>
      <div id="discussion-member-list"></div>
    </dialog>`;
  document.getElementById('chat-messages').before(panel);
  const controls = document.createElement('div');
  controls.id = 'discussion-teacher-controls';
  controls.hidden = true;
  controls.innerHTML = `<button id="discussion-mute-all" type="button" role="switch" aria-checked="false" aria-label="全员禁言">
    <span>全员禁言</span><span class="discussion-switch" aria-hidden="true"></span></button>`;
  document.querySelector('#chat-panel .chat-header').append(controls);
  const drawer = document.getElementById('discussion-member-settings');
  document.getElementById('discussion-member-open').addEventListener('click', () => {
    drawer.showModal();
    for (const id of ['discussion-feedback', 'discussion-error']) drawer.append(document.getElementById(id));
  });
  drawer.addEventListener('close', () => {
    for (const id of ['discussion-feedback', 'discussion-error']) panel.append(document.getElementById(id));
  });
  document.getElementById('discussion-member-close').addEventListener('click', () => drawer.close());
  drawer.addEventListener('click', event => {
    if (event.target === drawer) {
      const rect = drawer.getBoundingClientRect();
      if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) drawer.close();
    }
  });
  document.getElementById('discussion-member-search').addEventListener('input', renderDiscussionMembers);
  for (const filter of drawer.querySelectorAll('[data-filter]')) {
    filter.addEventListener('click', () => {
      for (const item of drawer.querySelectorAll('[data-filter]')) item.setAttribute('aria-pressed', String(item === filter));
      renderDiscussionMembers();
    });
  }
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
  document.getElementById('discussion-member-open').hidden = !teacher;
  const drawer = document.getElementById('discussion-member-settings');
  if (!teacher && drawer.open) drawer.close();
  document.getElementById('discussion-member-rule').hidden = !moderation.all_muted;
  document.getElementById('discussion-controls').classList.toggle('is-muted', teacher ? moderation.all_muted : moderation.muted);
  document.getElementById('discussion-status').textContent = teacher
    ? moderation.all_muted ? '全员禁言中' : '学员可自由发言'
    : moderation.muted ? moderation.all_muted ? '老师已开启全员禁言，你仍可查看讨论' : '老师已将你禁言，你仍可查看讨论'
      : '可自由发言';
  const button = document.getElementById('discussion-mute-all');
  button.setAttribute('aria-checked', String(moderation.all_muted));
  button.disabled = pending;
  refreshDiscussionInputs();
  renderDiscussionMembers();
}

export function renderDiscussionMembers() {
  const list = document.getElementById('discussion-member-list');
  if (!list) return;
  list.replaceChildren();
  if (state.myRole !== 'host') return;
  const query = document.getElementById('discussion-member-search').value.trim().toLocaleLowerCase();
  const onlyMuted = document.querySelector('[data-filter="muted"]').getAttribute('aria-pressed') === 'true';
  const allStudents = state.viewerList.filter(viewer => viewer.role !== 'host');
  const students = allStudents.filter(viewer => String(viewer.name).toLocaleLowerCase().includes(query)
    && (!onlyMuted || (moderation.muted_viewer_ids || []).includes(viewer.id)));
  if (!students.length) {
    const empty = document.createElement('p');
    empty.className = 'discussion-empty';
    empty.textContent = !allStudents.length ? '等待学员加入' : query ? '没有匹配的学员' : '暂无单独禁言的学员';
    list.append(empty);
  }
  for (const student of students) {
    const muted = (moderation.muted_viewer_ids || []).includes(student.id);
    const row = document.createElement('div');
    row.className = 'discussion-member';
    const label = document.createElement('span');
    label.className = 'discussion-member-name';
    label.textContent = student.name;
    const actions = document.createElement('div');
    actions.className = 'discussion-member-actions';
    if (muted) {
      const badge = document.createElement('span');
      badge.className = 'discussion-muted-badge';
      badge.textContent = '已禁言';
      actions.append(badge);
    }
    const button = document.createElement('button');
    button.type = 'button';
    button.textContent = muted ? '解除禁言' : '禁言';
    button.dataset.viewerId = student.id;
    button.setAttribute('aria-label', `${button.textContent}：${student.name}`);
    button.setAttribute('aria-pressed', String(muted));
    button.disabled = pending;
    button.addEventListener('click', () => updatePermission({ scope: 'student', viewer_id: student.id, muted: !muted }));
    actions.append(button);
    row.append(label, actions);
    list.append(row);
  }
}

async function updatePermission(change) {
  if (pending) return;
  pending = true;
  clearTimeout(feedbackTimer);
  document.getElementById('discussion-error').textContent = '';
  document.getElementById('discussion-feedback').textContent = '';
  const studentName = state.viewerList.find(viewer => viewer.id === change.viewer_id)?.name || '该学员';
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
    document.getElementById('discussion-feedback').textContent = change.scope === 'all'
      ? change.muted ? '已开启全员禁言' : '已关闭全员禁言'
      : change.muted ? `已禁言 ${studentName}` : `已解除 ${studentName} 的禁言`;
    feedbackTimer = setTimeout(() => {
      document.getElementById('discussion-feedback').textContent = '';
    }, 3000);
  } catch (error) {
    document.getElementById('discussion-error').textContent = error.message || '设置失败，请检查连接后重试';
  } finally {
    pending = false;
    render();
  }
}
