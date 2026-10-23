@echo off
setlocal
call "%~dp0windows-lan\check.cmd"
exit /b %errorlevel%
