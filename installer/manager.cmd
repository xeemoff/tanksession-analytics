@echo off
setlocal DisableDelayedExpansion
powershell.exe -NoLogo -NoProfile -STA -ExecutionPolicy Bypass -File "%~dp0Start-TankSession.ps1" %*
set "TANKSESSION_EXIT=%ERRORLEVEL%"
if not "%TANKSESSION_EXIT%"=="0" pause
exit /b %TANKSESSION_EXIT%
