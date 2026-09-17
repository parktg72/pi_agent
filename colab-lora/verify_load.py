"""Colab VM에서 학습 결과 어댑터를 실제 번들 모델(Q6_K)과 llama.cpp b11010에 올려 본다 (C단계 합의 9).

개발 PC는 RAM이 모자라 27B GGUF를 올릴 수 없다. VM에서 다음을 한다.
1. 번들과 같은 Q6_K(lmstudio-community/Qwen3.8-27B-GGUF)를 받아 sha256을 번들 인수인계 값과 대조한다.
2. llama.cpp b11010 소스(변환기)와 Ubuntu CPU 빌드(sha256 고정)를 받는다.
3. convert_adapter.py로 어댑터를 GGUF로 바꾼다(개발 PC에서 할 변환과 같은 코드).
4. llama-cli(CPU)로 무어댑터·어댑터 각각 짧게 생성하고, 어댑터 텐서가 모두 적재됐는지 로그로 확인한다.
   몇 스텝짜리 시험 어댑터는 출력이 같을 수 있어 출력 차이는 합격 조건이 아니다(기록만).

산출: <out>/verify.json, <out>/pi-lora-verify.gguf(검증용 사본 — 반입용 변환은 개발 PC에서 다시 한다).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tarfile
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
Q6K_REPO = "lmstudio-community/Qwen3.8-27B-GGUF"
Q6K_FILE = "Qwen3.8-27B-Q6_K.gguf"
Q6K_SHA256 = "6b1d4d0e66297a02878911203d076c9fb4e3bad6153510b958f24512dde28b04"  # docs/superpowers/plans/handoff §1
LLAMA_TAG = "b11010"
LLAMA_CPU_URL = f"https://github.com/ggml-org/llama.cpp/releases/download/{LLAMA_TAG}/llama-{LLAMA_TAG}-bin-ubuntu-x64.tar.gz"
LLAMA_CPU_SHA256 = "d0080249767958f1bb1ad6bbd16889ceaf197301697ae38291cfe62c297227ac"  # GitHub release asset digest
BASE_MODEL = "Qwen/Qwen3.8-27B"
BASE_REVISION = "1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0"


def log(event: str, **fields) -> None:
    print(json.dumps({"t": round(time.time(), 1), "event": event, **fields}, ensure_ascii=False), flush=True)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(16 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def run(cmd: list, **kwargs) -> subprocess.CompletedProcess:
    log("run", cmd=" ".join(str(c) for c in cmd)[:300])
    return subprocess.run(cmd, capture_output=True, text=True, **kwargs)


def generate(cli: Path, model: Path, lora: Path | None) -> tuple[int, str, str]:
    cmd = [str(cli), "-m", str(model), "-p", "hello", "-n", "8", "--temp", "0", "--seed", "1", "--single-turn", "-v", "-c", "2048"]
    cwd = None
    if lora is not None:
        # 번들 start-llama.bat과 같이 상대경로로 준다(절대경로는 콜론 분리로 실패한다).
        cmd += ["--lora-scaled", f"{lora.name}:1.0"]
        cwd = lora.parent
    try:
        result = run(cmd, cwd=cwd, stdin=subprocess.DEVNULL, timeout=3600)
    except subprocess.TimeoutExpired as error:
        return -1, str(error.stdout or ""), f"timeout: {error}"
    return result.returncode, result.stdout, result.stderr


def fetch(args, report):
    """Q6_K·llama.cpp CPU 빌드·소스·원본 config를 받아 sha256을 대조한다. 실패하면 None."""
    from huggingface_hub import hf_hub_download, snapshot_download

    model = Path(hf_hub_download(Q6K_REPO, Q6K_FILE, cache_dir=str(args.cache)))
    report["q6k_sha256"] = sha256_file(model)
    if report["q6k_sha256"] != Q6K_SHA256:
        log("fail", reason="Q6_K sha256이 번들 값과 다르다", got=report["q6k_sha256"])
        return None
    log("q6k", ok=True)

    tarball = args.cache / "llama-cpu.tar.gz"
    if not tarball.exists():
        urllib.request.urlretrieve(LLAMA_CPU_URL, tarball)
    if sha256_file(tarball) != LLAMA_CPU_SHA256:
        log("fail", reason="llama.cpp CPU 빌드 sha256 불일치")
        return None
    with tarfile.open(tarball) as archive:
        archive.extractall(args.cache / "llama-cpu", filter="data")
    cli = next((args.cache / "llama-cpu").rglob("llama-cli"))
    cli.chmod(0o755)

    source = args.cache / "llama.cpp"
    if not source.exists():
        result = run(["git", "clone", "--depth", "1", "--branch", LLAMA_TAG, "https://github.com/ggml-org/llama.cpp", str(source)])
        if result.returncode != 0:
            log("fail", reason="llama.cpp 소스 받기 실패", stderr=result.stderr[-2000:])
            return None
    base = Path(snapshot_download(BASE_MODEL, revision=BASE_REVISION, cache_dir=str(args.cache),
                                  allow_patterns=["config.json", "tokenizer*", "vocab.json", "merges.txt", "chat_template.jinja", "*_config.json"]))
    return model, cli, source, base


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--adapter", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--cache", type=Path, default=Path("/content/verify-cache"))
    # 개발 PC 시험용: 내려받기·sha 대조를 건너뛰고 주어진 파일로 같은 흐름을 돈다(초소형 모델).
    p.add_argument("--local-model", type=Path)
    p.add_argument("--local-cli", type=Path)
    p.add_argument("--local-source", type=Path)
    p.add_argument("--local-base", type=Path)
    args = p.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    args.cache.mkdir(parents=True, exist_ok=True)
    report: dict = {"q6k_sha256_expected": Q6K_SHA256, "llama_tag": LLAMA_TAG}

    if all([args.local_model, args.local_cli, args.local_source, args.local_base]):
        model, cli, source, base = args.local_model, args.local_cli, args.local_source, args.local_base
        report["local_test"] = True
    else:
        fetched = fetch(args, report)
        if fetched is None:
            return 2
        model, cli, source, base = fetched

    lora = args.out / "pi-lora-verify.gguf"
    result = run([sys.executable, str(HERE / "convert_adapter.py"), str(args.adapter), str(lora), "--base", str(base), "--llama-cpp", str(source)])
    if result.returncode != 0:
        log("fail", reason="어댑터 변환 실패", stdout=result.stdout[-2000:], stderr=result.stderr[-2000:])
        return 3
    converted = json.loads(lora.with_suffix(".json").read_text(encoding="utf-8"))
    report["adapter_gguf"] = converted

    base_rc, base_out, base_err = generate(cli, model, None)
    lora_rc, lora_out, lora_err = generate(cli, model, lora)
    report["returncodes"] = {"base": base_rc, "lora": lora_rc}
    if base_rc != 0:
        report["base_stderr_tail"] = base_err[-1500:]
    if lora_rc != 0:
        report["lora_stderr_tail"] = lora_err[-1500:]
    loaded = re.search(r"llama_adapter_lora_init_impl: loaded (\d+) tensors", lora_err)
    report["lora_loaded_tensors"] = int(loaded.group(1)) if loaded else None
    report["lora_load_errors"] = [line for line in lora_err.splitlines() if re.search(r"\b(error|failed)\b", line, re.I)][:10]
    report["output_base_tail"] = base_out[-300:]
    report["output_lora_tail"] = lora_out[-300:]
    report["outputs_differ"] = base_out.strip() != lora_out.strip()
    # 적재 로그만으로는 모자라다 - 적재 뒤 OOM·SIGKILL로 죽어도 로그에 오류 줄이 없을 수 있다(opencode 리뷰).
    report["ok"] = (base_rc == 0 and lora_rc == 0 and report["lora_loaded_tensors"] == converted["tensors"]
                    and not report["lora_load_errors"])
    (args.out / "verify.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    log("verify", ok=report["ok"], loaded=report["lora_loaded_tensors"], expected=converted["tensors"], outputs_differ=report["outputs_differ"])
    return 0 if report["ok"] else 4


if __name__ == "__main__":
    raise SystemExit(main())
