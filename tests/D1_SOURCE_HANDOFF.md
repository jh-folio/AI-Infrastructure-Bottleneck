# D1 공개 JSON 취득·재조회 시험

이번 probe는 SEC 공개 JSON의 취득·원문 보존·항목별 재조회만 시험한다. 재무 정의 검증·근거 채택·점수·IR/PDF 추출·yfinance는 아직 포함하지 않는다. RSS와 개인 연구자료는 사용하지 않는다.

Python 실행과 HTTPS·파일 접근이 가능한 실제 환경에서 아래 작업을 수행한다. 설치 ZIP 생성은 이 작업의 실행 성공이 아니다. 대상 기업 CIK는 사용자가 지정한 공개 표본으로 정하며 제품 기본 기업으로 저장하지 않는다.

1. 사용자가 허용한 저장 위치 아래 존재하지 않는 `SOURCE_DIR`를 정한다. 저장 probe의 기존 폴더와 구분한다.
2. 실행 환경의 `SEC_USER_AGENT`에 본인의 실제 식별/연락 정보를 설정한다. 이 값은 패키지·채팅 출력·로그에 넣지 않는다. 없으면 configuration_required를 반환한다.
3. `python -X utf8 plugin/runtime/adapters/source_probe.py init --state-dir SOURCE_DIR`를 실행한다.
4. `python -X utf8 plugin/runtime/adapters/source_probe.py capture --state-dir SOURCE_DIR --url https://data.sec.gov/submissions/CIK##########.json`에서 CIK를 10자리 실제 표본으로 바꾼다. 성공 시 document_id·해시·바이트 수를 보존한다.
5. `python -X utf8 plugin/runtime/adapters/source_probe.py query --state-dir SOURCE_DIR --document-id DOCUMENT_ID --pointer /name`으로 회사명을 재조회한다. 공시목록은 `/filings/recent/form` 등의 실제 JSON Pointer로 읽는다. companyfacts는 공개 endpoint로 별도 capture한 후 필요한 taxonomy/tag/units를 조회한다.
6. 같은 URL을 다시 취득해 동일 응답이면 unchanged, 내용 변경이면 새 document_id가 기록되는지 확인한다. 새 실행에서 기존 document_id를 재조회해 해시를 대조한다.

출력은 최대 길이가 제한된 원문 JSON 발췌다. truncated=true라면 pointer를 더 좁혀 다시 읽는다. 발췌가 단위·기간·주석·반대 근거를 모두 담는다고 가정하지 않는다. 원문은 DB에 bytes로 보존되며 조회 시 해시를 검사한다. 실패/부분 응답은 조회 가능한 문서로 채택하지 않고 attempts에 남긴다.

403·429·timeout·parse_failed는 변화 없음이 아니다. 차단 시 우회하거나 반복 요청하지 말고 해당 실행 환경의 실패로 기록한다. 임의 URL·인증 URL·redirect는 지원하지 않는다. 이번 구현은 data.sec.gov/www.sec.gov 공개 HTTPS JSON만 허용하고 자동 대량 수집·재시도는 하지 않는다.

저장/자료원 전체 로컬 테스트: `python -X utf8 -m unittest discover -s tests -p "test_*.py" -v`.

2026-09-14 개발 PC의 SEC 표본 요청은 HTTP403이었다. 로컬 실패가 Work에서도 같은 결과를 보장하지 않는다. 실제 Work에서 성공/실패와 새 세션 재접근을 따로 기록한다. D1의 나머지 심층 리서치·화면·예약 검증은 별도다.
