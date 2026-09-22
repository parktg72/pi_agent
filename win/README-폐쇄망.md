# 폐쇄망 실행 안내

## 전제
- 관리자 권한 없이 압축 해제만으로 동작한다.
- 이 번들은 한 사용자 계정 전용이다. `home\agent` 에 세션과 툴 출력이 쌓이고 여기에는 작업한 소스 내용이 남는다.

## 순서

| # | 실행할 것 | 언제 | 창 |
|---|---|---|---|
| 0 | 번들을 `C:\pi_agent` 로 복사 | 최초 1회 | — |
| 1 | `verify-bundle.bat` | 최초 1회 | 아무 창 |
| 2 | `config.env` 의 `GPU_TENSOR_SPLIT` 채우기 | 최초 1회 | — |
| 3 | `install-python-packages.bat` | 파이썬 작업이 필요할 때만 | 아무 창 |
| 4 | `start-llama.bat` | **매번**, 가장 먼저 | 전용 창 — 닫지 않는다 |
| 5 | `start-pi.bat` | **매번**, 4번 다음 | 작업 폴더에서 |
| 6 | `verify-offline.bat` | 최초 1회 + 문제 생겼을 때 | 아무 창 |
| 7 | `install-kg.bat` → `start-llama.bat kg` + `start-embedding.bat` + `start-lightrag.bat` | 지식그래프 작업이 필요할 때만 | 아래 "지식그래프 스택" 절 |

**매번 반복되는 것은 4→5 둘뿐이다.** 나머지는 처음 한 번이다.

**1 — 무결성 검사가 먼저다.** 전송 중 손상은 여기서만 잡힌다. 출력의 파일 수가
`STAGING_MANIFEST.json` 의 `totals.files` 와 같아야 한다. 다르면 **거기서 멈추고
다시 복사한다** — 뒤 단계는 전부 무의미해진다. **반드시 `verify-bundle.bat`
으로 실행한다 — `bin\python\python.exe tools\verify_bundle.py` 를 직접 부르지
않는다.** 이 배치를 거치지 않으면 콘솔 코드페이지 지정(`chcp 65001`)과
`PYTHONIOENCODING=utf-8` 이 빠져 파이썬 출력이 콘솔 기본 코드페이지(한국어
윈도우면 CP949)로 나가고, 한글 진단 메시지가 깨진다(2026-08-18 윈도우 실측 —
"간단하니 직접 부르자"로 되돌리지 마라).

**2 — 현장에서 확인할 값은 `GPU_TENSOR_SPLIT` 하나다.** 나머지(`MODEL_FILE`,
`MODEL_ALIAS`, `PI_MODEL_ID`, `MMPROJ_FILE`, `MODEL_LOAD_TIMEOUT`)는 반입 시점에
이미 채워져 있다. 반입값은 지식그래프 번들의 시작값 `10,11,8` 이다 — 0번은 화면
출력, 2번은 임베딩 서버(bge-m3, 약 1.2 GB)와 같이 쓰므로 둘 다 덜 준다. 이 PC의
`nvidia-smi` 여유 VRAM으로 다시 정한다. 비우면 llama.cpp 기본 분배를 쓴다.
`1,1,1` 로 고정하지 않는다 — 디스플레이가 붙은 GPU의 실여유가 다른 두 장보다 적다.

비율을 손으로 정하기 어렵다면 같은 폴더의 `llama-fit-params.exe` 가 현재 여유
VRAM에서 맞는 분배를 계산해 출력한다(llama.cpp b11010 `tools/fit-params`).
`start-llama.bat` 과 같은 모델·컨텍스트로 한 번 돌리고, 출력된 `-ts` 값을
`GPU_TENSOR_SPLIT` 에 옮긴다.

```
cd C:\pi_agent
bin\llama-cuda\llama-fit-params.exe -m models\Qwen3.8-27B-UD-Q5_K_M.gguf -c 63488 -sm layer -ctk q8_0 -ctv f16
```

출력에 `-ngl` 이 전체 층 수보다 작게 나오면 모델이 VRAM에 다 안 들어간다는
뜻이다 — 그대로 쓰지 말고 `LLAMA_CTX` 를 줄이거나 `LLAMA_KV_TYPE=q8_0` 을
먼저 검토한다(아래 "설정 최적화"). `start-llama.bat` 은 `-ngl 999` 로 전 층을
GPU에 강제하므로, 안 들어가면 느려지는 대신 기동이 실패한다.

`llama-fit-params.exe` 가 "Device Guard 정책에 의해 차단" 으로 안 뜰 수 있다 —
2026-09-17 스테이징 PC에서 실제로 그랬다(같은 폴더의 `llama-server.exe` 는
실행됐다). 그때는 위의 `nvidia-smi` 비율 방식으로 채운다.

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

**6 — `verify-offline.bat` 이 마지막에 판정을 찍고, 실패하면 nonzero로 끝난다.**

콘솔 마지막의 `=== 판정 요약 ===` 이 항목별로 `[PASS]`/`[FAIL]` 을 적는다.
파일 넷을 눈으로 대조하지 않아도 무엇이 깨졌는지 거기서 안다.

| 항목 | 무엇을 보나 |
|---|---|
| 번들 무결성 | `manifest-check.txt` — 매니페스트와 일치 |
| models.json 생성 | `config.env` 의 포트·alias·컨텍스트로 `home\agent\models.json` 이 만들어졌고, `settings.json` 에 컨텍스트 안전값(아래 절)이 들어갔다 |
| 패키지 트리 동기화 | `pi-packages\` 전량이 `home\agent\` 에 경로·크기·해시까지 같게 놓였다 |
| `/v1/models` 의 alias | `v1-models.json` 에 `MODEL_ALIAS` 가 있다 |
| 확장/스킬 4종 | `pi-packages.txt` 에 4종이 나열된다 |
| Pi 툴 왕복 | `pi-tool-roundtrip.json` 의 이벤트가 성립한다 (아래) |

툴 왕복은 **Pi의 종료 코드로 판정하지 않는다.** `pi.exe` 는 `stopReason: error`
와 `Connection error.` 를 낸 직후에도 0을 반환한 적이 있다(2026-08-19 실측).
대신 JSON 이벤트를 본다: `stopReason` 이 error가 아닐 것, 최종 assistant 응답이
있을 것, 토큰 수가 양수일 것, 도구 호출과 그 결과가 있을 것, 최종 답변에
`NARWHAL-7Q2X` 가 있을 것. 그 낱말은 스크립트가 직접 쓴 프로브 파일에서 온다 —
모델이 파일을 못 읽고 지어냈다면 나올 수 없다.

두 가지는 여전히 눈으로 본다: `nvidia-smi.txt` 의 드라이버 버전(551.61 이상)과
`pktmon.txt` 의 외부 주소 시도 0건.

증거 수집은 중간에 멈추지 않는다. 어느 단계가 실패해도 나머지 단계를 끝까지
돌고 마지막에 한 번에 판정한다 — 실패한 이유를 설명하는 증거를 버리지 않기
위해서다.

무결성 검사가 무언가를 지적하면 그것은 진짜 전송 손상이다 — `config.env` 는
해시 범위 밖이므로 값을 고친 것 때문에 빨간불이 뜨지는 않는다(아래
"`config.env` 는 실행되지 않는다" 절).

## 모델 ID 두 개가 반드시 맞아야 한다

`config.env` 에는 이름이 비슷한 값이 둘 있다. 어긋나면 서버는 정상인데 Pi만
모델을 찾지 못한다.

| 값 | 누가 읽나 | 예 |
|---|---|---|
| `MODEL_ALIAS` | `llama-server` 의 `--alias`. `/v1/models` 에 이 이름으로 나타난다 | `qwen3.8-27b` |
| `PI_MODEL_ID` | Pi의 `--model`. `<제공자>/<MODEL_ALIAS>` 형식이다 | `local/qwen3.8-27b` |

`PI_MODEL_ID` 의 앞부분 `local` 은 번들 루트 `models.json` 이 선언하는 제공자
이름이고, 뒷부분은 `MODEL_ALIAS` 와 **글자 그대로 같아야 한다.**

## 사고 수준과 "Response was truncated before completion."

Pi 화면에 이 영어 한 줄이 뜨고 턴이 그대로 끝나면, 모델이 답을 다 쓰기 전에
출력 한도에 부딪힌 것이다. 공급자가 `finish_reason: "length"` 를 돌려줬다는
뜻이고, Pi는 그 턴을 이어가지 않는다.

이 번들에서 그 한도를 밀어붙이는 것은 대개 **사고 토큰**이다. GGUF 안의
Qwen3.8 채팅 템플릿은 요청에 `reasoning_effort` 가 없으면 스스로 `xhigh` 를
쓴다:

```
{%- set resolved_reasoning_effort = reasoning_effort|default('xhigh') %}
```

사고 토큰은 답변과 같은 출력 예산을 쓴다. Pi는 대화가 `contextWindow - 16384`
를 넘으면 자동 압축한다(`bin\pi\docs\compaction.md` 의 `reserveTokens`).
`contextWindow` 는 `config.env` 의 `LLAMA_CTX` 에서 렌더링된다 — 2026-09-17
이전에는 템플릿에 32768이 박혀 있어 서버를 65536으로 띄워도 Pi는 32768 창을
가정했다. 32768이면 실사용 답변 예산이 대략 12,000 토큰이고, xhigh 로 도는 긴
턴은 그 선을 넘길 수 있다. 기본값 63488(62k)이면 압축은 47,104 초과에서 일어나 여유가 크게 늘지만 사고 토큰이
출력 예산을 먹는 구조는 같다.

그래서 `config.env` 에 `PI_THINKING` 이 있다.

| 값 | 뜻 |
|---|---|
| `off` | 사고를 끈다. 템플릿이 `<think>` 를 즉시 닫는다 |
| `low` | 짧게 생각하고 결론으로 간다 |
| `medium` | 번들 기본값 |
| `high` | 템플릿의 `xhigh` 로 매핑된다 — 가장 길게 생각한다 |

`start-pi.bat` 이 이 값을 `--thinking` 으로 넘긴다. 비워 두거나 이 키가 없던
시절의 `config.env` 를 쓰고 있으면 `medium` 이 적용된다. 세션 안에서는
`/thinking` 으로 즉시 바꿀 수 있고, **Shift+Tab** 이 단계를 순환한다.

잘림이 계속되면 순서는 이렇다: `/thinking low` → 그래도 잘리면 요청을 쪼개
파일로 나눠 쓰게 한다 → 그래도면 `LLAMA_CTX` 상향을 검토한다(VRAM 실측이
먼저다).

### 왜 `models.json` 이 필요한가

`pi.exe` 에 내장된 llama.cpp 제공자는 llama-server가 **라우터 모드**로 떠
있기를 요구한다(`--models-dir` 로 띄우고 모델을 API로 적재하는 방식). 이
번들은 무인 기동의 결정성을 위해 `-m` 단일 모델 모드로 띄우므로 그 경로를 쓸
수 없다. 대신 번들 루트의 `models.json` 이 OpenAI 호환 엔드포인트를 제공자
`local` 로 **정적 선언**한다.

번들 루트의 `models.json` 은 **템플릿**이다. 포트와 alias 자리에
`${LLAMA_PORT}`, `${MODEL_ALIAS}` 자리표시자가 들어 있고, `start-pi.bat` 과
`verify-offline.bat` 이 실행할 때마다 `config.env` 의 값으로 렌더링해
`home\agent\models.json` 을 새로 쓴다. 그래서 포트와 alias의 출처는
`config.env` 하나뿐이다.

**`models.json` 도, `home\agent\models.json` 도 손으로 고치지 마라.** 앞은
매니페스트 해시 범위 안이라 고치면 무결성 검사가 잡고, 뒤는 다음 실행에서
덮어써진다. `LLAMA_PORT` 만 바꾸면 둘 다 따라온다.

이 구조 이전에는 포트가 두 곳에 따로 있었고, `LLAMA_PORT` 만 바꾸면 readiness
폴링은 새 포트로 통과하는데 Pi는 8080으로 붙으려다 실패했다 — 그리고 그
실패가 exit 0으로 보고됐다(2026-08-19 외부 감사 실측).

> **이 연결 방식은 리허설에서 처음 검증된다.** 정적 제공자 선언이 이 Pi
> 빌드에서 실제로 동작하는지는 윈도우에서 `pi.exe` 를 돌려봐야만 안다.

## `config.env` 는 실행되지 않는다 — 파싱된다

`config.env` 는 `.bat` 문법으로 생겼지만 **코드로 실행되지 않는다.**
`tools\config_parse.py` 가 읽어서 검사하고, 통과한 값만 담은 사본을
`home\agent\config.cmd` 로 내보낸 뒤 그 사본만 `call` 한다.

거부되는 것:

| 무엇 | 왜 |
|---|---|
| 허용 목록에 없는 키 | `.bat` 이 읽지 않는 이름이다. 오타가 조용히 무시되는 대신 멈춘다 |
| 값 안의 `& \| < > ^ % !` 와 `"` | `&` 뒤는 명령으로 실행되고, `%VAR%`·`!VAR!` 는 값에서 소실된다(2026-08-19 실측) |
| 비ASCII 바이트 | `call` 되는 `.cmd` 에서 cmd.exe의 줄 오프셋 계산이 어긋난다 |
| 형식이 틀린 값 | 포트 범위, 정수, 백엔드 이름, `<제공자>/<alias>` 형식을 각각 검사한다 |
| `MODEL_ALIAS` 와 어긋나는 `PI_MODEL_ID` | 서버는 정상인데 Pi만 없는 모델을 요청하게 된다 |
| `set` 도 주석도 아닌 줄 | 설정 파일에 명령을 적는 길을 남기지 않는다 |

거부되면 어느 줄이 왜 거부됐는지 찍고 **nonzero로 멈춘다.** 거부된 설정으로
`home\agent\config.cmd` 를 남기지 않으므로, 다음 실행이 옛 사본을 쓰는 일도
없다.

`config.env` 자체는 현장에서 값을 채우는 파일이라 `STAGING_MANIFEST.json` 의
해시 범위에서 **제외**돼 있다. 값을 고쳐도 무결성 검사는 조용해야 정상이다.

## 종료 코드

실패는 nonzero로 나온다. 증거는 그대로 남고, 종료 코드는 그 판정을 따른다.

| 코드 | 어디서 | 뜻 |
|---|---|---|
| 0 | 전부 | 판정한 항목이 모두 통과했다 |
| 1 | `verify-offline.bat` | 판정 항목 중 하나 이상이 실패했다. 콘솔 요약이 어느 것인지 적는다 |
| 2 | `start-llama.bat`, `start-pi.bat` | 필수 파일이 없거나 필수 설정이 비었다 |
| 3 | `start-pi.bat` | 타임아웃 안에 모델이 `/v1/models` 에 나타나지 않았다 |
| 4 | 전부 | 쓸 수 있는 파이썬을 찾지 못했다 |
| 5 | `start-pi.bat` / `install-python-packages.bat` | `models.json` 렌더링 실패 / 오프라인 설치 실패 |
| 6 | 전부 / `install-python-packages.bat` | `config.env` 가 거부됐다 / 임포트 검증 실패 |
| 7 | `start-pi.bat` | 패키지 트리가 반입본과 다르다 |
| 8 | `start-llama.bat` | `LLAMA_BACKEND=vulkan` 은 이 모델에서 금지다 |
| 9 | `start-llama.bat` | `LLAMA_BACKEND=cpu` 에 `ALLOW_CPU_DIAGNOSTIC=1` 이 없다 |
| 10 | `start-pi.bat` | `home\agent\settings.json` 이 JSON이 아니어서 컨텍스트 안전값을 넣지 못했다 — 고치거나 지우고 다시 실행 |

`pi.exe` 자신의 종료 코드는 `start-pi.bat` 이 그대로 전달한다. 다만 그것을
성공의 증거로 쓰지는 않는다 — `stopReason: error` 직후에도 0을 반환한 실측이
있다.

## 파이썬

`start-pi.bat`, `verify-bundle.bat`, `verify-offline.bat` 은 파이썬을 쓴다. 찾는 순서는
`config.env` 의 `PYTHON_CMD` → 번들 내장 `bin\python\python.exe` →
`py -3.12` → `python` 이다. 번들이 파이썬 3.12 임베디드 배포를 들고 다니므로
대상 PC에 파이썬이 없어도, Microsoft Store 앱 실행 별칭 스텁이 잡혀도 동작한다.

`config.env` 를 읽는 일 자체가 파이썬을 쓰므로, 그 파싱만은 `PYTHON_CMD` 를
보지 않는다(그 값이 바로 `config.env` 안에 있기 때문이다) — 번들 내장
`bin\python\python.exe` → `py -3.12` → `python` 순으로 찾는다.

**`install-python-packages.bat` 만은 이 순서를 따르지 않는다.** 임베디드
배포에는 pip이 없어서 패키지를 설치할 수 없기 때문이다 — 그 스크립트는 대상
PC의 시스템 Python 3.12를 쓰고, `PYTHON_CMD` 로 지정된 것도 3.12인지와 pip이
있는지를 검사한 뒤에야 쓴다. 아래 "Python 오프라인 패키지 설치" 절을 보라.

## 콘솔 인코딩

`.bat` 파일(`start-llama.bat`, `start-pi.bat`, `verify-bundle.bat`,
`verify-offline.bat`, `install-python-packages.bat`)과
`config.env` / `config.env.example` 은 이제
순수 ASCII다 — 배치 자신이 내는 메시지(`[FAIL]`, `[info]`, `[warn]` 등)는
전부 영문이다. 그래서 콘솔 코드페이지를 `chcp 65001`(UTF-8)로 맞춰도 배치
자신의 출력은 깨지지 않는다.

`tools\*.py` 는 여전히 한글로 진단 메시지를 낸다(예: `packages_diff.py` 의
`[warn]` 경고). 배치는 파이썬을 부르기 전에 `PYTHONIOENCODING=utf-8` 을
세팅하므로, 이 한글 출력은 UTF-8 콘솔에 정상 표시된다. `evidence\` 아래
남는 리다이렉트 파일(`manifest-check.txt`, `python-packages-check.txt`,
`pi-tool-roundtrip.json` 등)도 같은 이유로 이제 UTF-8이다 — CP949가 아니다.

**왜 바뀌었나.** 예전에는 `.bat` 자신에 한글 메시지가 있었다 — 그래서 파일을
CP949로 인코딩해야 했고(UTF-8 `.bat` 은 cmd.exe가 줄 위치를 바이트 오프셋으로
다시 찾다가 파싱을 깨뜨린다), 콘솔도 `chcp 949` 로 맞춰야 했다. 문제는 실제
사용 환경(VS Code 터미널, Windows Terminal)이 출력을 UTF-8로 디코드한다는
것이었다 — CP949 바이트가 그대로 나오니 한글이 깨졌다. 해법은 `.bat` 에서
한글 자체를 없애는 것이다: 파일에 비ASCII 문자가 없으면 파일 인코딩 문제가
성립하지 않고, 콘솔을 `chcp 65001` 로 맞출 수 있고, 파이썬이 내는 한글은
UTF-8로 정상 출력된다.

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
  `vulkan` 은 `start-llama.bat` 이 거부한다(exit 8) — 문서가 아니라 코드가 막는다.** `bin\llama-vulkan`은 이 아키텍처의
  `ggml_ssm_conv`/`ggml_ssm_scan`을 구현하지 않았고, 조용히 CPU로 폴백하면서
  GPU↔CPU 경계에서 상태가 손상된다(상류 이슈 `ggml-org/llama.cpp#19957`,
  2026-02-27 open, 미해결). 결과는 손상된 출력이거나 `vk::DeviceLostError`다.
  `bin\llama-vulkan` 자체는 다른 모델에는 유효하므로 번들에서 빼지 않지만,
  이 모델에는 쓰지 않는다. `cpu`로 바꿔 원인을 좁힌다 — 느리지만 정확하다.
  30B 모델 실사용 속도가 나오지 않으므로 CPU는 진단용이고, 그래서
  `config.env` 에 `ALLOW_CPU_DIAGNOSTIC=1` 을 명시해야만 뜬다(없으면 exit 9).
  약 20GB(UD-Q5_K_M)를 시스템 RAM에 올리는 일이라 사고로 선택되면 안 된다 — RAM이나
  페이지파일이 모자라면 실패하는 대신 오래 스래싱한다.
- `MSVCP140.dll` 관련 오류가 나면 `bin\llama-cuda` 안의 app-local DLL이 지워졌는지 확인한다.
- 긴 프롬프트를 처리하다 화면이 잠깐 꺼지며 "디스플레이 드라이버 응답 중지 후 복구"
  (이벤트 뷰어 `nvlddmkm`, TDR)가 뜨고 llama-server가 죽으면, `config.env` 의
  `LLAMA_UBATCH` 를 128로 낮추고 다시 띄운다. 기본은 256이다(2026-09-22 지식그래프
  번들 정렬 — vocab 248,320의 logits 버퍼를 줄이려는 값). 리허설 §11-14.

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
| `npm:pi-subagents@0.68.0` | `subagent` 툴 — `scout`/`worker`/`reviewer`/`oracle`/`delegate`/`researcher` 내장 서브에이전트로 자식 Pi 세션에 위임한다. superpowers 확장이 이름까지 지목하며 전제로 깔아 둔 툴이다. `researcher` 페르소나는 웹 검색을 전제로 하므로 폐쇄망에서는 무용하다 — 나머지 5개는 로컬 모델 호출만 하므로 유효하다. 백그라운드 위임은 0.68.0에서 구조가 바뀌었다 — 아래 참고 |
| `npm:@juicesharp/rpiv-todo@2.10.1` | `/reload`·컴팩션에도 살아남는 라이브 todo 오버레이. superpowers 확장이 "설치된 todo 툴이 있으면 쓰라"고 안내하는 공백을 메운다 |
| `npm:@juicesharp/rpiv-ask-user-question@2.10.1` | 모델이 모호할 때 추측 대신 구조화된 객관식 질문을 사용자에게 던지는 툴 |

### 서브에이전트: 포어그라운드는 된다, 백그라운드는 리허설에서 확인한다

`pi-subagents` 의 두 위임 경로는 서로 다른 실행 파일을 쓴다.

- **포어그라운드 위임(기본)** — 자식 세션을 `pi.exe` 자신으로 띄운다.
  Node가 필요 없으므로 폐쇄망에서 **동작한다.**
- **백그라운드/`async` 위임** — 0.50.0에서는 러너를 `node.exe` 로 띄워 Node가
  없는 폐쇄망 PC에서 `ENOENT` 로 실패했다. **0.68.0 소스는 달라졌다:**
  `src/runs/shared/pi-spawn.ts` 의 `resolveBunPiExecutable()` 이 Bun으로
  컴파일된 단독 `pi.exe` 를 알아보면, 백그라운드 러너도 `pi.exe` 자신을
  `--mode rpc` 로 띄운다(`src/runs/background/async-execution.ts`
  `spawnRunner`). 즉 Node 없이 동작할 **구조**다. 다만 이것은 소스를 읽어
  확인한 것이고 실제 모델을 붙인 실행은 아직 아무도 보지 않았다 — 리허설에서
  백그라운드 위임 1회를 돌려 `ENOENT` 가 사라졌는지 확인하기 전까지는
  포어그라운드만 믿는다.

동시 요청은 폭주하지 않는다. `start-llama.bat` 이 `--parallel 1` 로
띄우므로 llama-server는 요청을 한 번에 하나씩 처리한다. 포어그라운드
위임을 여러 개 겹치면 응답이 뒤섞이는 것이 아니라 **지연이 그만큼
길어지고**, 재시도와 겹쳐 타임아웃처럼 보인다. 위임은 하나씩 하는 것이
이 구성에서 가장 빠르다.

## 반입 매체로 복사할 때

스테이징 PC의 `models\` 에는 반입하지 않는 모델이 함께 있다:
`Qwen3.8-27B-Q8_0.gguf`, `Qwen3.8-27B-Uncensored-GGUF\`,
`DeepSeek-R1-0528-Qwen3-8B-GGUF\`. 매니페스트는 이 셋을 경로로 빼 두었으므로
같이 복사돼도 `verify-bundle.bat` 은 조용하다. 약 63GB이니 복사할 때 빼는 편이
낫다. 개발 PC에서 Colab 학습에 쓰는 `colab-lora\` 도 폐쇄망에는 필요 없다(예:
`robocopy H:\model\pi_agent C:\pi_agent /E /XF Qwen3.8-27B-Q8_0.gguf
/XD Qwen3.8-27B-Uncensored-GGUF DeepSeek-R1-0528-Qwen3-8B-GGUF colab-lora`).

## 이전 번들에서 올릴 때 (Pi 0.84.2 → 0.85.1)

같은 `C:\pi_agent` 에 새 번들을 덮어쓰는 경우에만 해당한다. 새 폴더에 풀면
건너뛴다.

1. `start-llama.bat` 창과 Pi 창을 모두 닫는다.
2. `home\agent\npm` 폴더를 지운다. `xcopy /D` 는 새 판에서 사라진 파일을
   지우지 않는다 — pi-subagents는 0.50.0에서 0.68.0으로 올라가며 의존성
   (`acorn`, `undici` 추가)과 파일 구성이 바뀌었으므로 옛 파일이 섞이면 안 된다.
   세션 기록(`home\agent\sessions`)은 지우지 않는다.
3. `home\agent\settings.json` 의 `packages` 배열을 `pi-packages\settings.packages.json`
   과 같게 고친다(직접 고친 설정이 없으면 파일을 지우고 다시 실행해도 된다).
   고치지 않으면 `start-pi.bat` 이 `[warn]` 으로 차이를 알려 준다.
4. `verify-bundle.bat` → `verify-offline.bat` 순서로 다시 확인한다.

`bin\pi\docs\keybindings.md` 기준으로 이미지 붙여넣기는 여전히 윈도우에서
`Alt+V` 다(0.84.3에서 윈도우·WSL 기본 키가 정리됐지만 이 키는 그대로다).

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

## 긴 작업이 컨텍스트 때문에 멈출 가능성 줄이기 (settings.json 안전값)

Pi 0.85.1은 긴 작업을 이렇게 멈춘다(소스 추적, 2026-09-17):

- 대화가 `contextWindow - reserveTokens` 를 넘으면 압축하는데, 새로 붙은 도구 결과는
  **글자수/4** 로 추정한다. 한글 결과는 실제 토큰이 훨씬 많아 추정보다 늦게 압축된다.
- 그래서 서버 창을 넘기거나 답이 잘리면 "압축 후 재시도"로 복구하지만 **한 실행에
  한 번뿐**이다. 두 번째는 `Context overflow recovery failed...` 로 멈춘다.
- 서버는 긴 이력을 처음부터 계산(prefill)하는 동안 첫 토큰 전까지 아무것도 보내지
  않는다. 1080 Ti 3장에서 27B는 이 구간이 수 분 걸릴 수 있는데 Pi의 HTTP 유휴
  타임아웃 기본값은 **5분**, 요청 타임아웃은 SDK 기본 **10분**이다.

`start-pi.bat` 과 `verify-offline.bat` 은 실행할 때마다 `tools\pi_settings.py` 로
`home\agent\settings.json` 에 다음 **하한**을 맞춘다. 더 큰 값, 다른 키, 운영자가
`/settings` 로 바꾼 것은 그대로 두고, 바꾼 것이 있으면 `[info]` 로 적는다.

| 키 | 값 (LLAMA_CTX 63488 기준) | Pi 기본값 |
|---|---|---|
| `compaction.enabled` | `true` | `true` |
| `compaction.reserveTokens` | 23808 (창의 3/8, 상한은 창의 절반) — 압축은 39,680 초과에서 | 16384 |
| `compaction.keepRecentTokens` | 13,226 이하(창에서 reserve를 뺀 값의 1/3) — 압축 뒤 남는 한글 이력이 실제로는 약 3배여도 재시도가 창 안에 들어가게 | 20000 |
| `httpIdleTimeoutMs` | 1800000 (30분, `0` 으로 끈 것은 존중) | 300000 |
| `retry.provider.timeoutMs` | 3600000 (60분) | SDK 10분 |

이것은 보장이 아니라 위험을 줄이는 값이다. 남는 한계:

- 도구 결과 하나는 Pi가 50KB·2000줄로 자르지만, 한글이면 그 하나가 실제로 1만 토큰을
  넘을 수 있다. 큰 한글 문서는 `read` 도구의 offset/limit로 나눠 읽게 한다.
- 30분 넘게 첫 토큰이 안 나오는 prefill, 백그라운드 서브에이전트를 여러 개 겹쳐
  60분 넘게 대기열에 선 요청은 여전히 타임아웃된다 — 위임은 하나씩 한다.
- 그래도 멈추면 `/compact` 로 수동 압축한 뒤 "이어서 진행해"라고 요청한다.

**요청 한 번에 기본으로 드는 크기 (2026-09-17 실측, stub 서버가 받은 요청):** 시스템
프롬프트 11.1k자 + superpowers 부트스트랩 4.3k자 + 도구 스키마 10개 약 30k자 = **약 13k
토큰**. 그중 `pi-subagents` 의 `subagent`(18.4k자)·`bg_wait`(4.5k자)·`subagent_supervisor`
가 약 절반이다. 새 세션의 첫 응답 전에 이만큼을 prefill 하고, 63k 창에서도 그만큼이 늘
빠진다. `pi-subagents` 의 `toolDescriptionMode: compact` 는 221자만 줄여 효과가 없었다.
`start-pi.bat` 은 `home\agent\extensions\subagent\config.json` 에 `asyncByDefault: false`
(없을 때만)를 넣는다 — `--parallel 1` 서버에서 백그라운드 자식이 부모와 한 슬롯을
번갈아 쓰며 서로의 캐시를 밀어내지 않게 한다.

## 설정 최적화 (GTX 1080 Ti ×3, RAM 128GB)

`config.env.example` 에 2026-09-17 추가되고 2026-09-22 지식그래프 번들(`폐쇄망지식그래프`)에
맞춰 바뀐 키들이다. 근거는 llama.cpp b11010 소스와 pane 합의(`tasks/pi-agent-kg-align`)이고,
**VRAM·토큰/초 효과는 이 PC에서 아직 아무도 재지 않았다** — 리허설이 각 항목을 기록한다.

| 키 | `config.env.example` 값 (키가 비었을 때) | 무엇을 하나 |
|---|---|---|
| `LLAMA_FLASH_ATTN` | `auto` (`auto`) | flash attention. `auto` 는 장치에서 돌 수 있는지 먼저 시험하고 기동 로그에 `flash_attn enabled` 또는 `not supported, set to disabled` 를 남긴다. b11010은 텐서코어 없는 GPU의 head 256을 tile/vec 커널로 지원한다(`ggml-cuda/fattn.cu`). `off` 는 지식그래프 번들 가이드의 설정인데, 그 가이드가 인용한 "head size 64/128만 지원" 오류는 b11010에 없다 — 구버전 기준이다. 리허설 §11-2가 둘을 비교한다. `on` 은 시험을 건너뛰어 안 될 때 연산이 CPU로 가므로 받지 않는다 |
| `LLAMA_CTX` | 63488 (63488) | Pi 프로파일의 서버 컨텍스트이자 Pi의 `contextWindow`. qwen35는 전체 어텐션 16층만 KV를 가져 63488에서 KV 약 3.9 GiB(f16), K q8_0이면 약 2.9 GiB. **256의 배수만 받는다** |
| `LLAMA_KV_TYPE` | `q8_0` (`q8_0`) | **2026-09-22부터 K 캐시에만 적용된다.** V 캐시는 `f16` 고정 — 양자화 V는 flash attention이 전제인데 FA가 `off` 거나 `auto` 가 꺼질 수 있다. K q8_0은 FA 없이도 되고 KV를 약 25% 줄인다 |
| `CHAT_TEMPLATE_FILE` | `qwen38-c3cf9e34.jinja` (모델 내장 템플릿) | `chat-templates\` 의 템플릿을 `--chat-template-file` 로 쓴다. 원본 Qwen3.8 템플릿(Q6_K 내장본, sha256 `c3cf9e34…`)이다 — 도구 왕복·렌더 일치·LoRA 데이터가 모두 이것으로 검증됐다. UD-Q5_K_M 파일에는 Unsloth 변형 템플릿(시스템 메시지 병합, 문자열 도구 인자 예외)이 들어 있다. `start-pi.bat` 이 서버가 이 템플릿을 쓰는지 `/props` 로 확인한다 |
| `LLAMA_CACHE_RAM_MIB` | 32768 (llama.cpp 기본 8192) | 프롬프트 캐시를 시스템 RAM에 둔다. 슬롯이 하나라 서브에이전트 턴이 본 세션의 KV를 밀어내는데, 이 캐시가 있으면 다음 턴에 전체 이력을 다시 prefill하지 않는다 |
| `LLAMA_UBATCH` | `256` (`256`) | prefill 물리 배치. 논리 배치 `-b` 는 1024 고정이라 그보다 크게는 못 준다. TDR 증상이 있으면 128 |
| (고정) `-b 1024`, `--no-mmap`, `-sm layer` | 항상 | 지식그래프 번들 가이드의 값. `--no-mmap` 은 윈도우에서 초기 적재를 안정시키려는 것, `-sm tensor` 는 FA가 필요해 쓰지 않는다 |
| `LLAMA_SPEC_MTP` | `0` (꺼짐) | 모델 내장 MTP 층으로 추측 디코딩. 리허설 A/B 후 켠다 |
| `LEARNING_AUTO_REFLECT` | `1` (켜짐) | 학습 확장의 자동 반성. 위 "학습 확장" 절 |
| `LORA_FILE` / `LORA_SCALE` | 비움 / 1.0 | 아래 "LoRA" 절. **어댑터는 `MODEL_FILE=Qwen3.8-27B-Q6_K.gguf` 에서만 받는다** — UD-Q5_K_M은 적재 검증 전이라 `config.env` 검사가 거부한다 |
| `KG_CTX` / `KG_PARALLEL` / `EMBED_*` | 32768 / 4 / bge-m3·8081·GPU 2 | 아래 "지식그래프 스택" 절 |

양자화 선택 (2026-09-22 변경): **기본은 UD-Q5_K_M**(Unsloth dynamic, 18.4 GiB, sha256
`2de73110…` — HF 원본 LFS 해시와 스테이징 PC 재계산 일치), 백업은 Q6_K(20.9 GiB — LoRA
적재가 검증된 유일한 기반)와 Q4_K_M(15.7 GiB). 셋 다 반입하고 매니페스트가 검사한다.
UD-Q5_K_M + mmproj 0.87 GiB + 63488 KV 약 2.9 GiB(K q8_0)는 연산 버퍼 전 약 22 GiB로
3장 합계 안에는 들어가지만 장별로 들어가는지는 `GPU_TENSOR_SPLIT` 이 정한다.
지식그래프 번들 문서의 "Q6_K에서 62k 부근 OOM"은 출처(실측인지 계산인지)가 적혀 있지
않다 — 이 PC에서 확인된 사실로 다루지 않는다. 안 들어가거나 너무 느리면 순서대로:
`LLAMA_CTX=49152` → `LLAMA_UBATCH=128` → `MODEL_FILE=Qwen3.8-27B-Q4_K_M.gguf`.
모델을 바꿔도 alias·mmproj·고정 템플릿은 그대로다. Q8_0(27.1 GiB)은 33GB에 안
들어가 반입하지 않는다.

## 학습 확장 — 쓰면서 규칙과 스킬이 쌓이는 경로 (가중치 학습 없음)

`start-pi.bat` 은 `pi-extensions\learning.ts` 를 함께 싣는다. LoRA와 달리 모델을 다시
학습시키지 않고, **다음 세션의 프롬프트와 도구**를 바꾼다. 효과가 바로 나고 되돌리기 쉽다.

**규칙 기억**

- 모델이 작업 중 확인한 교훈을 `remember_rule` 도구로 한 줄씩 저장한다.
  - 이 폴더에만 해당: `<작업 폴더>\.pi\learned-rules.md`
  - 모든 작업에 해당: `C:\pi_agent\home\agent\memory\rules.md`
- 저장된 규칙은 매 턴 시스템 프롬프트 끝에 "Learned rules"로 붙는다(합계 4000자까지,
  넘치면 오래된 것부터 빠진다). 참고자료로 표시되며 사용자의 요청이나 지금 관찰한
  사실보다 우선하지 않는다.
- 저장될 때마다 화면에 `[learning] ... 규칙 #N 저장` 이 뜬다. **틀린 규칙은 바로 지운다**:
  `/rules` 로 번호를 보고 `/forget project 3` 처럼 지운다. 파일을 직접 고쳐도 된다.
- 비밀번호·키처럼 보이는 값, 같은 규칙, 파일당 50개를 넘는 것은 저장을 거부한다.

**반성**

- `/reflect [초점]` — 이 세션을 돌아보고 규칙을 최대 2개, 다시 쓸 절차가 있으면 스킬을
  최대 1개 만든다(코드로 제한).
- 자동 반성: 대화형 세션에서 도구를 8번 이상 쓴 작업이 정상 종료되면(30분에 한 번까지)
  같은 반성을 스스로 돈다. 자동 반성은 **이 폴더 규칙만** 저장한다(전역 규칙은
  `/reflect` 를 직접 실행할 때만). 1080 Ti 3장에서는 이 한 턴도 수 분 걸릴 수 있다 —
  끼어드는 게 싫으면 `config.env` 에 `LEARNING_AUTO_REFLECT=0`.
- 기존 `/retro` 는 AGENTS.md 추가안을 **제안만** 한다(쓰지 않음). 사람이 고르는 쪽은 `/retro`,
  자동으로 쌓는 쪽은 `/reflect`.

**스킬 도구화**

- 여러 단계 명령으로 성공한 절차를 모델이 `package_skill` 로 PowerShell 또는 파이썬
  스크립트로 만든다(Git Bash는 없을 수 있어 받지 않는다). 처음에는
  `home\agent\skills-pending\<이름>\` 에만 생기고 **모델에게 보이지 않는다.**
- `/skills-pending` 으로 목록을 보고, `/skill-approve <이름>` 을 실행하면 **스크립트 본문 전체와
  위험 명령 경고**(`Remove-Item -Recurse`, `rd /s`, `shutil.rmtree` 등)를 보여 주고 확인을 받는다.
  승인하면 `home\agent\skills\<이름>\` 으로 옮겨지고 `skill_<이름>` 도구가 바로 생긴다.
  다음부터 모델은 여러 단계를 다시 추론하지 않고 **도구 한 번**으로 끝낸다.
- 승인 뒤 스크립트나 파라미터를 고치면 해시가 달라져 도구로 등록되지 않는다(다시 승인).
- 이 승인은 보안 경계가 아니다 — 모델은 원래 `bash`·`write` 로 무엇이든 실행할 수 있다.
  사람이 보지 않은 스크립트가 자동으로 "한 번 호출" 도구가 되는 것을 막는 장치다.
- 등록 스킬 도구는 12개까지다. 도구 스키마는 매 요청 컨텍스트를 쓴다.

## LoRA — 오래 쓸수록 이 PC에 맞춰 가는 경로

먼저 기대치를 정확히 한다. **모델은 쓰는 동안 스스로 학습하지 않는다.** 할 수
있는 것은 사람이 고른 세션을 모아 가끔(예: 월 1회) 따로 학습시키고, 검사를
통과한 어댑터만 켜는 것이다. 그리고 효과가 가장 빠르고 위험이 없는 것은
가중치가 아니라 **지시문(AGENTS.md)** 을 키우는 쪽이다. 그래서 순서가 이렇다.

**1단계 — `/retro` (지금 바로, 위험 없음).** 작업이 잘 끝난 세션에서 Pi에
`/retro` 를 입력한다. 이 세션에서 확인된 규칙·명령·실수를 `AGENTS.md` 추가안으로
정리해 보여 준다. **파일은 쓰지 않는다** — 번호로 골라 "1, 3번 반영해" 라고
답하면 그때 반영한다. 프로젝트 규칙은 작업 폴더의 `AGENTS.md`, 모든 작업에 통하는
습관은 `C:\pi_agent\home\agent\AGENTS.md` 에 쌓인다. Pi는 시작할 때 둘 다
읽는다(`bin\pi\docs\usage.md` "Context Files").

**2단계 — 학습 데이터 모으기.** `/retro` 가 "LoRA 학습 후보: 예" 라고 한
세션만, `/session` 으로 세션 ID를 확인해 `C:\pi_agent\lora\approved.txt` 에
한 줄씩 적는다(`#` 뒤는 주석). 결과가 틀렸거나, 비밀번호·키·개인정보가 오간
세션은 넣지 않는다 — 틀린 대화로 학습하면 틀린 습관이 굳는다.

```
C:\pi_agent\export-sessions.bat
```

`home\agent\sessions` 에서 `lora\approved.txt` 의 세션만 골라 `lora\train.jsonl` 과
반출 검토 보고서 `lora\train.report.md` 를 쓴다. 파이썬을 직접 부르지 않는다 — 1단계의
`verify-bundle.bat` 과 같은 이유로 한글 사유 메시지가 깨진다. `--drop-thinking` 같은
인자는 뒤에 붙이면 그대로 넘어간다.

| 종료 코드 | 뜻 |
|---|---|
| 0 | 내보냄 |
| 2 | `approved.txt` 의 ID 중 세션 폴더에 없는 것이 있다(나머지는 내보냈다) — 오타 확인 |
| 3 | 승인 목록이 비었거나 내보낸 것이 0개 |

학습 샘플은 **모델이 실제로 받은 입력과 똑같이** 만든다. 세션 파일에는 시스템
프롬프트·도구 목록·사고 수준이 남지 않으므로, `start-pi.bat` 이 싣는
`pi-extensions\lora-snapshot.ts` 가 요청마다(바뀔 때만) 그것을 세션에 적어 둔다.
**이 확장 없이 기록된 세션은 "요청 스냅샷 없음"으로 제외된다.** 그 밖에:

- 한 세션에서 규칙·도구·사고 수준이 바뀌면 샘플이 구간별로 나뉜다. 각 샘플의
  `messages` 는 그 시점까지의 전체 문맥이고, `train_indices` 가 가리키는 응답만 학습
  대상이다(길이 제한에 잘린 응답은 문맥으로만 둔다).
- 확장 패키지가 요청에만 끼워 넣는 메시지(예: superpowers 안내문)도 스냅샷에 적혀
  같은 위치에 들어간다.
- 사고(thinking) 내용은 기본으로 들어간다 — 추론 때도 모델이 이전 사고를 다시 받는다
  (`--drop-thinking` 으로 뺄 수 있지만 학습·추론 입력이 달라진다).
- 도구 인자는 JSON 객체로 쓴다(Qwen3.8 chat_template 요구).
- compaction(자동 요약)이 있었던 세션은 Pi와 같은 규칙(요약 + 보존 구간)으로 문맥을
  재구성한다. 이미지가 들어간 세션과 끝까지 완료된 응답이 없는 세션은 제외된다.
  제외 사유는 보고서에 남는다.

`password=`, `token:`, `sk-...`, `ghp_...`, `AIza...`, `Bearer ...`, `://user:pass@`,
개인키 블록 같은 문자열은 `[REDACTED]` 로 가려지지만, **가림은 보조 장치다** — 승인
전에 사람이 보는 것이 1차 방어다. 사용자 계정 경로(`C:\Users\이름`)·사설 IP·내부
호스트명은 모델이 배워야 할 실제 경로일 수 있어 가리지 않고, 보고서의 "가리지 않은
민감 후보"에 나열한다. 반대 방향 한계도 있다: 키 이름만 보고 가리므로
`token = tokenizer(text)` 같은 평범한 코드도 `token = [REDACTED]` 로 바뀐다. 코드가
많은 세션은 `lora\train.jsonl` 에서 그런 줄이 학습을 망치지 않는지 확인한다.

**`train.jsonl` 을 PC 밖(예: Colab)으로 옮기는 것은 반출이다.** 보고서를 사람이 읽고
기관의 반출 승인을 받은 뒤에만 옮기고, 옮긴 파일의 sha256이 보고서 값과 같은지 확인한다.

**3단계 — 학습(폐쇄망 밖).** 이 번들에는 학습 도구가 없다. 1080 Ti 3장에서 27B 학습은 매우
느려, 반출이 승인되면 인터넷 되는 개발 PC에서 Google Colab GPU로 학습한다. 절차·가드·합격 기준은
개발 트리의 `colab-lora\README.md` 에 있다(이 폴더는 반입 대상이 아니다). 요점:

- `train.jsonl` 의 sha256이 `train.report.md` 값과 같아야 시작한다.
- **2026-09-22부터 기본 모델은 UD-Q5_K_M이지만 어댑터는 Q6_K에서만 쓴다.** 어댑터를 켜려면 `MODEL_FILE=Qwen3.8-27B-Q6_K.gguf` 로 바꾼다 — UD-Q5_K_M은 내장 템플릿이 다르고 적재 검증 전이라 `config.env` 검사가 `LORA_FILE` 을 거부한다.
- 학습 결과 어댑터는 Colab에서 번들과 같은 Q6_K·llama.cpp b11010에 올려 텐서 적재를 확인하고,
  개발 PC에서 GGUF로 바꿔 sha256을 적는다. 반입할 것은 `.gguf` 와 그 `.json`(sha256) 둘뿐이다.
- 학습 대상 모듈에서 `linear_attn.out_proj` 는 빠져 있다 — 넣으면 GGUF 변환이 실패한다(2026-09-17 CPU 실측).

폐쇄망 안에서 직접 학습하려면 원본 가중치(약 56GB)와 학습용 파이썬 스택을 따로 반입해야 한다. 반입 전
확인 절차는 `docs/superpowers/plans/rehearsal-2026-08-18.md` §11-13(개발 트리 문서).

**4단계 — 어댑터 켜기와 되돌리기.** 학습 결과를 GGUF 어댑터로 변환한 파일을
`C:\pi_agent\lora\` 에 두고 `config.env` 에 적는다.

```
set "LORA_FILE=pi-sessions-2026-10.gguf"
set "LORA_SCALE=1.0"
```

반입한 파일은 켜기 전에 `certutil -hashfile C:\pi_agent\lora\<파일>.gguf SHA256` 이 함께 온 `.json` 의 `sha256` 과
같은지 확인한다. `start-llama.bat` 을 다시 띄운 뒤 **`verify-offline.bat` 이 통과해야 켜 둔다.**
툴 왕복이 깨지면 그 어댑터는 버린다. 되돌리기는 `LORA_FILE` 을 비우고
`start-llama.bat` 을 다시 띄우는 것이 전부다. 파일 이름에는 영문·숫자·`._-`
만 쓴다 — 콜론·괄호·공백이 들어가면 `config.env` 검사가 거부한다(llama-server가
콜론을 배율 구분자로 읽고, 괄호는 배치 블록을 깨뜨린다). `lora\` 폴더는
무결성 검사 범위 밖이라 여기에 파일을 넣어도 `verify-bundle.bat` 이 빨간불을
띄우지 않는다.

## 지식그래프 스택 (LightRAG · graphify, 2026-09-22)

`폐쇄망지식그래프` 번들을 이 번들에 합쳤다(`tasks/pi-agent-kg-align` 합의). 문서에서
엔티티·관계를 뽑아 지식그래프를 만드는 LightRAG(WebUI 포함), 임베디드 그래프 DB Kuzu,
NetworkX·rdflib, 코드/문서를 그래프로 바꾸는 graphify가 들어 있다. **모두 외부 네트워크
없이 동작한다.** 무결성은 따로 두지 않고 `STAGING_MANIFEST.json` 하나로 검사한다.

| 경로 | 내용 |
|---|---|
| `packages_win\kg\wheelhouse\` | 휠 276개(py3.12 win_amd64). numpy·boto3는 패키지 간 핀이 충돌해 두 버전씩 들어 있어서, 통계 스택(`packages_win\py312`, `.venv`)과 **섞지 않는다** |
| `packages_win\kg\tiktoken\` | tiktoken 원본(cl100k_base, o200k_base) |
| `models\bge-m3-FP16.gguf` | 임베딩 모델(1024차원, 다국어, 최대 8192토큰) |
| `kg\lightrag.env` | LightRAG 설정 템플릿 |
| `pi-skills\graphify\` | graphify 스킬의 폐쇄망판(아래) |
| `home\kg\` | `install-kg.bat` 이 대상 PC에서 만드는 venv·토크나이저 캐시·작업 폴더(매니페스트 밖) |

### 순서

```
C:\pi_agent\install-kg.bat            :: 최초 1회. home\kg\venv 생성, --no-index 설치, pip check, 토크나이저 캐시
C:\pi_agent\start-llama.bat kg        :: 창 1 - LLM(kg 프로파일, 8080)
C:\pi_agent\start-embedding.bat       :: 창 2 - 임베딩(8081, GPU 2)
C:\pi_agent\start-lightrag.bat        :: 창 3 - LightRAG, WebUI http://127.0.0.1:9621
```

문서는 `home\kg\work\inputs` 에 넣고 WebUI에서 인덱싱한다. 결과는 `home\kg\work\rag_storage\`
(`graph_chunk_entity_relation.graphml` 은 Gephi·yEd로 연다). 이 폴더를 주기적으로 백업한다.

**kg 프로파일과 Pi는 동시에 쓰지 않는다.** 둘 다 `LLAMA_PORT` 를 쓴다. `start-llama.bat kg` 는
32768을 4슬롯이 나눠(슬롯당 8192) 청크 추출을 병렬로 돌리는데, Pi의 첫 요청만 약 13k 토큰이라
그 슬롯에 들어가지 않는다. 그래서 `start-pi.bat` 이 서버의 `/props` 를 보고 슬롯이 1개가 아니거나
창이 `LLAMA_CTX` 와 다르면 Pi를 띄우지 않는다(exit 11). Pi로 돌아가려면 kg 창을 닫고 인자 없이
`start-llama.bat` 을 다시 띄운다. kg 프로파일은 비전 프로젝터를 올리지 않는다.

`kg\lightrag.env` 는 요청 하나의 입력+출력이 슬롯(8192) 안에 들도록 상한을 둔다(추출 입력 4000,
요약 입력 4000, 질의 전체 4000, 출력 2500). 라이브러리 기본값(`MAX_TOTAL_TOKENS` 30000 등)은 슬롯을
넘는다. `start-lightrag.bat` 은 기동 직전에 **실제로 적용될 값**(보존된 `home\kg\work\.env` +
같은 이름의 환경변수, 없는 키는 라이브러리 기본값)을 떠 있는 LLM 서버의 슬롯 크기(`/props`)와
대조해 넘치면 띄우지 않는다(`tools\kg_budget.py`, exit 3). `.env` 를 고쳤다면 이 검사가 알려 준다.
LightRAG가 부를 서버 주소와 모델 이름은 `config.env` 의 `LLAMA_PORT`·`EMBED_PORT`·`MODEL_ALIAS` 로
bat이 넣는다 — `.env` 의 같은 키보다 우선한다. 추출은 사고를 끈다(`enable_thinking: false`).
품질 영향은 아직 재지 않았다.

임베딩 서버의 벡터 길이가 **1024** 인지 확인한다(`EMBEDDING_DIM` 과 같아야 인덱싱이 깨지지 않는다):

```
curl http://127.0.0.1:8081/v1/embeddings -H "Content-Type: application/json" -d "{\"model\":\"bge-m3\",\"input\":\"테스트\"}"
```

### graphify

Pi 세션에서 `/skill:graphify <폴더>` 로 부른다(`start-pi.bat` 이 `--skill` 로 로드). 코드는
tree-sitter AST로 로컬 파싱하므로 LLM을 쓰지 않는다. 문서·PDF·이미지의 의미 추출은 지금 도는
Pi(로컬 llama-server)가 한다. 폐쇄망판에서는 GitHub clone, `pip`/`uv` 설치, Gemini API,
Whisper 전사, `graphify add <url>`, Neo4j/FalkorDB push를 지웠다(`tools\sanitize_graphify_skill.py`).
graphify는 PATH가 아니라 번들 venv(`home\kg\venv\Scripts\python.exe -m graphify`)로만 부른다 — 이 PC에
다른 graphify가 있어도 섞이지 않는다. graphify가 만든 HTML(`graph.html` 등)은 그래프 라이브러리를
CDN에서 받게 돼 있어서, 스킬이 `tools\graphify_offline_html.py` 로 번들의 고정 사본(vis-network 9.1.6,
d3 7.9.0, mermaid 11.17.2 — `packages_win\kg\web\`)을 가리키게 바꾼다.
**`GEMINI_API_KEY`·`GOOGLE_API_KEY` 는 설정하지 않는다** — 설정하면 graphify가 외부 API를 부른다.

### 확인할 것

- `netstat -ano | findstr "8080 8081 9621"` 로 전부 `127.0.0.1` 에만 바인딩됐는지
- 방화벽 아웃바운드 차단 상태에서 설치·인덱싱이 끝나는지(외부 호출이 없는지)
- `nvidia-smi -l 5` 로 GPU 2의 LLM 몫 + 임베딩 몫이 11GB를 넘지 않는지

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

**실패 시 볼 곳**: 설치 실패와 임포트 실패는 이제 각각 종료 코드 5, 6으로 나온다. 무엇이 왜 실패했는지는 `evidence\` 의 두 파일에 있다.
- `evidence\python-packages-install.txt` — pip 설치 로그 전체. 마지막 줄이
  `Successfully installed`로 끝나는지 확인한다.
- `evidence\python-packages-check.txt` — `packages_win\requirements.txt` 가
  선언한 **직접 의존 전부**를 하나씩 임포트한 결과다. 패키지마다 `OK` 또는
  `FAIL` 한 줄씩 남고 마지막 줄이 `IMPORT_OK` 여야 한다. `FAIL` 줄이 하나라도
  있으면 그 줄이 어느 패키지인지와 예외 메시지를 그대로 알려 준다 — 위
  install 로그에서 그 패키지가 실제로 설치됐는지 먼저 본다. `lightgbm` 만
  `FAIL` 이면 위의 VC 런타임 배치가 실패한 것이다(`[warn]` 메시지와
  `evidence\lightgbm-location.txt` 를 본다).
