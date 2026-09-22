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
rem Every step that can fail stops the script with a nonzero code: a server
rem started without its .env would fall back to the library defaults, which
rem point at external endpoints.
if not defined LLAMA_PORT set "LLAMA_PORT=8080"
if not defined EMBED_PORT set "EMBED_PORT=8081"
if not defined MODEL_ALIAS set "MODEL_ALIAS=qwen3.8-27b"
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
if not exist "%KG_HOME%\tiktoken_cache" (
  echo [FAIL] %KG_HOME%\tiktoken_cache not found - rerun install-kg.bat
  exit /b 2
)
if not exist "%ROOT%kg\lightrag.env" (
  echo [FAIL] %ROOT%kg\lightrag.env not found
  exit /b 2
)
if not exist "%KG_WORK%\inputs" mkdir "%KG_WORK%\inputs"
if not exist "%KG_WORK%\inputs" (
  echo [FAIL] could not create %KG_WORK%\inputs
  exit /b 5
)
rem The template is copied once. Later edits in home\kg\work\.env are the
rem operator's and are kept; delete that file to go back to the template.
if not exist "%KG_WORK%\.env" copy /y "%ROOT%kg\lightrag.env" "%KG_WORK%\.env" >nul
if not exist "%KG_WORK%\.env" (
  echo [FAIL] could not copy kg\lightrag.env to %KG_WORK%\.env
  exit /b 5
)
rem The servers this bundle started are the ones LightRAG must talk to, so the
rem ports and the model name come from config.env. LightRAG loads .env with
rem override=False (lightrag\api\config.py), so these process values win over
rem the same keys in .env.
set "LLM_BINDING_HOST=http://127.0.0.1:%LLAMA_PORT%/v1"
set "EMBEDDING_BINDING_HOST=http://127.0.0.1:%EMBED_PORT%/v1"
set "LLM_MODEL=%MODEL_ALIAS%"
set "TIKTOKEN_CACHE_DIR=%KG_HOME%\tiktoken_cache"
rem kg\lightrag.env caps each request to fit an 8192-token slot. Refuse to
rem start if the LLM server on LLAMA_PORT has smaller slots (or is not up).
"%KG_PY%" "%ROOT%tools\server_profile.py" --base-url "http://127.0.0.1:%LLAMA_PORT%" --min-slot-ctx 8192
if errorlevel 1 (
  echo [FAIL] start start-llama.bat kg first, with slots of at least 8192 tokens
  exit /b 3
)
cd /d "%KG_WORK%"
if errorlevel 1 (
  echo [FAIL] could not change to %KG_WORK%
  exit /b 5
)
echo [info] LightRAG in %KG_WORK% - documents go in %KG_WORK%\inputs
echo [info] LLM %LLM_BINDING_HOST% as %LLM_MODEL%, embeddings %EMBEDDING_BINDING_HOST%
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
