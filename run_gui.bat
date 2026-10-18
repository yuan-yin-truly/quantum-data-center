@echo off
rem ===========================================================================
rem  Chiplet Thermal Studio - double-click launcher
rem
rem  Just double-click this file. On a fresh clone it will find a Python,
rem  offer to install the three packages it needs, and start the GUI.
rem
rem  An optional design file can be passed in:
rem      run_gui.bat my_design.json
rem
rem  The console window that opens alongside the GUI carries the run log and
rem  any start-up errors. Minimise it if it is in the way; closing it closes
rem  the GUI.
rem ===========================================================================

setlocal EnableDelayedExpansion
cd /d "%~dp0"
title Chiplet Thermal Studio

set "VENV_PY=%~dp0.venv\Scripts\python.exe"
set "PY="

rem --- 1. A local .venv always wins, so a project install stays self-contained.
if exist "%VENV_PY%" (
    set "PY=%VENV_PY%"
    goto :have_python
)

rem --- 2. Otherwise ask the py launcher, then a plain python on PATH.
for /f "delims=" %%I in ('py -3 -c "import sys;print(sys.executable)" 2^>nul') do set "PY=%%I"
if not defined PY (
    for /f "delims=" %%I in ('python -c "import sys;print(sys.executable)" 2^>nul') do set "PY=%%I"
)

if not defined PY (
    echo.
    echo   No Python 3 was found on this computer.
    echo.
    echo   Install Python 3.10 or newer from https://www.python.org/downloads/
    echo   and tick "Add python.exe to PATH" in the installer, then run this
    echo   file again.
    echo.
    pause
    exit /b 1
)

:have_python
echo   Python: %PY%

rem --- 3. Check the three packages the GUI needs.
"%PY%" -c "import PySide6, numpy, matplotlib" >nul 2>&1
if not errorlevel 1 goto :launch

echo.
echo   This GUI needs PySide6, numpy and matplotlib, and at least one of them
echo   is missing from the Python above.
echo.
echo     [1]  Install them into a local .venv folder here  (recommended)
echo     [2]  Install them into that Python itself
echo     [3]  Cancel
echo.
choice /c 123 /n /m "   Choose 1, 2 or 3: "
set "ANSWER=%ERRORLEVEL%"
echo.

if "%ANSWER%"=="3" exit /b 1

if "%ANSWER%"=="1" (
    echo   Creating .venv ...
    "%PY%" -m venv ".venv"
    if errorlevel 1 (
        echo.
        echo   Could not create the virtual environment.
        pause
        exit /b 1
    )
    set "PY=%VENV_PY%"
)

echo   Installing the requirements. This takes a minute the first time ...
echo.
"%PY%" -m pip install --upgrade pip
"%PY%" -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo   The install failed. The pip output above says why.
    pause
    exit /b 1
)

"%PY%" -c "import PySide6, numpy, matplotlib" >nul 2>&1
if errorlevel 1 (
    echo.
    echo   The packages still will not import. The pip output above says why.
    pause
    exit /b 1
)
echo.
echo   Requirements installed.

:launch
echo   Starting Chiplet Thermal Studio ...
echo.
"%PY%" -m chiplet_gui %*
set "RC=%ERRORLEVEL%"

if not "%RC%"=="0" (
    echo.
    echo   The GUI exited with code %RC%. The message above says why.
    pause
)

exit /b %RC%
