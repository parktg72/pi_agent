@echo off
chcp 949 >nul
setlocal
set "ROOT=%~dp0"
rem 상대 경로가 호출 시점의 cwd가 아니라 번들 루트를 기준으로 풀리게 한다.
cd /d "%ROOT%"
call :load_config
if errorlevel 1 exit /b 6

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
if defined MMPROJ_FILE if not exist "%ROOT%models\%MMPROJ_FILE%" (
  echo [FAIL] %ROOT%models\%MMPROJ_FILE% 없음
  exit /b 2
)

set "TS_ARG="
if defined GPU_TENSOR_SPLIT set "TS_ARG=-ts %GPU_TENSOR_SPLIT%"

set "MMPROJ_ARG="
if defined MMPROJ_FILE set MMPROJ_ARG=--mmproj "%ROOT%models\%MMPROJ_FILE%"

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
  -sm layer %TS_ARG% %MMPROJ_ARG%
exit /b %errorlevel%

:load_config
rem cmd의 call은 .bat/.cmd 확장자만 배치로 실행한다. .env를 그대로 call하면
rem 아무 일도 하지 않고 errorlevel 0으로 돌아온다 - 2026-08-18 윈도우 실측:
rem config.env의 모든 set이 무시되어 MODEL_ALIAS가 끝내 비어 있었다.
rem 운영자에게 익숙한 파일명을 유지하면서 실제로 실행되게 하려고, 가변 영역에
rem .cmd 사본을 만들어 그것을 call한다. 사본은 매번 원본에서 다시 만든다.
if not exist "%ROOT%config.env" goto :eof
if not exist "%ROOT%home\agent" mkdir "%ROOT%home\agent"
copy /y "%ROOT%config.env" "%ROOT%home\agent\config.cmd" >nul
if errorlevel 1 (
  echo [FAIL] config.env를 실행 가능한 사본으로 복사하지 못했다
  exit /b 1
)
call "%ROOT%home\agent\config.cmd"
goto :eof
