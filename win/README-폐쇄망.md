# 폐쇄망 실행 안내

## 전제
- 관리자 권한 없이 압축 해제만으로 동작한다.
- 이 번들은 한 사용자 계정 전용이다. `home\agent` 에 세션과 툴 출력이 쌓이고 여기에는 작업한 소스 내용이 남는다.

## 순서

| # | 실행할 것 | 언제 | 창 |
|---|---|---|---|
| 0 | 번들을 `C:\pi_agent` 로 복사 | 최초 1회 | — |
| 1 | `bin\python\python.exe tools\verify_bundle.py --root .` | 최초 1회 | 아무 창 |
| 2 | `config.env` 의 `GPU_TENSOR_SPLIT` 채우기 | 최초 1회 | — |
| 3 | `install-python-packages.bat` | 파이썬 작업이 필요할 때만 | 아무 창 |
| 4 | `start-llama.bat` | **매번**, 가장 먼저 | 전용 창 — 닫지 않는다 |
| 5 | `start-pi.bat` | **매번**, 4번 다음 | 작업 폴더에서 |
| 6 | `verify-offline.bat` | 최초 1회 + 문제 생겼을 때 | 아무 창 |

**매번 반복되는 것은 4→5 둘뿐이다.** 나머지는 처음 한 번이다.

**1 — 무결성 검사가 먼저다.** 전송 중 손상은 여기서만 잡힌다. 출력의 파일 수가
`STAGING_MANIFEST.json` 의 `totals.files` 와 같아야 한다. 다르면 **거기서 멈추고
다시 복사한다** — 뒤 단계는 전부 무의미해진다.

**2 — 현장에서 채울 값은 `GPU_TENSOR_SPLIT` 하나다.** 나머지(`MODEL_FILE`,
`MODEL_ALIAS`, `PI_MODEL_ID`, `MMPROJ_FILE`, `MODEL_LOAD_TIMEOUT`)는 반입 시점에
이미 채워져 있다. `nvidia-smi` 로 GPU별 여유 VRAM을 보고 그 비율을 넣는다.
비워두면 llama.cpp 기본 분배를 쓴다. `1,1,1` 로 고정하지 않는다 — 디스플레이가
붙은 GPU의 실여유가 다른 두 장보다 적다.

**3 — 기본이 격리 설치다.** 인자 없이 실행하면 `C:\pi_agent\.venv` 에 깔린다.
`--user` 는 그 계정의 **모든** Python 3.12 에 영향을 준다(아래 "왜 격리가
기본인가" 참고). 코딩 에이전트만 쓸 거면 이 단계는 건너뛰어도 된다.

**4 — 이 창은 서버가 사는 곳이므로 닫지 않는다.**

**5 — 코딩할 폴더에서 절대 경로로 부른다.**

```
cd D:\작업폴더
C:\pi_agent\start-pi.bat
```

Pi는 **실행한 폴더를 작업 프로젝트로 삼는다.** 번들 루트 안에서 실행하면
`C:\pi_agent` 자신이 프로젝트가 되어 정작 작업 대상을 못 본다. 모델이
준비되기 전에는 Pi가 뜨지 않으므로, 4번을 건너뛰면 여기서 기다리다 실패한다.

**6 — 판정은 종료 코드가 아니라 `evidence\` 안의 내용이다.** 넷을 확인한다.

| 파일 | 통과 기준 |
|---|---|
| `manifest-check.txt` | 매니페스트와 일치 |
| `v1-models.json` | `qwen3.8-27b` 가 있다 |
| `pi-tool-roundtrip.json` | 최종 답변에 `NARWHAL-7Q2X` 가 있다 |
| `pi-packages.txt` | 확장·스킬 4종이 나열된다 |

`pi-tool-roundtrip.json` 의 낱말은 스크립트가 직접 쓴 프로브 파일에서 온다 —
모델이 파일을 못 읽고 지어냈다면 그 낱말이 나올 수 없다.

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

**`install-python-packages.bat` 만은 이 순서를 따르지 않는다.** 임베디드
배포에는 pip이 없어서 패키지를 설치할 수 없기 때문이다 — 그 스크립트는 대상
PC의 시스템 Python 3.12를 쓰고, `PYTHON_CMD` 로 지정된 것도 3.12인지와 pip이
있는지를 검사한 뒤에야 쓴다. 아래 "Python 오프라인 패키지 설치" 절을 보라.

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

## Pi 확장·스킬 (pi-packages)

`pi-packages\` 에는 인터넷이 되는 윈도우 PC에서 `pi install` 로 미리 설치해
반입한 확장·스킬 트리가 들어 있다(조사 근거:
`.superpowers/sdd/2026-08-18-pi-agent-closed-network/pi-packages-research.md`).
`pi.exe` 는 Bun으로 컴파일된 자기완결 바이너리라 확장을 로드하는 시점에는
npm/git이 전혀 필요 없다 — npm/git은 오직 **설치할 때만** 쓰이고, 이미 설치된
트리가 `PI_CODING_AGENT_DIR\npm\`, `\git\` 구조로 놓여 있으면 그대로 읽는다.
그래서 대상 PC에서 다시 설치하지 않고, 설치가 끝난 결과물을 통째로 실어
왔다. `start-pi.bat` 이 실행할 때마다 `pi-packages\` 를 `home\agent\` 로
동기화한다(models.json과 같은 관용구 — 매니페스트가 검증한 원본에서 항상
다시 채운다).

| 패키지 | 하는 일 |
|---|---|
| `git:github.com/obra/superpowers@v6.3.0` | 브레인스토밍·계획 작성·TDD·체계적 디버깅·코드 리뷰 요청/수신·작업분해 등 11종 스킬과, 세션 시작 시 `using-superpowers` 스킬을 시스템 컨텍스트에 자동 주입하는 부트스트랩 확장 |
| `npm:pi-subagents@0.50.0` | `subagent` 툴 — `scout`/`worker`/`reviewer`/`oracle`/`delegate`/`researcher` 내장 서브에이전트로 자식 Pi 세션에 위임한다. superpowers 확장이 이름까지 지목하며 전제로 깔아 둔 툴이다. `researcher` 페르소나는 웹 검색을 전제로 하므로 폐쇄망에서는 무용하다 — 나머지 5개는 로컬 모델 호출만 하므로 유효하다. **단, 포어그라운드 위임만 된다** — 아래 참고 |
| `npm:@juicesharp/rpiv-todo@2.6.1` | `/reload`·컴팩션에도 살아남는 라이브 todo 오버레이. superpowers 확장이 "설치된 todo 툴이 있으면 쓰라"고 안내하는 공백을 메운다 |
| `npm:@juicesharp/rpiv-ask-user-question@2.6.1` | 모델이 모호할 때 추측 대신 구조화된 객관식 질문을 사용자에게 던지는 툴 |

### 서브에이전트: 포어그라운드는 되고 백그라운드는 안 된다

`pi-subagents` 의 두 위임 경로는 서로 다른 실행 파일을 쓴다.

- **포어그라운드 위임(기본)** — 자식 세션을 `pi.exe` 자신으로 띄운다.
  Node가 필요 없으므로 폐쇄망에서 **동작한다.**
- **백그라운드/`async` 위임** — 러너를 `node.exe` 로 띄운다. 폐쇄망 PC에는
  Node가 없으므로 프로세스 생성이 `ENOENT` 로 **실패한다.** 로그에
  `[pi-subagents] async spawn failed: ... ENOENT` 류 메시지가 남는다.
  이것은 설정 실수가 아니라 이 번들의 구조적 한계다 — Node를 반입하지
  않는 결정의 결과다.

동시 요청은 폭주하지 않는다. `start-llama.bat` 이 `--parallel 1` 로
띄우므로 llama-server는 요청을 한 번에 하나씩 처리한다. 포어그라운드
위임을 여러 개 겹치면 응답이 뒤섞이는 것이 아니라 **지연이 그만큼
길어지고**, 재시도와 겹쳐 타임아웃처럼 보인다. 위임은 하나씩 하는 것이
이 구성에서 가장 빠르다.

**`pi install` 은 폐쇄망 PC에서 쓰지 않는다.** npm/git 네트워크 호출이
필요하므로 폐쇄망에서는 동작하지 않는다 — 반입한 `pi-packages\` 가 이미 그
결과물이다. 패키지를 추가/교체하려면 인터넷이 되는 윈도우 PC에서 다시
설치하고 `pi-packages\` 를 통째로 다시 실어 와야 한다.

**확장을 끄고 싶을 때**: 스킬/서브에이전트 없이 순수 모델 대화만 필요하면
`pi.exe` 호출에 플래그를 더한다.
```
bin\pi\pi.exe --offline --model %PI_MODEL_ID% --no-extensions --no-skills
```
`--no-extensions` 는 확장 발견 자체를 끄고(브레인스토밍 자동 주입, subagent
툴, todo 오버레이, ask-user-question 툴이 전부 사라진다), `--no-skills` 는
스킬 발견만 끈다(`/skill:이름` 으로 직접 지정한 스킬은 그래도 로드된다).
`start-pi.bat` 은 이 두 플래그를 기본으로 넣지 않으므로, 끄고 싶을 때는
직접 인자를 붙여 실행하거나(`start-pi.bat --no-extensions --no-skills` —
`%*` 로 그대로 전달된다) `bin\pi\pi.exe` 를 직접 호출한다.

`home\agent\settings.json` 은 사용자가 `/trust`, `/settings` 로 직접 고칠 수
있는 파일이라 models.json과 달리 **처음 한 번만** 채워진다(이미 있으면
건드리지 않는다) — 패키지 목록을 지웠다가 되살리고 싶으면 그 파일을 직접
지우고 `start-pi.bat` 을 다시 실행한다.

그래서 번들을 새 판으로 갈아 끼울 때 문제가 생긴다: v2 번들이 패키지를
추가해도 기존 `settings.json` 이 있으면 그 항목은 조용히 등록되지 않고,
`xcopy /D` 는 상류에서 삭제된 파일을 지우지도 않는다. `start-pi.bat` 과
`verify-offline.bat` 은 실행할 때마다 번들의 목록과 `settings.json` 의 목록을
대조해 **다르면 경고만** 출력한다(`[warn] home\agent\settings.json의 패키지
목록이 번들과 다르다`). 자동으로 덮어쓰지는 않는다 — 운영자가 편집할 수 있는
파일이기 때문이다. 번들 목록으로 되돌리려면 `home\agent\settings.json` 을
지우고 다시 실행하거나, 직접 고친 설정이 있으면 그 파일의 `packages` 배열만
손으로 맞춘다.

## 하지 않는 것
- `pi install` 로 패키지나 확장을 새로 설치하지 않는다. npm이 필요하고
  폐쇄망에서는 동작하지 않는다 — 반입한 `pi-packages\` 를 쓴다(위 절 참고).
- 모델을 새로 내려받지 않는다. 반입한 GGUF만 쓴다.
- `--host` 를 `127.0.0.1` 외의 값으로 바꾸지 않는다.

## Python 오프라인 패키지 설치 (통계·생존분석 스택)

`packages_win\` 는 Pi/llama-server와 무관한 별도 반입물이다 — 의료 데이터
통계 분석에 쓰는 pandas/lifelines/statsmodels/scikit-learn 등 Python 3.12
휠 155개(약 337MB)를 담는다. 조사 근거와 목록 선정 이유는
`.superpowers/sdd/2026-08-18-pi-agent-closed-network/python-wheelhouse-research.md`
에 있다.

**언제 돌리나**: Pi/llama-server 기동과는 독립적이다. 대상 PC에서 Python으로
통계 분석 코드를 돌리기 전에, 번들 반입 후 한 번 `install-python-packages.bat`
을 실행한다(다른 `.bat`과 같이 번들 **루트**에 있다 — `win\`은 매니페스트 해시
범위 밖이라 반입된 PC에 그 디렉터리가 아예 없을 수 있다). 순서는 상관없다 —
`start-llama.bat`/`start-pi.bat` 이전이든 이후든 무방하다.

**무엇이 설치되나**: `packages_win\requirements.txt`(범위 선언, 사람이 읽는
목록)와 `packages_win\constraints-py312.txt`(155개 전체 정확 핀)를 함께 써서
`packages_win\py312\`의 오프라인 휠만으로 설치한다. 패키지 전체 목록은
`packages_win\requirements.txt`를 보라 — 여기 다시 나열하지 않는다.

```
install-python-packages.bat          (기본 — 번들 루트에 .venv 를 만들어 격리 설치)
install-python-packages.bat --user   (전역 사용자 site-packages 에 설치)
```

### 왜 격리(`.venv`)가 기본인가

`--user` 설치는 `%APPDATA%\Python\Python312\site-packages` 에 numpy·pandas를
심는다. 그 경로는 그 사용자 계정의 **모든** Python 3.12 실행에 자동으로
들어가므로, 사내 스크립트가 `numpy<2`를 쓰고 있으면 이 설치 하나로 즉시
깨진다. 그리고 되돌리는 절차는 이 번들에 없다. 통계 분석 스택을 반입하는
것이 목적이지 대상 PC의 파이썬 환경을 바꾸는 것이 목적이 아니므로,
**아무 인자 없이 실행하면 번들 루트에 `.venv` 를 만들어 그 안에만 설치한다.**

- 분석 코드는 `.venv\Scripts\python.exe` 로 돌린다. Jupyter 등 실행 파일은
  `.venv\Scripts\` 에 놓인다.
- `.venv` 는 `STAGING_MANIFEST.json` 의 해시 범위 **밖**이다(`config.env` 와
  같은 이유 — 대상 PC에서 생기는 가변 영역이다). 설치 후에도
  `verify-offline.bat` 의 무결성 검사는 조용해야 정상이다.
- 지우고 다시 만들려면 `.venv` 폴더를 통째로 지우고 다시 실행하면 된다.

**`--user` 를 쓸 때 감수하는 것**: 위에 적은 전역 영향이 그대로 발생한다.
이미 그 계정에 다른 버전의 numpy/pandas가 있으면 이 설치가 그것을 덮어쓰고,
같은 계정의 다른 파이썬 작업이 바뀐 버전을 보게 된다. 실행 파일은
`%APPDATA%\Python\Python312\Scripts` 에 놓이는데 이 경로는 보통 `PATH` 에
없으므로, `jupyter` 등을 이름만으로 실행하려면 그 폴더를 `PATH` 에 넣거나
`python -m jupyterlab` 처럼 모듈로 실행한다. 스크립트가 그 경로를 콘솔에
찍어 주므로 그대로 보면 된다. 필요할 때만 골라 쓰고, 기본은 격리를 쓴다.

### 이 스크립트가 쓰는 파이썬

이 스크립트 **하나만은** 다른 `.bat` 들과 반대로 번들 내장 임베디드
파이썬(`bin\python\python.exe`)을 쓰지 않는다 — 그 배포에는 pip이 없어서
패키지를 설치할 수 없다. **대상 PC에 이미 설치된 시스템 Python 3.12**가
있어야 한다. `py -3.12` 를 먼저 찾고, 없으면 `python` 을 쓴다.

찾은 파이썬은(그리고 `config.env` 의 `PYTHON_CMD` 로 **지정한** 파이썬도)
다음 둘을 반드시 통과해야 한다. 하나라도 아니면 무엇이 문제인지 말하고
멈춘다.

1. `sys.version_info[:2] == (3, 12)` — `packages_win\py312` 의 휠 155개는
   전부 cp312 win_amd64 전용이다. 3.13에서 돌리면 155개가 전부
   "not a supported wheel"로 실패한다.
2. `import pip` — 임베디드 배포를 지정했을 때 여기서 걸린다.

> `config.env` 의 `PYTHON_CMD` 는 모든 `.bat` 이 공유하는 변수지만, **이
> 스크립트에서만 의미가 다르다.** 다른 `.bat` 은 비워 두면 번들 내장
> 파이썬을 먼저 쓰는데, 이 스크립트는 그 파이썬을 쓸 수 없다. 그래서
> `PYTHON_CMD` 에 `bin\python\python.exe` 를 적어 두면 이 스크립트는
> "pip이 없다"며 멈춘다 — 그때는 그 값을 비우거나, 시스템 Python 3.12의
> 경로를 적어라.

`--no-index --find-links packages_win\py312 --constraint packages_win\constraints-py312.txt`
로만 설치하므로 네트워크로 새지 않는다.

### lightgbm과 VC 런타임

`lightgbm` 휠 안의 `lib_lightgbm.dll` 의 실제 import 테이블에는 `MSVCP140.dll`,
`VCOMP140.DLL`(OpenMP), `VCRUNTIME140.dll`, `VCRUNTIME140_1.dll` 4종이 있는데
(실측, 2026-08-18) 휠은 이 중 무엇도 동봉하지 않는다(scikit-learn은
`sklearn\.libs\` 에 4종을 전부 자체 동봉해서 무사하다). **우리가 반입한 것은
앞의 2종(`VCOMP140.DLL`, `MSVCP140.dll`)뿐이다** — 번들의 VC 런타임 3종
(`bin\llama-*\` 안 app-local)은 파이썬 프로세스의 검색 경로에 없어서 쓸 수
없다. 나머지 `VCRUNTIME140.dll`, `VCRUNTIME140_1.dll` 2종은 대상 PC의
**시스템 Python 3.12 설치본**이 `Python312\VCRUNTIME140.dll`(과 짝 파일)로
동봉하는 것을 그대로 쓴다(로드 경로 실측 확인, 2026-08-18). 위험은 낮지만
이 전제에 기댄다 — Python 3.12를 표준 python.org 설치본이 아닌 다른 경로
(VC 런타임을 자체 동봉하지 않는 포터블 배포 등)로 넣으면 이 두 DLL이 없을
수 있고, 그러면 `import lightgbm` 이전에 OS 로더 단계에서 실패한다.

그래서 `packages_win\vcruntime\` 에는 우리가 반입해야 하는 2종
(`VCOMP140.DLL`, `MSVCP140.dll`)만 실어 왔고, 설치 스크립트가 설치된
`lightgbm\bin\` 옆에 같은 app-local 방식으로 복사한다. 설치 위치는
격리/`--user` 에 따라 다르므로 파이썬에게 직접 물어 찾는다.

**실패 시 볼 곳**: 종료 코드가 아니라 `evidence\` 의 두 파일이 판정 기준이다.
- `evidence\python-packages-install.txt` — pip 설치 로그 전체. 마지막 줄이
  `Successfully installed`로 끝나는지 확인한다.
- `evidence\python-packages-check.txt` — `packages_win\requirements.txt` 가
  선언한 **직접 의존 전부**를 하나씩 임포트한 결과다. 패키지마다 `OK` 또는
  `FAIL` 한 줄씩 남고 마지막 줄이 `IMPORT_OK` 여야 한다. `FAIL` 줄이 하나라도
  있으면 그 줄이 어느 패키지인지와 예외 메시지를 그대로 알려 준다 — 위
  install 로그에서 그 패키지가 실제로 설치됐는지 먼저 본다. `lightgbm` 만
  `FAIL` 이면 위의 VC 런타임 배치가 실패한 것이다(`[warn]` 메시지와
  `evidence\lightgbm-location.txt` 를 본다).
