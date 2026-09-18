"""Persisted host-neutral research coordination; host tools execute the research.

Schema-1 append-only tasks and atomic checkpoint events. This module never
spawns agents, registers schedules, or certifies the meaning of evidence.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone

from monitoring import exclusive
from research import data, existing_action
from research_store import digest, required
import research_loop as loop
import research_scope

DOMAINS = (
    ('semiconductors', '반도체·메모리·패키징·제조장비', [('A',1,11)]),
    ('network', '네트워크·광통신', [('A',12,20)]),
    ('facilities', '데이터센터 건설·냉각·현장 전력', [('B',1,14)]),
    ('grid', '전력장비·계통 접속·송전', [('C',1,9)]),
    ('generation', '발전원·연료·저장', [('C',10,18)]),
    ('process_materials', '반도체 소재·가스', [('D',5,14)]),
    ('bulk_materials', '금속·전기강판·광학 소재', [('D',1,4),('D',15,22)]),
    ('model_supply', 'AI 모델 개발·공급사', [('F',1,1)]),
    ('delivery', '인력·인허가·EPC·입지·자원', [('E',1,13)]),
)
DOMAIN_IDS = {d[0] for d in DOMAINS}
BASE = {f'{prefix}{i:02}':key for key,_,ranges in DOMAINS
        for prefix,start,end in ranges for i in range(start,end+1)}


def clock():
    return datetime.now(timezone.utc)


def text(value, name):
    if not isinstance(value,str) or not value.strip(): raise ValueError('Required text: '+name)
    return value


def integer(value, low, high, name):
    if isinstance(value,bool) or not isinstance(value,int) or not low<=value<=high:
        raise ValueError('Invalid '+name)
    return value


def events(store,cid):
    out=[]
    for r in store.records('task'):
        p=r['payload']['data']; e=p.get('coordination_event')
        if p.get('type')=='research_coordination': e=p
        if e and e.get('campaign_id')==cid: out.append((r['id'],e))
    return out


def state(store,cid):
    loop.current(store,cid)
    result={'config':None,'assignments':{},'jobs':{},'schedule':None,'mode':'running','runs':{},'failures':0}
    for rid,e in events(store,cid):
        op=e['operation']
        if op=='configure':
            result['config']=e['config'];result['assignments']=e['assignments']
        elif op=='assign':result['assignments'].update(e['assignments'])
        elif op=='claim':result['jobs'][rid]={**e,'id':rid,'status':'active'}
        elif op=='renew':
            result['jobs'][e['replaces']]['status']='renewed'
            result['jobs'][rid]={**e,'id':rid,'status':'active'}
        elif op=='submit':
            result['jobs'][e['job_id']].update(status='submitted',submission_id=rid)
        elif op=='apply':result['jobs'][e['job_id']].update(status='applied',checkpoint_id=rid)
        elif op=='release':
            result['jobs'][e['job_id']].update(status='released',reason=e['reason'])
            result['failures']+=1
        elif op=='schedule':result['schedule']={**e,'receipt_id':rid}
        elif op=='control':result['mode']=e['mode']
        elif op=='run':result['runs'][e['host_run_id']]=rid
        elif op=='finish':
            result['mode']='completed';result['completed_checkpoint']=e['completed_checkpoint']
    result['failures'] += sum(j['status']=='active' and datetime.fromisoformat(j['expires_at'])<=clock()
                              for j in result['jobs'].values())
    if result['mode']=='completed' and loop.current(store,cid)[0]!=result.get('completed_checkpoint'):
        result['mode']='paused'
    return result


def mapping(nodes, assignments):
    byid={n['node_id']:n for n in nodes};memo={}
    def get(nid, visiting=()):
        if nid in memo:return memo[nid]
        if nid in visiting:raise ValueError('Node lineage cycle')
        if nid in assignments: answer=assignments[nid]
        elif nid in BASE:answer=BASE[nid]
        else:
            parents=byid[nid].get('predecessor_ids',[])
            inherited={get(p,visiting+(nid,)) for p in parents if p in byid}
            answer=next(iter(inherited)) if len(inherited)==1 and None not in inherited else None
        memo[nid]=answer;return answer
    return {n['node_id']:get(n['node_id']) for n in nodes if loop.active(n)}


def fingerprint(nodes,questions,node_ids):
    return digest({'nodes':[n for n in nodes if n['node_id'] in node_ids],
                   'questions':[q for q in questions if q['node_id'] in node_ids]})


def live_jobs(s):
    return [j for j in s['jobs'].values() if j['status']=='submitted' or
            (j['status']=='active' and datetime.fromisoformat(j['expires_at'])>clock())]


def status(store,cid):
    s=state(store,cid); research=loop.resume(store,cid);owners={n:d for n,d in mapping(research['nodes'],s['assignments']).items() if n in research['scope_profile']['included_node_ids']}
    pending={p['node_id'] for p in research['pending']};jobs=live_jobs(s)
    groups=[]
    for key,name,_ in DOMAINS:
        ids=[n for n,d in owners.items() if d==key]
        groups.append({'domain_id':key,'name':name,'node_ids':ids,
                       'pending_node_ids':[n for n in ids if n in pending],
                       'status':('not_in_scope' if not ids else 'needs_research' if pending.intersection(ids) else 'structurally_reviewable'),
                       'active_job_ids':[j['id'] for j in jobs if j['domain_id']==key]})
    schedule=s['schedule']; cfg=s['config']
    if not cfg: action='configure'
    elif s['mode'] in ('paused','completed'):action='stop_schedule' if schedule and schedule['status'] in ('active','failed') else s['mode']
    elif s['failures']>=cfg['max_failures']:action='limit_reached'
    elif any(d is None for d in owners.values()):action='assign_nodes'
    elif any(j['status']=='submitted' for j in jobs):action='review_submissions'
    elif jobs:action='wait_or_claim_available_domain'
    elif not research['pending']:action='review_and_synthesize'
    else:action='claim'
    return {'campaign_id':cid,'project_id':store.project_id,'checkpoint_id':research['checkpoint_id'],
            'scope_profile':research['scope_profile'],'as_of_date':data(store,cid)['as_of_date'],'mode':s['mode'],'config':cfg,
            'domains':groups,'unmapped_node_ids':[n for n,d in owners.items() if d is None],
            'active_jobs':[{'job_id':j['id'],'domain_id':j['domain_id'],'node_ids':j['node_ids'],
                            'status':j['status'],'expires_at':j['expires_at'],
                            'submission_id':j.get('submission_id')} for j in jobs],
            'pending_count':len(research['pending']),'next_action':action,
            'run_count':len(s['runs']),'failure_count':s['failures'],'schedule':schedule,
            'remaining_scheduled_runs':max(0,cfg['max_runs']-len(s['runs'])) if cfg else None,
            'automatic_execution_verified':False,'read_only':True,
            'boundary':'Host receipts are recorded declarations. Actual unattended execution and research quality require Work validation.'}


def schedule_packet(store,cid):
    s=status(store,cid)
    return {'campaign_id':cid,'project_id':store.project_id,'registered':False,
            'existing_schedule':s['schedule'],'desired_action':'stop' if s['next_action'] in ('stop_schedule','completed','paused','limit_reached') else 'create_or_update',
            'state_dir':str(store.folder),'checkpoint_id':s['checkpoint_id'],
            'prompt':('Continue the existing AI infrastructure research campaign '+cid+' for project '+store.project_id+
                '. Locate the latest project state; never initialize a replacement or silently use an old upload. '
                'Follow plugin/workflows/AUTOMATIC_RESEARCH.md. Read coordination-status, record this host run once, '
                'review pending submissions and claim independent work only while running. Delegate explicitly when supported; '
                'workers return separate source-backed artifacts. The coordinator alone imports, reviews and commits results. '
                'Continue available batches without asking the user to proceed. Preserve the cutoff and all active nodes. '
                'Pause for unavailable current state, repeated failure or configured limits. Stop this schedule after verified '
                'completion or user stop. Notify only meaningful progress, actionable blockage or final delivery.'),
            'instruction':'Use an available host scheduling tool in the existing research chat, then record its actual receipt. This packet creates no schedule.'}


def save(store,request,action,event,refs=(),documents=()):
    return store.append('task',request,{'type':'research_coordination',**event,'action_sha256':digest(action)},refs,documents)


def execute(store,op,request,value):
    required(value,'campaign_id');cid=value['campaign_id'];action={'type':'coordination-'+op,'data':value}
    with exclusive(store):
        old=existing_action(store,'task',request,action)
        if old:return old
        s=state(store,cid);head,current=loop.current(store,cid)
        e={'campaign_id':cid,'operation':op};refs=[cid];docs=[]
        if op=='configure':
            if s['config']:raise ValueError('Coordination already configured; preserve its policy')
            cfg={k:integer(value[k],lo,hi,k) for k,lo,hi in
                 [('concurrency',1,3),('lease_minutes',5,240),('max_runs',1,1000),('max_failures',1,100)]}
            cfg['parallel_supported']=value.get('parallel_supported') is True
            cfg['automatic_resume_requested']=value.get('automatic_resume_requested') is True
            e.update(config=cfg,assignments={})
        elif not s['config']:raise ValueError('Configure coordination first')
        elif op=='assign':
            assignments=value['assignments'];byid={n['node_id']:n for n in current['nodes'] if loop.active(n)}
            if not isinstance(assignments,dict) or not assignments:raise ValueError('Provide node/domain assignments')
            if any(n not in byid or d not in DOMAIN_IDS for n,d in assignments.items()):raise ValueError('Invalid node/domain')
            if any(set(assignments).intersection(j['node_ids']) for j in live_jobs(s)):raise ValueError('Release affected jobs before changing ownership')
            e['assignments']=assignments
        elif op=='claim':
            if s['mode']!='running':raise ValueError('Research is paused or completed')
            if s['failures']>=s['config']['max_failures']:
                raise ValueError('Execution limit reached; preserve incomplete research')
            live=live_jobs(s);capacity=s['config']['concurrency'] if s['config']['parallel_supported'] else 1
            if len(live)>=capacity:raise ValueError('Concurrency occupied; do not duplicate active work')
            owners={n:d for n,d in mapping(current['nodes'],s['assignments']).items() if n in research_scope.included(current)}
            if None in owners.values():raise ValueError('Assign unmapped active nodes before proceeding')
            domain=value['domain_id']
            if domain not in DOMAIN_IDS:raise ValueError('Invalid domain')
            if any(j['domain_id']==domain for j in live):raise ValueError('Domain already has active work')
            pending={p['node_id'] for p in loop.resume(store,cid)['pending']}
            available=[n for n,d in owners.items() if d==domain and n in pending]
            ids=value.get('node_ids',available)
            if not isinstance(ids,list) or not ids or len(ids)!=len(set(ids)) or not set(ids)<=set(available):
                raise ValueError('Claim only distinct pending nodes in this domain')
            e.update(domain_id=domain,node_ids=ids,worker_id=text(value['worker_id'],'worker_id'),
                     base_checkpoint=head,base_fingerprint=fingerprint(current['nodes'],current['questions'],ids),
                     expires_at=(clock()+timedelta(minutes=s['config']['lease_minutes'])).isoformat())
            refs.append(head)
        elif op in ('submit','apply','release','renew'):
            job=s['jobs'].get(value['job_id'])
            if not job:raise ValueError('Unknown job')
            refs.append(job['id']);e['job_id']=job['id']
            if op=='release':
                if job['status'] not in ('active','submitted'):raise ValueError('Job already closed')
                e['reason']=text(value['reason'],'reason')
            else:
                if s['mode']!='running':raise ValueError('Research is paused or completed')
                if op in ('submit','renew') and (job['status']!='active' or datetime.fromisoformat(job['expires_at'])<=clock()):
                    raise ValueError('Job lease expired or is not active; reclaim work')
                if op=='renew':
                    # Renew is represented as a replacement claim; old job is released by reducer below.
                    e.update(replaces=job['id'],domain_id=job['domain_id'],node_ids=job['node_ids'],
                             worker_id=job['worker_id'],base_checkpoint=job['base_checkpoint'],
                             base_fingerprint=job['base_fingerprint'],
                             expires_at=(clock()+timedelta(minutes=s['config']['lease_minutes'])).isoformat())
                if op=='submit':
                    result=value['result'];required(result,'nodes','questions','summary','remaining_work')
                    if not isinstance(result['nodes'],list) or not isinstance(result['questions'],list):raise ValueError('Result lists required')
                    text(result['summary'],'summary')
                    if not isinstance(result['remaining_work'],list):raise ValueError('Remaining work must be a list')
                    for field,key in [('nodes','node_id'),('questions','id')]:
                        items=result[field]
                        if len({i[key] for i in items})!=len(items):raise ValueError('Duplicate result item')
                        if any(i['node_id'] not in job['node_ids'] for i in items):raise ValueError('Result outside assigned nodes')
                    for n in result['nodes']: docs.extend(n.get('document_ids',[]))
                    for q in result['questions']:
                        refs.extend(q.get('judgment_ids',[]))
                        docs.extend(r['document_id'] for r in q.get('source_reviews',[]))
                        docs.extend(d for a in q.get('attempts',[]) for d in a.get('document_ids',[]))
                    e.update(result=result,result_sha256=digest(result))
                if op=='apply':
                    if job['status']!='submitted':raise ValueError('Submit a result before review')
                    submission=data(store,job['submission_id']);result=submission['result'];refs.append(job['submission_id'])
                    if value.get('result_sha256')!=submission['result_sha256']:raise ValueError('Review must match submitted result hash')
                    review=value['review'];required(review,'reviewer','source_checks','scope_checks','counterargument_checks')
                    for k in ('reviewer','source_checks','scope_checks','counterargument_checks'):text(review[k],k)
                    if review['reviewer']==job['worker_id']:raise ValueError('Coordinator review must be separate from worker authoring')
                    owners={n:d for n,d in mapping(current['nodes'],s['assignments']).items() if n in research_scope.included(current)}
                    if any(owners.get(n)!=job['domain_id'] for n in job['node_ids']):raise ValueError('Assigned scope changed; review and reclaim')
                    if fingerprint(current['nodes'],current['questions'],job['node_ids'])!=job['base_fingerprint']:
                        raise ValueError('Assigned questions changed; review and reclaim')
                    nodes={n['node_id']:deepcopy(n) for n in current['nodes']};qs={q['id']:deepcopy(q) for q in current['questions']}
                    for n in result['nodes']:nodes[n['node_id']]=n
                    for q in result['questions']:
                        if q['id'] in qs and qs[q['id']]['node_id']!=q['node_id']:raise ValueError('Question identity collision')
                        qs[q['id']]=q
                    if fingerprint(list(nodes.values()),list(qs.values()),job['node_ids'])==job['base_fingerprint']:
                        raise ValueError('No research progress; release job with a reason instead')
                    from research_quality import inspect_questions
                    problems=inspect_questions(store,list(nodes.values()),list(qs.values()),data(store,cid)['as_of_date'])
                    if any(p['node_id'] in job['node_ids'] for p in problems):raise ValueError('Submitted closure fails source or repetition review; release and investigate')
                    e.update(review=review,submission_id=job['submission_id'])
                    merged={'campaign_id':cid,'previous_id':head,'nodes':list(nodes.values()),'questions':list(qs.values()),'coordination_event':e}
                    # Checkpoint and applied-job receipt are one SQLite append, including crash recovery.
                    return loop.checkpoint(store,request,merged,_action=action,_locked=True)
        elif op=='schedule':
            required(value,'schedule_id','status','host','receipt')
            for k in ('schedule_id','host','receipt'):text(value[k],k)
            if value['status'] not in ('active','paused','stopped','failed'):raise ValueError('Invalid schedule status')
            old_schedule=s['schedule']
            if old_schedule and old_schedule['status'] in ('active','failed') and old_schedule['schedule_id']!=value['schedule_id']:
                raise ValueError('Stop existing schedule before registering another')
            if value['status']=='active' and (s['mode']!='running' or not s['config']['automatic_resume_requested']):
                raise ValueError('Automatic resume is disabled')
            e.update({k:value[k] for k in ('schedule_id','status','host','receipt')})
        elif op=='run':
            runid=text(value['host_run_id'],'host_run_id')
            if runid in s['runs']:raise ValueError('Host run already recorded; use its original request id')
            if s['mode']!='running':raise ValueError('Research is paused or completed')
            if len(s['runs'])>=s['config']['max_runs']:raise ValueError('Run limit reached')
            required(value,'schedule_id','observed_checkpoint')
            if not s['schedule'] or s['schedule']['status']!='active' or value['schedule_id']!=s['schedule']['schedule_id']:
                raise ValueError('Active schedule receipt required')
            if value['observed_checkpoint']!=head:raise ValueError('Restore latest checkpoint before resuming')
            e.update(host_run_id=runid,schedule_id=value['schedule_id'],observed_checkpoint=head,at=clock().isoformat())
        elif op=='control':
            if value['mode'] not in ('paused','running'):raise ValueError('Invalid control mode')
            if s['mode']=='completed':raise ValueError('Completed campaign cannot restart automatically')
            e.update(mode=value['mode'],reason=text(value['reason'],'reason'))
        elif op=='finish':
            from research_quality import completion
            if live_jobs(s):raise ValueError('Release or apply all jobs before completion')
            if not completion(store,cid,value['report_id'])['ready_to_submit']:raise ValueError('Full research and matching report required')
            e.update(report_id=value['report_id'],completed_checkpoint=head,meaning_review=text(value['meaning_review'],'meaning_review'))
            refs.append(value['report_id'])
        else:raise ValueError('Unknown coordination operation')
        return save(store,request,action,e,refs,docs)


def packet(store,cid,job_id):
    s=state(store,cid);job=s['jobs'].get(job_id)
    if not job:raise ValueError('Unknown job')
    _,v=loop.current(store,cid)
    if fingerprint(v['nodes'],v['questions'],job['node_ids'])!=job['base_fingerprint']:
        raise ValueError('Assigned input changed; reclaim work')
    return {'job':job,'project_id':store.project_id,'campaign_id':cid,'as_of_date':data(store,cid)['as_of_date'],
            'nodes':[n for n in v['nodes'] if n['node_id'] in job['node_ids']],
            'questions':[q for q in v['questions'] if q['node_id'] in job['node_ids']],
            'instruction':'Investigate assigned nodes using original sources, history and counterevidence. Return separate artifacts with source bytes/locations and proposed nodes/questions. Do not write the shared DB. Coordinator imports sources and judgments before submission/review. No template closure; preserve unresolved work.'}
