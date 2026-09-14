# AI Infrastructure Bottleneck — D5 Preview

버전 **0.3.0-d5.5**. 공개자료 취득 → 근거 검토 → 보고서 → 반복 추적 → 대시보드·지도를 연결한 연구 시험판입니다. 실제 Work에서의 연구 흐름·품질 인수를 앞둔 버전입니다.

## Work에서 시작

기존 [GitHub 저장소](https://github.com/jh-folio/AI-Infrastructure-Bottleneck) 링크로 설치 또는 갱신하고, 실행 환경에서 manifest 버전을 확인합니다. 비공개 저장소의 기존 접근 권한은 필요합니다. 설치 위치나 장기 저장 경로는 고정하지 않습니다.

> tests/D5_WORK_HANDOFF.md에 따라 버전을 확인하고 기존 상태를 보존하며 실제 심층 리서치·보고서·대시보드·후속 갱신을 통합 점검해줘.

[통합 검증 안내](tests/D5_WORK_HANDOFF.md), [상세 실행 계약](plugin/workflows/RUNTIME_GUIDE.md)을 제공합니다. 통합 검증 요청에는 안내 문서의 공급망 병목 위치·심화도·추세 과제를 사용합니다. 사용자가 지정한 다른 범위가 있으면 우선합니다. 이전 개인 연구나 점수·순위는 기본값에 없습니다.

## 포함 기능

- 5개 워크플로우: 설정, 조사/보고서, 반복 수집/갱신, 감사/설명, 대시보드/지도
- SEC submissions/companyfacts, yfinance 가격, 공개 IR HTML/PDF 취득과 실패 이력
- 단위·공시 vintage를 보존한 fact 후보, 문단/페이지/JSON Pointer 재조회와 질문별 제한 packet
- 범위가 일치하는 채택/보류/정정 근거, 반증·경쟁 가설을 포함한 판단과 사건 기록
- 검토된 분야 간 종합 문장·공급망 위치/심화도/추세 비교표·미검토 범위·추적 목록을 고정 snapshot에서 생성, 이전 보고서 대비 변경 요약
- Scoring 3.1 산술·적격성·Tier/binding 구분, 버전별 엔진 재현·snapshot·인용 초안
- UUID/해시/참조 검사, 중복 요청 방지, 비파괴 backup/restore

코드는 Python 3.10+와 표준 SQLite를 사용합니다. 가격/PDF는 선택 의존성을 설치합니다:

```text
python -m pip install -r requirements-optional.txt
python -X utf8 -m unittest discover -s tests -p "test_*.py" -v
```

SEC는 실제 식별/연락처를 담은 SEC_USER_AGENT 환경 설정이 필요합니다. 키나 연락처는 패키지/보고서에 넣지 않습니다. 웹 검색은 API 밖 원출처 발견·반증·심층 교차검증에 계속 사용합니다. RSS는 기본 경로에서 제외합니다.

## 검증 경계

로컬에서는 합성 행동 검사 및 IR HTML/PDF·yfinance 표본 취득을 확인했습니다. D3 SEC companyfacts는 로컬 식별 설정이 없어 설정 필요로 기록했습니다. 이전 D1의 Work SEC submissions 및 새 세션 저장 성공은 사용자의 화면에서 보고된 별도 증거입니다.

반복 수집과 중단 재개, 심층 리서치 자료 인계/반환 등록, 읽기 전용 HTML 대시보드와 지도를 포함합니다. 실제 심층 리서치는 호스트의 기능으로 실행하며 코드가 대신 호출하지 않습니다. 실제 예약 등록·실행, Work의 HTML 표시·재접근, 연구 내용/가독성의 사용자 인수는 별도입니다. 자동 경제성/가치평가나 baseline 승인을 제공하지 않습니다.
