"""Read-only projection of a report's exact input snapshot; no new research or scores."""
from pathlib import Path
import json
from datetime import date
import calendar
from research_store import required, digest
from research import data

KINDS={'technical':'기술적 의존','observed':'관측된 지연 전파','conditional':'조건부 전파'}


def score_bounds(row):
    a=(row.get('assessment') or {}).get('result',{})
    if a.get('scoreability') not in ('Fully Scorable','Provisionally Scorable'):return None
    v=a.get('overall',{});lo,hi=v.get('low'),v.get('high')
    if not all(isinstance(n,(int,float)) and not isinstance(n,bool) and 0<=n<=100 for n in (lo,hi)) or lo>hi:return None
    return {'low':lo,'high':hi,'provisional':a['scoreability']=='Provisionally Scorable'}


def history_for(row, records, as_of):
    end=date.fromisoformat(as_of);month=end.year*12+end.month-1-6;year,m=divmod(month,12);m+=1
    start=date(year,m,min(end.day,calendar.monthrange(year,m)[1])).isoformat()
    scope=lambda s:{k:v for k,v in s.items() if k!='as_of_date'}
    candidates=[row]
    superseded={rec['payload']['data'].get('supersedes') for rec in records.values() if rec['kind']=='evidence'}
    for rec in records.values():
        value=rec['payload']['data']
        if rec['kind']=='report' and value.get('generation') in ('supply-chain-synthesis-1','supply-chain-synthesis-2','supply-chain-synthesis-3'):
            candidates.extend(value['rows'])
    by_date={}
    for r in candidates:
        if superseded.intersection(r.get('support_ids',[])+r.get('counter_ids',[])):continue
        when=r['scope']['as_of_date'];score=score_bounds(r)
        if score and scope(r['scope'])==scope(row['scope']) and start<=when<=as_of:
            by_date.setdefault(when,{})[r['judgment_id']]=score
    # Same-day conflicting revisions are not silently joined into a false trend.
    return [{'date':when,**next(iter(values.values()))} for when,values in sorted(by_date.items()) if len(values)==1]


def relation(store, request, value):
    required(value,'from_judgment_id','to_judgment_id','kind','reason','evidence_ids')
    if value['kind'] not in KINDS or value['from_judgment_id']==value['to_judgment_id']:
        raise ValueError('Invalid relation kind or self relation')
    for key in ('from_judgment_id','to_judgment_id'):data(store,value[key],'judgment')
    if not isinstance(value['evidence_ids'],list):raise ValueError('Relation evidence must be a list')
    if value['kind']!='technical' and not value['evidence_ids']:raise ValueError('Propagation needs reviewed evidence')
    for eid in value['evidence_ids']:
        e=data(store,eid,'evidence')
        if e['decision']!='accepted':raise ValueError('Relation evidence must be accepted')
        if value['kind']=='observed' and e['nature']!='observation':raise ValueError('Observed propagation needs observations')
    return store.append('task',request,{'type':'relation',**value},
        [value['from_judgment_id'],value['to_judgment_id'],*value['evidence_ids']])


def projection(store, report_id):
    report=data(store,report_id,'report')
    if report.get('generation') not in ('supply-chain-synthesis-1','supply-chain-synthesis-2','supply-chain-synthesis-3'):
        raise ValueError('Dashboard requires a supply-chain synthesis report')
    snap=store.read_snapshot(report['snapshot_id'])
    records={r['id']:r for r in snap['records']};docs={d['id']:d for d in snap['documents']}
    superseded={r['payload']['data'].get('supersedes') for r in records.values() if r['kind']=='evidence'}
    rows=[]
    for row in report['rows']:
        if row['judgment_id'] not in records:raise ValueError('Report judgment missing from snapshot')
        sources=[]
        for eid in row['support_ids']+row['counter_ids']:
            e=records[eid]['payload']['data'];d=docs[e['document_id']]
            from supply_view import public_source
            sources.append(public_source(e,d,'지지 근거' if eid in row['support_ids'] else '반대·대안 근거'))
        companies=[]
        for company in records[row['judgment_id']]['payload']['data'].get('companies',[]):
            if not isinstance(company,dict) or not company.get('name') or not company.get('role'):continue
            eids=company.get('evidence_ids',[])
            if not eids or not isinstance(eids,list) or not set(eids)<=set(row['support_ids']+row['counter_ids']):continue
            companies.append({'name':company['name'],'role':company['role']})
        observations=sorted({records[e]['payload']['data']['observed_at'] for e in row['support_ids']
                             if records[e]['payload']['data'].get('observed_at')})
        publications=sorted({s['published_at'] for s in sources if s.get('published_at')})
        rows.append({**row,'sources':sources,'score':score_bounds(row),
                     'observation_dates':observations,'publication_dates':publications,
                     'binding_status':(row.get('assessment') or {}).get('result',{}).get('binding_status','NotDemonstrated'),
                     'history':history_for(row,records,report['as_of_date']),'companies':companies})
    ids={r['judgment_id'] for r in rows};relations=[]
    for record in records.values():
        v=record['payload']['data']
        if record['kind']!='task' or v.get('type')!='relation':continue
        if v['from_judgment_id'] not in ids or v['to_judgment_id'] not in ids:continue
        evidence=[]
        for eid in v['evidence_ids']:
            e=records[eid]['payload']['data']
            if eid in superseded or e['decision']!='accepted':raise ValueError('Relation has superseded or unaccepted evidence')
            if e['published_at']>report['as_of_date']:raise ValueError('Relation evidence newer than report')
            if v['kind']=='observed' and e['nature']!='observation':raise ValueError('Invalid observed propagation')
            d=docs[e['document_id']]
            evidence.append({'claim':e['claim'],'url':d['url'],'producer':d['producer']})
        relations.append({**v,'label':KINDS[v['kind']],'sources':evidence})
    from supply_view import expand
    nodes, node_relations, events = expand(report,rows,records,docs,relations)
    result={'title':report['title'],'as_of_date':report['as_of_date'],'snapshot_id':report['snapshot_id'],
        'view_version':2,'nodes':nodes,'node_relations':node_relations,'events':events,
        'inventory_scope':report.get('map_catalog',{}).get('scope','legacy_subset'),
        'research_stage':report.get('research_stage','interim'),
        'highlight_ids':report.get('highlight_ids',[]),
        'report_id':report_id,'rows':rows,'relations':relations,'coverage':report['coverage'],
        'changes':report['changes'],'claims':report['synthesis_claims'],
        'research_execution':report.get('research_execution',{'status':'unknown','reason':'과거 보고서에 실행 기록이 없습니다.'}),
        'monitor_runs':[r['payload']['data'] for r in records.values() if r['kind']=='task' and r['payload']['data'].get('type')=='monitor_run']}
    result['projection_sha256']=digest(result)
    return result


def export(store, report_id, destination):
    value=projection(store,report_id)
    html=render_html(value)
    path=Path(destination).resolve()
    with path.open('x',encoding='utf-8') as f:f.write(html)
    return {'path':str(path),'snapshot_id':value['snapshot_id'],'projection_sha256':value['projection_sha256'],
            'read_only':True,'report_id':report_id}


def render_html(value):
    template=Path(__file__).resolve().parents[1]/'ui/dashboard.html'
    raw=json.dumps(value,ensure_ascii=False,allow_nan=False).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
    html=template.read_text(encoding='utf-8').replace('__FONT_CSS__',(template.parent/'fonts.css').read_text(encoding='utf-8'))
    html=html.replace('__UI_SCRIPT__',(template.parent/'dashboard.js').read_text(encoding='utf-8'))
    html=html.replace('__RESEARCH_DATA__',raw)
    return html
