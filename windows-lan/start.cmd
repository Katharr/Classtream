@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" goto install
if not exist "runtime\data\classtream.db" goto install
if exist "runtime\password-required" goto install
".venv\Scripts\python.exe" lan.py start --open-browser
if errorlevel 1 pause
exit /b
:install
echo First-time setup is required. Starting install.cmd...
call "%~dp0install.cmd"
