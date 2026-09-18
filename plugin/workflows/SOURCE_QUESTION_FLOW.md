# 자료 취득에서 질문별 원문 검토까지

조회·재개·원문 재사용·묶음 인계는 [효율적인 조사](EFFICIENT_RESEARCH.md)를 적용한다. 새 연구는 기본78개/맥락10개이며 기존 campaign은 저장된 범위를 유지한다. 상세 이력의 반복 출력 대신 compact 조회와 변경분 저장을 기본으로 한다.

이 흐름은 조사 큐와 저장 원문을 연결한다. 스킬이 원문을 읽고 판단하는 일을 대신하지 않으며, 실행 시간이나 자료 개수로 종료하지 않는다. 모든 명령은 실제 `state_dir`/`project_id`를 함께 전달한다. 쓰기 명령에는 고유 `request_id`를 사용한다. 변경 없는 재시도만 같은 ID를 재사용한다.

## 1. 질문과 자료 경로 연결

`research-start`/`research-resume`으로 현재 유효 노드를 확인하고 `research-checkpoint`에 노드별 구체적인 질문을 저장한다. 각 질문은 기존 수요/공급·역사·반증·가동 영향·추세 차원을 사용한다. 수집 전 원문이 답해야 할 관측을 정한다.

`source-plan`은 하나의 실제 원문 경로를 노드와 질문 차원에 연결한다. source는 `url/producer/kind`, 선택 `published_at`이고 bindings는 `node_id/dimensions/purpose` 배열이다. kind는 `public_document`, `ir`, `sec_filing`, `sec_submissions`, `sec_companyfacts`다. public_document의 명시적 HTTPS 경로 등록은 해당 호스트 취득 범위만 추가하며 프로젝트 설정을 변경하지 않는다. 실제 요청 전 공인 주소 검사와 redirect 거부를 유지한다. URL의 인증정보/쿼리를 수집 기록에 넣지 않는다. SEC 요청 식별·제한은 기존 계약을 따른다.

```json
{"op":"source-plan","state_dir":"STATE","project_id":"PROJECT_ID","request_id":"route-issuer-q3","data":{"campaign_id":"CAMPAIGN_ID","source":{"url":"https://issuer.example.org/q3-results.html","producer":"공식 발행자","kind":"public_document","published_at":"2026-08-01"},"bindings":[{"node_id":"A03","dimensions":["demand_supply","alternatives"],"purpose":"해당 세대 HBM의 고객 배정 제약과 대체 공급 인증 내용을 검토"}]}}
```

위 URL은 형식 예시다. 실행 전에 실제 발행처·원문 URL·공개일로 치환한다. `published_at`을 모르면 생략하고 원문 검토에서 확인한다. 수집일을 발표일로 채우지 않는다. 기존 저장 원문을 연결하려면 data에 `document_id`를 추가한다. URL/발행자/알려진 발표일이 기존 원문과 일치해야 한다. 하나의 문서가 여러 노드를 다루면 bindings를 추가하되 각 노드의 검토 목적을 구체화한다. 기존 노드의 자료 계획이 신규/분할 노드에 자동 상속되지는 않는다.

## 2. 취득·캐시·호스트 자료 가져오기

```json
{"op":"source-acquire","state_dir":"STATE","project_id":"PROJECT_ID","request_id":"acquire-issuer-q3","data":{"plan_id":"PLAN_ID"}}
```

저장된 같은 원문 버전이 있으면 `cached`와 `network_performed=false`를 반환한다. 이는 최신 상태 확인이 아니다. 원문 변경을 실제 확인할 때만 새 request_id와 `refresh:true`로 요청한다. 성공/실패는 자료 계획과 연결된 불변 취득 기록에 저장한다. 실패 후 대체 원문/발행처를 발견하면 별도 source-plan을 연결한다. 실패가 질문을 닫거나 근거를 채택하지는 않는다.

HTML/PDF/UTF-8 text/CSV와 공개 JSON을 보존한다. CSV는 행·헤더를 함께 읽고 JSON은 `filings`/`facts` 또는 JSON Pointer로 선택 조회한다. PDF에 선택 의존성 pypdf가 없거나 시각 표/차트가 있으면 추출 제한으로 남긴다. 미지원 파일을 빈 내용의 성공으로 취급하지 않는다. XLSX·OCR과 추가 산업 API의 전용 해석기는 이 기능의 구현 범위가 아니다.

호스트 도구가 확보한 자료를 가져오는 경우:

```json
{"op":"source-import","state_dir":"STATE","project_id":"PROJECT_ID","request_id":"import-original","data":{"plan_id":"PLAN_ID","path":"ACTUAL_SAVED_SOURCE_PATH","mime":"text/plain","capture_kind":"extracted_text","acquisition_note":"사용한 도구와 원문 추출 범위·누락을 실제 수행 내용대로 기록"}}
```

capture_kind는 실제 원본 파일이면 `original_bytes`, 원문에서 추출한 텍스트면 `extracted_text`, 검색 응답이면 `search_trace`다. 검색 요약을 extracted_text/original_bytes로 이름만 바꾸지 않는다. 스킬의 진술은 호스트 실행의 독립 인증이 아니다. 원문 URL/발행자는 source-plan에 유지하고 자료 표현 방식은 별도로 보존한다. 저장 해시는 제공한 바이트의 해시이며 추출 텍스트를 원본 PDF 해시로 부르지 않는다. search_trace와 내부 web-search/web-open 응답은 직접 채택 근거로 승격할 수 없다.

## 3. 질문별로 지지와 반대 문맥 조회

```json
{"op":"question-packet","state_dir":"STATE","project_id":"PROJECT_ID","campaign_id":"CAMPAIGN_ID","question_id":"QUESTION_ID","focus_terms":["HBM","allocation","lead time"],"counter_terms":["qualification","alternative","cancellation","supply expansion"],"limit":3,"max_chars":6000}
```

자료 계획의 node/dimension과 기존 질문 attempts에 연결된 원문만 읽는다. 원문 버전들을 숨기거나 신규 결론으로 합치지 않는다. 기준일 이후로 확인된 발표는 발췌에서 제외하고 공개일 미확인은 검토 필요로 반환한다. 오래된 자료의 현재 적용 여부는 스킬이 사건일과 범위를 별도로 검토한다.

focus/counter는 **검색 묶음**이며 지지/반증으로 자동 채택된 근거가 아니다. 두 묶음은 별도 발췌 예산을 사용하므로 긴 앞부분이 다른 묶음을 모두 밀어내지 않는다. 관련 원문과 앞뒤 문맥을 읽는다. `next_offset`이 있으면 다음 문서 페이지를 조회한다. 자료 경로는20개씩 반환하며 `next_route_offset`은 다음 요청의 `route_offset`으로 넘긴다. 질문에 scope가 없으면 scope_review_required를 반환하므로 판단 전에 구체적인 평가 범위를 정한다. 긴 절은 아래 명령으로 이어 읽는다.

```json
{"op":"source-context","state_dir":"STATE","project_id":"PROJECT_ID","document_id":"DOCUMENT_ID","focus_terms":["HBM","allocation"],"counter_terms":["alternative","qualification"],"max_chars":6000,"cursors":{"focus":{"offset":0,"char_offset":3000},"counter":null}}
```

cursor는 반환된 `lanes.focus.next_cursor`/`lanes.counter.next_cursor`를 그대로 사용한다. 생략한 묶음은 처음부터, 명시한 null 묶음은 이미 읽은 것으로 처리한다. 다음 조회에서는 같은 용어/문서 버전을 사용한다. 정확한 절은 `read-document`로 확장한다. 검색어 일치가 없는 것은 관측 부재의 증거가 아니므로 동의어·다른 절/표/첨부·발행처로 확장한다. JSON이면 `structured_read_required` 안내에 따라 알려진 Pointer를 읽는다.

## 4. 실제 검토 후 기존 판단 경로로 연결

원문에서 관련 사실과 반대 문맥을 읽고 노드·규격·지역·시점에 적용되는지 판단한다. 해당하는 사실만 `adopt`로 검토하고 `judgment`에서 지지/반대 근거·경쟁 설명·남은 공백·다음 행동을 기록한다. source-plan이나 검색 묶음을 evidence_id로 대신 쓰지 않는다.

질문별 실제 읽기 결과는 기존 checkpoint의 attempts와 source_reviews에 남긴다. source_reviews에는 기존 document_id/location/quote/finding/relevance/role 계약을 사용한다. 자동으로 검토문·quote·정성 판단을 생성하거나 모든 질문을 일괄 종결하지 않는다. 이어 `research-next`가 반환하는 source_plan_ids와 question-packet 경로에서 같은 실행을 계속한다. 반환 action에 없는 state_dir/project_id/request_id와 실제 검색어는 호출자가 채운다.

이 기능은 원문 경로·문맥·실패 상태의 전달이다. 의미 검토·공백 종결의 충분성·전체 노드 화면·독자용 보고서의 인수는 별도다.
