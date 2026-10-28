"""Exercise actual adapter startup/capture/shutdown with a temporary database."""
import json
import gc
import os
from pathlib import Path
import struct
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.stdout.reconfigure(encoding='utf-8')
adapter = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else ROOT / 'windows-lan'
sys.path.insert(0, str(adapter))
with tempfile.TemporaryDirectory() as data:
    os.environ['CLASSTREAM_DATA'] = data
    from compat import create_application
    from fast_capture import CAPTURE_TASKS
    from fastapi.testclient import TestClient
    from app import database, state
    from stream_transport import StreamManager

    app = create_application('http://192.0.2.10:8080', fps=30)
    with TestClient(app, client=('127.0.0.1', 54321)) as client:
        database.create_admin('lifecycle-test', 'isolated-test-password', 'Lifecycle teacher')
        token = client.post('/api/admin/login', json={
            'username': 'lifecycle-test', 'password': 'isolated-test-password'}).json()['token']
        assert client.get('/api/status').json()['fps'] == 30
        assert isinstance(state.manager, StreamManager)
        with client.websocket_connect('/ws/1?stream=2&admin_token=' + token) as ws:
            ws.send_json(dict(type='register', name='Lifecycle teacher', session_id='lifecycle'))
            while True:
                message = ws.receive()
                if message.get('bytes'):
                    payload = message['bytes']
                    size = struct.unpack('!I', payload[4:8])[0]
                    header = json.loads(payload[8:8 + size])
                    assert header['key'] and header['patches']
                    ws.send_json(dict(type='stream:ack', epoch=header['epoch'], seq=header['seq']))
                    break
    assert not CAPTURE_TASKS
    assert not state.manager.tasks
    assert not state.manager.peers
    print('PASS: actual teacher adapter startup, 30 FPS setting, screen packet/ACK, disconnect, capture-thread and sender shutdown; temporary DB only.')
    gc.collect()  # Upstream sqlite context managers rely on GC to close handles.
