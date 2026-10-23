import sys,types
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
