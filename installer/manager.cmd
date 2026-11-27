@echo off
setlocal
powershell.exe -NoLogo -NoProfile -STA -ExecutionPolicy Bypass -File "%~dp0TankSession-Manager.ps1" %*
if errorlevel 1 pause
exit /b %ERRORLEVEL%
