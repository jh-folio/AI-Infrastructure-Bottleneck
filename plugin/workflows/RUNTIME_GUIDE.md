# D3 runtime 사용법

이 문서는 패키지 내부 실행 계약이다. Python 3.10 이상과 SQLite가 필요하다. SEC에는 환경의 SEC_USER_AGENT(앱 식별과 실제 연락처)가 필요하며 값은 보고서·Git에 출력하지 않는다. yfinance와 pypdf는 선택 의존성이다. `requirements-optional.txt` 설치 또는 host에서 제공된 동등 도구 사용 여부를 기록한다. 의존성/네트워크 실패를 성공으로 대체하지 않는다. SEC는 순차 요청하고 요청 사이 0.2초 이상 간격을 둔다. 403/429 우회나 무한 재시도는 하지 않는다.

아래 경로는 패키지 루트 기준이다. 개발 저장소에서도 같은 runtime 경로를 쓴다. 사용자의 실제 state_dir를 확인한다. `STATE`/`PROJECT_ID`는 설명용 placeholder이며 실행 전에 실제값으로 치환한다.

```text
python -X utf8 plugin/runtime/research_cli.py --action action.json
```

한 번에 한 action JSON 파일을 작성한다. 재시도에는 동일 request_id와 동일 내용을 사용한다. 내용이 달라지면 새 request_id와 supersedes를 사용한다. CLI의 종료 코드와 반환 status를 모두 검사한다. 수집 실패도 attempt 기록을 만들므로 종료 코드 0만으로 성공이라고 하지 않는다.

## 시작·복구

```json
{"op":"capabilities"}
```

```json
{"op":"init","state_dir":"STATE","config":{"name":"연구 이름","scope":"사용자가 정한 조사 범위","as_of_date":"2026-09-14","ir_hosts":["investor.example.org"]}}
```

새 비어 있는 위치만 사용한다. 반환 project_id와 state_dir를 인계 기록에 남긴다. 기존 프로젝트는 init하지 않고 `project.json`을 읽어 같은 ID로 `snapshot`/`audit`한다. 이미 승인된 범위의 일상 쓰기는 반복 승인 없이 진행한다. 아직 결정되지 않은 사용자 연구 scope·기준일만 확인한다. user env 접근 제어는 UUID 검사를 대신하지 않는다.

이후 action의 공통 필드:

```json
{"op":"snapshot","state_dir":"STATE","project_id":"PROJECT_ID"}
```

`backup`은 공통 필드에 새 `destination`을 더한다. `restore`는 `{op:"restore", backup_dir:"기존 백업", destination:"새 폴더"}` 형태의 유효 JSON으로 실행한다. 백업·복구는 기존 폴더를 덮어쓰지 않는다. 최신 state를 backup한 뒤 새 세션에서 재접근하고, 원래 연구 폴더와 복구 폴더를 동시에 쓰는 것은 피한다. D1 DB는 별도로 보존한다.

## 취득·읽기

각 행의 필드를 공통 action에 더한다.

| op | 추가 입력 | 결과/주의 |
|---|---|---|
| sec | cik, dataset: submissions 또는 companyfacts | raw SEC JSON 저장. 인증 키 불필요, 식별 User-Agent 필요 |
| ir | url, producer, published_at 선택 | 등록된 HTTPS 호스트, query 없는 공개 HTML/PDF/text. redirect/JS/OCR 미지원 |
| prices | ticker, start, end | end 제외, auto_adjust=false, actions=true. currency·timezone 누락은 partial |
| filings | document_id, as_of 선택, offset/limit | submissions recent 행·공시 링크. older_files는 추가 조사 대상이며 전역사 취득 완료 아님 |
| facts | document_id, taxonomy, tag, as_of 선택 | companyfacts의 개별 단위·기간·공시 vintage를 fact 후보로 저장. 합산·TTM·정규화 자동 계산 없음 |
| search | document_id, terms 배열, max_chars/offset 선택 | 매칭 문단과 앞뒤 문맥/페이지. 부족하면 next_offset과 continuation을 따라 읽음 |
| read-document | document_id, location, max_chars/char_offset 선택 | JSON Pointer 또는 block:1/page:1. 긴 원문은 next_char_offset으로 끝까지 조회 |
| packet | question, scope, terms, max_chars, document_ids 선택 | 한 질문의 제한된 원문 묶음. 생략 목록·실패 상태·snapshot 보존 |
| list | kind 선택, offset/limit | 작은 기록 목록. 자세한 내용은 record |
| record | id, include_artifacts 선택 | 불변 기록. 엔진 source는 명시 요청 때만 표시 |

SEC 단위·start/end·filed·form·fy/fp·frame·accn을 보존한다. 분기와 누적, stock/flow, 다른 taxonomy·통화를 검토 없이 합치지 않는다. yfinance에는 raw HTTP가 아니라 반환 행을 저장하며 현 시점 vendor 수정 이력이다. Close와 Adj Close·split·배당·환율·실제 주식수를 확인하기 전 가치평가를 파생하지 않는다.

IR PDF는 text 추출만으로 표·차트·각주/순서를 확정하지 않는다. 빈 페이지는 시각/OCR 검토가 필요하다. 웹 원출처 탐색으로 URL을 확보하고, 가용한 host 도구로 시각 검증한다. 런타임이 저장하지 못한 문서는 외부 조사 기록과 한계를 보존한다. 다른 도구 성공을 이 adapter 성공으로 표시하지 않는다.

## 검토와 판단

scope는 아래 8개 필드를 모두 명시한다. 기간이나 규격이 다르면 별도 scope로 만든다. 회사 전체 공시는 특정 제품 병목의 직접 근거가 자동으로 되지 않는다.

```json
{"node_id":"사용자 선택 ID","geography":"범위","product_spec":"규격","scenario":"base","horizon":"명시 기간","as_of_date":"2026-09-14","protocol_version":"3.1","methodology_version":"3.1"}
```

`adopt`의 data:

```json
{"document_id":"DOC_ID","location":"block:1","quote":"위치에서 그대로 확인한 원문","claim":"범위가 한정된 주장","scope":{},"nature":"observation","grade":"B","confidence":"Medium","confidence_reason":"검토 이유","producer_family":"검토한 독립 계열","original_producer_id":"원생산자","claim_family_id":"주장 계열","source_tier":1,"published_at":"2026-09-01","decision":"accepted","review_reason":"범위 적합성과 반대 문맥을 확인한 이유"}
```

빈 scope는 위 8필드로 채운다. nature는 observation/external_plan/external_forecast/inference/scenario. decision은 accepted/hold/rejected. source_tier는 1–5, grade는 A–D, confidence는 Low/Medium/High. 원문 날짜가 불명확하면 꾸며 채우지 말고 task로 남긴다. quote 검사는 literal 위치 검증이며 해석 승인 검증은 아니다. 정정에는 이전 evidence ID인 supersedes를 추가한다.

`judgment` data는 question, scope, conclusion, support_ids, counter_ids, alternatives(배열), unknowns, next_actions, confidence, reasoning을 포함한다. counter_ids가 비면 counter_search_limit에 탐색 범위와 한계를 쓴다. 폐기/보류/정정된 evidence나 다른 scope는 거부된다. 지지와 반증, 가용 공급과 수요 압력을 함께 인계한다.

`event` data는 scope, event_type, event_date, description, evidence_ids, materiality, review_reason. 계획/수정/실현 등 의미를 적고 필요한 tracking_id, target_date, target_value, unit, prior_event_id, actual_value 등은 확장 필드에 보존한다. `task`는 question, scope, unknowns, next_actions; 답이 없다는 사실과 다음 관측을 저장한다. `node`는 node_id, name, scope 및 확장 분류/참조 필드. 87개 ID는 [정체성 목록](../ontology/node_ids_v1.json)을 참고하되 기존 점수나 사용자의 기본 연구 대상을 생성하지 않는다.

## 계산·보고서

`assess` data는 scope, factors, confidence, confidence_reason, conflicts(resolved/bounded/unresolved), scope_coherent(boolean), change_cause와 선택 direction_evidence_ids/binding_*를 받는다. factors는 shortage/access/elasticity/build/demand/substitution/system_criticality/regulatory/concentration 9개 모두 필요하다.

근거 factor의 예: `{status:"EvidenceBounded",low:3,high:4,grade:"B",evidence_ids:["ID"],reason_low:"하한 anchor 이유",reason_high:"상한 anchor 이유",mechanism:"다른 factor와 구별되는 기제"}`를 유효 JSON으로 작성한다. Unknown/ResearchMissing/N/A는 `{status:"Unknown",low:null,high:null,gap_cause:"미확인 이유"}`처럼 기록한다. clock_start/end, time_definition, scope_exclusions, confidence, evidence_nature, shared_evidence_group 등 검토 필드를 필요에 맞게 포함한다. [수치 정책](../methodology/scoring_v31_reference.md)의 anchor를 반드시 읽고 모델이 검토한 입력만 넘긴다.

D3는 Unknown confidence 예외의 robustness 증명을 구현하지 않았으므로 Unknown 포함 시 Low만 허용한다. 임의로 근거를 바꿔 이를 통과시키지 않는다. binding_status 기본은 NotDemonstrated. 다른 상태는 binding_evidence_ids/binding_reason이 필요하고 ObservedBinding은 실제 관측 + project_id/required_path/schedule_impact/alternatives_and_float도 필요하다. 결과는 prepared이며 승인·확정 투자추천이 아니다.

`replay`는 assessment id로 등록된 당시 엔진 산술을 재현한다. `compare`의 old_id/new_id는 scope/방법/변경원인을 검사하고 자동 Momentum은 만들지 않는다. `audit`는 hash/참조/산술 검사이며 독립 해석 검토를 대체하지 않는다. 과거 엔진이 미등록이면 자료의 코드를 실행하지 말고 재현 미지원으로 보고한다.

`report`는 request_id, judgment_ids, assessment_ids 선택, event_ids 선택, mode(report/weekly_brief/answer), title을 받는다. 고정 snapshot의 검토 내용을 인용 Markdown 초안으로 저장한다. `export-report`에 id와 새 destination을 주어 파일로 내보낸다. 심층 리서치 결과·사람이 검토한 해석은 별도 단계이며 이 템플릿 렌더러 자체가 연구를 수행한 것은 아니다. 요약에서는 원문의 scope/조건·반증·미확인을 생략하지 않는다.


## 공급망 종합과 변경 요약 — 0.2.0-d3.3

일반 `report`는 개별 기록의 인용 초안이다. 최초 공급망 종합·분야 간 비교와 후속 변경 요약에는 **synthesize**를 사용한다. 새 schema나 연구 이관이 필요하지 않으며 결과는 기존 report record로 저장되고 export-report/backup/restore로 재조회한다.

먼저 연구자가 기존 judgment 입력에 다음 선택 필드를 추가한다. 자동으로 부족 점수나 추세 방향을 추론하는 필드가 아니다. 이미 검토한 판단을 구조화하는 단계다. 기존 judgment는 새 request_id로 추가 기록하여 원본을 보존한다.

```json
{
  "bottleneck": {
    "severity": "수요 대비 가용 공급의 부족을 근거 범위에서 설명",
    "persistence": null,
    "operational_impact": "관측된 일정 영향 또는 아직 확인하지 못한 부분"
  },
  "comparison": {
    "prior_judgment_id": "이전 판단 ID",
    "direction": "strengthening",
    "change_cause": "new_observation",
    "reason": "두 시점의 정합적인 근거로 검토한 변화 이유",
    "evidence_ids": ["현재 판단에 채택된 새 관측 근거 ID"]
  }
}
```

comparison이 없으면 추세 미확인이다. direction은 strengthening/easing/unchanged/unknown이고 change_cause는 new_observation/data_recovery/correction/scope_change/method_change다. 같은 node/지역/규격/시나리오/horizon/방법, 과거→현재 기준일, 현재 judgment에 연결된 observation 근거의 `observed_at`과 공개일이 이전 기준일 이후·현재 기준일 이내인지 확인한다. observed_at은 원문에서 확인한 실제 관측일 YYYY-MM-DD이며 수집일로 채우지 않는다. 과거 공시와 최신 정정 vintage의 차이를 산업 변화로 바꾸지 않는다.

조건이 부족하거나 계획/전망만 있으면 요청한 방향을 그대로 표시하지 않고 추세 미확인과 이유를 저장한다. 현재 자동 추세 gate는 실제 관측 비교를 지원하며 전망/계획 변경은 reasoning과 조건부 설명에 보존한다. 자연어 인과 판단 자체를 코드가 검증했다는 뜻은 아니다. 잘못된 범위·보류/정정 근거가 현재 판단에 연결되면 보고서 생성을 거부한다. 과거 정정된 근거는 역사 설명으로만 보존하고 새 관측 추세로 재사용하지 않는다.

선택 `assessment_id`로 같은 scope의 중앙 계산을 연결할 수 있다. 평가의 근거도 현재 판단의 지지/반증에 포함해야 한다. 숫자 총점과 Tier는 기존 scoreability를 통과한 평가만 표시한다. 미식별 정성 필드는 null/미확인으로 남기며 engine 산식·기존 결과는 변경하지 않는다.

synthesize action은 state_dir/project_id/request_id와 다음 data를 받는다:

```json
{
  "title": "AI 인프라 공급망 병목 현황",
  "as_of_date": "2026-09-14",
  "coverage": [
    {"segment": "검토한 공급망 구간", "status": "reviewed", "reason": "탐색과 심층 선정 이유", "judgment_ids": ["판단 A", "판단 B"]},
    {"segment": "아직 검토하지 못한 구간", "status": "unreviewed", "reason": "남은 탐색과 필요 원출처", "judgment_ids": []}
  ],
  "synthesis_claims": [
    {"text": "분야 간 관계를 검토한 종합 결론", "judgment_ids": ["판단 A", "판단 B"], "reasoning": "공통점·차이·중요성의 판단 이유", "limitations": ["범위별 해석과 비교 한계"]}
  ],
  "highlight_ids": ["판단 A", "판단 B"]
}
```

예시 날짜/명칭/ID는 실제 연구에 맞게 치환한다. coverage는 의도한 탐색 범위를 먼저 선언하고 reviewed/unreviewed/missing/out_of_scope와 이유를 보존한다. reviewed는 연결된 scope에 검토 기록이 있다는 뜻이며 구간 전체의 전수 검증을 뜻하지 않는다. 새 ID 목록이나 익숙한 후보만으로 전체 공급망을 대표했다고 하지 않는다. 같은 평가 scope의 최신 판단 하나를 선택하고 이전 판단은 comparison으로 연결한다.

둘 이상의 현재 판단을 묶을 때 synthesis_claims에 최소 하나의 분야 간 종합 판단을 작성한다. 각 문장은 실제 현재 판단 ID, reasoning, 명시적인 limitations를 가져야 한다. 코드가 결론을 창작하지 않는다. 모델은 원출처와 범위/반증을 검토하여 이 문장을 작성하고 코드가 동일 snapshot의 연결·형식·조건 보존을 담당한다. 다른 scope를 글로벌 순위나 실제 전파로 합치지 않는다. highlight_ids는 순위가 아니라 표시할 핵심 판단 선택이며 생략하면 모든 현재 판단을 요약한다.

결과에는 핵심 종합/조건·반증, 위치별 강도/지속성/가동 영향/추세 비교표, 미검토 범위, 후보별 이전→현재 판단·경쟁 가설, 다음 추적 항목, 원문 위치/해시와 snapshot을 포함한다. next_actions에는 다음에 볼 지표·원출처·판단 변경 조건을 명시한다. 문자열을 넘겼다는 이유로 의미 적합성이 검증됐다고 하지 않는다.

후속 종합에는 `previous_report_id`를 추가한다. 현재 행과 이전 행을 scope로 대응하고 추가/제외/범위 변경/판단 교체/검토된 추세를 구분한다. 새 행은 새 병목으로, 제외 행은 해소로, 같은 기록 재사용은 실제 안정으로 표시하지 않는다. 같은 request_id/동일 action은 최초 report/snapshot을 반환하며 데이터가 바뀌면 새 request_id를 쓴다. 과거 보고서 내용은 수정하지 않는다.

## 연구 검토와 독자용 문체 — D3.4

0.2.0-d3.4의 새 synthesize 입력에는 아래 필드가 필수다. 앞 절의 예시에 추가해서 사용한다. 기존 보고서의 export는 유지하며, 새 작성 요청에는 새 request_id를 사용한다. 과거 근거·판단을 덮어쓰지 않고 정정과 비교 이력으로 연결한다.

```json
{
  "research_execution": {"status": "unknown", "reason": "실제 실행 자료를 확보하지 못함"},
  "judgment_reviews": [{
    "judgment_id": "현재 판단 ID",
    "claim_level": "constraint",
    "source_fit": [{"evidence_id": "해당 판단의 근거 ID", "source_scope": "원문이 실제 조사한 모집단·제품·지역·기간", "applicability": "direct", "nature": "observation", "reason": "평가 대상에 적용할 수 있는 이유"}],
    "demand_supply": "동일 규격의 필요한 물량과 사용 가능한 공급, 미충족·배정의 관계. 증설 발표만이면 그 한계",
    "operational_link": "목표 가동일과 필수 경로·대체 수단의 연결. 직접 영향 미확인이면 그대로 기록",
    "comparison_basis": "실제 달력 기간과 비교 가능한 두 시점. 미확인 또는 정정이면 그 이유"
  }]
}
```

- source_fit은 현재 판단의 지지·반대 근거를 빠짐없이 한 번씩 검토한다. 원문의 범위를 scope 문자열에서 자동 복사하지 않는다. direct는 해당 주장을 직접 뒷받침하는 경우, context는 배경 참고만 가능한 경우다. 원래 근거의 nature와 재검토 결과가 다르면 먼저 adopt 정정 이력을 만든다. 문자열 분류 검사는 원문 의미의 독립 검토가 아니다.
- claim_level=constraint는 해당 범위의 제약 설명이며 직접 지지 근거가 필요하다. operational은 실제 가동 영향까지 주장하는 경우로, operational_source_ids에 직접 적용되는 관측 근거를 지정한다. context_only는 배경만 확보한 상태이므로 확정 판단 행으로 발행할 수 없다. 범위를 좁혀 실제로 입증되는 판단을 만들거나 coverage에 검토 한계와 다음 조사를 기록한다. 모른다는 사실을 낮은 병목으로 바꾸지 않는다.
- 각 synthesis_claims에 comparison_scope=reviewed_subset 또는 comprehensive를 추가한다. 미검토·미확보 구간이 있으면 comprehensive는 거부한다. reviewed_subset일 때도 문장에 전체 산업 순위나 검토 밖 비교를 넣지 않는다.
- research_execution.status는 completed/unavailable/not_run/unknown/excluded_by_user다. completed는 실제 entrypoint와 execution_document_id·result_document_id가 모두 필요하다. 호스트 실행 흔적/인계·수행 기록과 반환 결과를 별도 원문 문서로 저장하여 참조한다. 호출 ID가 없는 스킬은 실제 적용·실행 과정과 결과 위치를 기록하며 가상의 호출 ID를 만들지 않는다. 문서 등록만으로 실행 진위를 자동 인증하는 것은 아니다. 일반 웹 조사나 렌더러 실행 로그를 심층 리서치 실행 증거로 쓰지 않는다.
- 실제 Work 실행을 확인할 수 없는 상태를 unavailable로 추정하지 않는다. unknown은 미확인이고 unavailable은 도구 탐색·호출에서 확인된 사용 불가다. completed 외에는 심층 리서치 완료를 표시하지 않되 독립적으로 가능한 원문 취득·정리와 초안 작성은 계속한다.

### 문장을 쓰고 읽는 기준

한 문단은 무엇이 부족한지, 어떤 자료가 그렇게 말하는지, 실제 가동에 어떻게 영향을 주는지, 어디까지 알 수 있는지를 연결한다. 처음 나오는 HBM은 AI 칩에 붙는 고대역폭 메모리, energization은 전력 인입을 마쳐 전기를 공급하는 단계, COD는 상업운전 시작, lead time은 주문부터 인도까지 걸리는 기간처럼 문맥에 맞게 설명한다. 제품명이 판단에 필요하면 설명 뒤에 유지한다. 수치·단위·지역·기간·조건은 생략하지 않는다.

본문 입력에 node_id, evidence ID, snapshot, binding, scoreability, 해시를 넣지 않는다. 일반 독자가 필요한 실제 가동 제약·확실성·평가 가능 여부는 한국어로 설명한다. 코드와 상세 계산·원문 재조회 위치는 자동 부록에 보존한다. 출처는 본문 자료 번호와 발행처 링크로 연결한다. 렌더러는 연구자가 작성한 문장을 번역하거나 판단을 고치지 않으므로, 어색한 명사 나열과 과도한 확정 표현은 입력 단계에서 수정한다.

예: “C06 binding High, energization 제약” 대신 “전력 공급 준비가 늦어지면 서버 설치를 마쳐도 가동을 시작하지 못할 수 있습니다. 다만 이번 자료는 발전소의 접속 지연을 다루므로, 데이터센터에서 같은 지연이 발생했다고 단정할 수는 없습니다.”

연구 결과 전체를 읽고 비교표·요약에도 같은 제한이 남아 있는지 확인한다. 미검토 구간, 반대 근거, 변화 미확인을 부록에만 숨기지 않는다.

## D4 반복 추적·D5 화면 — 0.3.0-d5.1

모든 action은 기존 research_cli.py --action 입력을 사용한다. 아래에는 공통 state_dir/project_id를 생략했다. 상태 폴더는 실제 사용자 프로젝트이며 배포 폴더와 분리한다. 같은 요청 재시도는 같은 request_id, 새 회차/정정은 새 request_id다.

### 심층 리서치 자료 인계와 반환

```json
{"op":"research-handoff","request_id":"research-input-1","data":{"purpose":"AI 공급망 병목의 위치·심화도·추세 검토","document_ids":["원문 ID"],"record_ids":["판단/근거 ID"]}}
```

반환 task를 record로 읽으면 고정 snapshot과 자료 참조·작성 지침이 있다. 실제 호스트의 심층 리서치 스킬/도구를 이 자료와 연결한다. 코드가 호스트 기능을 대신 실행하지 않는다. 실제 기록과 결과를 별도 파일로 확보한 뒤 다음을 실행한다.

```json
{"op":"research-return","request_id":"research-result-1","data":{"handoff_id":"앞 task ID","entrypoint":"실제로 적용한 호스트 스킬/도구","execution_path":"실행 기록 파일의 실제 경로","result_path":"반환 보고서의 실제 경로"}}
```

반환 task의 research_execution을 synthesize에 전달한다. 결과의 주장은 채택 후보이며 원문/범위 검토와 정정·판단 절차를 거쳐야 한다. 호출 성공을 단지 스스로 선언한 문서를 진짜 실행 증거로 바꾸지 않는다. 접촉정보·토큰·비밀정보를 실행 기록에 넣지 않는다.

### 반복 수집

```json
{"op":"monitor-plan","request_id":"monitor-plan-1","data":{"name":"등록 공개자료 추적","sources":[{"id":"issuer-filings","op":"sec","cik":"320193","dataset":"submissions"}]}}
{"op":"monitor-run","request_id":"monitor-2026-09-14-1","data":{"plan_id":"계획 task ID","period":"2026-09-14"}}
```

예시 CIK는 API 형식 설명용이며 실제 연구 기본 대상이 아니다. 계획 sources에는 sec(cik/dataset), ir(url/producer/published_at 선택), prices(ticker/start/end)를 사용할 수 있다. 등록 호스트·연락처·의존성 조건은 기존 adapter와 동일하다. 전체 원문이 대화에 덤프되지 않으며 결과 task는 소스별 상태와 변경/실패 수를 보존한다.

OS 잠금으로 같은 프로젝트의 수집 실행을 직렬화하고, 소스별 완료 기록으로 중단 후 재개한다. 네트워크 응답 저장 직후 기록 전에 종료되면 재취득할 수 있지만 원문은 중복 저장되지 않는다. 산업 변화는 자동 판정하지 않는다. 실패로 완료한 회차를 재수집할 때는 새 요청 ID를 사용한다. 같은 완료 회차의 재시도는 기존 결과를 반환한다. 가격의 기간은 계획에 고정되므로 다음 기간은 새 계획으로 명시한다.

```json
{"op":"schedule-packet","plan_id":"계획 task ID"}
```

위 결과는 호스트 예약에 전달할 실행 양식이고 registered=false다. 실제 예약 등록은 사용자 요청 주기/시간대와 실제 호스트 도구의 성공 기록이 있을 때만 수행·기록한다. 등록된 예약은 동일 회차의 안정된 요청 ID, 실제 상태 경로/프로젝트 ID, 수집 뒤 변경 근거 검토를 사용한다. 자동 점수 쓰기를 포함하지 않는다.

### 관계와 읽기 전용 화면

```json
{"op":"relation","request_id":"relation-1","data":{"from_judgment_id":"출발 판단 ID","to_judgment_id":"영향받는 판단 ID","kind":"conditional","reason":"두 대상과 기간, 전파 조건을 원문으로 검토한 설명","evidence_ids":["채택 근거 ID"]}}
{"op":"export-dashboard","report_id":"종합 보고서 ID","destination":"새 dashboard.html 경로"}
{"op":"dashboard-data","report_id":"같은 보고서 ID"}
```

kind는 technical/observed/conditional이다. 관계는 점수에 영향을 주지 않는다. observed는 관측 근거가 필요하고 conditional은 조건을 설명한다. 단순히 두 대상이 기술적으로 연결된다는 자료를 실제 지연 전파 근거로 채택하지 않는다. 판단 단위 ID로 연결하므로 같은 노드라도 지역·규격·기간이 다르면 별개 대상이다.

관계를 먼저 기록하고 그 뒤 보고서를 생성한다. 화면은 보고서가 참조한 고정 snapshot만 읽으므로 이후 관계·새 수집·점수를 과거 화면에 섞지 않는다. 관계 근거가 정정되면 새 관계와 새 보고서를 검토해서 만들며, 이전 화면은 당시 기록으로 보존한다. 조회/HTML export는 연구 DB에 쓰지 않는다. 목적 파일이 이미 있으면 덮어쓰지 않고 오류를 반환한다.

HTML은 외부 네트워크 없이 필터·원문 탐색·지도 확대/이동·관계별 근거를 제공한다. 실제 Work에서 JavaScript 실행/파일 접근은 별도 인수다. 화면 출력 성공을 연구 승인·예약 성공으로 표현하지 않는다.
