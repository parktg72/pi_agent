# KCD-8 — 한국표준질병·사인분류 제8차 개정

통계청이 고시하는 한국형 질병분류(ICD-10 기반, 국내 코드·명칭 추가). 통계청 통계분류포털 배포본.

## 주의

- ICD-10과 **같은 코드셋이 아니다.** ICD-10 슬롯과 섞지 않고, 두 체계 간 대응을 자동 동치로 만들지 않는다.
- 배포 파일 형식(엑셀 등)은 받은 뒤 확인한다. 이용 조건은 배포처 약관으로 확인한다.

## 넣는 법

1. 원본 파일을 `data/` 아래에 그대로 둔다(압축을 풀지 말지는 원본 형식에 따른다 - 파서가 생길 때 정한다).
2. `slot.example.json`을 `slot.json`으로 복사해 출처·라이선스 검토 칸을 채운다.
3. 번들 루트에서 `check-terminology.bat record kcd8` 로 파일 목록·크기·sha256을 기록한다.
   파일이 바뀌면 `review_status`가 `unreviewed`로 되돌아간다 - 다시 검토하고 `approved`로 쓴다.
4. `check-terminology.bat` 이 `[recorded]` 를 내면 기록·해시·검토가 맞다는 뜻이다. **적재 가능하다는 뜻은 아니다** -
   이 번들에는 아직 이 형식의 파서·적재기가 없다(원본과 형식 명세를 받은 뒤 만든다).

`data/`와 `slot.json`은 git에 올라가지 않고(공개 저장소) 매니페스트도 검사하지 않는다. 스테이징 PC에서 넣고
`record`하면 대상 PC의 `check-terminology.bat`이 전송 손상을 잡는다. 현장에서 직접 넣어도 번들 무결성 검사는 깨지지 않는다.
적재 결과(Oxigraph 저장소)는 `home\kg\terminology\oxigraph\` 에 만들 예정이다(아직 없음).

`slot.json` 필드: `source`, `distributor`(배포 기관), `release`(버전·릴리스), `acquired_on`(취득일), `source_url`,
`license_terms`(이용 조건 문서·URL), `review_status`(`unreviewed`|`approved`|`rejected`), `review_scope`(검토한 이용 범위),
`review_basis`(검토 근거), `files`(record가 채움). 이 도구는 법률 판정을 하지 않는다.
