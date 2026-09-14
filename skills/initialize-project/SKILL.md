---
name: initialize-project
description: 연구 프로젝트를 시작하거나 기존 상태에 다시 접근하고 저장·복구 가능성을 확인한다. D1 합성 저장 점검도 이 진입점에서 수행한다.
---

# 프로젝트 시작과 재접근

[제품 목적과 기본 실행 계약](../../plugin/methodology/PRODUCT_CONTRACT.md)을 먼저 적용한다.

[공통 규칙](../../plugin/methodology/research_rules.md)과 [실행 계약](../../plugin/workflows/RUNTIME_GUIDE.md)을 읽는다. 사용자가 D1 시험을 지정하면 패키지의 tests/D1_WORK_HANDOFF.md 또는 tests/D1_SOURCE_HANDOFF.md를 따른다.

현재 환경의 Python/SQLite/선택 의존성을 capabilities로 확인한다. 기존 상태가 있으면 project.json의 실제 경로·ID로 snapshot/audit한다. 새 연구면 사용자가 지정한 범위를 우선한다. 별도 지정 없는 최초 연구는 AI 인프라 공급망 탐색을 기본으로 실행일 기준을 명시하고 시작하며, 임의의 기업 질문/종목을 요구하지 않는다. 비교·전망 기간은 적용 규칙과 자료 범위에 맞게 명시하고 새 연구 폴더만 init한다. 사용자가 이미 결정한 사항은 다시 승인받지 않는다. 설치 위치·수동 업로드·고정 cloud 경로를 가정하지 않는다.

반환 ID/경로/버전/첫 snapshot과 미지원 capability를 인계한다. 재접근 실패 시 초기화·재다운로드로 증거를 덮지 않는다. 기존 backup을 검증해 새 폴더로만 복구한다. 다음 최초 연구는 build-baseline, 기존 상태 갱신은 monitor-update로 연결한다. 기본값에 개인의 종목·점수·과거 결론·RSS를 넣지 않는다.
