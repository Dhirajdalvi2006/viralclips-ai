@echo off
setlocal EnableDelayedExpansion

REM ===================================================================
REM  VIRALCLIPS AI - health-check.bat
REM  Verifies every runtime dependency and reports a clear verdict.
REM  Exits 0 when the application is healthy, 1 otherwise.
REM ===================================================================

cd /d "%~dp0"

set "VENV_PY=%~dp0.venv\Scripts\python.exe"
set "API_PORT=8799"
if not "%VIRALCLIPS_API_PORT%"=="" set "API_PORT=%VIRALCLIPS_API_PORT%"
set "API_URL=http://127.0.0.1:%API_PORT%"

set "FAILURES=0"

echo(
echo  ==========================================================
echo    V I R A L C L I P S   A I   -   HEALTH CHECK
echo  ==========================================================
echo(

REM --- Python -------------------------------------------------------------
if exist "%VENV_PY%" (
    for /f "tokens=2" %%v in ('"%VENV_PY%" --version 2^>nul') do set "PYVER=%%v"
    echo  [OK]   Python           !PYVER!
) else (
    echo  [FAIL] Python           the virtual environment is missing
    set "FAILURES=1"
)

REM --- FFmpeg -------------------------------------------------------------
where ffmpeg >nul 2>&1
if errorlevel 1 (
    if exist "%~dp0ffmpeg\bin\ffmpeg.exe" (
        set "PATH=%~dp0ffmpeg\bin;!PATH!"
    ) else (
        echo  [FAIL] FFmpeg           not found on PATH
        set "FAILURES=1"
    )
)
if not "!FAILURES!"=="1" (
    for /f "tokens=3" %%v in ('ffmpeg -version 2^>nul ^| findstr /c:"ffmpeg version"') do echo  [OK]   FFmpeg          %%v
)

REM --- imports ------------------------------------------------------------
if exist "%VENV_PY%" (
    "%VENV_PY%" -c "import sys; sys.path.insert(0,'.'); import chopify, projects, score_clips, render_clips, providers.adapter, viralclips_app.main; print('IMPORTS OK')" >"%TEMP%\vc_health.txt" 2>&1
    findstr /c:"IMPORTS OK" "%TEMP%\vc_health.txt" >nul && (
        echo  [OK]   Package imports  all modules import cleanly
    ) || (
        echo  [FAIL] Package imports  a module failed to import
        type "%TEMP%\vc_health.txt"
        set "FAILURES=1"
    )
)

REM --- AI provider --------------------------------------------------------
if exist "%VENV_PY%" (
    "%VENV_PY%" viralclips.py --provider-check >"%TEMP%\vc_provider.txt" 2>&1
    findstr /c:"\"ok\": true" "%TEMP%\vc_provider.txt" >nul && (
        echo  [OK]   AI provider      Groq responded to a live request
    ) || (
        echo  [WARN] AI provider      no successful live response
        echo         The pipeline still works; scoring falls back to heuristics.
    )
)

REM --- API and worker ----------------------------------------------------
REM The API and the worker are the application itself. If either is not
REM running, the installation is not healthy, so these are failures and
REM not warnings. Only the AI provider degrades gracefully -- the
REM pipeline falls back to heuristic scoring -- so that stays a warning.
set "API_UP=0"
set "WORKER_ALIVE=0"
if exist "%VENV_PY%" (
    "%VENV_PY%" -c "import json,urllib.request; r=urllib.request.urlopen('%API_URL%/api/health',timeout=3); d=json.loads(r.read()); print('HTTP', r.status); print('WORKER_ALIVE', bool(d.get('worker',{}).get('alive')))" >"%TEMP%\vc_api.txt" 2>&1
    findstr /c:"HTTP 200" "%TEMP%\vc_api.txt" >nul && (
        echo  [OK]   API              %API_URL% is responding
        set "API_UP=1"
    ) || (
        echo  [FAIL] API              %API_URL% is not responding
        echo         The API may not be running. Use start.bat.
        set "FAILURES=1"
    )
    findstr /c:"WORKER_ALIVE True" "%TEMP%\vc_api.txt" >nul && (
        echo  [OK]   Worker heartbeat  present and the worker is alive
        set "WORKER_ALIVE=1"
    ) || (
        echo  [FAIL] Worker heartbeat  no live worker is answering
        echo         The background worker may not be running. Use start.bat.
        set "FAILURES=1"
    )
) else (
    echo  [FAIL] API              the virtual environment is missing
    set "FAILURES=1"
)

REM --- disk ---------------------------------------------------------------
if exist "%VENV_PY%" (
    "%VENV_PY%" -c "import shutil; print(round(shutil.disk_usage('.').free/1024**3,1))" >"%TEMP%\vc_disk.txt" 2>&1
    set /p FREEGB=<"%TEMP%\vc_disk.txt"
    echo  [OK]   Free disk         !FREEGB! GB
)

echo(
if "!FAILURES!"=="0" (
    echo  HEALTHY
    echo(
    endlocal
    exit /b 0
) else (
    echo  UNHEALTHY - see the FAIL lines above.
    echo(
    endlocal
    exit /b 1
)
