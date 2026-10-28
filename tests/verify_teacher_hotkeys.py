"""Native registration/message delivery and authenticated privacy, using a temporary DB."""
import ctypes
from ctypes import wintypes
from contextlib import asynccontextmanager
import gc
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from unittest.mock import patch

adapter = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).resolve().parents[1] / 'windows-lan'
sys.path.insert(0, str(adapter))
from teacher_hotkeys import WindowsHotkeys, TeacherShortcuts, parse_binding

bindings = {'hide': 'Ctrl+Alt+Shift+Y', 'restore': 'Ctrl+Alt+Shift+Z'}
assert parse_binding('Ctrl+Alt+H') == (0x4003, ord('H'))
for invalid in ('H', 'Ctrl+H', 'Win+Alt+H', 'Ctrl+Alt+F11', 'Ctrl+Alt+HH', 'Ctrl+Ctrl+Alt+H'):
    try:
        parse_binding(invalid)
        raise AssertionError(invalid)
    except ValueError:
        pass

def eventually(predicate):
    deadline = time.monotonic() + 4
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.02)
    raise AssertionError('Timed out waiting for native shortcut state')

def post_hotkey(native, command_id):
    # Inject only into our isolated message queue, never the user's desktop input.
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    assert user32.PostThreadMessageW(native.thread_id, 0x0312, command_id, 0)

if os.name == 'nt':
    delivered = threading.Event()
    native = WindowsHotkeys(lambda cmd: delivered.set() if cmd == 'hide' else None)
    competitor = WindowsHotkeys(lambda cmd: None)
    try:
        assert not native.start(bindings), native.error
        assert competitor.start(bindings), 'Duplicate native registration must fail'
        post_hotkey(native, 1)
        assert delivered.wait(2), 'Registered hotkey message not delivered'
        native.stop()
        assert not competitor.start(bindings), 'Stopping must release all registrations'
        competitor.stop()
        assert not competitor.start({'restore': bindings['restore']})
        assert native.start(bindings), 'The second binding is occupied'
        probe = WindowsHotkeys(lambda cmd: None)
        try:
            assert not probe.start({'hide': bindings['hide']}), 'Failed pair must roll back its first binding'
        finally:
            probe.stop()
    finally:
        native.stop()
        competitor.stop()

with tempfile.TemporaryDirectory() as temporary, patch('teacher_hotkeys.notify'):
    os.environ['CLASSTREAM_DATA'] = temporary
    from compat import create_application
    from app import database, state
    from fastapi.testclient import TestClient
    app = create_application('http://192.0.2.10:8080')
    service = app.state.teacher_shortcuts
    database.init_db()
    database.create_admin('shortcut-test', 'isolated-test-password')
    session = database.new_session('Shortcut tests')

    @asynccontextmanager
    async def lifespan(_):
        yield
        await service.shutdown()
        await state.manager.shutdown()

    app.router.lifespan_context = lifespan
    with TestClient(app, client=('127.0.0.1', 50000)) as client:
        token = client.post('/api/admin/login', json={
            'username': 'shortcut-test', 'password': 'isolated-test-password'}).json()['token']
        headers = {'X-Admin-Token': token}
        assert client.get('/api/teacher-shortcuts').status_code == 403
        assert client.post('/api/teacher-shortcuts', headers=headers,
                           json={'enabled': True, 'bindings': bindings}).status_code == 400
        with TestClient(app, client=('192.0.2.25', 50001)) as remote:
            assert remote.get('/api/teacher-shortcuts', headers=headers).status_code == 403
            assert remote.post('/api/teacher-shortcuts', headers=headers,
                               json={'enabled': True}).status_code == 403
        with client.websocket_connect('/ws/1?stream=2&session_id=host-test&admin_token=' + token) as host:
            host.send_json({'type': 'register', 'session_id': 'host-test', 'name': 'Test teacher'})
            while host.receive_json()['type'] != 'chat:history':
                pass
            duplicate = {'hide': 'Ctrl+Alt+H', 'restore': 'Alt+Ctrl+H'}
            assert client.post('/api/teacher-shortcuts', headers=headers,
                               json={'enabled': True, 'bindings': duplicate}).status_code == 400
            state.screen_permissions[1] = {'allowed-student'}
            if os.name == 'nt':
                result = client.post('/api/teacher-shortcuts', headers=headers,
                                     json={'enabled': True, 'bindings': bindings}).json()
                assert result['enabled'] and result['online'], result
                saved = json.loads(service.preferences_path.read_text('utf-8'))
                assert saved == {'enabled': True, 'bindings': bindings}
                restored = TeacherShortcuts(service.preferences_path)
                assert restored.auto_enable and restored.bindings == bindings
                post_hotkey(service.native, 1)
                eventually(lambda: client.get('/api/teacher-shortcuts', headers=headers).json()['frozen'])
                with client.websocket_connect('/ws/1?stream=2&session_id=allowed-student&join=' + session) as student:
                    student.send_json({'type':'register','session_id':'allowed-student','name':'Frozen student'})
                    while student.receive_json()['type'] != 'chat:history':
                        pass
                    assert state.manager.frozen and not state.private_mode
                post_hotkey(service.native, 2)
                eventually(lambda: not client.get('/api/teacher-shortcuts', headers=headers).json()['frozen'])
            else:
                assert client.post('/api/screen/freeze', headers=headers, json={'enabled': True}).json()['frozen']
                assert not client.post('/api/screen/freeze', headers=headers, json={'enabled': False}).json()['frozen']
            assert state.screen_permissions[1] == {'allowed-student'}
            with client.websocket_connect('/ws/1?stream=2&session_id=other-student&join=' + session) as student:
                assert student.receive_json()['reason'] == 'restricted'
            with client.websocket_connect('/ws/1?stream=2&session_id=allowed-student&join=' + session) as student:
                student.send_json({'type': 'register', 'session_id': 'allowed-student', 'name': 'Student'})
                while student.receive_json()['type'] != 'chat:history':
                    pass
        if os.name == 'nt':
            before = state.manager.frozen
            post_hotkey(service.native, 1)
            eventually(lambda: service.revision >= 3)
            assert state.manager.frozen == before and '离线' in service.result
        client.post('/api/admin/logout', headers=headers)
        eventually(lambda: not service.native.thread or not service.native.thread.is_alive())
        assert client.post('/api/screen/freeze', headers=headers, json={'enabled': True}).status_code == 401
        new_token = client.post('/api/admin/login', json={
            'username': 'shortcut-test', 'password': 'isolated-test-password'}).json()['token']
        client.post('/api/teacher-shortcuts', headers={'X-Admin-Token': new_token}, json={'enabled': False})
        assert not TeacherShortcuts(service.preferences_path).auto_enable
    gc.collect()
print('PASS: native conflict/cleanup/message delivery, local-only auth, offline/logout rejection, freeze/resume, original per-screen permissions and credential-free preference persistence. Desktop key injection is not part of this test.')
