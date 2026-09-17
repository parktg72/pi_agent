# colab-lora — 폐쇄망 세션으로 Colab에서 LoRA 학습하기

**이 폴더는 인터넷이 되는 개발 PC(WSL) 전용이다.** 폐쇄망 번들에는 넣지 않는다
(`tools/manifest.py` 제외 루트, README-폐쇄망 반입 복사 제외 목록).
결정의 근거와 합의: 개발 트리 `tasks/pi-agent-lora-upgrade/artifacts/c-consensus.md`.

## 전체 흐름

1. **폐쇄망 PC**: `export-sessions.bat` → `lora\train.jsonl`, `lora\train.report.md`.
2. **반출 승인**: 사람이 보고서(민감 후보·제외 사유 포함)를 읽고 기관 승인을 받는다.
   파일을 옮긴 뒤 `sha256sum train.jsonl` 이 보고서 값과 같은지 확인한다.
3. **개발 PC — 점검(GPU 비용 없음)**: `dataset.py` 로 학습 시퀀스 통계를 본다.
4. **개발 PC — Colab 사전 시험**(`run.sh trial`, H100 150분 상한) → 통과하면 본학습(`run.sh train`).
5. **개발 PC — 변환**: `convert_adapter.py` 로 GGUF를 만든다(sha256·텐서 수 기록).
6. **반입**: `pi-lora-YYYYMMDD.gguf` 와 `.json`(sha256)을 승인 매체로 옮겨 `C:\pi_agent\lora\` 에 두고
   `config.env` 의 `LORA_FILE` 로 켠다. `verify-offline.bat` 통과와 `LORA_FILE` 비우기 롤백 확인 뒤 운영.

## 준비 (개발 PC, 한 번)

```bash
# Colab CLI 로그인 (colab whoami 로 확인)
# 학습 스크립트 점검용 파이썬: torch(cpu), transformers==5.17.0, peft==0.21.0, safetensors
git clone --depth 1 --branch b11010 https://github.com/ggml-org/llama.cpp ~/llama.cpp-b11010
```

## 3. 점검

```bash
python colab-lora/dataset.py --data train.jsonl --tokenizer Qwen/Qwen3.8-27B
```

`train`/`eval` 세션 수, 학습 대상 수, `separate_targets`(요청 토큰이 달라 따로 학습할 대상 —
빈 reasoning 뒤 응답), `over_length_targets`(`--max-seq-len` 을 넘어 보류된 대상), 최대 시퀀스
길이가 나온다. 템플릿이 번들 GGUF와 다르면 여기서 멈춘다.

## 4. Colab 실행

```bash
# 사전 시험: 반출 데이터가 아직 없으므로 합성 데이터로 최장 문맥(약 31k·62k 토큰)과 학습 대상이 많은 응답(약 8k)을 잰다
python colab-lora/make_trial_data.py --base <v2 train.jsonl 예: 픽스처 export> --tokenizer Qwen/Qwen3.8-27B --out trial.jsonl
colab-lora/run.sh trial trial.jsonl trial.report.md --max-seq-len 65536 --holdout 0

colab-lora/run.sh train train.jsonl train.report.md      # 본학습 (추가 인자는 train.py로)
```

사전 시험의 결과(`trial_checks` 피크 VRAM)로 본학습의 `--max-seq-len`(기본 32768)을 정한다. 합성 데이터라
품질은 재지 않는다 — 커널·메모리·NF4 제외 목록·Q6_K 적재만 본다. 본학습 평가(보류 세션을 학습 전·후 두 번)는
보류 세션이 많고 길면 수십 분이 들 수 있다.

`run.sh` 가 코드로 지키는 것:

- 데이터 sha256이 보고서 값과 다르거나, 이미 Colab 세션이 있으면 시작하지 않는다.
- 요청한 GPU가 아니면 업로드 전에 멈춘다(77). 마감은 실행 시작부터 `WALL_MIN`(trial 150, train 600분) 하나다. 설치·업로드·학습·검증·회수가 모두 그 안에
  들어가고, 학습에는 검증·회수 몫(`VERIFY_RESERVE_MIN` 30분)과 여유 5분을 뺀 시간만 준다. 자동 연장은 없다.
- 세션 생성 시도부터 정리 대상이다. 어떤 종료 경로든 VM 파일을 지우고 `colab stop` 한 뒤 서버 목록에서
  사라졌는지 확인한다. 이 스크립트가 죽어도 로컬 감시 프로세스가 마감 10분 뒤 stop한다.
- 모든 파일(데이터·코드·checkpoint·어댑터)은 40MB 조각으로 주고받고 양쪽 sha256을 대조한다.
  받은 `report.json` 의 데이터·어댑터·어댑터 설정 해시도 대조한다.
- 학습이 시간 상한에 걸리면 checkpoint(어댑터+optimizer+scheduler+RNG+진행 위치+설정 지문)를 받아 두고
  76으로 끝난다. `RESUME_FROM=<work>/checkpoint run.sh train ...` 으로 이어 간다(데이터·설정이 다르면 거부).
- 학습이 끝나면 VM에서 번들과 같은 Q6_K(sha256 대조)와 llama.cpp b11010에 어댑터를 올려
  텐서가 모두 적재되는지 확인한다(`verify.json`).

환경변수: `GPU`(기본 H100), `SESSION`, `WALL_MIN`, `POLL_SEC`. 결과: `colab-lora/work/<시각>-<모드>/`
(Git 제외).

종료 코드: 0 완료, 64 사용법·RESUME_FROM 오류, 65 데이터 sha 불일치, 66 기존 세션 있음, 70 세션이 안 닫힘
(수동 stop), 71 패키지 설치 실패, 72 마감 초과, 73 학습 실패, 74 해시 불일치, 75 Q6_K 적재 검증 실패,
76 시간 상한으로 멈춤(checkpoint 받음), 77 요청과 다른 GPU 할당.

**사전 시험 통과 조건**(합의 12): `train.py --trial` 이 종료코드 0 — 코드가 검사하는 것은 커널 대체 경고 없음
(첫 스텝 뒤), loss·grad 유한, 매 스텝 LoRA 가중치 실제 갱신, checkpoint 재개가 망가뜨린 가중치를 복원. 짧은
시퀀스·가장 긴 시퀀스·대상 토큰이 가장 많은 시퀀스를 모두 돌린다. 사람이 볼 것: `report.json` 의
`modules`(in_proj_a/b/qkv·lm_head가 Linear+bfloat16, `linear4bit_modules` > 0), `trial_checks` 의 피크 VRAM,
`train.log` 의 `tokens_per_sec`, `verify.json` 의 `ok: true`·`returncodes` 0, 마지막 줄 "세션 종료 확인".

## 5. 변환

```bash
python colab-lora/convert_adapter.py colab-lora/work/<시각>-train/adapter pi-lora-20261001.gguf \
  --base <Qwen/Qwen3.8-27B config·토크나이저 폴더> --llama-cpp ~/llama.cpp-b11010
```

출력 이름은 `config.env LORA_FILE` 규칙(`[A-Za-z0-9._-]+.gguf`)을 따라야 한다. 같은 이름의 `.json` 에
sha256·텐서 수가 남는다.

## 학습 규칙 요약

- 원본 `Qwen/Qwen3.8-27B`(revision `1d4bf0f2…`)를 NF4로 올린 QLoRA. `lm_head`·`visual`·`in_proj_a/b/qkv` 는 BF16.
- LoRA 대상: `language_model` 층의 q/k/v/o, in_proj_qkv/z/a/b, gate/up/down. `linear_attn.out_proj`·visual·mtp 제외.
- r 16, alpha 32, dropout 0.05, lr 1e-4, 1 epoch, 스텝당 대상 토큰 8192.
- 학습 대상은 `train_indices` 응답의 생성 토큰(`<|im_end|>` 포함)뿐. 렌더는 번들 GGUF 템플릿, 도구 정의는
  llama-server와 같게 `type·function{name, description, parameters}` 로 줄인다(llama-server `/apply-template`·
  `/tokenize` 와 문자열·토큰 ID 일치 실측).
- 평가는 세션 단위 10% 보류.

## 개발 PC에서 이미 확인한 것 (GPU 없이)

`tests/test_colab_lora_dataset.py`, `tests/test_colab_lora_run.py`(가짜 colab CLI)와 개발 트리
`tasks/pi-agent-lora-upgrade/artifacts/c-probe/`: 실제 구조(비전·MTP 포함)를 줄인 초소형 모델로
`train.py --trial` → `convert_adapter.py` → Windows·Linux llama.cpp b11010 적재(56 텐서), 렌더·토큰 동일성.
**27B 실물의 메모리·처리량·커널 동작은 사전 시험에서만 확인된다.**
