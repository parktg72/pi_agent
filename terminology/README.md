# 의료 용어 체계 덤프 슬롯

| 슬롯 | 내용 |
|---|---|
| `kcd8/` | KCD-8 한국표준질병·사인분류 |
| `icd10/` | ICD-10 (WHO) |
| `atc/` | ATC (WHO) |
| `umls/` | UMLS Metathesaurus (NLM, 라이선스 필요) |
| `omop/` | OMOP Standardized Vocabularies (OHDSI Athena) |

**2026-09-23 현재 어느 슬롯에도 데이터가 없다.** 자리와 검사 도구(`tools/terminology_slots.py`, `check-terminology.bat`)만 있다.
RDF 저장소 엔진 pyoxigraph는 `install-kg.bat`이 `home\kg\venv`에 설치한다. 파서·적재기·질의 도구는 원본과 형식 명세를 받은 뒤 만든다.
각 슬롯의 README를 따른다. 근거: 개발 트리 `tasks/pi-agent-terminology/artifacts/consensus.md`.
