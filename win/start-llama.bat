@echo off
chcp 65001 >nul
setlocal
rem The Python tools print Korean diagnostics. Their encoding is pinned here,
rem before the first Python call - config.env is parsed by Python now, so that
rem call happens earlier than it used to. PYTHONIOENCODING only covers stdio;
rem PYTHONUTF8 covers file I/O the tools do.
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
set "ROOT=%~dp0"
rem Relative paths must resolve against the bundle root, not the caller's cwd.
cd /d "%ROOT%"
call :resolve_bootstrap_python
if errorlevel 1 exit /b 4
call :load_config
if errorlevel 1 exit /b 6
rem Profile. No argument = the Pi coding-agent server (one slot, LLAMA_CTX).
rem "kg" = the knowledge-graph extraction server for LightRAG: KG_PARALLEL slots
rem sharing KG_CTX (default 32768 / 4 = 8192 per slot, closed-network KG bundle, 02 guide).
rem Both use port LLAMA_PORT, so switching means stopping one and starting the
rem other; start-pi.bat refuses to attach to a kg server (tools\server_profile.py).
set "PROFILE=pi"
if /I "%~1"=="kg" set "PROFILE=kg"
if not "%~1"=="" if /I not "%~1"=="kg" (
  echo [FAIL] unknown profile "%~1" - use no argument for Pi, or kg for LightRAG extraction
  exit /b 2
)

if not defined LLAMA_BACKEND set "LLAMA_BACKEND=cuda"
if not defined LLAMA_PORT set "LLAMA_PORT=8080"
if not defined LLAMA_CTX set "LLAMA_CTX=63488"

rem The Vulkan ban used to live only in README and the design spec, while this
rem script accepted LLAMA_BACKEND=vulkan and ran it. A backend that returns
rem wrong answers quietly is worse than one that fails, so the ban is code now.
if /I "%LLAMA_BACKEND%"=="vulkan" (
  echo [FAIL] LLAMA_BACKEND=vulkan is refused for this model.
  echo        The Vulkan backend does not implement ggml_ssm_conv / ggml_ssm_scan
  echo        for the qwen35 architecture. It falls back to CPU silently and
  echo        corrupts state across the GPU-CPU boundary, so the result is either
  echo        a wrong answer or vk::DeviceLostError.
  echo        upstream issue: ggml-org/llama.cpp#19957, open since 2026-02-27.
  echo        If CUDA fails, the only fallback for this model is cpu, and that is
  echo        diagnostic only - see ALLOW_CPU_DIAGNOSTIC in config.env.
  exit /b 8
)
rem cpu means loading a ~20GB (UD-Q5_K_M) model into system RAM. On a machine short of RAM
rem or pagefile that thrashes for a long time instead of failing, so it must be
rem chosen on purpose, never by accident.
if /I "%LLAMA_BACKEND%"=="cpu" if not "%ALLOW_CPU_DIAGNOSTIC%"=="1" (
  echo [FAIL] LLAMA_BACKEND=cpu needs an explicit opt-in.
  echo        This loads a ~20GB model into system RAM. A 27B dense model does
  echo        not reach usable speed on CPU - this backend is for narrowing down
  echo        a problem, not for production.
  echo        Set ALLOW_CPU_DIAGNOSTIC=1 in config.env if that is what you want.
  exit /b 9
)
if /I "%LLAMA_BACKEND%"=="cpu" echo [warn] cpu backend: diagnostic only, not production speed.

set "LLAMA_DIR=%ROOT%bin\llama-%LLAMA_BACKEND%"
if not exist "%LLAMA_DIR%\llama-server.exe" (
  echo [FAIL] %LLAMA_DIR%\llama-server.exe not found
  exit /b 2
)
if not defined MODEL_FILE (
  echo [FAIL] MODEL_FILE is not set - fill in config.env
  exit /b 2
)
if not defined MODEL_ALIAS (
  echo [FAIL] MODEL_ALIAS is not set - fill in config.env
  exit /b 2
)
if not exist "%ROOT%models\%MODEL_FILE%" (
  echo [FAIL] %ROOT%models\%MODEL_FILE% not found
  exit /b 2
)
if defined MMPROJ_FILE if not exist "%ROOT%models\%MMPROJ_FILE%" (
  echo [FAIL] %ROOT%models\%MMPROJ_FILE% not found
  exit /b 2
)

set "TS_ARG="
if defined GPU_TENSOR_SPLIT set "TS_ARG=-ts %GPU_TENSOR_SPLIT%"

set "MMPROJ_ARG="
if defined MMPROJ_FILE set MMPROJ_ARG=--mmproj "%ROOT%models\%MMPROJ_FILE%"
rem Chat template. The bundle pins the original Qwen3.8 template (sha256
rem c3cf9e34..., the one embedded in the Q6_K GGUF and used by every tool
rem round-trip, render parity and LoRA data check). The UD-Q5_K_M GGUF embeds an
rem Unsloth variant that merges system messages and raises on string tool-call
rem arguments. Clearing CHAT_TEMPLATE_FILE falls back to the embedded template.
set "TEMPLATE_ARG="
if defined CHAT_TEMPLATE_FILE if not exist "%ROOT%chat-templates\%CHAT_TEMPLATE_FILE%" (
  echo [FAIL] "%ROOT%chat-templates\%CHAT_TEMPLATE_FILE%" not found
  echo        Clear CHAT_TEMPLATE_FILE in config.env to use the template embedded in the model.
  exit /b 2
)
if defined CHAT_TEMPLATE_FILE set TEMPLATE_ARG=--chat-template-file "%ROOT%chat-templates\%CHAT_TEMPLATE_FILE%"
set "CTX=%LLAMA_CTX%"
set "PARALLEL=1"
if not defined KG_CTX set "KG_CTX=32768"
if not defined KG_PARALLEL set "KG_PARALLEL=4"
if "%PROFILE%"=="kg" set "CTX=%KG_CTX%"
if "%PROFILE%"=="kg" set "PARALLEL=%KG_PARALLEL%"
rem Extraction sends text only, and the vision projector costs VRAM on the card
rem that also hosts the embedding server, so the kg profile leaves it out.
if "%PROFILE%"=="kg" set "MMPROJ_ARG="

rem Tuning for 3x GTX 1080 Ti and 128GB RAM, 2026-09-17, aligned with the
rem closed-network KG bundle on 2026-09-22 (tasks\pi-agent-kg-align consensus).
rem Evidence for each line is llama.cpp b11010 source; see config.env.example.
rem Flash attention comes from LLAMA_FLASH_ATTN, auto by default. ggml-cuda/fattn.cu
rem picks the tile/vec kernels on GPUs without tensor cores, head size 256
rem included, so auto can resolve to enabled on Pascal. auto probes the device
rem first (src/llama-context.cpp) and logs "flash_attn not supported, set to
rem disabled" if it cannot run there; forcing on skips that probe and lets the
rem op land on the CPU instead, so on is not offered. off is what the
rem KG bundle guide sets; rehearsal 11-2 compares off and auto.
rem -fit off: this script owns -ngl, -ts and -c. With -ngl set, --fit (default
rem on) gives up every start and prints an abort line operators read as a
rem failure (common/fit.cpp "n_gpu_layers already set by user").
if not defined LLAMA_FLASH_ATTN set "LLAMA_FLASH_ATTN=auto"
rem LLAMA_KV_TYPE is the K cache type only. A quantized V cache needs flash
rem attention, which is off or may resolve to off here, so V stays f16.
if not defined LLAMA_KV_TYPE set "LLAMA_KV_TYPE=q8_0"

rem Host-RAM prompt cache. With a single slot, switching between a session and
rem a subagent evicts the KV state; the RAM cache lets it come back without a
rem full re-prefill, which is the slow part on Pascal. Unset keeps the
rem llama.cpp default of 8192 MiB.
set "CACHE_RAM_ARG="
if defined LLAMA_CACHE_RAM_MIB set "CACHE_RAM_ARG=--cache-ram %LLAMA_CACHE_RAM_MIB%"

rem Speculative decoding from the model's own MTP layer. Opt-in until a field
rem A/B measurement: on this hybrid model the target context rolls back through
rem checkpoints, so the gain on Pascal is unmeasured.
set "SPEC_ARG="
if "%LLAMA_SPEC_MTP%"=="1" set "SPEC_ARG=--spec-type draft-mtp"

rem Physical batch size, 256 by default. The vocabulary has 248,320 entries, so
rem the logits buffer at the llama.cpp default of 512 is large; 256 is what the
rem KG bundle guide sets. Lower it to 128 if long prompts trigger a Windows
rem "display driver stopped responding" (TDR) reset. The logical batch is fixed
rem at 1024 and config_parse refuses a larger ubatch.
if not defined LLAMA_UBATCH set "LLAMA_UBATCH=256"

rem LoRA adapter trained on the target PC. Clearing LORA_FILE is the rollback.
rem --lora-scaled splits FNAME:SCALE on every colon, so an absolute H:\ path
rem has one colon too many and startup fails. This script has already changed
rem to the bundle root, so the relative lora\ path is used on purpose.
if not defined LORA_SCALE set "LORA_SCALE=1.0"
set "LORA_ARG="
if defined LORA_FILE if not exist "%ROOT%lora\%LORA_FILE%" (
  echo [FAIL] "%ROOT%lora\%LORA_FILE%" not found
  echo        Clear LORA_FILE in config.env to start the base model without an adapter.
  exit /b 2
)
if defined LORA_FILE set LORA_ARG=--lora-scaled "lora\%LORA_FILE%:%LORA_SCALE%"

echo [info] starting %MODEL_FILE% as %MODEL_ALIAS% on the %LLAMA_BACKEND% backend, profile %PROFILE%
echo [info] ctx %CTX% over %PARALLEL% slot(s), k cache %LLAMA_KV_TYPE%, v cache f16, flash attention %LLAMA_FLASH_ATTN%, ubatch %LLAMA_UBATCH%
if defined CHAT_TEMPLATE_FILE echo [info] chat template chat-templates\%CHAT_TEMPLATE_FILE%
if defined LORA_FILE echo [info] LoRA adapter lora\%LORA_FILE% at scale %LORA_SCALE%
"%LLAMA_DIR%\llama-server.exe" ^
  -m "%ROOT%models\%MODEL_FILE%" ^
  --alias "%MODEL_ALIAS%" ^
  --jinja ^
  --host 127.0.0.1 ^
  --port %LLAMA_PORT% ^
  -ngl 999 ^
  -c %CTX% ^
  --parallel %PARALLEL% ^
  -sm layer %TS_ARG% %MMPROJ_ARG% ^
  -fa %LLAMA_FLASH_ATTN% -fit off -ctk %LLAMA_KV_TYPE% -ctv f16 -b 1024 -ub %LLAMA_UBATCH% --no-mmap %TEMPLATE_ARG% %CACHE_RAM_ARG% %SPEC_ARG% %LORA_ARG%
exit /b %errorlevel%

:load_config
rem config.env used to be copied to home\agent\config.cmd and called. That made
rem the config file *code*: 2026-08-19 measurement showed a value containing &
rem runs the rest as a command, and %%VAR%% / !VAR! vanish from values. Python
rem parses it now against an allowed-key list and a value character set, and
rem writes a sanitized .cmd holding nothing but verified set statements. That
rem sanitized file is what gets called.
if not exist "%ROOT%config.env" exit /b 0
if not exist "%ROOT%home\agent" mkdir "%ROOT%home\agent"
%BOOTSTRAP_PY% "%ROOT%tools\config_parse.py" --config "%ROOT%config.env" --out "%ROOT%home\agent\config.cmd"
if errorlevel 1 (
  echo [FAIL] config.env was refused - fix the lines listed above
  exit /b 1
)
call "%ROOT%home\agent\config.cmd"
exit /b 0

:resolve_bootstrap_python
rem Reading config.env now needs a Python before the config is read, so this
rem resolver cannot consult PYTHON_CMD - that value lives in the config. It is
rem deliberately separate from :resolve_python for that reason. The bundled
rem embedded distribution comes first: with no admin rights and no network, a
rem missing system Python or a Microsoft Store app-execution-alias stub leaves
rem no way to recover.
if defined BOOTSTRAP_PY goto :eof
if not exist "%ROOT%bin\python\python.exe" goto :resolve_bootstrap_system
set "BOOTSTRAP_PY="%ROOT%bin\python\python.exe""
goto :eof
:resolve_bootstrap_system
py -3.12 -c "import sys" >nul 2>&1
if not errorlevel 1 (
  set "BOOTSTRAP_PY=py -3.12"
  goto :eof
)
python -c "import sys" >nul 2>&1
if not errorlevel 1 (
  set "BOOTSTRAP_PY=python"
  goto :eof
)
echo [FAIL] no Python found - config.env cannot be parsed without one.
echo        Restore the bundled bin\python\python.exe, or install Python 3.12.
exit /b 1
