@echo off
setlocal
set "ROOT=%~dp0"
if exist "%ROOT%config.env" call "%ROOT%config.env"
if not defined LLAMA_PORT set "LLAMA_PORT=8080"

set "PI_OFFLINE=1"
set "PI_CODING_AGENT_DIR=%~dp0home\agent"
set "LLAMA_BASE_URL=http://127.0.0.1:%LLAMA_PORT%"

if not exist "%ROOT%bin\pi\pi.exe" (
  echo [FAIL] %ROOT%bin\pi\pi.exe 없음
  exit /b 2
)
if not defined MODEL_ALIAS (
  echo [FAIL] MODEL_ALIAS 미설정 - config.env를 채워라
  exit /b 2
)

call :resolve_python
if errorlevel 1 exit /b 4

%PYTHON_CMD% "%ROOT%tools\wait_model.py" --base-url "%LLAMA_BASE_URL%" --alias "%MODEL_ALIAS%" --timeout 600
if errorlevel 1 (
  echo [FAIL] 모델이 준비되지 않았다 - Pi를 시작하지 않는다
  exit /b 3
)

"%ROOT%bin\pi\pi.exe" --offline --model "%MODEL_ALIAS%" %*
exit /b %errorlevel%

:resolve_python
if defined PYTHON_CMD goto :eof
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
echo [FAIL] Python을 찾지 못했다 - config.env의 PYTHON_CMD로 경로를 지정하라
exit /b 1
