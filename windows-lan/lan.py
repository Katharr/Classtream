"""Portable Windows LAN launcher. Uses only Python's standard library itself."""
import argparse
import hashlib
import getpass
import ipaddress
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import ssl
import subprocess
import sys
import time
import webbrowser
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parent
RUNTIME = ROOT / "runtime"
PUBLIC = RUNTIME / "student-setup"
CADDY = ROOT / "bin" / "caddy.exe"
CADDY_VERSION = "2.11.7"
# Checked against the publisher's SHA-512 release manifest before bundling.
CADDY_SHA256 = "5f93a9bd555f3aac9d33af2756ba14b3519d8cca4ffd55256bdaeab444c9db2a"


def configuration():
    cfg = json.loads((ROOT / "config.json").read_text("utf-8-sig"))
    cfg.setdefault("fps", 60)
    cfg.setdefault("mode", "http")
    cfg.setdefault("http_port", 8080)
    if cfg['mode'] not in ('http', 'https'):
        raise ValueError('mode must be http or https.')
    if type(cfg["fps"]) is not int or not 1 <= cfg["fps"] <= 60:
        raise ValueError("fps must be an integer from 1 to 60.")
    ip = ipaddress.ip_address(cfg["teacher_ip"])
    if ip.version != 4 or ip.is_loopback or ip.is_unspecified or ip.is_multicast:
        raise ValueError("teacher_ip must be this PC's LAN IPv4 address.")
    for key in ("http_port", "https_port", "backend_port"):
        if type(cfg[key]) is not int or not 1024 <= cfg[key] <= 65535:
            raise ValueError(f"{key} must be an integer from 1024 to 65535.")
    cfg['public_port'] = cfg[cfg['mode'] + '_port']
    if cfg['public_port'] == cfg['backend_port']:
        raise ValueError('Public and local teacher ports must differ.')
    cfg['public_url'] = f"{cfg['mode']}://{ip}:{cfg['public_port']}"
    cfg['teacher_url'] = f"http://127.0.0.1:{cfg['backend_port']}/?host=admin"
    return cfg


def caddy_environment():
    env = os.environ.copy()
    # Keep Caddy's generated configuration and credentials inside runtime/.
    env["XDG_DATA_HOME"] = str(RUNTIME / "xdg-data")
    env["XDG_CONFIG_HOME"] = str(RUNTIME / "xdg-config")
    env["APPDATA"] = str(RUNTIME / "appdata")
    return env


def prepare(cfg):
    (RUNTIME / "data").mkdir(parents=True, exist_ok=True)
    if cfg['mode'] == 'http':
        return None  # No reverse proxy, certificate or CA in the default mode.
    if not CADDY.is_file():
        raise RuntimeError('Missing bin/caddy.exe. Run install.cmd after choosing https mode.')
    digest = hashlib.sha256(CADDY.read_bytes()).hexdigest()
    if digest != CADDY_SHA256:
        raise RuntimeError("Caddy executable checksum mismatch; restore the original binary.")
    (RUNTIME / "data").mkdir(parents=True, exist_ok=True)
    storage = (RUNTIME / "caddy-data").as_posix()
    text = """{
    admin off
    persist_config off
    auto_https disable_redirects
    skip_install_trust
    storage file_system {
        root "%s"
    }
    servers {
        protocols h1 h2
    }
}

%s {
    bind %s
    tls internal
    reverse_proxy 127.0.0.1:%s
}
""" % (storage, cfg["public_url"], cfg["teacher_ip"], cfg["backend_port"])
    config_path = RUNTIME / "Caddyfile"
    config_path.write_text(text, "utf-8")
    subprocess.run([str(CADDY), "validate", "--config", str(config_path),
                    "--adapter", "caddyfile"], env=caddy_environment(), check=True,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return config_path


def root_certificate():
    return RUNTIME / "caddy-data" / "pki" / "authorities" / "local" / "root.crt"


def export_student_setup(cfg):
    if cfg['mode'] != 'https':
        raise RuntimeError('HTTP mode needs no student setup. Share ' + cfg['public_url'] + '/class')
    cert = root_certificate()
    if not cert.is_file():
        raise RuntimeError("CA certificate is not ready. Start the server first.")
    PUBLIC.mkdir(parents=True, exist_ok=True)
    shutil.copy2(cert, PUBLIC / "classroom-root.crt")
    script = ('@echo off\r\ncd /d "%~dp0"\r\n'
              'certutil -user -addstore Root "%~dp0classroom-root.crt"\r\n'
              'if errorlevel 1 (pause & exit /b 1)\r\n'
              'echo Certificate installed for the current Windows user.\r\n'
              'echo Restart your browser and open: ' + cfg["public_url"] + '/class\r\npause\r\n')
    (PUBLIC / "install-certificate.cmd").write_bytes(script.encode("ascii"))
    der = ssl.PEM_cert_to_DER_cert(cert.read_text("ascii"))
    fingerprint = hashlib.sha256(der).hexdigest().upper()
    (PUBLIC / "README.txt").write_text(
        "Classtream student setup / 学生机一次性设置\n\n"
        "请仅安装教师通过可信渠道提供的证书。\n"
        "双击 install-certificate.cmd，为当前 Windows 用户导入根证书；"
        "接受系统提示后，完全关闭并重新打开浏览器。\n"
        "Firefox 若仍提示证书错误，请在其证书设置中手动导入 classroom-root.crt。\n\n"
        f"学生入口：{cfg['public_url']}/class\n"
        f"证书 SHA-256：{fingerprint}\n\n"
        "同一学生机若换 Windows 登录用户，需要为新用户重新导入。\n"
        "卸载：运行 certmgr.msc，找到“受信任的根证书颁发机构”中"
        "与上述指纹匹配的证书并删除；不要删除其他证书。\n", "utf-8-sig")
    archive = RUNTIME / "student-setup.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
        for path in sorted(PUBLIC.iterdir()):
            if path.is_file():
                z.write(path, path.name)
    return archive


def wait_http(url, process, timeout=40, context=None):
    deadline = time.monotonic() + timeout
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
        *([urllib.request.HTTPSHandler(context=context)] if context else []))
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Server process exited ({process.returncode}). See runtime logs.")
        try:
            with opener.open(url, timeout=2) as r:
                if r.status == 200:
                    return
        except (OSError, urllib.error.URLError):
            time.sleep(0.25)
    raise RuntimeError(f"Startup timed out: {url}. See runtime logs.")


def check(cfg):
    context = ssl.create_default_context(cafile=str(root_certificate())) if cfg['mode'] == 'https' else None
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
        *([urllib.request.HTTPSHandler(context=context)] if context else []))
    with opener.open(cfg["public_url"] + "/api/status", timeout=5) as r:
        status = json.load(r)
    with opener.open(cfg["public_url"] + "/class", timeout=5) as r:
        html = r.read().decode("utf-8")
        assert "window.__CLASSTREAM_JOIN_TOKEN__=" in html
        assert r.headers.get("Cache-Control") == "no-store"
    for name in ("stream", "voice"):
        with opener.open(cfg["public_url"] + f"/static/js/{name}.js", timeout=5) as r:
            script = r.read().decode("utf-8")
            assert "'wss:' : 'ws:'" in script
            assert "`ws://${location.host}" not in script
    with opener.open(cfg['public_url'] + '/static/js/config.js', timeout=5) as r:
        assert 'createSessionId()' in r.read().decode('utf-8')
    if cfg['mode'] == 'http':
        assert 'window.__CLASSTREAM_VOICE_ENABLED__=false' in html
        req = urllib.request.Request(cfg['public_url'] + '/api/admin/login', data=b'{}',
                                     headers={'Content-Type': 'application/json'})
        try:
            opener.open(req, timeout=5).close()
            raise AssertionError('LAN admin login should be blocked.')
        except urllib.error.HTTPError as exc:
            assert exc.code == 403
    print('PASS: /class, HTTP-compatible UUID, WS/WSS scripts; ' +
          ('LAN admin blocked; no student certificates.' if cfg['mode'] == 'http' else 'TLS chain + IP SAN.'))
    print(f"Monitors: {status['monitors']}; active class: {bool(status['session_token'])}")
    print('A separate student device still needs a real viewing test.')


def assert_port_free(address, port):
    with socket.socket() as probe:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            probe.bind((address, port))
        except OSError as exc:
            code = getattr(exc, 'winerror', None) or exc.errno
            if code in (10049, 99):
                reason = 'The configured IP is not assigned to this PC (network/DHCP address changed).'
            elif code in (10048, 98):
                reason = 'Another process is already listening on this address/port.'
            elif code in (10013, 13):
                reason = 'Windows denied this bind; check reserved ports or security policy.'
            else:
                reason = str(exc)
            raise RuntimeError(f'Cannot bind {address}:{port}: {reason} [OS error {code}]') from exc


def refresh_network_if_needed(cfg):
    """Repair a changed DHCP address, without mistaking port conflicts for IP changes."""
    if os.name == 'nt':
        subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass',
                        '-File', str(ROOT / 'refresh-network.ps1')], check=True)
        return configuration()
    return cfg


def update_network_address(cfg, addresses):
    """Keep the existing connected adapter; switch only with one unambiguous replacement."""
    if cfg['teacher_ip'] in addresses or len(addresses) != 1:
        return cfg
    raw = json.loads((ROOT / 'config.json').read_text('utf-8-sig'))
    raw['teacher_ip'] = addresses[0]
    temporary = ROOT / 'config.json.tmp'
    temporary.write_text(json.dumps(raw, indent=2), 'utf-8')
    temporary.replace(ROOT / 'config.json')
    updated = configuration()
    ready = RUNTIME / 'ready.json'
    data = json.loads(ready.read_text('utf-8'))
    data['student_url'] = updated['public_url'] + '/class'
    temporary = RUNTIME / 'ready.json.tmp'
    temporary.write_text(json.dumps(data, indent=2), 'utf-8')
    temporary.replace(ready)
    print('NETWORK CHANGED: Student: ' + data['student_url'], flush=True)
    return updated


def serve(cfg):
    os.environ["CLASSTREAM_DATA"] = str(RUNTIME / "data")
    from compat import create_application
    import uvicorn
    application = create_application(cfg['public_url'], fps=cfg['fps'], teacher_url=cfg['teacher_url'])
    config = uvicorn.Config(application, proxy_headers=(cfg['mode'] == 'https'),
                            forwarded_allow_ips='127.0.0.1', access_log=False, log_level='warning',
                            ws_per_message_deflate=False)
    addresses = [('127.0.0.1', cfg['backend_port'])]
    if cfg['mode'] == 'http':
        addresses.append(('0.0.0.0', cfg['http_port']))
    sockets = []
    try:
        for address in addresses:
            listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sockets.append(listener)
            if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            listener.bind(address)
        uvicorn.Server(config).run(sockets=sockets)
    finally:
        for listener in sockets:
            listener.close()


def start(cfg, open_browser=False):
    from windows_job import ProcessJob
    if (RUNTIME / 'password-required').exists():
        raise RuntimeError('First-time password setup is incomplete. Run install.cmd before starting.')
    cfg = refresh_network_if_needed(cfg)
    config_path = prepare(cfg)
    assert_port_free("127.0.0.1", cfg["backend_port"])
    assert_port_free('0.0.0.0' if cfg['mode'] == 'http' else cfg['teacher_ip'], cfg['public_port'])
    stop_request = RUNTIME / "stop.request"
    stop_request.unlink(missing_ok=True)
    children = []
    job = ProcessJob()
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        with (RUNTIME / "backend.log").open("a", encoding="utf-8") as backend_log, \
             (RUNTIME / "caddy.log").open("a", encoding="utf-8") as caddy_log:
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"
            env["PYTHONUNBUFFERED"] = "1"
            backend = subprocess.Popen([sys.executable, str(ROOT / "lan.py"), "serve"],
                cwd=ROOT, env=env, stdout=backend_log, stderr=subprocess.STDOUT,
                creationflags=flags)
            children.append(backend)
            job.add(backend)
            wait_http(f"http://127.0.0.1:{cfg['backend_port']}/api/status", backend)
            if cfg['mode'] == 'http':
                wait_http(cfg['public_url'] + '/api/status', backend)
            else:
                start_https(cfg, config_path, children, job, caddy_log, flags)
            (RUNTIME / 'launcher.pid').write_text(str(os.getpid()), 'ascii')
            (RUNTIME / 'ready.json').write_text(json.dumps({
                'mode': cfg['mode'], 'student_url': cfg['public_url'] + '/class',
                'teacher_url': cfg['teacher_url'], 'pid': os.getpid()}, indent=2), 'utf-8')
            print(f"\nREADY\nTeacher: {cfg['teacher_url']}")
            print(f"Student: {cfg['public_url']}/class")
            print('HTTP: no student installation; microphone disabled.' if cfg['mode'] == 'http'
                  else f"Student certificate package: {RUNTIME / 'student-setup.zip'}")
            print('Keep this window open. Ctrl+C or stop.cmd stops the service.', flush=True)
            if open_browser:
                webbrowser.open(cfg['teacher_url'])
            if cfg['mode'] == 'http' and os.name == 'nt':
                (RUNTIME / 'network-addresses.json').unlink(missing_ok=True)
                watcher = subprocess.Popen(['powershell.exe', '-NoProfile', '-ExecutionPolicy',
                    'Bypass', '-File', str(ROOT / 'refresh-network.ps1'), '-Watch'],
                    cwd=ROOT, stdout=backend_log, stderr=subprocess.STDOUT, creationflags=flags)
                children.append(watcher)
                job.add(watcher)
            while True:
                snapshot = RUNTIME / 'network-addresses.json'
                if cfg['mode'] == 'http' and snapshot.exists():
                    try:
                        addresses = json.loads(snapshot.read_text('utf-8-sig'))
                        cfg = update_network_address(cfg, addresses)
                    except (OSError, ValueError):
                        pass  # Retry a transient file read on the next iteration.
                if stop_request.exists():
                    try:
                        stop_request.unlink()
                    except PermissionError:
                        pass  # A scanner/another stop invocation may briefly hold the marker.
                    print("Stop requested.", flush=True)
                    return
                for child in children:
                    if child.poll() is not None:
                        raise RuntimeError("A server exited. See runtime logs; both servers will stop.")
                time.sleep(0.5)
    finally:
        try:
            for child in reversed(children):
                if child.poll() is None:
                    child.terminate()
                    try:
                        child.wait(timeout=8)
                    except subprocess.TimeoutExpired:
                        child.kill()
                        child.wait(timeout=5)
        finally:
            job.close()
            # A transient Windows file lock must never prevent child cleanup.
            for name in ('ready.json', 'launcher.pid'):
                for attempt in range(10):
                    try:
                        (RUNTIME / name).unlink(missing_ok=True)
                        break
                    except OSError as exc:
                        if attempt == 9:
                            print(f'Could not remove stale marker {name}: {exc}', flush=True)
                        else:
                            time.sleep(0.05)


def start_https(cfg, config_path, children, job, caddy_log, flags):
    caddy = subprocess.Popen([str(CADDY), "run", "--config", str(config_path),
                "--adapter", "caddyfile"], cwd=ROOT, env=caddy_environment(),
                stdout=caddy_log, stderr=subprocess.STDOUT, creationflags=flags)
    children.append(caddy)
    job.add(caddy)
    deadline = time.monotonic() + 20
    while not root_certificate().is_file():
        if caddy.poll() is not None or time.monotonic() > deadline:
            raise RuntimeError('Caddy did not generate its CA. See runtime/caddy.log.')
        time.sleep(0.2)
    context = ssl.create_default_context(cafile=str(root_certificate()))
    wait_http(cfg['public_url'] + '/api/status', caddy, context=context)
    export_student_setup(cfg)


def password():
    os.environ['CLASSTREAM_DATA'] = str(RUNTIME / 'data')
    from app import database
    if (RUNTIME / 'ready.json').exists():
        raise RuntimeError('Stop the service before changing the password.')
    database.init_db()
    database.create_admin('admin', 'admin123')
    username = input('Username [admin]: ').strip() or 'admin'
    if not database.admin_exists(username):
        raise ValueError('Unknown administrator.')
    value = getpass.getpass('New password (8+ characters): ')
    if len(value) < 8 or value != getpass.getpass('Repeat new password: '):
        raise ValueError('Passwords do not match or are shorter than 8 characters.')
    database.update_password(username, value)
    print('Password updated. Start the service and log in with the new password.')


def import_data(source):
    source = Path(source).expanduser().resolve()
    target = RUNTIME / "data"
    db = source / "classtream.db"
    if not db.is_file():
        raise RuntimeError(f"No classtream.db in {source}.")
    if (target / "classtream.db").exists():
        raise RuntimeError("Target database already exists. Import only into a fresh runtime/data directory.")
    target.mkdir(parents=True, exist_ok=True)
    # SQLite's backup API includes committed WAL contents; raw file copies may not.
    with sqlite3.connect(db.as_uri() + "?mode=ro", uri=True) as original, \
         sqlite3.connect(target / "classtream.db") as backup:
        original.backup(backup)
    if (source / "uploads").is_dir():
        shutil.copytree(source / "uploads", target / "uploads", dirs_exist_ok=True)
    print(f"Copied data to {target}. Original data was retained.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["start", "stop", "serve", "check", "prepare", "export-students", "import-data", 'password', 'open-teacher'])
    parser.add_argument("--source", help="Existing Classtream data directory for import-data")
    parser.add_argument('--open-browser', action='store_true')
    args = parser.parse_args()
    cfg = configuration()
    if args.command == "stop":
        RUNTIME.mkdir(parents=True, exist_ok=True)
        temporary = RUNTIME / f'stop.{os.getpid()}.tmp'
        temporary.write_text('stop', 'ascii')
        temporary.replace(RUNTIME / 'stop.request')
        print("Stop requested. The launcher will stop both servers within a few seconds.")
    elif args.command == "import-data":
        if not args.source:
            parser.error("import-data requires --source")
        import_data(args.source)
    elif args.command == "prepare":
        print(prepare(cfg))
    elif args.command == "export-students":
        print(export_student_setup(cfg))
    elif args.command == 'password':
        password()
    elif args.command == 'open-teacher':
        webbrowser.open(cfg['teacher_url'])
    elif args.command == 'start':
        start(cfg, open_browser=args.open_browser)
    else:
        {"start": start, "serve": serve, "check": check}[args.command](cfg)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped.")
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
