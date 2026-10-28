"""DXGI capture for Classtream 1.0.1, with MSS fallback and measured timings."""
import asyncio
import json
import os
import time

import cv2
import numpy as np


class FrameSource:
    def __init__(self, rect):
        self.rect = rect
        self.camera = None
        self.sct = None
        self.previous = None
        self.backend = 'mss'
        try:
            import dxcam
            # DXcam is pinned to 0.3.0. Match desktop coordinates, never assume
            # MSS monitor numbering matches DXGI output/adapter numbering.
            factory = getattr(dxcam, '__factory')
            for device_index, outputs in enumerate(factory.outputs):
                for output_index, output in enumerate(outputs):
                    bounds = output.desc.DesktopCoordinates
                    geometry = (bounds.left, bounds.top, bounds.right - bounds.left,
                                bounds.bottom - bounds.top)
                    if geometry == tuple(rect[k] for k in ('left', 'top', 'width', 'height')):
                        self.camera = dxcam.create(device_idx=device_index, output_idx=output_index,
                                                   output_color='BGR', max_buffer_len=2)
                        self.backend = 'dxgi'
                        return
            raise RuntimeError('No DXGI output matches the selected monitor.')
        except Exception as exc:
            self._fallback(exc)

    def _fallback(self, reason):
        if self.camera is not None:
            try:
                self.camera.release()
            except Exception:
                pass
            self.camera = None
        self.previous = None
        from mss import mss
        self.sct = mss()
        self.backend = 'mss'
        print(f'Capture: MSS fallback ({reason})', flush=True)

    def grab(self):
        if self.camera is not None:
            try:
                frame = self.camera.grab(new_frame_only=True)
                if frame is not None:
                    self.previous = frame
                    return frame, True
                return self.previous, False
            except Exception as exc:
                self._fallback(exc)
        raw = self.sct.grab(self.rect)
        return cv2.cvtColor(np.asarray(raw), cv2.COLOR_BGRA2BGR), True

    def close(self):
        if self.camera is not None:
            self.camera.release()
        if self.sct is not None:
            self.sct.close()


CAPTURE_TASKS = set()
META_INTERVAL = 1.0
CAPTURE_RETRY = 1.0


class CapturePipeline:
    """Keep capture creation, grabbing and release on one dedicated thread."""
    def __init__(self, rect):
        from stream_transport import FrameStore
        self.source = FrameSource(rect)
        self.rect = rect
        self.store = FrameStore()
        self.resized = None

    def tick(self, quality, show_cursor):
        import pyautogui
        started = time.perf_counter()
        frame, changed = self.source.grab()
        captured = time.perf_counter()
        if frame is None:
            raise RuntimeError('No screen frame available')
        if changed or self.resized is None:
            height = max(1, int(frame.shape[0] * 1280 / frame.shape[1]))
            self.resized = cv2.resize(frame, (1280, height), interpolation=cv2.INTER_LINEAR)
        x, y = pyautogui.position()
        sx = int((x - self.rect['left']) * 1280 / self.rect['width'])
        sy = int((y - self.rect['top']) * self.resized.shape[0] / self.rect['height'])
        visible = show_cursor and 0 <= sx < 1280 and 0 <= sy < self.resized.shape[0]
        cursor = (sx, sy, True) if visible else (0, 0, False)
        latest = self.store.latest
        if (not changed and latest is not None and latest.cursor == cursor
                and self.store.quality == quality):
            snapshot = None
        else:
            snapshot = self.store.update(self.resized, quality, cursor)
        return snapshot, ((captured - started) * 1000,
                          (time.perf_counter() - captured) * 1000), self.source.backend

    def close(self):
        self.source.close()


async def capture_loop(monitor_id, rect, manager, settings):
    from concurrent.futures import ThreadPoolExecutor
    task = asyncio.current_task()
    CAPTURE_TASKS.add(task)
    worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix=f'capture-{monitor_id}')
    loop = asyncio.get_running_loop()
    pipeline = None
    count = 0
    started = time.monotonic()
    last_log = started
    last_capture_at = None
    timings, backend = (0.0, 0.0), 'initializing'

    async def heartbeat():
        nonlocal count, started, last_log
        while True:
            await asyncio.sleep(META_INTERVAL)
            now = time.monotonic()
            elapsed = now - started
            rate = round(count / max(elapsed, .001), 1)
            count, started = 0, now
            if not manager.connections.get(monitor_id):
                continue
            try:
                snapshot = manager.latest.get(monitor_id)
                meta = dict(type='meta', fps=rate,
                            target_fps=min(30, settings.fps), viewers=manager.total_viewers,
                            quality=settings.quality, session=settings.session_name,
                            viewer_list=manager.get_viewer_list(), capture_backend=backend,
                            capture_ms=round(timings[0], 2), encode_ms=round(timings[1], 2),
                            stream_epoch=snapshot.epoch if snapshot else 0,
                            stream_seq=snapshot.seq if snapshot else 0,
                            capture_age_ms=(round((now - last_capture_at) * 1000, 1)
                                            if last_capture_at is not None else None),
                            frozen=manager.frozen, **manager.metrics(monitor_id))
                await manager.broadcast(monitor_id, json.dumps(meta))
                if now - last_log >= 5:
                    logged = {k: v for k, v in meta.items() if k not in ('viewer_list', 'session')}
                    print(f'Stream monitor={monitor_id}: {json.dumps(logged)}', flush=True)
                    last_log = now
            except Exception as exc:
                print(f'[heartbeat monitor={monitor_id}] {type(exc).__name__}: {exc}', flush=True)

    heartbeat_task = asyncio.create_task(heartbeat())
    try:
        while True:
            try:
                if not manager.connections.get(monitor_id):
                    await asyncio.sleep(0.1)
                    continue
                if pipeline is None:
                    pending = loop.run_in_executor(worker, CapturePipeline, rect)
                    try:
                        pipeline = await asyncio.shield(pending)
                    except asyncio.CancelledError:
                        pipeline = await pending
                        raise
                    print(f'Capture monitor={monitor_id}: {pipeline.source.backend}; stream=2', flush=True)
                begin = time.perf_counter()
                snapshot, timings, backend = await loop.run_in_executor(
                    worker, pipeline.tick, settings.quality, settings.show_cursor)
                # Static frames count as a healthy capture, without producing JPEGs.
                last_capture_at = time.monotonic()
                if snapshot is not None:
                    manager.publish(monitor_id, snapshot)
                    count += 1
                remaining = max(0, 1 / max(1, min(30, settings.fps)) - (time.perf_counter() - begin))
                if os.name == 'nt' and remaining > 0:
                    await asyncio.to_thread(time.sleep, remaining)
                else:
                    await asyncio.sleep(remaining)
            except Exception as exc:
                print(f'[capture monitor={monitor_id}] {exc}', flush=True)
                await asyncio.sleep(CAPTURE_RETRY)
    finally:
        heartbeat_task.cancel()
        await asyncio.gather(heartbeat_task, return_exceptions=True)
        if pipeline is not None:
            await loop.run_in_executor(worker, pipeline.close)
        worker.shutdown(wait=True)
        CAPTURE_TASKS.discard(task)
