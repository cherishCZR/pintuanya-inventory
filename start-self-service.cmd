@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Run install-windows.cmd first, then start this file again.
    if not defined CI pause
    exit /b 2
)
".venv\Scripts\python.exe" "scripts\launch.py"
set "PINTUANYA_LAUNCH_EXIT=%ERRORLEVEL%"
if not defined CI pause
exit /b %PINTUANYA_LAUNCH_EXIT%
