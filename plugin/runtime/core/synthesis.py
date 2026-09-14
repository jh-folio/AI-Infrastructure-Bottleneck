"""Render reviewed supply-chain judgments from one immutable snapshot.

No model calls, implicit scoring, global ranking or automatic trend inference.
"""
from datetime import date
import html
import json

from research_store import required, digest, dumps
from research import SCOPE, scope_check, existing_action, display_result

FORMAT = 'supply-chain-synthesis-1'
DIMENSIONS = tuple(k for k in SCOPE if k != 'as_of_date')
STATUS = {'reviewed': '연결 범위의 검토 기록 있음', 'unreviewed': '미검토', 'missing': '근거 미확보', 'out_of_scope': '대상 밖'}
CONFIDENCE = {'Low': '낮음', 'Medium': '중간', 'High': '높음'}
DIRECTION = {'strengthening': '심화', 'easing': '완화', 'unchanged': '유지', 'unknown': '추세 미확인'}
CAUSE = {'new_observation': '새 관측', 'data_recovery': '자료 회복', 'correction': '정정',
         'scope_change': '범위 변경', 'method_change': '방법 변경'}


def text(value):
    """Keep untrusted prose from introducing table columns or HTML."""
    if isinstance(value, list):
        return ' / '.join(text(v) for v in value) if value else '기록 없음'
    if value is None:
        return '미확인'
    if not isinstance(value, str):
        value = json.dumps(value, ensure_ascii=False)
    return html.escape(value).replace('|', '&#124;').replace('\r', '').replace('\n', '<br>')


def key(scope):
    return tuple(scope[k] for k in DIMENSIONS)


def scope_label(scope):
    return ' · '.join(str(scope[k]) for k in ('node_id', 'geography', 'product_spec', 'scenario', 'horizon', 'as_of_date'))


def make_report(store, request, value):
    action = {'synthesis_format': FORMAT, 'data': value}
    prior = existing_action(store, 'report', request, action)
    if prior:
        return prior
    required(value, 'title', 'as_of_date', 'coverage')
    date.fromisoformat(value['as_of_date'])
    if not isinstance(value['coverage'], list) or not value['coverage']:
        raise ValueError('Declare the intended coverage, including unreviewed segments')
    snap = store.snapshot()
    records = {r['id']: r for r in snap['records']}
    documents = {d['id']: d for d in snap['documents']}
    superseded = {r['payload']['data'].get('supersedes') for r in records.values() if r['kind'] == 'evidence'}
    refs, used_evidence = set(), {}

    def get(rid, kind):
        r = records.get(rid)
        if not r or r['kind'] != kind:
            raise ValueError('Reference missing from fixed snapshot or wrong kind')
        refs.add(rid)
        return r['payload']['data']

    def reviewed(rid, historical=False):
        j = get(rid, 'judgment')
        scope_check(j['scope'])
        if j['scope']['as_of_date'] > value['as_of_date']:
            raise ValueError('Judgment newer than report as-of date')
        ids = set(j['support_ids'] + j['counter_ids'])
        if not ids:
            raise ValueError('Judgment has no reviewed evidence')
        for eid in ids:
            e = get(eid, 'evidence')
            if (eid in superseded and not historical) or e['decision'] != 'accepted' or e['scope'] != j['scope']:
                raise ValueError('Held, rejected, superseded or wrong-scope evidence')
            if e['published_at'] > j['scope']['as_of_date'] or e['document_id'] not in documents:
                raise ValueError('Evidence date or document invalid')
            used_evidence[eid] = e
        return j

    def trend(j):
        c = j.get('comparison')
        out = {'direction': 'unknown', 'label': DIRECTION['unknown'], 'cause': None,
               'reason': '비교 가능한 두 시점의 검토 입력이 없습니다.', 'prior_judgment_id': None}
        if not c:
            return out
        required(c, 'prior_judgment_id', 'direction', 'change_cause', 'reason', 'evidence_ids')
        if c['direction'] not in DIRECTION or c['change_cause'] not in CAUSE:
            raise ValueError('Invalid comparison direction or change cause')
        old = reviewed(c['prior_judgment_id'], historical=True)
        if not isinstance(c['evidence_ids'], list) or not set(c['evidence_ids']) <= set(j['support_ids'] + j['counter_ids']):
            raise ValueError('Comparison evidence must belong to the current judgment')
        out.update(cause=c['change_cause'], prior_judgment_id=c['prior_judgment_id'], review_reason=c['reason'],
                   requested_direction=c['direction'], prior_conclusion=old['conclusion'], prior_scope=old['scope'])
        if key(old['scope']) != key(j['scope']):
            out['reason'] = '범위·기간 또는 방법이 달라 추세를 비교할 수 없습니다.'
        elif c['change_cause'] != 'new_observation':
            out['reason'] = CAUSE[c['change_cause']] + ' 기록입니다. 실제 산업 변화로 표시하지 않습니다.'
        elif set(old['support_ids'] + old['counter_ids']) & superseded:
            out['reason'] = '이전 근거가 정정되어 같은 근거 기준의 변화인지 재검토가 필요합니다.'
        elif old['scope']['as_of_date'] >= j['scope']['as_of_date']:
            out['reason'] = '비교 기준일이 과거→현재 순서가 아닙니다.'
        else:
            allowed = set(j['support_ids'] + j['counter_ids'])
            if not c['evidence_ids'] or not set(c['evidence_ids']) <= allowed:
                raise ValueError('Trend references must be adopted evidence in current judgment')
            observations = []
            for eid in c['evidence_ids']:
                e = used_evidence[eid]
                if e.get('observed_at'):
                    date.fromisoformat(e['observed_at'])
                if (e['nature'] == 'observation' and e.get('observed_at')
                        and old['scope']['as_of_date'] < e['observed_at'] <= j['scope']['as_of_date']
                        and old['scope']['as_of_date'] < e['published_at'] <= j['scope']['as_of_date']):
                    observations.append(eid)
            if not observations:
                out['reason'] = '새 시점의 실제 관측·공개일이 확인되지 않아 추세를 유보합니다.'
            else:
                out.update(direction=c['direction'], label=DIRECTION[c['direction']], reason=c['reason'],
                           evidence_ids=observations)
        return out

    segments, ids, scopes, rows = set(), set(), set(), []
    coverage = []
    for c in value['coverage']:
        required(c, 'segment', 'status', 'reason', 'judgment_ids')
        if not isinstance(c['segment'], str) or c['segment'] in segments or c['status'] not in STATUS:
            raise ValueError('Invalid or duplicate coverage segment')
        if not isinstance(c['judgment_ids'], list) or ((c['status'] == 'reviewed') != bool(c['judgment_ids'])):
            raise ValueError('Reviewed segments require judgments; unreviewed segments cannot claim them')
        segments.add(c['segment']); coverage.append(dict(c))
        for rid in c['judgment_ids']:
            if rid in ids:
                raise ValueError('A judgment may appear only once in a synthesis')
            ids.add(rid)
            j = reviewed(rid)
            if key(j['scope']) in scopes:
                raise ValueError('Choose one current judgment per scope; link older judgments as comparisons')
            scopes.add(key(j['scope']))
            b = j.get('bottleneck', {})
            if not isinstance(b, dict):
                raise ValueError('Bottleneck review must be an object')
            for field in ('severity', 'persistence', 'operational_impact'):
                if b.get(field) is not None and (not isinstance(b[field], str) or not b[field].strip()):
                    raise ValueError('Qualitative bottleneck fields must be text or null')
            assessment = None
            if j.get('assessment_id'):
                a = get(j['assessment_id'], 'assessment')
                if a['scope'] != j['scope']:
                    raise ValueError('Assessment scope differs from judgment')
                a_refs = set(records[j['assessment_id']]['payload']['refs']) - {a.get('supersedes')}
                if not a_refs <= set(j['support_ids'] + j['counter_ids']):
                    raise ValueError('Judgment must review assessment evidence too')
                assessment = {'id': j['assessment_id'], 'result': display_result(a['result'])}
            rows.append({'segment': c['segment'], 'judgment_id': rid, 'scope': j['scope'],
                         'conclusion': j['conclusion'], 'reasoning': j['reasoning'], 'confidence': j['confidence'],
                         'severity': b.get('severity'), 'persistence': b.get('persistence'),
                         'operational_impact': b.get('operational_impact'), 'trend': trend(j), 'assessment': assessment,
                         'support_ids': j['support_ids'], 'counter_ids': j['counter_ids'],
                         'counter_search_limit': j.get('counter_search_limit'),
                         'alternatives': j['alternatives'], 'unknowns': j['unknowns'], 'next_actions': j['next_actions']})
    highlights = value.get('highlight_ids', [r['judgment_id'] for r in rows])
    if not isinstance(highlights, list) or (rows and not highlights) or len(set(highlights)) != len(highlights) or not set(highlights) <= ids:
        raise ValueError('Highlights must refer to unique current rows')
    claims = value.get('synthesis_claims', [])
    if not isinstance(claims, list) or (len(rows) > 1 and not claims):
        raise ValueError('Multiple rows require reviewed cross-scope synthesis claims')
    for claim in claims:
        required(claim, 'text', 'judgment_ids', 'reasoning', 'limitations')
        linked = claim['judgment_ids']
        if not isinstance(linked, list) or not linked or len(set(linked)) != len(linked) or not set(linked) <= ids:
            raise ValueError('Synthesis claims must cite current reviewed rows')
        if not isinstance(claim['limitations'], list) or not claim['limitations']:
            raise ValueError('Preserve explicit limitations in synthesis claims')
        if not all(isinstance(s, str) and s.strip() for s in [claim['text'], claim['reasoning'], *claim['limitations']]):
            raise ValueError('Synthesis prose and limitations must be nonempty text')
    if len(rows) > 1 and not any(len(c['judgment_ids']) > 1 for c in claims):
        raise ValueError('Cross-scope synthesis must connect at least two reviewed rows')
    previous = None
    changes = []
    if value.get('previous_report_id'):
        previous = get(value['previous_report_id'], 'report')
        if previous.get('generation') != FORMAT or previous['as_of_date'] > value['as_of_date']:
            raise ValueError('Previous report must be an earlier supply-chain synthesis')
        before = {key(r['scope']): r for r in previous['rows']}
        after = {key(r['scope']): r for r in rows}
        for k, row in after.items():
            old = before.get(k)
            if not old:
                status = '범위 변경' if any(r['scope']['node_id'] == row['scope']['node_id'] for r in before.values()) else '이번 비교에 추가'
            elif old['judgment_id'] == row['judgment_id']:
                status = '저장된 판단 유지 — 새 관측 검증을 뜻하지 않음'
            elif row['trend']['prior_judgment_id'] != old['judgment_id']:
                status = '판단 교체 — 이전 보고서와 직접 비교 근거 미확인'
            else:
                status = row['trend']['label'] + ' · ' + row['trend']['reason']
            changes.append({'scope': row['scope'], 'status': status, 'before': old['conclusion'] if old else None,
                            'after': row['conclusion'], 'judgment_id': row['judgment_id'],
                            'previous_judgment_id': old['judgment_id'] if old else None})
        for k, old in before.items():
            if k not in after:
                changes.append({'scope': old['scope'], 'status': '이번 비교에서 제외 — 병목 해소를 뜻하지 않음',
                                'before': old['conclusion'], 'after': None, 'previous_judgment_id': old['judgment_id']})
    failures = [a for a in snap['attempts'] if a['status'] not in ('success', 'unchanged')]
    output = {'title': value['title'], 'as_of_date': value['as_of_date'], 'mode': 'synthesis',
              'snapshot_id': snap['snapshot_id'], 'generation': FORMAT, 'action_sha256': digest(action),
              'coverage': coverage, 'rows': rows, 'highlight_ids': highlights, 'changes': changes,
              'previous_report_id': value.get('previous_report_id'), 'source_failures': failures, 'synthesis_claims': claims,
              'approval': 'prepared_not_baseline_approved'}
    output['markdown'] = render(output, used_evidence, documents)
    return store.append('report', request, output, sorted(refs), sorted({e['document_id'] for e in used_evidence.values()}))


def render(value, evidence, documents):
    t = text
    numbers = {r['judgment_id']: i+1 for i, r in enumerate(value['rows'])}
    lines = ['# ' + t(value['title']), '', '기준일: ' + value['as_of_date'], '',
             '검토된 판단을 공급망 위치에 따라 정리했습니다. 표의 순서는 병목 순위가 아닙니다.',
             '각 행의 판단 기준일을 확인하세요. 과거 판단을 포함했다고 보고 기준일에 재검토됐다는 뜻은 아닙니다.', '', '## 핵심 요약', '']
    if not value['rows']:
        lines += ['아직 검토된 판단이 없습니다. 아래 미검토·근거 공백을 먼저 확인해야 합니다.', '']
    for c in value['synthesis_claims']:
        linked = [r for r in value['rows'] if r['judgment_id'] in c['judgment_ids']]
        lines += [t(c['text']), '종합 이유: ' + t(c['reasoning']), '조건·한계: ' + t(c['limitations']),
                  '연결 범위·확신도: ' + ' / '.join(t(scope_label(r['scope'])) + ' (' + t(CONFIDENCE.get(r['confidence'], r['confidence'])) + ')' for r in linked),
                  '근거 판단: ' + ' · '.join('판단 ' + str(numbers[rid]) for rid in c['judgment_ids']), '']
    for r in value['rows']:
        if r['judgment_id'] in value['highlight_ids']:
            lines += [f"- **{t(r['segment'])}**: {t(r['conclusion'])} ({t(r['scope']['geography'])}, {t(r['scope']['product_spec'])}; 확신도 {t(CONFIDENCE.get(r['confidence'], r['confidence']))}).",
                      '  범위: ' + t(scope_label(r['scope'])) + '. ' + r['trend']['label'] + ': ' + t(r['trend']['reason']),
                      '  미확인: ' + t(r['unknowns']) + ' · 근거 판단 ' + str(numbers[r['judgment_id']])]
            lines.append('  반증·대안: ' + t([evidence[e]['claim'] for e in r['counter_ids']] if r['counter_ids'] else r['counter_search_limit']))
    lines += ['', '요약은 선택된 판단이며 검토 범위 전체와 미검토 구간은 아래에 표시합니다.', '',
              '## 공급망 위치별 비교', '', '| 구간 / 적용 범위 | 부족의 강도 | 지속성 | 가동 영향 | 추세 / 확신도 |',
              '|---|---|---|---|---|']
    for r in value['rows']:
        lines.append('| ' + ' | '.join([t(r['segment']) + '<br>' + t(scope_label(r['scope'])),
                     t(r['severity']) if r['severity'] is not None else '미확인',
                     t(r['persistence']) if r['persistence'] is not None else '미확인',
                     t(r['operational_impact']) if r['operational_impact'] is not None else '미확인',
                     r['trend']['label'] + '<br>' + t(r['trend']['reason']) + '<br>' + t(CONFIDENCE.get(r['confidence'], r['confidence'])) + '<br>미확인: ' + t(r['unknowns'])]) + ' |')
    lines += ['', '## 탐색 범위와 남은 공백', '', '| 구간 | 검토 상태 | 선정·제외 / 남은 이유 |', '|---|---|---|']
    for c in value['coverage']:
        lines.append('| ' + ' | '.join([t(c['segment']), STATUS[c['status']], t(c['reason'])]) + ' |')
    for r in value['rows']:
        lines += ['', '## 판단 ' + str(numbers[r['judgment_id']]) + ': ' + t(r['segment']) + ' — 근거와 변화', '', t(r['conclusion']), '',
                  '범위: ' + t(scope_label(r['scope'])), '판단: ' + t(r['reasoning']),
                  '확신도: ' + t(CONFIDENCE.get(r['confidence'], r['confidence'])), '판단 ID: ' + r['judgment_id'], '']
        for role, ids in [('지지', r['support_ids']), ('반증·대안', r['counter_ids'])]:
            for eid in ids:
                lines.append('- ' + role + ': ' + t(evidence[eid]['claim']) + ' · ' + eid)
        if not r['counter_ids']:
            lines.append('반증 탐색 한계: ' + t(r['counter_search_limit']))
        if r['trend'].get('prior_conclusion'):
            lines += ['이전 판단: ' + t(r['trend']['prior_conclusion']),
                      '이전 범위: ' + t(scope_label(r['trend']['prior_scope'])),
                      '변경 검토 이유: ' + t(r['trend']['review_reason'])]
        lines += ['추세: ' + r['trend']['label'] + ' · ' + t(r['trend']['reason']),
                  '경쟁 가설: ' + t(r['alternatives']), '미확인: ' + t(r['unknowns'])]
        if r['assessment']:
            a = r['assessment']['result']
            lines += ['계산 적격성: ' + t(a['scoreability']) + ' · 실제 binding: ' + t(a['binding_status'])]
            if a['scoreability'] in ('Fully Scorable', 'Provisionally Scorable'):
                lines.append('근거한정 총점 범위: ' + t(a['overall']) + ' · 확정 Tier: ' + t(a['tier_confirmed']))
            else:
                lines.append('공통 총점·숫자 Tier는 제시하지 않습니다. 부분 축과 전체 입력은 평가 기록에서 조회합니다.')
            lines.append('평가 ID: ' + r['assessment']['id'])
    lines += ['', '## 이전 보고서에서 달라진 점', '']
    if not value['previous_report_id']:
        lines.append('첫 종합 기록입니다. 과거 대비 변화율이나 순위를 만들지 않았습니다.')
    for c in value['changes']:
        lines += ['- ' + t(scope_label(c['scope'])) + ': ' + t(c['status']),
                  '  이전: ' + t(c['before']) + ' → 현재: ' + t(c['after'])]
    lines += ['', '## 다음 추적 항목', '']
    for r in value['rows']:
        lines.append('- ' + t(r['segment']) + ' (' + t(scope_label(r['scope'])) + '): ' + t(r['next_actions']))
    lines += ['', '## 원문과 재조회 위치', '']
    for eid, e in sorted(evidence.items()):
        d = documents[e['document_id']]
        # Escape link syntax while retaining the original URL in the stored document.
        url = d['url'].replace('(', '%28').replace(')', '%29').replace(' ', '%20')
        label = t(d['producer']).replace('[', '&#91;').replace(']', '&#93;')
        lines += [f"- {eid}: [{label}]({url}) · {t(e['location'])} · 공개일 {e['published_at']} · {e['nature']}",
                  '  원문: ' + t(e['quote']), '  SHA-256: ' + d['sha256']]
    lines += ['', '## 검증 범위', '', 'snapshot: ' + value['snapshot_id'],
              '작성자 검토 입력을 결정론적으로 정리한 초안입니다. 독립 해석 검토·baseline 승인은 별도입니다.',
              f"저장소 전체에서 이 snapshot까지의 미성공/부분 취득 기록: {len(value['source_failures'])}건. 본문 주장의 실패 수나 변화 없음 판정이 아닙니다."]
    return '\n'.join(lines) + '\n'
