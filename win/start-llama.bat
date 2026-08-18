@echo off
setlocal
set "ROOT=%~dp0"
if exist "%ROOT%config.env" call "%ROOT%config.env"

if not defined LLAMA_BACKEND set "LLAMA_BACKEND=cuda"
if not defined LLAMA_PORT set "LLAMA_PORT=8080"
if not defined LLAMA_CTX set "LLAMA_CTX=32768"

set "LLAMA_DIR=%ROOT%bin\llama-%LLAMA_BACKEND%"
if not exist "%LLAMA_DIR%\llama-server.exe" (
  echo [FAIL] %LLAMA_DIR%\llama-server.exe 없음
  exit /b 2
)
if not defined MODEL_FILE (
  echo [FAIL] MODEL_FILE 미설정 - config.env를 채워라
  exit /b 2
)
if not defined MODEL_ALIAS (
  echo [FAIL] MODEL_ALIAS 미설정 - config.env를 채워라
  exit /b 2
)
if not exist "%ROOT%models\%MODEL_FILE%" (
  echo [FAIL] %ROOT%models\%MODEL_FILE% 없음
  exit /b 2
)

set "TS_ARG="
if defined GPU_TENSOR_SPLIT set "TS_ARG=-ts %GPU_TENSOR_SPLIT%"

echo [info] %LLAMA_BACKEND% 백엔드로 %MODEL_FILE% 를 %MODEL_ALIAS% 로 올린다
"%LLAMA_DIR%\llama-server.exe" ^
  -m "%ROOT%models\%MODEL_FILE%" ^
  --alias "%MODEL_ALIAS%" ^
  --jinja ^
  --host 127.0.0.1 ^
  --port %LLAMA_PORT% ^
  -ngl 999 ^
  -c %LLAMA_CTX% ^
  --parallel 1 ^
  -sm layer %TS_ARG%
exit /b %errorlevel%
