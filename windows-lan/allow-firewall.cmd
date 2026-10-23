@echo off
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0allow-firewall.ps1"
if errorlevel 1 (
  echo Firewall setup failed or elevation was canceled. See README.md.
) else (
  echo Firewall setup completed. The configured classroom port is allowed from the local subnet.
)
pause
