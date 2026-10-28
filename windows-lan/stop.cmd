@echo off
setlocal
if not defined CLASSTREAM_HOME set "CLASSTREAM_HOME=%~dp0"
cd /d "%~dp0"
if exist "%CLASSTREAM_HOME%\.venv\Scripts\python.exe" (
  "%CLASSTREAM_HOME%\.venv\Scripts\python.exe" lan.py stop
) else (
  python lan.py stop
)
pause
