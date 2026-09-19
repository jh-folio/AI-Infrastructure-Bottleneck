# Claude Cowork 내구 사본 시험

실제 Claude Cowork 계정에서 확인한다. 로컬 unittest 통과는 Cowork의 저장 동작을 증명하지 않는다. 개인 DB·원문·보고서는 배포 저장소에 올리지 않는다.

1. 이 시험 전용 빈 폴더를 만들어 Cowork 새 작업에 연결한다. 기존 파일이 든 폴더는 쓰지 않는다.
2. “AI Bottleneck으로 처음 시작해줘”를 요청한다. 에이전트가 연결 폴더를 `durable_dir`로 넘기고 `durable-check`가 `ready`를 반환하는지, 폴더에 `AI-Bottleneck-State/PROBE.json`이 생기는지 확인한다.
3. 첫 checkpoint 뒤 `AI-Bottleneck-State/<project_id>/<시각-해시>/research.sqlite`와 `backup.json`이 있고 응답의 `durable.status`가 `saved`인지 확인한다. 연결 폴더의 다른 파일이 그대로인지도 확인한다.
4. 세션을 닫는다. 새 Cowork 작업에 같은 폴더를 연결하고 “이어서 조사해줘”를 요청한다. `workflow`가 `durable_restore_available`을 반환하고 새 DB를 만들지 않고 복구하는지, 복구 뒤 질문·원문 개수가 종료 직전과 같은지 확인한다. 복구본에 마지막 저장 이후 변경이 없을 수 있다는 안내가 나오는지 본다.
5. 폴더 없이 시작하면 `durable_location_required`가 나오고 한 번만 질문하는지, “임시 저장”을 고르면 세션 종료 시 사라질 수 있다는 안내가 나오는지 확인한다.
6. 관찰한 Cowork 버전·OS·폴더 위치(로컬/클라우드 동기화 폴더)·소요 시간·오류를 기록한다. 연결 폴더의 기존 파일이 사라지거나 SQLite 오류가 나면 즉시 중단하고 원인을 보고한다.

통과 조건은 3번의 사본 생성과 4번의 새 세션 자동 복구를 실제로 관찰하는 것이다. 폴더 연결 없이 진행한 실행의 지속성은 이 시험이 보장하지 않는다.
