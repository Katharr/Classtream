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


async def capture_loop(monitor_id, rect, manager, settings):
    from app.capture import _draw_cursor
    source = None
    try:
        count = fresh = 0
        totals = [0.0, 0.0, 0.0, 0]
        started = time.perf_counter()
        while True:
            try:
                if not manager.connections.get(monitor_id):
                    count = fresh = 0
                    totals = [0.0, 0.0, 0.0, 0]
                    started = time.perf_counter()
                    await asyncio.sleep(0.1)
                    continue
                if source is None:
                    source = FrameSource(rect)
                    print(f'Capture monitor={monitor_id}: {source.backend}', flush=True)
                    started = time.perf_counter()
                begin = time.perf_counter()
                frame, changed = source.grab()
                captured = time.perf_counter()
                if frame is None:
                    await asyncio.sleep(0.005)
                    continue
                height = max(1, int(frame.shape[0] * 1280 / frame.shape[1]))
                frame = cv2.resize(frame, (1280, height), interpolation=cv2.INTER_LINEAR)
                if settings.show_cursor:
                    _draw_cursor(frame, rect, 1280, height)
                ok, encoded = cv2.imencode('.jpg', frame,
                    [int(cv2.IMWRITE_JPEG_QUALITY), settings.quality])
                if not ok:
                    raise RuntimeError('JPEG encoding failed.')
                payload = encoded.tobytes()
                compressed = time.perf_counter()
                await manager.broadcast(monitor_id, payload)
                sent = time.perf_counter()
                count += 1
                fresh += int(changed)
                for i, value in enumerate((captured - begin, compressed - captured,
                                            sent - compressed, len(payload))):
                    totals[i] += value
                elapsed = sent - started
                if elapsed >= 1.0:
                    await manager.broadcast(monitor_id, json.dumps({
                        'type': 'meta', 'fps': round(count / elapsed, 1),
                        'viewers': manager.total_viewers, 'quality': settings.quality,
                        'session': settings.session_name, 'viewer_list': manager.get_viewer_list(),
                        'capture_backend': source.backend,
                        'new_capture_fps': round(fresh / elapsed, 1),
                        'capture_ms': round(totals[0] * 1000 / count, 2),
                        'encode_ms': round(totals[1] * 1000 / count, 2),
                        'send_ms': round(totals[2] * 1000 / count, 2),
                        'frame_kib': round(totals[3] / count / 1024, 1),
                    }))
                    count = fresh = 0
                    totals = [0.0, 0.0, 0.0, 0]
                    started = time.perf_counter()
                remaining = max(0, 1 / max(1, settings.fps) -
                                (time.perf_counter() - begin))
                if os.name == 'nt' and settings.fps >= 30 and remaining > 0:
                    # Windows' IOCP asyncio sleep measured ~15.6 ms even for a
                    # 1 ms request. Python 3.14 sleep uses a high-resolution
                    # waitable timer; run it in a worker to keep WS responsive.
                    await asyncio.to_thread(time.sleep, remaining)
                else:
                    await asyncio.sleep(remaining)
            except Exception as exc:
                print(f'[capture monitor={monitor_id}] {exc}', flush=True)
                await asyncio.sleep(1)
    finally:
        if source is not None:
            source.close()
