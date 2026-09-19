"""Small transport views and opt-in payload metrics; not host token accounting."""
import json
import hashlib
import sqlite3
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
    context=action.get('telemetry',{})
    if not isinstance(context,dict):context={}
    def opaque(name):
        value=context.get(name)
        return hashlib.sha256(str(value).encode()).hexdigest() if value is not None else None
    segments=[]
    def visit(obj):
        if isinstance(obj,dict):
            if isinstance(obj.get('segment_id'),str):segments.append(obj['segment_id'])
            for v in obj.values():visit(v)
        elif isinstance(obj,list):
            for v in obj:visit(v)
    visit(result)
    receipts=result.get('receipts',[]) if isinstance(result,dict) else []
    inserted=result.get('inserted') if isinstance(result,dict) else None
    retry=inserted is False or any(r.get('inserted') is False for r in receipts)
    phase=context.get('phase')
    return {'schema_version':2,'operation':action['op'],'input_bytes':len(incoming),'output_bytes':len(outgoing),
            'input_chars':len(incoming.decode()),'output_chars':len(outgoing.decode()),
            'response_sha256':hashlib.sha256(outgoing).hexdigest(),
            'run_id':opaque('run_id'),'work_unit_id':opaque('work_unit_id'),
            'phase':phase if phase in ('initial','resume','monitor','source','review','record','delivery') else None,
            'outcome':('error' if result.get('status')=='error' else 'partial' if result.get('status')=='partial' else 'success'),
            'retry':retry,'segment_hashes':sorted({hashlib.sha256(s.encode()).hexdigest() for s in segments}),
            'record_apply_count':len(receipts) if receipts else int(inserted is not None),
            'new_review_count':_new_reviews(action,result),
            'reused_review_count':int(action['op']=='review-use' and inserted is True),
            'review_validation_status':result.get('status') if action['op']=='review-status' else None,
            'review_id_hash':hashlib.sha256(result['review_id'].encode()).hexdigest() if action['op']=='review-status' and result.get('review_id') else None,
            'host_model_turns':None,'host_tool_calls':None,'host_compactions':None,
            'actual_host_tokens':None,'measurement_scope':'CLI JSON payload only; excludes host context, cached and reasoning tokens'}


def _new_reviews(action,result):
    """Count only newly committed declarations, never claim verified semantic quality."""
    if action['op']=='review-seal':return int(result.get('inserted') is True)
    def count(op,data):
        updates=data.get('updates',[]) if op=='research-questions-update' else [data] if op=='research-question-update' else []
        return sum(len(u.get('source_reviews_add',[]))+int('semantic_review' in u.get('set',{})) for u in updates)
    if action['op']=='research-batch':
        committed={r['key'] for r in result.get('receipts',[]) if r.get('inserted') is True}
        return sum(count(i['op'],i['data']) for i in action.get('data',{}).get('items',[]) if i['key'] in committed)
    return count(action['op'],action.get('data',{})) if result.get('inserted') is True else 0


def record_metric(store,action,result):
    from monitoring import exclusive
    row=measure(action,result)
    with exclusive(store):
        with (store.folder/'usage_metrics.jsonl').open('a',encoding='utf-8') as f:f.write(dumps(row)+'\n')


def usage_summary(store):
    path=store.folder/'usage_metrics.jsonl';groups={};seen=set();repeated=0
    segments=set();repeated_segments=0;malformed=0;reviews=0;reused=0;invalidated=set()
    if path.exists():
        for line in path.read_text(encoding='utf-8').splitlines():
            try:
                row=json.loads(line);key=row['operation']
                if not all(type(row[k]) is int and row[k]>=0 for k in ('input_bytes','output_bytes')):raise ValueError()
            except (ValueError,KeyError,TypeError):
                malformed+=1;continue
            group=groups.setdefault(key,{'calls':0,'input_bytes':0,'output_bytes':0,'partial':0,'errors':0,'retries':0,'record_apply_count':0})
            group['calls']+=1
            for name in ('input_bytes','output_bytes'):group[name]+=row[name]
            response=row.get('response_sha256')
            if response and response in seen:repeated+=1
            if response:seen.add(response)
            group['partial']+=row.get('outcome')=='partial';group['errors']+=row.get('outcome')=='error'
            group['retries']+=bool(row.get('retry'))
            group['record_apply_count']+=row.get('record_apply_count',0)
            for segment in row.get('segment_hashes',[]):
                if segment in segments:repeated_segments+=1
                segments.add(segment)
            reviews+=row.get('new_review_count',0)
            reused+=row.get('reused_review_count') or 0
            if row.get('review_validation_status') in ('review_required','pending_relevance') and row.get('review_id_hash'):
                invalidated.add(row['review_id_hash'])
    return {'operations':groups,'repeated_response_count':repeated,'actual_host_tokens':None,
            'repeated_segment_count':repeated_segments,'new_review_count':reviews,'malformed_rows':malformed,
            'reused_review_count':reused,'invalidated_review_count':len(invalidated),
            'note':'Payload measurements only. Reuse counts committed receipt uses; invalidations count distinct receipts observed non-valid by review-status, not all stored reviews. Repetition can be legitimate.'}


def batch(store,request,value):
    """Replay-safe ordered writes. Each item commits separately and has a stable request ID."""
    import research
    import source_work
    import research_work_unit
    import research_coordination as coordinator
    handlers={'source-plan':source_work.source_plan,'source-import':source_work.import_source,
              'adopt':research.adopt,'judgment':research.judgment,'event':research.event,
              'research-questions-update':research_work_unit.update,
              'coordination-submit':lambda s,r,v:coordinator.execute(s,'submit',r,v),
              'coordination-apply':lambda s,r,v:coordinator.execute(s,'apply',r,v)}
    items=value.get('items')
    if not isinstance(items,list) or not 1<=len(items)<=50:raise ValueError('Batch needs 1..50 items')
    names=[i.get('key') for i in items]
    if any(not isinstance(n,str) or not n or len(n)>80 for n in names) or len(set(names))!=len(names):
        raise ValueError('Distinct batch keys required')
    if any(n+suffix in names for n in names for suffix in ('.document_id','.result_sha256')):
        raise ValueError('Batch keys collide with generated reference aliases')
    if any(i.get('op') not in handlers for i in items):raise ValueError('Unsupported batch operation')
    terminal={'research-questions-update','coordination-apply'}
    if any(i['op'] in terminal for i in items[:-1]):raise ValueError('Question application must be the final item')
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
            if item['op']=='coordination-submit':
                ids[item['key']+'.result_sha256']=research.data(store,rid)['result_sha256']
            receipts.append({'key':item['key'],'id':rid,'inserted':result.get('inserted')})
        except (ValueError,KeyError,TypeError,OSError,sqlite3.Error) as exc:
            failure={'status':'partial','receipts':receipts,'ids':ids,'failed_key':item['key'],
                    'error_type':type(exc).__name__,'instruction':'Fix the failed item; replay unchanged successful items with the same request ID.'}
            cid=item.get('data',{}).get('campaign_id')
            if isinstance(cid,str):
                import research_loop
                try:
                    failure['checkpoint_id']=research_loop.current(store,cid)[0]
                    failure['next_action']={'op':'research-next','campaign_id':cid,'limit':5}
                except (ValueError,KeyError):pass
            return failure
    result={'status':'complete','receipts':receipts,'ids':ids,
            'boundary':'Record application only; not research completion or semantic certification.'}
    last=items[-1]
    if last['op'] in terminal:
        import research_loop
        cid=resolve(last['data'])['campaign_id']
        result['applied_checkpoint_id']=receipts[-1]['id']
        result['checkpoint_id']=research_loop.current(store,cid)[0]
        result['next_action']={'op':'research-next','campaign_id':cid,'limit':5}
    return result
