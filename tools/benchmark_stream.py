"""Bounded, in-process ASGI stream stress checks; no network or desktop access.

Run with the application Python: python tools/benchmark_stream.py.
The measured latency ends at a synthetic ASGI receiver, with artificial ACKs.
It is NOT browser rendering latency or physical screen-to-screen latency.
No application, database, classroom, listener, or capture device is started.
"""
import asyncio
import json
from pathlib import Path
import statistics
import struct
import sys
import time
from unittest.mock import patch

import cv2
import numpy as np
from starlette.websockets import WebSocket

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'windows-lan'))
from stream_transport import ACK_TIMEOUT, SEND_TIMEOUT, FrameStore, StreamManager
from app import state


def summary(values):
    if not values:
        return {'samples': 0, 'p50': None, 'p95': None, 'max': None}
    ordered = sorted(values)
    return dict(samples=len(values), p50=round(statistics.median(ordered), 2),
                p95=round(ordered[min(len(ordered) - 1, int(len(ordered) * .95))], 2),
                max=round(ordered[-1], 2))


def parse_packet(payload):
    assert payload[:4] == b'CS2\0', 'unexpected stream protocol'
    size = struct.unpack('!I', payload[4:8])[0]
    assert 0 < size <= len(payload) - 8, 'invalid header length'
    header = json.loads(payload[8:8 + size])
    offset, rectangles = 8 + size, {}
    for x, y, width, height, length in header['patches']:
        assert x >= 0 and y >= 0 and width > 0 and height > 0
        assert x + width <= header['width'] and y + height <= header['height']
        assert length > 0 and offset + length <= len(payload)
        rectangles[(x, y, width, height)] = payload[offset:offset + length]
        offset += length
    assert offset == len(payload), 'unconsumed image bytes'
    return header, rectangles


class SyntheticViewer:
    def __init__(self, name, timeline, *, teacher=False, ack_delay=0.,
                 missing_ack=False, blocked=False):
        self.name, self.timeline = name, timeline
        self.ack_delay, self.missing_ack, self.blocked = ack_delay, missing_ack, blocked
        self.incoming = asyncio.Queue()
        self.incoming.put_nowait({'type': 'websocket.connect'})
        self.ack_tasks = set()
        self.receipts, self.publication_age_ms, self.batch_sizes = [], [], []
        self.rectangles, self.epoch, self.seq = {}, 0, 0
        self.image_bytes = self.patch_bytes = 0
        self.send_attempts = 0
        self.block_started = asyncio.Event()
        self.closed_at = None
        query = b'stream=2&admin_token=synthetic-stress' if teacher else b'stream=2'
        self.ws = WebSocket(dict(type='websocket', path='/synthetic/1', headers=[],
                                 query_string=query), self.incoming.get, self.send)

    async def deliver_ack(self, header):
        if self.ack_delay:
            await asyncio.sleep(self.ack_delay)
        self.incoming.put_nowait(dict(type='websocket.receive', text=json.dumps(
            dict(type='stream:ack', epoch=header['epoch'], seq=header['seq']))))

    async def send(self, message):
        if message.get('bytes') is not None:
            self.send_attempts += 1
            if self.blocked:
                self.block_started.set()
                await asyncio.Event().wait()  # Must be cancelled by the send deadline.
            payload = message['bytes']
            header, rectangles = parse_packet(payload)
            received_at = time.monotonic()
            key = (header['epoch'], header['seq'])
            assert key in self.timeline, 'sender produced an unknown snapshot'
            if header['epoch'] == self.epoch:
                assert header['seq'] > self.seq, 'duplicate/out-of-order snapshot'
            if header['key']:
                self.rectangles.clear()
            else:
                assert header['epoch'] == self.epoch, 'delta without matching base'
            self.rectangles.update(rectangles)
            self.epoch, self.seq = key
            self.receipts.append(received_at)
            self.publication_age_ms.append((received_at - self.timeline[key]) * 1000)
            self.batch_sizes.append(len(payload))
            self.image_bytes += len(payload)
            self.patch_bytes += sum(map(len, rectangles.values()))
            if not self.missing_ack:
                task = asyncio.create_task(self.deliver_ack(header))
                self.ack_tasks.add(task)
                task.add_done_callback(self.ack_tasks.discard)
        elif message['type'] == 'websocket.close':
            self.closed_at = time.monotonic()
            self.incoming.put_nowait(dict(type='websocket.disconnect', code=message['code']))

    async def consume(self, manager):
        try:
            while True:
                if (await self.ws.receive())['type'] == 'websocket.disconnect':
                    break
        finally:
            manager.disconnect(self.ws, 1)


async def until(predicate, timeout, description):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(.005)
    assert predicate(), description


def code_frame():
    frame = np.full((720, 1280, 3), (30, 25, 22), np.uint8)
    lines = (
        'async def share_screen(classroom):',
        '    latest = await capture_desktop()',
        '    for student in classroom.students:',
        '        await student.send_latest(latest)',
        '    # Bounded queues; fresh state; visible status',
    )
    for row in range(23):
        text = f'{row + 1:02d}  ' + lines[row % len(lines)]
        cv2.putText(frame, text, (12, 28 + row * 29), cv2.FONT_HERSHEY_SIMPLEX,
                    .48, (210, 224, 236), 1, cv2.LINE_AA)
    return frame


async def scenario(name, count, *, blocked=False, fault=True, duration=4.25):
    manager, store, timeline = StreamManager(), FrameStore(), {}
    viewers = [SyntheticViewer('teacher', timeline, teacher=True)]
    viewers.extend(SyntheticViewer(f'student-{index}', timeline)
                   for index in range(1, count - (2 if fault else 1)))
    slow = SyntheticViewer('student-slow-900ms', timeline, ack_delay=.9)
    viewers.append(slow)
    failure = None
    if fault:
        failure = SyntheticViewer('student-blocked' if blocked else 'student-no-ack',
                                  timeline, blocked=blocked, missing_ack=not blocked)
        viewers.append(failure)
    assert len(viewers) == count
    normal = [viewer for viewer in viewers if not (viewer.ack_delay or
              viewer.blocked or viewer.missing_ack)]
    cooperative = [viewer for viewer in viewers if not (viewer.blocked or viewer.missing_ack)]
    receivers, encoding_ms = [], []
    generated = large_updates = 0
    peak_pace_ms = peak_tasks = 0
    frame = code_frame()
    rng = np.random.default_rng(281026 + count)
    started = time.monotonic()

    def publish(cursor):
        nonlocal generated
        before = time.monotonic()
        snapshot = store.update(frame, 70, cursor)
        encoding_ms.append((time.monotonic() - before) * 1000)
        assert snapshot is not None, 'the scripted source must change each update'
        timeline[(snapshot.epoch, snapshot.seq)] = time.monotonic()
        manager.publish(1, snapshot)
        generated += 1

    try:
        for index, viewer in enumerate(viewers):
            await manager.connect(viewer.ws, 1)
            manager.register_viewer(viewer.ws, f'{name}-{index}', viewer.name,
                                    role='host' if index == 0 else 'guest')
            receivers.append(asyncio.create_task(viewer.consume(manager)))
        assert manager.has_admin_connected() and manager.total_viewers == count
        tick = 0
        next_large = 0.
        while time.monotonic() - started < duration:
            elapsed = time.monotonic() - started
            if elapsed >= next_large:
                # A large, noisy right-hand panel changes alongside readable code.
                # This produces substantial packets instead of compressible blanks.
                frame[96:672, 768:1280] = rng.integers(0, 256, (576, 512, 3), np.uint8)
                next_large = elapsed + .8
                large_updates += 1
            frame[680:712, 16:160] = (tick * 19 % 256, tick * 37 % 256, tick * 53 % 256)
            cursor = (20 + tick * 7 % 700, 100 + tick % 500, True)
            publish(cursor)
            tick += 1
            peak_pace_ms = max(peak_pace_ms, manager.metrics(1).get('max_pace_ms', 0))
            peak_tasks = max(peak_tasks, len(manager.tasks))
            # Capture/encoding time is part of the tick budget, with no catch-up burst.
            await asyncio.sleep(max(.001, 1 / 30 - encoding_ms[-1] / 1000))

        target = store.latest
        expected = {(tile[0], tile[1], tile[2], tile[3]): tile[5] for tile in target.tiles}
        await until(lambda: all((peer := manager.peers.get(id(viewer.ws))) is not None
                    and peer.last_seq == target.seq for viewer in cooperative),
                    3., 'cooperative viewers did not converge to final state')
        assert all(viewer.rectangles == expected for viewer in cooperative), \
            'coalescing lost a changed tile; final canvases differ from the source'
        if failure:
            await until(lambda: failure.closed_at is not None, 1.,
                        'unresponsive sender was not closed')
            assert failure.closed_at - started < max(ACK_TIMEOUT, SEND_TIMEOUT) + 1., \
                'unresponsive sender survived its bounded deadline'
            if blocked:
                assert failure.block_started.is_set() and failure.image_bytes == 0
            else:
                assert len(failure.batch_sizes) == 1, 'missing ACK allowed multiple in-flight batches'
        for viewer in normal:
            assert viewer.closed_at is None, 'healthy viewer was disconnected'
            assert len(viewer.batch_sizes) >= (6 if count == 16 else 12), \
                'healthy viewer made too little progress under contention'
            if failure:
                assert viewer.receipts[-1] > failure.closed_at + .2, \
                    'healthy viewer stopped progressing after another viewer failed'

        # Static image/cursor produces no publication and no extra image bytes.
        before_idle = sum(viewer.image_bytes for viewer in cooperative)
        for _ in range(5):
            assert store.update(frame, 70, cursor) is None
        await asyncio.sleep(.3)
        assert sum(viewer.image_bytes for viewer in cooperative) == before_idle, \
            'static source caused image traffic'

        ages = [value for viewer in normal for value in viewer.publication_age_ms]
        gaps = [(right - left) * 1000 for viewer in normal
                for left, right in zip(viewer.receipts, viewer.receipts[1:])]
        age_summary, gap_summary = summary(ages), summary(gaps)
        p95_limit, max_limit = (1000, 2000) if count == 16 else (500, 1000)
        assert age_summary['p95'] < p95_limit, f'normal receiver age P95 too high: {age_summary}'
        assert age_summary['max'] < max_limit, f'normal receiver age maximum too high: {age_summary}'
        assert gap_summary['max'] < max_limit, f'normal receiver stalled: {gap_summary}'
        assert peak_tasks <= count * 2, 'unbounded stream sender tasks'
        assert peak_pace_ms >= 5, 'scenario did not exercise bandwidth pacing'
        result = dict(
            scenario=name, connections=count, normal_receivers=len(normal),
            image_budget_mbps=manager.bytes_per_second * 8 / 1_000_000,
            source_updates=generated, large_updates=large_updates,
            publication_to_synthetic_receive_ms=age_summary,
            normal_receive_gap_ms=gap_summary, encoding_ms=summary(encoding_ms),
            peak_pace_ms=peak_pace_ms, peak_sender_tasks=peak_tasks,
            batches=sum(len(viewer.batch_sizes) for viewer in viewers),
            packet_bytes=sum(viewer.image_bytes for viewer in viewers),
            batch_bytes=summary([size for viewer in viewers for size in viewer.batch_sizes]),
            slow_receiver_batches=len(slow.batch_sizes),
            failed_receiver_batches=len(failure.batch_sizes) if failure else None,
            failed_receiver_closed_ms=(round((failure.closed_at - started) * 1000, 2)
                                       if failure else None),
            static_image_bytes_delta=0, final_tile_maps_equal=True,
        )
    finally:
        for viewer in viewers:
            manager.disconnect(viewer.ws, 1)
        for task in receivers:
            task.cancel()
        await asyncio.gather(*receivers, return_exceptions=True)
        pending_acks = [task for viewer in viewers for task in viewer.ack_tasks]
        for task in pending_acks:
            task.cancel()
        await asyncio.gather(*pending_acks, return_exceptions=True)
        await manager.shutdown()
        await asyncio.sleep(0)
        assert not manager.tasks and not manager.peers
        assert not any(manager.connections.values()) and manager.total_viewers == 0
        assert not manager.has_admin_connected()
    result['tasks_after_shutdown'] = 0
    print('PASS ' + json.dumps(result, separators=(',', ':')), flush=True)
    return result


async def main():
    results = []
    with patch.dict(state.admin_tokens, {'synthetic-stress': {'username': 'synthetic'}}):
        results.append(await scenario('five_healthy_with_slow_ack', 5, fault=False, duration=3.5))
        results.append(await scenario('five_with_missing_ack', 5))
        results.append(await scenario('five_with_blocked_send', 5, blocked=True))
        # Initial keyframes queue for ~0.7s at this shared budget. Keep producing
        # past that plus the 3s ACK deadline to observe healthy progress afterward.
        results.append(await scenario('sixteen_short_pressure', 16, duration=4.5))
    print(json.dumps(dict(
        measurement='In-process publication to synthetic ASGI receipt; artificial ACKs; '
                    'not browser rendering or physical screen-to-screen latency',
        network_listener_started=False, desktop_capture_started=False,
        production_data_accessed=False, scenarios=results), indent=2), flush=True)


if __name__ == '__main__':
    asyncio.run(main())
