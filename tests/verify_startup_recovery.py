"""Real Windows processes/ports; all fixtures use temporary state and random ports."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
CODE = ROOT / 'windows-lan'
sys.path.insert(0, str(CODE))
from startup_lock import StartupLock


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


with tempfile.TemporaryDirectory(prefix='Classtream recovery 中文 ') as folder:
    base = Path(folder)
    home = base / 'state'
    code = base / 'code'
    code.mkdir()
    (home / 'runtime').mkdir(parents=True)
    ports = [free_port(), free_port()]
    while ports[0] == ports[1]:
        ports[1] = free_port()
    (home / 'config.json').write_text(json.dumps(dict(
        mode='http', backend_port=ports[0], http_port=ports[1])), encoding='utf-8')
    fixture = code / 'lan.py'
    fixture.write_text('''
import socket, sys, time
sockets = []
for port in sys.argv[sys.argv.index('--ports')+1:]:
    sock = socket.socket()
    sock.bind(('127.0.0.1', int(port)))
    sock.listen()
    sockets.append(sock)
print('READY', flush=True)
time.sleep(120)
''', encoding='utf-8')

    def spawn(deployment):
        process = subprocess.Popen([sys.executable, str(fixture), 'serve', '--home',
            str(deployment), '--ports', *map(str, ports)], stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True)
        assert process.stdout.readline().strip() == 'READY'
        return process

    def recover(success, code_root=code):
        command = ['powershell.exe', '-NoProfile', '-ExecutionPolicy',
            'Bypass', '-File', str(CODE / 'recover-service.ps1'),
            '-DeploymentRoot', str(home)]
        if code_root is not None:
            command += ['-CodeRoot', str(code_root)]
        result = subprocess.run(command,
            capture_output=True, text=True, timeout=40)
        assert (result.returncode == 0) == success, result.stdout + result.stderr
        return result

    # A different deployment using the same code and ports must survive.
    other = spawn(base / 'other home')
    try:
        (home / 'runtime' / 'launcher.pid').write_text(str(other.pid), encoding='ascii')
        result = recover(False)
        assert 'another application' in result.stderr and other.poll() is None
        assert (home / 'runtime' / 'launcher.pid').exists()
    finally:
        other.terminate()
        other.wait(timeout=5)

    # An unresponsive owned server must be forcibly cleaned, including its sockets.
    owned = spawn(home)
    try:
        result = recover(True)
        owned.wait(timeout=5)
        assert 'Cleaning residual' in result.stdout
        assert not (home / 'runtime' / 'launcher.pid').exists()
        assert not (home / 'runtime' / 'stop.request').exists()
        recover(True)  # Repeated cleanup with no server is harmless.
        recover(True, code_root=None)  # Windows PowerShell -File default path resolution.
    finally:
        if owned.poll() is None:
            owned.terminate()
            owned.wait(timeout=5)

    # Simultaneous starts cannot clean up each other's half-started services.
    lock_path = home / 'runtime' / 'startup.lock'
    with StartupLock(lock_path):
        env = os.environ.copy()
        env['PYTHONPATH'] = str(CODE)
        result = subprocess.run([sys.executable, '-c',
            'from pathlib import Path; from startup_lock import StartupLock; '
            'import sys; StartupLock(Path(sys.argv[1]))', str(lock_path)],
            env=env, capture_output=True, text=True)
        assert result.returncode != 0 and 'already in progress' in result.stderr
    with StartupLock(lock_path):
        pass
print('PASS: foreign deployment protected; residual listener killed; repeated cleanup; startup lock')
