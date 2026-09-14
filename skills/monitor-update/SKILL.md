---
name: monitor-update
description: 기존 연구에 새 자료·사건을 반영하고 수동 주간 브리프를 작성한다. 기존 판단 설명 요청은 재조사 없이 저장된 근거부터 확인한다.
---

# 수동 갱신·브리프·기존 판단 설명

[제품 목적과 기본 실행 계약](../../plugin/methodology/PRODUCT_CONTRACT.md)을 먼저 적용한다.

[규칙](../../plugin/methodology/research_rules.md)과 [실행 계약](../../plugin/workflows/RUNTIME_GUIDE.md)을 따른다. D3에는 예약 실행이 없으므로 자동 모니터링이 켜졌다고 말하지 않는다.

설명 요청은 list/record/read-document에서 기존 snapshot의 이유·scope·반증·미확인을 답하고 새로운 연구를 자동 시작하지 않는다. 갱신 요청은 기존 ID/상태를 확인하고 마지막 task/next_actions부터 자료를 재취득한다. 동일 raw와 수집 실패를 구별한다. 새 주장/정정은 adopt의 새 request_id/supersedes로 남긴다.

공급망 위치별로 무엇이 얼마나 심화/완화됐는지 기존 판단과 비교한다. 변화 판단은 정합적인 두 시점의 근거가 있어야 하며 없으면 추세 미확인을 명시한다. 계획·수정·실현/정상 완료를 event와 judgment로 검토하고 판단 유지·수정·기각·미확인을 기록한다. 단순 자료 회복·정정·범위 변경을 실제 산업 변화로 표현하지 않는다. 재계산은 동일 scope와 버전의 채택 입력에서 수행한다. 영향 없는 대상을 일괄 재평가하지 않는다.

주간 요청은 report mode=weekly_brief에 선택한 event_ids/judgment_ids/assessment_ids를 넘겨 수동 브리프를 만들고 인용/미확인/다음 관측을 검토한다. 최신 backup과 snapshot/버전/다음 행동을 남긴다. 예약과 장기 자동 재접근 인수는 D4다.
