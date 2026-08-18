@echo off
setlocal enabledelayedexpansion
set "ROOT=%~dp0"
if exist "%ROOT%config.env" call "%ROOT%config.env"
if not defined LLAMA_PORT set "LLAMA_PORT=8080"
set "EV=%ROOT%evidence"
if not exist "%EV%" mkdir "%EV%"

echo [1/6] 하드웨어와 드라이버
nvidia-smi > "%EV%\nvidia-smi.txt" 2>&1
type "%EV%\nvidia-smi.txt"

echo [2/6] 번들 무결성
call :resolve_python
if errorlevel 1 exit /b 4
%PYTHON_CMD% "%ROOT%tools\verify_bundle.py" --root "%ROOT%" > "%EV%\manifest-check.txt" 2>&1
type "%EV%\manifest-check.txt"

echo [3/6] 네트워크 캡처 시작
pktmon start --capture --file-name "%EV%\pktmon.etl" >nul 2>&1
if errorlevel 1 echo [warn] pktmon을 시작하지 못했다 - 관리자 권한이 필요할 수 있다

echo [4/6] 적재된 모델
powershell -NoProfile -ExecutionPolicy Bypass -Command "(Invoke-RestMethod -Uri 'http://127.0.0.1:%LLAMA_PORT%/v1/models' -TimeoutSec 10) | ConvertTo-Json -Depth 6" > "%EV%\v1-models.json" 2>&1
type "%EV%\v1-models.json"

echo [5/6] Pi 툴 왕복
set "PI_OFFLINE=1"
set "PI_CODING_AGENT_DIR=%ROOT%home\agent"
set "LLAMA_BASE_URL=http://127.0.0.1:%LLAMA_PORT%"
"%ROOT%bin\pi\pi.exe" --offline --no-session --model "%MODEL_ALIAS%" --tools read --mode json -p "evidence\probe.txt 파일을 read 도구로 읽고 그 안의 낱말 하나를 그대로 답하라" > "%EV%\pi-tool-roundtrip.json" 2>&1
type "%EV%\pi-tool-roundtrip.json"

echo [6/6] 네트워크 캡처 종료
pktmon stop >nul 2>&1
pktmon etl2txt "%EV%\pktmon.etl" --out "%EV%\pktmon.txt" >nul 2>&1

echo.
echo 증거는 %EV% 에 있다. 종료 코드가 아니라 그 안의 내용이 판정 기준이다.
echo 확인할 것: nvidia-smi 드라이버 551.61 이상, 매니페스트 일치, v1-models에 %MODEL_ALIAS%,
echo pi-tool-roundtrip.json 안의 실제 도구 실행과 최종 답변, pktmon.txt에 외부 주소 시도 0건.
goto :end

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

:end
endlocal
