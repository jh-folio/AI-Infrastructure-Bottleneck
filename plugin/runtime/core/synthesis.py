"""Render reviewed supply-chain judgments from one immutable snapshot.

No model calls, implicit scoring, global ranking or automatic trend inference.
"""
from datetime import date
import html
import json

from research_store import required, digest, dumps
from research import SCOPE, scope_check, existing_action, display_result
from report_review import validate_review

FORMAT = 'supply-chain-synthesis-3'
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
    stage=value.get('research_stage','interim')
    if stage not in ('interim','baseline_review'):raise ValueError('Invalid research stage')
    campaign=None
    if stage=='baseline_review':
        required(value,'campaign_id','checkpoint_id')
        from research_loop import resume
        campaign=resume(store,value['campaign_id'])
        if campaign['checkpoint_id']!=value['checkpoint_id'] or not campaign['ready_for_review']:
            raise ValueError('Research incomplete or checkpoint stale; inspect research-next and continue investigation')
    required(value, 'title', 'as_of_date', 'coverage')
    date.fromisoformat(value['as_of_date'])
    if not isinstance(value['coverage'], list) or not value['coverage']:
        raise ValueError('Declare the intended coverage, including unreviewed segments')
    if value.get('campaign_id'):
        from research_loop import current
        head, _ = current(store,value['campaign_id'])
        if value.get('checkpoint_id') and value['checkpoint_id'] != head:
            raise ValueError('Research checkpoint stale')
        value = dict(value, checkpoint_id=head)
    snap = store.snapshot()
    records = {r['id']: r for r in snap['records']}
    documents = {d['id']: d for d in snap['documents']}
    superseded = {r['payload']['data'].get('supersedes') for r in records.values() if r['kind'] == 'evidence'}
    refs, used_evidence = set(), {}
    if value.get('checkpoint_id'):refs.add(value['checkpoint_id'])

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
                         'qualitative_state': b.get('state','unknown'),
                         'operational_impact': b.get('operational_impact'), 'trend': trend(j), 'assessment': assessment,
                         'support_ids': j['support_ids'], 'counter_ids': j['counter_ids'],
                         'counter_search_limit': j.get('counter_search_limit'),
                         'alternatives': j['alternatives'], 'unknowns': j['unknowns'], 'next_actions': j['next_actions']})
    execution, reviews, execution_docs = validate_review(value, rows, used_evidence, documents)
    for row in rows:
        if row['qualitative_state']=='easing' and row['trend']['direction']!='easing':
            raise ValueError('Qualitative easing needs a comparable, reviewed easing trend')
    highlights = value.get('highlight_ids', [r['judgment_id'] for r in rows])
    if not isinstance(highlights, list) or (rows and not highlights) or len(set(highlights)) != len(highlights) or not set(highlights) <= ids:
        raise ValueError('Highlights must refer to unique current rows')
    claims = value.get('synthesis_claims', [])
    if not isinstance(claims, list) or (len(rows) > 1 and not claims):
        raise ValueError('Multiple rows require reviewed cross-scope synthesis claims')
    for claim in claims:
        required(claim, 'text', 'judgment_ids', 'reasoning', 'limitations', 'comparison_scope')
        if claim['comparison_scope'] not in ('reviewed_subset', 'comprehensive'):
            raise ValueError('Declare the extent of the comparison')
        if claim['comparison_scope'] == 'comprehensive' and any(c['status'] in ('unreviewed', 'missing') for c in coverage):
            raise ValueError('Unreviewed coverage cannot support a comprehensive comparison')
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
        if previous.get('generation') not in (FORMAT, 'supply-chain-synthesis-1','supply-chain-synthesis-2') or previous['as_of_date'] > value['as_of_date']:
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
    if campaign:
        from research_loop import current
        head, campaign_state=current(store,value['campaign_id'])
        if head!=value['checkpoint_id']:raise ValueError('Research advanced during rendering; retry latest checkpoint')
        campaign_root=get(value['campaign_id'],'task')
        if campaign_root['as_of_date']!=value['as_of_date']:raise ValueError('Campaign/report cutoff mismatch')
        from research_loop import active
        from research_scope import included
        included_ids=included(campaign_state)
        selected={n['node_id'] for n in campaign_state['nodes'] if n['node_id'] in included_ids and n['disposition']=='selected'}
        retired={n['node_id'] for n in campaign_state['nodes'] if not active(n)}
        if retired & {r['scope']['node_id'] for r in rows}:
            raise ValueError('Retired nodes cannot be included in the current baseline; preserve historical reports')
        if not selected <= {r['scope']['node_id'] for r in rows}:
            raise ValueError('Baseline report must include selected research nodes')
        conclusions={rid for q in campaign_state['questions'] if q['status']=='resolved' and q['node_id'] in included_ids for rid in q['judgment_ids']}
        if not conclusions <= {r['judgment_id'] for r in rows}:
            raise ValueError('Report must carry the judgments used to resolve research questions')
        if execution['status'] not in ('completed','excluded_by_user'):
            raise ValueError('Baseline research execution incomplete; save interim and continue')
    output = {'title': value['title'], 'as_of_date': value['as_of_date'], 'mode': 'synthesis',
              'research_stage':stage,'campaign_id':value.get('campaign_id'),
              'checkpoint_id':value.get('checkpoint_id'),
              'research_quality_version':3 if campaign else None,
              'snapshot_id': snap['snapshot_id'], 'generation': FORMAT, 'action_sha256': digest(action),
              'coverage': coverage, 'rows': rows, 'highlight_ids': highlights, 'changes': changes,
              'previous_report_id': value.get('previous_report_id'), 'source_failures': failures, 'synthesis_claims': claims,
              'research_execution': execution, 'judgment_reviews': reviews,
              'approval': 'prepared_not_baseline_approved'}
    from supply_view import freeze_catalog
    output['map_catalog'] = freeze_catalog(store,value,rows)
    output['markdown'] = render(output, used_evidence, documents)
    return store.append('report', request, output, sorted(refs), sorted({e['document_id'] for e in used_evidence.values()} | set(execution_docs)))


def render(value, evidence, documents):
    from reader_report import render_reader
    return render_reader(value, evidence, documents, text)
