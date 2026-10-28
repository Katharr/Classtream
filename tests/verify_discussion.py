"""Real WebSocket permission checks; separate database and no desktop capture."""
from contextlib import ExitStack
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'windows-lan'))
temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ['CLASSTREAM_DATA'] = temp.name

from compat import create_application
from fastapi.testclient import TestClient
from app import database, state


def receive(ws, kind):
    for _ in range(100):
        data = ws.receive_json()
        if data['type'] == kind:
            return data
    raise AssertionError('Missing message: ' + kind)


def register(ws, sid):
    ws.send_json(dict(type='register', session_id=sid, name='test'))
    receive(ws, 'chat:history')


database.init_db()
database.create_admin('test', 'test-password')
app = create_application('http://127.0.0.1:18766')
with ExitStack() as stack:
    client = TestClient(app, client=('127.0.0.1', 50000))
    stack.callback(client.close)
    remote = TestClient(app, client=('192.0.2.11', 50001))
    stack.callback(remote.close)
    auth = client.post('/api/admin/login', json=dict(username='test', password='test-password')).json()['token']
    headers = {'x-admin-token': auth}
    room = client.post('/api/session/new', headers=headers, json={'name': 'discussion'}).json()['token']
    assert client.get('/api/discussion').status_code == 401
    assert remote.post('/api/discussion', headers=headers, json=dict(scope='all', muted=True)).status_code == 403
    assert client.post('/api/discussion', headers=headers, json=dict(scope='all', muted='false')).status_code == 400
    assert client.get('/api/discussion', headers=headers).json()['all_muted'] is False
    host = stack.enter_context(client.websocket_connect('/ws/1?stream=2&admin_token=' + auth))
    register(host, 'host')
    first = stack.enter_context(client.websocket_connect(f'/ws/1?stream=2&join={room}&session_id=first'))
    register(first, 'first')
    second = stack.enter_context(client.websocket_connect(f'/ws/1?stream=2&join={room}&session_id=second'))
    register(second, 'second')
    first_id = state.manager._viewer_id['first']

    def change(**data):
        response = client.post('/api/discussion', headers=headers, json=data)
        assert response.status_code == 200, response.text
        return response.json()

    def send(ws, text):
        ws.send_json(dict(type='chat:send', text=text))
        return receive(ws, 'chat:message')

    def blocked(ws, **data):
        ws.send_json(data)
        assert receive(ws, 'chat:blocked')['muted'] is True

    send(first, 'default allowed')
    change(scope='student', viewer_id=first_id, muted=True)
    blocked(first, type='chat:send', text='blocked text')
    blocked(first, type='chat:send', file={'url': '/uploads/blocked.txt'}, text='')
    blocked(first, type='chat:react', msg_id=state.manager.chat_history[0]['id'], emoji='👍')
    first.send_json(dict(type='register', session_id='host', name='fake teacher'))
    first.send_json(dict(type='register', session_id='second', name='fake student'))
    blocked(first, type='chat:send', text='spoof blocked')
    assert state.manager._session_role['host'] == 'host'
    send(second, 'other student allowed')
    send(host, 'teacher allowed')
    for monitor in (2, 1):
        with client.websocket_connect(f'/ws/{monitor}?stream=2&join={room}&session_id=first') as reconnect:
            register(reconnect, 'first')
            blocked(reconnect, type='chat:send', text='reconnect or second screen blocked')
    change(scope='all', muted=True)
    blocked(second, type='chat:send', text='all blocked')
    with client.websocket_connect(f'/ws/1?stream=2&join={room}&session_id=late') as late:
        register(late, 'late')
        blocked(late, type='chat:send', text='late join blocked')
    send(host, 'teacher during all mute')
    change(scope='all', muted=False)
    send(second, 'all mute released')
    blocked(first, type='chat:send', text='individual remains blocked')
    change(scope='student', viewer_id=first_id, muted=False)
    send(first, 'individual released')
    texts = [message['text'] for message in state.manager.chat_history]
    assert texts == ['default allowed', 'other student allowed', 'teacher allowed',
                     'teacher during all mute', 'all mute released', 'individual released'], texts
    assert not state.manager.chat_history[0]['reactions']
    host_id = state.manager._viewer_id['host']
    assert client.post('/api/discussion', headers=headers,
                       json=dict(scope='student', viewer_id=host_id, muted=True)).status_code == 404
    change(scope='student', viewer_id=first_id, muted=True)
    change(scope='all', muted=True)
    assert client.post('/api/session/new', json={'name': 'unauthorized'}).status_code == 401
    assert client.get('/api/discussion', headers=headers).json()['all_muted'] is True
    client.post('/api/session/new', headers=headers, json={'name': 'next classroom'})
    assert client.get('/api/discussion', headers=headers).json() == dict(ok=True, all_muted=False, muted_viewer_ids=[])
print('PASS: default open; teacher authorization; individual/all mute; text/file/reaction blocking; teacher exemption; reconnect/multi-screen/late join; registration spoof rejected; unmute precedence; classroom reset.')
