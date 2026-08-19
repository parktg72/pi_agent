# Task 8 리허설 절차서 — 인터넷 되는 윈도우 PC에서

> 이 문서는 로그가 아니라 **그대로 따라 하는 절차서**다. 1080 Ti 3장이 달린
> 윈도우 PC 앞에서 위에서 아래로 실행한다. GPU가 없는 WSL 개발 머신에서는
> Task 8 Step 1(스테이징)까지만 끝낼 수 있고, 이 문서가 다루는 실기 리허설은
> 전부 여기서, 사용자가 직접 수행한다.
>
> 스펙 근거: `docs/superpowers/specs/2026-08-18-pi-agent-closed-network-design.md`
> §4(레이아웃), §5(부트스트랩 계약), §6(GPU 배치), §8(검증), §10(현장 확인).
> 번들 루트는 `H:\model\pi_agent`(반입 후 폐쇄망 PC에서는 `C:\pi_agent`).
> 아래 명령은 전부 번들 루트에서 실행한다고 가정한다.

---

## 0. 전제 확인 — 리허설을 시작하기 전에 반드시 잰다

이 절을 건너뛰고 `start-llama.bat`부터 실행하지 마라. 여기서 잡히는 문제는
이후 단계 전부를 무의미하게 만든다.

| 확인 항목 | 명령 | 통과 기준 | 기록 |
|---|---|---|---|
| 드라이버 버전 | `nvidia-smi` | 상단 "Driver Version"이 **551.61 이상** — CUDA 12.4 GA 최소 요구치. 미만이면 CUDA 백엔드가 뜨지 않는다(§3.6) | 관문 ① 기록란에 적기 |
| GPU 3장 각각의 총/여유 VRAM | `nvidia-smi --query-gpu=index,name,memory.total,memory.used,memory.free --format=csv` | 장당 총 11GB 근방, GPU0는 디스플레이 출력 때문에 free가 다른 두 장보다 적게 나오는 것이 정상 | §3 "-ts 결정 방법" 절의 표에 옮겨 적기 |
| VC++ 런타임 시스템 설치 여부 | PowerShell: `Get-Item "C:\Windows\System32\MSVCP140.dll","C:\Windows\System32\VCRUNTIME140.dll","C:\Windows\System32\VCRUNTIME140_1.dll" -ErrorAction SilentlyContinue` | 있어도 없어도 리허설은 진행된다 — 번들이 `bin\llama-cuda\`에 app-local로 3종을 이미 들고 있다(스테이징 시 이 WSL 호스트의 `C:\Windows\System32`에서 복사함). 시스템에 있으면 그쪽이 우선 로드되므로, 있다면 **버전이 app-local 사본과 다른지**도 적어 둔다 | 알아만 두면 됨. 문제 생기면 README "GPU가 안 잡힐 때" 절 참고 |
| 관리자 권한 여부 | 현재 로그인 계정으로 `net session` 실행 — 성공하면 관리자, `System error 5`면 일반 사용자 | **관리자 권한 없이** 전체 절차가 통과해야 한다(§2 제약). `pktmon`(관문 ④ 이후 오프라인 재시험에서 사용)만 관리자 권한을 요구할 수 있다 — 없으면 `verify-offline.bat`이 `[warn]`을 찍고 계속 진행한다 | 기록란에 있음/없음만 적기 |
| 파이썬 | `bin\python\python.exe -V` 를 먼저 실행하고, 이어서 `py -3.12 -V` 와 `python -V` 도 실행해 본다 | `.bat`은 `config.env`의 `PYTHON_CMD` → **번들 내장 `bin\python\python.exe`** → `py -3.12` → `python` 순으로 찾는다. 번들 내장이 있으면 시스템 파이썬은 쓰이지 않는다. `python -V`가 아무 출력 없이 Microsoft Store를 여는 것은 앱 실행 별칭 스텁이며, 번들 내장이 있어야 하는 이유가 바로 그것이다 | **어느 파이썬이 실제로 쓰였는지** 기록란에 적기 — 관문 ③ 콘솔의 `wait_model.py` 출력이 나오면 그 경로가 동작한 것 |
| clean 상태 | Node·CUDA toolkit이 시스템에 설치돼 있지 않은 상태에서 시험하는 것이 이상적이다(§8.1) | 이미 설치돼 있어도 리허설 자체는 진행 가능 — 다만 "Node 없이도 Pi가 뜬다"는 확인이 약해진다는 것만 인지 | 설치 여부 기록 |

이 단계는 스펙 §10 "현장 확인이 필요한 항목" 6개 중 앞 3개(드라이버, VRAM,
VC++ 설치 여부)를 여기서 재는 것이다. 나머지(그룹 정책/AppLocker/Defender,
PCIe 토폴로지·RAM·디스크, 지속 부하 시 전력·온도)는 아래 단계들을 진행하면서
자연히 드러난다 — 실행이 막히면 관문 ①에서, 부하 문제는 관문 ①~③ 반복
과정에서 나타난다.

---

## 1. 번들 배치

1. `H:\model\pi_agent` 전체를 윈도우 PC의 리허설용 폴더로 복사한다(예:
   `D:\rehearsal\pi_agent` — 최종 반입 경로 `C:\pi_agent`와 다른 이름을 써서
   "이건 리허설 사본"임을 스스로 헷갈리지 않게 한다).
2. `config.env`가 이미 있는지 확인한다. 스테이징 단계(Task 8a)에서 아래
   값을 채운 `config.env`가 만들어져 매니페스트에 포함됐다:
   - `MODEL_FILE=Qwen3.8-27B-Q4_K_M.gguf`
   - `MODEL_ALIAS=qwen3.8-27b`
   - `MMPROJ_FILE=mmproj-Qwen3.8-27B-BF16.gguf`
   - `GPU_TENSOR_SPLIT=`(비어 있음 — 이 문서 §3에서 채운다)
   - `PI_MODEL_ID=local/qwen3.8-27b` (Pi에 넘길 제공자 한정 모델 ID —
     뒷부분이 `MODEL_ALIAS`와 글자 그대로 같아야 한다)
   - `PI_PROVIDER=local` (번들 루트 `models.json`이 선언하는 제공자 이름)
   - `MODEL_LOAD_TIMEOUT=600` (모델 적재 대기 최대 초. 15.66GB를 느린
     디스크에서 올려 600초로 모자라면 여기서 늘린다)
3. **매니페스트 무결성부터 확인한다** — 전송 중 손상은 여기서 잡는다(§10):
   ```
   verify-bundle.bat
   ```
   **`bin\python\python.exe tools\verify_bundle.py --root .`을 직접 부르지
   않는다** — `chcp 65001`과 `PYTHONIOENCODING=utf-8`이 빠져 파이썬 출력이
   콘솔 기본 코드페이지(CP949)로 나가고 한글 진단이 깨진다(2026-08-18
   윈도우 실측). `verify-bundle.bat`은 이 배치를 걸어 준다.
   기대 결과: `[ok] N개 파일이 매니페스트와 일치한다`. **N을 이 문서에
   박아 두지 않는다** — 스테이징을 다시 하면 바뀐다. 확인 방법은 이
   번들의 `STAGING_MANIFEST.json`을 열어 `totals.files` 값을 읽고, 위
   출력의 숫자가 **그 값과 같은지** 보는 것이다. 두 숫자가 다르면
   그 자체가 이상이다. 실패하면 어느 파일이
   `missing`/`unexpected`/`hash mismatch`인지 그대로 나온다 — **여기서
   멈춘다. 다음 단계로 넘어가지 않는다.**
   - `config.env`는 해시 범위에서 제외돼 있다(스펙 §9). 현장에서 값을
     채워도 이 검사는 조용해야 정상이다.
   - 증거로 남길 것: 이 명령의 전체 출력을 복사해 둔다(나중에
     `verify-offline.bat`이 같은 것을 `evidence\manifest-check.txt`에
     자동으로 남기지만, 최초 1회는 수동으로도 확인).

---

## 2. `-ts` (텐서 분할) 결정 — 관문 실행 전에 정한다

`start-llama.bat`은 `GPU_TENSOR_SPLIT`이 비어 있으면 `-ts` 인자 자체를
빼고 llama.cpp 기본 분배를 쓴다. 기본 분배도 동작은 하지만, **디스플레이가
붙은 GPU(보통 GPU0)의 실여유 VRAM이 다른 두 장보다 적다는 것을 반영하지
않는다** — 그래서 스펙이 `1,1,1` 균등 고정을 명시적으로 금지한다(§6).

절차:

1. 위 §0에서 잰 `nvidia-smi --query-gpu=index,memory.free --format=csv`
   결과를 다시 확인한다(디스플레이 출력이 붙어 있으면 유휴 상태에서도
   0.3~1GB 안팎이 이미 점유돼 있을 수 있다).
2. 세 장의 free VRAM을 MiB 단위로 얻는다. 예: GPU0 `10200`, GPU1
   `11200`, GPU2 `11200`이라면 비율은 대략 `10200:11200:11200` →
   기약해서 `51:56:56`처럼 정수비로 둔다. llama.cpp의 `-ts`는 상대
   비율이므로 절대값을 그대로 써도 되고(`10200,11200,11200`), 소수점
   비율(`0.91,1.0,1.0`)로 줄여도 된다 — 어느 쪽이든 **세 장이 균등하지
   않다는 사실이 값에 드러나야 한다**.
3. `config.env`의 `GPU_TENSOR_SPLIT=`에 이 값을 채운다.
4. `1,1,1`을 쓰지 않는 이유를 다시 확인: 균등 분배는 여유가 가장 적은
   GPU0을 기준으로 다른 두 장의 여유를 낭비하거나, GPU0에서 OOM을
   일으킨다. 이 모델은 §6 계산상 33GB 중 약 18.7GB만 쓰므로 여유가
   크지만, `-ts`를 정확히 맞추는 습관 자체가 이후 더 큰 모델을 올릴 때
   필요하다.
5. 기록란(§7)에 최종 확정값을 적는다.

---

## 3. 관문 ① — llama-server가 CUDA로 뜨고 3장에 분산되는가

```
start-llama.bat
```

이 창은 서버가 사는 곳이므로 리허설 내내 닫지 않는다.

**기대 결과:**
- 콘솔에 `[info] starting Qwen3.8-27B-Q4_K_M.gguf as qwen3.8-27b on the cuda backend`가
  찍히고, 이어서 llama.cpp의 정상 기동 로그(레이어별 텐서 배치, KV 캐시
  크기, `main: server is listening on http://127.0.0.1:8080` 류의 메시지)가
  나온다.
- 별도 콘솔(관리자 권한 불필요)에서 `nvidia-smi`를 다시 실행해 **3장 모두**
  `llama-server.exe` 프로세스가 VRAM을 점유하고 있는지 확인한다. 한 장만
  점유하고 있다면 `-sm layer`가 무시됐거나 `-ts`가 잘못된 것이다.

**증거로 남길 것:**
- `start-llama.bat`을 띄운 콘솔 전체 로그(스크롤을 위로 올려 기동 시점부터
  캡처하거나, 콘솔을 `> boot.log 2>&1`로 리다이렉트해 재실행).
- 기동 중/직후의 `nvidia-smi` 출력 — 3장 각각의 사용량이 보이는 스냅샷.
- 모델 적재에 걸린 시간(콘솔 타임스탬프 또는 스톱워치로 체감 측정).

**실패 시 다음에 볼 것:**
- `[FAIL] ...llama-server.exe not found` → 레이아웃이 깨졌다. §1의 매니페스트
  검증부터 다시.
- 드라이버/CUDA 관련 오류 문자열(`CUDA error`, `no kernel image is
  available` 등) → §0에서 잰 드라이버 버전이 551.61 미만이거나, 잘못된
  CUDA 자산이 섞였다는 뜻. **Vulkan으로 바꾸지 않는다** — §8 "알려진
  위험 1"을 본다. `LLAMA_BACKEND=cpu`로 바꿔 원인을 좁힌다(느리지만
  정확, 진단 전용).
- `MSVCP140.dll`을 못 찾는다는 오류 → `bin\llama-cuda\` 안의 app-local
  DLL 3종이 지워졌는지 확인. 스테이징 시 이 3개는 WSL 호스트의
  `C:\Windows\System32`에서 복사됐다(출처는 Task 8a 보고서 참고).
- 포트 충돌(`8080` 이미 사용 중) → 이전 리허설의 `llama-server.exe`가
  안 죽고 남아있는지 작업 관리자에서 확인 후 종료.

---

## 4. 관문 ② — `/v1/models`에 `qwen3.8-27b`가 나타나는가

관문 ①의 창을 그대로 둔 채, 새 콘솔에서:

```
powershell -NoProfile -Command "(Invoke-RestMethod -Uri 'http://127.0.0.1:8080/v1/models') | ConvertTo-Json -Depth 6"
```

**기대 결과:** JSON의 `data` 배열 안에 `"id": "qwen3.8-27b"`가 정확히
그 문자열로 나타난다(대소문자·하이픈까지 일치).

**증거로 남길 것:** 이 JSON 응답 원문 전체(나중에 `verify-offline.bat`이
동일한 것을 `evidence\v1-models.json`에 자동 저장하지만, 관문 판정
시점에 수동으로도 한 번 저장).

**실패 시 다음에 볼 것:**
- 연결 자체가 안 되면 관문 ①이 사실은 실패한 것이다 — 콘솔 로그를
  다시 본다.
- alias가 다른 문자열로 나온다면 `config.env`의 `MODEL_ALIAS`와
  `start-llama.bat`이 실제로 넘긴 `--alias` 값이 다른 것 — `config.env`를
  고치고 관문 ①부터 재시작.

---

## 5. 정적 제공자 선언 확인 — 관문 ③ 전에 반드시 한다

**이 절이 이번 리허설에서 처음 검증되는 경로다.** 스펙 §5.1을 먼저 읽어라.

요지: `pi.exe`에 내장된 llama.cpp 제공자는 llama-server가 **라우터 모드**로
떠 있기를 요구한다(바이너리에 `Server is not running in llama.cpp router
mode`, 동봉 `bin\pi\docs\llama-cpp.md`도 "Start `llama-server` without
`--model` or `-m`"). 그런데 이 번들은 무인 기동의 결정성을 위해 `-m` 단일
모델 모드로 띄운다. 그래서 관문 ①②는 통과하고 관문 ③에서 죽는 구조였다.

해결은 라우터 전환이 아니라 **정적 제공자 선언**이다. 번들 루트의
`models.json`이 로컬 엔드포인트를 제공자 `local`로 선언하고,
`start-pi.bat`·`verify-offline.bat`이 실행 초반에 그것을
`home\agent\models.json`으로 덮어쓴다.

절차:

1. 관문 ①의 서버가 뜬 상태에서, 먼저 `start-pi.bat`을 한 번 실행해
   `models.json`이 배치되게 한다(모델 대기 중이면 그대로 두거나 Ctrl+C로
   빠져나와도 파일은 이미 복사돼 있다). 배치를 확인한다:
   ```
   type home\agent\models.json
   ```
   **기대 결과:** 번들 루트의 `models.json`과 같은 내용. `providers.local`의
   `baseUrl` 포트가 `config.env`의 `LLAMA_PORT`와 같은지도 여기서 본다 —
   `models.json`은 정적 파일이라 환경변수를 읽지 않는다.
2. 제공자와 모델이 Pi에 보이는지 확인한다:
   ```
   set "LLAMA_BASE_URL=http://127.0.0.1:8080"
   bin\pi\pi.exe --offline --list-models
   ```
   **기대 결과:** 목록에 `local/qwen3.8-27b`가 나타난다. 나타나지 않으면
   관문 ③으로 넘어가지 마라 — 원인이 여기 있다.

   **이 명령을 손으로 직접 칠 때만 해당하는 주의:** 여기서 `LLAMA_BASE_URL`을
   일부러 설정하는 것은 `--list-models`가 내장 llama.cpp 제공자까지 함께
   나열하게 하려는 의도다 — 그 제공자는 라우터 API로 모델을 열거하므로
   같은 콘솔 출력 안에 `Server is not running in llama.cpp router mode`가
   **같이 나타나는 것이 정상**이다. 이건 §5.1이 고친 결함의 재발이
   아니다 — `local/qwen3.8-27b`가 목록에 있는지만 보면 된다. (`start-pi.bat`과
   `verify-offline.bat`은 이 변수를 `pi.exe` 호출 직전에 지우므로 실제
   운영 경로에서는 이 문자열이 나오지 않는다 — 2026-08-18 재리뷰.)
3. `config.env`의 `PI_MODEL_ID`가 위 출력과 **글자 그대로** 같은지 대조한다.
   `start-pi.bat`은 이 값을 `--model`로 그대로 넘긴다.

**증거로 남길 것:** `--list-models` 출력 전문, `home\agent\models.json` 내용.

**기록란(§9)에 적을 것:** 목록에 나타난 모델 ID 문자열, `PI_MODEL_ID` 확정값.

**실패 시 다음에 볼 것:**
- 목록에 `local/...`이 전혀 없다 → `home\agent\models.json`이 실제로
  놓였는지, JSON이 유효한지 본다. `start-pi.bat`은 파일이 없으면
  `[FAIL] ...models.json not found`으로 멈춘다.
- 모델은 보이는데 "auth" 관련 사유로 선택 불가 → `models.json`의
  `apiKey` 더미 값이 사라졌는지 확인한다. 키 없는 로컬 서버라도 값이
  있어야 목록에 살아 있다(상류 `bin\pi\docs\models.md`).
- 여전히 `Server is not running in llama.cpp router mode`가 보인다 →
  Pi가 우리 `local` 제공자가 아니라 **내장 llama.cpp 제공자**로 라우팅된
  것이다. `--model`에 제공자 접두사 없이 `qwen3.8-27b`만 넘기지 않았는지,
  `PI_MODEL_ID`가 `local/`로 시작하는지 확인한다.

---

## 5-2. Pi 확장·스킬 로드 확인 — 관문 ③ 전에 반드시 한다

**이 절도 이번 리허설에서 처음 검증되는 경로다.** 스펙 §13(Pi 확장·스킬
반입)을 먼저 읽어라. 조사(`pi-packages-research.md`)는 `pi.exe`가 로드
시점에 npm/git을 전혀 부르지 않는다고 정적 분석으로 결론 내렸고, 이
저장소 안에서(WSL의 `cmd.exe` 경유) `pi list`까지는 실제로 확인했다 —
하지만 GPU가 붙은 실제 리허설 PC에서, 그리고 스킬이 모델 대화에
주입되는 것까지는 아직 아무도 보지 않았다.

절차:

1. `start-pi.bat`을 한 번 실행한다(관문 ①의 서버가 아직 안 떠 있어도
   된다 — 모델 대기 중 Ctrl+C로 빠져나와도 동기화는 이미 끝나 있다).
   `pi-packages\`가 `home\agent\`로 동기화됐는지 파일 시스템에서 확인한다:
   ```
   dir home\agent\npm\node_modules
   dir /a home\agent\git\github.com\obra\superpowers\.git
   type home\agent\settings.json
   ```
   **기대 결과:** `settings.json`의 `packages` 배열에 4개 패키지가 모두
   있고, `npm\node_modules\` 밑에 `pi-subagents`, `@juicesharp\rpiv-todo`,
   `@juicesharp\rpiv-ask-user-question`, `jiti`, `typebox`, `yaml`이
   보이고, `superpowers\.git\`이 실제로 존재한다(윈도우에서 `.git`은
   숨김 속성이라 `dir /a` 로 봐야 보일 수 있다 — 2026-08-18 실측, `/H`
   없이 `xcopy`하면 통째로 스킵된다).
2. 모델 서버 없이, 패키지가 Pi에 등록됐는지 확인한다:
   ```
   bin\pi\pi.exe list
   ```
   **기대 결과:** 네 패키지 모두 "User packages:" 밑에 나열되고, 각
   경로가 `home\agent\npm\...` / `home\agent\git\...`를 가리킨다.
3. 확장이 실제로 로드돼 세션 부트스트랩이 죽지 않는지 확인한다(모델
   서버가 없어도 확장 로드는 세션 시작 단계에서 모델 호출보다 먼저
   일어난다):
   ```
   bin\pi\pi.exe --offline --no-session --mode json -p "hi" --model local/qwen3.8-27b
   ```
   **기대 결과:** JSON 이벤트 스트림이 `session`/`agent_start`까지 정상
   출력되고, 에러가 나더라도 `errorMessage`가 `"Connection error."`여야
   한다(모델 서버가 없어서 나는, 예상된 에러). 확장 로드 자체가 실패하면
   이 지점 이전에 다른 형태의 에러나 스택트레이스가 찍힌다 — 어느
   패키지인지 메시지에서 확인한다.
4. **관문 ①의 서버가 뜬 뒤** 실제 스킬 주입을 확인한다. 대화형
   `start-pi.bat` 세션에서 `/` 를 입력해 명령 자동완성을 열고
   `/skill:brainstorming` 이 목록에 나타나는지 본다. 나타나면 실행해
   보거나, 아무 질문이나 던진 뒤 "지금 사용 가능한 스킬을 나열해줘"라고
   물어본다. **기대 결과:** `/skill:` 자동완성에 superpowers의 스킬
   이름(`brainstorming`, `writing-plans`, `systematic-debugging`,
   `test-driven-development` 등 11종)이 나타난다 — 이것을 1차 성공
   기준으로 삼는다. 27B 로컬 모델이 스킬 존재를 대화 중에 스스로
   언급하지 못할 수 있으므로(조사 문서 §2: "models don't always do
   this"), 모델 응답에만 의존하지 않는다.
5. `pi-subagents`의 `subagent` 툴을 확인한다. **포어그라운드 위임은
   되고 백그라운드 위임은 안 된다** — 그 구분이 이 단계의 요점이다.

   먼저 도구 목록에 나타나는지 본다(대화형 세션에서 "지금 쓸 수 있는
   도구 목록을 나열해줘"). 그다음 **포어그라운드** 위임을 시킨다(예:
   "scout 서브에이전트로 이 폴더의 .bat 파일 개수를 세어줘" — `async`를
   켜지 말 것). **기대 결과: 성공.** 자식 세션은 `pi.exe` 자신으로
   스폰되므로(`runs/shared/pi-spawn.ts`의 `getPiSpawnCommand`가
   `process.execPath`의 파일명이 `pi.exe`면 그것을 그대로 쓴다) Node가
   필요 없다.

   이어서 **백그라운드/async** 위임을 한 번 시켜 본다(`async: true`).
   **기대 결과: 실패.** 이것이 정상이다 — `runs/background/
   async-execution.ts`가 `resolveNodeExecutable()`이 돌려준 `node.exe`로
   러너를 스폰하는데, `pi.exe`에서 실행하면 execPath가 `pi.exe`라 그
   함수는 언제나 문자열 `"node.exe"`를 돌려주고, Node가 없는 폐쇄망
   PC에서는 프로세스 생성이 `ENOENT`로 죽는다. 콘솔이나 로그에
   `[pi-subagents] async spawn failed: ... ENOENT` 류 메시지가 보이면
   원인이 확정된 것이다.

   **관찰되지 않을 것(예전 절차서가 잘못 지목했던 증상):** 2차
   `llama-server` 기동도, 새 `pi.exe`의 VRAM 추가 점유도 일어나지
   않는다. 백그라운드 러너는 프로세스 생성 단계에서 죽으므로 GPU에
   도달하지 못하고, 포어그라운드 자식은 같은 `local` 정적 제공자
   (`http://127.0.0.1:8080`)로 HTTP 요청만 보내므로 모델을 다시 띄우지
   않는다. `nvidia-smi` 스냅샷은 그 사실을 확인하는 용도로 남긴다.

   **동시 요청은 폭주가 아니라 직렬화다.** `start-llama.bat`이
   `--parallel 1`로 띄우므로 llama-server는 요청을 한 번에 하나씩
   처리한다. 포어그라운드 위임을 N개 겹치면 응답이 뒤섞이는 것이
   아니라 지연이 N배가 되고, 그것이 재시도와 겹쳐 타임아웃처럼 보인다.
   여러 개를 겹쳐 시켜 볼 때는 이 점을 알고 시간을 재라.

**증거로 남길 것:** `pi list` 출력 전문, 3번 스모크 테스트의 JSON 출력,
`/skill:` 자동완성 스크린샷 또는 답변 텍스트, subagent 위임 시도의
성공/실패와 그때의 `nvidia-smi` 스냅샷.

**기록란(§9)에 적을 것:** `pi list`에 나타난 패키지 4개 유무, 3번
스모크 테스트 결과(Connection error만 나왔는지), `/skill:` 자동완성
성공 여부, `subagent` 툴 위임 성공 여부와 GPU 충돌 관찰 여부.

**실패 시 다음에 볼 것:**
- `pi list`에 패키지가 하나도 없다 → `home\agent\settings.json`이
  실제로 놓였는지 본다. 이미 있던 `settings.json`을 재사용 중이면(2회차
  이상 실행) 최초 실행이 아니라서 심어지지 않은 것일 수 있다 — 스펙
  §13.3 참고, 지우고 다시 실행해 재현한다.
- `npm\node_modules\`가 비어 있거나 `git\...\superpowers\`에 `.git`이
  없다 → `pi-packages\`에서 `home\agent\`로 동기화가 실패했거나
  일부만 됐다는 뜻이다. `start-pi.bat` 콘솔에 `[FAIL] pi-packages\...`
  메시지가 있었는지 다시 본다.
- 3번 스모크 테스트에서 `Connection error.` 이외의 에러(스택트레이스,
  "Failed to load"류 메시지)가 보인다 → 확장 하나가 깨진 것이다. 네
  패키지를 하나씩 `--no-extensions -e <경로>`로 단독 로드해 범위를
  좁힌다.
- `/skill:` 자동완성에 아무것도 안 뜬다 → `--no-skills`가 실수로
  켜져 있지 않은지, `home\agent\git\github.com\obra\superpowers\skills\`
  디렉터리가 실제로 존재하는지 확인한다.
- **포어그라운드** 위임이 실패한다 → 예상 밖이다. 에러가 `ENOENT`나
  `node`를 가리키면 이 경로도 Node를 타고 있다는 뜻이므로
  `pi-spawn.ts`의 판정(`process.execPath`가 `pi.exe`인가)이 이 빌드에서
  깨진 것이다. 에러 전문을 그대로 기록한다. 모델 쪽 에러(연결/타임아웃)면
  위임이 아니라 §5의 배선이나 `--parallel 1` 직렬화 문제다.
- **백그라운드/async** 위임이 실패한다 → **정상이다.** 폐쇄망에 Node가
  없기 때문이고, 스펙 §13.5 우려 3번이 설명하는 그대로다. 실패로
  기록하지 말고 "예상된 실패, ENOENT 확인"으로 기록한다. 반대로 이것이
  성공하면 대상 PC에 Node가 설치돼 있다는 뜻이므로 그 사실을 기록한다.
- `nvidia-smi`에 두 번째 `llama-server.exe` 또는 새 `pi.exe` 프로세스의
  VRAM 점유가 보인다 → 예상 밖이다. 이 구성에서는 어느 위임 경로도
  모델을 다시 띄우지 않는다. 보이면 무엇이 떴는지 프로세스 목록째
  기록하고, 필요하면 `pi-subagents`를 비활성화(`--no-extensions` 또는
  `home\agent\settings.json`에서 해당 패키지 항목 제거)하는 것도
  고려한다.

---

## 6. 관문 ③ — Pi가 툴 왕복을 완주하는가

새 콘솔에서:

```
start-pi.bat
```

**기대 결과:** 콘솔에 `wait_model.py`가 먼저 `[ok] qwen3.8-27b 준비됨`을
찍고(§5 부트스트랩 계약의 readiness 폴링 단계), 그 다음 Pi가 대화형으로
뜬다.

대화형 세션에서 실제 파일 읽기 왕복을 시킨다. 예:

```
번들 루트의 README-폐쇄망.md 파일을 읽고 "하지 않는 것" 절에 나오는
항목을 그대로 나열해줘
```

**기대 결과 — 다음 세 가지가 모두 보여야 완주로 친다(스펙 §5 Step 5,
§8.3):**
1. Pi가 파일 읽기 툴 호출을 **실제로 실행**한다(모델이 문자열만
   생성하고 끝나는 게 아니라, Pi 로그/화면에 도구 실행 흔적이 보임).
2. 실행 결과(파일 내용)가 모델에 되돌아간다.
3. 그 결과를 반영한 **최종 답변**이 나온다(파일에 없는 내용을 지어내면
   실패).

이것이 스펙이 강조하는 지점이다 — "툴 호출 문자열이 생성됐다"는 통과
기준이 아니다(§8.3).

**증거로 남길 것:**
- 이 세션의 전체 텍스트(질문, 도구 호출, 도구 결과, 최종 답변).
- 체감 토큰/초(Pi가 표시하면 그 값, 아니면 답변 길이와 소요 시간으로
  추정).
- 32k에 가까운 긴 프롬프트 1회와 장시간 생성 1회도 시도해 본다(§8.1) —
  dense 27.8B라 Pascal에서 느릴 것으로 예상되므로(§8 "알려진 위험 3"),
  실사용에 버틸 만한 속도인지 여기서 감을 잡는다.

**실패 시 다음에 볼 것:**
- `[FAIL] the model is not ready` → 관문 ②가 사실 실패였거나 600초
  타임아웃 안에 적재가 안 끝난 것. 모델이 15.66GB라 디스크가 느리면
  적재 자체가 오래 걸릴 수 있다 — §0에서 디스크 여유/속도도 함께
  본다.
- 툴 호출 자체가 안 일어남(모델이 그냥 텍스트로만 답함) → §8.3의 7개
  조건 중 1~4번(GGUF의 `tokenizer.chat_template`, llama.cpp의 템플릿
  인식, Pi의 tools 스키마 전송, llama-server의 `tool_calls` 반환 형식)을
  의심. `tools\gguf.py`의 `check_tool_capable`을 다시 돌려 GGUF 쪽
  문제인지 먼저 배제:
  ```
  %PYTHON_CMD% tools\stage.py model-check --root .
  ```
- 모델 ID 불일치 오류 → `config.env`의 `PI_MODEL_ID`(Pi의 `--model`,
  `local/qwen3.8-27b`)와 `MODEL_ALIAS`(llama-server의 `--alias`,
  `qwen3.8-27b`)가 어긋난 것. 뒷부분이 글자 그대로 같아야 한다.
- **`Server is not running in llama.cpp router mode`** → `start-pi.bat`으로
  뜬 관문 ③ 콘솔에서 이 문자열이 나오면 이번 웨이브가 고친 바로 그 결함이
  재발한 것이다(스펙 §5.1). Pi가 우리 `local` 정적 제공자가 아니라 내장
  llama.cpp 제공자로 라우팅됐다는 뜻이다. 순서대로 확인한다: (1)
  `home\agent\models.json`이 실제로 놓였는가, (2) 그 JSON이 유효하고
  `providers.local`을 담고 있는가, (3) `--model`에 제공자 접두사 `local/`이
  붙어 나갔는가(`PI_MODEL_ID` 확인), (4) `models.json`의 `baseUrl` 포트가
  `LLAMA_PORT`와 같은가, (5) `LLAMA_BASE_URL`이 `pi.exe` 호출 전에 지워졌는가
  — `start-pi.bat`·`verify-offline.bat`은 모델 대기가 끝난 뒤 `pi.exe`를
  부르기 직전에 `set "LLAMA_BASE_URL="`으로 지운다(2026-08-18 재리뷰). 이
  변수가 남아 있으면 내장 llama.cpp 제공자가 인증된 것으로 취급되어 모델
  목록에 살아나고, 그 제공자가 같은 오류 문자열을 낸다 — 단, 이때는 우리
  `local` 정적 제공자가 아니라 그 곁에 **함께** 나타난 내장 제공자가 낸
  것이므로 관문 ③ 자체(도구 왕복)와는 무관할 수 있다. §5에서 사람이 직접
  `set "LLAMA_BASE_URL=..."` 뒤에 `--list-models`를 돌릴 때는 이 문자열이
  나오는 것이 정상이며 결함 재발이 아니다 — 거기서는 내장 제공자를 일부러
  드러내 보이려는 것이기 때문이다. **여기서 라우터 모드
  (`--models-dir`)로 바꾸지 마라** — 무인 기동의 결정성과 mmproj 평면
  배치 결정을 함께 깨뜨린다(스펙 §5.1, §6).
- 파이썬 관련 오류(`could not find Python`, import 실패) → §0의 파이썬
  행으로 돌아간다. `bin\python\python.exe`가 번들에 있으면 그것이 먼저
  쓰인다. `config.env`의 `PYTHON_CMD`로 강제 지정할 수도 있다.
- `[FAIL] PI_MODEL_ID is not set` → `config.env`를 채우지 않았거나, 채웠는데도
  적용되지 않은 것이다. 후자라면 `home\agent\config.cmd`가 만들어졌는지
  본다 — `.bat`은 `config.env`를 그 `.cmd` 사본을 거쳐 읽는다(스펙 §5.2).

---

## 7. 관문 ④ — 스크린샷 속 에러 메시지를 읽어내는가 (비전 프로젝터)

`config.env`의 `MMPROJ_FILE`이 채워져 있으므로(스테이징 시 기본값을
채워 둠) 관문 ①의 서버는 이미 `--mmproj`로 멀티모달 상태로 떠 있어야
한다. "멀티모달로 떴다"는 통과 기준이 아니다 — 실제로 이미지 속 문자를
읽어내는지가 기준이다(§8.1의 비전 프로젝터 확인 항목 3가지를 그대로
따른다).

절차:

1. **적재 영향 실측** — 관문 ①의 콘솔 로그에서 `--mmproj` 관련 적재
   로그(프로젝터 텐서 수, 적재 시간)를 확인하고, `nvidia-smi`로 프로젝터
   포함 총 VRAM 사용량을 잰다. §6 계산상 텍스트 모델만 약 17.8GiB,
   프로젝터 포함 약 18.7GiB로 추정돼 있다 — 실측값이 이 추정과 크게
   벗어나는지 기록.
2. **텍스트 전용 경로 회귀 확인** — `MMPROJ_FILE`이 설정된 상태에서도
   관문 ②(`/v1/models` alias)와 관문 ③(툴 왕복)이 그대로 통과하는지
   다시 확인한다. 영향이 있으면(툴 왕복이 깨지면) `config.env`의
   `MMPROJ_FILE=`을 비우고 텍스트 전용으로 되돌려 재확인 — 이 경우
   관문 ④는 "비전 비활성화, 알려진 제약으로 기록"으로 결론짓는다.
3. **실제 이미지 판독** — 아무 에러 메시지가 보이는 스크린샷 한 장을
   준비한다(예: 윈도우 이벤트 뷰어의 오류 다이얼로그를 캡처, 또는
   임의의 텍스트가 든 PNG). 비대화형으로 확인:
   ```
   bin\pi\pi.exe --offline -p @스크린샷.png "이 에러 메시지에 나온 문자열을 그대로 옮겨 적어라"
   ```
   또는 대화형 `start-pi.bat` 세션에서 `Alt+V`(윈도우 전용 — `Ctrl+V`
   아님)로 이미지를 붙여넣거나 터미널에 파일을 드래그.

**기대 결과:** 답변에 스크린샷 속 문자열이 **정확히** 포함된다. 대략적인
설명("에러 창이 보인다")은 실패로 친다 — 실사용 목적이 정확한 에러 코드
판독이기 때문이다(§6 표, §8.1).

**증거로 남길 것:**
- 사용한 스크린샷 원본.
- 적재 로그 발췌(프로젝터 관련 줄)와 VRAM 사용량 스냅샷.
- 판독 응답 전문 — 스크린샷 속 원문과 나란히 대조할 수 있게.
- BF16 프로젝터가 Pascal(FP16/BF16 텐서코어 없음)에서 어떻게 처리됐는지
  콘솔에 관련 경고/변환 로그가 있으면 그것도 남긴다.

**실패 시 다음에 볼 것:**
- 이미지가 아예 입력되지 않음 → README "GPU가 안 잡힐 때"·"이미지
  입력이 안 될 때" 절의 순서대로: 먼저 `MMPROJ_FILE`을 비우고 텍스트
  전용이 되는지 확인해 배선 문제와 모델 문제를 구분.
- 판독은 되지만 부정확 → BF16→Pascal 변환 정확도 문제로 기록(§8 "알려진
  위험 2"). 반입 여부 자체를 막는 조건은 아니나, README에 "정확도
  낮음, 텍스트로 재확인 권장" 같은 실사용 주의사항 추가를 고려.

---

## 8. 오프라인 재시험 — 관문 ①~④를 다시, 이번엔 네트워크 없이

여기까지 인터넷이 연결된 상태로 통과했다면, **이 조건에서 다시 통과해야
반입 가능**하다(§8.1, §8.2). 인터넷 연결 상태의 통과만으로는 불충분하다 —
폐쇄망 PC는 애초에 네트워크가 없고, 오프라인 스위치(`PI_OFFLINE=1`)가
정말로 아웃바운드를 막는지는 이 재시험에서만 증명된다(§3.2).

절차:

1. **기존 Pi home/cache를 지운다** — `home\agent\`를 삭제하고 처음부터
   다시 시작한다(§8.1). 이전 실행의 캐시된 상태가 오프라인 실패를
   가려줄 수 있기 때문이다. `home\agent\models.json`과 `config.cmd`도 같이
   지워지는데 정상이다 — `start-pi.bat`·`verify-offline.bat`이 번들 루트의
   원본에서 매번 다시 만든다(스펙 §5.1, §5.2). 이 재시험이 그 재생성
   경로를 실제로 확인해 준다.
2. **네트워크를 차단한다** — 둘 중 하나:
   - NIC을 비활성화(제어판 → 네트워크 연결 → 사용 안 함), 또는
   - Windows 방화벽으로 `127.0.0.1` 외 아웃바운드를 차단하는 규칙 추가
     (localhost 통신은 살려 둬야 llama-server ↔ Pi 통신이 된다).
3. 관문 ①~④를 **처음부터 다시** 실행한다. 명령은 동일.
4. **`verify-offline.bat`을 실행한다** — 이것이 폐쇄망 도착 후 실제로
   쓰일 스크립트이므로, 리허설에서 한 번 그대로 돌려 스크립트 자체의
   문제를 미리 잡는다:
   ```
   verify-offline.bat
   ```
   `evidence\`에 남는 것: `nvidia-smi.txt`, `manifest-check.txt`,
   `v1-models.json`, `probe.txt`(스크립트가 직접 쓰는 프로브 파일 —
   낱말 `NARWHAL-7Q2X` 한 줄), `pi-tool-roundtrip.json`,
   `pktmon.etl`/`pktmon.txt`(관리자 권한이 있을 때만), 그리고 콘솔에
   찍히는 확인 안내 문구. **`pi-tool-roundtrip.json` 판정 기준은 그 안에
   실제 도구 실행 흔적이 있고 최종 답변이 `NARWHAL-7Q2X`를 담는 것이다** —
   모델이 파일을 못 읽고 지어냈다면 이 낱말이 나올 수 없다.
   **exit 코드가 아니라 `evidence\` 안의 내용이 판정 기준**이다(§8.2).
5. `pktmon.txt`(또는 관리자 권한이 없어 못 남겼다면 방화벽/네트워크
   모니터 로그)에서 **외부 주소로의 연결 시도 0건**을 확인한다 — 성공한
   연결이 0건이 아니라 **시도 자체가 0건**이어야 한다(§8.2). `localhost`/
   `127.0.0.1` 트래픽은 제외하고 본다.

**증거로 남길 것:** `evidence\` 폴더 전체를 이 리허설용으로 별도 보관
(다음 폐쇄망 실행 때 덮어써지므로).

**실패 시 다음에 볼 것:**
- 오프라인에서만 실패하는 항목이 있다면 그게 곧 "인터넷 연결에
  암묵적으로 의존하던 부분"이다 — 어느 관문에서 갈렸는지 그대로
  기록하고, 그 관문의 "실패 시 다음에 볼 것"을 참고해 원인을 좁힌다.
- `pktmon`이 관리자 권한 없이 시작 안 됨 → `verify-offline.bat`이
  `[warn]`을 찍고 계속 진행한다. 이 경우 네트워크 시도 0건 확인은
  방화벽 로그나 리소스 모니터의 수동 관찰로 대체하고, 그 사실을
  기록란에 남긴다(§10의 "그룹 정책/AppLocker/Defender" 확인 항목과도
  연결된다 — 관리자 권한 없는 환경에서 어디까지 되는지가 곧 현장
  확인 대상).

---

## 9. 기록란

### 0. 전제

| 항목 | 실측값 |
|---|---|
| 드라이버 버전 | ______ (551.61 이상: Y / N) |
| GPU0 총/여유 VRAM | ______ / ______ MiB |
| GPU1 총/여유 VRAM | ______ / ______ MiB |
| GPU2 총/여유 VRAM | ______ / ______ MiB |
| VC++ 런타임 시스템 설치 | 있음 / 없음 (버전 다르면: ______) |
| 관리자 권한 | 있음 / 없음 |
| clean 상태(Node/CUDA toolkit 미설치) | Y / N |
| 파이썬 — `bin\python\python.exe -V` | ______ |
| 파이썬 — `py -3.12 -V` | ______ (없음/스텁이면 그렇게 적기) |
| 파이썬 — `python -V` | ______ (없음/스텁이면 그렇게 적기) |
| `.bat`이 실제로 쓴 파이썬 | 번들 내장 / `py -3.12` / `python` / `PYTHON_CMD` |

### -ts 확정값

`GPU_TENSOR_SPLIT=______________` (근거: 위 free VRAM 비율)

### 관문 ①(CUDA 기동/3장 분산)

- 결과: 통과 / 실패
- 모델 적재 시간: ______
- 기동 시 3장 VRAM 사용량: GPU0 ______ / GPU1 ______ / GPU2 ______

### 관문 ②(`/v1/models` alias)

- 결과: 통과 / 실패
- 응답에 나온 정확한 id 문자열: ______________

### Pi 제공자/모델 ID (정적 선언)

- `--list-models` 출력에서 확인한 제공자 이름: ______________
- 모델 ID 형식: ______________
- `--list-models` 에 나타난 모델 ID: `______________`
- `PI_MODEL_ID=______________` (확정값)
- `home\agent\models.json` 배치 확인: 예 / 아니오
- 실제로 쓰인 파이썬: 번들 내장 / `py -3.12` / `python` / `PYTHON_CMD` 지정

### Pi 확장·스킬 로드 확인 (§5-2)

- `pi list`에 나타난 패키지 4개: 예 / 아니오 (빠진 것: ______)
- `home\agent\npm\`, `\git\...\superpowers\.git\` 실제 존재: 예 / 아니오
- `home\agent\settings.json`에 packages 배열 등록: 예 / 아니오
- 3번 스모크 테스트(`--mode json -p "hi"`) 에러가 `Connection error.`뿐인가: 예 / 아니오
- `/skill:brainstorming` 자동완성에 나타남: 예 / 아니오
- `subagent` 툴이 도구 목록에 나타남: 예 / 아니오
- **포어그라운드** 위임 성공(기대: 성공): 예 / 아니오 / 미시행 — 에러: ______
- **백그라운드/async** 위임(기대: ENOENT 실패): 예상대로 실패 / 성공(=Node 있음) / 미시행
  - 실패 메시지에 `node` 또는 `ENOENT`가 있었나: 예 / 아니오 (실제 문구: ______)
- 위임 중 GPU/VRAM 추가 점유(2차 프로세스) 관찰(기대: 없음): 없음 / 있음(내용: ______)
- 포어그라운드 위임 N개를 겹쳤을 때 체감 지연(`--parallel 1` 직렬화 확인): ______

### 관문 ③(툴 왕복)

- 결과: 통과 / 실패
- 체감 토큰/초: ______
- 32k 근접 프롬프트 시험: 통과 / 실패 / 미시행

### 관문 ④(비전 프로젝터 — 스크린샷 판독)

- 적재 시간/VRAM 영향: ______
- 텍스트 전용 경로(②③) 회귀 없음: Y / N
- 스크린샷 문자열 정확 판독: Y / N (부정확하면 어떻게 틀렸는지: ______)

### 오프라인 재시험 (①~④ 반복)

- 결과: 통과 / 실패 (실패 시 어느 관문: ______)
- `verify-offline.bat` 종료 코드: ______ (참고용, 판정 기준 아님)
- `evidence\` 내용 확인: nvidia-smi ✓/✗, manifest-check ✓/✗, v1-models ✓/✗,
  pi-tool-roundtrip ✓/✗, 외부 연결 시도 0건 ✓/✗
- 백업 모델 필요 여부(§6): 필요 / 불필요 — 판단 근거: ______

---

## 10. 알려진 위험 네 가지 (절차 중 반드시 인지)

1. **Vulkan은 이 모델에 금지, 폴백은 CPU뿐.** `bin\llama-vulkan`은
   qwen35 아키텍처의 `ggml_ssm_conv`/`ggml_ssm_scan`을 구현하지 않고
   조용히 CPU로 폴백하면서 GPU↔CPU 경계에서 상태가 손상된다(상류 이슈
   `ggml-org/llama.cpp#19957`, 2026-02-27 open, 미해결 — 손상된 출력 또는
   `vk::DeviceLostError`로 이어짐). 관문 ①이 CUDA에서 실패해도 **Vulkan
   으로 넘어가지 마라** — `LLAMA_BACKEND=cpu`로 바꿔 원인을 좁힌다(느리지만
   정확, 진단 전용이지 실사용 대체재가 아님).
2. **BF16 프로젝터의 Pascal 처리 미검증.** `mmproj-Qwen3.8-27B-BF16.gguf`는
   BF16인데 Pascal(compute 6.1)은 BF16 텐서코어를 지원하지 않는다.
   llama.cpp가 변환해서 처리하긴 하겠지만 적재 시간·VRAM 사용량·정확도에
   미치는 영향이 실측된 적이 없다 — 관문 ④가 이걸 처음 재는 자리다.
3. **dense 27.8B라 Pascal에서 속도 저하 예상.** 당초 검토했던 MoE
   후보(활성 3.3B)와 달리 이 모델은 매 토큰 전체 27.8B가 활성화된다.
   FP16 텐서코어가 없는 Pascal에서 체감 저하가 예상되며, 하이브리드
   선형 어텐션은 긴 프롬프트의 prefill만 완화할 뿐 디코드 연산량 자체를
   줄이지 않는다. 관문 ③에서 잰 토큰/초가 실사용에 버틸 만한지가 이번
   리허설의 실질적 판정 포인트 중 하나다 — 너무 느리면 §6의 "백업 모델"
   반입 여부를 여기서 다시 논의해야 한다.
4. **`pi-subagents`의 백그라운드 위임은 폐쇄망에서 못 쓴다.**
   포어그라운드 위임은 `pi.exe` 자신을 스폰하므로 Node 없이 동작하지만
   (`runs/shared/pi-spawn.ts`), 백그라운드/async 위임은
   `runs/background/async-execution.ts`가 `node.exe`로 러너를 스폰하므로
   Node가 없는 PC에서 `ENOENT`로 죽는다. 스펙 §13.5, §5-2 절차 5번에서
   이 구분을 실측한다. 예전 판의 "2차 llama-server 기동이나 VRAM 점유를
   관찰하라"는 서술은 틀렸다 — 백그라운드 러너는 GPU에 도달하기 전에
   죽고, 포어그라운드 자식은 같은 `llama-server`에 HTTP로 붙을 뿐이다.
   동시 요청도 폭주가 아니라 직렬화다: `--parallel 1`이므로 위임 N개를
   겹치면 지연이 N배가 되고 재시도와 겹쳐 타임아웃처럼 보인다.
   백그라운드 위임에 의존하는 워크플로가 필요하면
   `home\agent\settings.json`에서 `npm:pi-subagents@0.50.0` 항목을 빼거나
   `--no-extensions`로 세션별로 끄는 것을 고려한다
   (`README-폐쇄망.md`의 "확장을 끄고 싶을 때" 절 참고).
