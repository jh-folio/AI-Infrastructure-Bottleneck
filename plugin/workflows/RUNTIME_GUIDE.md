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
