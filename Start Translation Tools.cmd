@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if not errorlevel 1 (
    py -3 TranslationTools.py
    if errorlevel 1 pause
    exit /b
)
where python >nul 2>nul
if not errorlevel 1 (
    python TranslationTools.py
    if errorlevel 1 pause
    exit /b
)
echo Python 3.10 or newer with Tcl/Tk is required.
echo Install it from https://www.python.org/downloads/ and then try again.
pause
