# D1 저장 POC 실행 안내

합성 데이터만 사용하는 저장 probe다. 설치용 플러그인이나 운영 연구 DB가 아니다. Python 표준 라이브러리만 필요하다. 프로젝트의 실제 Work 실행/파일 접근 도구가 있는 환경에서 수행하며, 로컬 Codex 결과를 Work 결과로 기록하지 않는다.

## 준비

저장소 루트 기준 아래 세 파일의 상대 위치를 유지한다.

- `plugin/runtime/core/persistence_poc.py`
- `plugin/database/poc_schema.sql`
- `tests/test_persistence_poc.py`

사용 가능한 실제 쓰기 위치를 먼저 확인한다. 아래 `STATE_DIR`는 해당 위치 아래의 **아직 존재하지 않는 폴더**로 대체한다. 설치 기본 경로가 아니다. 다른 연구 DB와 폴더는 사용하지 않는다. 실행 도구가 없으면 실패 원인과 가능한 전달 방식만 기록한다.

## 실행 A

```text
python -X utf8 plugin/runtime/core/persistence_poc.py init --state-dir STATE_DIR
```

출력의 project_id와 경로, 실제 도구명·실행 환경·시각을 기록한다. `init`은 이미 존재하는 폴더를 거부한다. 다시 초기화하지 말고 inspect로 재접근한다.

합성 JSON 파일을 만든다: `{"synthetic":true,"kind":"node","id":"SYNTH-N1"}`.

```text
python -X utf8 plugin/runtime/core/persistence_poc.py append --state-dir STATE_DIR --project-id PROJECT_ID --request-id probe-node --payload-file node.json
python -X utf8 plugin/runtime/core/persistence_poc.py inspect --state-dir STATE_DIR --project-id PROJECT_ID
```

출력의 count·state_hash·원문 기록을 보존한다. 필요시 unittest를 실행해 3개 노드·5개 근거와 null 점수 이력, 중단/충돌/실패한 schema 변경을 검증한다.

```text
python -X utf8 -m unittest discover -s tests -p test_persistence_poc.py -v
```

## 실행 B

새 Work 실행/세션에서 같은 저장 상태를 찾아 inspect를 수행한다. count·state_hash·project_id가 같아야 한다. 파일 재업로드나 사용자의 다운로드/가져오기가 필요했다면 수동 복구로 기록하며 자동 지속성 통과로 처리하지 않는다.

같은 append를 재전송하면 `inserted=false`여야 한다. 새 합성 ID와 request_id로 추가한 뒤 이전 기록이 그대로 남는지 확인한다. 동일 request_id의 다른 payload는 거부되어야 한다. 사용자 프로젝트 B는 별도 경로·식별자로 만들고 교차 쓰기 거부를 확인한다.

## 증거와 남은 경계

각 실행의 실제 환경·접근 경로·식별자·내용 해시·사용자 개입·오류·재시도 결과를 저장한다. 로컬 프로세스 재시작, 같은 세션 내 실행, Work 새 세션, 실제 예약 실행을 구분한다. 예약 실행은 별도 요청된 환경에서만 시험한다.

이 probe는 P0의 일부를 시험한다. 실제 사용자 접근 제어는 플랫폼/저장소 권한에 의존하며 project_id 확인만으로 보안 격리를 입증하지 않는다. 정식 연구 schema/migration runner, P1 심층 리서치, P3 화면, P4 공개자료 취득·재조회, 예약 저장 검증은 별도다. D1 전체 완료 조건은 개발 프로젝트의 WORK_POC 계획(이 시험 패키지에는 미포함)와 전환 안내를 따른다.
