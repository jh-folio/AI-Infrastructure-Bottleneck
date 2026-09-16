"""Reader-facing prose and citations, with separate reproducibility appendix."""
import json


def render_reader(value, evidence, documents, text):
    t = text
    sources = {eid: i + 1 for i, eid in enumerate(sorted(evidence))}
    nature = {'observation': '실제 관측', 'external_plan': '외부 계획', 'external_forecast': '외부 전망',
              'inference': '연구자의 추론', 'scenario': '조건부 시나리오'}
    confidence = {'Low': '낮음', 'Medium': '중간', 'High': '높음'}
    execution = value['research_execution']
    states = {'completed': '실행 및 결과 자료가 등록되어 있습니다.', 'unknown': '실제 실행 여부를 확인할 자료가 없습니다.',
              'not_run': '이번 작성에서는 실행하지 않았습니다.', 'unavailable': '이번 환경에서는 연결하지 못했습니다.',
              'excluded_by_user': '사용자 요청으로 제외했습니다.'}

    def scope(s):
        scenario = {'base': '기본 시나리오'}.get(s['scenario'], s['scenario'])
        return t(f"{s['geography']} / {s['product_spec']} / {s['horizon']} / {scenario} / 판단 기준일 {s['as_of_date']}")

    def cite(eid):
        return f"[자료 {sources[eid]}](#source-{sources[eid]})"

    lines = ['# ' + t(value['title']), '', '기준일: ' + value['as_of_date'], '',
             ('연구 상태: 검토용 종합 결과 — 최종 승인은 별도입니다.' if value.get('research_stage')=='baseline_review'
              else '연구 상태: 조사 중간 결과 — 최초 연구가 완료된 보고서가 아닙니다.'), '',
             '심층 리서치: ' + states[execution['status']], '',
             '표는 공급망 위치에 따라 정리했으며 순위를 뜻하지 않습니다. 확인하지 못한 구간은 별도로 표시했습니다.', '',
             '## 핵심 요약', '']
    if not value['rows']:
        lines += ['아직 검토된 판단이 없습니다. 아래 탐색 범위와 남은 공백을 확인해 주세요.', '']
    if value['rows'] and not value['synthesis_claims']:
        for row in value['rows']:
            if row['judgment_id'] in value['highlight_ids']:
                lines += [t(row['conclusion']) + ' ' + ' '.join(cite(e) for e in row['support_ids']), '',
                          '아직 모르는 점: ' + t(row['unknowns']), '']
    for claim in value['synthesis_claims']:
        linked = [r for r in value['rows'] if r['judgment_id'] in claim['judgment_ids']]
        refs = list(dict.fromkeys(e for r in linked for e in r['support_ids'] + r['counter_ids']))
        if claim['comparison_scope'] == 'reviewed_subset':
            lines += ['아래 비교는 이번에 검토한 범위에 한정됩니다. 공급망 전체의 순위는 아직 판단하지 않았습니다.', '']
        lines += [t(claim['text']), '', t(claim['reasoning']) + ' ' + ' '.join(cite(e) for e in refs), '',
                  '이 결론의 한계: ' + t(claim['limitations']), '']
    lines += ['## 공급망 위치별 비교', '', '| 어디에서 막히는가 | 부족은 어느 정도인가 | 얼마나 이어질 수 있는가 | 가동에 미치는 영향 | 이전보다 달라졌는가 |',
              '|---|---|---|---|---|']
    for row in value['rows']:
        lines.append('| ' + ' | '.join([t(row['segment']), t(row['severity']), t(row['persistence']),
                                        t(row['operational_impact']), row['trend']['label']]) + ' |')
    for row in value['rows']:
        lines += ['', '## ' + t(row['segment']), '', t(row['conclusion']), '',
                  '이 설명이 적용되는 범위: ' + scope(row['scope']), '', t(row['reasoning']), '',
                  '판단의 확실성: ' + confidence.get(row['confidence'], t(row['confidence'])), '']
        for role, ids in [('판단을 뒷받침하는 자료', row['support_ids']), ('다른 가능성을 보여 주는 자료', row['counter_ids'])]:
            for eid in ids:
                e = evidence[eid]
                lines += [role + ': ' + t(e['claim']) + ' (' + nature.get(e['nature'], t(e['nature'])) + '). ' + cite(eid), '']
        if not row['counter_ids']:
            lines += ['반대 근거를 찾는 데 남은 한계: ' + t(row['counter_search_limit']), '']
        lines += ['변화 판단: ' + row['trend']['label'] + '. ' + t(row['trend']['reason']), '',
                  '함께 검토할 다른 설명: ' + t(row['alternatives']), '', '아직 모르는 점: ' + t(row['unknowns']), '']
    lines += ['## 탐색 범위와 남은 공백', '', '| 구간 | 확인한 범위와 남은 일 |', '|---|---|']
    status = {'reviewed': '검토 기록 있음', 'unreviewed': '미검토', 'missing': '근거 미확보', 'out_of_scope': '대상 밖'}
    for c in value['coverage']:
        lines.append('| ' + t(c['segment']) + ' | ' + status[c['status']] + ': ' + t(c['reason']) + ' |')
    catalog=value.get('map_catalog',{})
    if catalog.get('scope')=='full_active_catalog':
        lines += ['', '### 전체 조사 목록', '', '아래 목록은 공급망 지도의 노드와 같습니다. 판단 범위가 여러 개이면 각각 보존하며, 미확인을 낮은 병목으로 해석하지 않습니다.', '',
                  '| 구간 | 조사 상태 | 확인한 내용 또는 남은 공백 |', '|---|---|---|']
        for node in catalog['nodes']:
            if node.get('lifecycle','active')!='active':continue
            qs=node.get('questions',[])
            from research_loop import DIMENSIONS
            state='미조사' if not qs else ('조사 진행 중' if any(q['status'] in ('open','blocked') for q in qs) or node.get('review_issues') or set(DIMENSIONS)-{q['dimension'] for q in qs} else '검토 기록 있음')
            linked=[r for r in value['rows'] if r['scope']['node_id']==node['node_id']]
            explanation=' / '.join(r['conclusion'] for r in linked) or ' / '.join(dict.fromkeys(q.get('answer','') for q in qs if q.get('answer')))
            lines.append('| '+t(node['name'])+' | '+state+' | '+t(explanation or '자료 탐색과 검토가 필요합니다.')+' |')
    lines += ['', '## 이전 보고서에서 달라진 점', '']
    if not value['previous_report_id']:
        lines += ['첫 종합 기록입니다. 이전 보고서와의 변화는 아직 비교하지 않았습니다.', '']
    for c in value['changes']:
        label = next((r['segment'] for r in value['rows'] if r['judgment_id'] == c.get('judgment_id')), c['scope']['product_spec'])
        if c['before'] == c['after']:
            lines += ['- ' + t(label) + ': 이전 설명을 유지했습니다. 이번에 상황이 그대로임을 새로 확인했다는 뜻은 아닙니다.']
        else:
            lines += ['- ' + t(label) + ': ' + t(c['status']), '  이전 설명: ' + t(c['before']), '  이번 설명: ' + t(c['after'])]
    lines += ['', '## 다음 추적 항목', '']
    for row in value['rows']:
        lines += ['- ' + t(row['segment']) + ': ' + t(row['next_actions'])]
    lines += ['', '## 출처', '']
    for eid in sorted(evidence):
        e = evidence[eid]; d = documents[e['document_id']]
        url = d['url'].replace('(', '%28').replace(')', '%29').replace(' ', '%20')
        producer = t(d['producer']).replace('[', '&#91;').replace(']', '&#93;')
        lines += [f'<a id="source-{sources[eid]}"></a>',
                  f"자료 {sources[eid]}. [{producer}]({url}) · {e['published_at']} · {nature.get(e['nature'], t(e['nature']))}", '']
    lines += ['## 부록: 검증과 재조회', '',
              '아래는 기록을 다시 확인하기 위한 정보입니다. 본문의 산업 판단과 별개이며 독립 검토나 최종 승인을 뜻하지 않습니다.', '',
              '심층 리서치 실행 기록: ' + t(execution['reason']), '',
              '실행·결과 자료의 등록은 실제 호스트 실행 로그의 독립 검증을 대신하지 않습니다.', '',
              'snapshot: ' + value['snapshot_id'], '',
              f"전체 저장 기록의 실패·부분 취득: {len(value['source_failures'])}건. 이 보고서만의 실패 수나 변화 없음 판정이 아닙니다.", '',
              '### 원문과 재조회 위치', '']
    for eid in sorted(evidence):
        e = evidence[eid]; d = documents[e['document_id']]
        lines += [f"- 자료 {sources[eid]}: {eid} · {t(e['location'])}", '  원문: ' + t(e['quote']), '  SHA-256: ' + d['sha256']]
    lines += ['', '### 판단·범위·계산 및 실행 기록', '']
    # JSON retains all internal identifiers and unrounded provenance outside the reader narrative.
    audit = {k: value[k] for k in ('rows', 'judgment_reviews', 'research_execution', 'previous_report_id')}
    lines += ['<pre>' + t(json.dumps(audit, ensure_ascii=False, indent=2)) + '</pre>']
    return '\n'.join(lines) + '\n'
