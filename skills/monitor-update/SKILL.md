---
name: monitor-update
description: 기존 연구의 공개자료를 반복 수집하고 변경 근거 검토·보고서 갱신을 연결한다. 기존 판단 설명은 저장 근거를 읽고, 예약은 명시적 요청과 실제 호스트 도구로 연결한다.
---

# 수동 갱신·브리프·기존 판단 설명

[제품 목적과 기본 실행 계약](../../plugin/methodology/PRODUCT_CONTRACT.md)을 먼저 적용한다.

[규칙](../../plugin/methodology/research_rules.md)과 [실행 계약](../../plugin/workflows/RUNTIME_GUIDE.md)의 D4/D5 절을 따른다. monitor-plan으로 수집 경로를 등록하고 monitor-run에 회차별 안정된 요청 ID를 준다. 중단 재개는 같은 ID, 실패 완료 뒤 재수집과 새 회차는 새 ID다. 수집 완료는 새 판단 채택이나 산업 변화 판정이 아니다.

설명 요청은 list/record/read-document에서 기존 snapshot의 이유·scope·반증·미확인을 답하고 새로운 연구를 자동 시작하지 않는다. 갱신 요청은 기존 ID/상태를 확인하고 마지막 task/next_actions부터 자료를 재취득한다. 동일 raw와 수집 실패를 구별한다. 새 주장/정정은 adopt의 새 request_id/supersedes로 남긴다.

공급망 위치별로 무엇이 얼마나 심화/완화됐는지 기존 판단과 비교한다. 변화 판단은 정합적인 두 시점의 근거가 있어야 하며 없으면 추세 미확인을 명시한다. 계획·수정·실현/정상 완료를 event와 judgment로 검토하고 판단 유지·수정·기각·미확인을 기록한다. 단순 자료 회복·정정·범위 변경을 실제 산업 변화로 표현하지 않는다. 재계산은 동일 scope와 버전의 채택 입력에서 수행한다. 영향 없는 대상을 일괄 재평가하지 않는다.

주간 요청은 report mode=weekly_brief에 선택한 event_ids/judgment_ids/assessment_ids를 넘겨 브리프를 만들고 인용/미확인/다음 관측을 검토한다. 최신 backup과 snapshot/버전/다음 행동을 남긴다. 예약 요청이 있으면 schedule-packet을 바탕으로 실제 호스트 도구에 주기·시간대·상태 경로·회차 ID를 연결한다. packet 자체는 등록이 아니며 실제 예약 ID/결과 없이 활성화로 표시하지 않는다. 필요한 변경 근거를 검토한 뒤 새 보고서와 화면을 만들도록 예약 지시문에 연결한다. 수집 오류를 점수 변경이나 변화 없음으로 바꾸지 않는다.

공급망 종합 갱신은 현재 judgment의 comparison에 이전 판단과 새 관측 근거·변경 원인을 연결하고 synthesize에 previous_report_id를 전달한다. 추가/제외된 구간과 범위 변경을 병목 심화/해소로 표현하지 않는다. 합성 결과의 변경 요약과 원문 근거를 검토한 뒤 export-report/backup한다. 개별 사건만의 brief는 기존 report mode=weekly_brief를 사용한다.
