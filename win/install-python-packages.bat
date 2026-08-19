@echo off
chcp 65001 >nul
setlocal
set "ROOT=%~dp0"
rem All relative paths must resolve against the bundle root, not the caller's cwd.
cd /d "%ROOT%"
call :load_config
if errorlevel 1 exit /b 6

set "PKG_DIR=%ROOT%packages_win\py312"
set "CONSTRAINT=%ROOT%packages_win\constraints-py312.txt"
set "REQUIREMENTS=%ROOT%packages_win\requirements.txt"
set "VCRUNTIME_DIR=%ROOT%packages_win\vcruntime"
set "VENV_DIR=%ROOT%.venv"
set "EV=%ROOT%evidence"
if not exist "%EV%" mkdir "%EV%"

if not exist "%PKG_DIR%" (
  echo [FAIL] %PKG_DIR% not found - the wheelhouse was not carried in
  exit /b 2
)
if not exist "%CONSTRAINT%" (
  echo [FAIL] %CONSTRAINT% not found
  exit /b 2
)
if not exist "%REQUIREMENTS%" (
  echo [FAIL] %REQUIREMENTS% not found
  exit /b 2
)

rem The console is now UTF-8, so pin Python output to UTF-8 too. The Python
rem resolution step below already runs Python, so this must be set first.
set "PYTHONIOENCODING=utf-8"

call :resolve_python
if errorlevel 1 exit /b 4

rem The default is an isolated install (%ROOT%.venv). A --user install writes
rem numpy/pandas into %APPDATA%\Python\Python312\site-packages, which affects
rem **every** Python 3.12 run for that user - if an internal script depends on
rem numpy<2 it breaks immediately with no rollback path. So isolation is the
rem default, and reaching global scope requires an explicit argument. The venv
rem sits outside the manifest hash scope (EXCLUDED_ROOTS in tools\manifest.py),
rem so creating it does not break integrity verification.
rem   install-python-packages.bat          -> isolated install into %ROOT%.venv (default)
rem   install-python-packages.bat --user   -> install into global user site-packages
set "INSTALL_SCOPE="
set "USE_VENV=1"
if /I "%~1"=="--user" set "USE_VENV=0"
if /I "%~1"=="user" set "USE_VENV=0"
if /I "%~1"=="venv" set "USE_VENV=1"
if "%USE_VENV%"=="0" goto :scope_user

if not exist "%VENV_DIR%\Scripts\python.exe" (
  echo [info] creating virtual environment - %VENV_DIR%
  %PYTHON_CMD% -m venv "%VENV_DIR%"
  if errorlevel 1 (
    echo [FAIL] failed to create virtual environment - %VENV_DIR%
    exit /b 4
  )
)
set "PYTHON_CMD="%VENV_DIR%\Scripts\python.exe""
set "CHECK_CMD="%VENV_DIR%\Scripts\python.exe""
call :validate_python
if errorlevel 1 exit /b 4
echo [1/4] install target: virtual environment %VENV_DIR% (isolated - does not touch the system Python)
echo       use %VENV_DIR%\Scripts\python.exe to run analysis code.
echo       executables such as Jupyter land in %VENV_DIR%\Scripts\.
goto :scope_done

:scope_user
set "INSTALL_SCOPE=--user"
echo [1/4] install target: global user site-packages (--user)
echo [warn] a --user install writes packages into %%APPDATA%%\Python\Python312\site-packages,
echo        affecting **every** Python 3.12 run under this user account. If an
echo        internal script depends on a different numpy/pandas version it breaks
echo        immediately, with no rollback. Re-run with no argument to isolate -
echo        %VENV_DIR% isolation is the default.
echo        executables (jupyter etc.) land in %%APPDATA%%\Python\Python312\Scripts.
goto :scope_done

:scope_done

echo [2/4] installing from the offline index only - nothing reaches the network
echo       find-links: %PKG_DIR%
echo       constraint: %CONSTRAINT%
%PYTHON_CMD% -m pip install --no-index --find-links "%PKG_DIR%" --constraint "%CONSTRAINT%" -r "%REQUIREMENTS%" %INSTALL_SCOPE% --no-warn-script-location > "%EV%\python-packages-install.txt" 2>&1
type "%EV%\python-packages-install.txt"

echo [3/4] placing the VC runtime lightgbm needs
call :place_vcruntime

echo [4/4] verifying the install - importing every direct dependency in requirements.txt one by one
%PYTHON_CMD% "%ROOT%tools\check_imports.py" --requirements "%REQUIREMENTS%" > "%EV%\python-packages-check.txt" 2>&1
type "%EV%\python-packages-check.txt"

echo.
echo Evidence is in %EV%. The judging basis is the content of the two files below, not the exit code.
echo   whether the last line of evidence\python-packages-install.txt ends with "Successfully installed"
echo   whether the last line of evidence\python-packages-check.txt is IMPORT_OK with no FAIL lines
goto :end

:load_config
rem cmd's call only treats .bat/.cmd extensions as batch. Calling .env as-is
rem does nothing and returns errorlevel 0 - 2026-08-18 measurement on another
rem script: every set in config.env was ignored and the value stayed empty.
rem So a runnable .cmd copy is made and that is called instead. The copy is
rem remade from the source every time.
if not exist "%ROOT%config.env" goto :eof
if not exist "%ROOT%home\agent" mkdir "%ROOT%home\agent"
copy /y "%ROOT%config.env" "%ROOT%home\agent\config.cmd" >nul
if errorlevel 1 (
  echo [FAIL] could not copy config.env to a runnable copy
  exit /b 1
)
call "%ROOT%home\agent\config.cmd"
goto :eof

:place_vcruntime
rem The lightgbm wheel does not vendor VCOMP140.DLL and MSVCP140.dll that
rem lib_lightgbm.dll requires (scikit-learn is fine because it bundles its own
rem copies under sklearn\.libs\). The bundle's three VC runtime files live
rem app-local under bin\llama-*\, which is not on the Python process's search
rem path. So, the same way sklearn does it, the same two DLLs are placed
rem app-local next to the installed lightgbm\bin\. Python 3.8+'s ctypes turns
rem on LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR when opening a DLL by path, so it
rem looks for dependent DLLs in that DLL's own folder.
rem The install location differs between venv and --user, so Python itself is
rem asked directly. find_spec does not execute the module - importing lightgbm
rem itself may fail right now because the DLL is missing, so asking via import
rem is not safe here.
if not exist "%VCRUNTIME_DIR%" (
  echo [warn] %VCRUNTIME_DIR% not found - lightgbm may fail to find VCOMP140.DLL
  goto :eof
)
set "LGB_DIR="
%PYTHON_CMD% -c "import importlib.util, os; spec = importlib.util.find_spec('lightgbm'); print(os.path.dirname(spec.origin) if spec and spec.origin else '')" > "%EV%\lightgbm-location.txt" 2>&1
for /f "usebackq delims=" %%d in ("%EV%\lightgbm-location.txt") do set "LGB_DIR=%%d"
if not defined LGB_DIR goto :place_vcruntime_missing
if not exist "%LGB_DIR%\bin" goto :place_vcruntime_missing
copy /y "%VCRUNTIME_DIR%\VCOMP140.DLL" "%LGB_DIR%\bin\" >nul
if errorlevel 1 goto :place_vcruntime_missing
copy /y "%VCRUNTIME_DIR%\MSVCP140.dll" "%LGB_DIR%\bin\" >nul
if errorlevel 1 goto :place_vcruntime_missing
echo       app-local placement done: %LGB_DIR%\bin
goto :eof
:place_vcruntime_missing
echo [warn] could not find where lightgbm installed - the VC runtime was not placed
echo        if the lightgbm line in [4/4] below shows FAIL, this is likely why.
echo        path lookup result: evidence\lightgbm-location.txt
goto :eof

:validate_python
rem Checks whether the Python in CHECK_CMD is (a) Python 3.12 and (b) has pip.
rem If either fails, say what is wrong and stop. A PYTHON_CMD supplied through
rem config.env must pass this same check.
%CHECK_CMD% -c "import sys" >nul 2>&1
if errorlevel 1 (
  echo [FAIL] could not run Python: %CHECK_CMD%
  echo        PYTHON_CMD in config.env is wrong, or no executable exists at that path.
  exit /b 1
)
%CHECK_CMD% -c "import sys; sys.exit(0 if sys.version_info[:2] == (3, 12) else 1)" >nul 2>&1
if errorlevel 1 (
  echo [FAIL] not Python 3.12: %CHECK_CMD%
  echo        all 155 wheels in packages_win\py312 are cp312 win_amd64 only, so
  echo        any other version fails every one of them with "not a supported wheel".
  echo        actual version:
  %CHECK_CMD% -c "import sys; print(sys.version)"
  exit /b 1
)
%CHECK_CMD% -c "import pip" >nul 2>&1
if errorlevel 1 (
  echo [FAIL] this Python has no pip: %CHECK_CMD%
  echo        the bundled embedded distribution ^(bin\python\python.exe^) has no pip.
  echo        if PYTHON_CMD in config.env points there, clear it - unlike the other
  echo        .bat files, this one script uses the target PC's **system** Python 3.12.
  exit /b 1
)
goto :eof

:resolve_python
rem This script does not use the bundled embedded Python (bin\python\python.exe) -
rem the embedded distribution has no pip, so it cannot install packages (this is
rem deliberately different from the other .bat files, which prefer that Python
rem first). It looks for the target PC's system Python 3.12: the py launcher
rem first, then python on PATH. If PYTHON_CMD is set via config.env it is used,
rem but the check is not skipped - an earlier version did goto :eof immediately
rem here, so a configured embedded-Python path would be used to attempt an
rem install with no pip.
if defined PYTHON_CMD goto :resolve_python_configured
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
echo        the bundled bin\python\python.exe cannot be used here - it has no pip.
exit /b 1

:resolve_python_configured
echo [info] using PYTHON_CMD from config.env: %PYTHON_CMD%
goto :resolve_python_validate

:resolve_python_validate
set "CHECK_CMD=%PYTHON_CMD%"
call :validate_python
if errorlevel 1 exit /b 1
goto :eof

:end
endlocal
