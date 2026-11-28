'use strict';

const teacher = location.pathname === '/oj/teacher';
const root = document.querySelector('#oj');
const nav = document.querySelector('#nav');
const account = document.querySelector('#account');
const tokenKey = 'pystream_admin_token';
const verdicts = {
  queued: '排队中', running: '评测中', finished: '已完成', executed: '运行完成', accepted: '通过', partial: '部分得分',
  compile_error: '编译错误', runtime_error: '运行错误', timeout: '超时', memory_limit: '超出内存限制',
  wrong_answer: '答案错误', output_limit: '输出超限', judge_error: '评测环境错误'
};
let identity;
let adminToken = teacher ? localStorage.getItem(tokenKey) : null;
let revision = 0;
const pollTokens = new WeakMap();

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
const draftKey = problemId => `oj-draft:${identity.id}:${problemId}`;
const submissionPath = (sheetId, problemId) => `/sheets/${sheetId}/problems/${problemId}/submissions`;

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
  const tabs = teacher ? [['题单', 'sheets'], ['题库', 'problems'], ['学员', 'students'], ['提交记录', 'submissions'], ['设置', 'settings']]
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
  return element('section', { class: 'catalog sheet-catalog' },
    heading('题单', teacher ? link('新建题单', '#sheets/new', 'button primary') : null),
    rows(sheets, sheet => element('a', { href: '#sheets/' + sheet.id, class: 'row-link sheet-tile' },
      element('strong', {}, sheet.title), sheetBadge(sheet)), '暂无题单'));
}

function showProblemProgress(node, problem) {
  const submission = problem.latest_submission;
  const score = submission ? `${submission.score ?? '—'} / ${submission.max_score} 分` : `满分 ${problem.max_score} 分`;
  node.replaceChildren(submission ? mark(submission) : badge('未提交', 'neutral'), element('span', {}, score));
}

function sheetProgress(sheet, current, className) {
  const nodes = new Map();
  const pending = new Map();
  const isPending = submission => ['queued', 'running'].includes(submission?.status);
  let watching = false;
  for (const problem of sheet.problems) {
    const node = element('span', { class: className, 'aria-live': 'polite' });
    showProblemProgress(node, problem);
    nodes.set(problem.id, node);
    if (isPending(problem.latest_submission)) pending.set(problem.id, problem.latest_submission);
  }

  async function refreshProgress() {
    if (current !== revision) return;
    const watched = new Map(pending);
    try {
      const updated = await api('/sheets/' + sheet.id);
      if (current !== revision) return;
      const problems = new Map(updated.problems.map(problem => [problem.id, problem]));
      for (const [id, previous] of watched) {
        if (pending.get(id) !== previous) continue;
        const problem = problems.get(id);
        const submission = problem?.latest_submission;
        if (problem && (submission?.status !== previous.status || !isPending(submission))) {
          showProblemProgress(nodes.get(id), problem);
        }
        if (isPending(submission)) pending.set(id, submission);
        else pending.delete(id);
      }
    } catch (error) {
      if ([401, 403, 404].includes(error.status)) {
        watching = false;
        return;
      }
    }
    watching = false;
    watch();
  }

  function watch() {
    if (watching || !pending.size || current !== revision) return;
    watching = true;
    setTimeout(refreshProgress, 1000);
  }
  watch();
  return nodes;
}

function studentSheet(sheet, current) {
  const nodes = sheetProgress(sheet, current, 'record-end');
  return [link('返回题单', '#sheets', 'back'), element('section', { class: 'catalog' },
    heading(sheet.title, sheetBadge(sheet)), rows(sheet.problems, (problem, index) =>
      element('a', { class: 'row-link problem-row', href: `#sheets/${sheet.id}/${problem.id}` },
        element('strong', {}, `${index + 1}. ${problem.title}`), nodes.get(problem.id)), '题单暂无题目'))];
}

function timeText(seconds) {
  return new Date(seconds * 1000).toLocaleString('zh-CN', { hour12: false });
}

function mark(record) {
  const key = record.verdict || record.status;
  const color = ['accepted', 'executed'].includes(key) ? 'green'
    : key === 'partial' ? 'yellow'
    : ['queued', 'running', 'finished'].includes(key) || !Object.hasOwn(verdicts, key) ? 'neutral' : 'red';
  return badge(verdicts[key] || '未知状态', color);
}

function sampleOutput(record, showOutputHeading = true) {
  return [record.detail ? pre(record.detail) : null,
    record.output !== undefined ? (showOutputHeading
      ? element('section', {}, element('h3', {}, '程序输出'), pre(record.output)) : pre(record.output)) : null].filter(Boolean);
}

function watchSubmission(id, current, { target, notice, update, pending, refreshButton }) {
  const token = {};
  pollTokens.set(target, token);
  const active = () => current === revision && pollTokens.get(target) === token;
  let timer;
  let loading = false;
  async function refresh() {
    if (!active() || loading) return;
    clearTimeout(timer);
    loading = true;
    if (refreshButton) refreshButton.disabled = true;
    try {
      const record = await api('/submissions/' + id);
      if (!active()) return;
      feedback(notice, '');
      update(record);
      pending = record.status !== 'finished';
    } catch (error) {
      if (!active()) return;
      feedback(notice, error.message);
      if ([401, 403, 404].includes(error.status)) pending = false;
    } finally {
      loading = false;
      if (refreshButton) refreshButton.disabled = false;
      if (active() && pending) timer = setTimeout(refresh, 750);
    }
  }
  if (pending) timer = setTimeout(refresh, 750);
  return refresh;
}

function sheetContext(sheet, problem, progress) {
  const problemLinks = sheet.problems.map((item, index) => {
    const attributes = { href: `#sheets/${sheet.id}/${item.id}`, 'aria-current': item.id === problem.id ? 'page' : undefined };
    return element('li', {}, element('a', attributes,
      element('span', { class: 'problem-number' }, `T${index + 1}`),
      element('span', {}, item.title, progress.get(item.id))));
  });
  return element('aside', { class: 'sheet-context', 'aria-labelledby': 'sheet-context-title' },
    element('h2', { id: 'sheet-context-title', class: 'panel-title' }, '题单信息'),
    element('div', { class: 'sheet-context-body' },
      element('div', { class: 'sheet-context-heading' },
        link(sheet.title, `#sheets/${sheet.id}`, 'sheet-context-link'), sheetBadge(problem)),
      element('h3', {}, '题目列表'), element('ol', { class: 'sheet-problems' }, problemLinks)));
}

function statementParagraph(text) {
  const paragraph = element('p', { class: 'statement' }, text);
  window.renderMathInElement?.(paragraph, {
    delimiters: [
      { left: '$$', right: '$$', display: true },
      { left: '$', right: '$', display: false },
    ],
    output: 'mathml',
    trust: false,
    maxSize: 20,
    preProcess: math => math.replaceAll('<=', '≤').replaceAll('>=', '≥'),
    // The renderer leaves malformed formulas as their original text.
    errorCallback: () => {},
  });
  return paragraph;
}

function problemPaper(problem, className) {
  const samples = problem.sample_cases || [{ input: problem.sample_input, output: problem.sample_output }];
  const sections = [['输入格式', problem.input_format], ['输出格式', problem.output_format],
    ['数据范围与约定', problem.constraints]].filter(([, text]) => text);
  const samplePairs = samples.map((sample, index) => {
    const suffix = samples.length > 1 ? ' ' + (index + 1) : '';
    return element('div', { class: 'samples problem-samples' },
      element('section', {}, element('h3', {}, '样例输入' + suffix), pre(sample.input)),
      element('section', {}, element('h3', {}, '样例输出' + suffix), pre(sample.output)));
  });
  return element('article', { class: className },
    element('header', { class: 'problem-intro' }, title(problem.title),
      element('p', { class: 'meta' }, `时限 ${problem.time_ms} ms　内存 ${problem.memory_mb} MB　满分 ${problem.max_score}`),
      problem.tags?.length ? element('p', { class: 'meta' }, problem.tags.join(' · ')) : null),
    element('h2', {}, '题目描述'), statementParagraph(problem.statement),
    sections.flatMap(([heading, text]) => [element('h2', {}, heading), statementParagraph(text)]),
    samplePairs);
}

function studentProblem(problem, sheet, current) {
  const progress = sheetProgress(sheet, current, 'sheet-problem-progress');
  return [link('返回题单', `#sheets/${sheet.id}`, 'back mobile-sheet-back'),
    element('div', { class: 'problem-layout' },
      element('div', { class: 'problem-main' }, problemPaper(problem, 'paper problem-paper'),
        problem.open ? submissionPanel(problem, sheet.id, current) : null),
      sheetContext(sheet, problem, progress))];
}

const cppTypes = new Set('auto bool char char16_t char32_t double float int long short signed unsigned void wchar_t'.split(' '));
const cppKeywords = new Set([
  'alignas alignof and and_eq asm bitand bitor break case catch class compl const constexpr const_cast continue',
  'decltype default delete do dynamic_cast else enum explicit export extern false for friend goto if inline mutable',
  'namespace new noexcept not not_eq nullptr operator or or_eq private protected public register reinterpret_cast',
  'return sizeof static static_assert static_cast struct switch template this thread_local throw true try typedef',
  'typeid typename union using virtual volatile while xor xor_eq'
].join(' ').split(' '));
const cppTokens = new RegExp([
  String.raw`(?<directive>^[\t ]*#[\t ]*(?:include\b[\t ]+<[^>\n]*>|[A-Za-z_]\w*))`,
  String.raw`(?<comment>//(?:\\\n|[^\n])*|/\*[\s\S]*?(?:\*/|(?![\s\S])))`,
  String.raw`(?<string>(?:u8|u|U|L)?R"(?<delimiter>[^\s()\\]{0,16})\([\s\S]*?(?:\)\k<delimiter>"|(?![\s\S]))` +
  String.raw`|(?:u8|u|U|L)?(?:"(?:\\[\s\S]|[^"\\\n])*"?|'(?:\\[\s\S]|[^'\\\n])*'?))`,
  String.raw`(?<number>(?:[0-9]|\.[0-9])(?:[eEpP][+-]|'\p{ID_Continue}|[.\p{ID_Continue}])*)`,
  String.raw`(?<word>[_\p{ID_Start}]\p{ID_Continue}*)`
].join('|'), 'gmu');

function highlightCpp(source) {
  const fragment = document.createDocumentFragment();
  let offset = 0;
  for (const { 0: text, index, groups } of source.matchAll(cppTokens)) {
    const kind = groups.directive ? 'directive' : groups.comment ? 'comment' : groups.string ? 'string' :
      groups.number ? 'number' : cppTypes.has(text) ? 'type' : cppKeywords.has(text) ? 'keyword' : null;
    if (!kind) continue;
    if (index > offset) fragment.append(source.slice(offset, index));
    fragment.append(element('span', { class: 'syntax-' + kind }, text));
    offset = index + text.length;
  }
  fragment.append(source.slice(offset));
  if (source.endsWith('\n')) fragment.append('\u200b');
  return fragment;
}

function sourceEditor(id, value, onEdit, { lineNumbers: numbered = false, autofocus = false, readOnly = false } = {}) {
  const input = element('textarea', { id, class: 'editor', maxlength: 65536, spellcheck: 'false',
    autocapitalize: 'off', autocomplete: 'off', wrap: numbered ? 'off' : 'soft', readonly: readOnly,
    'aria-label': autofocus ? 'C++17 源码' : undefined, autofocus });
  const syntax = element('div', { class: 'editor-syntax', 'aria-hidden': 'true', tabindex: '-1' });
  const surface = element('div', { class: 'editor-surface' }, syntax, input);
  const lineNumbers = numbered ? element('pre', { class: 'editor-line-numbers', 'aria-hidden': 'true' }) : null;

  function syncScroll() {
    syntax.scrollTop = input.scrollTop;
    syntax.scrollLeft = input.scrollLeft;
    if (lineNumbers) lineNumbers.scrollTop = input.scrollTop;
  }
  function paint() {
    syntax.replaceChildren(highlightCpp(input.value));
    if (lineNumbers) {
      const count = 1 + (input.value.match(/\n/g)?.length || 0);
      lineNumbers.textContent = Array.from({ length: count }, (_, index) => index + 1).join('\n');
    }
    syncScroll();
  }
  function setValue(source) {
    input.value = source;
    paint();
  }
  input.addEventListener('input', () => {
    paint();
    onEdit(input.value);
  });
  input.addEventListener('scroll', syncScroll);
  setValue(value);
  const node = numbered ? element('div', { class: 'numbered-editor' }, lineNumbers, surface) : surface;
  return { input, node, setValue };
}

function evaluationArea(editor, showOutputHeading = true) {
  const notice = errorLine();
  const updates = element('div', { class: 'judge-result', 'aria-live': 'polite' });
  const reloadButton = button('刷新题面', () => void render());
  reloadButton.hidden = true;
  return { editor, notice, updates, reloadButton, showOutputHeading, pending: false };
}

function debugDialog(problem, area, run, submit) {
  const input = element('textarea', { id: 'debug-input', maxlength: 65536, spellcheck: 'false' });
  const inputLabel = element('label', { for: input.id, class: 'debug-pane-title' });
  const expected = pre(problem.sample_output);
  const sampleButton = button('题目样例', () => showInput(true));
  const customButton = button('自定义输入', () => { showInput(false); input.focus(); });
  let customInput = '';
  function showInput(sample) {
    sampleButton.setAttribute('aria-pressed', sample);
    customButton.setAttribute('aria-pressed', !sample);
    inputLabel.textContent = sample ? '样例输入' : '自定义输入';
    input.readOnly = sample;
    input.value = sample ? problem.sample_input : customInput;
    expected.hidden = !sample;
  }
  input.addEventListener('input', () => { customInput = input.value; });
  showInput(true);

  const data = element('div', { class: 'debug-data' },
    element('section', { class: 'debug-pane' }, inputLabel, input),
    element('section', { class: 'debug-pane' }, element('h3', { class: 'debug-pane-title' }, '预期输出'), expected),
    element('section', { class: 'debug-pane' }, element('h3', { class: 'debug-pane-title' }, '代码运行结果'),
      element('div', { class: 'debug-result' }, area.notice, area.updates)));
  const toolbar = element('footer', { class: 'debug-toolbar' },
    element('div', { class: 'debug-actions', role: 'group', 'aria-label': '输入方式' }, sampleButton, customButton),
    element('div', { class: 'debug-actions' }, area.reloadButton, element('span', { class: 'debug-language' }, 'C++17'),
      button('在线运行', event => run(event, input.readOnly ? null : input.value), 'button debug-run'),
      button('提交评测', submit)));
  const dialog = element('dialog', { class: 'debug-dialog', 'aria-label': '在线调试' },
    element('header', { class: 'debug-header' }, element('span', { class: 'debug-brand' }, '课堂 OJ'),
      element('h2', { class: 'debug-title' }, problem.title), button('返回题目详情', () => dialog.close())),
    element('div', { class: 'debug-body' },
      element('section', { class: 'debug-statement', tabindex: '0', 'aria-label': '题面' }, problemPaper(problem, 'debug-paper')),
      element('section', { class: 'debug-workspace', 'aria-label': '代码工作区' },
        area.editor.node, data, toolbar)));
  return dialog;
}

function submissionPanel(problem, sheetId, current) {
  const draft = draftKey(problem.id);
  const initialSource = sessionStorage.getItem(draft) || '';
  function saveDraft(source, otherEditor) {
    otherEditor.setValue(source);
    sessionStorage.setItem(draft, source);
  }
  const main = evaluationArea(sourceEditor('source', initialSource, source => saveDraft(source, debug.editor)));
  const debugEditor = sourceEditor('debug-source', initialSource, source => saveDraft(source, main.editor),
    { lineNumbers: true, autofocus: true });
  debugEditor.node.classList.add('debug-source');
  const debug = evaluationArea(debugEditor, false);

  async function send(kind, area, control, customInput = null) {
    if (area.pending) return;
    if (!area.editor.input.value.trim()) {
      feedback(area.notice, '请输入 C++17 源码');
      area.editor.input.focus();
      return;
    }
    area.pending = control.disabled = true;
    feedback(area.notice, '');
    try {
      const payload = { kind, source: area.editor.input.value, version: problem.version };
      if (customInput !== null) payload.custom_input = customInput;
      const submission = await api(submissionPath(sheetId, problem.id), 'POST', payload);
      if (current !== revision) return;
      if (kind === 'judge') {
        if (dialog.open) dialog.close();
        goto('#submissions/' + submission.id);
        return;
      }
      area.updates.replaceChildren(mark(submission), link('查看提交', '#submissions/' + submission.id));
      watchSubmission(submission.id, current, { target: area.updates, notice: area.notice, pending: true,
        update: record => area.updates.replaceChildren(mark(record), ...sampleOutput(record, area.showOutputHeading)) });
    } catch (error) {
      area.reloadButton.hidden = error.code !== 'problem_version_changed';
      feedback(area.notice, error.message);
    } finally {
      area.pending = control.disabled = false;
    }
  }
  const dialog = debugDialog(problem, debug, (event, input) => send('sample', debug, event.currentTarget, input),
    event => send('judge', debug, event.currentTarget));
  return element('section', { class: 'submission-panel', 'aria-labelledby': 'submission-panel-title' },
    element('h2', { id: 'submission-panel-title', class: 'panel-title' }, '代码提交区域'),
    element('div', { class: 'code-panel' }, element('label', { for: 'source', class: 'code-label' }, 'C++17 源码'), main.editor.node,
      element('div', { class: 'actions' }, button('提交评测', event => send('judge', main, event.currentTarget), 'button primary'),
        button('进入在线调试', () => dialog.showModal()),
        button('测试样例', event => send('sample', main, event.currentTarget)), main.reloadButton), main.notice, main.updates), dialog);
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

function detailPanel(name, ...content) {
  return element('section', { class: 'detail-panel' }, element('h2', { class: 'panel-title' }, name),
    element('div', { class: 'detail-body' }, ...content));
}

function detailFields(fields) {
  return element('dl', {}, fields.map(([name, value]) =>
    element('div', {}, element('dt', {}, name), element('dd', {}, value))));
}

function usageText(value, format) {
  return value == null ? '—' : format(value);
}

const milliseconds = value => `${value} ms`;
const kibibytes = value => `${(value / 1024).toLocaleString('zh-CN', { maximumFractionDigits: 1 })} KiB`;

function maxUsage(record, key) {
  const values = (record.cases || []).map(test => test[key]).filter(Number.isFinite);
  return values.length ? Math.max(...values) : null;
}

function judgeCases(record, expanded) {
  if (record.status !== 'finished') return element('p', { class: 'meta' }, '评测结束后显示测试点结果。');
  if (!record.cases?.length) return record.detail ? pre(record.detail) : element('p', { class: 'meta' }, '没有测试点结果。');
  const mode = { sum: '独立计分', max: '取最高分' }[record.scoring];
  return element('details', { class: 'judge-cases', open: expanded },
    element('summary', {}, '默认分组', mode ? element('span', { class: 'case-mode' }, mode) : null,
      element('span', {}, `${record.score} / ${record.max_score}`)),
    element('ol', { class: 'case-grid' }, record.cases.map((test, index) =>
      element('li', { class: 'case-card' }, element('span', { class: 'case-number' }, `#${index + 1}`),
        element('div', { class: 'case-outcome' }, mark(test),
          element('strong', {}, `${test.verdict === 'accepted' ? test.points : 0} / ${test.points} 分`)),
        test.time_ms != null || test.memory_bytes != null ? element('p', { class: 'meta' },
          `${usageText(test.time_ms, milliseconds)} · ${usageText(test.memory_bytes, kibibytes)}`) : null))));
}

function submissionCode(record, problemHref, current) {
  const original = record.source.replace(/\r\n?/g, '\n');
  const notice = errorLine();
  const send = button('再次提交', resubmit, 'button primary');
  const latestProblem = link('打开最新题面', problemHref, 'button');
  latestProblem.hidden = true;
  latestProblem.addEventListener('click', () => sessionStorage.setItem(draftKey(record.problem_id), editor.input.value));
  let editable = false;
  const editor = sourceEditor('submitted-source', original, syncAction, { lineNumbers: true, readOnly: true });

  function syncAction() {
    send.hidden = !editable || editor.input.value === original;
    send.disabled = !editor.input.value.trim() || !latestProblem.hidden;
    feedback(notice, '');
  }

  async function resubmit() {
    if (send.disabled || send.hidden) return;
    const source = editor.input.value;
    send.disabled = editor.input.readOnly = true;
    feedback(notice, '');
    try {
      const retry = await api(submissionPath(record.sheet_id, record.problem_id), 'POST',
        { kind: 'judge', source, version: record.version });
      if (current === revision) {
        sessionStorage.setItem(draftKey(record.problem_id), source);
        goto('#submissions/' + retry.id);
      }
    } catch (error) {
      if (current !== revision) return;
      latestProblem.hidden = error.code !== 'problem_version_changed';
      editor.input.readOnly = !editable;
      send.disabled = !latestProblem.hidden;
      feedback(notice, error.message);
    }
  }

  return {
    node: detailPanel('代码', element('label', { for: editor.input.id, class: 'code-label' }, 'C++17 源码'),
      editor.node, element('div', { class: 'detail-code-actions' }, send, latestProblem, notice)),
    update(record) {
      const allowed = !teacher && Boolean(record.can_resubmit);
      if (allowed === editable) return;
      editable = allowed;
      editor.input.readOnly = !allowed;
      syncAction();
    }
  };
}

function submissionDetail(record, current) {
  const judge = record.kind === 'judge';
  const problemHref = `#sheets/${record.sheet_id}/${record.problem_id}`;
  const problemTitle = !teacher && record.problem_in_sheet ? link(record.title, problemHref) : record.title;
  const versionLabel = `题目版本 v${record.version}`;
  const problemVersion = teacher ? link(versionLabel, `#problems/${record.problem_id}/${record.version}`) : versionLabel;
  const notice = errorLine();
  const refreshButton = button('刷新', () => void refresh());
  const overview = element('div', { class: 'detail-overview', 'aria-live': 'polite' });
  const preliminary = element('p', { class: 'preliminary-result' });
  const finalResults = element('div', { class: 'detail-results' });
  const code = submissionCode(record, problemHref, current);

  function update(record) {
    overview.replaceChildren(detailFields([
      ['提交编号', `#${record.id}`], ['提交人', record.username],
      ['题目', element('span', { class: 'detail-problem' }, problemTitle, element('small', { class: 'meta' }, problemVersion))],
      ['提交时间', timeText(record.created_at)]
    ]), detailFields(judge ? [
      ['最终结果', mark(record)], ['最终得分', `${record.score ?? '—'} / ${record.max_score} 分`],
      ['最大运行耗时', usageText(maxUsage(record, 'time_ms'), milliseconds)],
      ['最大内存占用', usageText(maxUsage(record, 'memory_bytes'), kibibytes)]
    ] : [['运行结果', mark(record)]]));
    if (judge) {
      let sample = record.status === 'finished' ? '无初测记录' : '等待评测';
      if (record.sample_verdict) sample = record.sample_verdict === 'accepted' ? '全部通过' : verdicts[record.sample_verdict];
      preliminary.textContent = `初测结论：${sample}`;
      const group = finalResults.querySelector('details');
      finalResults.replaceChildren(judgeCases(record, group?.open ?? true));
    } else {
      finalResults.replaceChildren(...sampleOutput(record));
    }
    code.update(record);
  }

  update(record);
  const refresh = watchSubmission(record.id, current,
    { target: overview, notice, update, pending: record.status !== 'finished', refreshButton });
  const samples = judge ? null : element('div', { class: 'samples detail-samples' },
    element('section', {}, element('h3', {}, record.custom_input !== null ? '自定义输入' : '样例输入'), pre(record.test_input)),
    record.expected_output !== null
      ? element('section', {}, element('h3', {}, '预期输出'), pre(record.expected_output)) : null);
  return element('article', { class: 'submission-detail' },
    element('section', { class: 'detail-panel' },
      element('header', { class: 'panel-title detail-heading' }, title('提交记录详情'),
        link('返回提交记录', '#submissions'), refreshButton),
      element('div', { class: 'detail-body' }, overview, notice)),
    judge ? detailPanel('初步测试详情', preliminary) : null,
    detailPanel(judge ? '最终结果详情' : '运行详情', samples, finalResults), code.node);
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

function settings(data) {
  const notice = errorLine();
  return [title('设置'), formOf([
    field('学员默认密码', 'password', data.default_password, { required: true, maxlength: 128, autocomplete: 'new-password' })
  ], '保存默认密码', async (values, form) => {
    const result = await api('/settings/default-password', 'PUT', Object.fromEntries(values));
    feedback(notice, '默认密码已更新。新建学员或重置密码时生效。', true);
    const input = form.elements.password;
    if (input) input.value = result.default_password;
  }), notice];
}

async function loadTeacherProblems() {
  const report = await api('/problems/sync', 'POST');
  return teacherProblems(await api('/problems'), report);
}

function teacherProblems(problems, report) {
  const notice = errorLine();
  const syncControl = button('重新同步', async event => {
    const control = event.currentTarget;
    control.disabled = true;
    try {
      catalog.replaceWith(await loadTeacherProblems());
    } catch (error) {
      feedback(notice, error.message);
    } finally {
      control.disabled = false;
    }
  });
  if (report.warning) feedback(notice, report.warning);
  else if (report.configured) {
    feedback(notice, `备课同步完成。新增 ${report.added} 道，更新 ${report.updated} 道，已有 ${report.unchanged} 道。`, true);
  } else feedback(notice, '可在教师机配置备课目录后同步自编题。');
  const catalog = element('section', { class: 'catalog' },
    heading('题库', element('div', { class: 'actions' }, syncControl, link('新建题目', '#problems/new', 'button primary'))),
    notice, report.issues.length ? element('ul', {}, report.issues.map(issue =>
      element('li', {}, `${issue.file} · ${issue.reason}`))) : null,
    rows(problems, problem => element('a', { class: 'row-link problem-row', href: '#problems/' + problem.id },
      element('strong', {}, problem.title), element('span', { class: 'meta' },
        [`v${problem.version}`, `${problem.max_score} 分`, ...(problem.tags || []),
          problem.available === false ? '暂不可布置' : ''].filter(Boolean).join(' · '))), '暂无题目'));
  return catalog;
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
    element('article', { class: 'paper' },
      element('p', { class: 'meta' }, `时限 ${problem.time_ms} ms　内存 ${problem.memory_mb} MB`),
      statementParagraph(problem.statement),
      element('div', { class: 'samples' }, element('section', {}, element('h3', {}, '样例输入'), pre(problem.sample_input)),
        element('section', {}, element('h3', {}, '样例输出'), pre(problem.sample_output)))),
    element('h2', {}, '测试数据'), problem.groups.map((group, index) => element('section', { class: 'data-group' },
      element('h3', {}, `数据组 ${index + 1} · ${group.score} 分`), element('div', { class: 'pair' },
        element('section', {}, element('h3', {}, '输入'), pre(group.input)),
        element('section', {}, element('h3', {}, '标准输出'), pre(group.output)))))];
}

function sheetEditor(sheet, problems) {
  const selected = (sheet?.problems || []).map(problem => problem.id);
  const ordered = element('ol', { class: 'ordered' });
  const picker = element('select', { 'aria-label': '选择题目' });
  const tags = [...new Set(problems.filter(problem => problem.available !== false).flatMap(problem => problem.tags || []))];
  const filters = tags.map(tag => {
    const control = element('input', { type: 'checkbox', onchange: show });
    return { tag, control };
  });
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
    const active = filters.filter(({ control }) => control.checked);
    const available = problems.filter(problem => problem.available !== false && !selected.includes(problem.id)
      && active.every(({ tag }) => problem.tags?.includes(tag)));
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
      element('h2', {}, '题目顺序'), ordered,
      filters.length ? element('div', { class: 'actions', 'aria-label': '按标签筛选候选题' },
        filters.map(({ tag, control }) => element('label', { class: 'check' }, control, tag))) : null,
      element('div', { class: 'actions' }, picker, add),
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
    if (!extra) return studentSheet(await api('/sheets/' + id), current);
    const [problem, sheet] = await Promise.all([api(`/sheets/${id}/problems/${extra}`), api(`/sheets/${id}`)]);
    return studentProblem(problem, sheet, current);
  }
  if (teacher && section === 'students') return roster(await api('/students'));
  if (teacher && section === 'settings') return settings(await api('/settings'));
  if (teacher && section === 'problems') {
    if (!id) return loadTeacherProblems();
    if (id === 'new') return problemEditor();
    const problem = await api('/problems/' + id + (extra ? '?version=' + extra : ''));
    if (problem.sample_cases) return [link('返回题库', '#problems', 'back'), problemPaper(problem, 'paper')];
    return extra ? problemVersion(problem) : problemEditor(problem);
  }
  return [title('页面不存在'), link('返回题单', '#sheets', 'button')];
}

async function render() {
  const current = ++revision;
  const hash = location.hash.slice(1) || 'sheets';
  const [section, id, extra] = hash.split('/').map(part => encodeURIComponent(part));
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

window.addEventListener('hashchange', () => {
  window.scrollTo(0, 0);
  void render();
});
void render();
