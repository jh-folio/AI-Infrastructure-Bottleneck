# 효율적인 조사와 범위 관리

0.3.0-d5.11의 실행 계약이다. 저장된 전체 근거를 유지하고 모델에 전달하는 반복 문맥을 줄인다. 사용량 절감은 조사 충분성의 대체 기준이 아니다.

## 기본 범위와 기존 프로젝트

새 research-start의 기본 scope_profile은 `investment-supply-v1`이다. 원래87개 정의와 ID는 보존하되 E01–E06/E08/E10–E12의10개는 독립 전수 조사 대신 맥락 요인으로 둔다. 원래87개에 F01 AI 모델 개발·공급사 한 노드를 추가한 최신 목록은88개다. 기본78개에는 E07 EPC, E09 물, E13 전력 확보 부지가 포함된다. 포함 노드 모두의 수요/공급·역사·반증·가동 영향·추세를 실제 조사한다. 인력/인허가가 포함 노드의 가동 지연·공급 제약을 설명하는 중요한 경쟁 원인이면 해당 노드 질문과 근거에 기록하고 추가 조사한다. 그런 공백을 범위 밖이라고 닫지 않는다.

이전 profile 없는 campaign은 full-catalog-v1로 해석해 기존87개 의무를 유지한다. 새 연구에서 전체 목록을 원하면 start data의 scope_profile을 full-catalog-v1로 지정한다. 기존 연구의 범위를 사용자가 명시적으로 바꿀 때만 research-scope를 사용한다. 다른 모델/프로필로 조용히 전환하지 않는다.

```json
{"op":"research-scope","state_dir":"STATE","project_id":"PROJECT","request_id":"scope-change-1","data":{"campaign_id":"CAMPAIGN","previous_id":"LATEST","profile":"investment-supply-v1","effective_date":"2026-09-18","reason":"사용자가 기본 투자 공급망 범위로 전환 요청"}}
```

활성 담당 작업은 먼저 반영/해제해야 한다. 과거 질문·근거·보고서는 삭제하지 않으며 새 checkpoint부터 적용한다. 새로 추가되거나 분할/통합으로 생성된 노드는 자동 제외하지 않고 조사 대기열에 넣는다. 기본78개는 영구 고정 수가 아니다. scope_profile의 포함/맥락 ID와 catalog/active 수를 확인한다. 지도·독자 보고서는 당시 snapshot 범위를 유지한다.

## 작게 읽고 변경분만 저장

- research-resume은 기본 compact-v1: pending.items/total/next_offset을 반환한다. 다음 페이지에는 받은 checkpoint_id와 offset/limit을 전달해 상태 변경을 검출하거나 research-next로 실행할 질문을 받는다. 화면에 보이지 않는 항목이 완료된 것은 아니다. research-resume view=full은 이전 전체 응답이며, 가능하면 research-export destination으로 파일에 저장하고 경로·해시만 받는다.
- coordination-packet도 기본 compact-v1이다. questions.items의 미해결/품질 재검토 질문만 우선 전달하고 offset/limit으로 이어 읽는다. 완료된 이전 질문이 필요하면 research-question으로 조회한다. full 옵션은 호환·명시적 상세 조회용이다. 작업 소유권과 전체 이력은 저장소에 유지된다.
- 새 질문/노드 변경은 research-patch를 사용한다. 기존 질문은 research-question-update의 set과 attempts_add/source_reviews_add로 새 내용만 추가한다. campaign_id/previous_id/question_id가 필요하며 이전 시도·리뷰를 다시 복사하지 않는다. 상태 변경은 기존 checkpoint 검증을 통과해야 한다. 정정이 필요한 기존 리뷰는 전체 질문을 읽어 research-patch로 수정하고 정정 사유를 남긴다.
- source-context가 반환하는 segment_id를 실제 보관한 경우에만 known_segments 배열로 전달한다. 동일 문서·구간·내용은 text 대신 참조가 반환된다. 새 세션·새 작업자는 DB에 구간이 있다는 이유만으로 known_segments를 채우지 않는다. 원문을 잃었거나 새 의미 검토에 필요하면 known_segments 없이 다시 읽는다. 양쪽 검색 문맥의 next_cursor를 보존하며 검색 히트나 요약을 원문으로 취급하지 않는다. 새 문서 버전은 다른 해시다.

```json
{"op":"research-question-update","state_dir":"STATE","project_id":"PROJECT","request_id":"question-step-2","data":{"campaign_id":"CAMPAIGN","previous_id":"LATEST","question_id":"Q1","set":{"status":"open","next_action":"새로 확인한 공식 증설 발표의 가동 시점을 검토"},"attempts_add":[],"source_reviews_add":[]}}
```

## 묶음 인계

### 공통 자료 작업 단위와 여러 질문 반영

`research-work-unit`은 읽기 전용 편성이다. data에 campaign_id/checkpoint_id/question_ids(최대10)/reason/expected_output, 선택적으로 document_ids/job_id를 보낸다. 같은 문서·사건을 공유하는 작은 질문 묶음을 사람이 판단해 선택한다. 반환값은 work_unit_id, 소유자, 원문 버전 해시, 질문별 현재 답변·다음 행동·상세 조회, 다음 대기열 명령이다. 편성은 조사 완료가 아니다. 자료가 아직 없으면 document_ids 없이 먼저 탐색하며 나머지 질문은 research-next 대기열에 남는다. 필요한 이력/공백 경로는 research-question으로 조회한다.

주 에이전트의 배정되지 않은 질문은 `research-questions-update`로 한 체크포인트에 반영한다. data는 campaign_id/previous_id/updates이며 각 update는 question_id/set/attempts_add/source_reviews_add다. 같은 질문은 한 번만 넣고 새 질문은 먼저 research-patch로 만든다. attempts·source_reviews의 기존 내용은 코드가 보존한다. 원문 공통 사실은 adopt/event에 저장하되, 노드별 근거 적용·판단은 해당 scope를 유지한다. 표 머리/단위/주석/부정 표현과 계획·관측의 차이를 보존한다.

`research-batch`의 **마지막 항목**에 research-questions-update 또는 coordination-apply를 넣을 수 있다. 여러 질문에 첫 previous_id를 반복하지 않고 마지막에 한 번 반영한다. stale 응답이면 최신 ID를 기계적으로 대입하지 말고 바뀐 질문을 확인한다. 성공한 자료/근거는 그대로 두고 실패한 마지막 항목만 수정해 같은 batch request_id로 재시도한다. 성공 항목 수정은 새 요청과 정정 이력을 요구한다. 응답에는 applied_checkpoint_id, 현재 checkpoint_id, 다음 research-next 명령이 포함된다. 저장 완료는 연구 완료가 아니다.

활성/제출된 담당 작업의 질문은 직접 갱신할 수 없다. 담당자는 파일로 결과를 반환하고 주 에이전트가 기존 coordination-submit/apply의 별도 검토를 수행한다. batch 안에서도 submit과 apply를 사용할 수 있으며 `{"$ref":"submission.result_sha256"}`으로 제출 내용의 해시를 연결한다. review의 source_checks/scope_checks/counterargument_checks는 실제 주 에이전트 검토를 작성한다. 코드는 검토 내용을 생성하거나 검토자 역할을 대신하지 않는다.

내구 사본이 설정된 경우 batch(부분 성공 포함)와 질문 갱신 뒤 동기화한다. durable.status=failed면 DB 기록은 성공했어도 재개용 사본은 최신이 아니다. 같은 DB 기록을 새 ID로 반복하지 말고 durable-sync를 재시도한다.

예: 하나의 원문을 읽고 두 노드의 공급 질문을 검토했으나 직접 근거가 부족한 경우, source-plan/source-import → 노드별 adopt/judgment(실제로 판단했을 때만) → 두 질문의 open 상태와 서로 다른 다음 행동을 담은 research-questions-update로 묶는다. 같은 산업군 설명을 복제하거나 빈 판단으로 질문을 닫지 않는다. 다음 호출에서는 새 대기열을 계속 조사한다.

기존 질문 두 개를 실제로 검토한 뒤 다음 행동만 갱신하는 최소 입력 예시(문구를 그대로 복사하지 않는다):

```json
{"op":"research-batch","state_dir":"STATE","project_id":"PROJECT","request_id":"unit-1","telemetry":{"run_id":"run-1","phase":"initial","work_unit_id":"shared-original-1"},"data":{"items":[{"key":"questions","op":"research-questions-update","data":{"campaign_id":"CAMPAIGN","previous_id":"LATEST","updates":[{"question_id":"Q1","set":{"status":"open","next_action":"제품별 가용 생산량 원문 확인"}},{"question_id":"Q2","set":{"status":"open","next_action":"증설 계획의 가동 실적 원문 확인"}}]}}]}}
```

research-batch는 items(최대50)에 key/op/data를 담는다. 허용 op는 source-plan/source-import/adopt/judgment/event/research-questions-update/coordination-submit/coordination-apply다. 각 항목의 저장 요청 ID는 부모 request_id:key로 고정한다. 앞선 결과 ID는 {"$ref":"key"}, import한 원문 ID는 {"$ref":"key.document_id"}로 참조한다. 실제 원문 파일을 source-import로 전달하되 본문을 대화에 재출력하지 않는다. 코드가 근거/판단을 생성하는 기능은 아니다.

실패하면 status=partial, 성공 receipts/ids, failed_key와 error_type만 반환한다. 성공 항목은 이미 저장됐으므로 rollback 완료라고 하지 않는다. 성공 항목의 내용을 바꾸지 않고 같은 묶음 request_id로 재시도하면 중복 저장하지 않는다. 수정된 성공 항목은 새 요청과 정정 이력으로 처리한다. 작업자 결과의 소수 변경 노드/질문만 coordination-submit에 보내고 주 에이전트가 원문 범위·반증·주요 주장을 검토한 뒤 apply한다. 형식/해시 통과를 의미 검토로 간주하지 않는다.

## 계측과 중단

CLI의 state_dir/project_id가 있는 호출은 usage_metrics.jsonl에 요청/응답 문자·바이트 수, op, 응답 해시를 기록한다. 원문·검색어·연락처·경로는 기록하지 않는다. metrics=false로 끌 수 있다. usage-summary는 명령별 합계와 동일 응답 반복 수를 반환한다. 선택적 telemetry={run_id,phase,work_unit_id}로 실행 단계를 연결한다. ID는 로그에 해시로 저장하고 phase는 initial/resume/monitor/source/review/record/delivery 중 하나다. 성공/부분 실패/오류, 저장 재시도, 반환 구간의 반복, 새 검토 선언 수를 관측한다. 미제공 식별자·호스트 모델 턴/도구 호출/압축 횟수는 미관측 null이다. P3 재사용 수는 새로 저장한 review-use 수이며, 무효화 수는 review-status에서 비유효로 관측된 서로 다른 영수증 수다. 전체 원장의 무효화 총량이나 의미 검토 생략량을 추정하지 않는다. 검토 선언 수는 의미 검토의 정확성을 보장하지 않는다. 실제 호스트 input/output/reasoning/cached 토큰은 이 계측에 포함되지 않으며 actual_host_tokens=null이다. 문자량을 요금이나 남은5시간 한도로 환산하지 않는다. 호스트가 실제 사용량을 제공하면 그 증거는 별도로 보고한다. 계측 저장 실패는 성공한 DB 변경을 실패로 바꾸지 않으며 metrics_status=unavailable이면 같은 변경을 새 ID로 재시도하지 않는다.

관측된 사용 한도·사용자 운영 예산으로 중단할 때는 최신 checkpoint와 다음 행동을 보존하고 미완료로 표시한다. 실패 호출을 반복하지 않는다. 실제 호스트 예약 지원과 허용 시각을 확인할 수 있을 때만 자동 재개한다. 지원이 없으면 재개 자료를 보존하고 수동 재개가 필요함을 알린다. 제한이 풀린 뒤에는 완료된 자료 탐색·보고서를 다시 생성하지 않고 다음 미해결 작업부터 계속한다. 병렬은 총사용량 절감을 보장하지 않으며 동시 수/모델 변경으로 품질을 몰래 낮추지 않는다.

F01 작업은 [AI 모델 개발·공급사 조사 지침](../methodology/MODEL_SUPPLIERS.md)을 읽고 기업별 차이를 한 노드 내부 판단 범위로 보존한다. 기존 campaign의 목록은 자동 확대하지 않는다.

## 원문 의미 검토의 재사용(P3)

이 단계는 같은 campaign·기준일의 **이미 실제로 검토한 닫힌 질문**에만 적용한다. 처음부터 모든 원문을 생략하는 기능이 아니다. 기존 semantic_review/source_reviews를 유지하며 별도 판단 DB를 만들지 않는다. 원문 해시가 같아도 새로운 반증·사건·재검토 시점이 있으면 확인한다.

1. 실제 검토 후 `review-seal`을 호출한다. 최상위 request_id와 data의 campaign_id/checkpoint_id/question_id/role/reviewer/review_note/next_review_at/trigger_notes가 필요하다. role은 author 또는 coordinator다. next_review_at은 시간대를 포함한 미래 시각이며 근거에서 확인한 다음 가동·인증·납기·공개 예정 등 관련 시점을 고려해 정한다. 관련 상하류 판단·사건·관계는 dependency_ids로 명시한다. 미해결 질문이나 출처/중복 검사를 실패한 질문은 등록되지 않는다. 이 명령이 실제 검토를 수행하는 것은 아니다.
2. 재개·반복 검토 시 `review-status`에 data={campaign_id,question_id,role}를 보낸다. valid일 때만 해당 역할의 원문 해석을 재사용할 수 있다. 원 기록은 original_record_action으로 확인한다. missing은 과거 검토의 자동 승인 없이 원문부터 검토한다. pending_relevance는 새 자료/반증/유력 경로의 관련성을 아직 확인하지 않았다는 뜻이고 review_required는 근거·질문·범위·추출/방법 버전 변경, 원문 누락, 재검토 시점 도래 등이다.
3. valid인 기록을 실제 활용하면 `review-use`(request_id, data={campaign_id,question_id,role,review_id})로 계보를 남긴다. 같은 요청 재시도는 중복 기록하지 않는다. 과거 use의 재호출은 당시 ID를 반환하되 현재 유효성은 다시 확인하므로 reuse_allowed=false가 될 수 있다. 등록 영수증만으로 현재 재사용 가능하다고 판단하지 않는다.
4. 새 후보는 status.candidates의 id로 원문/record를 조회해 실제 관련성과 반증을 판단한다. kind=source_check의 attempt:N은 record ID가 아니라 취득 실패 기록이며 함께 반환된 source_id/observed_status로 실패한 원문 경로를 확인한다. 참조 원문의 재취득 실패는 변화 없음이나 최신 확인 성공이 아니므로 대기 상태에서 다른 경로·현재 적용 한계를 검토한다. offset/limit으로 페이지를 읽고 다음 페이지에 inventory_sha256를 전달한다. 변경됐으면 처음부터 목록을 확인한다. 최신 질문에 필요한 수정과 조사를 수행한 뒤 새 request_id의 review-seal에 candidate_reviews={ID:{disposition:"incorporated" 또는 "not_material",reason:"실제 검토 이유"}}를 보낸다. 이전 영수증 이후 새 후보 전부를 설명해야 하며 자동 문자열 분류로 채우지 않는다. scope가 없는 신규 원문은 보수적으로 확인 대기다. 다른 노드에 명확히 연결된 자료나 무관한 checkpoint 진행만으로 전체 검토를 무효화하지 않는다.
5. coordinator 등록에는 다른 reviewer가 작성한 현재 유효한 author 기록이 필요하다. 이 기록은 coordination-submit/apply의 별도 검토 절차를 대체하지 않는다. 최종 종합 주장·분야 간 인과 연결·상대 심각도·중복 근거 오용과 보고서 judgment_reviews는 새로 검토한다.

등록된 기록이 무효/관련성 미확인이면 research-resume/next의 review_saved_interpretation 작업과 완료 판정에 반영된다. 예전 원장은 재사용 영수증이 없으면 기존의 전체 원문 검토 절차를 따른다. 결정론적 원문 위치·해시·출처·중복 검사는 재사용하더라도 계속 수행한다. 내구 사본 설정이 있으면 seal/use도 저장한다. 변경 영향의 재조사 편성은 아래 P4 절차를 따른다.


## 변경 영향과 다음 조사 편성(P4)

새 campaign 또는 업데이트 실행에서 최신 checkpoint로 `impact-scan`을 호출해 비교 기준을 보존한다. data는 campaign_id/checkpoint_id, 선택적으로 document_ids/record_ids/explore/discovery_interval_days다. 안정된 request_id를 사용한다. 최초 호출은 기존 자료를 이미 변경된 자료라고 추정하지 않으며, 기존 미해결 질문은 그대로 조사한다. 과거 자료를 명시적으로 재검토하려면 해당 ID 또는 explore=true를 지정한다.

수집·채택·monitor-run 이후 같은 명령을 새 요청 ID로 실행한다. 원문 버전·실패·근거/사건/판단·검토된 관계를 따라 영향 질문과 보고서를 찾는다. 이는 재검토 경로이지 물리적 지연 전파나 점수 변경이 아니다. 관계/보고서 자체의 최종 의미 검토도 유지한다. `impact-details`에 최상위 scan_id/offset/limit을 전달해 필요한 경로를 페이지별로 읽는다. 미분류 자료는 보수적으로 현재 범위의 검토를 요구한다.

`research-dispatch`에 최상위 campaign_id, 선택적으로 max_nodes(기본3, 최대10)를 전달한다. 기존 coordination의 미해결 작업·활성 담당자·동시 수·중단 상태를 반영한 claim_actions만 반환한다. 주 에이전트가 안정된 request_id와 실제 worker_id를 붙여 coordination-claim을 실행한다. 지원된 실제 호스트 병렬 도구로 배정하거나 순차 수행하고, submit/apply 원문 검토와 단일 쓰기 경로를 유지한다. 읽기 전용 편성 응답은 담당자 실행이나 예약 등록 증거가 아니다. 담당자 결과는 호스트 대기 도구로 기다리며 모델 호출로 상태를 반복 조회하지 않는다.

변경 신호는 재시작 후에도 남는다. 실제 재검토한 질문에 review-seal을 만들 때 해당 신호와 새 자료를 incorporated/not_material 및 근거로 처리한다. scan을 한 번 더 실행하거나 빈 결과가 나왔다는 이유로 이전 미처리 신호를 지우지 않는다. 질문이 아직 미해결이면 계속 조사하며 검토 영수증으로 강제 종결하지 않는다. 완료된 campaign에 새 신호가 있으면 완료 상태를 유지하지 않고 기존 재개 절차를 따른다.

변경분만 보다가 새 병목을 놓치지 않도록 기본30일마다 현재 포함 범위 전체의 탐색 질문을 다시 연다. discovery_interval_days(1~365)는 운영 주기이며 점수 산정이나 최소 조사 기간이 아니다. next_discovery_at은 다음 실제 실행에서 검사하고, 그 자체로 호스트 예약을 만들지 않는다. 사용자 지원 범위 안의 실제 예약/재개 절차는 AUTOMATIC_RESEARCH를 따른다. 신설·분할 노드는 현재 scope와 질문 생성 절차에 따라 조사한다.
