"""Check the actual release assets, source provenance and strict package separation."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from build_windows_share import DEFAULTS, FILES
from build_offline_dependencies import INSTALLERS


def verify(directory, version):
    project = directory / f'Classtream-LAN-{version}-Win64.zip'
    dependencies = directory / 'Classtream-Dependencies-Win64-Py314.zip'
    for path in (project, dependencies):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        assert path.with_suffix('.zip.sha256').read_text('ascii').strip() == f'{digest}  {path.name}'
    prefix = 'Classtream-LAN/'
    expected = {prefix + 'windows-lan/' + name for name in FILES}
    expected |= {prefix + name for name in ('start.cmd', 'LICENSE', '先读我.txt', 'release.json')}
    with zipfile.ZipFile(project) as archive:
        assert archive.testzip() is None
        assert len(archive.namelist()) == len(expected) and set(archive.namelist()) == expected
        for name in archive.namelist():
            assert not any(part in ('offline', '.venv', 'runtime', 'teacher') for part in Path(name).parts)
            assert Path(name).suffix.lower() not in ('.zip', '.whl', '.exe', '.db', '.key', '.pem')
        assert json.loads(archive.read(prefix + 'windows-lan/config.json')) == DEFAULTS
        for name in FILES:
            if name == 'config.json':
                continue
            actual = archive.read(prefix + 'windows-lan/' + name)
            source = (ROOT / 'windows-lan' / name).read_bytes()
            if Path(name).suffix in ('.cmd', '.ps1'):
                source = source.replace(b'\r\n', b'\n').replace(b'\n', b'\r\n')
                assert b'\n' not in actual.replace(b'\r\n', b'')
            assert actual == source, name
        assert archive.read(prefix + '先读我.txt') == (directory / 'READ-ME-FIRST.txt').read_bytes()
        readme = archive.read(prefix + '先读我.txt').decode('utf-8-sig')
        assert version in readme and '首次启动默认联网下载' in readme
        metadata = json.loads(archive.read(prefix + 'release.json'))
        assert metadata == dict(version=version, source_commit=subprocess.check_output(
            ['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
            default_install='online', dependencies_bundled=False)
    with zipfile.ZipFile(dependencies) as archive:
        assert archive.testzip() is None
        manifest = json.loads(archive.read('offline/manifest.json'))
        entries = manifest['files']
        names = ['offline/' + entry['path'] for entry in entries]
        assert len(names) == len(set(names))
        assert len(archive.namelist()) == len(names) + 3
        assert set(archive.namelist()) == set(names) | {'offline/manifest.json', 'install.ps1', '离线依赖使用说明.txt'}
        for entry in entries:
            assert hashlib.sha256(archive.read('offline/' + entry['path'])).hexdigest() == entry['sha256']
        assert archive.read('offline/requirements-lock.txt') == (ROOT / 'windows-lan/requirements-lock.txt').read_bytes()
        for name, (algorithm, digest) in INSTALLERS.items():
            assert hashlib.new(algorithm, archive.read('offline/installers/' + name)).hexdigest() == digest
        script = (ROOT / 'windows-lan/install.ps1').read_bytes().replace(b'\r\n', b'\n').replace(b'\n', b'\r\n')
        assert archive.read('install.ps1') == script
    print('PASS: clean source-only project, matching readme/commit, separate verified offline dependencies')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--version', required=True)
    options = parser.parse_args()
    verify(options.directory, options.version)
