"""Freeze the full catalog and project source-backed views without changing research."""
import json
from pathlib import Path
from research_store import digest, required
from research import data


def freeze_catalog(store, value, rows):
    from research_catalog import load,BASE_VERSION,CURRENT_VERSION
    version=data(store,value['campaign_id']).get('catalog_version',BASE_VERSION) if value.get('campaign_id') else CURRENT_VERSION
    ontology=load(version)
    byid = {n['Node_ID']: n for n in ontology['nodes']}
    checkpoint_id = value.get('checkpoint_id')
    if value.get('campaign_id'):
        from research_loop import current
        head, state = current(store, value['campaign_id'])
        if checkpoint_id and checkpoint_id != head:
            raise ValueError('Catalog checkpoint stale; resume before synthesis')
        checkpoint_id = head
        catalog = state['nodes']
        questions = state['questions']
    else:
        # A narrow report has a declared subset; it is never called a full census.
        catalog = [{'node_id': nid, 'name': byid.get(nid, {}).get('Node_Name', nid), 'disposition': 'untracked'}
                   for nid in dict.fromkeys(r['scope']['node_id'] for r in rows)]
        questions = []
    from research_quality import inspect_questions
    import research_scope
    profile = research_scope.resolve(state) if value.get('campaign_id') else None
    included = set(profile['included_node_ids']) if profile else {n['node_id'] for n in catalog}
    quality = inspect_questions(store,[n for n in catalog if n['node_id'] in included],questions,value['as_of_date'])
    nodes = []
    for original in catalog:
        n = dict(original)
        n['scope_role'] = 'included' if n['node_id'] in included else 'context_only'
        n['module'] = byid.get(n['node_id'], {}).get('Module', 'Other')
        n['lifecycle'] = n.get('lifecycle', 'active')
        n['questions'] = [q for q in questions if q['node_id'] == n['node_id']]
        n['review_issues'] = [q for q in quality if q['node_id'] == n['node_id']]
        nodes.append(n)
    active_ids = {n['node_id'] for n in nodes if n['lifecycle'] == 'active'}
    edges = []
    for nid in sorted(active_ids):
        for source in byid.get(nid, {}).get('Dependencies', '').split():
            if source in active_ids and source != nid:
                edges.append({'from_node_id': source, 'to_node_id': nid, 'kind': 'reference',
                    'reason': '기본 공급망 목록에 등록된 의존관계입니다. 이번 조사에서 기술 범위와 출처를 재확인하기 전의 참고 연결입니다.',
                    'definition_source': {'catalog_version': ontology['version'], 'source_sha256': ontology['source_sha256'],
                                          'location': nid + '/Dependencies'},
                    'review_status': 'definition_unreviewed', 'evidence_ids': []})
    return {'version': 1, 'checkpoint_id': checkpoint_id, 'scope': 'full_active_catalog' if value.get('campaign_id') else 'declared_subset',
            'scope_profile':profile,'ontology_version': ontology['version'], 'nodes': nodes, 'reference_edges': edges}


def relation(store, request, value):
    required(value, 'campaign_id', 'from_node_id', 'to_node_id', 'kind', 'reason', 'scope', 'evidence_ids', 'as_of_date')
    from research_loop import current, active
    from datetime import date
    date.fromisoformat(value['as_of_date'])
    head, state = current(store, value['campaign_id'])
    ids = {n['node_id'] for n in state['nodes'] if active(n)}
    if value['from_node_id'] not in ids or value['to_node_id'] not in ids or value['from_node_id'] == value['to_node_id']:
        raise ValueError('Relation endpoints must be different active nodes')
    if value['kind'] not in ('technical', 'observed', 'conditional'):
        raise ValueError('Invalid reviewed relation kind')
    if not all(isinstance(value[k],str) and value[k].strip() for k in ('reason','scope')):
        raise ValueError('Explain the relation scope and reviewed mechanism')
    if not isinstance(value['evidence_ids'], list) or not value['evidence_ids']:
        raise ValueError('Reviewed relations need source evidence; catalog links remain unreviewed references')
    if value['kind'] != 'technical':
        required(value, 'mechanism', 'period', 'alternative_paths')
    for eid in value['evidence_ids']:
        ev = data(store, eid, 'evidence')
        if ev['decision'] != 'accepted' or ev['published_at'] > value['as_of_date']:
            raise ValueError('Relation needs accepted evidence available at cutoff')
        if value['kind'] == 'observed' and ev['nature'] != 'observation':
            raise ValueError('Observed propagation needs observations')
    return store.append('task', request, {'type': 'node_relation', **value}, [head, *value['evidence_ids']])


def public_source(evidence, document, role=None):
    from urllib.parse import urlsplit
    url = document['url']
    metadata = document.get('metadata', {})
    if isinstance(metadata,str):metadata=json.loads(metadata)
    valid = urlsplit(url).scheme in ('https', 'http') and bool(urlsplit(url).hostname)
    return {'role': role or '검토한 자료', 'claim': evidence.get('claim', evidence.get('finding', '')),
            'quote': evidence.get('quote', ''), 'nature': evidence.get('nature'), 'producer': document['producer'],
            'url': url if valid else None, 'source_status': 'original_url' if valid else 'original_url_missing',
            'location': evidence.get('location'), 'published_at': evidence.get('published_at') or metadata.get('published_at'),
            'capture_kind': metadata.get('capture_kind', 'unspecified'),
            'sha256': document['sha256'], 'document_id': document['id']}


def expand(report, rows, records, docs, relations):
    frozen = report.get('map_catalog')
    if not frozen:
        return [], relations, []  # Historical reports retain their original projection.
    nodes, events = [], []
    superseded = {r['payload']['data'].get('supersedes') for r in records.values() if r['kind'] == 'evidence'}
    for rec in records.values():
        v = rec['payload']['data']
        if rec['kind'] != 'event' or v['scope']['as_of_date'] > report['as_of_date']:
            continue
        linked = [records[eid]['payload']['data'] for eid in v['evidence_ids']]
        if any(eid in superseded for eid in v['evidence_ids']) or any(e['published_at'] > report['as_of_date'] for e in linked):
            continue
        events.append({'event_id': rec['id'], **v, 'sources': [public_source(e, docs[e['document_id']]) for e in linked]})
    for n in frozen['nodes']:
        if n['lifecycle'] != 'active' or n.get('scope_role') == 'context_only':
            continue
        scoped = [r for r in rows if r['scope']['node_id'] == n['node_id']]
        reviews = [public_source(review, docs[review['document_id']], '조사 자료')
                   for q in n['questions'] for review in q.get('source_reviews', []) if review['document_id'] in docs]
        unique = {(s['document_id'], s['location']): s for s in reviews + [s for r in scoped for s in r['sources']]}
        q = n['questions']
        dimensions={x['dimension'] for x in q}
        from research_loop import DIMENSIONS
        status = 'uninvestigated' if not q or n['disposition'] in ('queued', 'excluded', 'untracked') else (
            'in_progress' if any(x['status'] in ('open', 'blocked') for x in q) or n.get('review_issues') or set(DIMENSIONS)-dimensions else 'review_recorded')
        nodes.append({**n, 'judgments': scoped, 'sources': list(unique.values()), 'research_status': status,
            'context_factors': [], 'events': [e for e in events if e['scope']['node_id'] == n['node_id']],
            'summary': scoped[0]['conclusion'] if len(scoped) == 1 else (
                f'{len(scoped)}개 범위의 판단이 있습니다. 범위를 선택해 확인하세요.' if scoped else
                ('; '.join(dict.fromkeys(x.get('answer', '') for x in q if x.get('answer'))) or '아직 조사 결과가 없습니다.'))})
    ids = {n['node_id'] for n in nodes}
    mapped = []
    judgment_nodes = {r['judgment_id']: r['scope']['node_id'] for r in rows}
    for rel in relations:
        a, b = judgment_nodes.get(rel['from_judgment_id']), judgment_nodes.get(rel['to_judgment_id'])
        if a in ids and b in ids and a != b:
            legacy={**rel, 'from_node_id': a, 'to_node_id': b, 'review_status': 'legacy_judgment_relation'}
            if rel['kind']=='technical' and not rel.get('evidence_ids'):
                legacy.update(kind='reference',review_status='legacy_source_review_required',
                              reason='이전 기록의 연결이며 출처 재검토가 필요합니다. '+rel['reason'])
            mapped.append(legacy)
    for rec in records.values():
        v = rec['payload']['data']
        if rec['kind'] != 'task' or v.get('type') != 'node_relation' or v.get('campaign_id') != report.get('campaign_id'):
            continue
        if v['as_of_date'] > report['as_of_date']:continue
        if any(eid in superseded for eid in v['evidence_ids']):
            continue
        ev = [records[eid]['payload']['data'] for eid in v['evidence_ids']]
        entry={**v, 'review_status':'reviewed','sources':[public_source(e,docs[e['document_id']]) for e in ev]}
        context=set((frozen.get('scope_profile') or {}).get('context_node_ids',[]))
        endpoints={v['from_node_id'],v['to_node_id']}
        if endpoints & context:
            for node in nodes:
                if node['node_id'] in endpoints:node['context_factors'].append(entry)
        elif endpoints<=ids:mapped.append(entry)
    reviewed = {(e['from_node_id'], e['to_node_id']) for e in mapped if e['kind'] == 'technical'}
    mapped += [e for e in frozen['reference_edges'] if e['from_node_id'] in ids and e['to_node_id'] in ids and (e['from_node_id'], e['to_node_id']) not in reviewed]
    return nodes, mapped, events
