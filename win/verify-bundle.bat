@echo off
chcp 65001 >nul
setlocal
set "ROOT=%~dp0"
call :resolve_python
if errorlevel 1 exit /b 4

set "PYTHONIOENCODING=utf-8"

rem %ROOT% always ends with a backslash. Passing "%ROOT%" as-is escapes the
rem closing quote and breaks argv (measured: --root "C:\pi_agent\" ->
rem 'C:\pi_agent"'). A trailing dot ends the path instead.
%PYTHON_CMD% "%ROOT%tools\verify_bundle.py" --root "%ROOT%."
exit /b %errorlevel%

:resolve_python
if defined PYTHON_CMD goto :eof
rem The bundled embedded distribution is checked first - on a machine with no
rem admin rights and no network, if the system Python is missing or a
rem Microsoft Store app-execution-alias stub gets picked up instead, there is
rem no way to recover.
if not exist "%ROOT%bin\python\python.exe" goto :resolve_python_system
set "PYTHON_CMD="%ROOT%bin\python\python.exe""
goto :eof
:resolve_python_system
py -3.12 -c "import sys" >nul 2>&1
if not errorlevel 1 (
  set "PYTHON_CMD=py -3.12"
  goto :eof
)
python -c "import sys" >nul 2>&1
if not errorlevel 1 (
  set "PYTHON_CMD=python"
  goto :eof
)
echo [FAIL] could not find Python - set PYTHON_CMD in config.env to its path
exit /b 1
