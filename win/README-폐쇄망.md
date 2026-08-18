# 폐쇄망 실행 안내

## 전제
- 관리자 권한 없이 압축 해제만으로 동작한다.
- 이 번들은 한 사용자 계정 전용이다. `home\agent` 에 세션과 툴 출력이 쌓이고 여기에는 작업한 소스 내용이 남는다.

## 순서
1. 번들을 `C:\pi_agent` 로 복사한다.
2. `config.env.example` 을 `config.env` 로 복사하고 `MODEL_FILE`, `MODEL_ALIAS` 를 채운다.
3. `nvidia-smi` 로 GPU별 여유 VRAM을 보고 `GPU_TENSOR_SPLIT` 을 정한다. 비워두면 기본 분배를 쓴다. `1,1,1` 로 고정하지 않는다.
4. 창 하나에서 `start-llama.bat` 을 실행한다. 이 창은 서버가 사는 곳이므로 닫지 않는다.
5. 다른 창에서 `start-pi.bat` 을 실행한다. 모델이 준비되기 전에는 Pi가 뜨지 않는다.
6. `verify-offline.bat` 을 실행해 `evidence\` 에 증거를 남긴다.

## GPU가 안 잡힐 때
- `nvidia-smi` 의 드라이버가 551.61 미만이면 CUDA 12.4 빌드가 동작하지 않는다.
- `config.env` 의 `LLAMA_BACKEND` 를 `vulkan` 또는 `cpu` 로 바꿔 원인을 좁힌다. CPU는 진단용이며 30B 모델 실사용 속도가 나오지 않는다.
- `MSVCP140.dll` 관련 오류가 나면 `bin\llama-cuda` 안의 app-local DLL이 지워졌는지 확인한다.

## 하지 않는 것
- `pi install` 로 패키지나 확장을 설치하지 않는다. npm이 필요하고 폐쇄망에서는 동작하지 않는다.
- 모델을 새로 내려받지 않는다. 반입한 GGUF만 쓴다.
- `--host` 를 `127.0.0.1` 외의 값으로 바꾸지 않는다.
