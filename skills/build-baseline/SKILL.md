---
name: build-baseline
description: AI 공급망의 최초·심층 연구, 특정 질문의 자료 보강, 인용 보고서 작성을 수행한다. API와 원문 재조회로 자료를 모으고 필요한 웹 교차검증을 연결한다.
---

# 최초 연구·질문 보강·보고서

[공통 판단 규칙](../../plugin/methodology/research_rules.md)과 [실행 계약](../../plugin/workflows/RUNTIME_GUIDE.md)을 읽는다. 계산 직전에만 [Scoring 3.1](../../plugin/methodology/scoring_v31_reference.md)을 읽는다.

요청이 좁은 질문이면 해당 대상의 원문·판단만 보강하고 답한다. 최초/심층 조사·최종 보고서면 실제 환경에서 제공되는 심층 리서치 skill/tool을 발견하고 그 지침을 적용한다. 사용자 제외 지시를 우선한다. 없는 호출·작업 ID·실행 성공을 만들지 않는다. 연결되지 않으면 가능한 자료·판단·인용 초안을 먼저 준비하고 연결 미검증을 표시한다.

1. 사용자 scope와 기준일, 대상별 수요·가용 공급·미충족·일정 영향·반증 질문을 정한다. 과거 계획/수정/실현과 정상 완료 표본까지 탐색 계획에 포함한다.
2. SEC submissions/companyfacts, yfinance 가격, 등록 IR 공개 원문을 취득한다. filings/facts/search/read-document로 기간·단위와 앞뒤 문맥을 확인한다. 웹은 새 원출처 발견·규격별 설명·반증·독립 교차검증에 사용한다. 전체 JSON이나 원문을 대화에 반복 덤프하지 않는다.
3. 질문별 packet에서 검토한 claim을 adopt하고 판단을 judgment로 기록한다. 독립 계열·반대 문맥·비채택·Unknown·다음 관측을 보존한다. 근거가 없으면 task를 남긴다. 검토된 factor만 assess한다.
4. 실제 심층 리서치에 목적·scope·snapshot/원문 위치·규칙·지지/반증·보류·공백을 인계한다. 결과를 회수해 원문/범위/주장을 재검토하고 새 근거는 같은 채택 절차를 거친다. 심층 리서치 도구 접근이 불가하면 인계 준비까지만 기록한다.
5. report/export-report로 검토 가능한 인용 초안을 만든다. 본문·요약·표의 범위와 조건이 동일한지 확인하고 audit/backup한다. 독립 검토와 사용자 baseline 승인은 실제 수행 때만 기록한다. 산업경제성/개별 증권 판단은 요청 범위인 경우 물리적 한계를 인계하여 별도로 다룬다.
