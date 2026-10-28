"""Build a clean classroom ZIP using only the Python standard library."""
from pathlib import Path
import hashlib
import json
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "windows-lan"
FILES = (
    "compat.py", "classroom_ui.py", "classroom.css", "classroom.js", "classroom-errors.js", "teacher-shortcuts.js", "teacher_hotkeys.py", "lan.py", "windows_job.py", "fast_capture.py", "stream_transport.py", "stream-client.js", "config.json",
    "requirements.txt", "requirements-lock.txt", "setup.cmd", "start.cmd",
    "stop.cmd", "check.cmd", "allow-firewall.cmd", "allow-firewall.ps1",
    "README.md", "先读我.txt", "LICENSE", "browser-compat.js", "install.cmd",
    "install.ps1", "password.cmd", "refresh-network.ps1", "教师端说明.md",
    "学生端说明.md", "真机验收.md", "bin/CADDY-LICENSE.txt",
    "bin/CADDY-README.md", "bin/CADDY-VERIFICATION.txt",
)
DEFAULTS = dict(mode="http", teacher_ip="192.0.2.1", http_port=8080,
                https_port=8443, backend_port=8000, fps=30)


def build():
    # Never enumerate a live deployment: only these reviewed files can ship.
    payloads = {}
    for name in FILES:
        path = SOURCE / name
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"Missing file or unsupported symlink: {path}")
        data = (json.dumps(DEFAULTS, indent=2) + "\n").encode("utf-8") \
            if name == "config.json" else path.read_bytes()
        # Git's Windows line-ending settings must not break Windows entry points.
        if path.suffix in (".cmd", ".ps1"):
            data = data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
        if any(marker in data for marker in (b"-----BEGIN PRIVATE KEY-----",
                                             b"-----BEGIN RSA PRIVATE KEY-----",
                                             b"-----BEGIN EC PRIVATE KEY-----")):
            raise ValueError(f"Private key found in release file: {name}")
        payloads["Classtream-LAN/" + name] = data

    destination = ROOT / "dist"
    destination.mkdir(exist_ok=True)
    archive = destination / "Classtream-LAN-Share.zip"
    # A fixed timestamp and order make rebuilds reproducible on the same runtime.
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for name, data in sorted(payloads.items()):
            entry = zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o100644 << 16
            z.writestr(entry, data, compresslevel=6)
    with zipfile.ZipFile(archive) as z:
        if z.testzip() is not None or set(z.namelist()) != set(payloads):
            raise ValueError("Archive integrity or manifest verification failed")
        if json.loads(z.read("Classtream-LAN/config.json")) != DEFAULTS:
            raise ValueError("Archive default configuration verification failed")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (destination / "SHA256SUMS.txt").write_text(
        f"{digest}  {archive.name}\n", encoding="ascii")
    print(f"Built {archive}: {len(payloads)} files, {archive.stat().st_size:,} bytes")
    print(f"SHA-256: {digest}")


if __name__ == "__main__":
    build()
