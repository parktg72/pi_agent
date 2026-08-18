@echo off
chcp 949 >nul
setlocal
set "ROOT=%~dp0"
rem 모든 상대 경로가 호출 시점의 cwd가 아니라 번들 루트를 기준으로 풀리게 한다.
cd /d "%ROOT%"
call :load_config
if errorlevel 1 exit /b 6

set "PKG_DIR=%ROOT%packages_win\py312"
set "CONSTRAINT=%ROOT%packages_win\constraints-py312.txt"
set "REQUIREMENTS=%ROOT%packages_win\requirements.txt"
set "EV=%ROOT%evidence"
if not exist "%EV%" mkdir "%EV%"

if not exist "%PKG_DIR%" (
  echo [FAIL] %PKG_DIR% 없음 - 휠하우스가 반입되지 않았다
  exit /b 2
)
if not exist "%CONSTRAINT%" (
  echo [FAIL] %CONSTRAINT% 없음
  exit /b 2
)
if not exist "%REQUIREMENTS%" (
  echo [FAIL] %REQUIREMENTS% 없음
  exit /b 2
)

call :resolve_python
if errorlevel 1 exit /b 4

set "PYTHONIOENCODING=cp949"

rem 관리자 권한이 없을 수 있으므로 --user를 기본으로 쓴다. 완전히 격리하고
rem 싶으면 이 스크립트를 "install-python-packages.bat venv"로 실행한다 -
rem 먼저 %ROOT%.venv 를 만들고(이미 있으면 재사용) 그 안의 python.exe로
rem pip install을 다시 돌린다. 이때는 --user 대신 venv 자체가 격리를 준다.
set "INSTALL_SCOPE=--user"
if /I "%1"=="venv" (
  if not exist "%ROOT%.venv\Scripts\python.exe" (
    echo [info] 가상환경 생성 중 - %ROOT%.venv
    %PYTHON_CMD% -m venv "%ROOT%.venv"
    if errorlevel 1 (
      echo [FAIL] 가상환경 생성 실패
      exit /b 4
    )
  )
  set "PYTHON_CMD="%ROOT%.venv\Scripts\python.exe""
  set "INSTALL_SCOPE="
)

echo [1/2] 오프라인 인덱스에서만 설치한다 - 네트워크로 새지 않는다
echo       find-links: %PKG_DIR%
echo       constraint: %CONSTRAINT%
%PYTHON_CMD% -m pip install --no-index --find-links "%PKG_DIR%" --constraint "%CONSTRAINT%" -r "%REQUIREMENTS%" %INSTALL_SCOPE% > "%EV%\python-packages-install.txt" 2>&1
type "%EV%\python-packages-install.txt"

echo [2/2] 설치 확인 - 핵심 패키지 임포트
%PYTHON_CMD% -c "import pandas, numpy, lifelines, statsmodels, sklearn; print('IMPORT_OK', pandas.__version__, numpy.__version__, lifelines.__version__, statsmodels.__version__, sklearn.__version__)" > "%EV%\python-packages-check.txt" 2>&1
type "%EV%\python-packages-check.txt"

echo.
echo 증거는 %EV% 에 있다. 종료 코드가 아니라 아래 두 파일을 직접 확인하는 것이 판정 기준이다.
echo   evidence\python-packages-install.txt 마지막 줄이 "Successfully installed"로 끝나는지
echo   evidence\python-packages-check.txt 가 IMPORT_OK 로 시작하고 다섯 개 버전이 다 찍혔는지
goto :end

:load_config
rem cmd의 call은 .bat/.cmd 확장자만 배치로 취급한다. .env를 그대로 call하면
rem 아무 일도 하지 않고 errorlevel 0으로 돌아온다 - 2026-08-18 다른 스크립트에서
rem 실측된 문제: config.env의 모든 set이 무시되어 값이 끝내 비어 있었다.
rem 그래서 실행 가능한 .cmd 사본을 만들고 그것을 call한다. 사본은 매번
rem 원본에서 다시 만든다.
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
rem 이 스크립트는 번들 내장 임베디드 파이썬(bin\python\python.exe)을 쓰지
rem 않는다 - 임베디드 배포에는 pip이 없어 패키지를 설치할 수 없다(다른
rem .bat들이 그 파이썬을 최우선으로 쓰는 것과 의도적으로 다르다). 대상 PC의
rem 시스템 Python 3.12를 찾는다: py 런처를 먼저, 그다음 PATH의 python.
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
echo [FAIL] 시스템 Python 3.12를 찾지 못했다 - Python 3.12를 설치하거나 config.env의 PYTHON_CMD에 경로를 지정하라
exit /b 1

:end
endlocal
