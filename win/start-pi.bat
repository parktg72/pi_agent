@echo off
chcp 949 >nul
setlocal
set "ROOT=%~dp0"
call :load_config
if errorlevel 1 exit /b 6
if not defined LLAMA_PORT set "LLAMA_PORT=8080"
if not defined MODEL_LOAD_TIMEOUT set "MODEL_LOAD_TIMEOUT=600"

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
if not defined PI_MODEL_ID (
  echo [FAIL] PI_MODEL_ID 미설정 - config.env를 채워라. 형식은 ^<제공자^>/^<MODEL_ALIAS^> 이고
  echo        제공자는 models.json의 providers 키, 뒷부분은 MODEL_ALIAS와 글자 그대로 같아야 한다.
  exit /b 2
)

call :place_models_json
if errorlevel 1 exit /b 5

rem 패키지 동기화가 파이썬을 쓰므로(settings.json 목록 대조) 파이썬 탐색을
rem 그보다 먼저 한다.
call :resolve_python
if errorlevel 1 exit /b 4

set "PYTHONIOENCODING=cp949"

call :sync_packages
if errorlevel 1 exit /b 7

%PYTHON_CMD% "%ROOT%tools\wait_model.py" --base-url "%LLAMA_BASE_URL%" --alias "%MODEL_ALIAS%" --timeout %MODEL_LOAD_TIMEOUT%
if errorlevel 1 (
  echo [FAIL] 모델이 준비되지 않았다 - Pi를 시작하지 않는다
  exit /b 3
)

rem LLAMA_BASE_URL이 남아 있으면 pi.exe 내장 llama.cpp 제공자가 인증된 것으로
rem 취급되어 모델 목록에 살아난다. 그 제공자는 라우터 API로 모델을 열거하므로
rem "Server is not running in llama.cpp router mode"를 뱉는다 - models.json
rem 정적 제공자로 우회하려던 바로 그 실패다. wait_model.py가 끝났으니 이제
rem 이 변수는 필요 없다(원래도 --base-url 인자로 받아 필수는 아니었다).
set "LLAMA_BASE_URL="

"%ROOT%bin\pi\pi.exe" --offline --model "%PI_MODEL_ID%" %*
exit /b %errorlevel%

:place_models_json
rem pi.exe의 llama.cpp 제공자는 라우터 모드를 요구한다("Server is not running in
rem llama.cpp router mode"). 이 번들은 무인 기동의 결정성을 위해 -m 단일 모델
rem 모드로 띄우므로 그 경로를 쓸 수 없다. 대신 정적 제공자 선언으로 푼다.
rem 검증된 원본은 번들 루트에 있고(매니페스트 해시 범위 안), 가변 영역인
rem home\agent\ 로 매번 덮어써 설정이 항상 원본에서 나오게 한다.
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
if exist "%PI_CODING_AGENT_DIR%\npm\node_modules\pi-subagents\package.json" (
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
if exist "%PI_CODING_AGENT_DIR%\git\github.com\obra\superpowers\package.json" (
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
