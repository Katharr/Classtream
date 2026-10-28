"""Server-assigned identities through real WebSockets, with isolated classroom data."""
from contextlib import ExitStack
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'windows-lan'))
temp = tempfile.TemporaryDirectory()
os.environ['CLASSTREAM_DATA'] = temp.name

from compat import create_application
from fastapi.testclient import TestClient
from app import database, state
from stream_transport import STUDENT_NICKNAMES


def receive(ws, kind):
    while True:
        data = ws.receive_json()
        if data['type'] == kind:
            return data


def register_student(ws, data):
    ws.send_json(data)
    messages = {}
    while not {'identity', 'chat:history'} <= messages.keys():
        message = ws.receive_json()
        messages[message['type']] = message
    return messages['identity']['name']


database.init_db()
database.create_admin('test', 'test-password')
app = create_application('http://127.0.0.1:18766')
with ExitStack() as stack:
    client = TestClient(app, client=('127.0.0.1', 50000))
    # Do not enter lifespan: never capture the real teacher desktop.
    stack.callback(client.close)
    token = client.post('/api/admin/login', json={'username': 'test', 'password': 'test-password'}).json()['token']
    headers = {'x-admin-token': token}
    room = client.post('/api/session/new', headers=headers, json={'name': 'nicknames'}).json()['token']
    host = stack.enter_context(client.websocket_connect('/ws/1?stream=2&admin_token=' + token))
    host.send_json({'type': 'register', 'session_id': 'teacher', 'name': '陈老师'})
    receive(host, 'chat:history')

    names = []
    for i in range(25):
        url = f'/ws/1?stream=2&join={room}&session_id=student-{i}'
        with client.websocket_connect(url) as student:
            register = {'type': 'register', 'session_id': f'student-{i}', 'name': '自定义姓名'}
            name = register_student(student, register)
            names.append(name)
            assert register_student(student, {**register, 'name': '再次改名'}) == name
            student.send_json({'type': 'chat:send', 'text': 'hello', 'sender': '伪造姓名'})
            assert receive(student, 'chat:message')['sender'] == name
            with client.websocket_connect(url.replace('/ws/1?', '/ws/2?')) as second_screen:
                second_screen.send_json(register)
                assert receive(second_screen, 'identity')['name'] == name
        with client.websocket_connect(url) as reconnect:
            reconnect.send_json(register)
            assert receive(reconnect, 'identity')['name'] == name
    assert len(set(names)) == 25
    assert set(names[:20]) == set(STUDENT_NICKNAMES)
    assert all(name.endswith('2') for name in names[20:])
    assert state.manager._session_name['teacher'] == '陈老师'
    page = client.get('/class').text
    assert 'id="name-input"' not in page and 'id="name-modal"' not in page
    assert 'export function submitName' not in client.get('/static/js/auth.js').text
print('PASS: 25 unique animal nicknames; custom names ignored; chat identity; reconnect and multi-screen stability; teacher name unchanged; no name input.')
import gc
gc.collect()
temp.cleanup()
