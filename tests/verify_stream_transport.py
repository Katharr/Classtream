"""Synthetic frames and ASGI WebSockets: no desktop or classroom DB access."""
import asyncio
import json
from pathlib import Path
import struct
import sys
from unittest.mock import patch

import cv2
import numpy as np
from starlette.websockets import WebSocket

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'windows-lan'))
from stream_transport import FrameStore, StreamManager, packet


def unpack(payload):
    assert payload[:4] == b'CS2\0'
    size = struct.unpack('!I', payload[4:8])[0]
    header = json.loads(payload[8:8 + size])
    offset = 8 + size
    images = []
    for x, y, w, h, length in header['patches']:
        image = cv2.imdecode(np.frombuffer(payload[offset:offset + length], np.uint8), cv2.IMREAD_COLOR)
        assert image.shape == (h, w, 3)
        images.append((x, y, image))
        offset += length
    assert offset == len(payload)
    return header, images


def check_rectangles():
    store = FrameStore()
    frame = np.zeros((256, 384, 3), np.uint8)
    first = store.update(frame, 70, (10, 10, True))
    assert len(unpack(packet(first, 0, ()))[0]['patches']) == 6
    versions = tuple(t[4] for t in first.tiles)
    assert store.update(frame, 70, (10, 10, True)) is None
    cursor = store.update(frame, 70, (20, 20, True))
    payload = packet(cursor, first.epoch, versions)
    assert unpack(payload)[0]['patches'] == []
    frame[0:20, 0:20] = 255
    skipped = store.update(frame, 70, (20, 20, True))
    frame[200:220, 300:320] = 180
    latest = store.update(frame, 70, (20, 20, True))
    header, images = unpack(packet(latest, first.epoch, versions))
    assert len(images) == 2  # The skipped batch's change must survive.
    composed = np.zeros_like(frame)
    for x, y, image in images:
        composed[y:y + image.shape[0], x:x + image.shape[1]] = image
    assert composed[5, 5, 0] > 240 and composed[205, 305, 0] > 160
    changed_quality = store.update(frame, 60, (20, 20, False))
    assert changed_quality.epoch != first.epoch
    assert unpack(packet(changed_quality, first.epoch, versions))[0]['key']
    resized = store.update(frame[:128], 60, (20, 20, False))
    assert resized.epoch != changed_quality.epoch
    print(f'PASS: static dedup, cursor-only packet {len(payload)} bytes, cumulative dirty tiles, quality/size reset, JPEG composition.')


class Browser:
    def __init__(self, auto_ack=True, block_send=False):
        self.incoming = asyncio.Queue()
        self.incoming.put_nowait({'type': 'websocket.connect'})
        self.outgoing = []
        self.auto_ack = auto_ack
        self.block_send = block_send
        self.blocked = asyncio.Event()
        self.ws = WebSocket(dict(type='websocket', path='/ws/1', headers=[],
                                 query_string=b'stream=2'), self.incoming.get, self.send)

    async def send(self, message):
        if message.get('bytes') and self.block_send:
            self.blocked.set()
            await asyncio.Event().wait()
        self.outgoing.append(message)
        if message.get('bytes') and self.auto_ack:
            h, _ = unpack(message['bytes'])
            self.incoming.put_nowait(dict(type='websocket.receive', text=json.dumps(
                dict(type='stream:ack', epoch=h['epoch'], seq=h['seq']))))

    async def consume(self):
        while True:
            await self.ws.receive()


async def until(predicate, timeout=1):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(.002)


async def check_peers():
    manager = StreamManager()
    store = FrameStore()
    frame = np.zeros((256, 384, 3), np.uint8)
    fast, slow, blocked = Browser(), Browser(False), Browser(block_send=True)
    browsers = (fast, slow, blocked)
    receivers = []
    for browser in browsers:
        await manager.connect(browser.ws, 1)
        receivers.append(asyncio.create_task(browser.consume()))
    first = store.update(frame, 70, (0, 0, True))
    manager.publish(1, first)
    await until(lambda: manager.peers[id(fast.ws)].frames_sent == 1)
    await blocked.blocked.wait()
    for i in range(1, 8):
        frame[i:i+1, i:i+1] = i * 20
        manager.publish(1, store.update(frame, 70, (i, i, True)))
        await asyncio.sleep(.004)
    await until(lambda: manager.peers[id(fast.ws)].last_seq == store.latest.seq)
    assert len([m for m in slow.outgoing if m.get('bytes')]) == 1
    # Forged future ACK cannot unlock the slow sender.
    slow.incoming.put_nowait(dict(type='websocket.receive', text=json.dumps(
        dict(type='stream:ack', epoch=first.epoch, seq=99999))))
    await asyncio.sleep(.01)
    assert manager.peers[id(slow.ws)].frames_sent == 0
    slow.incoming.put_nowait(dict(type='websocket.receive', text=json.dumps(
        dict(type='stream:ack', epoch=first.epoch, seq=first.seq))))
    await until(lambda: len([m for m in slow.outgoing if m.get('bytes')]) == 2)
    last = [m['bytes'] for m in slow.outgoing if m.get('bytes')][-1]
    assert unpack(last)[0]['seq'] == store.latest.seq
    await manager.broadcast(1, json.dumps({'type': 'meta', 'fps': 30}))
    await until(lambda: any(m.get('text') for m in fast.outgoing))
    previous_count = len([m for m in fast.outgoing if m.get('bytes')])
    fast.incoming.put_nowait(dict(type='websocket.receive', text=json.dumps(dict(type='stream:resync'))))
    await until(lambda: len([m for m in fast.outgoing if m.get('bytes')]) > previous_count)
    assert unpack([m['bytes'] for m in fast.outgoing if m.get('bytes')][-1])[0]['key']
    # Existing permission/kick path cancels pending image work before notification.
    await slow.ws.send_text(json.dumps({'type': 'private'}))
    assert manager.peers[id(slow.ws)].stopped
    before = len(slow.outgoing)
    manager.publish(1, store.latest)
    await asyncio.sleep(.01)
    assert len(slow.outgoing) == before
    for browser in browsers:
        manager.disconnect(browser.ws, 1)
    for task in receivers:
        task.cancel()
    await asyncio.gather(*receivers, return_exceptions=True)
    await manager.shutdown()
    assert not manager.peers and not manager.has_admin_connected()
    print('PASS: healthy viewer isolated from blocked socket and missing ACK; one frame in flight; latest cumulative batch; forged ACK ignored; control/permission cleanup.')


async def check_ack_timeout():
    manager = StreamManager()
    browser = Browser(False)
    await manager.connect(browser.ws, 1)
    receiver = asyncio.create_task(browser.consume())
    store = FrameStore()
    with patch('stream_transport.ACK_TIMEOUT', .05):
        manager.publish(1, store.update(np.zeros((128, 128, 3), np.uint8), 70, (0, 0, False)))
        await until(lambda: any(m['type'] == 'websocket.close' for m in browser.outgoing))
    assert len([m for m in browser.outgoing if m.get('bytes')]) == 1
    assert manager.peers[id(browser.ws)].stopped
    manager.disconnect(browser.ws, 1)
    receiver.cancel()
    await asyncio.gather(receiver, return_exceptions=True)
    await manager.shutdown()
    assert not manager.tasks
    print('PASS: explicit resync keyframe; missing ACK closes rather than accumulating data; sender tasks drained.')


async def check_freeze():
    from app import state
    manager, store = StreamManager(), FrameStore()
    frame = np.zeros((128, 128, 3), np.uint8)
    student, teacher, late = Browser(), Browser(), Browser()
    teacher.ws.scope['query_string'] = b'stream=2&admin_token=freeze-test'
    receivers = []
    with patch.dict(state.admin_tokens, {'freeze-test': True}):
        for browser in (student, teacher):
            await manager.connect(browser.ws, 1)
            receivers.append(asyncio.create_task(browser.consume()))
        initial = store.update(frame, 70, (0, 0, False))
        manager.publish(1, initial)
        await until(lambda: all(manager.peers[id(b.ws)].frames_sent == 1 for b in (student, teacher)))
        manager.set_frozen(True)
        frame[:] = 255
        live = store.update(frame, 70, (0, 0, False))
        manager.publish(1, live)
        await until(lambda: manager.peers[id(teacher.ws)].last_seq == live.seq)
        assert manager.peers[id(student.ws)].last_seq == initial.seq
        await manager.connect(late.ws, 1)
        receivers.append(asyncio.create_task(late.consume()))
        await until(lambda: manager.peers[id(late.ws)].frames_sent == 1)
        assert manager.peers[id(late.ws)].last_seq == initial.seq
        manager.set_frozen(True)  # Idempotence must not replace the frozen snapshot.
        assert manager.frozen_frames[1] is initial
        manager.set_frozen(False)  # Resume even when no new capture is published.
        await until(lambda: all(manager.peers[id(b.ws)].last_seq == live.seq for b in (student, late)))
        assert not any(m['type'] == 'websocket.close' for b in (student, teacher, late) for m in b.outgoing)
    for browser in (student, teacher, late):
        manager.disconnect(browser.ws, 1)
    for task in receivers:
        task.cancel()
    await asyncio.gather(*receivers, return_exceptions=True)
    await manager.shutdown()
    # Freeze while the next frame is queued for bandwidth: do not send that frame.
    manager, student = StreamManager(), Browser()
    await manager.connect(student.ws, 1)
    receiver = asyncio.create_task(student.consume())
    manager.publish(1, initial)
    await until(lambda: manager.peers[id(student.ws)].frames_sent == 1)
    entered, release = asyncio.Event(), asyncio.Event()
    async def queued_pace(_):
        entered.set()
        await release.wait()
    manager.pace = queued_pace
    manager.publish(1, live)
    await entered.wait()
    manager.set_frozen(True)
    release.set()
    await asyncio.sleep(.05)
    assert manager.peers[id(student.ws)].frames_sent == 1
    manager.set_frozen(False)
    await until(lambda: manager.peers[id(student.ws)].last_seq == live.seq)
    manager.disconnect(student.ws, 1)
    receiver.cancel()
    await asyncio.gather(receiver, return_exceptions=True)
    await manager.shutdown()
    print('PASS: frozen final frame, live teacher preview, frozen late join, idempotence, static resume, and queued-frame freeze race without reconnect.')


if __name__ == '__main__':
    check_rectangles()
    asyncio.run(check_peers())
    asyncio.run(check_ack_timeout())
    asyncio.run(check_freeze())
