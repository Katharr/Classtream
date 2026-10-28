"""Loopback-only synthetic classroom used by verify_stream_browser.cjs."""
import asyncio
from contextlib import asynccontextmanager
import os
from pathlib import Path
import sys
import tempfile
import time

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, os.environ.get('CLASSTREAM_TEST_ADAPTER', str(ROOT / 'windows-lan')))
TEMP = tempfile.TemporaryDirectory()
os.environ['CLASSTREAM_DATA'] = TEMP.name
from compat import create_application
from app import state, database
from stream_transport import FrameStore

PORT = int(os.environ.get('CLASSTREAM_TEST_PORT', '18765'))
if not 1024 <= PORT <= 65535:
    raise ValueError('Invalid synthetic classroom port')
app = create_application(f'http://127.0.0.1:{PORT}', fps=30)
# Keep synthetic browser checks separate from the running teacher's global keys.
app.state.teacher_shortcuts.bindings = {'hide': 'Ctrl+Alt+Shift+Y', 'restore': 'Ctrl+Alt+Shift+Z'}
database.init_db()
database.create_admin('fixture', 'fixture-password', 'Test teacher')
database.new_session('Synthetic classroom')
state.monitor_list[:] = [dict(id=1, label='Synthetic display', width=640, height=384, left=0, top=0)]
store = FrameStore()
frame = np.full((384, 640, 3), 245, np.uint8)
cv2.putText(frame, 'Classtream transport validation', (20, 50), cv2.FONT_HERSHEY_SIMPLEX,
            .7, (30, 30, 30), 2)
mode = {'moving': True, 'capture': True, 'heartbeat': True}
last_capture = None


async def produce():
    global last_capture
    i = 0
    while True:
        if mode['capture']:
            cursor = ((i * 5) % 600, 180, True) if mode['moving'] else (100, 180, True)
            snapshot = store.update(frame, state.settings.quality, cursor)
            last_capture = time.monotonic()
            if snapshot:
                state.manager.publish(1, snapshot)
        i += 1
        await asyncio.sleep(1 / 30)


async def heartbeat():
    import json
    while True:
        await asyncio.sleep(1)
        if mode['heartbeat']:
            snapshot = store.latest
            await state.manager.broadcast(1, json.dumps(dict(
                type='meta', fps=30 if mode['moving'] else 0, target_fps=30,
                viewers=state.manager.total_viewers, quality=state.settings.quality,
                session=state.settings.session_name, viewer_list=state.manager.get_viewer_list(),
                stream_epoch=snapshot.epoch if snapshot else 0,
                stream_seq=snapshot.seq if snapshot else 0,
                capture_age_ms=(time.monotonic() - last_capture) * 1000 if last_capture else None,
                frozen=state.manager.frozen, **state.manager.metrics(1))))


@asynccontextmanager
async def lifespan(_):
    tasks = [asyncio.create_task(produce()), asyncio.create_task(heartbeat())]
    try:
        yield
    finally:
        await app.state.teacher_shortcuts.shutdown()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await state.manager.shutdown()


app.router.lifespan_context = lifespan


@app.get('/test/stats')
async def stats():
    return dict(**state.manager.metrics(1), peers=len(state.manager.peers),
                tasks=len(state.manager.tasks))


@app.post('/test/mode/{moving}')
async def set_mode(moving: int):
    mode['moving'] = bool(moving)
    return {'ok': True}


@app.post('/test/color/{value}')
async def set_color(value: int):
    frame[280:310, 280:310] = (0, 0, max(0, min(255, value)))
    return {'ok': True}


@app.post('/test/health/{name}/{enabled}')
async def set_health(name: str, enabled: int):
    if name not in ('capture', 'heartbeat'):
        return {'ok': False}
    mode[name] = bool(enabled)
    return {'ok': True}


# Test-only endpoints must precede the adapter's upstream '/' mount.
app.router.routes[:] = app.router.routes[-4:] + app.router.routes[:-4]


if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='127.0.0.1', port=PORT, access_log=False, log_level='warning',
                ws_per_message_deflate=False)
