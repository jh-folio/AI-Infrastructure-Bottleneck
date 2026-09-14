# AI Infrastructure Bottleneck — D3 Preview

버전 **0.2.0-d3.4**. 공개자료 취득 → 원문 위치 조회 → 근거 검토 → 판단/계산 → 인용 초안을 연결한 연구 시험판입니다. 실제 Work에서의 연구 흐름·품질 인수를 앞둔 버전입니다.

## Work에서 시작

기존 [GitHub 저장소](https://github.com/jh-folio/AI-Infrastructure-Bottleneck) 링크로 설치 또는 갱신하고, 실행 환경에서 manifest 버전을 확인합니다. 비공개 저장소의 기존 접근 권한은 필요합니다. 설치 위치나 장기 저장 경로는 고정하지 않습니다.

> D3 실제 자료·연구 흐름 검증을 진행해줘. tests/D3_WORK_HANDOFF.md를 읽고 버전과 실행 환경부터 확인해줘. 기존 D1 DB는 보존하고 새 연구 상태를 사용해줘.

[실제 검증 안내](tests/D3_WORK_HANDOFF.md), [상세 실행 계약](plugin/workflows/RUNTIME_GUIDE.md)을 제공합니다. D3 검증 요청에는 안내 문서의 공급망 병목 위치·심화도·추세 과제를 사용합니다. 사용자가 지정한 다른 범위가 있으면 우선합니다. 이전 개인 연구나 점수·순위는 기본값에 없습니다.

## 포함 기능

- 5개 워크플로우: 설정, 조사/보고서, 수동 갱신/브리프, 감사/설명, 화면 요청 안내
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

D3는 자동 예약, interactive dashboard/객체 지도, 자동 경제성/가치평가, 전체 공시 역사 수집, OCR을 포함하지 않습니다. 최종 보고서의 심층 리서치는 host에 실제 제공된 skill/tool을 사용해야 합니다. CLI가 생성하는 인용 초안은 심층 리서치 실행 자체가 아닙니다. 연구의 폭·깊이 개선과 Work 재접근은 사용자가 실제 실행하여 판단합니다. 정식 baseline/외부 사용자 출시 승인은 별도입니다.

[방법 규칙](plugin/methodology/research_rules.md)과 [Scoring 발췌](plugin/methodology/scoring_v31_reference.md)를 패키지 안에 포함합니다. D1 호환 probe/tests도 보존합니다. 개인 DB·원장·실제 수집 원문·보고서·비밀정보는 배포하지 않습니다. UUID 검사는 플랫폼 접근 제어를 대신하지 않습니다.

라이선스는 [LICENSE](LICENSE)를 따르며 이 시험판은 오픈소스 라이선스를 새로 부여하지 않습니다.
