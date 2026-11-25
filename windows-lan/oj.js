'use strict';

const teacher = location.pathname === '/oj/teacher';
const root = document.querySelector('#oj');
const nav = document.querySelector('#nav');
const account = document.querySelector('#account');
const tokenKey = 'pystream_admin_token';
const verdicts = {
  queued: '排队中', running: '评测中', finished: '已完成', accepted: '通过', partial: '部分得分',
  compile_error: '编译错误', runtime_error: '运行错误', timeout: '超时', memory_limit: '超出内存限制',
  wrong_answer: '答案错误', output_limit: '输出超限', judge_error: '评测环境错误'
};
let identity;
let adminToken = teacher ? localStorage.getItem(tokenKey) : null;
let revision = 0;
let timer;

function element(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === undefined || value === null || value === false) continue;
    if (key.startsWith('on')) node.addEventListener(key.slice(2), value);
    else if (value === true) node.setAttribute(key, '');
    else node.setAttribute(key, value);
  }
  node.append(...children.flat().filter(child => child !== null && child !== undefined));
  return node;
}

const link = (text, href, className) => element('a', { href, class: className }, text);
const button = (text, onclick, className = 'button') => element('button', { type: 'button', onclick, class: className }, text);
const submitButton = text => element('button', { type: 'submit', class: 'button primary' }, text);
const title = text => element('h1', {}, text);
const badge = (text, color) => element('span', { class: 'badge ' + color }, text);
const sheetBadge = sheet => badge(sheet.open ? '开放' : '历史', sheet.open ? 'green' : 'yellow');
const pre = text => element('pre', {}, text);
const empty = text => element('p', { class: 'empty' }, text);
const errorLine = () => element('p', { class: 'feedback', role: 'status', hidden: true });

function feedback(node, text, positive = false) {
  node.textContent = text;
  node.classList.toggle('success', positive);
  node.hidden = !text;
}

async function api(path, method = 'GET', data) {
  const headers = {};
  if (teacher && adminToken) headers['X-Admin-Token'] = adminToken;
  if (data !== undefined) headers['Content-Type'] = 'application/json';
  const response = await fetch(path.startsWith('/api/') ? path : '/api/oj' + (teacher ? '/teacher' : '') + path, {
    method, headers, body: data === undefined ? undefined : JSON.stringify(data), cache: 'no-store'
  });
  if (response.status === 204) return;
  const body = await response.json();
  if (!response.ok) {
    const error = new Error(typeof body.detail === 'string' ? body.detail : '请检查输入后重试');
    error.status = response.status;
    error.code = body.code;
    throw error;
  }
  return body;
}

function field(label, name, value = '', attributes = {}, multiline = false) {
  const control = element(multiline ? 'textarea' : 'input', { name, ...attributes });
  control.value = value;
  return element('label', { class: 'field' }, element('span', {}, label), control);
}

function formOf(fields, label, action) {
  const notice = errorLine();
  const send = submitButton(label);
  return element('form', { class: 'form', onsubmit: async event => {
    event.preventDefault();
    const form = event.currentTarget;
    if (send.disabled) return;
    send.disabled = true;
    feedback(notice, '');
    try {
      await action(new FormData(form), form);
    } catch (error) {
      feedback(notice, error.message);
    } finally {
      send.disabled = false;
    }
  } }, fields, element('div', { class: 'actions' }, send, notice));
}

function goto(href) {
  if (location.hash === href) void render();
  else location.hash = href;
}

function login() {
  return element('section', { class: 'login' }, title(teacher ? '教师登录' : '学员登录'), formOf([
    field('用户名', 'username', '', { required: true, maxlength: 32, autocomplete: 'username' }),
    field('密码', 'password', '', { type: 'password', required: true, maxlength: 128, autocomplete: 'current-password' })
  ], '登录', async values => {
    const data = Object.fromEntries(values);
    if (teacher) {
      const session = await api('/api/admin/login', 'POST', data);
      adminToken = session.token;
      localStorage.setItem(tokenKey, adminToken);
    } else {
      identity = await api('/login', 'POST', data);
    }
    await render();
  }));
}

function chrome(route, loggedIn) {
  const tabs = teacher ? [['题单', 'sheets'], ['题库', 'problems'], ['学员', 'students'], ['提交记录', 'submissions']]
                       : [['题单', 'sheets'], ['我的提交', 'submissions']];
  nav.replaceChildren(...(loggedIn ? tabs.map(([name, path]) => (
    element('a', { href: '#' + path, 'aria-current': route === path ? 'page' : undefined }, name)
  )) : []));
  account.replaceChildren();
  if (!loggedIn) return;
  const logoutError = errorLine();
  account.append(element('span', {}, teacher ? '教师' : identity.username),
    button('退出', async () => {
      try {
        if (teacher) {
          await api('/api/admin/logout', 'POST');
          adminToken = null;
          localStorage.removeItem(tokenKey);
        } else await api('/logout', 'POST');
        identity = null;
        await render();
      } catch (error) {
        feedback(logoutError, error.message);
      }
    }, 'text-button'), logoutError);
}

function heading(name, action) {
  return element('div', { class: 'heading' }, title(name), action);
}

function rows(items, draw, fallback) {
  return items.length ? element('ul', { class: 'rows' }, items.map((item, index) => element('li', {}, draw(item, index))))
                      : empty(fallback);
}

function sheetList(sheets) {
  return [heading('题单', teacher ? link('新建题单', '#sheets/new', 'button primary') : null),
    rows(sheets, sheet => element('a', { href: '#sheets/' + sheet.id, class: 'sheet-tile ' + (sheet.open ? 'open' : 'closed') },
      element('strong', {}, sheet.title), sheetBadge(sheet)), '暂无题单')];
}

function studentSheet(sheet) {
  return [link('返回题单', '#sheets', 'back'), heading(sheet.title, sheetBadge(sheet)),
    rows(sheet.problems, (problem, index) => element('a', { class: 'row-link', href: `#sheets/${sheet.id}/${problem.id}` },
      element('span', {}, `${index + 1}. ${problem.title}`), element('span', { class: 'meta' }, `${problem.max_score} 分`)), '题单暂无题目')];
}

function timeText(seconds) {
  return new Date(seconds * 1000).toLocaleString('zh-CN', { hour12: false });
}

function mark(record) {
  const key = record.verdict || record.status;
  const color = key === 'accepted' ? 'green' : ['partial', 'queued', 'running'].includes(key) ? 'yellow' : 'neutral';
  return badge(verdicts[key] || '未知状态', color);
}

function result(record) {
  return [element('div', { class: 'result-title' }, mark(record),
    record.kind === 'judge' && record.score !== undefined ? element('strong', {}, `${record.score} / ${record.max_score} 分`) : null),
  record.detail ? pre(record.detail) : null,
  record.output !== undefined ? element('section', {}, element('h3', {}, '程序输出'), pre(record.output)) : null,
  record.kind === 'judge' && record.cases?.length ? element('ol', { class: 'test-results' }, record.cases.map(group =>
    element('li', {}, element('span', {}, `${group.points} 分组`), mark(group)))) : null];
}

function pollSubmission(id, update, current, notice) {
  clearTimeout(timer);
  timer = setTimeout(async () => {
    if (current !== revision) return;
    try {
      const record = await api('/submissions/' + id);
      if (current !== revision) return;
      update.replaceChildren(...result(record).filter(Boolean));
      if (record.status !== 'finished') pollSubmission(id, update, current, notice);
    } catch (error) {
      if (current !== revision) return;
      feedback(notice, error.message);
      if (error.status !== 401 && error.status !== 403 && error.status !== 404) pollSubmission(id, update, current, notice);
    }
  }, 750);
}

function studentProblem(problem, sheetId, current) {
  const sample = element('div', { class: 'samples' },
    element('section', {}, element('h3', {}, '样例输入'), pre(problem.sample_input)),
    element('section', {}, element('h3', {}, '样例输出'), pre(problem.sample_output)));
  const statement = element('article', { class: 'paper' }, element('h2', {}, '题面'),
    element('p', { class: 'statement' }, problem.statement), sample);
  const headingRow = heading(problem.title, sheetBadge(problem));
  const details = element('p', { class: 'meta limits' }, `时限 ${problem.time_ms} ms　内存 ${problem.memory_mb} MB　满分 ${problem.max_score}`);
  if (!problem.open) return [link('返回题单', '#sheets/' + sheetId, 'back'), headingRow, details, statement];

  const notice = errorLine();
  const updates = element('div', { class: 'judge-result', 'aria-live': 'polite' });
  const draft = `oj-draft:${identity.id}:${problem.id}`;
  const editor = element('textarea', { id: 'source', class: 'editor', maxlength: 65536, spellcheck: 'false',
    autocapitalize: 'off', autocomplete: 'off', oninput: event => sessionStorage.setItem(draft, event.target.value) });
  editor.value = sessionStorage.getItem(draft) || '';
  const sampleButton = button('测试样例', () => send('sample'));
  const judgeButton = button('提交评测', () => send('judge'), 'button primary');
  const reloadButton = button('刷新题面', () => void render());
  reloadButton.hidden = true;
  let waiting = false;
  async function send(kind) {
    if (waiting) return;
    if (!editor.value.trim()) {
      feedback(notice, '请输入 C++17 源码');
      editor.focus();
      return;
    }
    waiting = sampleButton.disabled = judgeButton.disabled = true;
    feedback(notice, '');
    try {
      const submission = await api(`/sheets/${sheetId}/problems/${problem.id}/submissions`, 'POST',
        { kind, source: editor.value, version: problem.version });
      if (current !== revision) return;
      updates.replaceChildren(mark(submission), link('查看提交', '#submissions/' + submission.id));
      pollSubmission(submission.id, updates, current, notice);
    } catch (error) {
      reloadButton.hidden = error.code !== 'problem_version_changed';
      feedback(notice, error.message);
    } finally {
      waiting = sampleButton.disabled = judgeButton.disabled = false;
    }
  }
  return [link('返回题单', '#sheets/' + sheetId, 'back'), headingRow, details,
    element('div', { class: 'workspace' }, statement, element('section', { class: 'code-panel' },
      element('label', { for: 'source', class: 'code-label' }, 'C++17 源码'), editor,
      element('div', { class: 'actions' }, sampleButton, judgeButton, reloadButton), notice, updates))];
}

function submissionList(records, before) {
  return [heading(teacher ? '提交记录' : '我的提交', button('刷新', () => void render())),
    rows(records, record => element('a', { class: 'row-link record', href: '#submissions/' + record.id },
      element('span', {}, element('strong', {}, record.title), element('small', { class: 'meta' },
        `${teacher ? record.username + '　' : ''}${record.kind === 'sample' ? '样例' : '评测'} · v${record.version} · ${timeText(record.created_at)}`)),
      element('span', { class: 'record-end' }, mark(record), record.kind === 'judge' && record.score !== undefined ? `${record.score} 分` : null)
    ), '暂无提交'),
    element('div', { class: 'actions pagination' }, before ? link('返回最新', '#submissions', 'button') : null,
      records.length === 50 ? link('更早记录', '#submissions/before/' + records.at(-1).id, 'button') : null)];
}

function submissionDetail(record, current) {
  const notice = errorLine();
  const display = element('div', { class: 'judge-result', 'aria-live': 'polite' }, result(record));
  if (record.status !== 'finished') pollSubmission(record.id, display, current, notice);
  return [link('返回提交记录', '#submissions', 'back'), title(record.title),
    element('p', { class: 'meta' }, `${teacher ? record.username + '　' : ''}${timeText(record.created_at)}　${record.kind === 'sample' ? '样例' : '评测'}　`,
      teacher ? link(`题目版本 v${record.version}`, `#problems/${record.problem_id}/${record.version}`) : `题目版本 v${record.version}`),
    display, notice, element('h2', {}, '提交源码'), pre(record.source)];
}

function roster(data) {
  const notice = errorLine();
  return [title('学员'), element('p', { class: 'roster-password' }, '默认密码　', element('code', {}, data.default_password)),
    formOf([field('用户名', 'username', '', { required: true, maxlength: 32 })], '添加学员', async values => {
      await api('/students', 'POST', Object.fromEntries(values));
      await render();
    }), notice,
    rows(data.students, student => element('div', { class: 'row-link' }, element('strong', {}, student.username),
      button('重置密码', async event => {
        const control = event.currentTarget;
        control.disabled = true;
        try {
          await api(`/students/${student.id}/reset`, 'POST');
          feedback(notice, `已重置 ${student.username} 的密码`, true);
        } catch (error) {
          feedback(notice, error.message);
        } finally {
          control.disabled = false;
        }
      })), '暂无学员')];
}

function teacherProblems(problems) {
  return [heading('题库', link('新建题目', '#problems/new', 'button primary')),
    rows(problems, problem => element('a', { class: 'row-link', href: '#problems/' + problem.id },
      element('strong', {}, problem.title), element('span', { class: 'meta' }, `v${problem.version} · ${problem.max_score} 分`)), '暂无题目')];
}

function problemEditor(problem) {
  const data = problem || { title: '', statement: '', sample_input: '', sample_output: '', time_ms: 1000,
    memory_mb: 256, groups: [{ input: '', output: '', score: 100 }] };
  const groupList = element('div', { class: 'groups' });
  const addGroup = button('添加数据组', () => add({ input: '', output: '', score: 100 }));
  function order() {
    const groups = [...groupList.children];
    groups.forEach((item, index) => {
      item.querySelector('legend').textContent = '数据组 ' + (index + 1);
      item.querySelector('button').disabled = groups.length < 2;
    });
    addGroup.disabled = groups.length >= 20;
  }
  function add(group) {
    const item = element('fieldset', { class: 'data-group' }, element('legend'),
      element('div', { class: 'pair' }, field('输入', 'group_input', group.input, { rows: 3 }, true),
        field('标准输出', 'group_output', group.output, { rows: 3 }, true)),
      element('div', { class: 'actions' }, field('分数', 'group_score', group.score, { type: 'number', min: 1, max: 10000, required: true }),
        button('移除', () => { item.remove(); order(); })));
    groupList.append(item);
    order();
  }
  data.groups.forEach(add);
  return [link('返回题库', '#problems', 'back'), heading(problem ? '编辑题目' : '新建题目', problem ? badge('v' + problem.version, 'neutral') : null),
    formOf([field('标题', 'title', data.title, { required: true, maxlength: 120 }),
      field('题面', 'statement', data.statement, { required: true, rows: 7, maxlength: 32768 }, true),
      element('div', { class: 'pair' }, field('样例输入', 'sample_input', data.sample_input, { rows: 3 }, true),
        field('样例输出', 'sample_output', data.sample_output, { rows: 3 }, true)),
      element('div', { class: 'pair' }, field('时限（ms）', 'time_ms', data.time_ms, { type: 'number', min: 50, max: 10000, required: true }),
        field('内存（MB）', 'memory_mb', data.memory_mb, { type: 'number', min: 16, max: 512, required: true })),
      element('h2', {}, '测试数据'), groupList, addGroup
    ], problem ? '保存新版本' : '创建题目', async values => {
      const payload = Object.fromEntries(['title', 'statement', 'sample_input', 'sample_output', 'time_ms', 'memory_mb'].map(key => [key, values.get(key)]));
      payload.time_ms = Number(payload.time_ms);
      payload.memory_mb = Number(payload.memory_mb);
      const outputs = values.getAll('group_output');
      const scores = values.getAll('group_score');
      payload.groups = values.getAll('group_input').map((input, index) => ({ input, output: outputs[index], score: Number(scores[index]) }));
      await api(problem ? '/problems/' + problem.id : '/problems', problem ? 'PUT' : 'POST', payload);
      goto('#problems');
    })];
}

function problemVersion(problem) {
  return [link('编辑当前版本', '#problems/' + problem.id, 'back'), heading(problem.title, badge('v' + problem.version, 'neutral')),
    element('p', { class: 'statement' }, problem.statement),
    element('div', { class: 'pair' }, element('section', {}, element('h3', {}, '样例输入'), pre(problem.sample_input)),
      element('section', {}, element('h3', {}, '样例输出'), pre(problem.sample_output))),
    element('p', { class: 'meta' }, `${problem.time_ms} ms　${problem.memory_mb} MB`),
    element('h2', {}, '测试数据'), problem.groups.map((group, index) => element('section', { class: 'data-group' },
      element('h3', {}, `数据组 ${index + 1} · ${group.score} 分`), element('div', { class: 'pair' },
        element('section', {}, element('h3', {}, '输入'), pre(group.input)),
        element('section', {}, element('h3', {}, '标准输出'), pre(group.output)))))];
}

function sheetEditor(sheet, problems) {
  const selected = (sheet?.problems || []).map(problem => problem.id);
  const ordered = element('ol', { class: 'ordered' });
  const picker = element('select', { 'aria-label': '选择题目' });
  const add = button('加入题目', () => {
    if (selected.length < 100 && picker.value) selected.push(Number(picker.value));
    show();
  });
  const notice = errorLine();
  function swap(index, shift) {
    [selected[index], selected[index + shift]] = [selected[index + shift], selected[index]];
    show();
  }
  function show() {
    const available = problems.filter(problem => !selected.includes(problem.id));
    picker.replaceChildren(element('option', { value: '' }, '选择题目'),
      ...available.map(problem => element('option', { value: problem.id }, problem.title)));
    add.disabled = selected.length >= 100 || !available.length;
    ordered.replaceChildren(...selected.map((id, index) => {
      const problem = problems.find(item => item.id === id);
      return element('li', {}, element('strong', {}, problem.title),
        element('div', { class: 'actions' },
          element('button', { type: 'button', class: 'button', onclick: () => swap(index, -1), disabled: index === 0,
            'aria-label': `上移 ${problem.title}` }, '上移'),
          element('button', { type: 'button', class: 'button', onclick: () => swap(index, 1), disabled: index === selected.length - 1,
            'aria-label': `下移 ${problem.title}` }, '下移'),
          button('移除', () => { selected.splice(index, 1); show(); })));
    }));
  }
  show();
  const openControl = sheet && !sheet.open ? button('开放题单', async event => {
    const control = event.currentTarget;
    control.disabled = true;
    try {
      await api(`/sheets/${sheet.id}/open`, 'POST');
      goto('#sheets');
    } catch (error) {
      feedback(notice, error.message);
    } finally {
      control.disabled = false;
    }
  }, 'button primary') : null;
  return [link('返回题单', '#sheets', 'back'), heading(sheet ? '编辑题单' : '新建题单', sheet ? sheetBadge(sheet) : null),
    element('div', { class: 'actions' }, openControl, notice),
    formOf([field('标题', 'title', sheet?.title || '', { required: true, maxlength: 120 }),
      element('h2', {}, '题目顺序'), ordered, element('div', { class: 'actions' }, picker, add),
      !sheet ? element('label', { class: 'check' }, element('input', { type: 'checkbox', name: 'open' }), '创建时开放') : null
    ], sheet ? '保存题单' : '创建题单', async values => {
      await api(sheet ? '/sheets/' + sheet.id : '/sheets', sheet ? 'PUT' : 'POST',
        { title: values.get('title'), problem_ids: selected, open: values.has('open') });
      goto('#sheets');
    })];
}

async function view(section, id, extra, current) {
  if (section === 'submissions') {
    if (id === 'before') return submissionList(await api('/submissions?before=' + extra), true);
    return id ? submissionDetail(await api('/submissions/' + id), current) : submissionList(await api('/submissions'));
  }
  if (section === 'sheets') {
    if (!id) return sheetList(await api('/sheets'));
    if (teacher) {
      const [sheet, problems] = await Promise.all([id === 'new' ? null : api('/sheets/' + id), api('/problems')]);
      return sheetEditor(sheet, problems);
    }
    return extra ? studentProblem(await api(`/sheets/${id}/problems/${extra}`), id, current) : studentSheet(await api('/sheets/' + id));
  }
  if (teacher && section === 'students') return roster(await api('/students'));
  if (teacher && section === 'problems') {
    if (!id) return teacherProblems(await api('/problems'));
    if (id === 'new') return problemEditor();
    const problem = await api('/problems/' + id + (extra ? '?version=' + extra : ''));
    return extra ? problemVersion(problem) : problemEditor(problem);
  }
  return [title('页面不存在'), link('返回题单', '#sheets', 'button')];
}

async function render() {
  const current = ++revision;
  const hash = location.hash.slice(1) || 'sheets';
  const [section, id, extra] = hash.split('/').map(part => encodeURIComponent(part));
  clearTimeout(timer);
  root.setAttribute('aria-busy', 'true');
  try {
    if (!teacher && !identity) {
      try {
        identity = await api('/me');
      } catch (error) {
        if (error.status !== 401) throw error;
      }
    }
    const loggedIn = teacher ? Boolean(adminToken) : Boolean(identity);
    if (current !== revision) return;
    chrome(section, loggedIn);
    const content = loggedIn ? await view(section, id, extra, current) : login();
    if (current === revision) root.replaceChildren(...[content].flat(Infinity).filter(Boolean));
  } catch (error) {
    if (current !== revision) return;
    if (error.status === (teacher ? 403 : 401)) {
      identity = null;
      adminToken = null;
      if (teacher) localStorage.removeItem(tokenKey);
      chrome(section, false);
      root.replaceChildren(login());
    } else {
      const notice = errorLine();
      feedback(notice, error.message);
      root.replaceChildren(notice, button('重试', () => void render()));
    }
  } finally {
    if (current === revision) root.setAttribute('aria-busy', 'false');
  }
}

window.addEventListener('hashchange', render);
void render();
