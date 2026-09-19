"""Resumable source collection. Research judgments require a separate reviewed action."""
from contextlib import contextmanager
from datetime import date
import os
from research_store import required, digest
from research import data, existing_action


@contextmanager
def exclusive(store):
    # OS lock releases on process termination; the empty file is not a stale ownership token.
    path = store.folder / 'monitor.lock'
    with path.open('a+b') as f:
        if path.stat().st_size == 0:
            f.write(b'0'); f.flush()
        f.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise ValueError('Another monitoring run is active; retry after it finishes') from exc
        try:
            yield
        finally:
            f.seek(0)
            if os.name == 'nt': msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            else: fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def plan(store, request, value):
    required(value, 'name', 'sources')
    if not isinstance(value['sources'], list) or not 1 <= len(value['sources']) <= 100:
        raise ValueError('A monitoring plan needs 1 to 100 explicit sources')
    ids = set()
    for s in value['sources']:
        required(s, 'id', 'op')
        if not isinstance(s['id'], str) or not s['id'].strip() or s['id'] in ids:
            raise ValueError('Duplicate or empty source identifier')
        ids.add(s['id'])
        if s['op'] == 'sec':
            required(s, 'cik', 'dataset')
            if s['dataset'] not in ('submissions', 'companyfacts'): raise ValueError('Invalid SEC dataset')
        elif s['op'] == 'ir': required(s, 'url', 'producer')
        elif s['op'] == 'prices':
            required(s, 'ticker', 'start', 'end')
            if date.fromisoformat(s['start']) >= date.fromisoformat(s['end']): raise ValueError('Invalid price period')
        else: raise ValueError('Only source acquisition operations can be monitored')
    return store.append('task', request, {'type':'monitor_plan', **value})


def record_by_request(store, request):
    with store.connection() as db:
        row = db.execute('SELECT id FROM records WHERE request_id=?', (request,)).fetchone()
    return store.record(row[0]) if row else None


def collect(store, source):
    from research_sources import sec, fetch, prices
    if source['op'] == 'sec': return sec(store, source['cik'], source['dataset'])
    if source['op'] == 'ir': return fetch(store, source['url'], source['producer'], 'ir', source.get('published_at'))
    return prices(store, source['ticker'], source['start'], source['end'])


def run(store, request, value, collector=None):
    required(value, 'plan_id', 'period')
    date.fromisoformat(value['period'])
    p = data(store, value['plan_id'], 'task')
    if p.get('type') != 'monitor_plan': raise ValueError('Expected monitoring plan')
    action = {'type':'monitor_run', **value}
    with exclusive(store):
        previous = existing_action(store, 'task', request, action)
        if previous: return previous
        prefix = 'monitor/' + digest({'project':store.project_id, 'request':request})
        start_request = prefix + '/start'
        start = record_by_request(store, start_request)
        if start:
            if start['payload']['data']['action_sha256'] != digest(action): raise ValueError('Conflicting resumed run')
        else:
            snap = store.snapshot()
            start = store.record(store.append('task', start_request, {'type':'monitor_started',
                'action_sha256':digest(action), 'snapshot_id':snap['snapshot_id'], 'plan_id':value['plan_id'],
                'period':value['period']}, [value['plan_id']])['id'])
        baseline = store.read_snapshot(start['payload']['data']['snapshot_id'])
        latest = {}
        for attempt in baseline['attempts']:
            if attempt['document_id']:
                latest[attempt['source_id']] = attempt['document_id']
        results, refs = [], [value['plan_id'], start['id']]
        for source in p['sources']:
            step = prefix + '/' + digest(source['id'])
            saved = record_by_request(store, step)
            if saved:
                result = saved['payload']['data']['result']
            else:
                try:
                    result = (collector or collect)(store, source)
                    if not isinstance(result, dict) or 'status' not in result:
                        raise ValueError('Adapter did not return an acquisition status')
                    doc = result.get('document_id')
                    document = store.document(doc) if doc else None
                    if result['status'] in ('success', 'unchanged') and not doc:
                        raise ValueError('Successful acquisition must include a stored document')
                    result = {k:result[k] for k in ('status','document_id','source_id') if k in result}
                    result['content_change'] = bool(doc and doc != latest.get(document['source_id']))
                except (ValueError, OSError) as exc:
                    result = {'status':'failed', 'content_change':False, 'error_type':type(exc).__name__,
                              'message':'자료 경로·등록 호스트·기간 설정과 접근 가능 여부를 확인하세요.'}
                saved = store.record(store.append('task', step, {'type':'monitor_step','source':source,
                    'result':result}, [start['id']], [result['document_id']] if result.get('document_id') else [])['id'])
            refs.append(saved['id']); results.append({'source_id':source['id'], **result})
        failures = [r for r in results if r['status'] not in ('success','unchanged')]
        changed = [r for r in results if r.get('content_change')]
        output = {'type':'monitor_run', 'action_sha256':digest(action), **value,
                  'results':results, 'status':'partial' if failures else 'collected',
                  'review_required':bool(changed or failures), 'failed_count':len(failures), 'changed_count':len(changed),
                  'industry_change':'not_assessed', 'snapshot_before':baseline['snapshot_id'],
                  'summary':'수집 실패가 있어 변화 없음을 확인할 수 없습니다.' if failures else
                            ('새 자료가 있어 근거 검토가 필요합니다.' if changed else '수집한 원문은 같았습니다. 산업 상황이 같다는 판정은 아닙니다.')}
        return store.append('task', request, output, refs)


def schedule_packet(store, plan_id):
    p = data(store, plan_id, 'task')
    if p.get('type') != 'monitor_plan': raise ValueError('Expected monitoring plan')
    return {'registered':False, 'plan_id':plan_id, 'name':p['name'],
            'action_template':{'op':'monitor-run','state_dir':str(store.folder),'project_id':store.project_id,
              'request_id':'<stable unique occurrence ID>','data':{'plan_id':plan_id,'period':'<YYYY-MM-DD>'}},
            'instructions':'호스트 예약 기능에 연결할 인계 자료입니다. 예약 등록 증거 없이 활성화로 표시하지 않습니다. 같은 회차 재시도는 같은 요청 ID를 사용합니다. 수집 후 변경 자료만 검토하고 판단/점수는 별도 채택 절차를 따릅니다.'}
