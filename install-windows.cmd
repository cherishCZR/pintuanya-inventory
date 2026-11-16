@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" "scripts\install_windows.py"
    goto done
)
py -3.12 -c "import sys,struct; assert sys.version_info[:2]==(3,12) and struct.calcsize('P')==8" >nul 2>&1
if not errorlevel 1 (
    py -3.12 "scripts\install_windows.py"
    goto done
)
python -c "import sys,struct; assert sys.version_info[:2]==(3,12) and struct.calcsize('P')==8" >nul 2>&1
if not errorlevel 1 (
    python "scripts\install_windows.py"
    goto done
)
echo CPython 3.12 x64 was not found.
echo Install it from https://www.python.org/downloads/windows/ and run this file again.
set "PINTUANYA_BOOTSTRAP_EXIT=2"
goto finish
:done
set "PINTUANYA_BOOTSTRAP_EXIT=%ERRORLEVEL%"
:finish
if not defined CI pause
exit /b %PINTUANYA_BOOTSTRAP_EXIT%
