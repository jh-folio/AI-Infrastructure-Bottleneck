# 분야별 병렬 조사와 자동 재개

조회·재개·원문 재사용·묶음 인계는 [효율적인 조사](EFFICIENT_RESEARCH.md)를 적용한다. 새 연구는 기본78개/맥락10개이며 기존 campaign은 저장된 범위를 유지한다. 상세 이력의 반복 출력 대신 compact 조회와 변경분 저장을 기본으로 한다.

전체 연구의 실행 조율 절차다. [연구 실행](RESEARCH_EXECUTION.md)의 전수 조사·원문 검토·완료 조건을 유지한다. Python은 상태와 충돌을 관리하며, 실제 조사·위임·예약 도구 호출은 Work의 주 에이전트가 수행한다. CLI 응답을 안내하는 것만으로 연구를 끝내지 않는다.

## 시작과 역할

최초 전체 연구를 시작하면 기존 project/campaign을 발견하고 `coordination-status`로 상태를 읽는다. 미설정이면 아래 configure를 한 번 저장한다. 병렬·예약 도구의 실제 가용성과 사용자의 자동 진행 의사를 확인한다. 기존에 정한 내용을 반복해서 묻지 않는다. 지원하지 않는 기능을 사용 가능으로 선언하지 않는다. 조사 기준일은 고정한다.

해당 campaign에 이 결정이 아직 없는 상태에서 "처음 시작해줘"류 전체 조사 요청을 받으면, 호스트가 세션 내 구조화 질문 도구(예: Claude의 AskUserQuestion, Codex의 동등 기능)를 제공하는 경우 그 도구로 분야별 서브에이전트 병렬 진행 여부를 한 번만 묻는다. "서브에이전트로 분야별 병렬 진행 시도" vs "이 대화에서 순차로 직접 진행" 두 선택지면 충분하다. 답을 받으면 같은 턴에서 바로 이어간다 — 다음 사용자 메시지를 기다리지 않고 그 답을 `coordination-configure`의 `parallel_supported`/`automatic_resume_requested`에 저장한 뒤 research-start로 진행한다. 이 결정은 campaign당 한 번만 저장하며 이어서 조사해줘/재개에서는 다시 묻지 않고 저장된 값을 그대로 쓴다. 구조화 질문 도구가 없는 호스트에서는 이 단계를 생략하고 아래 실제 위임 시도 결과로만 판단한다.

`parallel_supported`는 호스트 이름만으로 true로 두지 않는다. 사용자가 병렬을 선택했더라도 그대로 true로 확정하지 않는다. 첫 분야를 실제로 하위 에이전트에 위임 시도하고 응답을 확인한 뒤에만 true로 설정한다. 위임 호출 자체가 발생하지 않거나(도구가 보이지 않거나 에이전트가 호출을 시도하지 않음), 호출은 되지만 오류·거부로 실패하면 즉시 false로 전환하고 남은 분야는 같은 대화에서 순차 처리한다. 같은 실행 안에서 이미 확인된 가용성 결과를 재시도마다 다시 추측하지 않는다. (2026-09-18: Claude Cowork에서 서브에이전트 위임이 시도조차 되지 않는 사례가 사용자 보고와 외부 이슈 트래커[anthropics/claude-code#55712, #81441]로 확인됐다. 호스트가 Cowork라는 이유만으로 병렬을 가정하지 않는다.)

공통 CLI는 `python -X utf8 plugin/runtime/research_cli.py --action ACTION.json`이다. 모든 action에 실제 `state_dir`, `project_id`를 넣는다. 쓰기는 고유 `request_id`와 `data`를 사용하며 data에 `campaign_id`를 넣는다. 같은 요청 재시도에는 동일 ID/내용을 사용한다.

```json
{"op":"coordination-configure","request_id":"configure-1","data":{"campaign_id":"ACTUAL_ID","concurrency":2,"lease_minutes":60,"max_runs":24,"max_failures":8,"parallel_supported":true,"automatic_resume_requested":true}}
```

예시의 동시 수·작업 소유권 기간·최대 예약 회차·실패 한도는 설정값이지 Work 한도나 조사 완료 기준이 아니다. 사용자가 허용한 운영 범위에 맞춘다. 정확한 토큰 사용량을 이 코드가 제한한다고 안내하지 않는다. 지원 없는 병렬은 false로 설정하면 한 묶음씩 처리한다. 기존 모델/추론 수준을 임의 변경하지 않는다.

주 에이전트는 계획·배정·원문 검토·공통 DB 반영·종합·예약을 맡는다. 분야 담당 하위 에이전트는 배정된 노드의 실제 자료 탐색과 질문별 판단을 맡으며 공통 DB에 쓰지 않는다. 분야별 에이전트를 명시적으로 위임하고, 결과를 기다린 뒤 검토한다. 한 분야가 끝나면 같은 실행에서 가능한 다음 묶음을 배정한다. 사용자가 분야마다 다음 진행을 요청하도록 만들지 않는다.

## 변경 감지와 배정 후보

실행 시작 시, 그리고 자료 취득·monitor-run 이후에는 EFFICIENT_RESEARCH의 impact-scan과 research-dispatch를 사용한다. 최초 비교 기준 설정과 변경 재검토를 구분한다. dispatch의 claim_actions에 실제 worker_id와 안정된 request_id를 붙여 아래 claim 절차를 수행한다. 빈 응답이면 next_action을 따르고 완료를 추정하지 않는다. 주기적 전체 탐색과 미분류 자료·실패 재검토는 생략하지 않는다. 이 명령들은 호스트 실행/예약을 대신하지 않는다.

## 작은 묶음 배정과 원문 인계

1. `coordination-status`는 전체9개 분야·유효 노드·미조사·진행 중인 작업을 반환한다. 새 노드가 한 분야의 계보를 계승하면 그 분야로 배정된다. 신규/분야 간 통합 노드는 `coordination-assign`의 `assignments:{"NODE_ID":"domain_id"}`로 책임 분야를 정한다. 목록에서 제외하지 않는다.
2. `coordination-claim` data에 `domain_id`, `worker_id`, 선택적 `node_ids`를 전달한다. 결과 id가 job_id다. 중복 분야/동시 수 초과는 대기하고 이미 수행 중인 조사를 다시 시작하지 않는다. `coordination-packet`은 campaign_id/job_id를 최상위에 넣어 배정된 노드·질문만 읽는다.
3. 담당자는 [자료 취득·재조회](SOURCE_QUESTION_FLOW.md)의 실제 자료 경로로 원문을 탐색한다. 읽기 전용 DB 접근이 가능하면 question-packet/source-context를 사용한다. 불가능하면 주 에이전트가 관련 원문·위치·질문 묶음을 분리 파일로 전달한다. campaign 전체 원장을 각 담당자에게 복사하지 않는다. 담당자는 [효율적인 조사](EFFICIENT_RESEARCH.md)의 조회·원문·묶음 계약만 필요한 시점에 읽고 설치/업그레이드/예약/화면 지침은 기본 인계에서 제외한다. 같은 자료를 공유하는 질문은 research-work-unit으로 작은 묶음을 편성할 수 있으나 배정 범위를 넘지 않는다. 원문을 실제로 받지 못한 새 작업자는 known_segments를 비운다.
4. 담당자는 분리 산출물에 원문 bytes 또는 호스트 발췌의 캡처 종류·URL·제작자·해시·위치, 노드별 적용 범위/시점, 반증, 미해결 질문, 후속 경로를 남긴다. 자료 index에서 실제 문서를 따라가며 대체 자료 탐색을 수행한다. 모델 요약을 원문 인용으로 제출하지 않는다.
5. 주 에이전트는 분리 산출물의 원문을 확인해 기존 source-plan/source-import/source-acquire, adopt/judgment/event로 순차 저장하고 실제 ID를 결과 질문에 연결한다. 이 단계의 근거/판단 저장만으로 질문을 완료 처리하지 않는다. 원장 반영은 아래 apply다. 원문 누락·접근 실패이면 해당 질문을 open/blocked로 유지한다.

긴 담당 작업은 `coordination-renew` data의 job_id로 소유권을 연장한다. 반환된 새 ID가 현재 job_id이고 이전 토큰으로 제출할 수 없다. 만료되면 상태를 다시 읽고 claim한다. 원문/분리 파일을 재사용하되 늦은 결과를 새 상태에 자동 덮어쓰지 않는다.

## 제출과 검토 반영

`coordination-submit` data:

```json
{"campaign_id":"ACTUAL_ID","job_id":"ACTUAL_JOB","result":{"nodes":[],"questions":[],"summary":"이번에 실제로 확인한 내용","remaining_work":["미해결 질문과 다음 경로"]}}
```

nodes/questions는 기존 research-patch와 같은 완전한 항목 형식이다. 변경한 항목만 넣으며 기존 질문/시도 이력은 보존한다. 빈 목록은 제출 형식 예시이지 조사 결과가 아니다. 제출은 검토 대기이며 DB의 조사 질문 상태를 아직 바꾸지 않는다. 반환 기록의 result_sha256을 `record`로 읽는다.

주 에이전트는 원문 의미·범위·반증을 점검한 뒤 `coordination-apply`에 campaign_id/job_id/result_sha256과 `review:{reviewer,source_checks,scope_checks,counterargument_checks}`를 전달한다. reviewer는 담당 worker_id와 달라야 한다. 이 구분은 실제 독립 검토의 인증이 아니다. 동일 작업의 질문/노드가 바뀌었으면 재검토하고, 다른 분야만 바뀌었으면 그 변경을 보존해 합친다. 체크포인트와 반영 영수증은 함께 저장되며 재시도해도 한 번만 반영된다.

잘못된 원문 적용·반복 공백·행 번호로 바꾼 결론은 반영 검사에서 재조사 대상으로 돌린다. 코드는 원문 의미의 진실을 인증하지 않는다. 정성적 원문 검토 책임은 주 에이전트에 있다. 결과가 부적합하거나 진전이 없으면 `coordination-release`에 job_id/reason을 기록하고 후속 조사로 다시 배정한다. 제출 후에는 만료됐다는 이유로 결과를 버리지 않으며 검토하거나 명시적으로 release한다.

## 예약으로 같은 연구 이어가기

자동 진행 요청이 있고 실제 호스트 예약 도구를 사용할 수 있으면 `coordination-schedule-packet`을 읽고 **현재 연구 대화의 실제 도구**로 예약을 생성/갱신한다. 저장 상태를 읽을 수 있는 위치와 주기는 호스트에서 확인한다. packet 생성은 등록이 아니다. 실제 도구가 반환한 schedule_id/host/receipt와 status(active/paused/stopped/failed)를 `coordination-schedule`에 저장한다. 활성 예약이 이미 있으면 재사용하며 중복 생성하지 않는다. 예약 등록의 응답이 불확실하면 먼저 호스트에서 조회한다.

예약 실행은 최신 project/campaign/checkpoint를 복원하고 `coordination-run`으로 실제 host_run_id, schedule_id, observed_checkpoint를 기록한다. 동일 호스트 회차를 다시 기록하지 않는다. 최대 회차 도달은 새 회차 시작을 막으며 마지막 허용 회차의 작업은 수행할 수 있다. 실패 한도·회차 한도에 도달하면 control paused와 실제 예약 중단을 처리하고 미완료 상태를 알린다. 한도 증가를 임의로 반복해 무한 재실행하지 않는다.

`coordination-status`에 살아 있는 담당 작업이 있으면 중복 배정하지 않는다. 비어 있는 분야만 claim할 수 있다. 최신 DB에 접근하지 못하면 새 DB를 만들지 않고 확인 가능한 최신 백업을 복원한다. Claude Cowork에서는 작업 폴더의 사본을 `durable-restore`로 복원한다(USER_WORKFLOW의 Cowork 절차). 대화에 옛 DB가 첨부돼 있다는 사실만으로 최신 상태라고 판단하지 않는다. 복원이 안 되면 사용자 조치가 필요한 장애로 일시정지한다. 이것을 무인 재개 성공으로 세지 않는다.

완료 때는 전수 질문·원문 의미·분야 간 종합을 확인하고 synthesize→research-completion→export-delivery 후 `coordination-finish`에 campaign_id/report_id/meaning_review를 기록한다. 이후 실제 호스트 예약을 중단하고 그 결과를 coordination-schedule로 기록한다. 사용자 중지에는 `coordination-control` mode=paused/reason과 실제 예약 중단을 수행한다. completed/paused는 새 claim을 막는다. 예약 중단 실패는 그대로 표시하고 재시도하며, 늦게 호출된 실행도 저장된 중지 상태를 존중한다.

예약 없이 현재 실행에서 진행 가능한 조사는 계속한다. 자동 재개 기능이 없거나 상태 접근이 안 되면 그 한계를 표시하며 가능하다고 약속하지 않는다. 연구 품질·실제 Work 병렬 작업·예약 재개·사용자 인수는 각각 별도로 검증한다. 중요한 진행 변화·사용자 조치가 필요한 장애·최종 결과만 알리고 매 회차마다 재개 요청을 요구하지 않는다.
