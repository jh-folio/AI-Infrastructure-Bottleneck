"""Small shared-source packets and atomic multi-question deltas; no generated judgments."""
from copy import deepcopy
from research import existing_action
from research_store import required
from monitoring import exclusive
import research_loop as loop
import research_scope
import research_coordination as coord


def packet(store, value):
    """Selection is explicit: a document match is not proof of applicability."""
    required(value, 'campaign_id', 'checkpoint_id', 'question_ids', 'reason', 'expected_output')
    head, state = loop.current(store, value['campaign_id'])
    if head != value['checkpoint_id']:
        raise ValueError('Stale work unit; read current questions')
    qids = value['question_ids']
    if not isinstance(qids, list) or not 1 <= len(qids) <= 10 or len(set(qids)) != len(qids):
        raise ValueError('Select 1..10 distinct questions')
    questions = {q['id']: q for q in state['questions']}
    if not set(qids) <= set(questions):
        raise ValueError('Create missing questions with research-patch first')
    selected = [questions[qid] for qid in qids]
    nodes = {q['node_id'] for q in selected}
    if not nodes <= research_scope.included(state):
        raise ValueError('Work unit outside campaign scope')
    for field in ('reason', 'expected_output'):
        if not isinstance(value[field], str) or not value[field].strip():
            raise ValueError('Explain grouping and expected output')
    job = value.get('job_id')
    if job:
        assigned = coord.packet(store, value['campaign_id'], job)['job']
        if job not in {j['id'] for j in coord.live_jobs(coord.state(store, value['campaign_id']))}:
            raise ValueError('Inactive work owner')
        if not nodes <= set(assigned['node_ids']):
            raise ValueError('Work unit outside assigned nodes')
    documents = set(value.get('document_ids', []))
    for q in selected:
        documents.update(r['document_id'] for r in q.get('source_reviews', []))
        documents.update(d for a in q['attempts'] for d in a.get('document_ids', []))
    from research_efficiency import question_view
    from research_store import digest
    return {'work_unit_id': 'unit-' + digest(value)[:24], 'campaign_id': value['campaign_id'],
            'checkpoint_id': head, 'job_id': job, 'owner': 'coordinator' if not job else 'assigned_worker',
            'node_ids': sorted(nodes), 'question_ids': qids, 'reason': value['reason'],
            'expected_output': value['expected_output'],
            'questions': [question_view(q) for q in selected],
            'documents': [{'document_id': d, 'sha256': store.document(d)['sha256'],
                           'read_action': 'source-context'} for d in sorted(documents)],
            'next_action': {'op': 'research-next', 'campaign_id': value['campaign_id'], 'limit': 5},
            'instruction': 'Read missing question details and source bytes. Share facts, not node conclusions. '
                           'No-source questions still require discovery. Workers return artifacts; only coordinator writes.'}


def update(store, request, value):
    """One strict checkpoint for all supplied deltas. Replay precedes stale/ownership checks."""
    required(value, 'campaign_id', 'previous_id', 'updates')
    action = {'type': 'research_questions_update', 'data': value}
    with exclusive(store):
        old = existing_action(store, 'task', request, action)
        if old:
            return old
        head, state = loop.current(store, value['campaign_id'])
        if head != value['previous_id']:
            raise ValueError('Stale checkpoint; re-read changed questions before applying')
        updates = value['updates']
        if not isinstance(updates, list) or not 1 <= len(updates) <= 10:
            raise ValueError('Provide 1..10 question deltas')
        questions = deepcopy(state['questions'])
        byid = {q['id']: q for q in questions}
        changed = set()
        allowed = {'status','next_action','answer','closure_reason','judgment_ids','remaining_uncertainty',
                   'why_more_search_unlikely','semantic_review','scope','shared_source_review'}
        owned = {n for j in coord.live_jobs(coord.state(store, value['campaign_id'])) for n in j['node_ids']}
        for delta in updates:
            required(delta, 'question_id')
            qid = delta['question_id']
            if qid in changed or qid not in byid:
                raise ValueError('Unknown or repeated question delta')
            if set(delta) - {'question_id', 'set', 'attempts_add', 'source_reviews_add'}:
                raise ValueError('Unsupported delta fields')
            q = byid[qid]
            if q['node_id'] not in research_scope.included(state):
                raise ValueError('Question outside campaign scope')
            if q['node_id'] in owned:
                raise ValueError('Assigned work requires coordination-submit/apply review')
            fields = delta.get('set', {})
            if not isinstance(fields, dict) or not set(fields) <= allowed:
                raise ValueError('Unsupported question fields')
            q.update(fields)
            for field in ('attempts', 'source_reviews'):
                additions = delta.get(field + '_add', [])
                if not isinstance(additions, list):
                    raise ValueError('Expected additions list')
                q.setdefault(field, []).extend(additions)
            changed.add(qid)
        from research_quality import inspect_questions
        from research import data
        problems = inspect_questions(store, state['nodes'], questions, data(store, value['campaign_id'])['as_of_date'])
        changed_nodes = {byid[qid]['node_id'] for qid in changed}
        if any(p['node_id'] in changed_nodes for p in problems):
            raise ValueError('Question closure fails source or repetition review; investigate or keep open')
        return loop.checkpoint(store, request, {'campaign_id': value['campaign_id'], 'previous_id': head,
            'nodes': state['nodes'], 'questions': questions}, _action=action, _locked=True)
