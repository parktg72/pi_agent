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
set "VCRUNTIME_DIR=%ROOT%packages_win\vcruntime"
set "VENV_DIR=%ROOT%.venv"
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

rem 콘솔이 CP949이므로 파이썬 출력도 CP949로 고정한다. 파이썬 탐색 단계가
rem 이미 파이썬을 실행하므로 그보다 먼저 건다.
set "PYTHONIOENCODING=cp949"

call :resolve_python
if errorlevel 1 exit /b 4

rem 기본은 격리 설치(%ROOT%.venv)다. --user 설치는 %APPDATA%\Python\Python312\
rem site-packages 에 numpy/pandas를 심어 그 사용자의 **모든** Python 3.12 실행에
rem 영향을 준다 - 사내 스크립트가 numpy<2를 쓰고 있으면 즉시 깨지고 되돌리는
rem 절차도 없다. 그래서 격리를 기본값으로 두고, 전역을 바꾸는 쪽을 인자로
rem 명시하게 한다. venv는 매니페스트 해시 범위 밖이라(tools\manifest.py의
rem EXCLUDED_ROOTS) 만들어져도 무결성 검사가 깨지지 않는다.
rem   install-python-packages.bat          -> %ROOT%.venv 에 격리 설치 (기본)
rem   install-python-packages.bat --user   -> 전역 사용자 site-packages 에 설치
set "INSTALL_SCOPE="
set "USE_VENV=1"
if /I "%~1"=="--user" set "USE_VENV=0"
if /I "%~1"=="user" set "USE_VENV=0"
if /I "%~1"=="venv" set "USE_VENV=1"
if "%USE_VENV%"=="0" goto :scope_user

if not exist "%VENV_DIR%\Scripts\python.exe" (
  echo [info] 가상환경 생성 중 - %VENV_DIR%
  %PYTHON_CMD% -m venv "%VENV_DIR%"
  if errorlevel 1 (
    echo [FAIL] 가상환경 생성 실패 - %VENV_DIR%
    exit /b 4
  )
)
set "PYTHON_CMD="%VENV_DIR%\Scripts\python.exe""
set "CHECK_CMD="%VENV_DIR%\Scripts\python.exe""
call :validate_python
if errorlevel 1 exit /b 4
echo [1/4] 설치 대상: 가상환경 %VENV_DIR% (격리 - 시스템 파이썬 환경을 건드리지 않는다)
echo       분석 코드를 돌릴 때는 %VENV_DIR%\Scripts\python.exe 를 쓴다.
echo       Jupyter 등 실행 파일은 %VENV_DIR%\Scripts\ 에 놓인다.
goto :scope_done

:scope_user
set "INSTALL_SCOPE=--user"
echo [1/4] 설치 대상: 전역 사용자 site-packages (--user)
echo [warn] --user 설치는 %%APPDATA%%\Python\Python312\site-packages 에 패키지를 심어
echo        이 사용자 계정의 **모든** Python 3.12 실행에 영향을 준다. 사내 스크립트가
echo        다른 numpy/pandas 버전을 쓰고 있으면 그 즉시 깨지고, 되돌리는 절차는 없다.
echo        격리하려면 인자 없이 다시 실행하라 - 기본값이 %VENV_DIR% 격리 설치다.
echo        실행 파일(jupyter 등)은 %%APPDATA%%\Python\Python312\Scripts 에 놓인다.
goto :scope_done

:scope_done

echo [2/4] 오프라인 인덱스에서만 설치한다 - 네트워크로 새지 않는다
echo       find-links: %PKG_DIR%
echo       constraint: %CONSTRAINT%
%PYTHON_CMD% -m pip install --no-index --find-links "%PKG_DIR%" --constraint "%CONSTRAINT%" -r "%REQUIREMENTS%" %INSTALL_SCOPE% --no-warn-script-location > "%EV%\python-packages-install.txt" 2>&1
type "%EV%\python-packages-install.txt"

echo [3/4] lightgbm용 VC 런타임 배치
call :place_vcruntime

echo [4/4] 설치 확인 - requirements.txt의 직접 의존을 하나씩 임포트한다
%PYTHON_CMD% "%ROOT%tools\check_imports.py" --requirements "%REQUIREMENTS%" > "%EV%\python-packages-check.txt" 2>&1
type "%EV%\python-packages-check.txt"

echo.
echo 증거는 %EV% 에 있다. 종료 코드가 아니라 아래 두 파일을 직접 확인하는 것이 판정 기준이다.
echo   evidence\python-packages-install.txt 마지막 줄이 "Successfully installed"로 끝나는지
echo   evidence\python-packages-check.txt 의 마지막 줄이 IMPORT_OK 이고 FAIL 줄이 없는지
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

:place_vcruntime
rem lightgbm 휠은 lib_lightgbm.dll이 요구하는 VCOMP140.DLL과 MSVCP140.dll을
rem 벤더링하지 않는다(scikit-learn은 sklearn\.libs\ 에 자체 동봉해 무사하다).
rem 번들의 VC 런타임 3종은 bin\llama-*\ 안 app-local이라 파이썬 프로세스의
rem 검색 경로에 없다. 그래서 sklearn이 하는 것과 같은 app-local 방식으로,
rem 설치된 lightgbm\bin\ 옆에 같은 두 DLL을 놓는다. 파이썬 3.8 이상의
rem ctypes는 경로로 DLL을 열 때 LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR을 켜므로
rem 그 DLL 자신의 폴더에서 의존 DLL을 찾는다.
rem 설치 위치는 venv/--user에 따라 다르므로 파이썬에게 직접 묻는다.
rem find_spec은 모듈을 실행하지 않는다 - 지금은 DLL이 없어서 import lightgbm
rem 자체가 실패할 수 있으므로 임포트로 경로를 물으면 안 된다.
if not exist "%VCRUNTIME_DIR%" (
  echo [warn] %VCRUNTIME_DIR% 없음 - lightgbm이 VCOMP140.DLL을 찾지 못할 수 있다
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
echo       app-local 배치 완료: %LGB_DIR%\bin
goto :eof
:place_vcruntime_missing
echo [warn] lightgbm의 설치 위치를 찾지 못해 VC 런타임을 놓지 못했다
echo        아래 [4/4]에서 lightgbm 줄이 FAIL로 나오면 이것이 원인이다.
echo        경로 조회 결과: evidence\lightgbm-location.txt
goto :eof

:validate_python
rem CHECK_CMD에 담긴 파이썬이 (a) Python 3.12이고 (b) pip을 가졌는지 본다.
rem 둘 중 하나라도 아니면 무엇이 문제인지 말하고 종료한다. config.env의
rem PYTHON_CMD로 지정된 파이썬도 이 검사를 통과해야 한다.
%CHECK_CMD% -c "import sys" >nul 2>&1
if errorlevel 1 (
  echo [FAIL] 파이썬을 실행하지 못했다: %CHECK_CMD%
  echo        config.env의 PYTHON_CMD가 잘못됐거나 그 경로에 실행 파일이 없다.
  exit /b 1
)
%CHECK_CMD% -c "import sys; sys.exit(0 if sys.version_info[:2] == (3, 12) else 1)" >nul 2>&1
if errorlevel 1 (
  echo [FAIL] Python 3.12가 아니다: %CHECK_CMD%
  echo        packages_win\py312 의 휠 155개는 전부 cp312 win_amd64 전용이라
  echo        다른 버전으로는 "not a supported wheel"로 전부 실패한다.
  echo        실제 버전:
  %CHECK_CMD% -c "import sys; print(sys.version)"
  exit /b 1
)
%CHECK_CMD% -c "import pip" >nul 2>&1
if errorlevel 1 (
  echo [FAIL] 이 파이썬에는 pip이 없다: %CHECK_CMD%
  echo        번들 내장 임베디드 배포^(bin\python\python.exe^)에는 pip이 없다.
  echo        config.env의 PYTHON_CMD에 그 경로를 적었다면 지워라 - 이 스크립트
  echo        하나만은 다른 .bat들과 달리 대상 PC의 **시스템** Python 3.12를 쓴다.
  exit /b 1
)
goto :eof

:resolve_python
rem 이 스크립트는 번들 내장 임베디드 파이썬(bin\python\python.exe)을 쓰지
rem 않는다 - 임베디드 배포에는 pip이 없어 패키지를 설치할 수 없다(다른
rem .bat들이 그 파이썬을 최우선으로 쓰는 것과 의도적으로 다르다). 대상 PC의
rem 시스템 Python 3.12를 찾는다: py 런처를 먼저, 그다음 PATH의 python.
rem PYTHON_CMD가 config.env로 지정돼 있으면 그것을 쓰되, 검사를 건너뛰지
rem 않는다 - 예전에는 여기서 곧바로 goto :eof 했기 때문에 임베디드 파이썬
rem 경로가 적혀 있으면 pip 없는 파이썬으로 설치를 시도했다.
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
echo [FAIL] 시스템 Python 3.12를 찾지 못했다 - py -3.12 도 python 도 실행되지 않는다.
echo        Python 3.12를 설치하거나 config.env의 PYTHON_CMD에 경로를 지정하라.
echo        번들 내장 bin\python\python.exe 는 여기에 쓸 수 없다 - pip이 없다.
exit /b 1

:resolve_python_configured
echo [info] config.env의 PYTHON_CMD를 쓴다: %PYTHON_CMD%
goto :resolve_python_validate

:resolve_python_validate
set "CHECK_CMD=%PYTHON_CMD%"
call :validate_python
if errorlevel 1 exit /b 1
goto :eof

:end
endlocal
