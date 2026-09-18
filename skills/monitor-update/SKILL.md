---
name: monitor-update
description: 기존 연구를 새 자료로 갱신하거나 저장된 내용으로 주간·월간 요약을 만든다. 미완료 연구 재개와 새 기간 갱신을 구분하며 예약은 명시적 요청과 실제 호스트 도구로 연결한다. 판단 이유 설명은 audit-research로 연결한다.
---

# 갱신·브리프·기존 판단 설명

미완료 최초 연구의 자동 후속 실행은 [병렬 조사·자동 재개](../../plugin/workflows/AUTOMATIC_RESEARCH.md)를 따른다. 정기 갱신과 최초 연구 완료까지의 자동 재개를 구분하고, 기존 coordination 상태가 paused/completed이면 새 작업을 시작하지 않는다.

[사용자 워크플로우](../../plugin/workflows/USER_WORKFLOW.md)를 먼저 적용한다. 새 자료 갱신은 workflow intent=update, 기존 내용만 요약은 brief, 이어서 조사는 resume다. 현재 실행일/사용자가 지정한 새 기준일은 as_of_date에 전달하고 좁은 갱신은 scope_mode=focused로 유지한다. 같은 기간의 미완료 최초 연구는 build-baseline으로 바로 이어간다. 판단 이유 설명은 audit-research로 인계한다. 새 기간은 이전 원장·보고서를 남기고 새 campaign에서 비교한다. 반환된 다음 단계를 같은 실행에서 수행한다.

[제품 목적과 기본 실행 계약](../../plugin/methodology/PRODUCT_CONTRACT.md)을 먼저 적용한다.

[규칙](../../plugin/methodology/research_rules.md)과 [실행 계약](../../plugin/workflows/RUNTIME_GUIDE.md)의 D4/D5 절을 따른다. monitor-plan으로 수집 경로를 등록하고 monitor-run에 회차별 안정된 요청 ID를 준다. 중단 재개는 같은 ID, 실패 완료 뒤 재수집과 새 회차는 새 ID다. 수집 완료는 새 판단 채택이나 산업 변화 판정이 아니다.

설명 요청은 list/record/read-document에서 기존 snapshot의 이유·scope·반증·미확인을 답하고 새로운 연구를 자동 시작하지 않는다. 갱신 요청은 기존 ID/상태를 확인하고 마지막 task/next_actions부터 자료를 재취득한다. 동일 raw와 수집 실패를 구별한다. 새 주장/정정은 adopt의 새 request_id/supersedes로 남긴다.

공급망 위치별로 무엇이 얼마나 심화/완화됐는지 기존 판단과 비교한다. 변화 판단은 정합적인 두 시점의 근거가 있어야 하며 없으면 추세 미확인을 명시한다. 계획·수정·실현/정상 완료를 event와 judgment로 검토하고 판단 유지·수정·기각·미확인을 기록한다. 단순 자료 회복·정정·범위 변경을 실제 산업 변화로 표현하지 않는다. 재계산은 동일 scope와 버전의 채택 입력에서 수행한다. 영향 없는 대상을 일괄 재평가하지 않는다.

주간 요청은 report mode=weekly_brief에 선택한 event_ids/judgment_ids/assessment_ids를 넘겨 브리프를 만들고 인용/미확인/다음 관측을 검토한다. 최신 backup과 snapshot/버전/다음 행동을 남긴다. 예약 요청이 있으면 schedule-packet을 바탕으로 실제 호스트 도구에 주기·시간대·상태 경로·회차 ID를 연결한다. packet 자체는 등록이 아니며 실제 예약 ID/결과 없이 활성화로 표시하지 않는다. 필요한 변경 근거를 검토한 뒤 새 보고서와 화면을 만들도록 예약 지시문에 연결한다. 수집 오류를 점수 변경이나 변화 없음으로 바꾸지 않는다.

공급망 종합 갱신은 현재 judgment의 comparison에 이전 판단과 새 관측 근거·변경 원인을 연결하고 synthesize에 previous_report_id를 전달한다. 추가/제외된 구간과 범위 변경을 병목 심화/해소로 표현하지 않는다. 합성 결과의 변경 요약과 원문 근거를 검토한 뒤 export-report/backup한다. 개별 사건만의 brief는 기존 report mode=weekly_brief를 사용한다.


미완료 최초 연구 campaign이 있으면 업데이트 전에 research-next로 남은 질문을 확인한다. '이어서 조사' 요청은 기존 checkpoint에서 재개하며 새 원장을 만들거나 미완료 baseline을 완료로 간주하지 않는다. 새 근거가 중요한 공백을 열면 기존 질문에 시도와 다음 행동을 덧붙인다. 세부 절차는 [연구 실행과 재개](../../plugin/workflows/RESEARCH_EXECUTION.md)를 따른다. 좁은 변경 확인 요청에는 그 범위를 우선한다.


조사 중 독립적인 새 범위가 발견되거나 노드 분할/통합이 필요하면 연구 실행 계약의 node-change를 사용한다. 기본87개 정의와 과거 이력은 보존하고 새 ID·범위·이유·적용일·이전/이후 대응을 기록한다. 첫 실행 전수 조사 의무는 추가·분할·통합 이후의 유효 노드 전체에 적용된다. 기존 범위를 몰래 제외하거나 점수/추세를 새 노드에 복사하지 않는다.

조회/재개나 실제 조사 시 [효율적인 조사](../../plugin/workflows/EFFICIENT_RESEARCH.md)를 적용한다. 새 연구는 기본78개/맥락10개이며 기존 campaign은 저장된 범위를 유지한다. 전체 원장을 반복 출력하지 않고 compact 조회·변경분 저장·묶음 인계를 사용한다.
