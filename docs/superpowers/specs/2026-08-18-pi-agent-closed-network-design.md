# Pi 코딩 에이전트 폐쇄망 윈도우 배포 설계

작성일: 2026-08-18
상태: 승인됨 (구현 계획 대기)
리뷰: OpenCode / GPT-5.6 Sol (herdr `wF:p2`), 서브에이전트 4종 분산 조사. 전체 판정 `conditional`, 조건은 아래 6개 항목으로 반영 완료.

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
├── home\agent\               PI_CODING_AGENT_DIR — 설정·세션 (가변)
├── evidence\                 검증 산출물 (가변)
├── start-llama.bat
├── start-pi.bat
├── verify-offline.bat
├── config.env                운영자가 현장에서 채운다 (해시 범위 밖)
├── config.env.example
├── models.json               Pi 정적 제공자 선언 (§5.1)
├── STAGING_MANIFEST.json
└── README-폐쇄망.md
```

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
- **파일 인코딩은 콘솔 코드페이지와 같아야 한다.** UTF-8 + `chcp 65001`은 CRLF여도 긴 한글 줄에서 같은 어긋남이 재현된다. CP949로 저장하고 `chcp 949`를 쓰면 재현되지 않는다. 파이썬 호출의 `PYTHONIOENCODING`도 여기에 맞춘다.
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
| 알려진 위험 — Vulkan 폴백 | `bin\llama-vulkan`(§4의 폴백 백엔드)은 이 아키텍처 계열(qwen3.5/qwen35)의 `ggml_ssm_conv`/`ggml_ssm_scan`을 구현하지 않았고, 조용히 CPU로 폴백하면서 GPU↔CPU 경계에서 상태가 손상된다(상류 이슈 `ggml-org/llama.cpp#19957`, 2026-02-27 open, 미해결 — 손상된 출력 또는 `vk::DeviceLostError`로 이어짐). CUDA 백엔드는 완전히 지원한다(`b10470`, 2026-08-17 릴리스 — qwen35 아키텍처와 MTP는 2026-05부터 지원됨). 즉 현장에서 CUDA가 실패해도 `llama-vulkan`은 이 모델에 안전한 폴백이 아니다 — 대신 `bin\llama-cpu`(느리지만 정확)로 내려가야 한다. README와 Task 8 리허설 항목에 이 제약을 명시할 것 |
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

`verify-offline.bat`이 `evidence\`에 다음을 남긴다. **exit 0이 아니라 남은 증거가 성공 기준이다.**

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

`STAGING_MANIFEST.json`은 **불변 영역만** 해시한다: `bin\`, `models\`, `.bat` 파일들, `models.json`, `config.env.example`, `README-폐쇄망.md`.

`home\agent\`와 `evidence\`는 제외한다. 첫 실행 즉시 내용이 바뀌므로 포함하면 무결성 검사가 곧바로 깨진다.

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

- Pi 패키지·확장의 오프라인 설치 (npm 필요)
- 폐쇄망 내 모델 추가 다운로드
- 다중 사용자 공유 배포
- 라우터 모드 다중 모델 운영 (§5.1에서 배제. 정적 제공자 선언으로 대체했다)

## 12. 성공 기준

폐쇄망 PC에서, 인터넷이 없는 상태로, 관리자 권한 없이:

1. `start-llama.bat` 실행 → 지정한 모델이 GPU에 적재되고 `/v1/models`에 고정 alias가 나타난다.
2. `start-pi.bat` 실행 → Pi가 그 모델로 대화하고 파일 읽기 툴 왕복이 성립한다.
3. `verify-offline.bat` 실행 → 위 증거가 `evidence\`에 남고, 외부 연결 시도가 0건으로 기록된다.
