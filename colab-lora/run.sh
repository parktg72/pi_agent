#!/usr/bin/env bash
# colab-lora/run.sh — 개발 PC(WSL)에서 Colab GPU로 LoRA 학습을 돌리고 어댑터를 받는다.
#
#   run.sh trial <train.jsonl> <train.report.md> [train.py 추가 인자...]
#   run.sh train <train.jsonl> <train.report.md> [train.py 추가 인자...]
#   RESUME_FROM=<이전 work 폴더>/checkpoint run.sh train ...   # 시간 상한으로 멈춘 학습 이어 가기
#
# C단계 합의(tasks/pi-agent-lora-upgrade/artifacts/c-consensus.md) 10·12와 코드 리뷰(opencode)를 코드로 지킨다.
# - 반출 데이터 sha256이 export-sessions.bat 보고서 값과 다르거나, 이미 Colab 세션이 있으면 시작하지 않는다.
# - 요청한 GPU가 아니면(Colab이 A100 대신 L4를 주는 경우 등) 업로드 전에 멈춘다(종료코드 77).
# - 마감 시각은 실행 시작부터 WALL_MIN(trial 150, train 600분)으로 하나다. 설치·업로드·학습·검증·회수가 모두
#   그 안에 들어가야 하고, 학습에는 검증·회수 몫(VERIFY_RESERVE_MIN)을 뺀 시간만 준다. 자동 연장은 없다.
# - 세션 생성 시도부터 정리 대상이다. 어떤 종료 경로든 VM 파일을 지우고 stop한 뒤 서버 목록에서 사라졌는지 본다.
#   이 스크립트가 죽어도 로컬 감시 프로세스가 마감 10분 뒤 stop한다(colab new가 띄운 keep-alive가 VM을 살려 두므로).
# - 파일은 조각(PART_BYTES)으로 주고받고 양쪽 sha256을 대조한다(Colab CLI 전송은 파일 전체를 base64로 한 번에 보낸다).
# - 학습이 시간 상한으로 checkpoint를 남기면(종료코드 5) 그것을 받아 두고 76으로 끝난다 - 지우지 않는다.
# - 학습이 끝나면 VM에서 번들과 같은 Q6_K + llama.cpp b11010에 어댑터를 올려 본다(verify_load.py).
# 결과: colab-lora/work/<시각>-<mode>/ — Git에 올리지 않는다.
set -euo pipefail

MODE=${1:-}
DATA=${2:-}
REPORT=${3:-}
shift 3 2>/dev/null || true
if [[ "$MODE" != trial && "$MODE" != train ]] || [[ ! -f "$DATA" || ! -f "$REPORT" ]]; then
  echo "usage: $0 trial|train <train.jsonl> <train.report.md> [train.py 추가 인자...]" >&2
  exit 64
fi

HERE=$(cd "$(dirname "$0")" && pwd)
COLAB=${COLAB:-colab}
SESSION=${SESSION:-pi-lora}
GPU=${GPU:-H100}
POLL_SEC=${POLL_SEC:-60}
PART_BYTES=${PART_BYTES:-40M}
VERIFY_RESERVE_MIN=${VERIFY_RESERVE_MIN:-30}
# trial 150분: 원본 56GB 받기·NF4 적재·causal-conv1d 빌드가 첫 스텝 전에 들어간다(추정 — 사전 시험 결과로 조정).
if [[ "$MODE" == trial ]]; then WALL_MIN=${WALL_MIN:-150}; else WALL_MIN=${WALL_MIN:-600}; fi
WALL_SEC=${WALL_SEC:-$(( WALL_MIN * 60 ))}  # 시험용으로 초 단위 지정 가능
MIN_TRAIN_MIN=${MIN_TRAIN_MIN:-10}
REMOTE=/content/pi-lora
WORK="${WORK_ROOT:-$HERE/work}/$(date +%Y%m%d-%H%M%S)-$MODE"
mkdir -p "$WORK"
LOG="$WORK/run.log"
deadline=$(( $(date +%s) + WALL_SEC ))

say() { echo "[run $(date +%H:%M:%S)] $*" | tee -a "$LOG" >&2; }
remaining() { echo $(( deadline - $(date +%s) )); }
remote_py() { # stdin의 파이썬을 VM 커널에서 실행한다. 인자: 제한 초(마감을 넘지 않게 줄인다)
  local limit=${1:-120} left
  left=$(remaining)
  (( left < 30 )) && left=30
  (( limit > left )) && limit=$left
  "$COLAB" exec -s "$SESSION" --timeout "$limit"
}
remote_sha() { # 원격 파일 sha256 (없으면 빈 문자열)
  printf 'import hashlib, os\np = "%s"\nif os.path.exists(p):\n    h = hashlib.sha256()\n    f = open(p, "rb")\n    for b in iter(lambda: f.read(1 << 24), b""):\n        h.update(b)\n    print("SHA", h.hexdigest())\n' "$1" \
    | remote_py 900 2>>"$LOG" | grep -o '^SHA [0-9a-f]*' | cut -d' ' -f2 || true
}
push_file() { # 로컬 파일을 조각으로 올려 VM에서 합치고 sha256을 대조한다
  local src=$1 dst=$2 parts want got part
  want=$(sha256sum "$src" | cut -d' ' -f1)
  parts=$(mktemp -d)
  split -b "$PART_BYTES" -d "$src" "$parts/part_"
  printf 'import os, glob\nos.makedirs(os.path.dirname("%s"), exist_ok=True)\nfor p in glob.glob("%s.part_*"):\n    os.remove(p)\nprint("ok")\n' "$dst" "$dst" | remote_py >>"$LOG" 2>&1
  for part in "$parts"/part_*; do
    "$COLAB" upload -s "$SESSION" "$part" "$dst.$(basename "$part")" >>"$LOG" 2>&1
  done
  rm -rf "$parts"
  printf 'import glob, os\nwith open("%s", "wb") as out:\n    for p in sorted(glob.glob("%s.part_*")):\n        out.write(open(p, "rb").read())\n        os.remove(p)\nprint("joined")\n' "$dst" "$dst" | remote_py 600 >>"$LOG" 2>&1
  got=$(remote_sha "$dst")
  if [[ "$got" != "$want" ]]; then
    say "[FAIL] 업로드 sha256 불일치 $dst: VM ${got:-없음} != 로컬 $want"
    return 1
  fi
}
fetch_file() { # VM 파일을 조각으로 받아 합치고 sha256을 대조한다. 성공하면 sha256을 표준출력에 쓴다
  local src=$1 dst=$2 want got names part
  want=$(remote_sha "$src")
  if [[ -z "$want" ]]; then
    say "[FAIL] VM에 $src 없음"
    return 1
  fi
  names=$(printf 'import os, subprocess\nd, f = os.path.split("%s")\nfor p in os.listdir(d):\n    if p.startswith(f + ".part_"):\n        os.remove(os.path.join(d, p))\nsubprocess.run(["split", "-b", "%s", "-d", f, f + ".part_"], cwd=d, check=True)\nprint("PARTS", " ".join(sorted(p for p in os.listdir(d) if p.startswith(f + ".part_"))))\n' "$src" "$PART_BYTES" \
    | remote_py 600 2>>"$LOG" | grep -o '^PARTS .*' | cut -d' ' -f2- || true)
  mkdir -p "$(dirname "$dst")"
  : > "$dst"
  for part in $names; do
    "$COLAB" download -s "$SESSION" "$(dirname "$src")/$part" "$dst.part" >>"$LOG" 2>&1
    cat "$dst.part" >> "$dst"
    rm -f "$dst.part"
  done
  printf 'import glob, os\nfor p in glob.glob("%s.part_*"):\n    os.remove(p)\n' "$src" | remote_py >>"$LOG" 2>&1 || true
  got=$(sha256sum "$dst" | cut -d' ' -f1)
  if [[ "$got" != "$want" ]]; then
    say "[FAIL] 다운로드 sha256 불일치 $src: 로컬 $got != VM $want"
    return 1
  fi
  echo "$got"
}

want=$(grep -o 'sha256: `[0-9a-f]\{64\}`' "$REPORT" | head -1 | grep -o '[0-9a-f]\{64\}' || true)
data_sha=$(sha256sum "$DATA" | cut -d' ' -f1)
if [[ -z "$want" || "$want" != "$data_sha" ]]; then
  say "[FAIL] $DATA sha256 $data_sha 이 보고서 값(${want:-없음})과 다르다 - 반출 승인된 파일인지 확인"
  exit 65
fi
if [[ -n "${RESUME_FROM:-}" ]] && [[ "$MODE" != train || ! -f "$RESUME_FROM/state.pt" || ! -f "$RESUME_FROM/adapter/adapter_model.safetensors" ]]; then
  say "[FAIL] RESUME_FROM=$RESUME_FROM 은 train 모드의 checkpoint 폴더(state.pt, adapter/)여야 한다"
  exit 64
fi
say "데이터 sha256 일치 $data_sha ($(wc -l < "$DATA") 샘플), 마감 $(date -d "@$deadline" +%H:%M)"

ours() { grep -q "^\[$SESSION\]" <<<"$1"; }  # colab sessions 줄: [로컬이름] endpoint | Hardware: ...
existing=$("$COLAB" sessions 2>&1 || true)
if ours "$existing"; then
  say "[FAIL] 같은 이름의 Colab 세션($SESSION)이 이미 있다 - 이전 실행이 남긴 것인지 확인하고 정리하라:"$'\n'"$existing"
  exit 66
fi
if ! grep -q "No active sessions" <<<"$existing" && [[ "${ALLOW_OTHER_SESSIONS:-0}" != 1 ]]; then
  say "[FAIL] 다른 Colab 세션이 있다(브라우저 런타임 등) - 정리하거나, 이 실행과 무관하면 ALLOW_OTHER_SESSIONS=1:"$'\n'"$existing"
  exit 66
fi

created=0
watchdog=""
cleanup() {
  local rc=$?
  if [[ $created == 1 ]]; then
    say "정리: VM 파일 삭제 후 세션 종료"
    printf 'import shutil, os\nshutil.rmtree("%s", ignore_errors=True)\nshutil.rmtree("/content/verify-cache", ignore_errors=True)\nshutil.rmtree(os.path.expanduser("~/.cache/huggingface"), ignore_errors=True)\nprint("wiped")\n' "$REMOTE" \
      | "$COLAB" exec -s "$SESSION" --timeout 300 >>"$LOG" 2>&1 || say "[warn] VM 파일 삭제 실패 - stop으로 VM이 사라지면 함께 지워진다"
    "$COLAB" stop -s "$SESSION" >>"$LOG" 2>&1 || true
    if ! ours "$("$COLAB" sessions 2>&1 || true)"; then
      say "세션 종료 확인($SESSION이 서버 목록에 없음)"
    else
      say "[FAIL] 세션이 아직 서버에 있다 - 'colab sessions' 확인 후 수동으로 stop 하라"
      rc=70
    fi
  fi
  if [[ -n "$watchdog" ]]; then
    kill -- -"$watchdog" 2>/dev/null || kill "$watchdog" 2>/dev/null || true
  fi
  exit $rc
}
trap cleanup EXIT
trap 'exit 130' INT TERM

say "세션 생성: $SESSION --gpu $GPU (마감까지 ${WALL_MIN}분)"
created=1  # 생성 응답이 실패해도 서버에는 만들어졌을 수 있다 - 정리 대상으로 둔다
setsid bash -c "sleep $(( WALL_SEC + 600 )); if \"\$1\" sessions 2>&1 | grep -q \"^\\[\$2\\]\"; then \"\$1\" stop -s \"\$2\"; fi" _ "$COLAB" "$SESSION" >>"$LOG" 2>&1 < /dev/null &
watchdog=$!
timeout 900 "$COLAB" new -s "$SESSION" --gpu "$GPU" >>"$LOG" 2>&1
hardware=$("$COLAB" status -s "$SESSION" 2>&1 || true)
echo "$hardware" >> "$LOG"
if ! grep -Eq "Hardware: ${GPU}( |\||$)" <<<"$hardware"; then
  say "[FAIL] 요청한 GPU($GPU)가 아니다 - 대체 할당으로 시간·비용만 쓰지 않게 멈춘다: $(grep -o 'Hardware: [^|]*' <<<"$hardware" | head -1)"
  exit 77
fi

printf 'import os\nos.makedirs("%s/out", exist_ok=True)\nprint("ok")\n' "$REMOTE" | remote_py >>"$LOG" 2>&1
push_file "$DATA" "$REMOTE/train.jsonl"
for f in dataset.py train.py verify_load.py convert_adapter.py qwen38_chat_template.jinja requirements-colab.txt; do
  push_file "$HERE/$f" "$REMOTE/$f"
done
if [[ -n "${RESUME_FROM:-}" ]]; then
  push_file "$RESUME_FROM/state.pt" "$REMOTE/out/checkpoint/state.pt"
  push_file "$RESUME_FROM/adapter/adapter_model.safetensors" "$REMOTE/out/checkpoint/adapter/adapter_model.safetensors"
  push_file "$RESUME_FROM/adapter/adapter_config.json" "$REMOTE/out/checkpoint/adapter/adapter_config.json"
fi
say "업로드 완료(sha256 대조), 패키지 설치"
pip_out=$(printf 'import subprocess, sys\nr = subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-r", "%s/requirements-colab.txt"], capture_output=True, text=True)\nprint(r.stdout[-3000:], r.stderr[-3000:])\nopen("%s/out/pip-freeze.txt", "w").write(subprocess.run([sys.executable, "-m", "pip", "freeze"], capture_output=True, text=True).stdout)\nprint("PIP_RC", r.returncode)\n' "$REMOTE" "$REMOTE" | remote_py 3600 2>&1 || true)
echo "$pip_out" >> "$LOG"
if ! grep -q "^PIP_RC 0" <<<"$pip_out"; then
  say "[FAIL] 패키지 설치 실패"
  exit 71
fi

# VM에서 파이썬 스크립트를 백그라운드로 띄우고(<name>.log, <name>.exit) 끝날 때까지 로그를 받아 온다.
# colab exec는 출력 없이 --timeout을 넘기면 끊기므로 긴 작업을 전경에서 돌리지 않는다.
# 인자는 JSON 목록으로 넘겨 argv로 전달한다 - 셸 따옴표를 거치지 않는다.
job_rc=""
run_job() {
  local name=$1 script=$2
  shift 2
  local args_json seen=0 status length
  args_json=$(python3 -c 'import json, sys; print(json.dumps(sys.argv[1:]))' "$@")
  say "$name 시작(백그라운드): $script $args_json"
  printf 'import json, subprocess, sys\nargs = json.loads(%s)\nsubprocess.Popen(["bash", "-c", "\\"$0\\" %s \\"$@\\" > %s.log 2>&1; echo $? > %s.exit", sys.executable] + args, cwd="%s", start_new_session=True)\nprint("launched")\n' \
    "$(python3 -c 'import json, sys; print(json.dumps(sys.argv[1]))' "$args_json")" "$script" "$name" "$name" "$REMOTE" | remote_py >>"$LOG" 2>&1
  job_rc=""
  while :; do
    sleep "$POLL_SEC"
    status=$(printf 'import os\nd = "%s"\nlog = open(d + "/%s.log").read() if os.path.exists(d + "/%s.log") else ""\nprint("LOGLEN", len(log))\nprint(log[%d:][-20000:], end="")\nprint("\\nEXIT", open(d + "/%s.exit").read().strip() if os.path.exists(d + "/%s.exit") else "RUNNING")\n' \
      "$REMOTE" "$name" "$name" "$seen" "$name" "$name" | remote_py 120 2>>"$LOG" || true)
    length=$(grep -o '^LOGLEN [0-9]*' <<<"$status" | head -1 | cut -d' ' -f2 || true)
    sed -e '/^LOGLEN /d' -e '/^EXIT /d' <<<"$status" | tee -a "$WORK/$name.log" | grep -E '"event": "(start|data|model|eval|step|oom|checkpoint|resumed|stop|fail|done|q6k|verify)"' | cut -c1-240 >&2 || true
    [[ -n "$length" ]] && seen=$length
    job_rc=$(grep -o '^EXIT .*' <<<"$status" | tail -1 | cut -d' ' -f2 || true)
    if [[ -n "$job_rc" && "$job_rc" != RUNNING ]]; then
      say "$name 종료코드 $job_rc"
      return 0
    fi
    if (( $(remaining) <= 0 )); then
      say "[FAIL] 마감(${WALL_MIN}분) 초과 - $name 프로세스 종료"
      printf 'import subprocess\nsubprocess.run(["pkill", "-f", "%s"])\nprint("killed")\n' "$script" | "$COLAB" exec -s "$SESSION" --timeout 60 >>"$LOG" 2>&1 || true
      exit 72
    fi
  done
}

train_min=$(( $(remaining) / 60 - VERIFY_RESERVE_MIN - 5 ))
if (( train_min < MIN_TRAIN_MIN )); then
  say "[FAIL] 학습에 남은 시간 ${train_min}분 - WALL_MIN을 늘려라(검증·회수 몫 ${VERIFY_RESERVE_MIN}분 포함)"
  exit 72
fi
extra=("--data" "train.jsonl" "--out" "out" "--time-limit-min" "$train_min")
if [[ "$MODE" == trial ]]; then extra+=("--trial"); fi
if [[ -n "${RESUME_FROM:-}" ]]; then extra+=("--resume"); fi
extra+=("$@")
run_job train train.py "${extra[@]}"
train_rc=$job_rc

"$COLAB" download -s "$SESSION" "$REMOTE/out/pip-freeze.txt" "$WORK/pip-freeze.txt" >>"$LOG" 2>&1 || true
if [[ "$train_rc" == 5 ]]; then
  fetch_file "$REMOTE/out/checkpoint/state.pt" "$WORK/checkpoint/state.pt" >/dev/null
  fetch_file "$REMOTE/out/checkpoint/adapter/adapter_model.safetensors" "$WORK/checkpoint/adapter/adapter_model.safetensors" >/dev/null
  fetch_file "$REMOTE/out/checkpoint/adapter/adapter_config.json" "$WORK/checkpoint/adapter/adapter_config.json" >/dev/null
  say "시간 상한으로 멈췄다 - checkpoint를 받았다(sha256 대조). 이어서: RESUME_FROM=$WORK/checkpoint $0 train $DATA $REPORT $*"
  exit 76
fi
if [[ "$train_rc" != 0 ]]; then
  say "[FAIL] train.py가 실패했다(종료코드 $train_rc) - $WORK/train.log 확인"
  exit 73
fi

fetch_file "$REMOTE/out/report.json" "$WORK/report.json" >/dev/null
adapter_sha=$(fetch_file "$REMOTE/out/adapter/adapter_model.safetensors" "$WORK/adapter/adapter_model.safetensors")
config_sha=$(fetch_file "$REMOTE/out/adapter/adapter_config.json" "$WORK/adapter/adapter_config.json")
read -r rep_data rep_adapter rep_config < <(python3 -c 'import json, sys; r = json.load(open(sys.argv[1])); print(r["data_sha256"], r["adapter_sha256"], r["adapter_config_sha256"])' "$WORK/report.json")
if [[ "$rep_data" != "$data_sha" || "$rep_adapter" != "$adapter_sha" || "$rep_config" != "$config_sha" ]]; then
  say "[FAIL] report.json 해시 불일치: data $rep_data/$data_sha adapter $rep_adapter/$adapter_sha config $rep_config/$config_sha"
  exit 74
fi
say "어댑터 받음: sha256 $adapter_sha (학습 데이터 sha256 일치)"

run_job verify verify_load.py --adapter out/adapter --out out/verify
if ! fetch_file "$REMOTE/out/verify/verify.json" "$WORK/verify.json" >/dev/null || [[ "$job_rc" != 0 ]]; then
  say "[FAIL] Q6_K 적재 검증 실패(종료코드 $job_rc) - $WORK/verify.log, verify.json 확인"
  exit 75
fi
say "완료: $WORK (adapter/, report.json, verify.json) - 다음: convert_adapter.py로 반입용 GGUF 변환"
