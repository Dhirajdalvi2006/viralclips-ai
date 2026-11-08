@echo off
setlocal EnableDelayedExpansion

REM ===================================================================
REM  VIRALCLIPS AI - stop.bat
REM
REM  Stops the API server and the background worker started by
REM  start.bat. Only the PIDs recorded in data\api.pid and
REM  data\worker.pid are stopped, so unrelated Python or Node
REM  processes are never killed.
REM ===================================================================

cd /d "%~dp0"

set "VENV_PY=%~dp0.venv\Scripts\python.exe"
set "API_PORT=8799"
if not "%VIRALCLIPS_API_PORT%"=="" set "API_PORT=%VIRALCLIPS_API_PORT%"

echo(
echo  Stopping VIRALCLIPS AI...
echo(

if not exist "%VENV_PY%" (
    echo  [!] The virtual environment is missing; falling back to a port check.
    goto :portcheck
)

"%VENV_PY%" -m viralclips_app.service_control stop

:portcheck
"%VENV_PY%" -m viralclips_app.service_control free-port !API_PORT! >nul 2>&1

echo(
echo  VIRALCLIPS AI stopped.
echo(
endlocal
exit /b 0
