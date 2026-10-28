"""Generate the workspace's sole daily entry point without copying application code."""
import argparse
import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def create(workspace):
    workspace = workspace.resolve()
    code = os.path.relpath(REPO / 'windows-lan', workspace).replace('/', '\\')
    if any(char in code for char in ('"', '%', '\n', '\r')):
        raise ValueError('Unsupported characters in the relative repository path')
    if not (workspace / 'teacher' / 'config.json').is_file():
        raise ValueError('Existing teacher/config.json is required; no machine data is generated')
    source = f'''@echo off
setlocal
set "CLASSTREAM_HOME=%~dp0teacher"
set "CLASSTREAM_CODE=%~dp0{code}"
cd /d "%~dp0"
if not exist "%CLASSTREAM_HOME%\\config.json" (
  echo ERROR: Missing teacher\\config.json.
  goto failed
)
if not exist "%CLASSTREAM_HOME%\\.venv\\Scripts\\python.exe" goto install
if not exist "%CLASSTREAM_HOME%\\runtime\\data\\classtream.db" goto install
if exist "%CLASSTREAM_HOME%\\runtime\\password-required" goto install
goto launch
:install
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%CLASSTREAM_CODE%\\install.ps1" -NoStart
if errorlevel 1 goto failed
:launch
"%CLASSTREAM_HOME%\\.venv\\Scripts\\python.exe" "%CLASSTREAM_CODE%\\lan.py" launch --home "%CLASSTREAM_HOME%" --open-browser
if errorlevel 1 goto failed
exit /b 0
:failed
echo Startup failed. See the message above and teacher\\runtime\\backend.log.
pause
exit /b 1
'''
    destination = workspace / 'start.cmd'
    destination.write_bytes(source.replace('\n', '\r\n').encode('ascii'))
    print(f'Created {destination}; application code stays in {REPO / "windows-lan"}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, default=REPO.parent)
    create(parser.parse_args().workspace)
