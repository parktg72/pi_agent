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
  `vulkan`으로 바꾸지 마라 — 금지다.** `bin\llama-vulkan`은 이 아키텍처의
  `ggml_ssm_conv`/`ggml_ssm_scan`을 구현하지 않았고, 조용히 CPU로 폴백하면서
  GPU↔CPU 경계에서 상태가 손상된다(상류 이슈 `ggml-org/llama.cpp#19957`,
  2026-02-27 open, 미해결). 결과는 손상된 출력이거나 `vk::DeviceLostError`다.
  `bin\llama-vulkan` 자체는 다른 모델에는 유효하므로 번들에서 빼지 않지만,
  이 모델에는 쓰지 않는다. `cpu`로 바꿔 원인을 좁힌다 — 느리지만 정확하다.
  30B 모델 실사용 속도가 나오지 않으므로 CPU는 진단용이다.
- `MSVCP140.dll` 관련 오류가 나면 `bin\llama-cuda` 안의 app-local DLL이 지워졌는지 확인한다.

## 하지 않는 것
- `pi install` 로 패키지나 확장을 설치하지 않는다. npm이 필요하고 폐쇄망에서는 동작하지 않는다.
- 모델을 새로 내려받지 않는다. 반입한 GGUF만 쓴다.
- `--host` 를 `127.0.0.1` 외의 값으로 바꾸지 않는다.
