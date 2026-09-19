"""Changed-source review routing. Dependency reachability never establishes a physical bottleneck."""
from collections import defaultdict, deque
from datetime import timedelta
from research_store import digest, required
from research import existing_action
from monitoring import exclusive
from source_work import task_records
import research_loop as loop
import research_scope
import review_reuse


def clock():
    return review_reuse.now()


def scans(store,cid):
    return [r for r in task_records(store,'research_impact') if r['payload']['data']['campaign_id']==cid]


def dependencies(store,cid,state,inventory):
    docs,records=inventory;edges=defaultdict(set)
    included=research_scope.included(state)
    questions={q['id']:q for q in state['questions'] if q['node_id'] in included}
    for qid,q in questions.items():
        edges['node:'+q['node_id']].add('question:'+qid)
        for j in q.get('judgment_ids',[]):edges[j].add('question:'+qid)
        for r in q.get('source_reviews',[]):edges[r['document_id']].add('question:'+qid)
    for rid,r in records.items():
        v=r['payload']['data']
        if v.get('type')=='research_impact':continue
        if v.get('campaign_id') and v['campaign_id']!=cid:continue
        for did in r['payload']['documents']:edges[did].add(rid)
        for ref in r['payload']['refs']:
            if ref in records:edges[ref].add(rid)
        scope=v.get('scope',{});nid=scope.get('node_id') if isinstance(scope,dict) else None
        if nid in included:edges[rid].add('node:'+nid)
        if v.get('type')=='source_plan' and v['campaign_id']==cid:
            for did,d in docs.items():
                if d['url']==v['source']['url']:edges[did].add(rid)
            for b in v['bindings']:
                for qid,q in questions.items():
                    if q['node_id']==b['node_id'] and q['dimension'] in b['dimensions']:edges[rid].add('question:'+qid)
        if v.get('type')=='node_relation':
            for nid in (v['from_node_id'],v['to_node_id']):
                if nid in included:edges[rid].add('node:'+nid)
            edges['node:'+v['from_node_id']].add(rid)
        if v.get('type')=='relation':
            for key in ('from_judgment_id','to_judgment_id'):edges[rid].add(v[key])
        if r['kind']=='source_check':
            for did,d in docs.items():
                if d['source_id']==v['source_id']:edges[rid].add(did)
    # Versions are connected as candidates, not asserted equal observations.
    versions=defaultdict(list)
    for did,d in docs.items():versions[d['url']].append(did)
    for ids in versions.values():
        for did in ids:edges[did].update(x for x in ids if x!=did)
    for r in store.records('report'):
        for ref in r['payload']['refs']:edges[ref].add('report:'+r['id'])
    return edges,questions


def scan(store,request,value):
    required(value,'campaign_id','checkpoint_id')
    action={'type':'research_impact','data':value}
    with exclusive(store):
        old=existing_action(store,'task',request,action)
        if old:return receipt(store,old)
        cid=value['campaign_id'];head,state=loop.current(store,cid)
        if head!=value['checkpoint_id']:raise ValueError('Stale checkpoint; resume before scanning')
        history=scans(store,cid);prior=history[-1]['payload']['data'] if history else None
        interval=value.get('discovery_interval_days',prior['discovery_interval_days'] if prior else 30)
        if type(interval) is not int or not 1<=interval<=365:raise ValueError('Discovery interval must be 1..365 days')
        inv=review_reuse.inventory(store)
        current_records={rid for rid,r in inv[1].items() if r['payload']['data'].get('type')!='research_impact'}
        previous=prior['observed_inventory'] if prior else {'documents':list(inv[0]),'records':list(current_records)}
        explicit_docs=value.get('document_ids',[]);explicit_records=value.get('record_ids',[])
        if not isinstance(explicit_docs,list) or not set(explicit_docs)<=set(inv[0]):raise ValueError('Unknown changed document')
        if not isinstance(explicit_records,list) or not set(explicit_records)<=current_records:raise ValueError('Unknown changed record')
        changed=set(inv[0])-set(previous['documents']) | current_records-set(previous['records']) | set(explicit_docs) | set(explicit_records)
        due=bool(value.get('explore')) or bool(prior and clock()>=review_reuse.timestamp(prior['next_discovery_at']))
        next_date=(clock()+timedelta(days=interval)).isoformat() if not prior or due else prior['next_discovery_at']
        edges,questions=dependencies(store,cid,state,inv)
        affected={};reports=set();unknown=[]
        for trigger in sorted(changed):
            queue=deque([(trigger,[trigger])]);seen=set();found=False
            while queue:
                key,path=queue.popleft()
                if key in seen:continue
                seen.add(key)
                if key.startswith('question:') and key[9:] in questions:
                    qid=key[9:];found=True
                    row=affected.setdefault(qid,{'question_id':qid,'node_id':questions[qid]['node_id'],'trigger_ids':[],'paths':[]})
                    row['trigger_ids'].append(trigger);row['paths'].append(path)
                if key.startswith('report:'):reports.add(key[7:])
                queue.extend((n,path+[n]) for n in sorted(edges.get(key,())))
            if not found:
                record=inv[1].get(trigger,{})
                value_data=record.get('payload',{}).get('data',{})
                scope=value_data.get('scope',{})
                unscoped=not isinstance(scope,dict) or not scope.get('node_id')
                if trigger in inv[0] or (record.get('kind') in ('event','evidence','assessment','source_check','monitor_failure') and unscoped):unknown.append(trigger)
        prior_scope=set(prior['included_node_ids']) if prior else research_scope.included(state)
        new_nodes=research_scope.included(state)-prior_scope
        for qid,q in questions.items():
            if due or unknown or q['node_id'] in new_nodes:
                row=affected.setdefault(qid,{'question_id':qid,'node_id':q['node_id'],'trigger_ids':[],'paths':[]})
                row['trigger_ids']+=unknown
                row['reason']='periodic_discovery' if due else 'unclassified_new_source' if unknown else 'scope_change'
        payload={'type':'research_impact','action_sha256':digest(action),'campaign_id':cid,'checkpoint_id':head,
                 'created_at':clock().isoformat(),'next_discovery_at':next_date,'discovery_interval_days':interval,
                 'included_node_ids':sorted(research_scope.included(state)),
                 'observed_inventory':{'documents':sorted(inv[0]),'records':sorted(current_records)},
                 'targets':list(affected.values()),'affected_report_ids':sorted(reports),
                 'changed_ids':sorted(changed),'periodic_discovery_due':due,
                 'boundary':'Candidates for source and synthesis review; not observed delay propagation or scores.'}
        saved=store.append('task',request,payload,[cid,head],explicit_docs)
        return receipt(store,saved)


def receipt(store,result):
    v=store.record(result['id'])['payload']['data']
    return {**result,'affected_question_count':len(v['targets']),'affected_report_count':len(v['affected_report_ids']),
            'next_discovery_at':v['next_discovery_at'],'detail_action':{'op':'impact-details','scan_id':result['id']},
            'next_action':{'op':'research-dispatch','campaign_id':v['campaign_id']},'research_complete':False}


def details(store,scan_id,offset=0,limit=10):
    from research_efficiency import page
    v=store.record(scan_id)['payload']['data']
    if v.get('type')!='research_impact':raise ValueError('Expected impact scan')
    return {'scan_id':scan_id,'targets':page(v['targets'],offset,limit),
            'affected_report_ids':v['affected_report_ids'],'boundary':v['boundary']}


def pending(store,cid,state):
    """A fresh author review acknowledges routed changes, including legacy questions without receipts."""
    latest={}
    for r in review_reuse.receipts(store,cid):
        v=r['payload']['data']
        if v['role']=='author':latest[v['question_id']]=v
    questions={q['id']:q for q in state['questions']};included=research_scope.included(state);result={}
    for r in scans(store,cid):
        for target in r['payload']['data']['targets']:
            qid=target['question_id'];q=questions.get(qid)
            if not q or q['node_id'] not in included or q['status'] not in ('resolved','bounded'):continue
            if r['id'] in latest.get(qid,{}).get('observed_inventory',{}).get('records',[]):continue
            result[qid]={'question_id':qid,'node_id':q['node_id'],'dimension':q['dimension'],
                         'action':'review_changed_dependencies','reasons':['unreviewed_impact_scan'],'scan_id':r['id']}
    return list(result.values())


def dispatch(store,cid,max_nodes=3):
    import research_coordination as coord
    if type(max_nodes) is not int or not 1<=max_nodes<=10:raise ValueError('Use 1..10 nodes per proposed job')
    s=coord.status(store,cid);config=s['config'];actions=[]
    if config and s['next_action'] in ('claim','wait_or_claim_available_domain'):
        capacity=config['concurrency'] if config['parallel_supported'] else 1
        slots=max(0,capacity-len(s['active_jobs']))
        # Least recently claimed domain first prevents repeated early-domain starvation.
        events=coord.events(store,cid);last={e['domain_id']:i for i,(_,e) in enumerate(events) if e['operation']=='claim'}
        for d in sorted(s['domains'],key=lambda d:last.get(d['domain_id'],-1)):
            if len(actions)>=slots:break
            if d['active_job_ids'] or not d['pending_node_ids']:continue
            actions.append({'op':'coordination-claim','data':{'campaign_id':cid,'domain_id':d['domain_id'],
                'node_ids':d['pending_node_ids'][:max_nodes]},'required_host_fields':['request_id','data.worker_id']})
    return {'campaign_id':cid,'checkpoint_id':s['checkpoint_id'],'next_action':s['next_action'],
            'claim_actions':actions,'active_jobs':s['active_jobs'],'pending_count':s['pending_count'],
            'instruction':'Coordinator executes claims with stable IDs, then uses actual host workers or sequential research. '
                          'Wait on host completion, not repeated model polling. No schedule or worker has been started by this read-only command.'}
