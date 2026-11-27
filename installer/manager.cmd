@echo off
setlocal
powershell.exe -NoLogo -NoProfile -STA -ExecutionPolicy Bypass -File "%~dp0TankSession-Manager.ps1" %*
set "TANKSESSION_EXIT=%ERRORLEVEL%"
if not "%TANKSESSION_EXIT%"=="0" pause
exit /b %TANKSESSION_EXIT%
