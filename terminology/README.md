# 의료 용어 체계 덤프 슬롯

| 슬롯 | 내용 |
|---|---|
| `kcd8/` | KCD-8 한국표준질병·사인분류 |
| `icd10/` | ICD-10 (WHO) |
| `atc/` | ATC (WHO) |
| `umls/` | UMLS Metathesaurus (NLM, 라이선스 필요) |
| `omop/` | OMOP Standardized Vocabularies (OHDSI Athena) |
| `mesh/` | MeSH RDF (NLM) — 2026-09-23 원본 반입 |
| `doid/` | Disease Ontology (CC0) — 2026-09-23 원본 반입 |
| `mondo/` | MONDO (CC BY 4.0) — 2026-09-23 원본 반입 |
| `hira_ingredients/` | 심평원 약가마스터 의약품주성분(공공누리 1유형) — 2026-09-23 원본 반입 |
| `hira_atc_mapping/` | 심평원 ATC코드 매핑 목록(공공누리 3유형, 변경금지) — 2026-09-23 원본 반입 |

**앞의 다섯 슬롯(kcd8·icd10·atc·umls·omop)은 비어 있다**(라이선스·계정이 필요해 사용자가 제공한다). 뒤의 다섯 슬롯에는 원본 파일이 스테이징 PC에서 들어가 있을 수 있다 — 들어 있어도 `slot.json`의 검토가 `approved`가 되기 전에는 `check-terminology.bat`이 incomplete로 보고한다. 원본 파일은 git에 없다.
RDF 저장소 엔진 pyoxigraph는 `install-kg.bat`이 `home\kg\venv`에 설치한다. 파서·적재기·질의 도구는 원본과 형식 명세를 받은 뒤 만든다.
각 슬롯의 README를 따른다. 근거: 개발 트리 `tasks/pi-agent-terminology/artifacts/consensus.md`.
