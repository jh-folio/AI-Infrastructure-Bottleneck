---
name: build-baseline
description: AI 공급망의 최초·심층 연구, 특정 질문의 자료 보강, 인용 보고서 작성을 수행한다. API와 원문 재조회로 자료를 모으고 필요한 웹 교차검증을 연결한다.
---

# 최초 연구·질문 보강·보고서

[제품 목적과 기본 실행 계약](../../plugin/methodology/PRODUCT_CONTRACT.md)을 먼저 적용한다.

[공통 판단 규칙](../../plugin/methodology/research_rules.md)과 [실행 계약](../../plugin/workflows/RUNTIME_GUIDE.md)을 읽는다. 계산 직전에만 [Scoring 3.1](../../plugin/methodology/scoring_v31_reference.md)을 읽는다.

요청이 좁은 질문이면 해당 대상의 원문·판단만 보강하고 답한다. 최초/심층 조사·최종 보고서면 실제 환경에서 제공되는 심층 리서치 skill/tool을 발견하고 그 지침을 적용한다. 사용자 제외 지시를 우선한다. 없는 호출·작업 ID·실행 성공을 만들지 않는다. 연결되지 않으면 가능한 자료·판단·인용 초안을 먼저 준비하고 연결 미검증을 표시한다.

1. 별도 범위를 지정하지 않은 최초 연구는 공급망 전반의 탐색→근거로 선정한 후보 심층 검토→분야 간 종합으로 진행한다. 검토/미검토 구간과 대상 선정 이유를 남기고, 사용자 scope와 기준일, 대상별 수요·가용 공급·미충족·일정 영향·반증 질문을 정한다. 과거 계획/수정/실현과 정상 완료 표본까지 탐색 계획에 포함한다.
2. 병목 위치·부족/지속성/가동 영향·두 시점 변화를 설명할 원출처를 선정하여 SEC submissions/companyfacts, 등록 IR·공개자료를 취득한다. yfinance 가격은 관련 후속 질문이나 별도 기술 검사에 필요한 경우 사용한다. filings/facts/search/read-document로 기간·단위와 앞뒤 문맥을 확인한다. 웹은 새 원출처 발견·규격별 설명·반증·독립 교차검증에 사용한다. 전체 JSON이나 원문을 대화에 반복 덤프하지 않는다.
3. 질문별 packet에서 검토한 claim을 adopt하고 판단을 judgment로 기록한다. 독립 계열·반대 문맥·비채택·Unknown·다음 관측을 보존한다. 근거가 없으면 task를 남긴다. 검토된 factor만 assess한다.
4. 실제 심층 리서치에 목적·scope·snapshot/원문 위치·규칙·지지/반증·보류·공백을 인계한다. 결과를 회수해 원문/범위/주장을 재검토하고 새 근거는 같은 채택 절차를 거친다. 심층 리서치 도구 접근이 불가하면 인계 준비까지만 기록한다.
5. judgment에 검토한 bottleneck(강도·지속성·가동 영향)과 필요한 comparison을 기록한다. 둘 이상의 분야 판단을 연결하는 synthesis_claims에는 결론·근거 판단 IDs·reasoning·limitations를 작성한다. runtime guide의 synthesize로 핵심 요약·위치별 비교·미검토 범위·추세·반증·추적 항목을 같은 snapshot에서 생성하고 export-report한다. 원문/표/요약의 조건과 반증이 일치하는지 검토한 뒤 audit/backup한다. 코드는 종합 결론을 창작하지 않으므로 검토된 분야 간 판단을 입력해야 한다. 독립 검토와 baseline 승인은 실제 수행 때만 기록한다.
