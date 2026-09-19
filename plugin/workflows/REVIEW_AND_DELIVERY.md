# 원문 의미 검토와 같은 상태의 결과 제출

조회·재개·원문 재사용·묶음 인계는 [효율적인 조사](EFFICIENT_RESEARCH.md)를 적용한다. 새 연구는 기본78개/맥락10개이며 기존 campaign은 저장된 범위를 유지한다. 상세 이력의 반복 출력 대신 compact 조회와 변경분 저장을 기본으로 한다.

## 질문을 닫기 전에

긴 조사에서는 전체 원장을 매번 대화에 넣지 않는다. `research-question`에 campaign_id/question_id를 전달하면 해당 질문과 노드만 읽는다. `research-patch`는 request_id와 data의 campaign_id/previous_id 및 변경한 nodes/questions 목록만 받는다. 각 항목은 그 노드/질문의 완전한 최신 값이며 기존 attempts는 유지하고 추가한다. 코드가 나머지 원장을 보존한다. 새 질문을 추가할 수 있지만 새 노드는 node-change로만 추가한다. 같은 request_id 재시도는 중복 저장하지 않고 오래된 previous_id는 거부한다. 연구 시작 시 전체 목록은 확인하되 이후에는 research-next→research-question/question-packet→실제 검토→research-patch를 반복한다.

실제로 읽은 source_reviews의 finding/relevance/quote/location을 유지한다. direct/gap_probe에는 application을 추가한다. 필드를 반복문으로 채우는 것이 아니라 실제 검토한 내용이다.

```json
{"source_population":"원문의 제품·지역·고객·단계","target_population":"이번 질문의 대상","fit":"direct","scope_reason":"적용 또는 제한 이유","nature":"observation","time_use":"historical","observation_date":"2024-07-10","time_reason":"과거 관측이며 현재 납기로 전용하지 않음"}
```

fit은 direct/context/outside, nature는 observation/external_plan/external_forecast/inference/scenario, time_use는 current/historical/future/undated다. 발표일은 document metadata, 수집일은 저장 이력, 관측일은 observation_date, 계획 목표일은 target_date다. current에는 관측일과 current_validity 설명이 필요하다. 오래된 관측의 현재 적용 근거를 꾸미지 말고 후속 자료를 읽는다. 계획·전망은 현재 실현이 아니며 발전원 접속은 부하 인입의 직접 근거가 아니다.

resolved/bounded 질문에는 아래 semantic_review를 연결한다.

```json
{"scope":"적용 범위·기간","interpretation":"사실에서 도출한 해석","counterargument":"확인한 반대 설명과 채택/기각 이유","residual_uncertainty":"판별되지 않은 부분","next_observation":"판단을 바꿀 다음 관측"}
```

정량값이 없어도 직접 근거로 답할 수 있는 정성 판단은 judgment에 남긴다. judgment.bottleneck.state는 constraint(제약 확인)/watch(주의 관찰)/easing(완화 근거)/adequate(충족 근거)/unknown이다. severity/persistence/operational_impact의 쉬운 설명과 confidence·binding·scope를 분리하고 숫자로 환산하지 않는다. 완화·추세 화살표에는 비교 가능한 시점의 근거가 필요하다.

history/trend를 resolved로 닫을 때 semantic_review.chronology에 두 시점 이상의 date/event/state/source_review_index를 연결한다. state는 plan/revision/realization/observation이고 source_review_index는 해당 질문 source_reviews의 0부터 시작하는 위치다. 같은 문서의 과거 이력은 허용하지만 현재 발표일을 여러 날짜로 바꿔 쓰면 안 된다. 계획과 실현을 각각 확인한다.

bounded에는 아래 semantic_review.gap도 필요하다.

```json
{"public_data_limit":"확인한 공개자료 한계","why_remaining_search_would_not_change_answer":"추가 탐색이 판단 범위를 좁히지 못하는 이유","reopen_when":"재개 조건","leads":[{"route":"attempts의 실제 경로","disposition":"investigated","reason":"읽은 내용과 확인한 한계"}]}
```

leads는 investigated/unavailable/not_material로 처리 이유를 남긴다. 유력 경로가 pending이면 같은 실행에서 조사한다. investigated는 found/irrelevant attempt에 연결한다. 검색 요약 두 개나 실패 URL만으로 공백을 닫지 않는다. unavailable/not_material 선언의 진실·충분성은 코드가 인증하지 않는다. 작성자가 모든 공백 종결을 읽고 다음 유력 원문이 남아 있는지 검토한다.

같은 인용을 여러 노드에 적용할 때 semantic_review.shared_source_review에 node_specific_application/different_from_other_nodes/limitations를 남긴다. 이는 공통 원문의 적용 검토이며 같은 결론 복사나 독립 출처 증가를 허용하지 않는다. research-next의 문제는 실제 조사·해석 정정으로 해결하고 새 checkpoint를 추가한다. 과거 quality version1은 새 검토를 자동 통과하지 않는다.

## 전체 노드·관계·이력

synthesize에 campaign_id와 최신 checkpoint_id를 전달한다. interim도 이 방식이어야 전체 목록이 붙는다. 당시 유효 노드·질문·공백·계보를 고정하며 판단 없는 노드와 여러 scope를 유지한다. 좁은 범위 요청에는 전수 campaign을 강제하지 않는다.

기본 ontology Dependencies는 **확인 전 참고 연결**이다. 현재 기술 범위를 검토한 연결이나 실제 지연 전파로 부르지 않는다. 추가·분할·통합한 새 ID에 관계를 자동 복사하지 않는다. 관련 기술 의존을 조사할 때 자료·범위를 검토해 node-relation으로 등록한다.

```json
{"op":"node-relation","request_id":"고유 ID","data":{"campaign_id":"실제 ID","from_node_id":"A03","to_node_id":"A01","kind":"technical","reason":"원문에서 검토한 의존 내용","scope":"적용 범위","as_of_date":"실제 기준일","evidence_ids":["실제 채택 ID"]}}
```

공통 action에는 state_dir/project_id가 필요하다. technical/observed/conditional은 모두 근거를 요구한다. observed/conditional에는 mechanism/period/alternative_paths도 필요하고 observed는 observation 근거여야 한다. 과거 판단 ID 사이 relation은 당시 보고서 범위 안에서 유지한다. 그림을 채우기 위해 선을 만들지 않는다.

과거 계획·수정·실현·관측은 기존 event 명령의 scope/event_type/event_date/description/evidence_ids/materiality/review_reason으로 저장한다. 계획 목표일은 미래일 수 있지만 미래 실현을 observation으로 쓰지 않는다. 점수 이력이 없어도 사건 이력을 표시하며 다른 scope를 점수 추세선으로 합치지 않는다.

## 고정한 결과 제출

1. 노드별 해석·모든 공백 종결의 원문 검토가 존재하고 현재 유효한지 확인한다. [효율적인 조사 P3](EFFICIENT_RESEARCH.md)의 review-status가 valid인 같은 campaign/기준일/질문/역할의 영수증만 재사용하고 review-use로 남긴다. missing/pending_relevance/review_required는 원문과 반증을 실제로 재검토한다. 주요 종합 주장·분야 간 인과 연결·상대 심각도 비교·노드 간 근거 중복 오용과 보고서 judgment_reviews는 이번 결과에 대해 새로 검토한다. 같은 에이전트의 재검토는 독립 검토가 아니다.
2. 최신 checkpoint에서 synthesize(research_stage=baseline_review) 후 research-completion을 확인한다. false면 같은 실행을 계속한다. 불가피한 호스트 중단은 미완료로 기록한다.
3. export-delivery에 report_id와 새 destination 폴더를 전달한다. report.md, dashboard.html, dashboard-data.json, node_review_ledger.json, research_review.json, source_index.json, completion_manifest.json, DELIVERY.json이 같은 report/snapshot에서 생성된다. 각각 손으로 재작성해 개수·상태를 바꾸지 않는다. 기존 출력은 덮어쓰지 않는다.
4. 동봉 렌더러의 HTML에서 전체 노드·범위 선택·원문 링크·점수 없는 이력·검색/확대/이동·모바일을 확인한다. 자체 HTML을 다시 작성하거나 점수 예시를 기본값으로 넣지 않는다.
5. audit와 별도 backup으로 원문·DB·프로젝트 ID를 사용자 연구 상태에 보존한다. export-delivery는 원문 바이트/DB 백업을 대신하지 않는다. 제공 가능한 상태 묶음을 함께 전달하고 원문 재배포 제한·민감정보를 확인한다. 개인 연구 상태는 GitHub 배포 저장소에 올리지 않는다.

자동검사·작성자 의미 검토·실제 Work 실행·사용자 인수는 별개다. 닫힌 질문 수나 필드 충족만으로 충분한 조사라고 하지 않는다.
