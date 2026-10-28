@echo off
setlocal
if not defined CLASSTREAM_HOME set "CLASSTREAM_HOME=%~dp0"
cd /d "%~dp0"
if not exist "%CLASSTREAM_HOME%\.venv\Scripts\python.exe" goto install
if not exist "%CLASSTREAM_HOME%\runtime\data\classtream.db" goto install
if exist "%CLASSTREAM_HOME%\runtime\password-required" goto install
"%CLASSTREAM_HOME%\.venv\Scripts\python.exe" lan.py launch --home "%CLASSTREAM_HOME%" --open-browser
if errorlevel 1 pause
exit /b
:install
echo First-time setup is required. Starting install.cmd...
call "%~dp0install.cmd"
