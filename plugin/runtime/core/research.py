"""Research commands: lineage, reviewed judgments, snapshots and cited drafts."""
from datetime import date
from pathlib import Path
import json
from decimal import Decimal, ROUND_FLOOR, ROUND_CEILING
from research_store import required, digest, dumps
from extraction import fact_candidates, text_packet, locate
from scoring import calculate, ENGINE, VERSION, WEIGHTS, replay

SCOPE = ('node_id','geography','product_spec','scenario','horizon','as_of_date','protocol_version','methodology_version')


def display_result(result):
    value=json.loads(dumps(result))
    for bounds in [value['overall'],*value['axes'].values()]:
        for key,mode in (('low',ROUND_FLOOR),('high',ROUND_CEILING)):
            if bounds[key] is not None:
                bounds[key]=float(Decimal(str(bounds[key])).quantize(Decimal('0.1'),rounding=mode))
        if bounds['mid'] is not None:
            bounds['mid']=round(bounds['mid'],1)
    return value


def scope_check(scope):
    required(scope,*SCOPE)
    if scope['protocol_version']!='3.1' or scope['methodology_version']!='3.1':
        raise ValueError('Only protocol/scoring 3.1 supported')
    date.fromisoformat(scope['as_of_date'])


def data(store, rid, kind=None):
    record=store.record(rid)
    if kind and record['kind']!=kind:
        raise ValueError('Wrong reference kind')
    return record['payload']['data']


def existing_action(store,kind,request,action):
    with store.connection() as db:
        row=db.execute('SELECT id FROM records WHERE request_id=?',(request,)).fetchone()
    if row:
        record=store.record(row['id'])
        if record['kind']!=kind or record['payload']['data'].get('action_sha256')!=digest(action):
            raise ValueError('Conflicting request id; use a new revision request')
        return {'id':record['id'],'inserted':False}


def save_facts(store, doc, taxonomy, tag, as_of):
    rows=fact_candidates(store.document(doc),taxonomy,tag,as_of)
    ids=[]
    for row in rows:
        result=store.append('fact','fact:'+digest(row),row,documents=[doc])
        ids.append(result['id'])
    return {'count':len(ids),'fact_ids':ids[:50],'fact_ids_truncated':len(ids)>50,
            'next_action':'Use paginated list kind=fact and record for details','status':'candidates_only'}


def adopt(store, request, value):
    required(value,'document_id','location','quote','claim','scope','nature','grade','confidence','confidence_reason','producer_family','source_tier','decision','review_reason')
    scope_check(value['scope'])
    if value['decision'] not in ('accepted','rejected','hold') or value['grade'] not in ('A','B','C','D'):
        raise ValueError('Invalid review decision or grade')
    if value['nature'] not in ('observation','external_plan','external_forecast','inference','scenario'):
        raise ValueError('Invalid evidence nature')
    if isinstance(value['source_tier'],bool) or value['source_tier'] not in (1,2,3,4,5) or value['confidence'] not in ('Low','Medium','High'):
        raise ValueError('Invalid confidence or source tier')
    doc=store.document(value['document_id'])
    if value['decision']=='accepted' and (doc['metadata'].get('capture_kind')=='search_trace' or
            doc['url'].startswith(('web-search:', 'web-open:'))):
        raise ValueError('Search/tool response is discovery evidence; capture and review the original source before adoption')
    excerpt=locate(doc,value['location'])
    if value['quote'] not in excerpt:
        raise ValueError('Quoted text not found at source location')
    published=value.get('published_at') or doc['metadata'].get('published_at')
    if doc['metadata'].get('published_at') and published!=doc['metadata']['published_at']:
        raise ValueError('Publication date conflicts with stored source metadata')
    if not published:
        raise ValueError('Publication date must be reviewed explicitly')
    date.fromisoformat(published)
    if published>value['scope']['as_of_date']:
        raise ValueError('Evidence unavailable at analysis as-of date')
    if value.get('observed_at'):
        date.fromisoformat(value['observed_at'])
        if value['nature']=='observation' and value['observed_at']>value['scope']['as_of_date']:
            raise ValueError('Future target is not an observed realization')
    refs=[]
    if value.get('supersedes'):
        old=data(store,value['supersedes'],'evidence')
        if old['scope']!=value['scope']:
            raise ValueError('Review revision scope mismatch')
        refs.append(value['supersedes'])
    value=dict(value,published_at=published,source_sha256=doc['sha256'])
    return store.append('evidence',request,value,refs, [doc['id']])


def current_evidence(store, ids, scope):
    superseded={r['payload']['data'].get('supersedes') for r in store.records('evidence')}
    out=[]
    for rid in ids:
        e=data(store,rid,'evidence')
        if rid in superseded or e['decision']!='accepted':
            raise ValueError('Evidence is held, rejected or superseded')
        if e['scope']!=scope:
            raise ValueError('Evidence scope mismatch')
        out.append(e)
    return out


def judgment(store, request, value):
    required(value,'question','scope','conclusion','support_ids','counter_ids','alternatives','unknowns','next_actions','confidence','reasoning')
    scope_check(value['scope'])
    if value.get('bottleneck',{}).get('state','unknown') not in ('constraint','watch','easing','adequate','unknown'):
        raise ValueError('Invalid qualitative state; never convert qualitative judgments to invented scores')
    ids=value['support_ids']+value['counter_ids']
    if value['confidence'] not in ('Low','Medium','High'):
        raise ValueError('Invalid judgment confidence')
    if not ids:
        raise ValueError('Judgment requires adopted evidence; use a task for unanswered questions')
    current_evidence(store,ids,value['scope'])
    if not isinstance(value['alternatives'],list) or not value['alternatives']:
        raise ValueError('Record competing hypotheses')
    if not value['counter_ids'] and not value.get('counter_search_limit'):
        raise ValueError('Explain missing counterevidence search coverage')
    return store.append('judgment',request,value,ids)


def assess(store, request, value):
    existing=existing_action(store,'assessment',request,value)
    if existing:
        return existing
    required(value,'scope','factors','confidence','confidence_reason','conflicts','scope_coherent','change_cause')
    scope_check(value['scope'])
    ids=set(value.get('direction_evidence_ids',[])) | set(value.get('binding_evidence_ids',[]))
    for factor in value['factors'].values():
        ids.update(factor.get('evidence_ids',[]))
    evidence=current_evidence(store,sorted(ids),value['scope'])
    evmap=dict(zip(sorted(ids),evidence))
    for factor in value['factors'].values():
        if factor.get('status')=='EvidenceBounded':
            cited=[evmap[x] for x in factor['evidence_ids']]
            worst=max((x['grade'] for x in cited),default='D')
            if factor['grade']<worst:
                raise ValueError('Factor grade exceeds cited evidence grade')
    families={e['producer_family'] for e in evidence}
    source_families={store.document(e['document_id'])['source_id'] for e in evidence}
    corequalified=all(any(evmap[e]['grade'] in ('A','B') for e in value['factors'].get(f,{}).get('evidence_ids',[]))
                      or min(len({evmap[e]['producer_family'] for e in value['factors'].get(f,{}).get('evidence_ids',[]) if evmap[e]['grade']=='C'}),
                             len({store.document(evmap[e]['document_id'])['source_id'] for e in value['factors'].get(f,{}).get('evidence_ids',[]) if evmap[e]['grade']=='C'}))>=2
                      for f in ('shortage','system_criticality'))
    binding=value.get('binding_status','NotDemonstrated')
    if binding not in ('ObservedBinding','ConditionalBinding','NotDemonstrated','DemonstratedNonBinding'):
        raise ValueError('Invalid binding state')
    if binding!='NotDemonstrated':
        required(value,'binding_evidence_ids','binding_reason')
        if not value['binding_evidence_ids']:
            raise ValueError('Binding needs evidence')
    if binding=='ObservedBinding':
        required(value,'project_id','required_path','schedule_impact','alternatives_and_float')
        if any(evmap[e]['nature']!='observation' for e in value['binding_evidence_ids']):
            raise ValueError('Forecast is not observed binding')
    inputs=dict(value,methodology_version=VERSION,independent_producers=min(len(families),len(source_families)),
                tier12_present=any(e['source_tier'] in (1,2) for e in evidence),
                tier1_core_evidence_qualified=corequalified)
    result=calculate(inputs)
    artifacts={f: {'sha256':digest((Path(__file__).parent/f).read_bytes()),
                   'source':(Path(__file__).parent/f).read_bytes().decode('utf-8')}
               for f in ('scoring.py','research.py','engines/d3_1_0.py')}
    snapshot=store.snapshot()
    payload={'scope':value['scope'],'inputs':inputs,'result':result,'engine_artifacts':artifacts,'action_sha256':digest(value),
             'input_snapshot_id':snapshot['snapshot_id'],'change_cause':value['change_cause'],
             'approval':'prepared_not_baseline_approved'}
    refs=sorted(ids)
    if value.get('supersedes'):
        data(store,value['supersedes'],'assessment');refs.append(value['supersedes']);payload['supersedes']=value['supersedes']
    return store.append('assessment',request,payload,refs)


def event(store,request,value):
    required(value,'scope','event_type','event_date','description','evidence_ids','materiality','review_reason')
    scope_check(value['scope']);date.fromisoformat(value['event_date'])
    if not value['evidence_ids']:
        raise ValueError('Event requires evidence')
    evidence=current_evidence(store,value['evidence_ids'],value['scope'])
    if value['event_type'] in ('observation','realization'):
        if value['event_date']>value['scope']['as_of_date'] or any(e['nature']!='observation' for e in evidence):
            raise ValueError('Realization events need dated observations, not future plans')
    return store.append('event',request,value,value['evidence_ids'])


def packet(store, question, scope, terms, max_chars=24000, document_ids=None):
    scope_check(scope)
    if not 1000<=max_chars<=60000:
        raise ValueError('Packet budget must be 1000..60000 characters')
    snap=store.snapshot()
    ids=document_ids if document_ids is not None else [d['id'] for d in snap['documents']]
    result={'question':question,'scope':scope,'snapshot_id':snap['snapshot_id'],'sources':[],
            'note':'Candidates only. Review demand, usable supply, shortage, schedule impact and counterevidence; no automatic adoption.'}
    left=max_chars
    omitted=[]
    for docid in ids:
        if left<1000:
            omitted.append(docid);continue
        doc=store.document(docid)
        if doc['mime']=='application/json':
            item={'document_id':docid,'producer':doc['producer'],'mime':doc['mime'],
                  'next_action':'Use filings, facts or read-document JSON Pointer to inspect selected values and units'}
            cost=len(dumps(item))
            if cost>left:
                omitted.append(docid);continue
            result['sources'].append(item);left-=cost
        else:
            found=text_packet(doc,terms,min(left,12000))
            cost=len(dumps(found))
            if cost>left:
                omitted.append(docid);continue
            result['sources'].append(found);left-=cost
    result['omitted_document_ids']=omitted
    result['attempts']=snap['attempts'][-20:]
    return result


def report(store,request,judgment_ids,assessment_ids=(),mode='report',title='연구 검토 초안',event_ids=()):
    action={'judgment_ids':list(judgment_ids),'assessment_ids':list(assessment_ids),'event_ids':list(event_ids),'mode':mode,'title':title}
    existing=existing_action(store,'report',request,action)
    if existing:
        return existing
    snap=store.snapshot()
    if mode not in ('report','weekly_brief','answer'):
        raise ValueError('Invalid report mode')
    refs=list(judgment_ids)+list(assessment_ids)+list(event_ids)
    snapshot_records={r['id'] for r in snap['records']}
    if any(r not in snapshot_records for r in refs):
        raise ValueError('Report reference absent from fixed snapshot')
    lines=['# '+title,'',f"기준일: {store.config['as_of_date']} · snapshot: {snap['snapshot_id']}",
           '', '작성 방식: 저장된 검토 입력을 연결한 초안. 독립 검토·baseline 승인·심층 리서치 실행을 뜻하지 않습니다.', '']
    sources={}
    if not refs:
        lines+=['아직 검토된 판단이나 평가가 없습니다. 자료 확보/검토를 진행해야 합니다.','']
    for rid in judgment_ids:
        value=data(store,rid,'judgment')
        ids=value['support_ids']+value['counter_ids']
        evidence=current_evidence(store,ids,value['scope'])
        lines+=['## '+value['question'],'',value['conclusion'],'',value['reasoning'],'',
                '적용 범위: '+dumps(value['scope']),'']
        for eid,e in zip(ids,evidence):
            role='반대/대안' if eid in value['counter_ids'] else '지지'
            lines+=[f"- {role}: {e['claim']} [{eid}]", f"  원문: {e['quote']}"]
            sources[eid]=e
        lines+=['','경쟁 가설: '+dumps(value['alternatives']),
                '미확인: '+dumps(value['unknowns']),'다음 확인: '+dumps(value['next_actions']),'']
    for rid in assessment_ids:
        v=data(store,rid,'assessment')
        eids=[x for x in store.record(rid)['payload']['refs'] if x!=v.get('supersedes')]
        sources.update(zip(eids,current_evidence(store,eids,v['scope'])))
        lines+=['## 범위한정 평가','', '범위: '+dumps(v['scope']),'', '```json',json.dumps(display_result(v['result']),ensure_ascii=False,indent=2),'```','']
    for rid in event_ids:
        v=data(store,rid,'event')
        sources.update(zip(v['evidence_ids'],current_evidence(store,v['evidence_ids'],v['scope'])))
        lines+=['## 검토된 사건','',v['event_date']+' · '+v['event_type'],v['description'],
                '중요성: '+str(v['materiality']),'검토: '+v['review_reason'],
                '근거: '+', '.join(v['evidence_ids']),'']
    failures=[x for x in snap['attempts'] if x['status'] not in ('success','unchanged')]
    lines+=['## 수집·해석 제한','',f'이 snapshot의 미성공/부분 취득 기록: {len(failures)}건. 실패는 변화 없음으로 해석하지 않습니다.','']
    for a in failures[-20:]:
        lines.append('- '+a['status']+' · source '+a['source_id'])
    lines+=['','## 원문과 검토 위치','']
    for eid,e in sources.items():
        doc=store.document(e['document_id'])
        lines.append(f"- [{eid}] [{doc['producer']}]({doc['url']}) · {e['location']} · 문서 {doc['id']} · {e['nature']}")
    text='\n'.join(lines)+'\n'
    output={'title':title,'mode':mode,'snapshot_id':snap['snapshot_id'],'markdown':text,'action_sha256':digest(action),
            'generation':'deterministic_cited_draft','approval':'prepared_not_baseline_approved'}
    return store.append('report',request,output,refs)


def audit(store):
    snapshot=store.snapshot()
    issues=[]
    records={r['id']:r for r in snapshot['records']}
    for r in records.values():
        for ref in r['payload']['refs']:
            if ref not in records:
                issues.append({'id':r['id'],'issue':'dangling_reference'})
        if r['kind']=='assessment':
            v=r['payload']['data']
            for name,artifact in v['engine_artifacts'].items():
                if digest(artifact['source'].encode('utf-8'))!=artifact['sha256']:
                    issues.append({'id':r['id'],'issue':'engine_artifact_hash_mismatch'})
            try:
                if replay(v['inputs'],v['result'],v['engine_artifacts'])!=v['result']:
                    issues.append({'id':r['id'],'issue':'calculation_mismatch'})
            except ValueError as exc:
                issues.append({'id':r['id'],'issue':'historical_replay_unavailable','reason':str(exc)})
    return {'snapshot_id':snapshot['snapshot_id'],'issues':issues,'record_count':len(records),
            'scope':'hash/references/arithmetic only; not independent source interpretation audit'}
