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
rem Embedding server for LightRAG: bge-m3 (1024-dim, multilingual, max 8192
rem tokens) on its own port and its own card, using the bundle's CUDA
rem llama-server - no second llama.cpp is carried in. Settings follow the
rem closed-network KG bundle guide section 4 (tasks\pi-agent-kg-align, item 7).
rem   CUDA_VISIBLE_DEVICES=EMBED_GPU hides the other cards, so -mg 0 is that card.
rem   --pooling cls is bge's pooling; a wrong value quietly ruins retrieval.
rem   -ub must be at least -c: an embedding is computed over the whole input.
if not defined EMBED_MODEL_FILE set "EMBED_MODEL_FILE=bge-m3-FP16.gguf"
if not defined EMBED_PORT set "EMBED_PORT=8081"
if not defined EMBED_GPU set "EMBED_GPU=2"
set "LLAMA_DIR=%ROOT%bin\llama-cuda"
if not exist "%LLAMA_DIR%\llama-server.exe" (
  echo [FAIL] "%LLAMA_DIR%\llama-server.exe" not found
  exit /b 2
)
if not exist "%ROOT%models\%EMBED_MODEL_FILE%" (
  echo [FAIL] "%ROOT%models\%EMBED_MODEL_FILE%" not found
  exit /b 2
)
set "CUDA_VISIBLE_DEVICES=%EMBED_GPU%"
echo [info] starting %EMBED_MODEL_FILE% as bge-m3 on 127.0.0.1:%EMBED_PORT%, GPU %EMBED_GPU%
echo [info] check: the /v1/embeddings vector length must be 1024 (EMBEDDING_DIM in kg\lightrag.env)
"%LLAMA_DIR%\llama-server.exe" ^
  -m "%ROOT%models\%EMBED_MODEL_FILE%" ^
  --alias bge-m3 ^
  --embeddings ^
  --host 127.0.0.1 ^
  --port %EMBED_PORT% ^
  -ngl 999 ^
  -sm none ^
  -mg 0 ^
  -c 8192 ^
  -b 8192 ^
  -ub 8192 ^
  --pooling cls
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
