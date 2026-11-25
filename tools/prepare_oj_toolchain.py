"""Install a private read-only-for-the-sandbox copy of an MSYS2 UCRT64 GCC toolchain."""
import argparse
import os
from pathlib import Path
import shutil
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
CODE = ROOT / 'windows-lan' if (ROOT / 'windows-lan').is_dir() else ROOT
REQUIRED = ('bin/g++.exe', 'bin/ld.exe', 'include', 'lib/gcc', 'x86_64-w64-mingw32/bin/as.exe')


def prepare(deployment, source):
    if os.name != 'nt':
        raise ValueError('The local C++17 judge requires Windows.')
    if any(not (source / name).exists() for name in REQUIRED):
        raise ValueError('Select the existing MSYS2 UCRT64 root, for example C:\\msys64\\ucrt64.')
    target = deployment / 'bin' / 'oj-toolchain'
    if target.resolve() != target or target == source or target.is_relative_to(source):
        raise ValueError('Select a separate deployment home without a redirected toolchain directory.')
    if target.exists():
        raise ValueError(f'{target} already exists. Move it aside before installing a replacement.')
    sys.path.insert(0, str(CODE))
    from oj_runner import COMPILER_PROFILE
    from oj_sandbox import WindowsSandbox

    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.oj-prepare-', dir=target.parent) as temporary:
        staging = Path(temporary) / 'oj-toolchain'
        staging.mkdir()
        for directory in ('bin', 'include', 'lib', 'x86_64-w64-mingw32'):
            shutil.copytree(source / directory, staging / directory)
        sandbox = WindowsSandbox()
        with sandbox.profile(COMPILER_PROFILE) as (_, sid):
            sandbox.grant(staging, sid, 'RX')
            sandbox.restrict_profile(sid)
        staging.rename(target)
    print(f'Installed the OJ toolchain at {target}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home', type=Path, required=True, help='Classtream deployment directory')
    parser.add_argument('--msys-ucrt64', type=Path, default=Path(r'C:\msys64\ucrt64'))
    args = parser.parse_args()
    try:
        prepare(args.home.resolve(), args.msys_ucrt64.resolve())
    except (OSError, ValueError) as error:
        parser.exit(1, f'{error}\n')
