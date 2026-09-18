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
- source-context가 반환하는 segment_id를 실제 보관한 경우에만 known_segments 배열로 전달한다. 동일 문서·구간·내용은 text 대신 참조가 반환된다. 원문을 잃었거나 새 의미 검토에 필요하면 known_segments 없이 다시 읽는다. 양쪽 검색 문맥의 next_cursor를 보존하며 검색 히트나 요약을 원문으로 취급하지 않는다. 새 문서 버전은 다른 해시다.

```json
{"op":"research-question-update","state_dir":"STATE","project_id":"PROJECT","request_id":"question-step-2","data":{"campaign_id":"CAMPAIGN","previous_id":"LATEST","question_id":"Q1","set":{"status":"open","next_action":"새로 확인한 공식 증설 발표의 가동 시점을 검토"},"attempts_add":[],"source_reviews_add":[]}}
```

## 묶음 인계

research-batch는 items(최대50)에 key/op/data를 담는다. 허용 op는 source-plan/source-import/adopt/judgment/event다. 각 항목의 저장 요청 ID는 부모 request_id:key로 고정한다. 앞선 결과 ID는 {"$ref":"key"}, import한 원문 ID는 {"$ref":"key.document_id"}로 참조한다. 실제 원문 파일을 source-import로 전달하되 본문을 대화에 재출력하지 않는다. 코드가 근거/판단을 생성하는 기능은 아니다.

실패하면 status=partial, 성공 receipts/ids, failed_key와 error_type만 반환한다. 성공 항목은 이미 저장됐으므로 rollback 완료라고 하지 않는다. 성공 항목의 내용을 바꾸지 않고 같은 묶음 request_id로 재시도하면 중복 저장하지 않는다. 수정된 성공 항목은 새 요청과 정정 이력으로 처리한다. 작업자 결과의 소수 변경 노드/질문만 coordination-submit에 보내고 주 에이전트가 원문 범위·반증·주요 주장을 검토한 뒤 apply한다. 형식/해시 통과를 의미 검토로 간주하지 않는다.

## 계측과 중단

CLI의 state_dir/project_id가 있는 호출은 usage_metrics.jsonl에 요청/응답 문자·바이트 수, op, 응답 해시를 기록한다. 원문·검색어·연락처·경로는 기록하지 않는다. metrics=false로 끌 수 있다. usage-summary는 명령별 합계와 동일 응답 반복 수를 반환한다. 실제 호스트 input/output/reasoning/cached 토큰은 이 계측에 포함되지 않으며 actual_host_tokens=null이다. 문자량을 요금이나 남은5시간 한도로 환산하지 않는다. 호스트가 실제 사용량을 제공하면 그 증거는 별도로 보고한다. 계측 저장 실패는 성공한 DB 변경을 실패로 바꾸지 않으며 metrics_status=unavailable이면 같은 변경을 새 ID로 재시도하지 않는다.

관측된 사용 한도·사용자 운영 예산으로 중단할 때는 최신 checkpoint와 다음 행동을 보존하고 미완료로 표시한다. 실패 호출을 반복하지 않는다. 실제 호스트 예약 지원과 허용 시각을 확인할 수 있을 때만 자동 재개한다. 지원이 없으면 재개 자료를 보존하고 수동 재개가 필요함을 알린다. 제한이 풀린 뒤에는 완료된 자료 탐색·보고서를 다시 생성하지 않고 다음 미해결 작업부터 계속한다. 병렬은 총사용량 절감을 보장하지 않으며 동시 수/모델 변경으로 품질을 몰래 낮추지 않는다.

F01 작업은 [AI 모델 개발·공급사 조사 지침](../methodology/MODEL_SUPPLIERS.md)을 읽고 기업별 차이를 한 노드 내부 판단 범위로 보존한다. 기존 campaign의 목록은 자동 확대하지 않는다.
