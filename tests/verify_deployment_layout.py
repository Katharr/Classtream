"""Verify code/state separation without touching the live classroom."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
CODE = ROOT / 'windows-lan'


def probe(home):
    env = os.environ.copy()
    env.pop('CLASSTREAM_HOME', None)
    if home is not None:
        env['CLASSTREAM_HOME'] = str(home)
    result = subprocess.run([sys.executable, '-c',
        'import json, lan; print(json.dumps([str(lan.ROOT), str(lan.HOME), '
        'str(lan.RUNTIME), str(lan.CADDY), lan.configuration()["teacher_ip"]]))'],
        cwd=CODE, env=env, capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


with tempfile.TemporaryDirectory(prefix='Classtream home 中文 ') as folder:
    home = Path(folder)
    cfg = json.loads((CODE / 'config.json').read_text('utf-8-sig'))
    cfg['teacher_ip'] = '192.0.2.77'
    config = home / 'config.json'
    config.write_text(json.dumps(cfg), encoding='utf-8')
    code, state, runtime, caddy, ip = probe(home)
    assert Path(code) == CODE and Path(state) == home
    assert Path(runtime) == home / 'runtime'
    assert Path(caddy) == home / 'bin' / 'caddy.exe' and ip == '192.0.2.77'

    env = os.environ.copy()
    env['CLASSTREAM_HOME'] = str(home)
    env['CLASSTREAM_DATA'] = str(home / 'runtime' / 'data')
    # Exercise the actual adapter: private configuration must come from home,
    # while HTTP assets must come directly from the canonical source tree.
    subprocess.run([sys.executable, '-c', '''
from compat import create_application
from fastapi.testclient import TestClient
client = TestClient(create_application('http://192.0.2.99:8080'))
assert client.get('/lan-info').json()['student_url'] == 'http://192.0.2.77:8080/class'
from pathlib import Path
assert client.get('/classroom-ui/classroom.js').content == Path('classroom.js').read_bytes()
'''], cwd=CODE, env=env, check=True)
    assert json.loads(config.read_text('utf-8')) == cfg

code, state, runtime, caddy, _ = probe(None)
assert Path(code) == Path(state) == CODE  # Portable installs retain their layout.
subprocess.run([sys.executable, str(ROOT / 'tools/build_windows_share.py')], check=True)
with zipfile.ZipFile(ROOT / 'dist/Classtream-LAN-Share.zip') as archive:
    names = archive.namelist()
    assert not any('/runtime/' in name or '/.venv/' in name or 'run_local' in name for name in names)
    assert b'CLASSTREAM_HOME' in archive.read('Classtream-LAN/lan.py')
print('PASS: separate home, source assets, portable fallback and clean release archive')
