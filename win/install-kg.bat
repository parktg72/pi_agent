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
rem Installs the knowledge-graph Python stack (LightRAG[api,offline], Kuzu,
rem NetworkX, rdflib, tiktoken, graphify) into its own virtual environment,
rem home\kg\venv, from packages_win\kg\wheelhouse only. It is kept apart from
rem .venv and packages_win\py312 on purpose: the KG wheelhouse carries two numpy
rem and two boto3 versions, and mixing it into the analysis stack's constraints
rem would break them (tasks\pi-agent-kg-align, item 1). home\ is outside the
rem manifest, so creating the venv does not disturb integrity checks.
rem Every step that can fail stops the script with a nonzero code.
set "KG_WHEELS=%ROOT%packages_win\kg\wheelhouse"
set "KG_TIKTOKEN=%ROOT%packages_win\kg\tiktoken"
set "KG_HOME=%ROOT%home\kg"
set "KG_VENV=%KG_HOME%\venv"
set "EV=%ROOT%evidence"
if not exist "%EV%" mkdir "%EV%"
if not exist "%KG_WHEELS%" (
  echo [FAIL] %KG_WHEELS% not found - the KG wheelhouse was not carried in
  exit /b 2
)
if not exist "%KG_TIKTOKEN%\o200k_base.tiktoken" (
  echo [FAIL] %KG_TIKTOKEN%\o200k_base.tiktoken not found
  exit /b 2
)
call :resolve_python
if errorlevel 1 exit /b 4
if not exist "%KG_HOME%" mkdir "%KG_HOME%"
if not exist "%KG_VENV%\Scripts\python.exe" (
  echo [1/5] creating virtual environment - %KG_VENV%
  %PYTHON_CMD% -m venv "%KG_VENV%"
  if errorlevel 1 (
    echo [FAIL] failed to create virtual environment - %KG_VENV%
    exit /b 4
  )
) else (
  echo [1/5] virtual environment exists - %KG_VENV%
)
set "KG_PY="%KG_VENV%\Scripts\python.exe""
echo [2/5] installing from %KG_WHEELS% only (--no-index, no network)
%KG_PY% -m pip install --no-index --find-links="%KG_WHEELS%" "lightrag-hku[api,offline]" kuzu networkx rdflib tiktoken "graphifyy[pdf,leiden]" > "%EV%\install-kg.txt" 2>&1
if errorlevel 1 (
  echo [FAIL] pip install failed - see evidence\install-kg.txt
  exit /b 5
)
echo [3/5] pip check
%KG_PY% -m pip check > "%EV%\install-kg-pipcheck.txt" 2>&1
if errorlevel 1 (
  echo [FAIL] pip check found broken requirements - see evidence\install-kg-pipcheck.txt
  exit /b 5
)
echo [4/5] building the tiktoken cache in %KG_HOME%\tiktoken_cache
%KG_PY% "%ROOT%tools\build_tiktoken_cache.py" --src "%KG_TIKTOKEN%" --dst "%KG_HOME%\tiktoken_cache"
if errorlevel 1 (
  echo [FAIL] tiktoken cache was not built
  exit /b 5
)
echo [5/5] import check with the network-free tokenizer cache
set "TIKTOKEN_CACHE_DIR=%KG_HOME%\tiktoken_cache"
%KG_PY% -c "import lightrag, kuzu, networkx, rdflib, graphify, tiktoken; n=len(tiktoken.get_encoding('o200k_base').encode('test')); print('[ok] imports; tiktoken offline tokens', n)"
if errorlevel 1 (
  echo [FAIL] import check failed
  exit /b 5
)
echo [ok] KG stack installed. Next: start-llama.bat kg, start-embedding.bat, start-lightrag.bat
exit /b 0

:resolve_python
rem Like install-python-packages.bat: a system Python 3.12 with pip is needed to
rem create a venv (the bundled embedded Python has neither venv nor pip).
if defined PYTHON_CMD goto :resolve_python_validate
py -3.12 -c "import sys" >nul 2>&1
if not errorlevel 1 (
  set "PYTHON_CMD=py -3.12"
  goto :resolve_python_validate
)
python -c "import sys" >nul 2>&1
if not errorlevel 1 (
  set "PYTHON_CMD=python"
  goto :resolve_python_validate
)
echo [FAIL] could not find a system Python 3.12 - neither py -3.12 nor python ran.
echo        install Python 3.12, or set PYTHON_CMD in config.env to its path.
exit /b 1
:resolve_python_validate
%PYTHON_CMD% -c "import sys; sys.exit(0 if sys.version_info[:2] == (3, 12) else 1)" >nul 2>&1
if errorlevel 1 (
  echo [FAIL] not Python 3.12: %PYTHON_CMD%
  echo        every KG wheel is cp312 win_amd64 or pure Python built for 3.12.
  exit /b 1
)
%PYTHON_CMD% -c "import venv, ensurepip" >nul 2>&1
if errorlevel 1 (
  echo [FAIL] this Python cannot create a venv with pip: %PYTHON_CMD%
  echo        the bundled bin\python\python.exe cannot be used here.
  exit /b 1
)
goto :eof

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
