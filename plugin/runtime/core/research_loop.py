"""Persistent agent research queue. Records work; never generates research or scores."""
import json
from contextlib import nullcontext
from pathlib import Path
from research_store import required, digest
from research import data, existing_action
from monitoring import exclusive

DIMENSIONS = ('demand_supply', 'history', 'alternatives', 'operational_impact', 'trend')
DEFINITION_FIELDS = ('node_id','name','scope','lifecycle','predecessor_ids','replacement_ids','effective_date')


def catalog_head(store):
    changes=[r for r in store.records('task') if r['payload']['data'].get('type')=='node_change']
    return changes[-1] if changes else None


def active(node):
    return node.get('lifecycle','active')=='active'


def _save(store, request, action, value, refs=(), documents=()):
    return store.append('task', request, dict(value, action_sha256=digest(action)), refs, documents)


def start(store, request, value):
    required(value, 'objective', 'as_of_date')
    from datetime import date
    date.fromisoformat(value['as_of_date'])
    action={'type':'research_campaign', **value}
    with exclusive(store):
        old=existing_action(store,'task',request,action)
        if old:return old
        ontology=json.loads((Path(__file__).resolve().parents[2]/'ontology/node_ids_v1.json').read_text(encoding='utf-8'))
        nodes=[{'node_id':n['Node_ID'],'name':n['Node_Name'],'disposition':'queued','reason':'',
                'document_ids':[]} for n in ontology['nodes']]
        latest=catalog_head(store)
        if latest:
            if date.fromisoformat(value['as_of_date'])<date.fromisoformat(latest['payload']['data']['change']['effective_date']):
                raise ValueError('New campaign cutoff precedes current catalog; use the historical campaign')
            nodes=[{**n,'disposition':'queued','reason':'','document_ids':[]} for n in latest['payload']['data']['catalog']]
        return _save(store,request,action,{'type':'research_campaign','objective':value['objective'],
            'as_of_date':value['as_of_date'],'nodes':nodes,'questions':[],
            'catalog_revision':latest['id'] if latest else None,
            'note':'Investigation inventory only; no initialized judgments, scores or graph edges.'},
            [latest['id']] if latest else [])


def current(store, campaign_id):
    root=data(store,campaign_id,'task')
    if root.get('type')!='research_campaign':raise ValueError('Expected research campaign')
    head=campaign_id;value=root
    for record in store.records('task'):
        v=record['payload']['data']
        if v.get('type') in ('research_checkpoint','node_change') and v.get('campaign_id')==campaign_id:
            if v['previous_id']!=head:raise ValueError('Research checkpoint fork')
            head=record['id'];value=v
    return head,value


def checkpoint(store, request, value, _action=None, _locked=False):
    required(value,'campaign_id','previous_id','nodes','questions')
    action=_action or {'type':'research_checkpoint',**value}
    with (nullcontext() if _locked else exclusive(store)):
        old=existing_action(store,'task',request,action)
        if old:return old
        head,previous=current(store,value['campaign_id'])
        if value['previous_id']!=head:raise ValueError('Stale checkpoint; resume current research first')
        nodes=value['nodes'];questions=value['questions'];docs=set();refs={head,value['campaign_id']}
        event=value.get('coordination_event')
        if event:
            refs.update([event['job_id'],event['submission_id']])
        if not isinstance(nodes,list) or not isinstance(questions,list):raise ValueError('Expected lists')
        ids=[n['node_id'] for n in nodes]
        if len(set(ids))!=len(ids) or set(ids)!={n['node_id'] for n in previous['nodes']}:
            raise ValueError('Preserve the full investigation inventory')
        for n in nodes:
            before=next(x for x in previous['nodes'] if x['node_id']==n['node_id'])
            if {k:n[k] for k in DEFINITION_FIELDS if k in n}!={k:before[k] for k in DEFINITION_FIELDS if k in before}:
                raise ValueError('Node definitions require node-change; do not edit checkpoint definitions')
            required(n,'disposition','document_ids')
            if n['disposition'] not in ('queued','scanned','selected','investigated'):
                raise ValueError('All initial nodes require investigation; exclusion is not allowed')
            if n['disposition']!='queued':required(n,'reason')
            if n['disposition'] in ('scanned','selected') and not n['document_ids']:
                raise ValueError('Screening needs stored sources')
            docs.update(n['document_ids'])
        qids=set()
        for q in questions:
            required(q,'id','node_id','dimension','question','status','attempts')
            if q['id'] in qids or q['node_id'] not in ids or q['dimension'] not in DIMENSIONS:
                raise ValueError('Invalid question identity or dimension')
            qids.add(q['id'])
            reviews=q.get('source_reviews',[])
            if not isinstance(reviews,list):raise ValueError('Expected source review list')
            for review in reviews:
                required(review,'document_id','location','quote','finding','relevance','role')
                docs.add(review['document_id'])
            if q['status'] not in ('open','resolved','bounded','blocked'):raise ValueError('Invalid question status')
            if not isinstance(q['attempts'],list):raise ValueError('Expected attempt list')
            for a in q['attempts']:
                required(a,'route','outcome','finding','document_ids')
                if a['outcome'] not in ('found','failed','irrelevant','unavailable'):raise ValueError('Invalid source outcome')
                if a['outcome']=='found' and not a['document_ids']:raise ValueError('Found requires stored source')
                docs.update(a['document_ids'])
            if q['status'] in ('open','blocked'):required(q,'next_action')
            else:
                required(q,'answer','closure_reason')
                if not q['attempts']:raise ValueError('Cannot close an uninvestigated question')
                if q['status']=='resolved':
                    required(q,'judgment_ids')
                    if not q['judgment_ids']:raise ValueError('Resolution needs reviewed judgments')
                    for rid in q['judgment_ids']:
                        j=data(store,rid,'judgment')
                        if j['scope']['node_id']!=q['node_id']:raise ValueError('Judgment/question node mismatch')
                        refs.add(rid)
                    if not any(a['outcome']=='found' for a in q['attempts']):raise ValueError('Resolution requires source work')
                if q['status']=='bounded':
                    required(q,'remaining_uncertainty','why_more_search_unlikely')
                    if len({a['route'] for a in q['attempts']})<2:
                        raise ValueError('Bounded uncertainty needs a documented alternative route')
        oldq={q['id']:q for q in previous['questions']};newq={q['id']:q for q in questions}
        if not set(oldq)<=set(newq):raise ValueError('Do not erase investigation questions')
        for qid,q in oldq.items():
            new=newq[qid]
            if any(new[k]!=q[k] for k in ('node_id','dimension','question')) or new['attempts'][:len(q['attempts'])]!=q['attempts']:
                raise ValueError('Preserve question identity and attempt history')
        for doc in docs:store.document(doc)
        revision=head if previous['type']=='node_change' else previous.get('catalog_revision')
        return _save(store,request,action,{**value,'type':'research_checkpoint','catalog_revision':revision},refs,docs)


def question(store,campaign_id,question_id):
    head,state=current(store,campaign_id)
    item=next((q for q in state['questions'] if q['id']==question_id),None)
    if item is None:raise ValueError('Question not found')
    node=next(n for n in state['nodes'] if n['node_id']==item['node_id'])
    return {'campaign_id':campaign_id,'checkpoint_id':head,'node':node,'question':item,
            'read_only':True,'note':'One question record; fetch original source context separately.'}


def patch(store,request,value):
    """Small agent input; unchanged nodes/questions are copied by code, never regenerated."""
    required(value,'campaign_id','previous_id')
    action={'type':'research_patch','data':value}
    prior=existing_action(store,'task',request,action)
    if prior:return prior
    head,state=current(store,value['campaign_id'])
    if head!=value['previous_id']:raise ValueError('Stale checkpoint; read current question before patching')
    nodes={n['node_id']:n for n in state['nodes']}
    questions={q['id']:q for q in state['questions']}
    for field,key,target in (('nodes','node_id',nodes),('questions','id',questions)):
        updates=value.get(field,[])
        if not isinstance(updates,list):raise ValueError('Patch updates must be lists')
        seen=set()
        for item in updates:
            required(item,key)
            if item[key] in seen:raise ValueError('Duplicate patch identity')
            if field=='nodes' and item[key] not in nodes:raise ValueError('Use node-change to add nodes')
            seen.add(item[key]);target[item[key]]=item
    merged={'campaign_id':value['campaign_id'],'previous_id':head,'nodes':list(nodes.values()),'questions':list(questions.values())}
    # The existing lock, append-only attempts and identity checks remain authoritative.
    return checkpoint(store,request,merged,_action=action)


def resume(store,campaign_id):
    head,v=current(store,campaign_id)
    pending=[{'node_id':n['node_id'],'action':'screen','name':n.get('name',n['node_id'])}
             for n in v['nodes'] if active(n) and n['disposition'] in ('queued','excluded')]
    active_ids={n['node_id'] for n in v['nodes'] if active(n)}
    selected={n['node_id'] for n in v['nodes'] if active(n) and n['disposition']=='selected'}
    investigated={n['node_id'] for n in v['nodes'] if active(n) and n['disposition'] not in ('queued','excluded')}
    for node in sorted(investigated):
        for dim in DIMENSIONS:
            if not any(q['node_id']==node and q['dimension']==dim for q in v['questions']):
                pending.append({'node_id':node,'action':'create_question','dimension':dim})
    pending += [dict(question_id=q['id'],node_id=q['node_id'],action=q['next_action'],status=q['status'])
                for q in v['questions'] if q['node_id'] in active_ids and q['status'] in ('open','blocked')]
    resolved=any(q['status']=='resolved' and q['node_id'] in selected for q in v['questions'])
    from research_quality import inspect_questions
    quality_work=inspect_questions(store,v['nodes'],v['questions'],data(store,campaign_id)['as_of_date'])
    pending+=quality_work
    return {'campaign_id':campaign_id,'checkpoint_id':head,'nodes':v['nodes'],'questions':v['questions'],
            'pending':pending,'full_inventory_investigated':not pending,
            'ready_for_review':bool(selected) and resolved and not pending,
            'quality_issues':quality_work,'research_quality_version':3,
            'meaning':'Source locations and repeated reviews checked; interpretation and user acceptance remain separate.'}


def change_nodes(store,request,value):
    """A single atomic record preserves catalog mapping and the campaign checkpoint."""
    from datetime import date
    from copy import deepcopy
    required(value,'campaign_id','previous_id','operation','source_ids','new_nodes','reason','effective_date')
    action={'type':'node_change','data':value}
    with exclusive(store):
        old=existing_action(store,'task',request,action)
        if old:return old
        head,prior=current(store,value['campaign_id'])
        if head!=value['previous_id']:raise ValueError('Stale checkpoint')
        latest=catalog_head(store)
        revision=head if prior['type']=='node_change' else prior.get('catalog_revision')
        if revision!=(latest['id'] if latest else None):raise ValueError('Catalog advanced in another campaign; start a new campaign from current catalog')
        when=date.fromisoformat(value['effective_date'])
        cutoff=date.fromisoformat(data(store,value['campaign_id'])['as_of_date'])
        if when>cutoff:raise ValueError('Node change cannot take effect after campaign cutoff')
        if latest and when<date.fromisoformat(latest['payload']['data']['change']['effective_date']):
            raise ValueError('Do not backdate catalog changes')
        op=value['operation'];sources=value['source_ids'];new=value['new_nodes']
        if not isinstance(sources,list) or not isinstance(new,list):raise ValueError('Expected source and new node lists')
        if not ((op=='add' and not sources and len(new)>=1) or (op=='split' and len(sources)==1 and len(new)>=2)
                or (op=='merge' and len(sources)>=2 and len(new)==1)):
            raise ValueError('Invalid add/split/merge cardinality')
        nodes=deepcopy(prior['nodes']);byid={n['node_id']:n for n in nodes}
        if len(set(sources))!=len(sources) or any(s not in byid or not active(byid[s]) for s in sources):
            raise ValueError('Sources must be distinct active nodes')
        newids=[]
        for n in new:
            required(n,'node_id','name','scope')
            if not all(isinstance(n[k],str) and n[k].strip() for k in ('node_id','name','scope')):
                raise ValueError('Node ID/name/scope must be nonempty text')
            if n['node_id'] in byid or n['node_id'] in newids:raise ValueError('Never reuse a node ID')
            newids.append(n['node_id'])
        for sid in sources:
            byid[sid].update(lifecycle='retired',replacement_ids=newids)
        for n in new:
            nodes.append({k:n[k] for k in ('node_id','name','scope')} | {
                'lifecycle':'active','predecessor_ids':sources,'replacement_ids':[],
                'effective_date':value['effective_date'],'disposition':'queued','reason':'','document_ids':[]})
        catalog=[{k:n[k] for k in DEFINITION_FIELDS if k in n} for n in nodes]
        docs=value.get('document_ids',[])
        for doc in docs:store.document(doc)
        return _save(store,request,action,{'type':'node_change','campaign_id':value['campaign_id'],
            'previous_id':head,'nodes':nodes,'questions':prior['questions'],'catalog':catalog,
            'change':value,'comparison_policy':'No automatic evidence, score, trend or edge transfer'},[head],docs)


def next_work(store,campaign_id,limit=10):
    if isinstance(limit,bool) or not isinstance(limit,int) or not 1<=limit<=30:
        raise ValueError('Use a work packet limit from 1 to 30')
    state=resume(store,campaign_id)
    # Small packets keep historical source excerpts out of the agent context.
    pending=state['pending']
    from source_work import next_details
    return {k:state[k] for k in ('campaign_id','checkpoint_id','ready_for_review')} | {
        'pending_count':len(pending),'next_actions':next_details(store,campaign_id,state,pending[:limit]),
        'more_pending':len(pending)>limit,
        'instruction':'Execute this packet, persist source references and checkpoint; then request the next packet.'}
