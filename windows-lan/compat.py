"""Small, in-memory adapter for the unmodified Classtream 1.0.1 package."""
import json
import ipaddress
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


def create_application(public_url, fps=10, teacher_url=None):
    if version("classtream") != "1.0.1":
        raise RuntimeError("This adapter requires classtream==1.0.1; see requirements.txt.")

    from fastapi import FastAPI
    from fastapi.responses import HTMLResponse, Response
    from app import database, state
    from app.main import app as original
    from app import main as original_module
    from fast_capture import capture_loop
    original_module.capture_loop = capture_loop
    from app.paths import STATIC_DIR, TEMPLATES_DIR
    state.settings.fps = fps

    @asynccontextmanager
    async def lifespan(_):
        async with original.router.lifespan_context(original):
            print(f"\nTeacher: {teacher_url or public_url + '/?host=admin'}")
            print(f"Student: {public_url}/class\n", flush=True)
            yield

    application = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None,
                          openapi_url=None)
    http_mode = public_url.startswith('http:')
    if http_mode:
        application.add_middleware(LocalAdministration)
    no_cache = {"Cache-Control": "no-store"}
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
    for name in ("config", "stream", "voice", "main", "sidebar", "chat"):
        scripts[name + ".js"] = (STATIC_DIR / "js" / (name + ".js")).read_text("utf-8")
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
    for name, token in (("main.js", "status.session_token"), ("sidebar.js", "d.token")):
        scripts[name] = replace_once(
            scripts[name], "`${location.protocol}//${location.host}/?join=${" + token + "}`",
            json.dumps(public_url + "/class"), name + " student URL")
    if http_mode:
        scripts['main.js'] = "import { watchClassroomAddress } from './browser-compat.js';\nwatchClassroomAddress();\n" + scripts['main.js']

    template = (TEMPLATES_DIR / "index.html").read_text("utf-8")
    if template.count("<head>") != 1:
        raise RuntimeError("Unsupported Classtream HTML template.")
    template = template.replace('<head>', '<head><script>window.__CLASSTREAM_VOICE_ENABLED__=' +
                                ('false' if http_mode else 'true') + ';</script>', 1)
    if http_mode:
        template = template.replace('</head>', '<style>#voice-section,#voice-ptt-btn{display:none!important}</style></head>', 1)
        template = replace_once(template,
            '<div class="shortcut-row"><span>Push to Talk (hold)</span><kbd>V</kbd></div>',
            '', 'HTTP voice shortcut')

    @application.get('/', response_class=HTMLResponse)
    async def index():
        return HTMLResponse(template, headers=no_cache)

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
