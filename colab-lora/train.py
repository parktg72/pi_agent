"""Colab VM에서 Qwen3.8-27B QLoRA를 학습한다 (C단계 합의: tasks/pi-agent-lora-upgrade/artifacts/c-consensus.md).

- 원본 Qwen/Qwen3.8-27B(revision 고정)를 NF4로 올린다. lm_head·visual·in_proj_a/b/qkv는 BF16으로 둔다(합의 14).
  prepare_model_for_kbit_training은 쓰지 않는다 - 비양자화 층을 전부 float32로 올려 수 GB를 더 쓴다.
- 라벨은 dataset.py가 만든다. 손실은 대상 토큰 위치의 hidden state에만 lm_head를 조각으로 적용해 계산한다
  (전체 어휘 로짓 63k x 248k를 만들지 않는다, 합의 2). forward에 labels=를 넘기지 않는다.
- Gated DeltaNet 커널(flash-linear-attention, causal-conv1d)이 없으면 시작하지 않는다(--allow-fallback은 CPU 시험용).
- 스텝 = 대상 토큰이 --target-tokens-per-step에 이를 때까지 모은 시퀀스 묶음. 손실은 묶음의 대상 토큰 평균.
- checkpoint(어댑터+optimizer+scheduler+RNG+진행 위치)를 --checkpoint-minutes마다, 그리고 --time-limit-min 직전에 남긴다.
  시간 상한에 걸리면 checkpoint를 남기고 종료코드 5로 끝난다(자동 연장 없음, 합의 10).
- --trial: 짧은 시퀀스 1스텝 → 긴 시퀀스부터 내려가며 OOM이 아닌 첫 길이(최대 학습 가능 길이) → 대상 토큰이 가장 많은
  시퀀스 → checkpoint 저장·재개 → 1스텝. 길이별 OOM·피크 메모리·처리량을 보고한다(합의 12, A100 40GB 대응).

산출: <out>/adapter/(PEFT safetensors, 반입 변환용), <out>/report.json, <out>/DONE(성공 표식), 로그는 표준출력 JSON 줄.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import os
import platform
import random
import sys
import time
from pathlib import Path

import torch
import torch.nn.functional as F
from torch.utils.checkpoint import checkpoint

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dataset  # noqa: E402

BASE_MODEL = "Qwen/Qwen3.8-27B"
BASE_REVISION = "1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0"
SKIP_4BIT = ["lm_head", "model.visual", "in_proj_a", "in_proj_b", "in_proj_qkv"]
# language_model 안의 텍스트 층만. linear_attn.out_proj는 convert_lora_to_gguf가 NotImplementedError(합의 5).
TARGET_MODULES = (r"model\.language_model\.layers\.\d+\.(self_attn\.(q_proj|k_proj|v_proj|o_proj)"
                  r"|linear_attn\.(in_proj_qkv|in_proj_z|in_proj_a|in_proj_b)|mlp\.(gate_proj|up_proj|down_proj))")
EXIT_TIME_LIMIT = 5


def log(event: str, **fields) -> None:
    print(json.dumps({"t": round(time.time(), 1), "event": event, **fields}, ensure_ascii=False), flush=True)


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--data", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--model", default=BASE_MODEL)
    p.add_argument("--revision", default=BASE_REVISION)
    p.add_argument("--template", type=Path, default=Path(__file__).with_name("qwen38_chat_template.jinja"))
    p.add_argument("--max-seq-len", type=int, default=32768)
    p.add_argument("--holdout", type=float, default=0.1)
    p.add_argument("--r", type=int, default=16)
    p.add_argument("--alpha", type=int, default=32)
    p.add_argument("--dropout", type=float, default=0.05)
    p.add_argument("--lr", type=float, default=1e-4)
    p.add_argument("--epochs", type=int, default=1)
    p.add_argument("--warmup-ratio", type=float, default=0.03)
    p.add_argument("--target-tokens-per-step", type=int, default=8192)
    p.add_argument("--lm-head-chunk", type=int, default=2048)
    p.add_argument("--max-steps", type=int, default=0, help="0 = 제한 없음")
    p.add_argument("--checkpoint-minutes", type=float, default=30)
    p.add_argument("--time-limit-min", type=float, default=0, help="0 = 제한 없음. 넘기 전에 checkpoint 후 종료코드 5")
    p.add_argument("--resume", action="store_true")
    p.add_argument("--trial", action="store_true")
    p.add_argument("--seed", type=int, default=1234)
    p.add_argument("--device", default="cuda")
    p.add_argument("--no-4bit", action="store_true", help="CPU 초소형 시험용")
    p.add_argument("--allow-fallback", action="store_true", help="커널 없이 torch 경로 허용(CPU 시험용)")
    return p.parse_args(argv)


def kernel_status() -> dict:
    status = {}
    try:
        from fla.ops.gated_delta_rule import chunk_gated_delta_rule  # noqa: F401
        status["flash_linear_attention"] = True
    except Exception as error:  # 설치 안 됨, CUDA 없음 등
        status["flash_linear_attention"] = f"missing: {error}"
    try:
        from causal_conv1d import causal_conv1d_fn  # noqa: F401
        status["causal_conv1d"] = True
    except Exception as error:
        status["causal_conv1d"] = f"missing: {error}"
    return status


class FallbackWatch(logging.Handler):
    """transformers가 커널 대신 torch 참조 구현으로 떨어질 때 남기는 경고를 모은다.

    커널 선택은 호출 시점에 확정되고 경고도 그때 나온다(integrations/hub_kernels.py). import만 확인해서는
    모자라다 - 첫 스텝 뒤에 이 목록이 비어 있어야 한다."""

    def __init__(self):
        super().__init__()
        self.messages: list[str] = []

    def emit(self, record):
        message = record.getMessage()
        if "falling back to its reference" in message:
            self.messages.append(message.split(" because ")[0])


def versions() -> dict:
    import peft
    import transformers

    out = {"python": platform.python_version(), "torch": torch.__version__, "transformers": transformers.__version__, "peft": peft.__version__}
    try:
        import bitsandbytes

        out["bitsandbytes"] = bitsandbytes.__version__
    except Exception:
        out["bitsandbytes"] = None
    if torch.cuda.is_available():
        out["gpu"] = torch.cuda.get_device_name(0)
        out["cuda"] = torch.version.cuda
    return out


def load_model(args, dtype):
    from peft import LoraConfig, get_peft_model
    from transformers import AutoModelForImageTextToText

    kwargs = {"revision": args.revision, "dtype": dtype}
    if not args.no_4bit:
        from transformers import BitsAndBytesConfig

        kwargs["quantization_config"] = BitsAndBytesConfig(
            load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True,
            bnb_4bit_compute_dtype=dtype, llm_int8_skip_modules=SKIP_4BIT)
        kwargs["device_map"] = {"": 0}
    model = AutoModelForImageTextToText.from_pretrained(args.model, **kwargs)
    if args.no_4bit:
        model.to(args.device)
    for parameter in model.parameters():
        parameter.requires_grad_(False)
    model.config.use_cache = False
    model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    model.enable_input_require_grads()
    lora = LoraConfig(r=args.r, lora_alpha=args.alpha, lora_dropout=args.dropout, bias="none", target_modules=TARGET_MODULES)
    model = get_peft_model(model, lora)
    names = [name for name, p in model.named_parameters() if p.requires_grad]
    bad = [name for name in names if "out_proj" in name or "visual" in name or "mtp" in name]
    if not names or bad:
        raise SystemExit(f"[FAIL] LoRA 대상이 합의와 다르다: {len(names)}개, 금지 {bad[:3]}")
    return model


def module_report(model) -> dict:
    """NF4 제외 목록이 실제로 적용됐는지(합의 14): 제외 대상 층의 클래스·dtype과 4bit 층 수."""
    report, quantized = {}, 0
    for name, module in model.named_modules():
        kind = type(module).__name__
        if kind == "Linear4bit":
            quantized += 1
        for key in ("in_proj_a", "in_proj_b", "in_proj_qkv", "lm_head"):
            if name.endswith(key) and key not in report and hasattr(module, "weight"):
                report[key] = {"module": name, "class": kind, "dtype": str(module.weight.dtype)}
        if ".visual." in name and "visual" not in report and hasattr(module, "weight") and isinstance(getattr(module, "weight"), torch.Tensor):
            report["visual"] = {"module": name, "class": kind, "dtype": str(module.weight.dtype)}
    report["linear4bit_modules"] = quantized
    return report


def sequence_loss(model, sequence: dataset.Sequence, device, chunk: int) -> tuple[torch.Tensor, int]:
    """대상 토큰 음의 로그우도 합과 대상 토큰 수. 위치 t의 정답은 hidden t-1로 예측한다."""
    inner = model.get_base_model()
    ids = torch.tensor([sequence.input_ids], device=device)
    labels = torch.tensor(sequence.labels, device=device)
    positions = (labels[1:] != dataset.IGNORE).nonzero().squeeze(1)
    targets = labels[1:][positions]
    hidden = inner.model(input_ids=ids, use_cache=False).last_hidden_state[0]
    selected = hidden[positions]

    def head(h, t):
        return F.cross_entropy(inner.lm_head(h).float(), t, reduction="sum")

    total = selected.new_zeros((), dtype=torch.float32)
    for start in range(0, selected.shape[0], chunk):
        total = total + checkpoint(head, selected[start:start + chunk], targets[start:start + chunk], use_reentrant=False)
    return total, int(targets.numel())


def plan_steps(sequences, per_step: int, seed: int, epochs: int) -> list[list[int]]:
    steps = []
    for epoch in range(epochs):
        order = list(range(len(sequences)))
        random.Random(seed + epoch).shuffle(order)
        batch, tokens = [], 0
        for index in order:
            batch.append(index)
            tokens += sequences[index].target_tokens
            if tokens >= per_step:
                steps.append(batch)
                batch, tokens = [], 0
        if batch:
            steps.append(batch)
    return steps


def evaluate(model, sequences, device, chunk) -> float | None:
    if not sequences:
        return None
    model.eval()
    total, count = 0.0, 0
    with torch.no_grad():
        for sequence in sequences:
            loss, n = sequence_loss(model, sequence, device, chunk)
            total += loss.item()
            count += n
    model.train()
    return total / count


def save_checkpoint(path: Path, model, optimizer, scheduler, step: int, fingerprint: dict) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(tmp / "adapter")
    torch.save({"optimizer": optimizer.state_dict(), "scheduler": scheduler.state_dict(), "step": step, "fingerprint": fingerprint,
                "rng": {"python": random.getstate(), "torch": torch.get_rng_state(),
                        "cuda": torch.cuda.get_rng_state_all() if torch.cuda.is_available() else None}}, tmp / "state.pt")
    if path.exists():
        import shutil

        shutil.rmtree(path)
    tmp.rename(path)
    log("checkpoint", step=step, path=str(path))


def load_checkpoint(path: Path, model, optimizer, scheduler, fingerprint: dict) -> int:
    from peft import set_peft_model_state_dict
    from safetensors.torch import load_file

    state = torch.load(path / "state.pt", weights_only=False)
    if state.get("fingerprint") != fingerprint:
        raise SystemExit(f"[FAIL] checkpoint가 이번 실행과 다르다(데이터·base·학습 설정): {state.get('fingerprint')} != {fingerprint}")
    set_peft_model_state_dict(model, load_file(path / "adapter" / "adapter_model.safetensors"))
    optimizer.load_state_dict(state["optimizer"])
    scheduler.load_state_dict(state["scheduler"])
    random.setstate(state["rng"]["python"])
    torch.set_rng_state(state["rng"]["torch"])
    if state["rng"]["cuda"] is not None and torch.cuda.is_available():
        torch.cuda.set_rng_state_all(state["rng"]["cuda"])
    log("resumed", step=state["step"], path=str(path))
    return state["step"]


def peak_memory_gib() -> float | None:
    return round(torch.cuda.max_memory_allocated() / 2**30, 2) if torch.cuda.is_available() else None


def main(argv=None) -> int:
    args = parse_args(argv)
    started = time.time()
    args.out.mkdir(parents=True, exist_ok=True)
    random.seed(args.seed)
    torch.manual_seed(args.seed)
    kernels = kernel_status()
    log("start", versions=versions(), kernels=kernels, args={k: str(v) for k, v in vars(args).items()})
    if not args.allow_fallback and not all(v is True for v in kernels.values()):
        log("fail", reason="Gated DeltaNet 커널 없음 - torch 경로는 긴 시퀀스에서 매우 느리다", kernels=kernels)
        return 2

    from transformers import AutoTokenizer, get_cosine_schedule_with_warmup
    from transformers.utils import logging as hf_logging

    fallback = FallbackWatch()
    hf_logging.get_logger().addHandler(fallback)

    tokenizer = AutoTokenizer.from_pretrained(args.model, revision=args.revision)
    template = args.template.read_text(encoding="utf-8")
    template_sha = dataset.check_template(template, tokenizer)
    samples = dataset.load_samples(args.data)
    train_samples, eval_samples = dataset.split_sessions(samples, args.holdout)
    render, encode = dataset.hf_functions(tokenizer, template)
    train_seqs, train_stats = dataset.build_all(train_samples, render, encode, args.max_seq_len)
    eval_seqs, eval_stats = dataset.build_all(eval_samples, render, encode, args.max_seq_len)
    log("data", train=train_stats.__dict__, eval=eval_stats.__dict__)
    if not train_seqs:
        log("fail", reason="학습할 시퀀스가 없다")
        return 3

    data_sha = hashlib.sha256(args.data.read_bytes()).hexdigest()
    fingerprint = {"data_sha256": data_sha, "model": args.model, "revision": args.revision, "template_sha256": template_sha,
                   **{k: getattr(args, k) for k in ("max_seq_len", "holdout", "r", "alpha", "dropout", "lr", "epochs",
                                                     "warmup_ratio", "target_tokens_per_step", "max_steps", "seed", "trial")}}
    dtype = torch.bfloat16 if args.device == "cuda" else torch.float32
    model = load_model(args, dtype)
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    modules = module_report(model)
    log("model", trainable_params=trainable, peak_gib=peak_memory_gib(), modules=modules)
    params = [p for p in model.parameters() if p.requires_grad]
    optimizer = torch.optim.AdamW(params, lr=args.lr, weight_decay=0.0)

    probe_name = next(n for n, p in model.named_parameters() if p.requires_grad and "lora_B" in n)
    fake_oom_over = int(os.environ.get("TRAIN_FAKE_OOM_OVER", "0"))  # CPU 시험용: 이 길이를 넘는 시퀀스에서 OOM을 흉내 낸다

    def do_step(indices: list[int], total: int) -> dict:
        """한 optimizer 스텝. 실패면 {"fail": 이유}. OOM은 호출자가 잡는다."""
        tick = time.time()
        batch = [train_seqs[i] for i in indices]
        step_targets = sum(s.target_tokens for s in batch)
        probe_before = model.get_parameter(probe_name).detach().clone()
        loss_sum = 0.0
        for sequence in batch:
            if fake_oom_over and len(sequence.input_ids) > fake_oom_over:
                raise torch.OutOfMemoryError(f"fake OOM at {len(sequence.input_ids)} tokens")
            loss, _ = sequence_loss(model, sequence, args.device, args.lm_head_chunk)
            (loss / step_targets).backward()
            loss_sum += loss.detach().item()
        grad_norm = float(torch.nn.utils.clip_grad_norm_(params, 1.0))
        if not math.isfinite(loss_sum) or not math.isfinite(grad_norm):
            return {"fail": "loss 또는 grad가 유한하지 않다", "loss": loss_sum, "grad_norm": grad_norm}
        optimizer.step()
        scheduler.step()
        optimizer.zero_grad(set_to_none=True)
        if args.trial and torch.equal(probe_before, model.get_parameter(probe_name).detach()):
            return {"fail": "optimizer step 뒤에도 LoRA 가중치가 그대로다", "grad_norm": grad_norm}
        seconds = time.time() - tick
        tokens = sum(len(s.input_ids) for s in batch)
        metrics = {"total": total, "loss": round(loss_sum / step_targets, 4), "grad_norm": round(grad_norm, 4),
                   "lr": scheduler.get_last_lr()[0], "tokens": tokens, "target_tokens": step_targets, "sec": round(seconds, 2),
                   "tokens_per_sec": round(tokens / seconds, 1), "peak_gib": peak_memory_gib()}
        if fallback.messages and not args.allow_fallback:
            return {"fail": "Gated DeltaNet 커널 대신 torch 참조 구현이 쓰였다", "fallback": sorted(set(fallback.messages))}
        return metrics

    def recover_from_oom() -> None:
        import gc

        optimizer.zero_grad(set_to_none=True)
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    def reset_peak() -> None:
        if torch.cuda.is_available():
            torch.cuda.reset_peak_memory_stats()

    ckpt = args.out / "checkpoint"
    trial_marks: dict = {}
    eval_before = None
    if args.trial:
        # 짧은 시퀀스 → 긴 시퀀스부터 내려가며 OOM이 아닌 첫 길이를 찾는다(최대 학습 가능 길이) → 대상 토큰이 가장 많은
        # 시퀀스(lm_head 손실 경로) → checkpoint 저장·망가뜨리기·재개 → 짧은 시퀀스. warmup 0(첫 스텝 lr이 0이면 갱신 검사가 무의미).
        scheduler = get_cosine_schedule_with_warmup(optimizer, 0, 50)
        ordered = sorted(range(len(train_seqs)), key=lambda i: len(train_seqs[i].input_ids))
        if torch.cuda.is_available():
            trial_marks["gpu_total_gib"] = round(torch.cuda.get_device_properties(0).total_memory / 2**30, 2)
        step = 0

        def trial_step(indices, label):
            nonlocal step
            reset_peak()
            result = do_step(indices, 0)
            if "fail" in result:
                log("fail", step=step + 1, **result)
                raise SystemExit(2 if "fallback" in result else 4)
            step += 1
            log("step", step=step, trial=label, **result)
            return result

        trial_step([ordered[0]], "short")
        ladder, max_ok = [], len(train_seqs[ordered[0]].input_ids)
        for index in reversed(ordered[1:]):
            tokens = len(train_seqs[index].input_ids)
            try:
                result = trial_step([index], f"length {tokens}")
            except torch.OutOfMemoryError as error:
                recover_from_oom()
                ladder.append({"tokens": tokens, "result": "oom"})
                log("oom", tokens=tokens, error=str(error).splitlines()[0][:200])
                continue
            ladder.append({"tokens": tokens, "result": "ok", "peak_gib": result["peak_gib"], "tokens_per_sec": result["tokens_per_sec"]})
            max_ok = tokens
            break
        trial_marks["length_ladder"] = ladder
        trial_marks["max_ok_tokens"] = max_ok
        most = max(range(len(train_seqs)), key=lambda i: train_seqs[i].target_tokens)
        if len(train_seqs[most].input_ids) <= max_ok:
            try:
                result = trial_step([most], "most targets")
                trial_marks["most_targets"] = {"target_tokens": result["target_tokens"], "tokens": result["tokens"], "peak_gib": result["peak_gib"]}
            except torch.OutOfMemoryError as error:
                recover_from_oom()
                trial_marks["most_targets"] = {"result": "oom", "tokens": len(train_seqs[most].input_ids)}
                log("oom", tokens=len(train_seqs[most].input_ids), error=str(error).splitlines()[0][:200])
        save_checkpoint(ckpt, model, optimizer, scheduler, step, fingerprint)
        probe = model.get_parameter(probe_name)
        saved = probe.detach().clone()
        with torch.no_grad():
            probe.add_(1.0)  # 저장 뒤 값을 망가뜨리고 재개가 되돌리는지 본다
        load_checkpoint(ckpt, model, optimizer, scheduler, fingerprint)
        trial_marks["resume_restores_weights"] = bool(torch.equal(saved, probe.detach()))
        if not trial_marks["resume_restores_weights"]:
            log("fail", reason="checkpoint 재개가 LoRA 가중치를 되돌리지 못했다", step=step)
            return 4
        trial_step([ordered[0]], "after resume")
    else:
        steps = plan_steps(train_seqs, args.target_tokens_per_step, args.seed, args.epochs)
        if args.max_steps:
            steps = steps[:args.max_steps]
        scheduler = get_cosine_schedule_with_warmup(optimizer, math.ceil(len(steps) * args.warmup_ratio), len(steps))
        if args.resume and not (ckpt / "state.pt").exists():
            log("fail", reason="--resume인데 checkpoint가 없다", path=str(ckpt))
            return 6
        step = load_checkpoint(ckpt, model, optimizer, scheduler, fingerprint) if args.resume else 0
        eval_before = evaluate(model, eval_seqs, args.device, args.lm_head_chunk)
        log("eval", when="before", loss=eval_before)
        model.train()
        last_ckpt = time.time()
        while step < len(steps):
            if args.time_limit_min and time.time() - started > args.time_limit_min * 60:
                save_checkpoint(ckpt, model, optimizer, scheduler, step, fingerprint)
                log("stop", reason="시간 상한", step=step, total=len(steps))
                return EXIT_TIME_LIMIT
            result = do_step(steps[step], len(steps))
            if "fail" in result:
                log("fail", step=step + 1, **result)
                return 2 if "fallback" in result else 4
            step += 1
            log("step", step=step, **result)
            if time.time() - last_ckpt > args.checkpoint_minutes * 60:
                save_checkpoint(ckpt, model, optimizer, scheduler, step, fingerprint)
                last_ckpt = time.time()

    eval_after = None if args.trial else evaluate(model, eval_seqs, args.device, args.lm_head_chunk)
    log("eval", when="after", loss=eval_after)
    model.save_pretrained(args.out / "adapter")
    adapter_file = args.out / "adapter" / "adapter_model.safetensors"
    report = {
        "base_model": args.model, "base_revision": args.revision, "template_sha256": template_sha,
        "data_sha256": data_sha,
        "adapter_sha256": hashlib.sha256(adapter_file.read_bytes()).hexdigest(),
        "adapter_config_sha256": hashlib.sha256((args.out / "adapter" / "adapter_config.json").read_bytes()).hexdigest(),
        "modules": modules,
        "versions": versions(), "kernels": kernels, "trial": args.trial, "steps": step,
        "train": train_stats.__dict__, "eval": eval_stats.__dict__, "eval_loss_before": eval_before, "eval_loss_after": eval_after,
        "trainable_params": trainable, "peak_gib": peak_memory_gib(), "seconds": round(time.time() - started, 1),
        "lora": {"r": args.r, "alpha": args.alpha, "dropout": args.dropout, "target_modules": TARGET_MODULES, "skip_4bit": None if args.no_4bit else SKIP_4BIT},
        "trial_checks": trial_marks, "kernel_fallbacks": sorted(set(fallback.messages)),
    }
    (args.out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (args.out / "DONE").write_text("ok\n", encoding="utf-8")
    log("done", seconds=report["seconds"], eval_before=eval_before, eval_after=eval_after)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
