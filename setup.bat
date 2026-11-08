@echo off
setlocal EnableDelayedExpansion

REM ===================================================================
REM  VIRALCLIPS AI - setup.bat
REM
REM  One-time setup. Creates the virtual environment with Python 3.11,
REM  installs the application and its dependencies, and checks that
REM  FFmpeg is available. Safe to run more than once.
REM
REM  Usage:
REM    setup.bat            create the environment and install everything
REM    setup.bat --check    only report what is present, change nothing
REM
REM  This script never touches your data directory, your clips or your
REM  credential file. It only creates .venv and installs packages.
REM ===================================================================

cd /d "%~dp0"

set "VENV_PY=%~dp0.venv\Scripts\python.exe"
set "PYLAUNCHER=py"
set "CHECK_ONLY=0"
if /i "%~1"=="--check" set "CHECK_ONLY=1"

echo(
echo  ==========================================================
echo    V I R A L C L I P S   A I   -   S E T U P
echo  ==========================================================
echo(

REM --- 1. find a suitable Python -------------------------------------
echo  [1/5] Locating Python 3.11...

set "BASE_PY="
if exist "%VENV_PY%" (
    for /f "tokens=2" %%v in ('"%VENV_PY%" --version 2^>nul') do set "BASE_PY=%VENV_PY%"
    echo         using the existing virtual environment
)

if "!BASE_PY!"=="" (
    for %%v in (3.11 3) do (
        if "!BASE_PY!"=="" (
            for /f "tokens=2" %%p in ('py -%%v --version 2^>nul') do (
                if "!BASE_PY!"=="" set "BASE_PY=py -%%v"
            )
        )
    )
)

if "!BASE_PY!"=="" (
    for /f "tokens=2" %%p in ('python --version 2^>nul') do (
        set "BASE_PY=python"
    )
)

if "!BASE_PY!"=="" (
    echo  [X] No Python was found on this machine.
    echo      Install Python 3.11 from https://www.python.org/downloads/
    echo      and tick "Add python.exe to PATH" during the install.
    goto :fail
)

for /f "tokens=2" %%v in ('!BASE_PY! --version 2^>nul') do set "PYVER=%%v"
echo         Python !PYVER!  (!BASE_PY!)

REM --- 2. FFmpeg ------------------------------------------------------
echo  [2/5] Checking for FFmpeg...
set "FFMPEG_OK=0"
where ffmpeg >nul 2>&1 && set "FFMPEG_OK=1"
if "!FFMPEG_OK!"=="0" (
    if exist "%~dp0ffmpeg\bin\ffmpeg.exe" (
        set "PATH=%~dp0ffmpeg\bin;!PATH!"
        set "FFMPEG_OK=1"
        echo         using the bundled copy in .\ffmpeg\bin
    )
)
if "!FFMPEG_OK!"=="0" (
    echo  [X] FFmpeg was not found.
    echo      Install it from https://ffmpeg.org/download.html and add
    echo      its bin folder to PATH, then run setup.bat again.
    goto :fail
)
for /f "tokens=3" %%v in ('ffmpeg -version 2^>nul ^| findstr /c:"ffmpeg version"') do echo         %%v

if "!CHECK_ONLY!"=="1" (
    echo(
    echo  Check only. Nothing was changed.
    echo  Run setup.bat without --check to install the application.
    endlocal
    exit /b 0
)

REM --- 3. create the virtual environment ------------------------------
if exist "%VENV_PY%" (
    echo  [3/5] Rebuilding the virtual environment...
    rmdir /s /q "%~dp0.venv" >nul 2>&1
) else (
    echo  [3/5] Creating the virtual environment...
)
!BASE_PY! -m venv "%~dp0.venv"
if not exist "%VENV_PY%" (
    echo  [X] The virtual environment could not be created.
    goto :fail
)

REM --- 4. install the dependencies -------------------------------------
echo  [4/5] Installing dependencies. This can take several minutes...
"%VENV_PY%" -m pip install --upgrade pip setuptools wheel
if errorlevel 1 (
    echo  [X] Could not update pip.
    goto :fail
)
"%VENV_PY%" -m pip install -r "%~dp0requirements.txt"
if errorlevel 1 (
    echo  [X] Installing the requirements failed.
    goto :fail
)

REM --- 5. verify the installation --------------------------------------
echo  [5/5] Verifying the installation...
"%VENV_PY%" -c "import sys; sys.path.insert(0,'.'); import chopify, render_clips, providers.adapter, viralclips_app.main; print('IMPORTS OK')"
if errorlevel 1 (
    echo  [X] Some modules failed to import. See the message above.
    goto :fail
)
"%VENV_PY%" -c "import sys; sys.path.insert(0,'.'); from viralclips_app import config; config.ensure_dirs(); from viralclips_app.db import init_db; init_db(); print('DATABASE OK')"
if errorlevel 1 (
    echo  [X] The database could not be initialised.
    goto :fail
)

echo(
echo  ==========================================================
echo    Setup complete.
echo  ==========================================================
echo(
echo    Next:
echo      1. Add your AI provider key. See docs\PROVIDER_SETUP.md
echo      2. Run start.bat
echo      3. Open http://127.0.0.1:8799
echo(
endlocal
exit /b 0

:fail
echo(
echo  Setup failed. See the messages above.
endlocal
exit /b 1
