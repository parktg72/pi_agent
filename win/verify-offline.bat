@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
set "ROOT=%~dp0"
rem Relative paths must resolve against the bundle root, not the caller's cwd.
cd /d "%ROOT%"
call :load_config
if errorlevel 1 exit /b 6
if not defined LLAMA_PORT set "LLAMA_PORT=8080"

if not defined MODEL_ALIAS (
  echo [FAIL] MODEL_ALIAS is not set - fill in config.env
  exit /b 2
)
if not defined PI_MODEL_ID (
  echo [FAIL] PI_MODEL_ID is not set - fill in config.env. The format is ^<provider^>/^<MODEL_ALIAS^>.
  exit /b 2
)

set "EV=%ROOT%evidence"
if not exist "%EV%" mkdir "%EV%"

echo [1/7] hardware and driver
nvidia-smi > "%EV%\nvidia-smi.txt" 2>&1
type "%EV%\nvidia-smi.txt"

echo [2/7] bundle integrity
call :resolve_python
if errorlevel 1 exit /b 4
set "PYTHONIOENCODING=utf-8"
rem %ROOT% always ends with a backslash. Passing "%ROOT%" as-is escapes the
rem closing quote and breaks argv (measured: --root "C:\pi_agent\" ->
rem 'C:\pi_agent"'). A trailing dot ends the path instead.
%PYTHON_CMD% "%ROOT%tools\verify_bundle.py" --root "%ROOT%." > "%EV%\manifest-check.txt" 2>&1
type "%EV%\manifest-check.txt"

echo [3/7] starting the network capture
pktmon start --capture --file-name "%EV%\pktmon.etl" >nul 2>&1
if errorlevel 1 echo [warn] could not start pktmon - it may require admin rights

echo [4/7] the loaded model
powershell -NoProfile -ExecutionPolicy Bypass -Command "(Invoke-RestMethod -Uri 'http://127.0.0.1:%LLAMA_PORT%/v1/models' -TimeoutSec 10) | ConvertTo-Json -Depth 6" > "%EV%\v1-models.json" 2>&1
type "%EV%\v1-models.json"

echo [5/7] did Pi's extensions and skills actually attach
set "PI_OFFLINE=1"
set "PI_CODING_AGENT_DIR=%ROOT%home\agent"
rem If pi.exe is started with LLAMA_BASE_URL still set, the built-in llama.cpp
rem provider is treated as authenticated and shows up in the model list. That
rem provider enumerates models through the router API, so it throws "Server is
rem not running in llama.cpp router mode" - the exact failure the models.json
rem static provider was meant to route around. This script does not use
rem wait_model.py, so this variable is not needed here at all. It may be left
rem over from a parent environment, so clear it before either pi.exe call.
set "LLAMA_BASE_URL="
call :place_models_json
if errorlevel 1 exit /b 5
rem Evidence that all four extensions attached has never been produced by
rem this bundle before - the manual check in rehearsal Sec 5-2 leaves nothing
rem in evidence\. Sync is redone here too because this script must be runnable
rem standalone, without start-pi.bat. The subroutine bodies use the same
rem idiom as start-pi.bat (:load_config, :resolve_python, :place_models_json
rem are already duplicated the same way in both files - there is no sharing
rem mechanism between .bat files).
call :sync_packages
if errorlevel 1 exit /b 7
"%ROOT%bin\pi\pi.exe" list > "%EV%\pi-packages.txt" 2>&1
type "%EV%\pi-packages.txt"

echo [6/7] Pi tool round trip
rem This script writes the probe file itself. Telling the model to read a
rem file that does not exist would drop the tool round-trip evidence
rem entirely. The prompt passes an absolute path.
set "PROBE=%EV%\probe.txt"
> "%PROBE%" echo NARWHAL-7Q2X
"%ROOT%bin\pi\pi.exe" --offline --no-session --model "%PI_MODEL_ID%" --tools read --mode json -p "%PROBE% - read this file with the read tool and answer with exactly the word written in it" > "%EV%\pi-tool-roundtrip.json" 2>&1
type "%EV%\pi-tool-roundtrip.json"

echo [7/7] stopping the network capture
pktmon stop >nul 2>&1
pktmon etl2txt "%EV%\pktmon.etl" --out "%EV%\pktmon.txt" >nul 2>&1

echo.
echo Evidence is in %EV%. The judging basis is its content, not the exit code.
echo Check: nvidia-smi driver 551.61 or newer, manifest match, %MODEL_ALIAS% present in v1-models,
echo the 4 extensions/skills listed as User packages in pi-packages.txt,
echo the actual tool call and final answer NARWHAL-7Q2X inside pi-tool-roundtrip.json,
echo 0 external-address attempts in pktmon.txt.
goto :end

:place_models_json
rem pi.exe's llama.cpp provider requires router mode. This bundle boots in
rem single-model -m mode, so a static provider declaration (models.json) is
rem used to make it recognize the endpoint.
if not exist "%ROOT%models.json" (
  echo [FAIL] %ROOT%models.json not found - Pi cannot recognize the local endpoint
  exit /b 1
)
if not exist "%PI_CODING_AGENT_DIR%" mkdir "%PI_CODING_AGENT_DIR%"
copy /y "%ROOT%models.json" "%PI_CODING_AGENT_DIR%\models.json" >nul
if errorlevel 1 (
  echo [FAIL] could not copy models.json to %PI_CODING_AGENT_DIR%
  exit /b 1
)
goto :eof

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
if not exist "%ROOT%pi-packages\settings.packages.json" goto :eof
if exist "%PI_CODING_AGENT_DIR%\settings.json" goto :sync_packages_compare
if not exist "%PI_CODING_AGENT_DIR%" mkdir "%PI_CODING_AGENT_DIR%"
copy /y "%ROOT%pi-packages\settings.packages.json" "%PI_CODING_AGENT_DIR%\settings.json" >nul
if errorlevel 1 (
  echo [FAIL] could not seed the initial settings.json
  exit /b 1
)
goto :eof
:sync_packages_compare
rem An existing settings.json is never overwritten. So when a v2 bundle adds
rem a package, it silently goes unregistered, and xcopy /D does not remove
rem anything deleted upstream either - there was no detection mechanism
rem anywhere in the update path. This only **warns** by diffing the two
rem lists. It does not overwrite automatically because this file is one the
rem operator can edit. String manipulation in batch is left to Python instead.
%PYTHON_CMD% "%ROOT%tools\packages_diff.py" --bundled "%ROOT%pi-packages\settings.packages.json" --installed "%PI_CODING_AGENT_DIR%\settings.json"
goto :eof

:load_config
rem cmd's call only executes .bat/.cmd extensions as batch. Calling .env as-is
rem does nothing and returns errorlevel 0 - 2026-08-18 Windows measurement:
rem every set in config.env was ignored and MODEL_ALIAS stayed empty.
rem To keep the filename operators are used to while making it actually run,
rem a .cmd copy is made in the mutable area and that is called instead. The
rem copy is remade from the source every time.
if not exist "%ROOT%config.env" goto :eof
if not exist "%ROOT%home\agent" mkdir "%ROOT%home\agent"
copy /y "%ROOT%config.env" "%ROOT%home\agent\config.cmd" >nul
if errorlevel 1 (
  echo [FAIL] could not copy config.env to a runnable copy
  exit /b 1
)
call "%ROOT%home\agent\config.cmd"
goto :eof

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

:end
endlocal
