@echo off
setlocal

REM ===================================================================
REM  VIRALCLIPS AI - restart.bat
REM ===================================================================

cd /d "%~dp0"

set "VENV_PY=%~dp0.venv\Scripts\python.exe"

echo  Restarting VIRALCLIPS AI...
echo(
call "%~dp0stop.bat"
REM The pause is taken with Python rather than "timeout": "timeout" needs
REM a real console and answers "Access is denied" in a non-interactive
REM session -- a scheduled task, a service, or a CI run -- which looks
REM like a restart failure when it is not.
if exist "%VENV_PY%" "%VENV_PY%" -c "import time; time.sleep(2)" >nul 2>&1
call "%~dp0start.bat"
exit /b %ERRORLEVEL%
