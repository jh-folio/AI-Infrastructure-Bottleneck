"""Append-only semantic-review receipts. Validity is not a machine verdict on meaning."""
from datetime import datetime, timezone
import hashlib
import sys
from importlib.metadata import version, PackageNotFoundError
from pathlib import Path
from research_store import required, digest
from research import data, existing_action
from monitoring import exclusive
from source_work import task_records
import research_loop as loop
import research_scope

ROLES = ('author', 'coordinator')


def now():
    return datetime.now(timezone.utc)


def timestamp(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('Review time must include timezone')
    return parsed


def methods():
    root = Path(__file__).resolve().parent
    files = [root/p for p in ('extraction.py','semantic_review.py','research_quality.py','review_reuse.py','scoring.py')]
    files += sorted((root/'engines').glob('*.py'))
    files += [root.parent.parent/'methodology'/p for p in ('research_rules.md','scoring_v31_reference.md')]
    try:pdf_version=version('pypdf')
    except PackageNotFoundError:pdf_version=None
    return digest({'files':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
                   'python':list(sys.version_info[:3]),'pypdf':pdf_version})


def inventory(store):
    """Only candidate metadata; do not materialize every historical checkpoint."""
    with store.connection() as db:
        docs = {r['id']:dict(r) for r in db.execute('SELECT id,url,sha256,metadata,source_id FROM documents')}
        failures = [dict(r) for r in db.execute("SELECT id,source_id,status FROM attempts WHERE status NOT IN ('success','unchanged')")]
    records = {r['id']:r for kind in ('evidence','judgment','event','fact','assessment') for r in store.records(kind)}
    records.update({r['id']:r for r in task_records(store,'source_plan')})
    for kind in ('node_relation','relation','research_impact'):
        records.update({r['id']:r for r in task_records(store,kind)})
    for record in task_records(store,'monitor_step'):
        if record['payload']['data']['result'].get('status') not in ('success','unchanged'):
            records[record['id']]={**record,'kind':'monitor_failure'}
    for failure in failures:
        key='attempt:'+str(failure['id'])
        records[key]={'id':key,'kind':'source_check','payload':{'data':failure,'refs':[],'documents':[]}}
    return docs, records


def dependency_state(store, cid, qid, dependency_ids):
    head, state = loop.current(store, cid)
    q = next((q for q in state['questions'] if q['id']==qid), None)
    if not q or q['node_id'] not in research_scope.included(state):
        raise ValueError('Question missing or outside active campaign scope')
    node = next(n for n in state['nodes'] if n['node_id']==q['node_id'])
    docs = {r['document_id'] for r in q.get('source_reviews',[])}
    # Prior discovery attempts remain in the question history, but are not all interpreted evidence.
    pending = list(q.get('judgment_ids',[])) + list(dependency_ids)
    records = {}
    while pending:
        rid = pending.pop()
        if rid in records:continue
        r = store.record(rid)
        if r['kind'] not in ('judgment','evidence','event','fact','assessment') and r['payload']['data'].get('type') not in ('node_relation','relation'):
            raise ValueError('Dependencies must be judgments, evidence, events or relations')
        records[rid] = r['payload']
        for child in r['payload']['refs']:
            child_record=store.record(child)
            if child_record['kind']!='task' or child_record['payload']['data'].get('type') in ('node_relation','relation'):
                pending.append(child)
        docs.update(r['payload']['documents'])
    superseded={r['payload']['data'].get('supersedes') for r in store.records('evidence')}
    current_evidence=set()
    for rid in list(q.get('judgment_ids',[]))+list(dependency_ids):
        record=store.record(rid);v=record['payload']['data']
        if record['kind']=='evidence':current_evidence.add(rid)
        else:current_evidence.update(v.get('support_ids',[])+v.get('counter_ids',[])+v.get('evidence_ids',[]))
    if current_evidence & superseded:
        raise ValueError('Referenced evidence was superseded; update the question first')
    versions = {}
    for did in sorted(docs):
        doc = store.document(did)
        if hashlib.sha256(doc['raw']).hexdigest()!=doc['sha256']:
            raise ValueError('Source content hash mismatch')
        if not all(doc.get(k) for k in ('url','producer','mime','metadata')):
            raise ValueError('Missing source metadata')
        versions[did] = {k:doc[k] for k in ('url','producer','mime','sha256','metadata','source_id')}
    # Excludes checkpoint ID and unrelated node progress; includes the complete question.
    frozen = {'campaign_id':cid,'as_of_date':data(store,cid)['as_of_date'],'question':q,
              'node':{k:node[k] for k in loop.DEFINITION_FIELDS if k in node},
              'records':records,'documents':versions,'method_version':methods()}
    return head, state, q, frozen


def receipts(store, cid):
    return [r for r in task_records(store,'semantic_review_record') if r['payload']['data']['campaign_id']==cid]


def latest(store,cid,qid,role):
    matches=[r for r in receipts(store,cid) if r['payload']['data']['question_id']==qid and r['payload']['data']['role']==role]
    return matches[-1] if matches else None


def candidates(store, receipt, current_inventory):
    """Scope bindings filter candidates, never decide their semantic relevance."""
    docs, records=current_inventory
    prior=receipt['observed_inventory'];node=receipt['node_id'];dimension=receipt['dimension']
    dep=receipt['dependencies'];known_urls={d['url'] for d in dep['documents'].values()}
    dependent_nodes={node}
    for r in dep['records'].values():
        scope=r['data'].get('scope',{})
        if isinstance(scope,dict) and scope.get('node_id'):dependent_nodes.add(scope['node_id'])
    plans=[r['payload']['data'] for r in records.values() if r['payload']['data'].get('type')=='source_plan']
    result=[]
    for did,doc in docs.items():
        if did in prior['documents']:continue
        bindings=[b for p in plans if p['source']['url']==doc['url'] and p['campaign_id']==receipt['campaign_id'] for b in p['bindings']]
        related=any(b['node_id'] in dependent_nodes for b in bindings)
        if doc['url'] in known_urls or related or not bindings:
            result.append({'id':did,'kind':'document','reason':'source_version' if doc['url'] in known_urls else 'related_source' if related else 'unclassified_source'})
    for rid,r in records.items():
        if rid in prior['records']:continue
        v=r['payload']['data'];kind=r['kind']
        if v.get('type')=='research_impact':
            if v['campaign_id']==receipt['campaign_id'] and any(t['question_id']==receipt['question_id'] for t in v['targets']):
                result.append({'id':rid,'kind':'task','reason':'dependency_impact_scan'})
            continue
        if kind=='source_check':
            if v['source_id'] in {d['source_id'] for d in dep['documents'].values()}:
                result.append({'id':rid,'kind':kind,'reason':'source_refresh_failed',
                               'source_id':v['source_id'],'observed_status':v['status']})
            continue
        if v.get('type')=='source_plan':
            if v['campaign_id']!=receipt['campaign_id']:continue
            if not any(b['node_id'] in dependent_nodes and (b['node_id']!=node or dimension in b['dimensions']) for b in v['bindings']):continue
        else:
            scope=v.get('scope',{});nid=scope.get('node_id') if isinstance(scope,dict) else None
            endpoints={v.get('from_node_id'),v.get('to_node_id')}
            touches=bool(set(r['payload']['refs']) & set(dep['records']))
            if nid and nid not in dependent_nodes and not touches:continue
            if v.get('type') in ('node_relation','relation') and any(endpoints) and not endpoints & dependent_nodes and not touches:continue
        result.append({'id':rid,'kind':kind,'reason':'new_lead' if v.get('type')=='source_plan' else 'new_evidence_or_dependency'})
    return result


def inspect_receipt(store, receipt, current_inventory=None):
    reasons=[]
    try:
        required(receipt,'reviewer','review_note','trigger_notes','reviewed_at','role','node_id','dimension',
                 'dependencies','dependency_sha256','observed_inventory')
        if receipt['role'] not in ROLES or digest(receipt['dependencies'])!=receipt['dependency_sha256']:
            raise ValueError('Incomplete review provenance')
        timestamp(receipt['reviewed_at'])
        _,_,q,frozen=dependency_state(store,receipt['campaign_id'],receipt['question_id'],receipt['dependency_ids'])
        if digest(frozen)!=receipt['dependency_sha256']:reasons.append('review_dependencies_changed')
        if q['status'] not in ('resolved','bounded'):reasons.append('question_not_closed')
        if now()>=timestamp(receipt['next_review_at']):reasons.append('review_time_due')
    except (KeyError,ValueError,TypeError,OSError):
        reasons.append('review_metadata_or_source_missing')
    try:pending=candidates(store,receipt,current_inventory or inventory(store))
    except (KeyError,ValueError,TypeError):
        reasons.append('review_inventory_missing');pending=[]
    return {'status':'review_required' if reasons else 'pending_relevance' if pending else 'valid',
            'reasons':reasons,'candidates':pending}


def status(store,value):
    required(value,'campaign_id','question_id','role')
    if value['role'] not in ROLES:raise ValueError('Invalid review role')
    record=latest(store,value['campaign_id'],value['question_id'],value['role'])
    if not record:return {'status':'missing','reuse_allowed':False,'instruction':'Read original sources and record actual review first.'}
    result=inspect_receipt(store,record['payload']['data'])
    inventory_hash=digest(result['candidates'])
    if value.get('inventory_sha256') and value['inventory_sha256']!=inventory_hash:
        raise ValueError('Candidate inventory changed; restart candidate paging')
    offset=value.get('offset',0);limit=value.get('limit',10)
    from research_efficiency import page
    return {**result,'candidates':page(result['candidates'],offset,limit),
            'review_id':record['id'],'role':value['role'],'reuse_allowed':result['status']=='valid',
            'inventory_sha256':inventory_hash,
            'reviewer':record['payload']['data'].get('reviewer'),'reviewed_at':record['payload']['data'].get('reviewed_at'),
            'original_record_action':{'op':'record','id':record['id']},
            'instruction':'Valid receipts reuse only this role and question; new synthesis and coordinator review remain separate.'}


def seal(store,request,value):
    required(value,'campaign_id','checkpoint_id','question_id','role','reviewer','review_note','next_review_at','trigger_notes')
    action={'type':'semantic_review_record','data':value}
    with exclusive(store):
        old=existing_action(store,'task',request,action)
        if old:return old
        if value['role'] not in ROLES:raise ValueError('Invalid review role')
        for k in ('reviewer','review_note','trigger_notes'):
            if not isinstance(value[k],str) or not value[k].strip():raise ValueError('Record actual review and triggers')
        if timestamp(value['next_review_at'])<=now():raise ValueError('Next review time must be in the future')
        deps=value.get('dependency_ids',[])
        if not isinstance(deps,list) or any(not isinstance(d,str) for d in deps):raise ValueError('Invalid dependency IDs')
        head,state,q,frozen=dependency_state(store,value['campaign_id'],value['question_id'],deps)
        if head!=value['checkpoint_id']:raise ValueError('Stale checkpoint; review current question')
        if q['status'] not in ('resolved','bounded'):raise ValueError('Review an investigated closed question first')
        from research_quality import inspect_questions
        if any(p['question_id']==q['id'] for p in inspect_questions(store,state['nodes'],state['questions'],frozen['as_of_date'])):
            raise ValueError('Question fails source, scope or repetition checks')
        author=latest(store,value['campaign_id'],q['id'],'author')
        if value['role']=='coordinator' and (not author or author['payload']['data']['reviewer']==value['reviewer'] or
                                            inspect_receipt(store,author['payload']['data'])['status']!='valid'):
            raise ValueError('Coordinator needs a valid author review by a different reviewer')
        prior=latest(store,value['campaign_id'],q['id'],value['role'])
        inv=inventory(store)
        changes=candidates(store,prior['payload']['data'],inv) if prior else [
            {'id':rid} for rid,r in inv[1].items() if r['payload']['data'].get('type')=='research_impact'
            and r['payload']['data']['campaign_id']==value['campaign_id']
            and any(t['question_id']==q['id'] for t in r['payload']['data']['targets'])]
        decisions=value.get('candidate_reviews',{})
        if not isinstance(decisions,dict) or set(decisions)!={c['id'] for c in changes}:
            raise ValueError('Review every new candidate explicitly')
        for decision in decisions.values():
            if decision.get('disposition') not in ('incorporated','not_material') or not isinstance(decision.get('reason'),str) or not decision['reason'].strip():
                raise ValueError('Explain candidate applicability and counterevidence')
        refs=[value['campaign_id'],head]+list(frozen['records'])
        if prior:refs.append(prior['id'])
        payload={**value,'type':'semantic_review_record','action_sha256':digest(action),
                 'dependency_ids':deps,'dependencies':frozen,'dependency_sha256':digest(frozen),
                 'node_id':q['node_id'],'dimension':q['dimension'],'observed_inventory':{'documents':sorted(inv[0]),'records':sorted(inv[1])},
                 'reviewed_at':now().isoformat(),'supersedes':prior['id'] if prior else None}
        return store.append('task',request,payload,refs,sorted(frozen['documents']))


def pending(store,cid,state):
    """Gate opted-in receipts; legacy records remain subject to the full existing review path."""
    bykey={}
    for r in receipts(store,cid):
        v=r['payload']['data'];bykey[(v['question_id'],v['role'])]=(r['id'],v)
    if not bykey:return []
    inv=inventory(store);questions={q['id']:q for q in state['questions']};included=research_scope.included(state);out=[]
    for (qid,role),(rid,receipt) in bykey.items():
        q=questions.get(qid)
        if not q or q['node_id'] not in included or q['status'] not in ('resolved','bounded'):continue
        result=inspect_receipt(store,receipt,inv)
        if result['status']!='valid':
            out.append({'question_id':qid,'node_id':q['node_id'],'dimension':q['dimension'],
                        'action':'review_saved_interpretation','review_id':rid,'role':role,
                        'reasons':result['reasons'] or ['new_candidate_relevance_unreviewed'],
                        'candidate_count':len(result['candidates'])})
    return out


def reuse(store,request,value):
    required(value,'campaign_id','question_id','role','review_id')
    action={'type':'semantic_review_use','data':value}
    with exclusive(store):
        old=existing_action(store,'task',request,action)
        if old:
            current=status(store,value)
            return {**old,'reuse_allowed':current['reuse_allowed'] and current.get('review_id')==value['review_id'],
                    'current_review_status':current['status']}
        result=status(store,value)
        if not result['reuse_allowed'] or result['review_id']!=value['review_id']:
            raise ValueError('Review is missing, superseded, changed or awaiting relevance review')
        head,_=loop.current(store,value['campaign_id'])
        saved=store.append('task',request,{'type':'semantic_review_use',**value,'checkpoint_id':head,
            'action_sha256':digest(action)},[value['review_id'],head])
        return {**saved,'reuse_allowed':True,'current_review_status':'valid'}
