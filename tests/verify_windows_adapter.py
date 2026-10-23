"""Integration checks use a separate database and never capture the screen."""
import json
import os
from pathlib import Path
import sys
import tempfile
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "windows-lan"))
temp = tempfile.TemporaryDirectory()
os.environ["CLASSTREAM_DATA"] = temp.name

from compat import create_application
from fastapi.testclient import TestClient
from app import database, state

database.init_db()
database.create_admin("test-teacher", "local-test-password")
application = create_application("https://192.0.2.10:8443")
client = TestClient(application, base_url="https://192.0.2.10:8443")
# Intentionally do not enter the client's lifespan: no screen capture or real DB.
assert 'window.__CLASSTREAM_JOIN_TOKEN__=null;' in client.get('/class').text
assert client.get('/class').headers['cache-control'] == 'no-store'
assert client.get('/').status_code == 200
assert client.get('/?host=admin').status_code == 200
assert client.get('/static/css/style.css').status_code == 200
assert client.get('/static/js/auth.js').status_code == 200
assert client.get('/static/js/missing.js').status_code == 404
assert client.post('/api/session/new', json={}).status_code == 401
auth = client.post('/api/admin/login', json={
    'username': 'test-teacher', 'password': 'local-test-password'}).json()['token']
headers = {'x-admin-token': auth}
token1 = client.post('/api/session/new', json={'name':'test one'}, headers=headers).json()['token']
page = client.get('/class')
assert page.url.path == '/class' and not page.history
assert json.dumps(token1) in page.text
token2 = client.post('/api/session/new', json={'name':'test two'}, headers=headers).json()['token']
assert token2 != token1
assert json.dumps(token2) in client.get('/class/').text
assert json.dumps(token1) not in client.get('/class').text
assert not database.is_valid_token(token1)

for filename in ('config', 'stream', 'voice', 'main', 'sidebar', 'chat', 'browser-compat'):
    response = client.get(f'/static/js/{filename}.js')
    assert response.status_code == 200
    assert response.headers['cache-control'] == 'no-store'
    (Path(temp.name) / (filename + '.mjs')).write_text(response.text, 'utf-8')
    (Path(temp.name) / (filename + '.js')).write_text(response.text, 'utf-8')
assert 'window.__CLASSTREAM_JOIN_TOKEN__' in client.get('/static/js/config.js').text
for filename in ('stream', 'voice'):
    source = client.get(f'/static/js/{filename}.js').text
    assert "'wss:' : 'ws:'" in source
    assert '`ws://${location.host}' not in source
for filename in ('main', 'sidebar'):
    assert '"https://192.0.2.10:8443/class"' in client.get(f'/static/js/{filename}.js').text

with client.websocket_connect('/ws/1?join=' + token1) as ws:
    assert ws.receive_json()['reason'] == 'invalid_session'
with client.websocket_connect('/ws/1?join=' + token2) as ws:
    assert ws.receive_json()['reason'] == 'host_disconnected'
with client.websocket_connect('/ws/1?admin_token=' + auth) as host:
    host.send_json({'type':'register','name':'Test teacher','session_id':'host-test'})
    while host.receive_json()['type'] != 'chat:history':
        pass
    with client.websocket_connect('/ws/1?join=' + token2) as student:
        student.send_json({'type':'register','name':'Test student','session_id':'student-test'})
        while student.receive_json()['type'] != 'chat:history':
            pass
        with client.websocket_connect('/voice/ws?join=' + token2 + '&session_id=student-test') as voice:
            assert voice.receive_json()['type'] == 'voice:init'
print('PASS: no-class page; short URL; rotation; authentication; original assets; screen and voice WebSockets.')
http_app = create_application('http://192.0.2.10:8080', teacher_url='http://127.0.0.1:8000/?host=admin')
local = TestClient(http_app, client=('127.0.0.1', 50000))
remote = TestClient(http_app, client=('192.0.2.11', 50001), base_url='http://192.0.2.10:8080')
assert remote.get('/class').status_code == 200
assert 'window.__CLASSTREAM_VOICE_ENABLED__=false' in remote.get('/class').text
assert 'window.__CLASSTREAM_VOICE_ENABLED__=false' in local.get('/?host=admin').text
assert remote.get('/?host=admin').status_code == 403
credentials = {'username': 'test-teacher', 'password': 'local-test-password'}
assert local.post('/api/admin/login', json=credentials).status_code == 200
assert remote.post('/api/admin/login', json=credentials).status_code == 403
assert remote.post('/api/admin/login', json=credentials, headers={'X-Forwarded-For': '127.0.0.1'}).status_code == 403
assert remote.post('/api/session/new', json={}, headers=headers).status_code == 403
assert remote.get('/api/status').status_code == 200
assert 'createSessionId()' in remote.get('/static/js/config.js').text
assert 'navigator.clipboard.writeText(' not in remote.get('/static/js/chat.js').text
assert 'copyText(raw)' in remote.get('/static/js/chat.js').text
try:
    with remote.websocket_connect('/ws/1?admin_token=' + auth):
        raise AssertionError('Remote host connection accepted.')
except Exception as exc:
    from starlette.websockets import WebSocketDisconnect
    assert isinstance(exc, WebSocketDisconnect) and exc.code == 1008
local.close()
remote.close()
print('PASS: HTTP viewer bootstrap; local administrator allowed; remote admin + spoofed forwarding denied; clipboard fallback.')
client.close()
node = shutil.which('node')
if node:
    target = Path(temp.name) / 'check_browser.mjs'
    shutil.copy2(ROOT / 'tests' / 'check_browser.mjs', target)
    (Path(temp.name) / 'package.json').write_text('{"type":"module"}', 'utf-8')
    for module in Path(temp.name).glob('*.mjs'):
        subprocess.run([node, '--check', str(module)], check=True)
    subprocess.run([node, str(target)], check=True)
else:
    print('SKIP: browser JS checks need Node.js (development only).')
import gc
gc.collect()
temp.cleanup()
