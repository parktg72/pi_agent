@echo off
chcp 65001 >nul
setlocal
set "ROOT=%~dp0"
rem Relative paths must resolve against the bundle root, not the caller's cwd.
cd /d "%ROOT%"
call :load_config
if errorlevel 1 exit /b 6

if not defined LLAMA_BACKEND set "LLAMA_BACKEND=cuda"
if not defined LLAMA_PORT set "LLAMA_PORT=8080"
if not defined LLAMA_CTX set "LLAMA_CTX=32768"

set "LLAMA_DIR=%ROOT%bin\llama-%LLAMA_BACKEND%"
if not exist "%LLAMA_DIR%\llama-server.exe" (
  echo [FAIL] %LLAMA_DIR%\llama-server.exe not found
  exit /b 2
)
if not defined MODEL_FILE (
  echo [FAIL] MODEL_FILE is not set - fill in config.env
  exit /b 2
)
if not defined MODEL_ALIAS (
  echo [FAIL] MODEL_ALIAS is not set - fill in config.env
  exit /b 2
)
if not exist "%ROOT%models\%MODEL_FILE%" (
  echo [FAIL] %ROOT%models\%MODEL_FILE% not found
  exit /b 2
)
if defined MMPROJ_FILE if not exist "%ROOT%models\%MMPROJ_FILE%" (
  echo [FAIL] %ROOT%models\%MMPROJ_FILE% not found
  exit /b 2
)

set "TS_ARG="
if defined GPU_TENSOR_SPLIT set "TS_ARG=-ts %GPU_TENSOR_SPLIT%"

set "MMPROJ_ARG="
if defined MMPROJ_FILE set MMPROJ_ARG=--mmproj "%ROOT%models\%MMPROJ_FILE%"

echo [info] starting %MODEL_FILE% as %MODEL_ALIAS% on the %LLAMA_BACKEND% backend
"%LLAMA_DIR%\llama-server.exe" ^
  -m "%ROOT%models\%MODEL_FILE%" ^
  --alias "%MODEL_ALIAS%" ^
  --jinja ^
  --host 127.0.0.1 ^
  --port %LLAMA_PORT% ^
  -ngl 999 ^
  -c %LLAMA_CTX% ^
  --parallel 1 ^
  -sm layer %TS_ARG% %MMPROJ_ARG%
exit /b %errorlevel%

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
