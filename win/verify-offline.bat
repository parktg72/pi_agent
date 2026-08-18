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

echo [1/7] 하드웨어와 드라이버
nvidia-smi > "%EV%\nvidia-smi.txt" 2>&1
type "%EV%\nvidia-smi.txt"

echo [2/7] 번들 무결성
call :resolve_python
if errorlevel 1 exit /b 4
set "PYTHONIOENCODING=cp949"
rem %ROOT%는 항상 역슬래시로 끝난다. "%ROOT%"를 그대로 넘기면 닫는 따옴표가
rem 이스케이프되어 argv가 깨진다(실측: --root "C:\pi_agent\" -> 'C:\pi_agent"').
rem 마침표를 붙여 경로를 끝낸다.
%PYTHON_CMD% "%ROOT%tools\verify_bundle.py" --root "%ROOT%." > "%EV%\manifest-check.txt" 2>&1
type "%EV%\manifest-check.txt"

echo [3/7] 네트워크 캡처 시작
pktmon start --capture --file-name "%EV%\pktmon.etl" >nul 2>&1
if errorlevel 1 echo [warn] pktmon을 시작하지 못했다 - 관리자 권한이 필요할 수 있다

echo [4/7] 적재된 모델
powershell -NoProfile -ExecutionPolicy Bypass -Command "(Invoke-RestMethod -Uri 'http://127.0.0.1:%LLAMA_PORT%/v1/models' -TimeoutSec 10) | ConvertTo-Json -Depth 6" > "%EV%\v1-models.json" 2>&1
type "%EV%\v1-models.json"

echo [5/7] Pi 확장·스킬이 실제로 붙었는가
set "PI_OFFLINE=1"
set "PI_CODING_AGENT_DIR=%ROOT%home\agent"
rem LLAMA_BASE_URL이 설정된 채로 pi.exe를 띄우면 내장 llama.cpp 제공자가
rem 인증된 것으로 취급되어 모델 목록에 살아난다. 그 제공자는 라우터 API로
rem 모델을 열거하므로 "Server is not running in llama.cpp router mode"를
rem 뱉는다 - models.json 정적 제공자로 우회하려던 바로 그 실패다. 이
rem 스크립트는 wait_model.py를 쓰지 않으므로 이 변수가 애초에 필요 없다.
rem 상위 환경에 남아 있을 수 있으니 두 pi.exe 호출보다 먼저 지운다.
set "LLAMA_BASE_URL="
call :place_models_json
if errorlevel 1 exit /b 5
rem 확장 4종이 붙었다는 증거는 지금까지 이 번들에서 생산된 적이 없다 -
rem 리허설 §5-2의 수기 확인은 evidence\에 남지 않는다. 동기화까지 여기서
rem 다시 하는 이유는 이 스크립트를 start-pi.bat 없이 단독으로 돌릴 수 있어야
rem 하기 때문이다. 서브루틴 본문은 start-pi.bat과 같은 관용구를 쓴다
rem (:load_config, :resolve_python, :place_models_json이 이미 두 파일에
rem 같은 방식으로 복제돼 있다 - .bat 사이에는 공유 수단이 없다).
call :sync_packages
if errorlevel 1 exit /b 7
"%ROOT%bin\pi\pi.exe" list > "%EV%\pi-packages.txt" 2>&1
type "%EV%\pi-packages.txt"

echo [6/7] Pi 툴 왕복
rem 프로브 파일은 이 스크립트가 직접 쓴다. 없는 파일을 읽으라고 시키면
rem 툴 왕복 증거가 통째로 날아간다. 프롬프트에는 절대 경로로 넘긴다.
set "PROBE=%EV%\probe.txt"
> "%PROBE%" echo NARWHAL-7Q2X
"%ROOT%bin\pi\pi.exe" --offline --no-session --model "%PI_MODEL_ID%" --tools read --mode json -p "%PROBE% 파일을 read 도구로 읽고 그 안에 적힌 낱말을 그대로 답하라" > "%EV%\pi-tool-roundtrip.json" 2>&1
type "%EV%\pi-tool-roundtrip.json"

echo [7/7] 네트워크 캡처 종료
pktmon stop >nul 2>&1
pktmon etl2txt "%EV%\pktmon.etl" --out "%EV%\pktmon.txt" >nul 2>&1

echo.
echo 증거는 %EV% 에 있다. 종료 코드가 아니라 그 안의 내용이 판정 기준이다.
echo 확인할 것: nvidia-smi 드라이버 551.61 이상, 매니페스트 일치, v1-models에 %MODEL_ALIAS%,
echo pi-packages.txt에 확장·스킬 4종이 User packages로 나열됐는지,
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

:sync_packages
rem pi install로 사전 설치해 둔 확장/스킬 트리(pi-packages\npm, pi-packages\git)는
rem 로드 시점에 npm/git이 전혀 필요 없다 - PI_CODING_AGENT_DIR 밑에 npm\, git\
rem 구조로만 놓이면 pi.exe가 그대로 인식한다(pi.exe docs\packages.md).
rem xcopy /D로 파일 단위 갱신 비교를 xcopy에 맡긴다 - 이미 최신이면 건너뛰므로
rem 여기서 별도 비교 로직을 만들지 않는다. /H는 git 클론 안의 숨김(Hidden)
rem 속성 .git 폴더가 조용히 스킵되지 않게 한다(2026-08-18 윈도우 실측).
rem xcopy가 실패해도 대상에 이미 패키지가 있으면 계속한다 - 다른 Pi 세션이
rem 파일을 잠그고 있으면 두 번째 기동이 아예 안 되던 문제였다. 대상이 비어
rem 있을 때만 실패로 본다(그때는 확장 없이 뜨느니 멈추는 것이 낫다).
if not exist "%ROOT%pi-packages\npm" goto :sync_packages_git
if not exist "%PI_CODING_AGENT_DIR%\npm" mkdir "%PI_CODING_AGENT_DIR%\npm"
xcopy "%ROOT%pi-packages\npm" "%PI_CODING_AGENT_DIR%\npm\" /E /H /Y /D /Q >nul
if not errorlevel 1 goto :sync_packages_git
if exist "%PI_CODING_AGENT_DIR%\npm\node_modules" (
  echo [warn] pi-packages\npm 동기화가 실패했지만 대상에 이미 패키지가 있다 - 기존 것으로 계속한다
  echo        다른 Pi 세션이 파일을 잠그고 있을 수 있다. 확장이 구버전일 수 있다.
  goto :sync_packages_git
)
echo [FAIL] pi-packages\npm 을 %PI_CODING_AGENT_DIR%\npm 로 동기화하지 못했고 대상도 비어 있다
exit /b 1
:sync_packages_git
if not exist "%ROOT%pi-packages\git" goto :sync_packages_settings
if not exist "%PI_CODING_AGENT_DIR%\git" mkdir "%PI_CODING_AGENT_DIR%\git"
xcopy "%ROOT%pi-packages\git" "%PI_CODING_AGENT_DIR%\git\" /E /H /Y /D /Q >nul
if not errorlevel 1 goto :sync_packages_settings
if exist "%PI_CODING_AGENT_DIR%\git\github.com" (
  echo [warn] pi-packages\git 동기화가 실패했지만 대상에 이미 패키지가 있다 - 기존 것으로 계속한다
  echo        다른 Pi 세션이 파일을 잠그고 있을 수 있다. 스킬이 구버전일 수 있다.
  goto :sync_packages_settings
)
echo [FAIL] pi-packages\git 를 %PI_CODING_AGENT_DIR%\git 로 동기화하지 못했고 대상도 비어 있다
exit /b 1
:sync_packages_settings
rem settings.json은 사용자가 /trust, /settings로 직접 고칠 수 있는 파일이라
rem models.json처럼 매번 덮어쓰면 사용자 설정이 날아간다. 없을 때만
rem 패키지 목록이 담긴 원본을 심어 최초 1회만 등록한다.
if not exist "%ROOT%pi-packages\settings.packages.json" goto :eof
if exist "%PI_CODING_AGENT_DIR%\settings.json" goto :sync_packages_compare
if not exist "%PI_CODING_AGENT_DIR%" mkdir "%PI_CODING_AGENT_DIR%"
copy /y "%ROOT%pi-packages\settings.packages.json" "%PI_CODING_AGENT_DIR%\settings.json" >nul
if errorlevel 1 (
  echo [FAIL] settings.json 초기값을 심지 못했다
  exit /b 1
)
goto :eof
:sync_packages_compare
rem 이미 있는 settings.json은 덮어쓰지 않는다. 그래서 v2 번들이 패키지를
rem 추가하면 조용히 미등록되고, xcopy /D는 상류에서 삭제된 것을 지우지도
rem 않는다 - 갱신 경로에 감지 수단이 하나도 없었다. 여기서는 두 목록을
rem 대조해 **경고만** 한다. 자동으로 덮어쓰지 않는 것은 이 파일이 운영자가
rem 편집할 수 있는 파일이기 때문이다. 배치 문자열 조작 대신 파이썬에 맡긴다.
%PYTHON_CMD% "%ROOT%tools\packages_diff.py" --bundled "%ROOT%pi-packages\settings.packages.json" --installed "%PI_CODING_AGENT_DIR%\settings.json"
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
