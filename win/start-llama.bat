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

if not defined LLAMA_BACKEND set "LLAMA_BACKEND=cuda"
if not defined LLAMA_PORT set "LLAMA_PORT=8080"
if not defined LLAMA_CTX set "LLAMA_CTX=32768"

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
rem cpu means loading a 22.4GB (Q6_K) model into system RAM. On a machine short of RAM
rem or pagefile that thrashes for a long time instead of failing, so it must be
rem chosen on purpose, never by accident.
if /I "%LLAMA_BACKEND%"=="cpu" if not "%ALLOW_CPU_DIAGNOSTIC%"=="1" (
  echo [FAIL] LLAMA_BACKEND=cpu needs an explicit opt-in.
  echo        This loads a 22.4GB Q6_K model into system RAM. A 27B dense model does
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

rem Tuning for 3x GTX 1080 Ti and 128GB RAM, 2026-09-17. Evidence for each line
rem is llama.cpp b11010 source; see config.env.example for the operator view.
rem Flash attention is left on auto, on purpose. ggml-cuda/fattn.cu picks the
rem tile/vec kernels on GPUs without tensor cores, so auto resolves to enabled on
rem Pascal. auto probes the device first (src/llama-context.cpp) and logs
rem "flash_attn not supported, set to disabled" if it cannot run there; forcing
rem on skips that probe and lets the op land on the CPU instead. A quantized KV
rem cache turns auto into enabled by itself.
rem -fit off: this script owns -ngl, -ts and -c. With -ngl set, --fit (default
rem on) gives up every start and prints an abort line operators read as a
rem failure (common/fit.cpp "n_gpu_layers already set by user").
if not defined LLAMA_KV_TYPE set "LLAMA_KV_TYPE=f16"

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

echo [info] starting %MODEL_FILE% as %MODEL_ALIAS% on the %LLAMA_BACKEND% backend
echo [info] ctx %LLAMA_CTX%, kv cache %LLAMA_KV_TYPE%, flash attention auto
if defined LORA_FILE echo [info] LoRA adapter lora\%LORA_FILE% at scale %LORA_SCALE%
"%LLAMA_DIR%\llama-server.exe" ^
  -m "%ROOT%models\%MODEL_FILE%" ^
  --alias "%MODEL_ALIAS%" ^
  --jinja ^
  --host 127.0.0.1 ^
  --port %LLAMA_PORT% ^
  -ngl 999 ^
  -c %LLAMA_CTX% ^
  --parallel 1 ^
  -sm layer %TS_ARG% %MMPROJ_ARG% ^
  -fa auto -fit off -ctk %LLAMA_KV_TYPE% -ctv %LLAMA_KV_TYPE% %CACHE_RAM_ARG% %SPEC_ARG% %LORA_ARG%
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
