"""Persistent agent research queue. Records work; never generates research or scores."""
import json
from pathlib import Path
from research_store import required, digest
from research import data, existing_action
from monitoring import exclusive

DIMENSIONS = ('demand_supply', 'history', 'alternatives', 'operational_impact', 'trend')


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
        return _save(store,request,action,{'type':'research_campaign','objective':value['objective'],
            'as_of_date':value['as_of_date'],'nodes':nodes,'questions':[],
            'note':'Investigation inventory only; no initialized judgments, scores or graph edges.'})


def current(store, campaign_id):
    root=data(store,campaign_id,'task')
    if root.get('type')!='research_campaign':raise ValueError('Expected research campaign')
    head=campaign_id;value=root
    for record in store.records('task'):
        v=record['payload']['data']
        if v.get('type')=='research_checkpoint' and v.get('campaign_id')==campaign_id:
            if v['previous_id']!=head:raise ValueError('Research checkpoint fork')
            head=record['id'];value=v
    return head,value


def checkpoint(store, request, value):
    required(value,'campaign_id','previous_id','nodes','questions')
    action={'type':'research_checkpoint',**value}
    with exclusive(store):
        old=existing_action(store,'task',request,action)
        if old:return old
        head,previous=current(store,value['campaign_id'])
        if value['previous_id']!=head:raise ValueError('Stale checkpoint; resume current research first')
        nodes=value['nodes'];questions=value['questions'];docs=set();refs={head,value['campaign_id']}
        if not isinstance(nodes,list) or not isinstance(questions,list):raise ValueError('Expected lists')
        ids=[n['node_id'] for n in nodes]
        if len(set(ids))!=len(ids) or set(ids)!={n['node_id'] for n in previous['nodes']}:
            raise ValueError('Preserve the full investigation inventory')
        for n in nodes:
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
        return _save(store,request,action,{'type':'research_checkpoint',**value},refs,docs)


def resume(store,campaign_id):
    head,v=current(store,campaign_id)
    pending=[{'node_id':n['node_id'],'action':'screen','name':n.get('name',n['node_id'])}
             for n in v['nodes'] if n['disposition'] in ('queued','excluded')]
    selected={n['node_id'] for n in v['nodes'] if n['disposition']=='selected'}
    investigated={n['node_id'] for n in v['nodes'] if n['disposition'] not in ('queued','excluded')}
    for node in sorted(investigated):
        for dim in DIMENSIONS:
            if not any(q['node_id']==node and q['dimension']==dim for q in v['questions']):
                pending.append({'node_id':node,'action':'create_question','dimension':dim})
    pending += [dict(question_id=q['id'],node_id=q['node_id'],action=q['next_action'],status=q['status'])
                for q in v['questions'] if q['status'] in ('open','blocked')]
    resolved=any(q['status']=='resolved' and q['node_id'] in selected for q in v['questions'])
    return {'campaign_id':campaign_id,'checkpoint_id':head,'nodes':v['nodes'],'questions':v['questions'],
            'pending':pending,'full_inventory_investigated':not pending,
            'ready_for_review':bool(selected) and resolved and not pending,
            'meaning':'Structural research readiness only; source interpretation and user acceptance remain separate.'}


def next_work(store,campaign_id,limit=10):
    if isinstance(limit,bool) or not isinstance(limit,int) or not 1<=limit<=30:
        raise ValueError('Use a work packet limit from 1 to 30')
    state=resume(store,campaign_id)
    # Small packets keep historical source excerpts out of the agent context.
    pending=state['pending']
    return {k:state[k] for k in ('campaign_id','checkpoint_id','ready_for_review')} | {
        'pending_count':len(pending),'next_actions':pending[:limit],
        'more_pending':len(pending)>limit,
        'instruction':'Execute this packet, persist source references and checkpoint; then request the next packet.'}
