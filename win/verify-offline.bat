@echo off
chcp 949 >nul
setlocal enabledelayedexpansion
set "ROOT=%~dp0"
rem 상대 경로가 호출 시점의 cwd가 아니라 번들 루트를 기준으로 풀리게 한다.
cd /d "%ROOT%"
call :load_config
if errorlevel 1 exit /b 6
if not defined LLAMA_PORT set "LLAMA_PORT=8080"

if not defined MODEL_ALIAS (
  echo [FAIL] MODEL_ALIAS 미설정 - config.env를 채워라
  exit /b 2
)
if not defined PI_MODEL_ID (
  echo [FAIL] PI_MODEL_ID 미설정 - config.env를 채워라. 형식은 ^<제공자^>/^<MODEL_ALIAS^> 이다.
  exit /b 2
)

set "EV=%ROOT%evidence"
if not exist "%EV%" mkdir "%EV%"

echo [1/6] 하드웨어와 드라이버
nvidia-smi > "%EV%\nvidia-smi.txt" 2>&1
type "%EV%\nvidia-smi.txt"

echo [2/6] 번들 무결성
call :resolve_python
if errorlevel 1 exit /b 4
set "PYTHONIOENCODING=cp949"
rem %ROOT%는 항상 역슬래시로 끝난다. "%ROOT%"를 그대로 넘기면 닫는 따옴표가
rem 이스케이프되어 argv가 깨진다(실측: --root "C:\pi_agent\" -> 'C:\pi_agent"').
rem 마침표를 붙여 경로를 끝낸다.
%PYTHON_CMD% "%ROOT%tools\verify_bundle.py" --root "%ROOT%." > "%EV%\manifest-check.txt" 2>&1
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
call :place_models_json
if errorlevel 1 exit /b 5
rem 프로브 파일은 이 스크립트가 직접 쓴다. 없는 파일을 읽으라고 시키면
rem 툴 왕복 증거가 통째로 날아간다. 프롬프트에는 절대 경로로 넘긴다.
set "PROBE=%EV%\probe.txt"
> "%PROBE%" echo NARWHAL-7Q2X
rem LLAMA_BASE_URL이 설정된 채로 pi.exe를 띄우면 내장 llama.cpp 제공자가
rem 인증된 것으로 취급되어 모델 목록에 살아난다. 그 제공자는 라우터 API로
rem 모델을 열거하므로 "Server is not running in llama.cpp router mode"를
rem 뱉는다 - models.json 정적 제공자로 우회하려던 바로 그 실패다. 이
rem 스크립트는 wait_model.py를 쓰지 않으므로 이 변수가 애초에 필요 없다.
set "LLAMA_BASE_URL="
"%ROOT%bin\pi\pi.exe" --offline --no-session --model "%PI_MODEL_ID%" --tools read --mode json -p "%PROBE% 파일을 read 도구로 읽고 그 안에 적힌 낱말을 그대로 답하라" > "%EV%\pi-tool-roundtrip.json" 2>&1
type "%EV%\pi-tool-roundtrip.json"

echo [6/6] 네트워크 캡처 종료
pktmon stop >nul 2>&1
pktmon etl2txt "%EV%\pktmon.etl" --out "%EV%\pktmon.txt" >nul 2>&1

echo.
echo 증거는 %EV% 에 있다. 종료 코드가 아니라 그 안의 내용이 판정 기준이다.
echo 확인할 것: nvidia-smi 드라이버 551.61 이상, 매니페스트 일치, v1-models에 %MODEL_ALIAS%,
echo pi-tool-roundtrip.json 안의 실제 도구 실행과 최종 답변에 낱말 NARWHAL-7Q2X,
echo pktmon.txt에 외부 주소 시도 0건.
goto :end

:place_models_json
rem pi.exe의 llama.cpp 제공자는 라우터 모드를 요구한다. 이 번들은 -m 단일 모델
rem 모드로 띄우므로 정적 제공자 선언(models.json)으로 엔드포인트를 인식시킨다.
if not exist "%ROOT%models.json" (
  echo [FAIL] %ROOT%models.json 없음 - Pi가 로컬 엔드포인트를 인식하지 못한다
  exit /b 1
)
if not exist "%PI_CODING_AGENT_DIR%" mkdir "%PI_CODING_AGENT_DIR%"
copy /y "%ROOT%models.json" "%PI_CODING_AGENT_DIR%\models.json" >nul
if errorlevel 1 (
  echo [FAIL] models.json을 %PI_CODING_AGENT_DIR% 로 복사하지 못했다
  exit /b 1
)
goto :eof

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

:resolve_python
if defined PYTHON_CMD goto :eof
rem 번들 내장 임베디드 배포를 가장 먼저 본다 - 관리자 권한도 네트워크도 없는
rem 곳에서 시스템 파이썬이 없거나 Microsoft Store 앱 실행 별칭 스텁이 잡히면
rem 복구가 불가능하기 때문이다.
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
echo [FAIL] Python을 찾지 못했다 - config.env의 PYTHON_CMD로 경로를 지정하라
exit /b 1

:end
endlocal
