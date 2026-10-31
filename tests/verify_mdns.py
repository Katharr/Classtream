"""Isolated URL/bootstrap checks and real mDNS packets over loopback only."""
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import time
import uuid
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'windows-lan'))
from lan_address import student_addresses, validate_mdns
from mdns import Publisher
import lan

cfg = dict(mode='http', teacher_ip='127.0.0.1', http_port=80, https_port=8443,
           backend_port=8000, mdns_enabled=True, mdns_hostname='live')
assert student_addresses(cfg)['student_url'] == 'http://127.0.0.1'
for bad in ('Live', 'live.local', '-live', 'live-', '', 'a' * 64):
    try:
        validate_mdns(dict(cfg, mdns_hostname=bad))
        raise AssertionError('Invalid name accepted')
    except ValueError:
        pass
publisher = Publisher()
with patch.object(publisher, '_publish', side_effect=OSError('test failure')):
    publisher.sync(cfg)
assert publisher.status == 'unavailable'
assert student_addresses(cfg, publisher.publication(cfg))['student_url'] == 'http://127.0.0.1'

with tempfile.TemporaryDirectory(prefix='Classtream mDNS ') as folder:
    home = Path(folder)
    (home / 'runtime').mkdir()
    # No live classroom database, environment, capture or launcher is used.
    os.environ['CLASSTREAM_HOME'] = str(home)
    os.environ['CLASSTREAM_DATA'] = str(home / 'runtime' / 'data')
    (home / 'runtime' / 'data').mkdir()
    config = dict(cfg, teacher_ip='192.0.2.77')
    (home / 'config.json').write_text(json.dumps(config), 'utf-8')
    with patch.object(lan, 'HOME', home), patch.object(lan, 'RUNTIME', home / 'runtime'):
        loaded = lan.configuration()
        assert loaded['public_url'] == 'http://192.0.2.77'
        from compat import create_application
        from fastapi.testclient import TestClient
        from app import database
        database.init_db()
        database.create_admin('test-teacher', 'test-password')
        application = create_application(loaded['public_url'])
        with_client = TestClient(application, base_url='http://live.local', client=('127.0.0.1', 54321))
        # Deliberately omit lifespan: no screen capture.
        client = with_client
        assert 'window.__CLASSTREAM_JOIN_TOKEN__=null;' in client.get('/').text
        auth = client.post('/api/admin/login', json=dict(username='test-teacher', password='test-password')).json()['token']
        token = client.post('/api/session/new', json={'name': 'test'}, headers={'x-admin-token': auth}).json()['token']
        assert json.dumps(token) in client.get('/').text
        assert json.dumps(token) in client.get('/class').text
        assert 'window.__CLASSTREAM_JOIN_TOKEN__' not in client.get('/?host=admin').text
        assert client.get('/lan-info').json()['student_url'] == 'http://192.0.2.77'
        publisher.status = 'published'
        lan.publish_ready(loaded, publisher)
        info = client.get('/lan-info').json()
        assert info['student_url'] == 'http://live.local'
        assert info['fallback_url'] == 'http://192.0.2.77'
        for name in ('main', 'sidebar'):
            assert '"http://live.local"' in client.get('/static/js/' + name + '.js').text
        publisher.status = 'conflict'
        lan.publish_ready(loaded, publisher)
        assert client.get('/lan-info').json()['student_url'] == 'http://192.0.2.77'
        updated = lan.update_network_address(loaded, ['192.0.2.78'])
        # An old ready file must not advertise a name for the wrong interface.
        assert client.get('/lan-info').json()['student_url'] == 'http://192.0.2.78'
        publisher.status = 'published'
        lan.publish_ready(updated, publisher)
        assert client.get('/lan-info').json()['student_url'] == 'http://live.local'
        publisher.sync(updated, [])
        lan.publish_ready(updated, publisher)
        assert client.get('/lan-info').json()['mdns_status'] == 'offline'
        assert client.get('/lan-info').json()['student_url'] == 'http://192.0.2.78'
        assert student_addresses(dict(config, http_port=8080), dict(
            publisher.publication(config), mdns_status='published'))['student_url'] == 'http://192.0.2.77:8080'
        client.close()
    import gc
    gc.collect()

print('PASS: root bootstrap, teacher login, short links, IP fallback, stale status and network changes')

from zeroconf import DNSAddress, DNSIncoming, DNSOutgoing, DNSQuestion, IPVersion, Zeroconf

publisher = Publisher()
name = 'classtream-test-' + uuid.uuid4().hex[:12]
test_cfg = dict(cfg, mdns_hostname=name)
host = name + '.local.'
sender = Zeroconf(interfaces=['127.0.0.1'], ip_version=IPVersion.V4Only)
try:
    publisher.sync(test_cfg)
    assert publisher.status == 'published', publisher.error
    # An ordinary hostname A query, without browsing any DNS-SD services.
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as query_socket:
        query_socket.bind(('127.0.0.1', 0))
        query_socket.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton('127.0.0.1'))
        query_socket.settimeout(4)
        query = DNSOutgoing(0, multicast=False, id_=1234)
        query.add_question(DNSQuestion(host, 1, 1))
        query_socket.sendto(query.packets()[0], ('224.0.0.251', 5353))
        response = DNSIncoming(query_socket.recvfrom(9000)[0])
        assert any(record.name == host and getattr(record, 'address', None) == socket.inet_aton('127.0.0.1')
                   for record in response.answers())
    # A different address claiming the same host must withdraw our registration.
    def conflict_packet():
        packet = DNSOutgoing(0x8400)
        packet.add_answer_at_time(DNSAddress(host, 1, 0x8001, 30, socket.inet_aton('192.0.2.99')), 0)
        sender.send(packet)
    conflict_packet()
    assert publisher.conflict.wait(4), 'Later hostname conflict not detected'
    publisher.sync(test_cfg)
    assert publisher.status == 'conflict' and publisher.zc is None
    assert student_addresses(test_cfg, publisher.publication(test_cfg))['student_url'] == 'http://127.0.0.1'
    # Conflict present during startup must also prevent successful publication.
    publisher = Publisher()
    import threading
    timer = threading.Timer(.15, conflict_packet)
    timer.start()
    try:
        publisher.sync(test_cfg)
    finally:
        timer.join()
    assert publisher.status == 'conflict' and publisher.zc is None, publisher.error
finally:
    publisher.close()
    sender.close()
print('PASS: real loopback hostname resolution, startup/runtime conflicts and socket cleanup')
