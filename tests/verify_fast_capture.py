import asyncio,json,sys,types
from pathlib import Path
from unittest.mock import patch
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1] / 'windows-lan'))
from fast_capture import FrameSource
rect=dict(left=-1920,top=0,width=1920,height=1080)
def output(left,top,width,height):
    b=types.SimpleNamespace(left=left,top=top,right=left+width,bottom=top+height)
    return types.SimpleNamespace(desc=types.SimpleNamespace(DesktopCoordinates=b))
class Camera:
    def __init__(self):self.calls=0;self.closed=False;self.fail=False
    def grab(self,**kw):
        if self.fail:raise RuntimeError('GPU unavailable')
        self.calls+=1
        return np.full((1080,1920,3),70,np.uint8) if self.calls==1 else None
    def release(self):self.closed=True
camera=Camera();choices=[]
def create(**kw):choices.append(kw);return camera
fake=types.SimpleNamespace(__factory=types.SimpleNamespace(outputs=[[output(0,0,1920,1080)],[output(-1920,0,1920,1080)]]),create=create)
class MSS:
    def __init__(self):self.closed=False
    def grab(self,r):return np.zeros((r['height'],r['width'],4),np.uint8)
    def close(self):self.closed=True
with patch.dict(sys.modules,{'dxcam':fake,'mss':types.SimpleNamespace(mss=MSS)}):
    src=FrameSource(rect)
    assert src.backend=='dxgi' and choices[0]['device_idx']==1 and choices[0]['output_idx']==0
    a,fresh=src.grab();assert fresh
    b,fresh=src.grab();assert not fresh and a is b
    camera.fail=True
    c,fresh=src.grab();assert fresh and src.backend=='mss' and camera.closed and c.shape==(1080,1920,3)
    fallback=src.sct;src.close();assert fallback.closed
    missing=FrameSource(dict(left=99,top=99,width=100,height=100));assert missing.backend=='mss';missing.close()
print('PASS: exact multi-adapter/negative-coordinate monitor mapping, unchanged frame reuse, GPU failure fallback and resource release.')


async def check_capture_heartbeat():
    from fast_capture import capture_loop, CAPTURE_TASKS
    from stream_transport import FrameStore

    class Pipeline:
        fail = True
        closed = False

        def __init__(self, _):
            self.source = types.SimpleNamespace(backend='synthetic')
            self.first = True
            self.snapshot = FrameStore().update(np.zeros((128, 128, 3), np.uint8),
                                                70, (0, 0, False))

        def tick(self, *_):
            if self.fail:
                raise RuntimeError('synthetic capture failure')
            snapshot = self.snapshot if self.first else None
            self.first = False
            return snapshot, (1.0, 2.0), 'synthetic'

        def close(self):
            Pipeline.closed = True

    class Manager:
        connections = {1: [object()]}
        latest = {}
        frozen = False
        total_viewers = 1
        messages = []

        def publish(self, monitor, snapshot): self.latest[monitor] = snapshot
        def get_viewer_list(self): return []
        def metrics(self, _): return {}
        async def broadcast(self, _, data): self.messages.append(json.loads(data))

    async def until(predicate):
        async with asyncio.timeout(2):
            while not predicate(): await asyncio.sleep(.005)

    manager = Manager()
    settings = types.SimpleNamespace(quality=70, show_cursor=True, fps=30, session_name='synthetic')
    with patch('fast_capture.CapturePipeline', Pipeline), patch('fast_capture.META_INTERVAL', .025), \
            patch('fast_capture.CAPTURE_RETRY', .02):
        task = asyncio.create_task(capture_loop(1, {}, manager, settings))
        try:
            await until(lambda: len(manager.messages) >= 2)
            assert all(m['capture_age_ms'] is None and m['stream_seq'] == 0
                       for m in manager.messages)
            Pipeline.fail = False
            await until(lambda: manager.messages[-1]['stream_seq'] == 1)
            await until(lambda: manager.messages[-1]['fps'] == 0)
            healthy = manager.messages[-1]
            assert healthy['stream_epoch'] == 1 and healthy['capture_age_ms'] < 100
            assert healthy['frozen'] is False
            # A static desktop continues to refresh capture health, without frames.
            before = len(manager.messages)
            await until(lambda: len(manager.messages) >= before + 3)
            assert manager.messages[-1]['stream_seq'] == 1
            assert manager.messages[-1]['capture_age_ms'] < 100
            Pipeline.fail = True
            before = len(manager.messages)
            await until(lambda: len(manager.messages) >= before + 5)
            assert manager.messages[-1]['capture_age_ms'] > 80
            assert manager.messages[-1]['stream_seq'] == 1
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    assert Pipeline.closed and not CAPTURE_TASKS
    print('PASS: independent metadata survives capture errors, static capture stays healthy, age grows during failure, heartbeat and worker clean up.')


asyncio.run(check_capture_heartbeat())
