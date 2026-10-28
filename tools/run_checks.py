"""Run repeatable checks with isolated data; optionally exercise Edge and a synthetic server."""
import argparse
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
PYTHON_CHECKS = (
    'verify_startup_recovery.py', 'verify_deployment_layout.py',
    'verify_windows_adapter.py', 'verify_fast_capture.py',
    'verify_stream_transport.py', 'verify_student_nicknames.py', 'verify_discussion.py',
)
BROWSER_CHECKS = (
    'verify_classroom_ui.cjs', 'verify_stream_browser.cjs', 'verify_discussion_browser.cjs',
    'verify_screen_pan.cjs', 'verify_teacher_shortcuts.cjs', 'verify_stream_recovery.cjs',
)


def main(suite='core'):
    env = os.environ.copy()
    env.pop('CLASSTREAM_HOME', None)
    env.pop('CLASSTREAM_DATA', None)
    env['PYTHONIOENCODING'] = 'utf-8'
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    env['PYTHONPATH'] = os.pathsep.join(filter(None, (str(ROOT / '.dev-deps'), env.get('PYTHONPATH'))))
    output = ROOT / '.artifacts'
    (output / 'browser').mkdir(parents=True, exist_ok=True)

    def run(command):
        print('CHECK ' + ' '.join(map(str, command)), flush=True)
        subprocess.run(list(map(str, command)), cwd=ROOT, env=env, check=True)

    if suite in ('core', 'all'):
        for check in PYTHON_CHECKS:
            run([sys.executable, '-B', ROOT / 'tests' / check])
    node = shutil.which('node')
    if not node and suite != 'stress':
        raise RuntimeError('Node.js is required for browser-script checks')
    if suite in ('core', 'all'):
        run([node, ROOT / 'tests/verify_stream_health.cjs'])
    if suite in ('stress', 'all'):
        run([sys.executable, '-B', ROOT / 'tools/benchmark_stream.py'])
    if suite in ('browser', 'all'):
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        for check in BROWSER_CHECKS:
            # Each isolated server gets a free port, avoiding Windows TIME_WAIT reuse.
            with socket.socket() as probe:
                if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
                    probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                probe.bind(('127.0.0.1', 0))
                port = probe.getsockname()[1]
            env['CLASSTREAM_TEST_PORT'] = str(port)
            env['CLASSTREAM_TEST_URL'] = f'http://127.0.0.1:{port}'
            with (output / 'fixture.log').open('w', encoding='utf-8') as log:
                server = subprocess.Popen([sys.executable, '-B', str(ROOT / 'tools/stream_fixture.py')],
                    cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
                try:
                    deadline = time.monotonic() + 20
                    while True:
                        if server.poll() is not None or time.monotonic() > deadline:
                            raise RuntimeError('Synthetic server failed; see .artifacts/fixture.log')
                        try:
                            with opener.open(env['CLASSTREAM_TEST_URL'] + '/api/status', timeout=1):
                                break
                        except OSError:
                            time.sleep(.2)
                    run([node, ROOT / 'tests' / check])
                finally:
                    server.terminate()
                    try:
                        server.wait(timeout=8)
                    except subprocess.TimeoutExpired:
                        server.kill()
                        server.wait(timeout=5)
    print('PASS: requested checks complete; artifacts are in .artifacts/', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite', choices=('core', 'browser', 'stress', 'all'), default='core')
    options = parser.parse_args()
    main(suite=options.suite)
