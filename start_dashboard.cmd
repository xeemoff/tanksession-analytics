@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 goto use_python
py -3 "%~dp0tools\launch_dashboard.py" %*
goto finished
:use_python
python "%~dp0tools\launch_dashboard.py" %*
:finished
if errorlevel 1 (
  echo Install Python 3.9+ and see START_HERE_RU.md for launch options.
  pause
)
endlocal
