@echo off
setlocal
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install-TankSession.ps1" %*
set "TANKSESSION_EXIT=%ERRORLEVEL%"
pause
exit /b %TANKSESSION_EXIT%
