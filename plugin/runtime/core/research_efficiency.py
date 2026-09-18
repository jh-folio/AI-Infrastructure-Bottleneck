"""Small transport views and opt-in payload metrics; not host token accounting."""
import json
import hashlib
from pathlib import Path
from research_store import dumps


def page(items, offset=0, limit=10):
    if type(offset) is not int or offset<0 or type(limit) is not int or not 1<=limit<=50:
        raise ValueError('Invalid page')
    return {'items':items[offset:offset+limit], 'total':len(items),
            'next_offset':offset+limit if offset+limit<len(items) else None}


def question_view(q):
    keys=('id','node_id','dimension','question','status','next_action','answer','judgment_ids','scope')
    result={k:q[k] for k in keys if k in q}
    result.update(attempt_count=len(q.get('attempts',[])),
                  review_count=len(q.get('source_reviews',[])),
                  detail_action={'op':'research-question','question_id':q['id']})
    return result


def resume_view(store,cid,offset=0,limit=10,checkpoint_id=None):
    import research_loop as loop
    state=loop.resume(store,cid)
    if checkpoint_id and checkpoint_id!=state['checkpoint_id']:raise ValueError('Stale paging checkpoint; restart from current summary')
    return {k:state[k] for k in ('campaign_id','checkpoint_id','scope_profile','ready_for_review',
                                 'full_inventory_investigated','research_quality_version')} | {
        'view':'compact-v1','question_count':len(state['questions']),
        'quality_issue_count':len(state['quality_issues']),
        'pending':page(state['pending'],offset,limit),
        'instruction':'Read the next pending page or research-question. Full state remains stored; compact output is not completion.'}


def packet_view(store,cid,job_id,offset=0,limit=10,checkpoint_id=None):
    import research_coordination as coordinator
    import research_loop as loop
    value=coordinator.packet(store,cid,job_id)
    state=loop.resume(store,cid)
    if checkpoint_id and checkpoint_id!=state['checkpoint_id']:raise ValueError('Stale paging checkpoint; restart from current summary')
    pending={p.get('question_id') for p in state['pending']}
    questions=[q for q in value['questions'] if q['status'] in ('open','blocked') or q['id'] in pending]
    return {k:value[k] for k in ('job','project_id','campaign_id','as_of_date','instruction')} | {
        'checkpoint_id':state['checkpoint_id'],'view':'compact-v1','nodes':[{k:n[k] for k in ('node_id','name','scope','disposition') if k in n}
                                  for n in value['nodes']],
        'questions':page([question_view(q) for q in questions],offset,limit),
        'stored_question_count':len(value['questions']),
        'note':'Submit changed records only. Fetch research-question before changing an existing record.'}


def export_state(store,cid,destination):
    import research_loop as loop
    raw=dumps(loop.resume(store,cid)).encode('utf-8')
    path=Path(destination).resolve()
    with path.open('xb') as f:f.write(raw)
    return {'path':str(path),'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}


def measure(action,result):
    incoming=dumps(action).encode('utf-8');outgoing=dumps(result).encode('utf-8')
    # No original text, search terms, paths or secrets in the metric row.
    return {'operation':action['op'],'input_bytes':len(incoming),'output_bytes':len(outgoing),
            'input_chars':len(incoming.decode()),'output_chars':len(outgoing.decode()),
            'response_sha256':hashlib.sha256(outgoing).hexdigest(),
            'actual_host_tokens':None,'measurement_scope':'CLI JSON payload only; excludes host context, cached and reasoning tokens'}


def record_metric(store,action,result):
    from monitoring import exclusive
    row=measure(action,result)
    with exclusive(store):
        with (store.folder/'usage_metrics.jsonl').open('a',encoding='utf-8') as f:f.write(dumps(row)+'\n')


def usage_summary(store):
    path=store.folder/'usage_metrics.jsonl';groups={};seen=set();repeated=0
    if path.exists():
        for line in path.read_text(encoding='utf-8').splitlines():
            row=json.loads(line);key=row['operation'];group=groups.setdefault(key,{'calls':0,'input_bytes':0,'output_bytes':0})
            group['calls']+=1
            for name in ('input_bytes','output_bytes'):group[name]+=row[name]
            if row['response_sha256'] in seen:repeated+=1
            seen.add(row['response_sha256'])
    return {'operations':groups,'repeated_response_count':repeated,'actual_host_tokens':None,
            'note':'Payload measurements only. Repetition can be legitimate; no automatic suppression.'}


def batch(store,request,value):
    """Replay-safe ordered writes. Each item commits separately and has a stable request ID."""
    import research
    import source_work
    handlers={'source-plan':source_work.source_plan,'source-import':source_work.import_source,
              'adopt':research.adopt,'judgment':research.judgment,'event':research.event}
    items=value.get('items')
    if not isinstance(items,list) or not 1<=len(items)<=50:raise ValueError('Batch needs 1..50 items')
    names=[i.get('key') for i in items]
    if any(not isinstance(n,str) or not n or len(n)>80 for n in names) or len(set(names))!=len(names):
        raise ValueError('Distinct batch keys required')
    if any(i.get('op') not in handlers for i in items):raise ValueError('Unsupported batch operation')
    ids={};receipts=[]
    def resolve(obj):
        if isinstance(obj,dict):
            if set(obj)=={'$ref'}:
                if obj['$ref'] not in ids:raise ValueError('Reference must name a successful earlier item')
                return ids[obj['$ref']]
            return {k:resolve(v) for k,v in obj.items()}
        if isinstance(obj,list):return [resolve(v) for v in obj]
        return obj
    for item in items:
        try:
            result=handlers[item['op']](store,request+':'+item['key'],resolve(item['data']))
            rid=result['id'];ids[item['key']]=rid
            if result.get('document_id'):ids[item['key']+'.document_id']=result['document_id']
            receipts.append({'key':item['key'],'id':rid,'inserted':result.get('inserted')})
        except (ValueError,KeyError,TypeError,OSError) as exc:
            return {'status':'partial','receipts':receipts,'ids':ids,'failed_key':item['key'],
                    'error_type':type(exc).__name__,'instruction':'Fix the failed item; replay unchanged successful items with the same request ID.'}
    return {'status':'complete','receipts':receipts,'ids':ids,
            'boundary':'Record transport only, not question closure or research completion.'}
