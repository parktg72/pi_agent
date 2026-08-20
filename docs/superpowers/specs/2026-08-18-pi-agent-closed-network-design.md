# Pi 코딩 에이전트 폐쇄망 윈도우 배포 설계

작성일: 2026-08-18
상태: **구현 완료, 현장 리허설 미수행** (2026-08-20 갱신). 스테이징(`H:\model\pi_agent`)과 `.bat`·도구·테스트는 모두 있고 229개 테스트가 통과한다. GPU가 달린 PC에서의 실기 리허설(`docs/superpowers/plans/rehearsal-2026-08-18.md`)은 아직 수행하지 않았다 — 즉 실제 GGUF를 적재한 llama-server와 Pi의 왕복은 이 저장소에서 아직 관측된 적이 없다.
리뷰: OpenCode / GPT-5.6 Sol (herdr `wF:p2`), 서브에이전트 4종 분산 조사. 전체 판정 `conditional`, 조건은 아래 6개 항목으로 반영 완료.
재리뷰: 2026-08-19 GPT-5.6 Sol 독립 감사, 판정 **수정 전 NO-GO** — "현재 검증 체계는 실패를 성공으로 승인할 수 있다". 지적 5건(실패의 exit 0 보고, 포트 이중 정의, `config.env`의 CMD 실행, 위험 백엔드가 문서로만 금지, 앵커만 보는 패키지 동기화)은 2026-08-20 `feature/fail-loudly`에서 고쳤다. 인수인계 기록은 `docs/superpowers/plans/handoff-2026-08-20.md`.

## 1. 목표

인터넷이 전혀 없는 윈도우 PC에서 Pi 코딩 에이전트(`@earendil-works/pi-coding-agent` v0.84.2)를 실행한다. 모델은 같은 PC에서 llama.cpp로 서빙한다. 외부 API 호출은 없다.

## 2. 제약

- 반입 매체: H: 드라이브. WSL에서는 `/mnt/h`(v9fs), 스테이징 위치 `H:\model\pi_agent`, 폐쇄망 PC 배치 위치 `C:\pi_agent`.
- GPU: GTX 1080 Ti (Pascal, compute capability 6.1) 3장, 장당 11GB, 합계 33GB. NVLink 없음.
- 관리자 권한을 가정하지 않는다. 설치 프로그램 실행이 아니라 압축 해제로 완결되어야 한다.
- 사내 배포 관례를 따른다: 스테이징 매니페스트(파일 수·바이트·SHA256) + 실행 `.bat`.

## 3. 확인된 사실과 근거

측정 일자 2026-08-17~18. 각 항목은 재현 가능한 방법으로 확인했다.

### 3.1 Pi 윈도우 바이너리는 자기완결이다

`pi-windows-x64.zip` (45,470,989 bytes, SHA256 `741fc1ae1afecb573ac2888e011188ff446b3940f4aabe1583f60bf55be8a3d0`) — 릴리스가 제공하는 `SHA256SUMS`와 대조 일치.

내용물 250개 중 `pi.exe`가 108,654,592 bytes로 런타임을 내장한다. import 테이블에 OS DLL만 나타난다:

```
KERNEL32.dll  OLEAUT32.dll  SHELL32.dll  USER32.dll  USERENV.dll
api-ms-win-core-synch-l1-2-0.dll  ntdll.dll
```

따라서 폐쇄망 PC에 **Node.js 설치가 불필요하고, VC++ 재배포 패키지도 Pi에는 필요 없다**. 다만 Pi의 패키지/확장 설치 기능(`pi install`)은 npm을 요구하므로 이 배포에서는 사용하지 않는다.

### 3.2 오프라인 스위치는 Pi 자신의 시작 시 네트워크 동작을 끈다

`PI_OFFLINE=1` 또는 `--offline`이 버전 체크(`pi.dev/api/latest-version`), 설치 텔레메트리(`pi.dev/api/report-install`), 패키지 업데이트 체크를 차단한다. 상류 문서 기준.

이것은 프로세스 전체의 아웃바운드가 0이라는 보장이 아니다. 그 증명은 §8의 네트워크 증거 수집이 담당한다.

### 3.3 llama.cpp는 CUDA 12.4 빌드만 쓸 수 있다

세 단계로 확인했다.

1. CUDA 13.0이 Maxwell/Pascal/Volta의 오프라인 컴파일·라이브러리 지원을 제거했다. 1080 Ti는 Pascal(6.1)이다.
2. llama.cpp 릴리스 워크플로는 `GGML_NATIVE=OFF`로 빌드하고, `ggml/src/ggml-cuda/CMakeLists.txt`는 `CUDAToolkit_VERSION < 13`일 때만 `50-virtual 61-virtual 70-virtual`을 추가한다.
3. 따라서 CUDA 12.4 빌드에만 Pascal용 PTX가 있고 드라이버가 로드 시 JIT 컴파일한다. **cuda-13.3 자산은 1080 Ti에서 쓸 수 없다.**

이 판단은 b10470 릴리스가 제공하는 자산 선택지 안에서의 결론이다. CUDA 12.x 전체를 배제한다는 뜻은 아니다.

### 3.4 배포 zip은 이미 자기완결이다 — 병합 불필요

초기 설계는 CPU zip + CUDA zip + cudart zip 3개 병합을 전제했으나 **틀렸다**. 릴리스 잡이 발행 직전 CPU 백엔드를 다른 모든 윈도우 zip에 넣는다:

```yaml
for target_zip in artifact/llama-bin-win-*-${arch}.zip; do
  (cd "$temp_dir" && zip -r "$realpath_target_zip" .)
```

실제 자산 `llama-b10470-bin-win-cuda-12.4-x64.zip`(250,799,028 bytes, SHA256 `e6f3fa9790ab7684ded44ade774dc94742ddb99e4b0abaf1603dab4f3d0803d3`)을 받아 확인한 결과 52개 파일에 `llama-server.exe`, `ggml-cuda.dll`, `ggml-base.dll`, `ggml-cpu-*.dll` 15종, `libomp140.x86_64.dll`이 모두 들어 있다.

필요한 자산은 **CUDA 빌드 zip + 짝이 맞는 cudart zip** 두 개다. cudart가 여전히 필요한 이유는 `ggml-cuda.dll`이 `cudart64_12.dll`, `cublas64_12.dll`, `nvcuda.dll`을 import하기 때문이다(`nvcuda.dll`은 드라이버가 제공).

### 3.5 llama.cpp 쪽은 VC++ 런타임이 필요하다

import 테이블 실측:

| 바이너리 | VC++ 런타임 의존 |
|---|---|
| `pi.exe` | 없음 |
| `llama-server.exe` | `VCRUNTIME140.dll` |
| `ggml-cuda.dll` | `MSVCP140.dll`, `VCRUNTIME140.dll`, `VCRUNTIME140_1.dll` |
| `ggml-base.dll` | `MSVCP140.dll`, `VCRUNTIME140.dll` |

관리자 권한 없이 재배포 패키지를 설치할 수 없는 상황을 가정하므로, 이 3개 DLL을 **app-local**로 `bin\llama-cuda\`에 함께 둔다. 현장에서 시스템에 이미 존재하면 그쪽이 우선한다.

### 3.6 드라이버 요구사항

CUDA 12.4 GA의 윈도우 최소 드라이버는 551.61이다. 폐쇄망 PC의 `nvidia-smi`가 그 이상이면 된다. 특정 버전으로 고정할 필요는 없다.

## 4. 번들 레이아웃

```
H:\model\pi_agent\            →  폐쇄망 PC의 C:\pi_agent\
├── bin\
│   ├── pi\                   pi-windows-x64.zip 해제 (pi.exe 등)
│   ├── llama-cuda\           CUDA 12.4 zip + cudart 12.4 zip + VC++ DLL 3종
│   ├── llama-vulkan\         Vulkan 빌드 (폴백, 독립 디렉터리)
│   ├── llama-cpu\            CPU 빌드 (진단용, 독립 디렉터리)
│   └── python\               Python 3.12 임베디드 배포 (.bat이 쓰는 파이썬)
├── models\                   GGUF
├── packages_win\             Python 3.12 오프라인 휠하우스 (Pi/llama-server와 독립)
│   ├── py312\                 *.whl 155개, win_amd64 cp312 (`--only-binary=:all:`로만 반입)
│   ├── vcruntime\             VCOMP140.DLL, MSVCP140.dll — lightgbm용 app-local (§13 아님, 아래 설명)
│   ├── requirements.txt       사람이 읽는 최상위 목록 (범위 선언)
│   └── constraints-py312.txt  155개 전체 정확 핀 (진실 출처는 휠셋 — §9 참고)
├── pi-packages\              사전 설치한 Pi 확장·스킬 트리 (§13)
│   ├── npm\node_modules\      pi-subagents, rpiv-todo, rpiv-ask-user-question 등
│   ├── git\github.com\        superpowers 클론 (.git 포함 — 숨김 속성)
│   └── settings.packages.json  packages 배열 정본의 배치본 (win\ 이 정본)
├── home\agent\               PI_CODING_AGENT_DIR — 설정·세션 (가변)
├── evidence\                 검증 산출물 (가변)
├── .venv\                    install-python-packages.bat의 기본 설치 대상 (가변, 대상 PC에서 생성)
├── start-llama.bat
├── start-pi.bat
├── verify-bundle.bat          tools\verify_bundle.py를 콘솔 인코딩(chcp 65001)까지 걸어 호출
├── verify-offline.bat
├── install-python-packages.bat  packages_win\ 를 대상 PC 시스템 Python 3.12에 오프라인 설치
├── config.env                운영자가 현장에서 채운다 (해시 범위 밖)
├── config.env.example
├── models.json               Pi 정적 제공자 선언 (§5.1)
├── STAGING_MANIFEST.json
└── README-폐쇄망.md
```

`packages_win\`은 통계·생존분석(pandas/lifelines/statsmodels/scikit-learn 등)
Python 스택이며 llama.cpp/Pi 기동 경로와 완전히 독립적이다 — 어느 쪽을 먼저
반입하거나 실행해도 서로 영향을 주지 않는다. 패키지 선정 근거와 조사 과정은
`.superpowers/sdd/2026-08-18-pi-agent-closed-network/python-wheelhouse-research.md`
에 있다. `install-python-packages.bat`은 번들 내장 임베디드 파이썬(`bin\python\`)
을 쓰지 않는다 — 그 배포에는 pip이 없다. 대신 대상 PC에 이미 설치된 시스템
Python 3.12를 `py -3.12` → `python` 순으로 찾는다(다른 `.bat`들의 "번들 내장
파이썬 우선" 순서와 의도적으로 반대다). 어느 경로로 찾았든, `config.env`의
`PYTHON_CMD`로 **지정**된 것이든, 쓰기 전에 두 가지를 검사한다:
`sys.version_info[:2] == (3, 12)`(휠 155개가 전부 cp312 전용이라 3.13에서는
155개가 모두 "not a supported wheel"로 실패한다)와 `import pip`(임베디드
배포를 지정했을 때 여기서 걸린다). 검사 없이 지정값을 그대로 쓰면
`config.env.example`의 안내를 따라 임베디드 경로를 적은 운영자가 pip 없는
파이썬으로 설치를 시도하게 된다.

**설치 범위의 기본값은 격리다.** 아무 인자 없이 실행하면 `%ROOT%.venv`를
만들어 거기에만 설치한다. `--user`를 인자로 명시했을 때만
`%APPDATA%\Python\Python312\site-packages`에 설치하고, 그때는 그 계정의 모든
Python 3.12 실행이 영향을 받는다는 경고를 콘솔에 찍는다 — 사내 스크립트가
`numpy<2`를 쓰고 있으면 그 설치 하나로 깨지고 되돌리는 절차가 없다. `.venv`는
매니페스트 해시 범위 밖이다(§9): 넣으면 설치 직후 `verify()`가 `unexpected:`를
수천 건 뱉어 무결성 검사가 영구히 빨간불이 되고, 운영자는 그 결과를 무시하도록
훈련된다.

`packages_win\vcruntime\`은 lightgbm 하나 때문에 있다. `lightgbm` 휠 안의
`lib_lightgbm.dll`의 실제 import 테이블에는 `MSVCP140.dll`, `VCOMP140.DLL`
(OpenMP), `VCRUNTIME140.dll`, `VCRUNTIME140_1.dll` 4종이 있는데(실측,
2026-08-18) 휠은 이 중 어느 것도 벤더링하지 않는다(`scikit-learn`은
`sklearn\.libs\`에 4종을 전부 자체 동봉해 무사하다). 이 번들이 따로 싣는
것은 앞의 2종(`VCOMP140.DLL`, `MSVCP140.dll`)뿐이다 — §3.5의 VC 런타임 3종은
`bin\llama-*\` 안 app-local이라 파이썬 프로세스의 DLL 검색 경로에 없어서
쓸 수 없다. 나머지 `VCRUNTIME140.dll`, `VCRUNTIME140_1.dll` 2종은 대상 PC의
**시스템 Python 3.12 설치본**이 `Python312\VCRUNTIME140.dll`(과 짝 파일)로
동봉하는 것을 그대로 쓴다(2026-08-18 실측으로 로드 경로 확인) — 이
스크립트가 시스템 Python을 요구하는 이유 중 하나다. 위험은 낮지만 이
전제에 기댄다: 운영자가 표준 python.org 설치본이 아닌 다른 경로(예: 별도
포터블 배포, VC 런타임을 자체 동봉하지 않는 파이썬)로 Python 3.12를
넣으면 이 두 DLL이 없을 수 있고, 그러면 `import lightgbm`이 아니라 그보다
먼저 OS 로더 단계에서 실패한다.

그래서 이 두 DLL(`VCOMP140.DLL`, `MSVCP140.dll`)을 따로 싣고,
`install-python-packages.bat`이 설치된 `lightgbm\bin\` 옆으로 복사한다 —
scikit-learn이 하는 것과 같은 app-local 방식이고, 파이썬 3.8+ ctypes가 경로로
DLL을 열 때 `LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR`를 켜므로 그 폴더에서 의존 DLL을
찾는다. 설치 위치는 격리/`--user`에 따라 다르므로 파이썬에게 직접 묻는다
(`importlib.util.find_spec` — DLL이 아직 없어 `import lightgbm` 자체가 실패할
수 있으므로 임포트로 물으면 안 된다).

`bin\python\`은 사용자가 대상 PC에 Python 3.12가 있다고 확인해 주었음에도
넣는다. 관리자 권한도 네트워크도 없는 곳에서 파이썬이 없거나 Microsoft Store
앱 실행 별칭 스텁이 잡히면 복구가 불가능하기 때문이다 — `.bat`은 `PYTHON_CMD`
→ 번들 내장 → `py -3.12` → `python` 순으로 찾는다.

백엔드 DLL을 섞지 않기 위해 세 런타임은 **각각 독립 디렉터리**를 유지한다. 한 폴더에 합치면 어느 백엔드가 로드됐는지 확정할 수 없다.

## 5. 결정적 모델 부트스트랩 계약

폐쇄망 무인 기동에서 가장 중요한 부분이다. 대화형 로드에 의존하지 않는다.

```
1. llama-server -m <models\정확한파일.gguf> --alias <고정-모델-ID> \
     --jinja --host 127.0.0.1 --port 8080 \
     -ngl 999 -c 32768 --parallel 1 -sm layer -ts <실측값>
2. readiness 폴링 — 서버가 응답할 때까지 대기 (무한 대기 금지, 타임아웃과 실패 종료)
3. /v1/models 조회 — <고정-모델-ID>가 나타나는지 확인. 없으면 중단.
4. 정적 제공자 선언 배치 — 번들 루트의 models.json을 PI_CODING_AGENT_DIR로
   복사한다. 이것이 있어야 Pi가 이 엔드포인트를 하나의 제공자로 인식한다.
5. Pi 기동 — --model <제공자>/<고정-모델-ID> 와 LLAMA_BASE_URL 사용
6. 툴 왕복 스모크 테스트 — 실제 파일 읽기 1회를 왕복으로 확인
```

### 5.1 왜 라우터 모드를 쓰지 않고 정적 제공자를 선언하는가

`pi.exe`에 내장된 llama.cpp 제공자는 **라우터 모드를 요구한다.** 근거 두 가지:

- 바이너리에 `throw new Error("Server is not running in llama.cpp router mode")` 문자열이 있다.
- 같이 실린 `bin\pi\docs\llama-cpp.md`가 "Start `llama-server` without `--model` or `-m`. Passing a model starts single-model mode instead of router mode."라고 못 박고, 문제 해결 절에도 "**Server is not in router mode:** Start it without `--model`, `-m`, or `-hf`."가 있다.

그런데 위 1번은 `-m`으로 단일 모델 모드를 띄운다. 그래서 관문 ①②(서버 기동, `/v1/models`에 alias 노출)는 통과하고 관문 ③(툴 왕복)에서 죽는다.

**라우터 모드로 바꾸지 않는다.** 무인 기동의 결정성이 이 절의 핵심이고, 라우터로 가면 명시적 load API 호출·동시 적재 한도·전환 절차가 `.bat`에 들어와야 하며 §6의 mmproj 평면 배치 결정과도 충돌한다(라우터는 멀티모달 모델을 하위 디렉터리에 두라고 요구한다).

대신 **정적 제공자 선언**으로 푼다. Pi는 `PI_CODING_AGENT_DIR\models.json`에서 사용자 정의 제공자를 읽는다(`bin\pi\docs\models.md`). 번들 루트에 다음을 두고, `start-pi.bat`·`verify-offline.bat`이 실행할 때마다 `PI_CODING_AGENT_DIR`로 덮어쓴다.

```json
{"providers":{"local":{"baseUrl":"http://127.0.0.1:8080/v1","api":"openai-completions",
 "apiKey":"local","compat":{"supportsDeveloperRole":false,"supportsReasoningEffort":false},
 "models":[{"id":"qwen3.8-27b", ...}]}}}
```

- 원본은 **번들 루트**에 둔다. `home\agent\`는 가변 영역이라 해시되지 않으므로 원본이 거기 있으면 매니페스트가 지켜 주지 못한다. 매번 덮어쓰므로 설정은 항상 검증된 원본에서 나온다.
- `compat`의 두 플래그를 끄는 이유는 상류 문서가 Ollama/vLLM 같은 OpenAI 호환 서버에 대해 명시하기 때문이다(`developer` 역할 대신 `system`, `reasoning_effort` 미전송).
- `apiKey`는 더미 값이다. 키 없는 로컬 서버라도 값이 있어야 모델이 `/model`과 `--list-models`에 나타난다.
- Pi에 넘기는 모델 ID는 제공자 한정 형식 `local/qwen3.8-27b`이다(`--model`은 `provider/id`를 받는다 — `bin\pi\docs\usage.md`). 뒷부분은 `llama-server`의 `--alias`와 **글자 그대로 같아야 한다.**
- `models.json`은 정적 파일이라 환경변수를 읽지 않는다. `LLAMA_PORT`를 바꾸면 `baseUrl`의 포트도 같이 바꿔야 한다.
- readiness 폴링이 보는 엔드포인트는 그대로 `/v1/models`다. 단일 모델 모드에서 정상 응답하며, 거기 나타나는 이름은 제공자 접두사 없는 `--alias` 값이다.

**이 연결 방식은 리허설에서 처음 검증된다.** 위 근거는 모두 바이너리 문자열과 동봉 문서에서 확인한 것이고, 정적 제공자 선언이 이 Pi 빌드에서 실제로 툴 왕복까지 완주하는지는 윈도우에서 `pi.exe`를 돌려봐야만 안다.

Pi 쪽 연결은 환경변수(`LLAMA_BASE_URL`, 필요 시 `LLAMA_API_KEY`)와 위 `models.json`으로 세팅하여 대화형 `/login` 단계를 제거한다.

### 5.2 실행 스크립트가 만족해야 하는 윈도우 제약 (2026-08-18 실측)

`.bat`은 우리가 쓰는 대로 실행되지 않는다. 아래 넷은 윈도우에서 직접 재현해 확인한 것이며, 각각 단독으로 반입 전체를 무력화한다.

- **줄바꿈은 CRLF여야 한다.** cmd.exe는 배치 파일을 실행하면서 줄을 바이트 오프셋으로 다시 찾는다. LF뿐인 파일에 비ASCII(한글) 줄이 있으면 그 다음 줄부터 파싱이 어긋나 줄 중간이 명령으로 실행된다.
- **파일 인코딩은 콘솔 코드페이지와 같아야 한다.** UTF-8 + `chcp 65001`은 CRLF여도 긴 한글 줄에서 같은 어긋남이 재현된다. 이 항목이 처음 실측된 시점에는 `.bat` 자신에 한글 `echo`/`rem`이 있었으므로, CP949로 저장하고 `chcp 949`를 쓰는 것으로 풀었다(파이썬 호출의 `PYTHONIOENCODING`도 그때는 `cp949`로 맞췄다).

  **2026-08-19 재구조화.** 실제 사용 환경(VS Code 터미널, Windows Terminal)이 출력을 UTF-8로 디코드한다는 현장 보고가 들어왔다 — CP949 바이트를 그대로 내보내면 그 두 터미널에서 한글이 깨진다. `chcp 949`로 콘솔을 맞춰도, 콘솔 자체가 아니라 그 콘솔을 렌더링하는 터미널 에뮬레이터가 UTF-8을 가정하면 소용이 없다. 근본 해법은 위 어긋남 자체를 없애는 것이다: `.bat`(`start-llama.bat`, `start-pi.bat`, `verify-offline.bat`, `install-python-packages.bat`)과 `config.env`/`config.env.example`에서 비ASCII 문자를 전부 뺐다 — 배치 자신의 메시지는 이제 전부 영문이다. 그러면 파일 인코딩 문제 자체가 성립하지 않으므로 콘솔은 `chcp 65001`(UTF-8)로 맞추고, 파이썬 호출의 `PYTHONIOENCODING`도 `utf-8`로 맞춘다. `tools\*.py`는 UTF-8 소스이고 한글 진단 메시지를 그대로 낸다 — 이제 이것이 UTF-8 콘솔에 정상 출력되고, `evidence\`로 리다이렉트된 파일도 UTF-8로 남는다. 한글이 필요한 운영 안내는 배치가 아니라 `win/README-폐쇄망.md`가 맡는다.
- **`call`은 `.bat`/`.cmd`만 배치로 실행한다.** `call "...\config.env"`는 아무 일도 하지 않고 `errorlevel 0`으로 돌아온다. 운영자에게 익숙한 `config.env` 이름을 유지하려면 가변 영역에 `.cmd` 사본을 만들어 그것을 `call`해야 한다.
- **후행 역슬래시가 붙은 경로를 따옴표 안에 넣어 외부 프로그램에 넘기지 않는다.** `%~dp0`는 항상 `\`로 끝나므로 `--root "%ROOT%"`는 argv에서 `C:\pi_agent"`로 깨진다. `--root "%ROOT%."`로 경로를 끝낸다.

## 6. GPU 배치

Qwen3-Coder-30B-A3B-Instruct 기준 산술:

- 구조: 48층, KV head 4, head dimension 128, 총 30.5B / 활성 3.3B
- 32k 컨텍스트 F16 KV 캐시: `2 × 48 × 4 × 128 × 32768 × 2 bytes = 3.0 GiB`
- Q4_K_M 가중치 약 17.3 GiB → 합계 약 20.3 GiB. 여기에 연산 버퍼·CUDA graph·단편화가 더해진다.

규칙:

- `-sm layer`를 쓴다. `-sm row`는 split-buffer 문제와 PCIe 통신 증가로 회피한다.
- `-ts`는 **실측 free VRAM에 맞춰 정한다. `1,1,1` 고정은 금지한다.** GPU0는 디스플레이 출력이 VRAM을 점유하므로 실제 여유가 다르다.
- `--parallel 1`로 32k가 여러 슬롯으로 쪼개지지 않게 한다.
- MoE의 활성 파라미터 3.3B는 연산량만 줄인다. expert 가중치는 전부 적재된다.
- NVLink가 없으므로 33GB는 단일 풀이 아니다. 층 분할·PCIe 전송이 성능과 OOM을 좌우한다.
- `--cpu-moe`는 expert를 RAM으로 보내 심각한 속도 저하를 부르므로 쓰지 않는다.

백업 모델로 7~8B급 Q4_K_M을 함께 반입한다. 큰 모델이 뜨지 않아도 그날 안에 동작을 보이기 위한 것이며, 툴 호출 왕복을 별도로 검증해야 한다.

**확정값 (Task 7, 2026-08-18).** 위 문단의 산술은 후보 조사 당시 검토했던 Qwen3-Coder-30B-A3B-Instruct(MoE) 기준이다. 실제로 반입이 확정된 모델은 사용자가 이미 확보해 둔 아래 모델이며, 아키텍처가 달라 산술을 다시 했다.

| 항목 | 값 |
|---|---|
| 파일명 | `Qwen3.8-27B-Q4_K_M.gguf` (`models\Qwen3.8-27B-Q4_K_M.gguf`, 단일 파일 — 분할 없음, `models\<이름>\` 하위 디렉터리 불필요) |
| 바이트 | 16,810,714,336 (15.66 GiB) |
| SHA256 | `e00082f779fa385cee8c68a3ec8833a75778cc87272240b942f74e0b8243e520` |
| 출처 | `lmstudio-community/Qwen3.8-27B-GGUF` (Hugging Face, llama.cpp b10430으로 양자화). 사용자의 LM Studio 로컬 캐시(`C:\Users\ptg\.lmstudio\models\lmstudio-community\Qwen3.8-27B-GGUF\`)에서 그대로 복사했고, 사본의 SHA256이 원본과 일치함을 확인했다 |
| 라이선스 | Apache 2.0 (원 모델 `Qwen/Qwen3.8-27B` 기준, gated 아님) |
| 권장 alias | `qwen3.8-27b` |
| 아키텍처 | GGUF `general.architecture = qwen35` — **dense 27.8B** (MoE 아님). 하이브리드: Gated DeltaNet 선형 어텐션 48층 + 전체 어텐션 16층(`qwen35.full_attention_interval = 4`), `block_count = 65`(본층 64 + MTP 1층), `attention.head_count_kv = 4`, `attention.key_length = attention.value_length = 256` |
| 32k F16 캐시 산술 | 전체 어텐션 16개 층만 컨텍스트에 비례하는 KV 캐시를 가진다: `2 × 4(head_count_kv) × 256(key/value_length) × 32768 × 2bytes × 16층 = 2.0 GiB`. 나머지 48개 선형 어텐션층은 SSM/conv 상태만 유지하며 이는 컨텍스트 길이와 무관하게 고정 크기다(오더 추정 수십~1백 MiB대 — 정확한 값은 Task 8 리허설에서 `nvidia-smi` 실측으로 확인). 가중치 15.66 GiB + 캐시 약 2.0~2.1 GiB ≈ **17.8 GiB**, 여기에 비전 프로젝터(아래 행) 약 0.87 GiB를 더하면 **≈ 18.7 GiB**. 연산 버퍼·CUDA graph를 넉넉히 얹어도 33GB(GPU0 디스플레이 점유 차감 후 약 32GB) 안에 여유 있게 들어온다 — 원래 검토했던 MoE 후보(약 20.3 GiB)보다 오히려 여유가 크다 |
| `mmproj-Qwen3.8-27B-BF16.gguf` | 931,145,856 bytes (0.867 GiB). **반입 확정 (Task 7b, 2026-08-18).** 사용자 지시로 반입하며, 폐쇄망 PC에서 에러 코드를 사진·스크린샷으로 입력하는 것이 실사용 목적이다 — "가능하면 넣는" 부가 기능이 아니라 필요 기능이다. `models\` 바로 아래에 평평하게 둔다(주력 모델과 동일한 규칙, `models\Qwen3.8-27B\` 하위 디렉터리 불필요). 사용자의 LM Studio 로컬 캐시(`C:\Users\ptg\.lmstudio\models\lmstudio-community\Qwen3.8-27B-GGUF\mmproj-Qwen3.8-27B-BF16.gguf`)에서 그대로 복사했고, 사본의 SHA256이 원본과 일치함을 확인했다. SHA256: `97ba9d70e7407f08c880def231fd360a312c76d0053387733f10dcf6affd75a1`. 설정은 `config.env`의 `MMPROJ_FILE=mmproj-Qwen3.8-27B-BF16.gguf`(기본값으로 채워 둠) — `start-llama.bat`이 이 값이 있으면 `--mmproj`를 조건부로 붙이고, 비우면 텍스트 전용으로 뜬다 |
| 백업 모델 | 이번 라운드에 반입하지 않음. 사용자가 이미 확보한 주력 모델을 먼저 검증하는 것이 우선이었고, 백업 필요 여부는 Task 8 리허설 결과를 보고 정한다 |
| 알려진 위험 — Vulkan 폴백 | `bin\llama-vulkan`(§4의 폴백 백엔드)은 이 아키텍처 계열(qwen3.5/qwen35)의 `ggml_ssm_conv`/`ggml_ssm_scan`을 구현하지 않았고, 조용히 CPU로 폴백하면서 GPU↔CPU 경계에서 상태가 손상된다(상류 이슈 `ggml-org/llama.cpp#19957`, 2026-02-27 open, 미해결 — 손상된 출력 또는 `vk::DeviceLostError`로 이어짐). CUDA 백엔드는 완전히 지원한다(`b10470`, 2026-08-17 릴리스 — qwen35 아키텍처와 MTP는 2026-05부터 지원됨). 즉 현장에서 CUDA가 실패해도 `llama-vulkan`은 이 모델에 안전한 폴백이 아니다 — 대신 `bin\llama-cpu`(느리지만 정확)로 내려가야 한다. **2026-08-20부터 문서가 아니라 코드가 막는다**: `start-llama.bat`이 `LLAMA_BACKEND=vulkan`을 이슈 번호와 함께 거부하고(exit 8), `cpu`는 `ALLOW_CPU_DIAGNOSTIC=1` 없이는 거부한다(exit 9) |
| 알려진 위험 — 연산량 | dense 27.8B 전량이 매 토큰 활성화된다(당초 권고안이던 MoE의 활성 3.3B 대비 토큰당 연산량이 훨씬 크다). Pascal(compute 6.1, FP16 텐서코어 없음)에서 체감 속도 저하가 예상된다. 하이브리드 선형 어텐션은 긴 프롬프트의 prefill을 완화할 뿐 디코드 연산량 자체는 줄이지 않는다 — 실측 토큰/초는 Task 8 리허설에서 확인해야 한다 |

`STAGING_MANIFEST.json`에는 스테이징 단계(Task 5)에서 위 파일의 해시가 다시 기록된다.

### 6.1 이미지 입력 경로의 출처

리뷰가 "문서상 주장"으로 남긴 세 가지는 상류 배포물에서 직접 확인한 것이다. 근거를 남겨 둔다.

- 윈도우에서 이미지 붙여넣기가 `Ctrl+V`가 아니라 `Alt+V`라는 것: Pi 0.84.2 `packages/coding-agent/README.md`의 단축키 표가 "Ctrl+V to paste an image or text (Alt+V on Windows), or drag images onto terminal"로 윈도우만 따로 명시한다.
- 비대화형 `@파일` 참조: 같은 문서의 예시 `pi -p @screenshot.png "What's in this image?"`.
- 클립보드가 별도 설치 없이 동작한다는 것: `pi-windows-x64.zip`의 파일 목록에 네이티브 애드온 `node_modules/@mariozechner/clipboard-win32-x64-msvc/clipboard.win32-x64-msvc.node`가 포함되어 있다(2026-08-18 실측).

세 항목 모두 문서와 아카이브 내용으로 확인한 것이며, 실제 동작은 §8의 리허설에서 스크린샷 왕복으로 확인한다.

## 7. 오프라인 봉인

- `.bat`이 `PI_OFFLINE=1`과 `PI_CODING_AGENT_DIR`를 강제 설정한다. 사용자가 잊을 수 없다.
- 경로는 `set "PI_CODING_AGENT_DIR=%~dp0home\agent"` 형식으로 쓴다. 공백과 현재 디렉터리 의존 문제를 피한다.
- llama-server는 `--host 127.0.0.1`로만 바인딩한다.
- Hugging Face 다운로드 기능은 사용하지 않는다.

`home\agent`에는 세션·로그·툴 출력이 쌓이며 소스 코드 내용이 포함된다. 다중 사용자가 같은 번들을 공유하지 않는다는 전제이며, 이를 README에 명시한다.

## 8. 검증

### 8.1 반입 전 리허설 (인터넷 되는 쪽)

폐쇄망에서 깨질 것을 여기서 잡는다.

- Node·CUDA toolkit·VC++ 런타임이 없는 clean 윈도우 상태에서 시험한다.
- 인터넷 연결 상태로 한 번, 이후 **NIC 차단 또는 localhost 외 아웃바운드 차단 상태에서 다시** 시험한다.
- 최종 `.bat`·경로·환경변수를 그대로 쓴다. 기존 Pi home/cache는 지운다.
- `Get-FileHash`, PE 의존성 검사, `llama-server --list-devices`, `nvidia-smi`를 기록한다.
- 명시적 모델 로드와 readiness 대기, `/v1/models`의 alias 확인.
- 32k에 가까운 프롬프트, 장시간 생성, 실제 툴 왕복 1회.
- CUDA / Vulkan / CPU를 각각 별도로 실행해 본다. Qwen3.8-27B(qwen35)에서는
  Vulkan을 정식 폴백으로 검증하지 않는다 — §6의 "알려진 위험 — Vulkan
  폴백" 참조. CUDA 실패 시 대체 경로는 CPU만 확인한다.
- **비전 프로젝터(`MMPROJ_FILE`) 리허설 확인 항목** — "멀티모달로 떴다"는
  통과 기준이 아니다. 아래 세 가지를 실측으로 확인한다:
  1. 이 프로젝터는 **BF16**인데 Pascal(compute 6.1)은 BF16 텐서코어를
     지원하지 않는다. llama.cpp가 변환해 처리하겠지만, 적재 시간·VRAM
     사용량·(가능하면) 정확도에 어떤 영향이 있는지 실측한다.
  2. 멀티모달 활성화가 §5 부트스트랩 계약의 텍스트 전용 툴 호출 경로에
     영향을 주지 않는지 확인한다 — `/v1/models` alias, 툴 왕복 스모크
     테스트가 `MMPROJ_FILE`을 설정한 상태에서도 그대로 통과해야 한다.
     영향이 있으면 `MMPROJ_FILE`을 비워 텍스트 전용으로 되돌릴 수 있다.
  3. **에러 메시지가 담긴 스크린샷 한 장을 실제로 넣어, 모델이 그 안의
     문자열을 정확히 읽어내는지 확인한다.** 이 기능의 실사용 목적(폐쇄망
     PC에서 에러 코드를 사진으로 입력)에 대한 실제 성공 기준은 이것이며,
     서버가 멀티모달 모드로 뜨는 것 자체가 아니다.

### 8.2 폐쇄망 도착 후

`verify-offline.bat`이 `evidence\`에 다음을 남긴다. **exit 0을 성공의 증거로 믿지 않는다** — 성공은 남은 증거가 말하고, 그 증거를 `tools\verify_gate.py`가 판정해 실패면 nonzero로 내보낸다.

- `nvidia-smi` 드라이버 버전과 GPU별 VRAM
- `/v1/models` 응답 원문
- Pi의 실제 완결 응답 1건과 토큰 수
- 툴 왕복 1회의 요청·실행·결과
- `pktmon`/WFP 로그로 **외부 연결 시도 0건** (성공한 연결 0건이 아니라 시도 0건)

### 8.3 툴 호출이 성립하기 위한 조건

`--jinja` 하나로 끝나지 않는다. 다음이 모두 성립해야 한다.

1. GGUF에 올바른 `tokenizer.chat_template`이 포함되어 있을 것
2. llama.cpp b10470이 그 템플릿을 인식할 것 (Qwen3-Coder XML형 tool parser가 `common/chat.cpp`에 존재)
3. Pi가 OpenAI 형식 `tools` 스키마를 전송할 것
4. llama-server가 `tool_calls`와 `finish_reason`을 Pi가 기대하는 형식으로 반환할 것
5. Pi가 툴을 실제 실행하고 결과를 모델에 되돌려 최종 답변을 받을 것
6. Pi의 모델 ID가 `/v1/models`의 alias와 정확히 일치할 것
7. 백업 모델도 같은 왕복을 통과할 것

"툴 호출 문자열이 생성됐다"는 통과 기준이 아니다.

## 9. 매니페스트 범위

`STAGING_MANIFEST.json`은 **불변 영역만** 해시한다: `bin\`, `models\`, `.bat` 파일들, `models.json`, `config.env.example`, `README-폐쇄망.md`, `packages_win\`(휠 155개 + `vcruntime\`의 DLL 2개 + `requirements.txt` + `constraints-py312.txt`), `pi-packages\`(사전 설치한 확장·스킬 트리 + `settings.packages.json`), `tools\`.

`packages_win\`도 다른 반입물과 같은 이유로 불변이다 — 오프라인 설치는 이 폴더의 휠만 참조하고 `install-python-packages.bat`이 쓰는 것은 `home\agent\`(가변, 위에서 이미 제외)와 `.venv\`(아래)뿐이다. 목록은 이 스펙에 다시 나열하지 않는다 — 진실 출처는 `packages_win\requirements.txt`다.

`pi-packages\`도 같다. §13.3이 이 트리를 "매니페스트가 검증한 원본"으로 삼고 매 실행마다 가변 영역인 `home\agent\`로 동기화하므로, 원본이 해시 범위 안에 있어야 그 주장이 성립한다. `bin\`, `models\`와 마찬가지로 gitignore 대상이지만(상류 npm/git 배포물) 해시는 한다 — 해시 범위와 git 추적 범위는 같지 않다.

`home\agent\`와 `evidence\`는 제외한다. 첫 실행 즉시 내용이 바뀌므로 포함하면 무결성 검사가 곧바로 깨진다.

`.venv\`도 제외한다. `install-python-packages.bat`의 기본값이 격리 설치라 대상 PC에서 반드시 생기고, 넣으면 설치 직후 `verify()`가 `unexpected: .venv/...`를 수천 건 뱉는다. `verify_bundle.py`는 그것을 실패로 취급하므로 무결성 검사가 영구히 빨간불이 되고, 운영자는 검사 결과를 무시하도록 훈련된다 — `tools\manifest.py` 독스트링이 명시적으로 경계하는 실패 모드다.

다음 셋도 같은 이유로 제외한다.

- `config.env` — README와 리허설 절차서가 `GPU_TENSOR_SPLIT` 등을 **현장에서 채우라고 지시한다.** 해시하면 지시를 따른 운영자에게 `hash mismatch: config.env`가 확정적으로 뜨고, 운영자는 무결성 검사 결과를 무시하도록 훈련된다. 그게 전송 손상을 잡는 유일한 장치다. 템플릿 `config.env.example`은 해시를 유지한다.
- `__pycache__\`와 `*.pyc` — `verify_bundle.py`가 `import manifest`를 먼저 하므로 자기가 검사할 파일을 자기가 다시 쓴다. 대상 PC의 파이썬 버전이 다르면 `unexpected:`로, 소스 mtime이 바뀌면 `hash mismatch:`로 무조건 실패한다. 경로 깊이와 무관하게 제외한다.

해시 범위는 git 추적 범위와 같지 않다. `bin\`, `models\`는 gitignore 대상이지만 반입물의 본체이므로 해시하고, `win\`은 git이 추적하지만 번들 루트로 복사된 사본만 해시하므로 제외한다.

기록 항목은 기존 관례를 따른다: 상대 경로, 파일 수, 바이트, SHA256, 원본과 대상의 일치 여부.

## 10. 현장 확인이 필요한 항목

설계로 결정할 수 없고 대상 PC에서만 확정되는 것들이다. 리허설로도 잡히지 않는다.

- 드라이버 버전이 551.61 이상인지
- GPU 3장의 실제 free VRAM과 디스플레이 점유량 → `-ts` 값
- VC++ 런타임의 시스템 설치 여부
- 그룹 정책 / AppLocker / Defender가 `pi.exe`·`llama-server.exe` 실행을 막는지
- 실제 PCIe 토폴로지, 시스템 RAM과 페이지파일, 디스크 여유
- 전송 중 손상 (매니페스트 대조로 검출)
- 3장 지속 부하 시 전력·온도

## 11. 범위 밖

- 폐쇄망 내 모델 추가 다운로드
- 다중 사용자 공유 배포
- 라우터 모드 다중 모델 운영 (§5.1에서 배제. 정적 제공자 선언으로 대체했다)
- 폐쇄망 PC에서의 `pi install` 실행 (npm 필요 — §13이 대신 사전 설치 후
  트리 반입 방식으로 다룬다)

## 12. 성공 기준

폐쇄망 PC에서, 인터넷이 없는 상태로, 관리자 권한 없이:

1. `start-llama.bat` 실행 → 지정한 모델이 GPU에 적재되고 `/v1/models`에 고정 alias가 나타난다.
2. `start-pi.bat` 실행 → Pi가 그 모델로 대화하고 파일 읽기 툴 왕복이 성립한다.
3. `verify-offline.bat` 실행 → 위 증거가 `evidence\`에 남고, 외부 연결 시도가 0건으로 기록된다.

증거를 남기는 것과 판정을 내는 것은 다른 일이다. `verify-offline.bat`은 증거를 **끝까지 다 모은 뒤**(중간에 abort하지 않는다 — 증거가 목적이다) `tools\verify_gate.py`로 여섯 항목을 판정하고, 하나라도 실패하면 nonzero로 끝난다. "성공 판정은 종료 코드가 아니라 증거"라는 원칙은 *exit 0을 성공의 증거로 믿지 말라*는 뜻이지 실패를 종료 코드로 알리지 말라는 뜻이 아니었다 — 실패를 nonzero로 내보내는 것은 그 원칙을 강화한다.

## 13. Pi 확장·스킬 반입

조사 근거: `.superpowers/sdd/2026-08-18-pi-agent-closed-network/pi-packages-research.md`.

### 13.1 왜 Node/npm을 반입하지 않아도 되는가

`pi.exe`는 Bun으로 컴파일된 자기완결 바이너리이고(§3.1), 확장은 TypeScript
원본 그대로 배포돼 내장 런타임이 직접 로드·실행한다. npm/git은 **설치
시점**에만 불리고, 로드 시점에는 전혀 관여하지 않는다 — `pi.exe` 내부
로직(`resolvePackageSources`)이 로컬 `package.json`의 버전만 semver로
비교해 "이미 설치돼 있는지" 판단하고, 맞으면 npm/git을 아예 호출하지 않는다.
git 소스는 더 단순해서 존재 여부만 본다.

그래서 이 반입은 **사전 설치 후 설치된 트리를 통째로 옮기는 방식**을
쓴다: 인터넷이 되는 윈도우 PC에서 `pi.exe`로 실제 `pi install`을 실행하고,
그 결과물(`npm\`, `git\`, `settings.json`의 `packages` 배열)을 번들 루트
`pi-packages\`에 실어 온다. 대상 PC에서는 `pi install`을 한 번도 부르지
않는다.

### 13.2 설치는 반드시 윈도우에서 한다

이 조사(그리고 이 웨이브의 실제 설치, Task 9 참고)는 WSL에서 실제 윈도우
프로세스(`cmd.exe`)를 띄워 `bin\pi\pi.exe`를 직접 실행하는 방식으로
진행했다 — Linux 샌드박스에서 설치하면 네이티브 애드온이 섞인 패키지의
경우 윈도우에서 못 쓰는 `.node`/`.so` 바이너리가 실릴 위험이 있기
때문이다. 이번에 반입이 확정된 4개 패키지(`superpowers`, `pi-subagents`,
`rpiv-todo`, `rpiv-ask-user-question`)는 순수 JS/TS로 실측 결과 네이티브
바이너리가 전혀 없었지만, 원칙은 패키지 구성과 무관하게 지킨다 — 다음
라운드에 네이티브 의존 패키지(예: 조사 단계에서 제외한 `pi-lens`)를
추가하게 되면 이 원칙이 실제로 막아 주는 값이 된다.

### 13.3 `home\`이 매니페스트 해시 범위 밖이라는 문제와 그 해법

`STAGING_MANIFEST.json`의 `excludedRoots`에 `home`이 들어 있어, 설치
결과물을 `home\agent\`에 직접 두면 무결성 검증 범위 밖에서 전달된다.
`models.json`이 이미 쓰는 패턴(번들 루트에 해시 대상 원본을 두고, 실행할
때마다 가변 영역으로 덮어쓴다)을 그대로 따른다:

- 설치 트리는 번들 루트 `pi-packages\npm\`, `pi-packages\git\`에 둔다 —
  `home`과 달리 `EXCLUDED_ROOTS`에 없으므로 매니페스트 해시 범위 안이다.
- `start-pi.bat`이 실행할 때마다 `xcopy /E /H /D /Q`로
  `PI_CODING_AGENT_DIR\npm\`, `\git\`에 동기화한다. `/D`가 파일 단위로
  이미 최신인 것을 건너뛰므로 별도 비교 로직 없이 반복 실행 비용이
  낮다. `/H`가 없으면 git 클론 안의 숨김(Hidden) 속성 `.git` 폴더가
  통째로 스킵된다(2026-08-18 윈도우 실측 — 연구 조사에서는 예상하지
  못했던 지점).
- `settings.json`의 `packages` 배열은 `models.json`과 다르게 다룬다.
  사용자가 `/trust`, `/settings`로 직접 고칠 수 있는 파일이라 매번
  덮어쓰면 사용자 설정이 날아간다. 그래서 **없을 때만** 번들 루트
  `pi-packages\settings.packages.json`(정본은 `win\settings.packages.json`,
  models.json과 같은 이유로 git 추적)을 심는다 — 최초 1회 등록 이후로는
  사용자의 편집을 존중한다.
- `pi-packages\npm\`, `pi-packages\git\` 자체는 `bin\`, `models\`와 같은
  이유로 git 추적 대상이 아니다(상류 npm/git 레지스트리에서 받은 배포물,
  `.gitignore`에 등재) — 물리적으로는 번들 루트에 존재하고 매니페스트가
  해시하지만, 이 저장소의 git 이력에는 들어가지 않는다.

### 13.4 반입 패키지 4개

`git:github.com/obra/superpowers@v6.3.0`(필수), `npm:pi-subagents@0.50.0`(필수),
`npm:@juicesharp/rpiv-todo@2.6.1`, `npm:@juicesharp/rpiv-ask-user-question@2.6.1`.
선정 근거와 비교 조사한 대안(각 비추천 사유 포함)은 조사 문서 §2·§3에
있다. 각 패키지가 실사용에서 하는 일은 `win\README-폐쇄망.md`의 "Pi
확장·스킬" 절에 표로 정리했다. 전부 전역(user) 스코프로만 설치한다 —
프로젝트 스코프는 무인 기동에서 트러스트 프롬프트 문제를 일으킨다(조사
문서 §1-5).

### 13.5 리허설에서 반드시 확인해야 하는 우려 세 가지

이 반입은 실제 GPU가 붙은 윈도우 PC에서의 리허설(Task 8)로 아직
검증되지 않았다. `docs/superpowers/plans/rehearsal-2026-08-18.md`의 확장
로드 확인 절차가 아래 세 가지를 다룬다.

1. **윈도우 설치 필요성** — §13.2의 원칙이 실제로 지켜졌는지. 이번
   4개 패키지는 네이티브 바이너리가 없음을 실측했지만(Task 9 보고서
   참고), 향후 패키지를 추가할 때마다 같은 실측을 반복해야 한다.
2. **`home\`이 해시 범위 밖이라는 문제** — §13.3의 동기화가 실제로
   매 실행마다 일어나고, 전송 손상이나 부분 복사가 발생했을 때
   `verify_bundle.py`가 잡아내는지. `pi-packages\`가 매니페스트 해시
   대상에 실제로 포함됐는지(재발행 시 `STAGING_MANIFEST.json`의
   `files` 배열에 `pi-packages/...` 항목이 나타나는지)도 확인 대상이다.
3. **`pi-subagents`의 백그라운드 위임은 폐쇄망에서 동작하지 않는다** —
   포어그라운드 위임과 백그라운드/async 위임이 서로 다른 실행 파일을
   쓴다. 소스 실측(`pi-packages\npm\node_modules\pi-subagents\src\`):

   - 포어그라운드(`runs/foreground/execution.ts`)는
     `runs/shared/pi-spawn.ts`의 `getPiSpawnCommand()`를 쓴다. 그
     함수는 `process.execPath`의 파일명이 `pi`/`pi.exe`이면 그것을
     그대로 자식 명령으로 쓴다(`isStandalonePiExecutable`). 이 번들은
     `pi.exe` 단독 바이너리이므로 **여기에 해당하고, Node 없이 동작한다.**
   - 백그라운드/async(`runs/background/async-execution.ts:493`)는
     `shared/node-executable.ts`의 `resolveNodeExecutable()`을 쓴다. 그
     함수는 `process.execPath`의 파일명이 `node`/`node.exe`가 아니면
     문자열 `"node.exe"`를 돌려주고, 스폰은
     `spawn(nodeCommand, [jitiCliPath, runner, cfgPath])` 형태다.
     `pi.exe`에서 실행하면 execPath가 `pi.exe`라 항상 이 폴백을 타고,
     Node가 없는 폐쇄망 PC에서는 **`ENOENT`로 실패한다.**

   즉 이 항목의 실패 양상은 "2차 llama-server 기동"이나 "VRAM 추가
   점유"가 아니다. 그런 것은 애초에 일어나지 않는다 — 백그라운드
   러너는 프로세스 생성 단계에서 죽는다(`[pi-subagents] async spawn
   failed: ... ENOENT`). 리허설에서 확인할 것은 이 구분이지 GPU 충돌이
   아니다.

   동시 요청 쪽은 별개이고, 그것도 폭주가 아니다. `start-llama.bat`이
   `--parallel 1`로 띄우므로 llama-server는 동시 요청을 **직렬화한다.**
   포어그라운드 위임을 N개 겹치면 응답이 뒤섞이는 것이 아니라 지연이
   N배가 되고, 그것이 재시도·타임아웃과 겹쳐 "멈춘 것처럼" 보인다.
   대응은 `--parallel`을 올리는 것이 아니라(KV 캐시가 슬롯 수만큼
   쪼개진다) 동시 위임 수를 줄이는 것이다.
