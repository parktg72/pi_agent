@echo off
chcp 65001 >nul
setlocal
rem The Python tools print Korean diagnostics; pin their encoding before the
rem first Python call (config.env is parsed by Python).
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
set "ROOT=%~dp0"
rem Relative paths must resolve against the bundle root, not the caller's cwd.
cd /d "%ROOT%"
call :resolve_bootstrap_python
if errorlevel 1 exit /b 4
call :load_config
if errorlevel 1 exit /b 6
rem Starts the LightRAG server (WebUI http://127.0.0.1:9621) from home\kg\work.
rem Needs: install-kg.bat once, start-llama.bat kg (port LLAMA_PORT) and
rem start-embedding.bat (port EMBED_PORT) running. The tokenizer cache is set
rem for this process only - no user-wide environment variable is written.
set "KG_HOME=%ROOT%home\kg"
set "KG_PY=%KG_HOME%\venv\Scripts\python.exe"
set "KG_WORK=%KG_HOME%\work"
if not exist "%KG_PY%" (
  echo [FAIL] %KG_PY% not found - run install-kg.bat first
  exit /b 2
)
if not exist "%KG_HOME%\venv\Scripts\lightrag-server.exe" (
  echo [FAIL] lightrag-server.exe not found in home\kg\venv - rerun install-kg.bat
  exit /b 2
)
if not exist "%ROOT%kg\lightrag.env" (
  echo [FAIL] %ROOT%kg\lightrag.env not found
  exit /b 2
)
if not exist "%KG_WORK%\inputs" mkdir "%KG_WORK%\inputs"
rem The template is copied once. Later edits in home\kg\work\.env are the
rem operator's and are kept; delete that file to go back to the template.
if not exist "%KG_WORK%\.env" copy /y "%ROOT%kg\lightrag.env" "%KG_WORK%\.env" >nul
set "TIKTOKEN_CACHE_DIR=%KG_HOME%\tiktoken_cache"
cd /d "%KG_WORK%"
echo [info] LightRAG in %KG_WORK% - documents go in %KG_WORK%\inputs
"%KG_HOME%\venv\Scripts\lightrag-server.exe"
exit /b %errorlevel%

:load_config
rem config.env used to be copied to home\agent\config.cmd and called. That made
rem the config file *code*: 2026-08-19 measurement showed a value containing &
rem runs the rest as a command, and %%VAR%% / !VAR! vanish from values. Python
rem parses it now against an allowed-key list and a value character set, and
rem writes a sanitized .cmd holding nothing but verified set statements. That
rem sanitized file is what gets called.
if not exist "%ROOT%config.env" exit /b 0
if not exist "%ROOT%home\agent" mkdir "%ROOT%home\agent"
%BOOTSTRAP_PY% "%ROOT%tools\config_parse.py" --config "%ROOT%config.env" --out "%ROOT%home\agent\config.cmd"
if errorlevel 1 (
  echo [FAIL] config.env was refused - fix the lines listed above
  exit /b 1
)
call "%ROOT%home\agent\config.cmd"
exit /b 0

:resolve_bootstrap_python
rem Reading config.env now needs a Python before the config is read, so this
rem resolver cannot consult PYTHON_CMD - that value lives in the config. It is
rem deliberately separate from :resolve_python for that reason. The bundled
rem embedded distribution comes first: with no admin rights and no network, a
rem missing system Python or a Microsoft Store app-execution-alias stub leaves
rem no way to recover.
if defined BOOTSTRAP_PY goto :eof
if not exist "%ROOT%bin\python\python.exe" goto :resolve_bootstrap_system
set "BOOTSTRAP_PY="%ROOT%bin\python\python.exe""
goto :eof
:resolve_bootstrap_system
py -3.12 -c "import sys" >nul 2>&1
if not errorlevel 1 (
  set "BOOTSTRAP_PY=py -3.12"
  goto :eof
)
python -c "import sys" >nul 2>&1
if not errorlevel 1 (
  set "BOOTSTRAP_PY=python"
  goto :eof
)
echo [FAIL] no Python found - config.env cannot be parsed without one.
echo        Restore the bundled bin\python\python.exe, or install Python 3.12.
exit /b 1
