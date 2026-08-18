# 폐쇄망 실행 안내

## 전제
- 관리자 권한 없이 압축 해제만으로 동작한다.
- 이 번들은 한 사용자 계정 전용이다. `home\agent` 에 세션과 툴 출력이 쌓이고 여기에는 작업한 소스 내용이 남는다.

## 순서
1. 번들을 `C:\pi_agent` 로 복사한다.
2. `config.env.example` 을 `config.env` 로 복사하고 `MODEL_FILE`, `MODEL_ALIAS`, `PI_MODEL_ID` 를 채운다.
3. `nvidia-smi` 로 GPU별 여유 VRAM을 보고 `GPU_TENSOR_SPLIT` 을 정한다. 비워두면 기본 분배를 쓴다. `1,1,1` 로 고정하지 않는다.
4. 창 하나에서 `start-llama.bat` 을 실행한다. 이 창은 서버가 사는 곳이므로 닫지 않는다.
5. 다른 창에서 `start-pi.bat` 을 실행한다. 모델이 준비되기 전에는 Pi가 뜨지 않는다.
   Pi는 **실행한 폴더를 작업 프로젝트로 삼으므로**, 코딩할 폴더로 먼저
   이동한 뒤 `C:\pi_agent\start-pi.bat` 을 절대 경로로 호출하라 — 번들 루트
   안에서 실행하면 그 폴더 자신이 작업 프로젝트가 되어 버린다.
6. `verify-offline.bat` 을 실행해 `evidence\` 에 증거를 남긴다.

`config.env` 는 현장에서 값을 채우는 파일이라 `STAGING_MANIFEST.json` 의 해시
범위에서 **제외**돼 있다. 값을 고쳐도 `verify-offline.bat` 의 무결성 검사는
조용해야 정상이다. 반대로 검사가 무언가를 지적하면 그것은 진짜 전송 손상이다.

## 모델 ID 두 개가 반드시 맞아야 한다

`config.env` 에는 이름이 비슷한 값이 둘 있다. 어긋나면 서버는 정상인데 Pi만
모델을 찾지 못한다.

| 값 | 누가 읽나 | 예 |
|---|---|---|
| `MODEL_ALIAS` | `llama-server` 의 `--alias`. `/v1/models` 에 이 이름으로 나타난다 | `qwen3.8-27b` |
| `PI_MODEL_ID` | Pi의 `--model`. `<제공자>/<MODEL_ALIAS>` 형식이다 | `local/qwen3.8-27b` |

`PI_MODEL_ID` 의 앞부분 `local` 은 번들 루트 `models.json` 이 선언하는 제공자
이름이고, 뒷부분은 `MODEL_ALIAS` 와 **글자 그대로 같아야 한다.**

### 왜 `models.json` 이 필요한가

`pi.exe` 에 내장된 llama.cpp 제공자는 llama-server가 **라우터 모드**로 떠
있기를 요구한다(`--models-dir` 로 띄우고 모델을 API로 적재하는 방식). 이
번들은 무인 기동의 결정성을 위해 `-m` 단일 모델 모드로 띄우므로 그 경로를 쓸
수 없다. 대신 번들 루트의 `models.json` 이 OpenAI 호환 엔드포인트를 제공자
`local` 로 **정적 선언**한다. `start-pi.bat` 과 `verify-offline.bat` 이 실행할
때마다 이 원본을 `home\agent\models.json` 으로 덮어쓰므로, 설정은 항상
매니페스트가 검증한 원본에서 나온다. `home\agent\models.json` 을 직접 고치지
마라 — 다음 실행에서 덮어써진다.

`LLAMA_PORT` 를 바꾸면 `models.json` 의 `baseUrl` 포트도 같이 바꿔야 한다.
`models.json` 은 정적 파일이라 환경변수를 읽지 않는다.

> **이 연결 방식은 리허설에서 처음 검증된다.** 정적 제공자 선언이 이 Pi
> 빌드에서 실제로 동작하는지는 윈도우에서 `pi.exe` 를 돌려봐야만 안다.

## 파이썬

`start-pi.bat` 과 `verify-offline.bat` 은 파이썬을 쓴다. 찾는 순서는
`config.env` 의 `PYTHON_CMD` → 번들 내장 `bin\python\python.exe` →
`py -3.12` → `python` 이다. 번들이 파이썬 3.12 임베디드 배포를 들고 다니므로
대상 PC에 파이썬이 없어도, Microsoft Store 앱 실행 별칭 스텁이 잡혀도 동작한다.

## 이미지로 에러 코드 입력하기 (비전 프로젝터)

`config.env`의 `MMPROJ_FILE`이 채워져 있으면(기본값이 이미 채워져 있다)
`start-llama.bat`이 `--mmproj`로 멀티모달로 뜬다. 스크린샷 속 에러 코드를
사진으로 넣고 싶을 때 쓴다. 이미지 입력이 필요 없거나 문제 원인을 좁힐
때는 `MMPROJ_FILE`을 비워 텍스트 전용으로 되돌린다.

- **대화형**: 이미지를 붙여넣을 때는 `Ctrl+V`가 아니라 **`Alt+V`** 를 쓴다
  (윈도우 전용 단축키). 터미널에 이미지 파일을 드래그해도 된다. 클립보드
  기능은 `pi-windows-x64.zip`에 같이 들어 있는 네이티브 애드온이 담당하므로
  별도 설치가 필요 없다.
- **비대화형**: `@파일` 참조를 쓴다.
  ```
  bin\pi\pi.exe --offline -p @screenshot.png "이 에러 코드가 무엇인지 설명하라"
  ```
- **이미지 입력이 안 될 때** 원인을 좁히는 순서: 먼저 `MMPROJ_FILE`을
  비우고 텍스트 전용으로 떠 본다. 그래도 안 되면 모델이 아니라 배선(Pi ↔
  llama-server 연결) 문제다.

## GPU가 안 잡힐 때
- `nvidia-smi` 의 드라이버가 551.61 미만이면 CUDA 12.4 빌드가 동작하지 않는다.
- **이 모델(Qwen3.8-27B, qwen35 아키텍처)에서 CUDA가 안 되면 폴백은 `cpu`뿐이다.
  `vulkan`으로 바꾸지 마라 — 금지다.** `bin\llama-vulkan`은 이 아키텍처의
  `ggml_ssm_conv`/`ggml_ssm_scan`을 구현하지 않았고, 조용히 CPU로 폴백하면서
  GPU↔CPU 경계에서 상태가 손상된다(상류 이슈 `ggml-org/llama.cpp#19957`,
  2026-02-27 open, 미해결). 결과는 손상된 출력이거나 `vk::DeviceLostError`다.
  `bin\llama-vulkan` 자체는 다른 모델에는 유효하므로 번들에서 빼지 않지만,
  이 모델에는 쓰지 않는다. `cpu`로 바꿔 원인을 좁힌다 — 느리지만 정확하다.
  30B 모델 실사용 속도가 나오지 않으므로 CPU는 진단용이다.
- `MSVCP140.dll` 관련 오류가 나면 `bin\llama-cuda` 안의 app-local DLL이 지워졌는지 확인한다.

## 하지 않는 것
- `pi install` 로 패키지나 확장을 설치하지 않는다. npm이 필요하고 폐쇄망에서는 동작하지 않는다.
- 모델을 새로 내려받지 않는다. 반입한 GGUF만 쓴다.
- `--host` 를 `127.0.0.1` 외의 값으로 바꾸지 않는다.

## Python 오프라인 패키지 설치 (통계·생존분석 스택)

`packages_win\` 는 Pi/llama-server와 무관한 별도 반입물이다 — 의료 데이터
통계 분석에 쓰는 pandas/lifelines/statsmodels/scikit-learn 등 Python 3.12
휠 155개(약 337MB)를 담는다. 조사 근거와 목록 선정 이유는
`.superpowers/sdd/2026-08-18-pi-agent-closed-network/python-wheelhouse-research.md`
에 있다.

**언제 돌리나**: Pi/llama-server 기동과는 독립적이다. 대상 PC에서 Python으로
통계 분석 코드를 돌리기 전에, 번들 반입 후 한 번 `win\install-python-packages.bat`
을 실행한다. 순서는 상관없다 — `start-llama.bat`/`start-pi.bat` 이전이든
이후든 무방하다.

**무엇이 설치되나**: `packages_win\requirements.txt`(범위 선언, 사람이 읽는
목록)와 `packages_win\constraints-py312.txt`(155개 전체 정확 핀)를 함께 써서
`packages_win\py312\`의 오프라인 휠만으로 설치한다. 패키지 전체 목록은
`packages_win\requirements.txt`를 보라 — 여기 다시 나열하지 않는다.

```
win\install-python-packages.bat        (대상 PC의 시스템 Python 3.12, --user 설치)
win\install-python-packages.bat venv   (번들 루트에 .venv 를 만들어 격리 설치)
```

이 스크립트는 번들 내장 임베디드 파이썬(`bin\python\python.exe`, pip 없음)을
쓰지 않는다 — **대상 PC에 이미 설치된 시스템 Python 3.12**가 있어야 한다.
`py -3.12`를 먼저 찾고, 없으면 `python`을 쓰고, 둘 다 없으면 명확히 실패한다
(`config.env`의 `PYTHON_CMD`로 경로를 직접 지정할 수도 있다 - 다른 `.bat`과
같은 변수를 공유한다).

`--no-index --find-links packages_win\py312 --constraint packages_win\constraints-py312.txt`
로만 설치하므로 네트워크로 새지 않는다.

**실패 시 볼 곳**: 종료 코드가 아니라 `evidence\` 의 두 파일이 판정 기준이다.
- `evidence\python-packages-install.txt` — pip 설치 로그 전체. 마지막 줄이
  `Successfully installed`로 끝나는지 확인한다.
- `evidence\python-packages-check.txt` — `pandas, numpy, lifelines,
  statsmodels, sklearn` 임포트 결과. `IMPORT_OK` 로 시작하고 다섯 개 버전이
  다 찍혀 있어야 한다. 비어 있거나 `Traceback`이 보이면 설치가 끝나지 않은
  것이다 — 위 install 로그에서 어느 패키지가 실패했는지 먼저 본다.
