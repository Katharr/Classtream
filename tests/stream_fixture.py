"""Loopback-only synthetic classroom used by verify_stream_browser.cjs."""
import asyncio
from contextlib import asynccontextmanager
import os
from pathlib import Path
import sys
import tempfile

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'windows-lan'))
TEMP = tempfile.TemporaryDirectory()
os.environ['CLASSTREAM_DATA'] = TEMP.name
from compat import create_application
from app import state, database
from stream_transport import FrameStore

app = create_application('http://127.0.0.1:18765', fps=30)
database.init_db()
database.create_admin('fixture', 'fixture-password', 'Test teacher')
database.new_session('Synthetic classroom')
state.monitor_list[:] = [dict(id=1, label='Synthetic display', width=640, height=384, left=0, top=0)]
store = FrameStore()
frame = np.full((384, 640, 3), 245, np.uint8)
cv2.putText(frame, 'Classtream transport validation', (20, 50), cv2.FONT_HERSHEY_SIMPLEX,
            .7, (30, 30, 30), 2)
mode = {'moving': True}


async def produce():
    i = 0
    while True:
        cursor = ((i * 5) % 600, 180, True) if mode['moving'] else (100, 180, True)
        snapshot = store.update(frame, state.settings.quality, cursor)
        if snapshot:
            state.manager.publish(1, snapshot)
        i += 1
        await asyncio.sleep(1 / 30)


@asynccontextmanager
async def lifespan(_):
    task = asyncio.create_task(produce())
    yield
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
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


# Test-only endpoints must precede the adapter's upstream '/' mount.
app.router.routes[:] = app.router.routes[-3:] + app.router.routes[:-3]


if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='127.0.0.1', port=18765, access_log=False, log_level='warning',
                ws_per_message_deflate=False)
