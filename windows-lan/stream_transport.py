"""Bounded JPEG rectangle transport, reusing upstream sessions and permissions.

Design references: MeshCentral's shared image cache / per-viewer send loop,
RFB rectangle updates and Guacamole's completed-frame sync. No upstream code
is copied. CS2 packets: magic, big-endian JSON length, JSON, JPEG rectangles.
Clients acknowledge {type:'stream:ack', epoch, seq} after applying a batch.
"""
import asyncio
import json
import struct
import time
from dataclasses import dataclass

import cv2
import numpy as np
from app.manager import ConnectionManager

MAGIC = b'CS2\0'
TILE = 128
SEND_TIMEOUT = 2.0
ACK_TIMEOUT = 3.0


@dataclass(frozen=True)
class Snapshot:
    epoch: int
    seq: int
    width: int
    height: int
    tiles: tuple
    cursor: tuple


class FrameStore:
    def __init__(self):
        self.previous = None
        self.quality = None
        self.epoch = 0
        self.seq = 0
        self.latest = None

    def update(self, frame, quality, cursor):
        reset = (self.previous is None or self.previous.shape != frame.shape
                 or quality != self.quality)
        if reset:
            self.epoch += 1
        tiles = []
        changed = reset
        index = 0
        for y in range(0, frame.shape[0], TILE):
            for x in range(0, frame.shape[1], TILE):
                pixels = frame[y:y + TILE, x:x + TILE]
                if reset or not np.array_equal(pixels, self.previous[y:y + TILE, x:x + TILE]):
                    ok, encoded = cv2.imencode('.jpg', pixels,
                                              [int(cv2.IMWRITE_JPEG_QUALITY), quality])
                    if not ok:
                        raise RuntimeError('JPEG rectangle encoding failed')
                    tiles.append((x, y, pixels.shape[1], pixels.shape[0], self.seq + 1,
                                  encoded.tobytes()))
                    changed = True
                else:
                    tiles.append(self.latest.tiles[index])
                index += 1
        if not changed and self.latest.cursor == cursor:
            return None
        self.seq += 1
        if changed:
            self.previous = frame.copy()
        self.quality = quality
        self.latest = Snapshot(self.epoch, self.seq, frame.shape[1], frame.shape[0],
                               tuple(tiles), cursor)
        return self.latest


def packet(snapshot, acknowledged_epoch, versions):
    key = snapshot.epoch != acknowledged_epoch
    selected = [t for i, t in enumerate(snapshot.tiles)
                if key or i >= len(versions) or versions[i] != t[4]]
    header = json.dumps(dict(epoch=snapshot.epoch, seq=snapshot.seq,
                             width=snapshot.width, height=snapshot.height, key=key,
                             cursor=snapshot.cursor,
                             patches=[[t[0], t[1], t[2], t[3], len(t[5])] for t in selected]),
                        separators=(',', ':')).encode()
    return MAGIC + struct.pack('!I', len(header)) + header + b''.join(t[5] for t in selected)


class Peer:
    def __init__(self, manager, ws, monitor):
        self.manager, self.ws, self.monitor = manager, ws, monitor
        self.raw_send, self.raw_receive = ws.send, ws.receive
        self.lock = asyncio.Lock()
        self.wake = asyncio.Event()
        self.ack = asyncio.Event()
        self.expected = None
        self.epoch, self.versions = 0, ()
        self.stopped = False
        self.controls = asyncio.Queue(maxsize=32)
        self.bytes_sent = self.frames_sent = self.coalesced = 0
        self.ack_ms = 0.0
        self.last_seq = 0
        self.resync = False
        self.task = asyncio.create_task(self.run())
        self.control_task = asyncio.create_task(self.send_controls())
        for task in (self.task, self.control_task):
            manager.tasks.add(task)
            task.add_done_callback(manager.tasks.discard)

    def stop(self):
        self.stopped = True
        for task in (self.task, self.control_task):
            if task is not asyncio.current_task():
                task.cancel()

    async def send(self, message):
        terminal = message['type'] == 'websocket.close'
        if message.get('text'):
            try:
                terminal |= json.loads(message['text']).get('type') in ('private', 'kicked', 'error')
            except (ValueError, AttributeError):
                pass
        if terminal:
            self.stop()
        async with self.lock:
            if self.stopped and message.get('bytes') is not None:
                return
            await asyncio.wait_for(self.raw_send(message), SEND_TIMEOUT)

    async def receive(self):
        while True:
            message = await self.raw_receive()
            if message.get('text'):
                try:
                    data = json.loads(message['text'])
                except ValueError:
                    return message
                if isinstance(data, dict) and data.get('type') == 'stream:ack':
                    if (data.get('epoch'), data.get('seq')) == self.expected:
                        self.ack.set()
                    continue
                if isinstance(data, dict) and data.get('type') == 'stream:resync':
                    self.resync = True
                    self.ack.set()
                    self.wake.set()
                    continue
            return message

    def enqueue_control(self, data):
        if self.stopped:
            return
        try:
            self.controls.put_nowait(data)
        except asyncio.QueueFull:
            self.stop()
            asyncio.create_task(self.close())

    async def close(self):
        try:
            await self.ws.close(code=1013)
        except Exception:
            pass

    async def send_controls(self):
        try:
            while True:
                await self.ws.send_text(await self.controls.get())
        except asyncio.CancelledError:
            raise
        except Exception:
            self.stop()
            await self.close()

    async def run(self):
        try:
            while True:
                await self.wake.wait()
                self.wake.clear()
                freeze_revision = self.manager.freeze_revision
                snapshot = self.manager.snapshot_for(self)
                if snapshot is None or self.stopped:
                    continue
                if self.resync:
                    self.epoch, self.versions, self.last_seq = 0, (), 0
                    self.resync = False
                if snapshot.seq == self.last_seq and snapshot.epoch == self.epoch:
                    continue
                payload = packet(snapshot, self.epoch, self.versions)
                # Global byte pacing also bounds simultaneous keyframe bursts.
                await self.manager.pace(len(payload))
                # A freeze/restore can happen while this batch waits for bandwidth.
                if self.manager.freeze_revision != freeze_revision:
                    self.wake.set()
                    continue
                self.expected = (snapshot.epoch, snapshot.seq)
                self.ack.clear()
                started = time.monotonic()
                await self.ws.send_bytes(payload)
                await asyncio.wait_for(self.ack.wait(), ACK_TIMEOUT)
                self.ack_ms = (time.monotonic() - started) * 1000
                self.bytes_sent += len(payload)
                self.frames_sent += 1
                if not self.resync:
                    self.epoch = snapshot.epoch
                    self.versions = tuple(t[4] for t in snapshot.tiles)
                    self.last_seq = snapshot.seq
                self.expected = None
        except asyncio.CancelledError:
            raise
        except Exception:
            self.stop()
            await self.close()


class StreamManager(ConnectionManager):
    def __init__(self):
        super().__init__()
        self.peers = {}
        self.latest = {}
        self.frozen = False
        self.freeze_revision = 0
        self.frozen_frames = {}
        self.tasks = set()
        self.next_send = 0.0
        self.bytes_per_second = 8_000_000  # 64 Mbps total image budget

    def is_teacher(self, peer):
        from app import state
        token = peer.ws.query_params.get('admin_token')
        return bool(token and token in state.admin_tokens)

    def snapshot_for(self, peer):
        if self.frozen and not self.is_teacher(peer):
            # Existing viewers keep their own final frame. New viewers receive only
            # the snapshot captured before freezing, never the live teacher preview.
            if peer.last_seq:
                return None
            return self.frozen_frames.get(peer.monitor)
        return self.latest.get(peer.monitor)

    def set_frozen(self, enabled):
        if self.frozen == enabled:
            return
        self.frozen = enabled
        self.freeze_revision += 1
        self.frozen_frames = dict(self.latest) if enabled else {}
        for peer in self.peers.values():
            peer.wake.set()

    async def pace(self, size):
        now = time.monotonic()
        due = max(now, self.next_send)
        self.next_send = due + size / self.bytes_per_second
        await asyncio.sleep(max(0, due - now))

    async def connect(self, ws, monitor_id):
        if ws.query_params.get('stream') != '2':
            await ws.accept()
            await ws.send_text(json.dumps({'type': 'error', 'reason': 'refresh_required'}))
            await ws.close(code=4004)
            return
        await super().connect(ws, monitor_id)
        peer = Peer(self, ws, monitor_id)
        self.peers[id(ws)] = peer
        ws.send, ws.receive = peer.send, peer.receive
        peer.wake.set()

    def disconnect(self, ws, monitor_id):
        peer = self.peers.pop(id(ws), None)
        if peer:
            peer.stop()
        super().disconnect(ws, monitor_id)

    async def shutdown(self):
        for peer in list(self.peers.values()):
            peer.stop()
        await asyncio.gather(*list(self.tasks), return_exceptions=True)
        self.latest.clear()
        self.frozen_frames.clear()

    def publish(self, monitor_id, snapshot):
        self.latest[monitor_id] = snapshot
        for ws in list(self.connections.get(monitor_id, [])):
            peer = self.peers.get(id(ws))
            if peer:
                peer.coalesced += int(peer.wake.is_set())
                peer.wake.set()

    async def broadcast(self, monitor_id, data):
        if isinstance(data, bytes):
            raise RuntimeError('Use publish() for versioned screen updates')
        for ws in list(self.connections.get(monitor_id, [])):
            peer = self.peers.get(id(ws))
            if peer:
                peer.enqueue_control(data)

    def metrics(self, monitor_id):
        peers = [p for p in self.peers.values() if p.monitor == monitor_id]
        return dict(stream_protocol=2, stream_bytes=sum(p.bytes_sent for p in peers),
                    stream_batches=sum(p.frames_sent for p in peers),
                    coalesced_updates=sum(p.coalesced for p in peers),
                    max_ack_ms=round(max((p.ack_ms for p in peers), default=0), 1))
