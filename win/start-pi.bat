@echo off
chcp 65001 >nul
setlocal
rem The Python tools print Korean diagnostics. Their encoding is pinned here,
rem before the first Python call - config.env is parsed by Python now, so that
rem call happens earlier than it used to. PYTHONIOENCODING only covers stdio;
rem PYTHONUTF8 covers file I/O the tools do.
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
set "ROOT=%~dp0"
call :resolve_bootstrap_python
if errorlevel 1 exit /b 4
call :load_config
if errorlevel 1 exit /b 6
if not defined LLAMA_PORT set "LLAMA_PORT=8080"
if not defined MODEL_LOAD_TIMEOUT set "MODEL_LOAD_TIMEOUT=600"

set "PI_OFFLINE=1"
set "PI_CODING_AGENT_DIR=%~dp0home\agent"
set "LLAMA_BASE_URL=http://127.0.0.1:%LLAMA_PORT%"

if not exist "%ROOT%bin\pi\pi.exe" (
  echo [FAIL] %ROOT%bin\pi\pi.exe not found
  exit /b 2
)
if not defined MODEL_ALIAS (
  echo [FAIL] MODEL_ALIAS is not set - fill in config.env
  exit /b 2
)
if not defined PI_MODEL_ID (
  echo [FAIL] PI_MODEL_ID is not set - fill in config.env. The format is ^<provider^>/^<MODEL_ALIAS^>,
  echo        where the provider is the models.json providers key and the rest must match
  echo        MODEL_ALIAS character-for-character.
  exit /b 2
)

call :place_models_json
if errorlevel 1 exit /b 5

rem Package sync uses Python (it compares against settings.json), so resolve
rem Python before that.
call :resolve_python
if errorlevel 1 exit /b 4

call :sync_packages
if errorlevel 1 exit /b 7

%PYTHON_CMD% "%ROOT%tools\wait_model.py" --base-url "%LLAMA_BASE_URL%" --alias "%MODEL_ALIAS%" --timeout %MODEL_LOAD_TIMEOUT%
if errorlevel 1 (
  echo [FAIL] the model is not ready - not starting Pi
  exit /b 3
)

rem If LLAMA_BASE_URL is still set, pi.exe's built-in llama.cpp provider is
rem treated as authenticated and shows up in the model list. That provider
rem enumerates models through the router API, so it throws "Server is not
rem running in llama.cpp router mode" - the exact failure the models.json
rem static provider was meant to route around. wait_model.py is done now, so
rem this variable is no longer needed (it was never required in the first
rem place, since it can also be passed as --base-url).
set "LLAMA_BASE_URL="

rem pi.exe's own exit code is passed through unchanged. It is not evidence that
rem the model answered - pi.exe has been measured returning 0 after printing
rem "stopReason: error / Connection error." - which is why verify-offline.bat
rem judges the JSON events instead. But a nonzero code from pi.exe must not be
rem swallowed either, so it is propagated as-is.
rem The Qwen3.8 chat template inside the GGUF defaults reasoning_effort to xhigh
rem when a request carries none (measured 2026-08-25 by reading
rem tokenizer.chat_template), and thinking tokens spend the same output budget as
rem the answer. Inside -c 32768 that default is what cuts long turns short:
rem the server reports finish_reason "length" and Pi prints "Response was
rem truncated before completion." and ends the turn. models.json maps Pi's
rem thinking levels onto the template's chat_template_kwargs; this passes the
rem configured level. A config.env written before this key existed leaves
rem PI_THINKING unset, so the bundle default is applied here, not in that file.
if not defined PI_THINKING set "PI_THINKING=medium"
rem /retro turns what a session taught into proposed AGENTS.md lines and a LoRA
rem approval hint, without writing anything until the user approves. The
rem template is read straight from the hashed bundle root, so nothing is copied
rem into home\agent and there is no sync step to go stale.
set "PROMPT_ARG="
if exist "%ROOT%pi-prompts\retro.md" set PROMPT_ARG=--prompt-template "%ROOT%pi-prompts\retro.md"
"%ROOT%bin\pi\pi.exe" --offline --model "%PI_MODEL_ID%" --thinking "%PI_THINKING%" %PROMPT_ARG% %*
exit /b %errorlevel%

:place_models_json
rem pi.exe's llama.cpp provider requires router mode ("Server is not running
rem in llama.cpp router mode"). This bundle boots in single-model -m mode for
rem deterministic unattended startup, so that path is not usable. A static
rem provider declaration is used instead.
rem The bundle root models.json is a *template*: the port and the alias are
rem placeholders. It used to be a static file with 8080 baked in while
rem config.env carried LLAMA_PORT separately, so changing the port made
rem readiness pass on the new port while Pi still dialed 8080 - and that
rem failure was reported as exit 0. Now config.env is the single source and
rem this renders home\agent\models.json from it on every run. The template
rem stays inside the manifest hash scope; only the rendered copy is mutable.
if not exist "%ROOT%models.json" (
  echo [FAIL] %ROOT%models.json not found - Pi cannot recognize the local endpoint
  exit /b 1
)
if not exist "%PI_CODING_AGENT_DIR%" mkdir "%PI_CODING_AGENT_DIR%"
rem contextWindow in the rendered models.json comes from LLAMA_CTX, the same
rem value start-llama.bat gives the server, with the same default. A template
rem that pinned 32768 once sat under a server started with 65536.
if not defined LLAMA_CTX set "LLAMA_CTX=32768"
%BOOTSTRAP_PY% "%ROOT%tools\render_models_json.py" --template "%ROOT%models.json" --out "%PI_CODING_AGENT_DIR%\models.json" --port "%LLAMA_PORT%" --alias "%MODEL_ALIAS%" --model-id "%PI_MODEL_ID%" --ctx "%LLAMA_CTX%"
if errorlevel 1 (
  echo [FAIL] could not render models.json into %PI_CODING_AGENT_DIR%
  exit /b 1
)
exit /b 0

:sync_packages
rem The extension/skill tree pre-installed with pi install (pi-packages\npm,
rem pi-packages\git) needs no npm/git at load time - pi.exe recognizes it as
rem soon as it sits under PI_CODING_AGENT_DIR as npm\, git\ (see pi.exe
rem docs\packages.md). xcopy /D leaves the file-level freshness comparison to
rem xcopy itself - it skips files that are already current, so no separate
rem comparison logic is built here. /H makes sure the hidden .git folder
rem inside a git clone is not silently skipped (2026-08-18 Windows
rem measurement). If xcopy fails but the destination already has packages,
rem continue anyway - otherwise a second Pi session locking a file would make
rem every later startup fail outright. Only an empty destination counts as
rem failure (in that case, stopping is better than starting with no
rem extensions). This Windows build's xcopy has been observed returning exit
rem code 0 even when an individual file copy fails with access denied
rem (2026-08-18 Windows measurement) - judging by "if not errorlevel 1" alone
rem would misread that as success and never reach the content check. So the
rem anchor file check always runs regardless of xcopy's exit code, and if the
rem exit code was nonzero but the anchor exists anyway, that is logged as a
rem [warn] hint of a partial failure. If the anchor is missing, it is a
rem failure regardless of exit code (exit /b 1 stands).
rem The anchor check alone is not enough: it proves one file arrived, not that
rem the tree did. :verify_package_trees below compares every staged file by
rem path, size and hash, and that comparison is what decides.
if not exist "%ROOT%pi-packages\npm" goto :sync_packages_git
if not exist "%PI_CODING_AGENT_DIR%\npm" mkdir "%PI_CODING_AGENT_DIR%\npm"
xcopy "%ROOT%pi-packages\npm" "%PI_CODING_AGENT_DIR%\npm\" /E /H /Y /D /Q >nul
set "SYNC_NPM_ERR=%errorlevel%"
if exist "%PI_CODING_AGENT_DIR%\npm\node_modules\pi-subagents\package.json" goto :sync_packages_npm_ok
echo [FAIL] could not sync pi-packages\npm to %PI_CODING_AGENT_DIR%\npm and the destination is empty too
exit /b 1
:sync_packages_npm_ok
if "%SYNC_NPM_ERR%"=="0" goto :sync_packages_git
echo [warn] pi-packages\npm sync failed but the destination already has packages - continuing with the existing ones
echo        another Pi session may be locking a file. The extension may be an older version.
:sync_packages_git
if not exist "%ROOT%pi-packages\git" goto :sync_packages_settings
if not exist "%PI_CODING_AGENT_DIR%\git" mkdir "%PI_CODING_AGENT_DIR%\git"
xcopy "%ROOT%pi-packages\git" "%PI_CODING_AGENT_DIR%\git\" /E /H /Y /D /Q >nul
set "SYNC_GIT_ERR=%errorlevel%"
if exist "%PI_CODING_AGENT_DIR%\git\github.com\obra\superpowers\package.json" goto :sync_packages_git_ok
echo [FAIL] could not sync pi-packages\git to %PI_CODING_AGENT_DIR%\git and the destination is empty too
exit /b 1
:sync_packages_git_ok
if "%SYNC_GIT_ERR%"=="0" goto :sync_packages_settings
echo [warn] pi-packages\git sync failed but the destination already has packages - continuing with the existing ones
echo        another Pi session may be locking a file. The skill may be an older version.
:sync_packages_settings
rem settings.json is a file the user can edit directly through /trust,
rem /settings, so overwriting it every run like models.json would erase user
rem settings. Seed the source with its package list only when it is missing,
rem so registration happens exactly once.
if not exist "%ROOT%pi-packages\settings.packages.json" goto :verify_package_trees
if exist "%PI_CODING_AGENT_DIR%\settings.json" goto :sync_packages_compare
if not exist "%PI_CODING_AGENT_DIR%" mkdir "%PI_CODING_AGENT_DIR%"
copy /y "%ROOT%pi-packages\settings.packages.json" "%PI_CODING_AGENT_DIR%\settings.json" >nul
if errorlevel 1 (
  echo [FAIL] could not seed the initial settings.json
  exit /b 1
)
goto :verify_package_trees
:sync_packages_compare
rem An existing settings.json is never overwritten. So when a v2 bundle adds
rem a package, it silently goes unregistered, and xcopy /D does not remove
rem anything deleted upstream either - there was no detection mechanism
rem anywhere in the update path. This only **warns** by diffing the two
rem lists. It does not overwrite automatically because this file is one the
rem operator can edit. String manipulation in batch is left to Python instead.
%PYTHON_CMD% "%ROOT%tools\packages_diff.py" --bundled "%ROOT%pi-packages\settings.packages.json" --installed "%PI_CODING_AGENT_DIR%\settings.json"
:verify_package_trees
rem The gate used to be two anchor files, so a partial xcopy passed it. Every
rem staged file is compared by path, size and hash instead - 2,191 files and
rem 14MB, so hashing costs nothing next to loading a 16.8GB model.
if not exist "%ROOT%pi-packages" exit /b 0
%PYTHON_CMD% "%ROOT%tools\package_tree.py" --pair "%ROOT%pi-packages\npm::%PI_CODING_AGENT_DIR%\npm" --pair "%ROOT%pi-packages\git::%PI_CODING_AGENT_DIR%\git"
if errorlevel 1 (
  echo [FAIL] the package tree on disk does not match what the bundle carried
  exit /b 1
)
exit /b 0

:load_config
rem config.env used to be copied to home\agent\config.cmd and called. That made
rem the config file *code*: 2026-08-19 measurement showed a value containing &
rem runs the rest as a command, and percent-VAR-percent / !VAR! vanish from
rem values. Python parses it now against an allowed-key list and a value
rem character set, and writes a sanitized .cmd holding nothing but verified set
rem statements. That sanitized file is what gets called.
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
