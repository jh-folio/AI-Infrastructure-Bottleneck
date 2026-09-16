"""Connect source acquisition to research questions without adopting conclusions."""
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

from extraction import segments
from monitoring import exclusive
from research import data, existing_action
from research_store import digest, required
from research_loop import DIMENSIONS, active, current

SOURCE_KINDS = {'public_document', 'ir', 'sec_filing', 'sec_submissions', 'sec_companyfacts'}
CAPTURE_KINDS = {'original_bytes', 'extracted_text', 'search_trace'}


def bounded_int(value, low, high, name):
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError('Invalid ' + name)
    return value


def terms_check(terms):
    if (not isinstance(terms, list) or not 1 <= len(terms) <= 30 or
            not all(isinstance(t, str) and 0 < len(t.strip()) <= 160 for t in terms)):
        raise ValueError('Provide 1..30 nonempty explicit search terms per lane')


def source_plan(store, request, value):
    """One stored source can serve distinct, explicitly mapped node questions."""
    required(value, 'campaign_id', 'source', 'bindings')
    action = {**value, 'type': 'source_plan'}
    with exclusive(store):
        old = existing_action(store, 'task', request, action)
        if old:
            return old
        head, state = current(store, value['campaign_id'])
        nodes = {n['node_id'] for n in state['nodes'] if active(n)}
        source = value['source']
        required(source, 'url', 'producer', 'kind')
        if not all(isinstance(source[k], str) and source[k].strip() for k in ('url', 'producer', 'kind')):
            raise ValueError('Source URL, producer and kind must be nonempty strings')
        if source['kind'] not in SOURCE_KINDS:
            raise ValueError('Unsupported source kind')
        from research_sources import public_url, source_hosts
        hosts = ({urlsplit(source['url']).hostname} if source['kind'] == 'public_document'
                 else source_hosts(store, source['kind']))
        public_url(source['url'], hosts, resolve=False)
        if source.get('published_at'):
            date.fromisoformat(source['published_at'])
            cutoff = data(store, value['campaign_id'])['as_of_date']
            if source['published_at'] > cutoff:
                raise ValueError('Planned source publication is after campaign cutoff')
        bindings = value['bindings']
        if not isinstance(bindings, list) or not 1 <= len(bindings) <= 300:
            raise ValueError('Provide explicit node/dimension bindings')
        seen = set()
        for b in bindings:
            required(b, 'node_id', 'dimensions', 'purpose')
            if b['node_id'] not in nodes or not isinstance(b['purpose'], str) or not b['purpose'].strip():
                raise ValueError('Source binding needs an active node and a concrete purpose')
            if (not isinstance(b['dimensions'], list) or not b['dimensions'] or
                    not set(b['dimensions']) <= set(DIMENSIONS)):
                raise ValueError('Invalid source binding dimensions')
            for dimension in b['dimensions']:
                key = b['node_id'], dimension
                if key in seen:
                    raise ValueError('Duplicate source binding')
                seen.add(key)
        docs = []
        if value.get('document_id'):
            doc = store.document(value['document_id'])
            verify_source(doc, source)
            docs.append(doc['id'])
        return store.append('task', request, {**action, 'action_sha256': digest(action),
                            'catalog_checkpoint_id': head}, [value['campaign_id'], head], docs)


def verify_source(doc, source):
    if doc['url'] != source['url'] or doc['producer'] != source['producer']:
        raise ValueError('Stored document does not match the registered original source')
    if source.get('published_at') and doc['metadata'].get('published_at') != source['published_at']:
        raise ValueError('Stored publication date differs; retain the original metadata')


def task_records(store, record_type):
    # Canonical JSON is compact. This is only a prefilter; verify identity and type below.
    # Do not deserialize every large historical research checkpoint once per source.
    with store.connection() as db:
        ids = db.execute("SELECT id FROM records WHERE kind='task' AND instr(payload,?)>0 ORDER BY rowid",
                         ('"type":"' + record_type + '"',)).fetchall()
    result = []
    for row in ids:
        r = store.record(row['id'])
        if r['payload']['data'].get('type') == record_type:
            result.append(r)
    return result


def plans(store, campaign_id):
    return [r for r in task_records(store, 'source_plan') if r['payload']['data']['campaign_id'] == campaign_id]


def acquisitions(store, plan_id):
    return [r for r in task_records(store, 'source_acquisition') if r['payload']['data']['plan_id'] == plan_id]


def acquire(store, request, value, opener=None):
    """An explicit refresh may fetch; a cache reuse never claims a fresh observation."""
    required(value, 'plan_id')
    if not isinstance(value.get('refresh', False), bool):
        raise ValueError('refresh must be boolean')
    action = {**value, 'type': 'source_acquisition', 'mode': 'fetch'}
    with exclusive(store):
        old = existing_action(store, 'task', request, action)
        if old:
            return {**old, **data(store, old['id'])['result']}
        plan = data(store, value['plan_id'], 'task')
        if plan.get('type') != 'source_plan':
            raise ValueError('Expected source plan')
        source = plan['source']
        cutoff = data(store, plan['campaign_id'])['as_of_date']
        cached = None
        if not value.get('refresh', False):
            with store.connection() as db:
                rows = db.execute('SELECT id FROM documents WHERE url=? AND producer=? ORDER BY rowid DESC',
                                  (source['url'], source['producer'])).fetchall()
            for row in rows:
                doc = store.document(row['id'])
                # Search responses and extracted host text are not HTTP-cache substitutes.
                if doc['metadata'].get('capture_kind', 'original_bytes') != 'original_bytes':
                    continue
                if source.get('published_at') and doc['metadata'].get('published_at') != source['published_at']:
                    continue
                if doc['metadata'].get('published_at') and doc['metadata']['published_at'] > cutoff:
                    continue
                cached = doc
                break
        if cached:
            result = {'document_id': cached['id'], 'status': 'cached', 'network_performed': False,
                      'freshness': 'Stored version only; use refresh to check the live source'}
        else:
            from research_sources import fetch
            result = fetch(store, source['url'], source['producer'], source['kind'],
                           source.get('published_at'), opener=opener,
                           registered_hosts={urlsplit(source['url']).hostname})
        docid = result.get('document_id')
        saved = store.append('task', request, {**action, 'result': result, 'action_sha256': digest(action)},
                             [value['plan_id']], [docid] if docid else [])
        return {**saved, **result}


def import_source(store, request, value):
    """Capture bytes obtained through a host tool; record their representation honestly."""
    required(value, 'plan_id', 'path', 'mime', 'capture_kind', 'acquisition_note')
    if value['capture_kind'] not in CAPTURE_KINDS:
        raise ValueError('Invalid capture kind')
    if not isinstance(value['acquisition_note'], str) or not value['acquisition_note'].strip():
        raise ValueError('Explain the actual source acquisition and extraction limits')
    if value['mime'] not in ('text/plain', 'text/html', 'application/xhtml+xml', 'application/pdf',
                            'application/json', 'text/csv'):
        raise ValueError('Unsupported import MIME')
    if value['capture_kind'] != 'original_bytes' and value['mime'] not in ('text/plain', 'application/json'):
        raise ValueError('Host excerpts/search traces must declare their actual text or JSON representation')
    from research_sources import LIMIT
    path = Path(value['path']).resolve()
    with path.open('rb') as stream:
        raw = stream.read(LIMIT + 1)
    if not raw or len(raw) > LIMIT:
        raise ValueError('Empty or oversized source import')
    if value['mime'] == 'application/pdf' and not raw.startswith(b'%PDF-'):
        raise ValueError('Invalid PDF import')
    # A changed file with the same request ID must not silently reuse the old import.
    action = {**value, 'type': 'source_acquisition', 'mode': 'import', 'raw_sha256': digest(raw)}
    with exclusive(store):
        old = existing_action(store, 'task', request, action)
        if old:
            return {**old, **data(store, old['id'])['result']}
        plan = data(store, value['plan_id'], 'task')
        if plan.get('type') != 'source_plan':
            raise ValueError('Expected source plan')
        s = plan['source']
        metadata = {'adapter': 'host_import', 'capture_kind': value['capture_kind'],
                    'published_at': s.get('published_at'), 'acquisition_note': value['acquisition_note']}
        result = store.capture(s, raw, value['mime'], metadata)
        result.update(network_performed=False, capture_kind=value['capture_kind'])
        saved = store.append('task', request, {**action, 'result': result, 'action_sha256': digest(action)},
                             [value['plan_id']], [result['document_id']])
        return {**saved, **result}


def context(store, document_id, focus_terms, counter_terms, max_chars=6000, cursors=None):
    """Two separately budgeted retrieval lanes, with exact continuation positions."""
    terms_check(focus_terms)
    terms_check(counter_terms)
    bounded_int(max_chars, 400, 24000, 'context text budget')
    doc = store.document(document_id)
    blocks, warnings = segments(doc)
    cursors = cursors or {}
    if not isinstance(cursors, dict) or not set(cursors) <= {'focus', 'counter'}:
        raise ValueError('Invalid context cursors')
    lanes = {}
    for name, terms in (('focus', focus_terms), ('counter', counter_terms)):
        if name in cursors and cursors[name] is None:
            lanes[name] = {'terms': terms, 'segments': [], 'next_cursor': None, 'already_exhausted': True}
            continue
        selected = set()
        hits = set()
        for i, block in enumerate(blocks):
            if any(t.casefold() in block['text'].casefold() for t in terms):
                hits.add(i)
                selected.update(range(max(0, i - 1), min(len(blocks), i + 2)))
        indices = sorted(selected)
        cursor = cursors.get(name) or {}
        if not isinstance(cursor, dict):
            raise ValueError('Invalid lane cursor')
        offset = bounded_int(cursor.get('offset', 0), 0, len(indices), 'block offset')
        char = bounded_int(cursor.get('char_offset', 0), 0, 24 * 1024 * 1024, 'character offset')
        if offset == len(indices) and char:
            raise ValueError('Character offset after last matching block')
        if offset < len(indices) and char > len(blocks[indices[offset]]['text']):
            raise ValueError('Character offset exceeds source block')
        left = max_chars // 2
        output = []
        next_cursor = None
        for pos in range(offset, len(indices)):
            block = blocks[indices[pos]]
            if left == 0 or len(output) == 40:
                next_cursor = {'offset': pos, 'char_offset': 0}
                break
            end = min(len(block['text']), char + left)
            output.append({'location': block['location'], 'text': block['text'][char:end],
                           'char_offset': char, 'total_chars': len(block['text']),
                           'term_match': indices[pos] in hits, 'truncated': end < len(block['text'])})
            left -= end - char
            if end < len(block['text']):
                next_cursor = {'offset': pos, 'char_offset': end}
                break
            char = 0
        lanes[name] = {'terms': terms, 'segments': output, 'matching_context_blocks': len(indices),
                       'next_cursor': next_cursor, 'no_match_is_not_absence': True}
    capture = doc['metadata'].get('capture_kind', 'legacy_unspecified')
    return {'document_id': document_id, 'source_url': doc['url'], 'producer': doc['producer'],
            'sha256': doc['sha256'], 'published_at': doc['metadata'].get('published_at'),
            'capture_kind': capture, 'lanes': lanes, 'warnings': warnings,
            'structured_read_required': doc['mime'] == 'application/json',
            'note': 'Retrieval candidates only. Read context and verify scope; counter matches are not automatically counterevidence.'}


def question_packet(store, campaign_id, question_id, focus_terms, counter_terms,
                    offset=0, limit=3, max_chars=6000, route_offset=0):
    bounded_int(offset, 0, 1000000, 'source offset')
    bounded_int(limit, 1, 6, 'source limit')
    bounded_int(max_chars, 400, 10000, 'per-document text budget')
    bounded_int(route_offset, 0, 1000000, 'route offset')
    terms_check(focus_terms)
    terms_check(counter_terms)
    head, state = current(store, campaign_id)
    q = next((q for q in state['questions'] if q['id'] == question_id), None)
    if q is None:
        raise ValueError('Question missing; create it in a checkpoint first')
    if not any(active(n) and n['node_id'] == q['node_id'] for n in state['nodes']):
        raise ValueError('Question belongs to a retired node; use historical records explicitly')
    cutoff = data(store, campaign_id)['as_of_date']
    sources = {}
    routes = []
    acquired_by_plan = {}
    for r in task_records(store, 'source_acquisition'):
        acquired_by_plan.setdefault(r['payload']['data']['plan_id'], []).append(r)
    for r in plans(store, campaign_id):
        p = r['payload']['data']
        binding = next((b for b in p['bindings'] if b['node_id'] == q['node_id'] and q['dimension'] in b['dimensions']), None)
        if not binding:
            continue
        acqs = acquired_by_plan.get(r['id'], [])
        docids = ([p['document_id']] if p.get('document_id') else [])
        docids += [a['payload']['data']['result']['document_id'] for a in acqs if a['payload']['data']['result'].get('document_id')]
        for did in dict.fromkeys(docids):
            sources.setdefault(did, []).append(r['id'])
        routes.append({'plan_id': r['id'], 'url': p['source']['url'], 'purpose': binding['purpose'],
                       'latest_result': acqs[-1]['payload']['data']['result'] if acqs else None,
                       'latest_network_result': next((a['payload']['data']['result'] for a in reversed(acqs)
                           if a['payload']['data']['result'].get('network_performed')), None),
                       'acquire_action': {'op': 'source-acquire', 'data': {'plan_id': r['id']}}})
    # Existing checkpoints remain usable without re-registering all stored documents.
    for a in q['attempts']:
        for did in a.get('document_ids', []):
            sources.setdefault(did, [])
    items = list(sources.items())
    excerpts = []
    for did, pids in items[offset:offset + limit]:
        doc = store.document(did)
        published = doc['metadata'].get('published_at')
        if published and published > cutoff:
            excerpts.append({'document_id': did, 'plan_ids': pids, 'excluded': 'after_campaign_cutoff', 'published_at': published})
            continue
        excerpts.append({**context(store, did, focus_terms, counter_terms, max_chars), 'plan_ids': pids,
                         'date_review_required': not bool(published)})
    return {'campaign_id': campaign_id, 'checkpoint_id': head, 'question_id': question_id,
            'node_id': q['node_id'], 'dimension': q['dimension'], 'question': q['question'],
            'as_of_date': cutoff, 'status': q['status'], 'next_action': q.get('next_action'),
            'scope': q.get('scope'), 'scope_review_required': not bool(q.get('scope')),
            'routes': routes[route_offset:route_offset+20], 'total_routes': len(routes),
            'next_route_offset': route_offset+20 if route_offset+20 < len(routes) else None,
            'sources': excerpts, 'total_documents': len(items),
            'next_offset': offset + limit if offset + limit < len(items) else None,
            'review_record_ids': q.get('judgment_ids', []),
            'instruction': 'Follow source-context cursors or read-document; then review and adopt/judge explicitly. Record attempts and source_reviews in a new checkpoint. This packet does not complete the question.'}


def next_details(store, campaign_id, state, actions):
    """No full source bodies in the queue; return explicit, executable retrieval routes."""
    registered = plans(store, campaign_id)
    out = []
    questions = {q['id']: q for q in state['questions']}
    for action in actions:
        q = questions.get(action.get('question_id'))
        dimension = q['dimension'] if q else action.get('dimension')
        ids = [r['id'] for r in registered if any(b['node_id'] == action['node_id'] and
               (dimension is None or dimension in b['dimensions']) for b in r['payload']['data']['bindings'])]
        item = {**action, 'source_plan_ids': ids, 'source_action': 'Read plans, acquire/import source bytes, then inspect question context'}
        if q:
            item.update(dimension=dimension, question=q['question'],
                        packet_action={'op': 'question-packet', 'campaign_id': campaign_id, 'question_id': q['id']},
                        required_packet_arguments=['focus_terms', 'counter_terms'])
        out.append(item)
    return out
