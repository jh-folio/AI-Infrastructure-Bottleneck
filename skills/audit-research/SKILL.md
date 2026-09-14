---
name: audit-research
description: 연구 기록의 해시·참조·계산 이력·인용과 범위 보존을 검토하고 기존 판단을 설명한다. 자동 구조 검사와 독립 해석 검토를 구분한다.
---

# 기록 감사와 설명

[공통 규칙](../../plugin/methodology/research_rules.md), [실행 계약](../../plugin/workflows/RUNTIME_GUIDE.md), 점수 감사면 [계산 기준](../../plugin/methodology/scoring_v31_reference.md)을 적용한다.

사용자 scope/프로젝트 ID와 audit 대상 snapshot을 확인한다. audit는 hash/참조/산술 검사를 수행하며 감사 snapshot을 저장한다. 엄격한 읽기 전용 요청이면 record/read-document를 사용하고 snapshot/audit/backup 쓰기 여부를 사전에 구분한다. replay는 등록된 당시 엔진과 hash 일치 시만 재현한다. 연구 DB에 담긴 source를 코드로 실행하지 않는다.

지지·반증과 원문 위치, 독립 계열, 공시/관측/기준일, factor endpoint·기제, 요약의 조건 보존을 사람이 확인할 수 있게 제시한다. 관련 scope 밖 값·혼합 통화/분기·사후 정보·보류 근거 재사용을 검사한다. 판단 설명은 새 연구 없이 저장 원문부터 답한다.

작성자 자동 검사와 별도 독립 검토, baseline 승인, 실제 Work 실행을 나눠 보고한다. 수정 요청이 있으면 기존 evidence/assessment를 덮지 않고 정정 원인과 supersedes를 남긴다. 동일 입력 재계산과 산업 변화 해석을 구분한다.
