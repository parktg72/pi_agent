@echo off
chcp 65001 >nul
setlocal
set "ROOT=%~dp0"
call :resolve_python
if errorlevel 1 exit /b 4

rem tools\export_sessions.py prints its per-session reasons in Korean. Called
rem directly, python.exe writes them in the console default code page and
rem VS Code / Windows Terminal show garbage (2026-08-18 measurement, same as
rem verify-bundle.bat). This wrapper pins the console and Python to UTF-8.
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"

rem Only sessions listed in lora\approved.txt are exported. Extra arguments
rem such as --keep-thinking are passed through. The tool's own exit code is
rem returned unchanged: 0 exported, 2 an approved ID was not found, 3 nothing
rem to export.
if not exist "%ROOT%lora" mkdir "%ROOT%lora"
%PYTHON_CMD% "%ROOT%tools\export_sessions.py" --sessions-dir "%ROOT%home\agent\sessions" --approved "%ROOT%lora\approved.txt" --out "%ROOT%lora\train.jsonl" %*
exit /b %errorlevel%

:resolve_python
if defined PYTHON_CMD goto :eof
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
