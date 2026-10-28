"""Small, in-memory adapter for the unmodified Classtream 1.0.1 package."""
import json
import ipaddress
import os
import re
from contextlib import asynccontextmanager
from importlib.metadata import version
from pathlib import Path
from urllib.parse import parse_qs


class LocalAdministration:
    """HTTP students may view, but administrator credentials stay on loopback."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] in ('http', 'websocket'):
            address = (scope.get('client') or ('', 0))[0]
            try:
                local = ipaddress.ip_address(address).is_loopback
            except ValueError:
                local = False
            query = parse_qs(scope.get('query_string', b'').decode('utf-8', 'replace'))
            path = scope.get('path', '')
            headers = dict(scope.get('headers', []))
            admin_request = (
                'host' in query or 'admin_token' in query or b'x-admin-token' in headers
                or path.startswith(('/api/admin/', '/api/session/', '/api/screen/'))
                or path == '/api/settings')
            if admin_request and not local:
                if scope['type'] == 'websocket':
                    await send({'type': 'websocket.close', 'code': 1008})
                else:
                    from fastapi.responses import JSONResponse
                    response = JSONResponse({'detail': 'Open the teacher page on this PC using 127.0.0.1.'}, status_code=403)
                    await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


def replace_once(source, old, new, label):
    if source.count(old) != 1:
        raise RuntimeError(f"Unsupported Classtream source: {label}. Expected 1.0.1.")
    return source.replace(old, new, 1)


def create_application(public_url, fps=30, teacher_url=None):
    if version("classtream") != "1.0.1":
        raise RuntimeError("This adapter requires classtream==1.0.1; see requirements.txt.")

    from fastapi import FastAPI, Request
    from fastapi.responses import HTMLResponse, Response
    from app import database, state
    from app.main import app as original
    from app import main as original_module
    from fast_capture import capture_loop, CAPTURE_TASKS
    from stream_transport import StreamManager
    from teacher_hotkeys import TeacherShortcuts
    # Test and production data roots stay isolated; this file contains no auth tokens.
    data_root = Path(os.environ.get('CLASSTREAM_DATA', str(Path(__file__).parent / 'runtime' / 'data')))
    shortcuts = TeacherShortcuts(data_root.parent / 'teacher-shortcuts.json'
                                if data_root.name == 'data' else data_root / 'teacher-shortcuts.json')
    if not isinstance(state.manager, StreamManager):
        if state.manager.connections:
            raise RuntimeError('Stop the classroom before installing stream transport.')
        state.manager = StreamManager()
    original_module.capture_loop = capture_loop
    from app.paths import STATIC_DIR, TEMPLATES_DIR
    state.settings.fps = fps

    @asynccontextmanager
    async def lifespan(_):
        async with original.router.lifespan_context(original):
            print(f"\nTeacher: {teacher_url or public_url + '/?host=admin'}")
            print(f"Student: {public_url}/class\n", flush=True)
            try:
                yield
            finally:
                import asyncio
                await shortcuts.shutdown()
                tasks = list(CAPTURE_TASKS)
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                await state.manager.shutdown()

    application = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None,
                          openapi_url=None)
    application.state.teacher_shortcuts = shortcuts
    http_mode = public_url.startswith('http:')
    if http_mode:
        application.add_middleware(LocalAdministration)
    no_cache = {"Cache-Control": "no-store"}

    def local_teacher(request):
        address = request.client.host if request.client else ''
        try:
            local = ipaddress.ip_address(address).is_loopback
        except ValueError:
            local = False
        token = request.headers.get('x-admin-token', '')
        return token if local and token in state.admin_tokens else None

    @application.get('/api/teacher-shortcuts')
    async def shortcut_status(request: Request):
        from fastapi.responses import JSONResponse
        token = local_teacher(request)
        if not token:
            return JSONResponse({'ok': False}, status_code=403, headers=no_cache)
        return JSONResponse({'ok': True, 'ready': shortcuts.online(token), **shortcuts.status()}, headers=no_cache)

    @application.post('/api/teacher-shortcuts')
    async def configure_shortcuts(request: Request):
        from fastapi.responses import JSONResponse
        token = local_teacher(request)
        if not token:
            return JSONResponse({'ok': False}, status_code=403)
        try:
            data = await request.json()
            if not isinstance(data, dict) or type(data.get('enabled')) is not bool:
                raise ValueError('启用状态必须为布尔值')
            bindings = data.get('bindings')
            if bindings is not None and (not isinstance(bindings, dict)
                    or not all(isinstance(v, str) for v in bindings.values())):
                raise ValueError('快捷键格式不正确')
            result = await shortcuts.configure(token, data['enabled'], bindings)
            return JSONResponse({'ok': not bool(result['error']), **result}, headers=no_cache)
        except ValueError as exc:
            return JSONResponse({'ok': False, 'error': str(exc)}, status_code=400)
        except (TypeError, AttributeError):
            return JSONResponse({'ok': False, 'error': '快捷键格式不正确'}, status_code=400)
        except OSError:
            return JSONResponse({'ok': False, 'error': '无法保存本机快捷键配置，请检查目录写入权限'}, status_code=500)

    # Freeze delivery without closing student sockets or changing screen permissions.
    @application.post('/api/screen/freeze')
    async def change_shared_freeze(request: Request):
        from fastapi.responses import JSONResponse
        token = request.headers.get('x-admin-token', '')
        if token not in state.admin_tokens:
            return JSONResponse({'ok': False}, status_code=401)
        try:
            data = await request.json()
            if not isinstance(data, dict) or type(data.get('enabled')) is not bool:
                raise ValueError('状态必须为布尔值')
            return JSONResponse(await shortcuts.set_frozen(token, data['enabled']))
        except (ValueError, TypeError):
            return JSONResponse({'ok': False}, status_code=400)
        except PermissionError:
            return JSONResponse({'ok': False}, status_code=401)
    # Retain the original screen privacy API independently of freezing.
    @application.post('/api/screen/private')
    async def change_shared_visibility(request: Request):
        from fastapi.responses import JSONResponse
        token = request.headers.get('x-admin-token', '')
        if token not in state.admin_tokens:
            return JSONResponse({'ok': False}, status_code=401)
        try:
            data = await request.json()
            if not isinstance(data, dict) or type(data.get('enabled')) is not bool:
                raise ValueError('状态必须为布尔值')
            return JSONResponse(await shortcuts.set_private(token, data['enabled']))
        except (ValueError, TypeError):
            return JSONResponse({'ok': False}, status_code=400)
        except PermissionError:
            return JSONResponse({'ok': False}, status_code=401)
    def current_public_url():
        if not http_mode:
            return public_url
        try:
            cfg = json.loads((Path(__file__).parent / 'config.json').read_text('utf-8-sig'))
            return f"http://{ipaddress.IPv4Address(cfg['teacher_ip'])}:{int(cfg['http_port'])}"
        except (OSError, ValueError, KeyError):
            return public_url

    @application.get('/lan-info')
    async def lan_info():
        from fastapi.responses import JSONResponse
        return JSONResponse({'student_url': current_public_url() + '/class'}, headers=no_cache)
    scripts = {}
    for name in ("config", "stream", "voice", "main", "sidebar", "chat", "controls", "auth", "viewers"):
        scripts[name + ".js"] = (STATIC_DIR / "js" / (name + ".js")).read_text("utf-8")
    # Students register immediately; only the server chooses their classroom name.
    scripts['auth.js'] = re.sub(
        r'/\*\* Show name modal.*?(?=// ── Full-page overlays)', '', scripts['auth.js'], flags=re.S)
    scripts['auth.js'] = scripts['auth.js'].replace("import { reRegisterAll }           from './stream.js';", '')
    scripts['auth.js'] = replace_once(scripts['auth.js'],
        'export async function initStudentFlow() {',
        "export async function initStudentFlow() {\n  state.myName = '';", 'clear legacy student name')
    scripts['main.js'] = replace_once(scripts['main.js'],
        'showNoSessionOverlay, showNameModal, submitName, submitAdminLogin,',
        'showNoSessionOverlay, submitAdminLogin,', 'student auth imports')
    scripts['main.js'] = replace_once(scripts['main.js'],
        "    if (state.myName) {\n      reRegisterAll();          // name already known → register immediately\n"
        "    } else {\n      showNameModal();          // first visit → ask for name\n    }",
        '    reRegisterAll();', 'automatic student registration')
    scripts['main.js'] = replace_once(scripts['main.js'],
        "  _on('name-submit-btn',    () => submitName());", '', 'remove name submit')
    scripts['stream.js'] = replace_once(scripts['stream.js'],
        'if (!ws || ws.readyState !== WebSocket.OPEN || !state.myName) return;',
        'if (!ws || ws.readyState !== WebSocket.OPEN) return;', 'nameless student registration')
    scripts['viewers.js'] = replace_once(scripts['viewers.js'],
        '  switch (data.type) {',
        "  switch (data.type) {\n    case 'identity':\n"
        "      if (state.myRole !== 'host') {\n        state.myName = data.name;\n"
        "        document.dispatchEvent(new Event('classtream:name-changed'));\n      }\n      return;",
        'server assigned identity')
    scripts['stream-client.js'] = (Path(__file__).parent / 'stream-client.js').read_text('utf-8')
    scripts['stream.js'] = "import { createFrameReceiver } from './stream-client.js';\n" + scripts['stream.js']
    scripts['stream.js'] = replace_once(scripts['stream.js'],
        'new URLSearchParams({ session_id: SESSION_ID })',
        "new URLSearchParams({ session_id: SESSION_ID, stream: '2' })", 'stream negotiation')
    scripts['stream.js'] = replace_once(scripts['stream.js'],
        "  const img = document.getElementById('screen-img');",
        "  const img = document.getElementById('screen-img');\n"
        "  const receiveFrame = createFrameReceiver(ws, img, _hideSinglePrivate);", 'single receiver')
    scripts['stream.js'] = replace_once(scripts['stream.js'],
        "    if (state.paused) return;\n    // Live frame arrived — hide private overlay if it was showing\n"
        "    _hideSinglePrivate();\n    const url = URL.createObjectURL(e.data);\n"
        "    const old = img.src;\n    img.src = url;\n"
        "    if (old && old.startsWith('blob:')) URL.revokeObjectURL(old);",
        '    receiveFrame(e.data);', 'single frame rendering')
    # Both original grid and reconnect paths use the same receiver.
    if scripts['stream.js'].count('let prev = null;') != 2:
        raise RuntimeError('Unsupported grid stream source.')
    scripts['stream.js'] = scripts['stream.js'].replace('let prev = null;',
        'const receiveFrame = createFrameReceiver(ws, gimg, () => _hideCellPrivate(cell, gimg));')
    for indent in ('      ', '    '):
        scripts['stream.js'] = replace_once(scripts['stream.js'],
            indent + 'if (state.paused) return;\n' + indent + '_hideCellPrivate(cell, gimg);\n' +
            indent + 'const url = URL.createObjectURL(e.data); gimg.src = url;\n' +
            indent + 'if (prev) URL.revokeObjectURL(prev); prev = url;',
            indent + 'receiveFrame(e.data);', 'grid frame rendering ' + str(len(indent)))
    scripts['stream.js'] = replace_once(scripts['stream.js'],
        "document.createElement('img')", "document.createElement('canvas')", 'grid canvas')
    # Globally hidden students retry through the normal authenticated permission path.
    # Restoring sharing therefore resumes permitted students without manual refresh.
    scripts['stream.js'] = """function retryGlobalPrivacy(data, ws, reconnect) {
  if (!['global', 'global_private'].includes(data.reason)) return;
  setTimeout(() => { if (Object.values(state.wsMap).includes(ws)) reconnect(); }, 2000);
}
""" + scripts['stream.js']
    scripts['stream.js'] = replace_once(scripts['stream.js'],
        '        _showSinglePrivate(() => { _hideSinglePrivate(); _connectSingle(id); });',
        '        retryGlobalPrivacy(data, ws, () => _connectSingle(id));\n'
        '        _showSinglePrivate(() => { _hideSinglePrivate(); _connectSingle(id); });', 'global single resume')
    scripts['stream.js'] = replace_once(scripts['stream.js'],
        '          _showCellPrivate(cell, gimg, () =>',
        '          retryGlobalPrivacy(data, ws, () => _reconnectGridCell(m.id, gimg, cell));\n'
        '          _showCellPrivate(cell, gimg, () =>', 'global grid resume')
    scripts['stream.js'] = replace_once(scripts['stream.js'],
        '\n        _showCellPrivate(cell, gimg, () =>',
        '\n        retryGlobalPrivacy(data, ws, () => _reconnectGridCell(id, gimg, cell));\n'
        '\n        _showCellPrivate(cell, gimg, () =>', 'global grid reconnect resume')
    scripts['controls.js'] = replace_once(scripts['controls.js'],
        'state.paused = !state.paused;',
        "state.paused = !state.paused;\n  window.dispatchEvent(new Event('classtream-pause'));", 'pause repaint')
    scripts['controls.js'] = scripts['controls.js'].replace('img.naturalWidth', 'img.width').replace('img.naturalHeight', 'img.height')
    scripts['controls.js'] = replace_once(scripts['controls.js'],
        'export function togglePause() {', "export function togglePause() {\n  if (new URLSearchParams(location.search).has('host')) return;", 'no teacher pause')
    scripts['controls.js'] = replace_once(scripts['controls.js'],
        'export function setupKeyboard() {', "export function setupKeyboard() {\n  if (new URLSearchParams(location.search).has('host')) return;", 'teacher keyboard owner')
    scripts['controls.js'] = scripts['controls.js'].replace(
        "    if (['INPUT', 'TEXTAREA'].includes(e.target.tagName)) return;",
        "    if (e.repeat || e.isComposing || e.keyCode === 229 || document.querySelector('.modal-backdrop:not(.hidden)')) return;\n"
        "    if (['INPUT', 'TEXTAREA'].includes(e.target.tagName)) return;")
    scripts['browser-compat.js'] = (Path(__file__).parent / 'browser-compat.js').read_text('utf-8')
    scripts['config.js'] = "import { createSessionId } from './browser-compat.js';\n" + scripts['config.js']
    scripts['config.js'] = replace_once(scripts['config.js'], 'crypto.randomUUID()',
                                         'createSessionId()', 'HTTP UUID')
    for name, expected in (('sidebar.js', 2), ('chat.js', 2)):
        if scripts[name].count('navigator.clipboard.writeText(') != expected:
            raise RuntimeError('Unsupported Classtream clipboard code: ' + name)
        scripts[name] = ("import { copyText } from './browser-compat.js';\n" +
                         scripts[name].replace('navigator.clipboard.writeText(', 'copyText('))

    scripts["config.js"] = replace_once(
        scripts["config.js"], "export const JOIN_PARAM = _p.get('join');",
        "export const JOIN_PARAM = _p.get('join') ?? window.__CLASSTREAM_JOIN_TOKEN__ ?? null;",
        "JOIN_PARAM")
    for name in ("stream.js", "voice.js"):
        scripts[name] = replace_once(
            scripts[name], "`ws://${location.host}",
            "`${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}", name)

    # Do not request the microphone just for opening a screen-viewing page.
    scripts["voice.js"] = replace_once(
        scripts["voice.js"],
        "  try {\n    const tmp = await navigator.mediaDevices.getUserMedia({ audio: true });\n"
        "    tmp.getTracks().forEach(t => t.stop());\n  } catch { /* labels will be generic */ }",
        "  // Ask for microphone permission only when the user starts talking.",
        "initial microphone request")
    scripts["voice.js"] = replace_once(
        scripts["voice.js"], "async function _populateDevices() {",
        "async function _populateDevices() {\n  if (!navigator.mediaDevices) return;", "device guard")
    scripts['voice.js'] = replace_once(
        scripts['voice.js'], 'export function initVoice() {',
        'export function initVoice() {\n  if (window.__CLASSTREAM_VOICE_ENABLED__ === false) return;', 'HTTP voice')
    scripts['voice.js'] = replace_once(scripts['voice.js'],
        "    if (e.code === 'KeyV' && !e.repeat &&",
        "    if (e.code === 'KeyV' && !e.repeat && !e.isComposing && e.keyCode !== 229 &&\n"
        "        !e.ctrlKey && !e.altKey && !e.metaKey && !e.shiftKey &&\n"
        "        document.documentElement.dataset.teacherKeys !== 'off' &&\n"
        "        !document.querySelector('.modal-backdrop:not(.hidden)') &&\n"
        "        !document.activeElement?.closest('button,select,summary,[contenteditable]') &&",
        'safe push to talk')
    scripts['voice.js'] = replace_once(scripts['voice.js'],
        "    if (e.code === 'KeyV' &&\n        !['INPUT', 'TEXTAREA'].includes(document.activeElement?.tagName)) {",
        "    if (e.code === 'KeyV') {", 'always release push to talk')
    scripts['voice.js'] = replace_once(scripts['voice.js'],
        "  _bind('voice-output-select', 'change', _applyOutputDevice);",
        "  window.addEventListener('blur', _stopTalk);\n"
        "  document.addEventListener('visibilitychange', () => { if (document.hidden) _stopTalk(); });\n"
        "  _bind('voice-output-select', 'change', _applyOutputDevice);", 'stop talking in background')
    scripts['voice.js'] = replace_once(scripts['voice.js'],
        "  const mime    = _pickMime();",
        "  if (!_talking) { _micStream.getTracks().forEach(t => t.stop()); _micStream = null; return; }\n"
        "  const mime    = _pickMime();", 'late microphone permission')
    for name, token in (("main.js", "status.session_token"), ("sidebar.js", "d.token")):
        scripts[name] = replace_once(
            scripts[name], "`${location.protocol}//${location.host}/?join=${" + token + "}`",
            json.dumps(public_url + "/class"), name + " student URL")
    if http_mode:
        scripts['main.js'] = "import { watchClassroomAddress } from './browser-compat.js';\nwatchClassroomAddress();\n" + scripts['main.js']

    template = (TEMPLATES_DIR / "index.html").read_text("utf-8")
    template = replace_once(template, '<img id="screen-img" src="" alt="Screen stream"/>',
        '<canvas id="screen-img" width="1280" height="800" aria-label="Screen stream"></canvas>', 'screen canvas')
    if template.count("<head>") != 1:
        raise RuntimeError("Unsupported Classtream HTML template.")
    template = template.replace('<head>', '<head><script>window.__CLASSTREAM_VOICE_ENABLED__=' +
                                ('false' if http_mode else 'true') + ';</script>', 1)
    if http_mode:
        template = template.replace('</head>', '<style>#voice-section,#voice-ptt-btn{display:none!important}</style></head>', 1)
        template = replace_once(template,
            '<div class="shortcut-row"><span>Push to Talk (hold)</span><kbd>V</kbd></div>',
            '', 'HTTP voice shortcut')

    from classroom_ui import render_template, localize_script
    template = render_template(template)
    scripts = {name: localize_script(name, source) for name, source in scripts.items()}

    @application.get('/classroom-ui/{name}')
    async def classroom_asset(name: str):
        from fastapi.responses import FileResponse
        if name not in ('classroom.css', 'classroom.js', 'classroom-errors.js', 'teacher-shortcuts.js'):
            return Response(status_code=404)
        return FileResponse(Path(__file__).parent / name, headers=no_cache)

    @application.get('/', response_class=HTMLResponse)
    async def index(request: Request):
        page = template
        if 'host' in request.query_params:
            page = re.sub(r'  <button class="btn" id="btn-pause".*?</button>', '', page, flags=re.S)
            page = re.sub(r'<div class="shortcut-row"><span>暂停 / 继续</span>.*?</div>', '', page)
        return HTMLResponse(page, headers=no_cache)

    @application.get("/class", response_class=HTMLResponse)
    @application.get("/class/", response_class=HTMLResponse)
    async def classroom():
        session = database.get_active_session()
        token = json.dumps(session["token"] if session else None).replace("<", "\\u003c")
        bootstrap = "<script>window.__CLASSTREAM_JOIN_TOKEN__=" + token + ";</script>"
        return HTMLResponse(template.replace("<head>", "<head>" + bootstrap, 1), headers=no_cache)

    @application.get("/static/js/{name}")
    async def javascript(name: str):
        if name in scripts:
            source = scripts[name].replace(json.dumps(public_url + '/class'),
                                            json.dumps(current_public_url() + '/class'))
            return Response(source, media_type="text/javascript", headers=no_cache)
        # Delegate unchanged modules to the original static-file mount.
        from fastapi.responses import FileResponse
        candidate = STATIC_DIR / "js" / name
        if candidate.parent == STATIC_DIR / "js" and candidate.is_file():
            return FileResponse(candidate, media_type="text/javascript", headers=no_cache)
        return Response(status_code=404)

    application.mount("/", original)
    return application
