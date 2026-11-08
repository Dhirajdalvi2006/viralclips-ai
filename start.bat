@echo off
setlocal EnableDelayedExpansion

REM ===================================================================
REM  VIRALCLIPS AI - start.bat
REM
REM  1. verify Python          4. start the background worker
REM  2. verify FFmpeg          5. start the API server
REM  3. free the API port      6. wait, report the URLs, open the browser
REM
REM  Each service records its own PID (data\worker.pid, data\api.pid)
REM  so stop.bat stops exactly these two processes and nothing else.
REM ===================================================================

cd /d "%~dp0"

set "VENV_PY=%~dp0.venv\Scripts\python.exe"
set "API_PORT=8799"
if not "%VIRALCLIPS_API_PORT%"=="" set "API_PORT=%VIRALCLIPS_API_PORT%"
set "API_URL=http://127.0.0.1:%API_PORT%"
set "LOGDIR=%~dp0data\logs"

echo(
echo  ==========================================================
echo    V I R A L C L I P S   A I
echo  ==========================================================
echo(

if not exist "%LOGDIR%" mkdir "%LOGDIR%"

REM --- 1. verify Python ------------------------------------------------
if not exist "%VENV_PY%" (
    echo  [X] The virtual environment is missing.
    echo      Expected: %VENV_PY%
    echo      Run setup.bat to rebuild it.
    goto :fail
)
for /f "tokens=2" %%v in ('"%VENV_PY%" --version 2^>nul') do set "PYVER=%%v"
echo  [1/6] Python           : !PYVER!

REM --- 2. verify FFmpeg ------------------------------------------------
set "FFMPEG_OK=0"
where ffmpeg >nul 2>&1 && set "FFMPEG_OK=1"
if "!FFMPEG_OK!"=="0" (
    if exist "%~dp0ffmpeg\bin\ffmpeg.exe" (
        set "PATH=%~dp0ffmpeg\bin;!PATH!"
        set "FFMPEG_OK=1"
    )
)
if "!FFMPEG_OK!"=="0" (
    echo  [X] FFmpeg was not found.
    echo      Install FFmpeg and add it to PATH, then run this again.
    goto :fail
)
for /f "tokens=3" %%v in ('ffmpeg -version 2^>nul ^| findstr /c:"ffmpeg version"') do echo  [2/6] FFmpeg          : %%v

REM --- 3. stop leftovers and free the port --------------------------------
echo  [3/6] Releasing the port and stopping any previous run...
"%VENV_PY%" -m viralclips_app.service_control stop >nul 2>&1
"%VENV_PY%" -m viralclips_app.service_control free-port !API_PORT! >nul 2>&1
REM The pause is taken with Python rather than "timeout": "timeout" needs
REM a real console and answers "Access is denied" in a non-interactive
REM session -- a scheduled task, a service, or a CI run -- which looks
REM like a startup failure when it is not.
"%VENV_PY%" -c "import time; time.sleep(1)" >nul 2>&1

REM --- 4/5. start the worker and the API -----------------------------------
REM The launcher is a Python helper so the services are started as
REM properly detached processes with their real PIDs recorded. That is
REM what lets stop.bat stop exactly these two and nothing else.
echo  [4/6] Starting the background worker...
"%VENV_PY%" -m viralclips_app.service_control start --services worker

echo  [5/6] Starting the API server...
"%VENV_PY%" -m viralclips_app.service_control start --services api

REM --- 6. wait until the API answers ---------------------------------------
echo  [6/6] Waiting for the API to become ready...
set "READY=0"
for /l %%i in (1,1,90) do (
    if "!READY!"=="0" (
        "%VENV_PY%" -c "import urllib.request; urllib.request.urlopen('%API_URL%/api/health',timeout=2)" >nul 2>&1 && set "READY=1"
        if "!READY!"=="0" "%VENV_PY%" -c "import time; time.sleep(1)" >nul 2>&1
    )
)
if "!READY!"=="0" (
    echo  [X] The API did not become ready in time.
    echo      Check "%LOGDIR%\api.out.log"
    goto :fail
)

echo  Ready.
echo(
echo  --------------------------------------------------------------
echo    Application:       %API_URL%
echo    API:               %API_URL%
echo    API documentation:  %API_URL%/docs
echo  --------------------------------------------------------------
echo(
echo    The background worker keeps processing while the browser is
echo    closed. Run stop.bat to shut everything down.
echo(

REM --- open the browser (best effort) --------------------------------------
REM Opening the browser is a convenience, not a requirement. In a
REM non-interactive session -- a scheduled task, a service, a CI run --
REM there is no desktop to reach and Windows answers "Access is
REM denied". The plain "start" command prints that refusal even when
REM its own output is redirected, so the launch goes through
REM PowerShell instead, where the failure is caught and discarded.
REM The URLs printed above are what the user needs either way.
powershell -NoProfile -Command "try { Start-Process '%API_URL%' -ErrorAction Stop } catch { }" >nul 2>&1
endlocal
exit /b 0

:fail
echo(
echo  Startup failed. See the messages above.
endlocal
exit /b 1
