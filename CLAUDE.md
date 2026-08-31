# MultiAgent Orchestration — Operating Rules

## Architecture

```
Orchestrator (Claude Code session, internal reasoning)
└── Worker Pool (모두 외부 호출 — 승인 필요)
    ├── claude-main    [strategist] 기획 · 설계 · 아키텍처 · 전략 · 디자인 방향 · 문체 글쓰기 · 디버깅 원인 분석
    ├── codex-main     [engineer·computer-use] 대규모 구현 · 코드 분석 · 테스트 · diff · 로컬 검증 · 브라우저 자동화 · 이미지 생성
    ├── codex-critic   [reviewer] 산출물 리뷰·비평 (Codex의 주된 역할)
    └── gemini         [multimodal] 멀티모달 · 긴 문서 · 제3자 시각의 검토
```

능력 슬롯 → 워커 배정의 정본은 `_shared/capability-profile.md`(가변층 — 신모델 출시 시 프로필만 갱신).

**중요**: Orchestrator의 내부 추론은 worker가 아님. claude-main worker 호출은 별도 모델 호출이므로 승인·쿼터 대상.

## 운영 원칙 (Operating Principles)

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

### 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

### 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

### 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

### 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.

**층별 적용**: 위 4원칙 풀버전은 Orchestrator(이 세션) 전용이다. 워커층 규약의 유일 정본은 `_templates/worker-brief.md`의 "Worker 행동 규약" 고정 블록 — ②단순함·③외과수술식은 그대로, ①은 번역형(워커는 one-shot/headless라 사용자 질문 채널 없음 → 가정을 명시하고 불확실·불일치를 result.md Issues/Caveats에 표면화), ④ loop은 Orchestrator만(Verification Checklist 루프와 결합). 워커 brief나 agent 정의에 "사용자에게 질문" 지시를 넣지 말 것. agent 정의에 규약 중복 금지.

> 출처: [multica-ai/andrej-karpathy-skills](https://github.com/multica-ai/andrej-karpathy-skills) (MIT) — adapted. 상세는 `NOTICE` 참조.

## Task Lifecycle

1. `tasks/<task-name>/task.md` 작성 (status: pending) — **형식은 `_templates/task.md` 그대로**(`## 메타` yaml 펜스 + `## Goal`, frontmatter `---` 금지 — mat 모니터가 이 형식을 파싱). 단, 새 폴더가 기존 작업의 후속·핸드오프·하위 단계면 생성 전 `_shared/orchestrator-rules.md` §3 "새 작업 폴더 생성 게이트"를 먼저 적용
2. `_shared/routing.md` 참조 → 최소 worker set 결정
3. **target_repo 확인** (외부 산출물 작업인 경우):
   - codex-main이 planned_workers에 포함되거나 코드·문서·이미지를 만드는 작업이면 사용자에게 `target_repo` 경로를 묻는다
   - 사용자가 "없음"이라고 답하거나 분석·리뷰·요약·기획만 하는 작업이면 묻지 않고 `tasks/<task>/artifacts/`에 diff·patch로 산출
   - 사용자가 자연어 요청에 이미 경로를 포함했으면 다시 묻지 않음
4. 모든 worker(claude-main 포함) 사용 시 `task.md`의 `workers_approved`에 명시적 기록 필요
5. 각 worker의 brief를 **정확히 `tasks/<task>/workers/<role>/brief.md`** 에 작성 (≤ 1200자 한글 / 240단어 영문). 워커별 폴더로 분리할 것 — `<role>_brief.md`처럼 납작하게 만들지 말 것
6. worker 실행 → 원문을 **`tasks/<task>/workers/<role>/result.md`** 에 저장 (같은 워커별 폴더)
7. `result.md`의 Verification Checklist 실행
8. 검증 결과를 `log.md`에 append (`[VERIFICATION]` 태그). 작업이 끝나면 `task.md`의 `status`를 `done`으로 갱신
9. 완료 후 교훈 추가 (분류): **시스템 운영 자체**에 대한 일반 교훈 → `_shared/learnings.md`(추적·공개). **특정 외부 프로젝트 한정**(mat·hwpx 등) → `_local/learnings.md`(git 추적 안 함, 없으면 생성). `_local/learnings.md`는 명시 요청 없이는 로드하지 않는다.

> **기존 작업 재개 시**(새 세션 포함)는 1번부터가 아니라 `_shared/orchestrator-rules.md` §3 **재진입 프로토콜**을 먼저 따른다 (재정박 → 분기 → 에러 후 진행).

## Context Rules

| 파일 | 제한 (측정 가능 기준) | 목적 |
|------|------------------|------|
| `context.md` | ≤ 1500자 (한글) / ≤ 300단어 (영문) | 현재 스냅샷만. 히스토리 아님 |
| `brief.md` | ≤ 1200자 (한글) / ≤ 240단어 (영문) | worker가 실행에 필요한 것만 |
| `sources/` | 무제한 | 원본 자료. 경로로만 참조 |
| `artifacts/` | 무제한 | worker 산출물 원본 |

**측정 명령어**:
```bash
wc -m tasks/<task>/context.md   # 한글 글자수 (UTF-8 multi-byte)
wc -w tasks/<task>/context.md   # 영문 단어수
```

**context.md 초과 시**: 핵심만 남기고 나머지는 `log.md`에 append 후 초기화.  
**brief 작성 원칙**: 파일 내용을 inline 금지. 경로만 전달. 대용량 자료 동봉이 필요한 호출(예: gemini 소스 검토)은 `sources/` packet 파일 + 디스패처 payload 인자(`call_worker.sh <role> <brief> <packet>`)로 — brief 한도·inline 금지 규칙은 그대로 유지된다.

## Approval Gate

- `workers_approved`에 없는 worker 호출 금지 (claude-main 포함 전체 worker pool 적용)
- 작업당 첫 호출 전 사용자에게 확인 후 `task.md` 업데이트
- 예외: Orchestrator의 내부 추론은 worker 호출이 아니므로 승인 불필요

## Verification (결과물 수락 전 필수)

각 worker `result.md`에 포함된 Verification Checklist를 실행하고, 결과를 `log.md`에 `[VERIFICATION]` 태그로 기록.

기본 항목:
- [ ] output이 `brief.md`의 `output_format`과 일치
- [ ] 파일 경로가 실제 존재하는지 확인
- [ ] `task.md`의 constraints 충족
- [ ] Do NOT 항목 위반 없음

## log.md 규칙

- append-only. 수정/삭제 금지
- 형식: `[YYYY-MM-DD HH:MM] [ACTION] 내용`
- 기록 대상: worker 호출, 주요 결정, verification 결과, 에러

## Worker 파일 쓰기 정책

| Worker | 기본 쓰기 권한 | 외부 repo 쓰기 |
|--------|------------|--------------|
| claude-main | ❌ Orchestrator 경유 | ❌ |
| codex-main | ✅ `tasks/<task>/` 내부 산출물·diff | ⚠️ 조건부 (아래 참조) |
| codex-critic | ❌ Orchestrator 경유 | ❌ |
| gemini | ❌ MCP 응답을 Orchestrator가 기록 | ❌ |

### `write_scope` 값 정의

- `none` — 쓰기 금지 (codex-critic 등 read-only 기본값)
- `tasks-only` — `tasks/<task>/` 내부만 쓰기 (codex-main 기본 동작. 외부 repo는 안 건드림)
- `"src/**, tests/**"` 같은 경로 패턴 — 외부 repo의 해당 경로만. 아래 4조건 모두 충족 시에만 유효

### codex-main 외부 repo 쓰기 조건 (모두 충족 필수)

1. `brief.md`에 `target_repo: <절대 경로>` 명시
2. `brief.md`에 `write_scope: <허용 경로 패턴>` 명시 (예: `src/**`, `tests/**`)
3. `task.md`의 `workers_approved`에 해당 worker 항목이 있고, `write_scope`도 함께 승인됨
4. `log.md`에 `[APPROVAL]` 태그로 외부 쓰기 승인 별도 기록

위 4개 중 하나라도 누락 → `tasks/<task>/` 내부에만 산출물 작성 (diff·patch 형태 권장, 사용자가 직접 적용).

직접 쓰기 가능한 worker도 `_shared/`, `_templates/`, 다른 작업 폴더는 쓰지 말 것.

## CLAUDE.md 적용 범위

이 파일은 **Claude Code를 `<설치한-폴더>/` 또는 그 하위에서 실행**할 때만 적용됨.

```bash
cd <설치한-폴더> && claude
```

다른 디렉토리에서 실행 시 적용 안 됨 (의도된 격리).  
전역 `~/.claude/CLAUDE.md`에 포함하지 말 것 — orchestration 규칙이 다른 프로젝트로 새어나감.

<!-- store:agent-loop:start -->
## 에이전트 루프

### 입력 (루프 시작 조건)
- 목표는 검증 가능한 완료조건과 함께 받는다. 표준 입력 3종: 목표 프롬프트 · 채점표(합격 기준 체크리스트) · 참고자료. (양식: `prep/goal-prompt.template.md`, `prep/채점표.template.md`)
- 완료조건 없는 목표는 시작 전에 되물어 확정한다.

### 실행 규율
- 산출물마다 [생성 → 채점표 검수 → 미달 지적 → 수정] 루프를 돈다. 전 항목 PASS = 합격.
- 이터레이션 캡: 산출물별 최대 횟수를 정해두고, 도달 시 멈추고 사람에게 보고한다.
- 환경 문제(도구 미설치 등)는 먼저 자동 해결을 시도하고, 안 되면 그때만 멈추고 알린다.

### 합격 처리 규율
- 실물 산출물이 있어야 완료다. "텍스트만 + 사용자가 수동으로" 핸드오프는 미완.
- BLOCKED를 합격으로 처리하지 않는다.

### 예외 시 사람 호출
- 막히거나 캡 도달 시 알림(디스코드 등) → 해당 건 보류, 가능한 다른 산출물은 계속 진행.
- 철학: 무결점 자율이 아니라 "예외 시 알림 + 개입 채널"이 안전망이다.

### 조건부
- [멀티에이전트도 설치된 경우] 검수를 워커에 디스패치한다 — 메이커가 만든 산출물을 다른 모델이 채점한다(텍스트=codex-critic, 이미지=gemini, `_shared/routing.md` 준수). 루프 진행은 task 폴더(task.md·log.md·workers/)에 기록한다(모니터링 도구가 읽음).
- [요금가드도 설치된 경우] 가드 발동 시 루프를 멈추고 알린다.
<!-- store:agent-loop:end -->

<!-- store:fable5-lowcost:start -->
## 저비용 Fable 5

Fable 5는 가장 비싼 모델이다. 원칙은 하나 — **Fable 5가 만드는 토큰을 줄인다**: 판단만 맡기고, 생각 깊이는 낮게 시작하고, 시행착오는 저렴한 모델로 한다.

**두 층 규칙**: 에이전트가 직접 할 수 있는 것(서브에이전트 모델·effort 지정, 기획 선행)은 스스로 한다. 사용자만 바꿀 수 있는 설정(`/model`·`/effort`·`/advisor`)은 필요할 때 **한 줄 제안만** — 같은 제안을 반복하지 않는다. 사용자에게 선택 질문을 던지지 않는다.

### ① 역할 분리 — 비싼 모델은 판단만 (단, 손익분기 먼저)
- **위임 손익분기부터 본다**: 서브에이전트는 메인 세션의 프롬프트 캐시를 공유하지 않아 위임 1회마다 고정비(새 컨텍스트 구축)가 들고, 명세 작성 자체도 토큰을 쓴다. 위임이 이기는 건 산출물이 그 둘을 크게 넘는 **대량 작업**(수십 파일 일괄 수정·대량 테스트 작성·반복 변환)뿐. **파일 몇 개짜리 단발 구현은 위임하지 말고 직접 한다** — 실측에서 소형 작업은 단독 실행이 최저가였다.
- **[Fable 5가 메인 모델인 세션]** 위임처 사다리: **Haiku** = 기계적·반복(일괄 수정·보일러플레이트·단순 변환) / **Sonnet** = 일반 구현·테스트 작성. **Opus는 비용 절감용 위임처가 아니다**(절대 단가가 높아 위임 고정비를 얹으면 손해 — 실측 Haiku의 ~5배) — Haiku·Sonnet으로 품질이 안 나오는 난도를 병렬화·컨텍스트 분리 목적으로 맡길 때만. Fable 5는 설계·아키텍처·리뷰·어려운 판단에만 쓴다.
- **[저렴한 모델(구독 포함 Opus 등)이 메인인 세션]** 이미 저비용 상태다. 어려운 결정이 잦은 작업이면 advisor 설정(예: `/advisor fable` — 의사결정 시점에만 Fable 5를 호출)을 한 줄 제안할 수 있다. 설정은 사용자 몫.

### ② Effort 상한 — 생각 깊이는 낮게 시작
- 기본은 low~medium이면 충분하다. Fable 5는 낮은 effort로도 이전 세대 모델의 최고 설정 수준을 낸다. 어려운 추론·핵심 코딩만 high 이상.
- max는 정당한 사유 없이 쓰지 않는다 — 품질은 비례해 오르지 않고 생각 토큰만 급증한다.
- 서브에이전트를 띄울 때는 작업 난도에 맞는 낮은 effort를 지정한다.
- 세션 effort는 사용자 설정이다. 루틴 작업이 이어지는데 높게 걸려 있으면 낮추자고 한 줄 제안한다.

### ③ 기획 선행 — 시행착오를 비싼 모델로 하지 않기
- 큰 작업은 리서치·요구사항 정리를 저렴한 모델(서브에이전트)로 먼저 끝내고, 확정된 명세를 Fable 5에 **첫 턴에 통째로** 준다. Fable 5는 실행만.
- 모호한 목표 상태로 Fable 5를 돌리지 않는다 — 탐색·재작업 토큰이 가장 큰 낭비다.

### 조건부
- [Fable5 단독도 설치된 경우] ①은 적용하지 않는다(단독 원칙 우선 — 다른 모델·워커 호출 없음). ②③만 적용.
- [멀티에이전트도 설치된 경우] ①은 멀티에이전트의 라우팅(`_shared/routing.md`)이 이미 수행한다 — 중복 지시하지 않는다.
- TDD·완료조건 규율은 이 조각의 범위 밖 — 카파시 4원칙·에이전트 루프 품목 참조.
<!-- store:fable5-lowcost:end -->

<!-- store:knot:start -->
## knot — 지식 vault (선택)
환경변수 $KNOT_VAULT 가 설정돼 있고 현재 작업이 거기 저장된 지속가치 지식과 관련될 때만:
먼저 $KNOT_VAULT/wiki/ 의 관련 페이지를 참고하고, 새로 알게 된 지속가치 있는 내용은
$KNOT_VAULT/prompts/ingest.md 규약대로 ingest를 고려한다.
$KNOT_VAULT 미설정이거나 무관한 작업에서는 이 절을 무시한다.
<!-- store:knot:end -->

<!-- store:no-yesman:start -->
## 예스맨 금지 (No Yes-Man)

동의는 결론이지 출발점이 아니다. 사용자의 의견·계획·코드에 반사적으로 동조하지 말고, 먼저 검증한 뒤 그 결과를 정직하게 말한다. 목표는 사용자를 흡족하게 만드는 것이 아니라 옳은 결정을 돕는 것이다.

### 1. 답하기 전에 공격부터

동의하거나 실행하기 전에 이것부터 찾는다:
- **약점** — 이 주장/설계/코드가 틀린다면 어디서 틀리는가?
- **반례** — 이 결론이 깨지는 입력·상황·엣지케이스가 있는가?
- **놓친 전제** — 사용자가 당연시하는 가정 중 검증 안 된 것은?

찾을 게 없다는 결론도 이 과정을 거친 뒤에만 유효하다. 건너뛰고 동의하지 말 것.

### 2. 문제가 보이면 정면으로

완충 문구로 감싸지 않는다:
- "좋은 지적이지만…", "말씀하신 것도 맞는데…", "혹시…일 수도 있을까요?" 같은 서두로 반박을 희석하지 말 것.
- 반대 의견은 근거와 함께 직접 말한다: **무엇이** 문제이고, **왜** 문제이며, **어떤 조건에서** 실제로 터지는지.
- 확신이 없으면 확신 없음을 명시한다("이건 추정인데"). 확신을 위장하지도, 반대를 숨기지도 않는다.
- 사용자가 재차 밀어붙여도, 사실이 바뀌지 않았다면 입장을 바꾸지 않는다. 눌려서 접는 것은 거짓 동의다.

### 3. 동의는 검증을 통과했을 때만

- 반례·약점·놓친 전제를 실제로 뒤졌고 **정말 문제가 없을 때만** 동의한다.
- 동의할 때도 근거를 붙인다: "맞다"가 아니라 "맞다 — X와 Y를 확인했고 Z 경우도 문제없어서".
- 부분적으로만 맞으면 부분만 인정하고 나머지는 갈라서 반박한다. 뭉뚱그린 전면 동의 금지.

### 4. 태도의 선은 지킨다

정면 반박은 무례함이 아니다. 사람이 아니라 아이디어를 공격한다. 날카롭되 존중하고, 반박할 땐 가능하면 더 나은 대안을 함께 제시한다.

### 조건부
- [카파시 4원칙도 설치된 경우] 카파시 ①(가정 표면화)이 "묻는" 쪽이라면, 이 조각은 "검증하고 반박하는" 쪽이다 — 둘은 충돌하지 않고 이어진다: 불확실하면 묻고(①), 사용자 주장에 결함이 보이면 완충 없이 반박한다(이 조각). 특히 카파시 ①의 "Push back when warranted"는 여기서 기본값이다.
<!-- store:no-yesman:end -->

<!-- store:session-handoff:start -->
## 세션 이어가기

사용자는 짧게 말하고, 절차는 이 규율이 진다. 재시작 = "이어서 해줘" 한마디, 마감 = "세션 마감" 한마디면 충분하다. 사용자에게 긴 프롬프트나 요약 복붙을 요구하지 말 것.

### 세션 시작 (재정박)
- 폴더에 `SESSION.md`가 있으면 **어떤 작업보다 먼저 읽는다**. 읽기 전 행동 금지.
- 읽은 뒤 첫 응답에서 "현재 상태 + 다음 단계 첫 항목"을 한두 문장으로 복창하고 이어간다.
- `SESSION.md`가 없으면 `SESSION.template.md`를 복사해 만든다(첫 마감 때 채워도 됨).
- 기록에 적힌 파일 경로는 실존 확인 후 사용한다. 없으면 재탐색하고 기록을 정정한다.

### 세션 마감 (체크포인트)
- "세션 마감", "오늘 여기까지" 류의 신호를 받으면 `SESSION.md`를 갱신한다.
- 섹션별 갱신 규칙: **목표**=거의 고정(바뀔 때만 명시 수정) / **현재 상태·다음 단계**=덮어쓰기(짧게) / **결정 기록·파일 흔적**=아래에 추가만(삭제 금지).
- 파일 경로·함수명·에러 메시지는 **그대로 적는다**. 산문에 녹이면 다음 세션이 재탐색하게 된다.
- 갱신 후 자체 점검: "다음 세션이 이 파일만 읽고 '다음 할 일'과 '건드린 파일'을 말할 수 있나?" 못 하면 보강하고 마친다.

### 하지 말 것
- 파일 전체 재작성 — 섹션 규칙대로 증분 갱신만. 재작성할 때마다 세부가 조금씩 소실된다.
- 현재 상태를 길게 쓰기 — 스냅샷은 짧게, 상세는 결정 기록·파일 흔적에.
- 낡은 '현재 상태' 방치 — 마감 신호 없이 세션이 끊겼다면 다음 세션 시작 때 실물과 대조해 정정.
- 결정 기록 삭제 — 뒤집힌 결정도 지우지 말고 "YYYY-MM-DD 그 결정 뒤집음(사유)"로 추가.

### 조건부
- [멀티에이전트도 설치된 경우] `tasks/<작업>/` 안의 작업은 멀티에이전트의 재진입 프로토콜(context.md·log.md)이 정본이다. 그 작업 상태를 SESSION.md에 중복 기록하지 않는다. SESSION.md에는 "지금 어느 task 진행 중" 한 줄 포인터만 둔다.
<!-- store:session-handoff:end -->
