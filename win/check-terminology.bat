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
rem Checks the medical terminology dump slots (terminology\kcd8, icd10, atc,
rem umls, omop) against their slot.json records: required provenance and licence
rem review fields, review_status approved, file sizes and sha256. The slots are
rem outside the manifest, so this is their transfer check.
rem   check-terminology.bat              check every slot (nonzero if any is incomplete)
rem   check-terminology.bat record umls  hash terminology\umls\data into slot.json
rem "recorded" means records, hashes and review match - not that the data can be
rem loaded: no parser or loader exists yet.
rem Branches use goto, not parenthesized blocks: the errorlevel variable inside
rem a block is expanded when the block is parsed, before its command runs.
if "%~1"=="" goto :check_all
if /I "%~1"=="record" goto :record_slot
echo [FAIL] unknown argument "%~1" - use no argument, or record ^<slot^>
exit /b 2

:check_all
%BOOTSTRAP_PY% "%ROOT%tools\terminology_slots.py" --root "%ROOT%." check
exit /b %errorlevel%

:record_slot
if "%~2"=="" goto :record_missing
%BOOTSTRAP_PY% "%ROOT%tools\terminology_slots.py" --root "%ROOT%." record %2
exit /b %errorlevel%
:record_missing
echo [FAIL] name the slot to record: kcd8, icd10, atc, umls or omop
exit /b 2

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
