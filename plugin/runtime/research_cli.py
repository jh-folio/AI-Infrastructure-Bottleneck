"""Run one explicit research action from JSON. See workflows/RUNTIME_GUIDE.md."""
import argparse
import json
from pathlib import Path
import sqlite3
import sys

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'core'))
sys.path.insert(0,str(ROOT/'adapters'))
from research_store import Store,create,restore,dumps
import research
from extraction import filings,locate,text_packet
from research_sources import sec,fetch,prices,capabilities


def execute(action):
    op=action['op']
    if op=='capabilities':
        return capabilities()
    if op=='init':
        return create(action['state_dir'],action['config'])
    if op=='restore':
        return restore(action['backup_dir'],action['destination'])
    store=Store(action['state_dir'],action['project_id'])
    if op=='sec':
        return sec(store,action['cik'],action['dataset'])
    if op=='ir':
        return fetch(store,action['url'],action['producer'],'ir',action.get('published_at'))
    if op=='prices':
        return prices(store,action['ticker'],action['start'],action['end'])
    if op=='filings':
        result=filings(store.document(action['document_id']),action.get('as_of',store.config['as_of_date']))
        offset=action.get('offset',0);limit=action.get('limit',20)
        if not 0<=offset or not 1<=limit<=100:raise ValueError('Invalid paging')
        rows=result['rows'];result.update(total=len(rows),rows=rows[offset:offset+limit],next_offset=offset+limit if offset+limit<len(rows) else None)
        return result
    if op=='facts':
        return research.save_facts(store,action['document_id'],action['taxonomy'],action['tag'],action.get('as_of',store.config['as_of_date']))
    if op=='read-document':
        doc=store.document(action['document_id']);text=locate(doc,action['location']);budget=action.get('max_chars',12000)
        if not 1<=budget<=50000:raise ValueError('Invalid budget')
        start=action.get('char_offset',0)
        if not isinstance(start,int) or start<0:raise ValueError('Invalid character offset')
        return {'document_id':doc['id'],'sha256':doc['sha256'],'location':action['location'],
                'text':text[start:start+budget],'truncated':len(text)>start+budget,
                'next_char_offset':start+budget if len(text)>start+budget else None,'total_chars':len(text)}
    if op=='search':
        return text_packet(store.document(action['document_id']),action['terms'],action.get('max_chars',16000),action.get('offset',0))
    if op=='packet':
        return research.packet(store,action['question'],action['scope'],action['terms'],action.get('max_chars',24000),action.get('document_ids'))
    if op in ('adopt','judgment','event','assess'):
        return getattr(research,op)(store,action['request_id'],action['data'])
    if op in ('node','task'):
        if op=='node':
            from research_store import required
            required(action['data'],'node_id','name','scope')
        else:
            from research_store import required
            required(action['data'],'question','scope','unknowns','next_actions')
        research.scope_check(action['data']['scope'])
        return store.append(op,action['request_id'],action['data'],action.get('refs',[]))
    if op=='report':
        return research.report(store,action['request_id'],action.get('judgment_ids',[]),action.get('assessment_ids',[]),action.get('mode','report'),action.get('title','연구 검토 초안'),action.get('event_ids',[]))
    if op=='synthesize':
        from synthesis import make_report
        return make_report(store,action['request_id'],action['data'])
    if op=='record':
        result=store.record(action['id'])
        if not action.get('include_artifacts'):
            value=result['payload']['data']
            if 'engine_artifacts' in value:
                value['engine_artifacts']={k:{'sha256':v['sha256']} for k,v in value['engine_artifacts'].items()}
        return result
    if op=='list':
        rows=store.records(action.get('kind'));offset=action.get('offset',0);limit=action.get('limit',20)
        if offset<0 or not 1<=limit<=100:raise ValueError('Invalid paging')
        return {'total':len(rows),'records':[{'id':r['id'],'kind':r['kind'],'created_at':r['created_at'],
                    'scope':r['payload']['data'].get('scope'),'question':r['payload']['data'].get('question')}
                    for r in rows[offset:offset+limit]],'next_offset':offset+limit if offset+limit<len(rows) else None}
    if op=='replay':
        from scoring import replay
        value=research.data(store,action['id'],'assessment')
        result=replay(value['inputs'],value['result'],value['engine_artifacts'])
        return {'matches':result==value['result'],'result':result}
    if op=='snapshot':
        snap=store.snapshot()
        return {'snapshot_id':snap['snapshot_id'],'record_count':len(snap['records']),'document_count':len(snap['documents']),'attempts':snap['attempts'][-20:]}
    if op=='audit':
        return research.audit(store)
    if op=='backup':
        return store.backup(action['destination'])
    if op=='export-report':
        value=research.data(store,action['id'],'report');path=Path(action['destination']).resolve()
        with path.open('x',encoding='utf-8') as f:f.write(value['markdown'])
        return {'path':str(path),'snapshot_id':value['snapshot_id']}
    if op=='compare':
        from scoring import compare
        return compare(research.data(store,action['old_id'],'assessment'),research.data(store,action['new_id'],'assessment'))
    raise ValueError('Unknown operation')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--action',required=True,help='JSON action file')
    a=p.parse_args()
    try:
        action=json.loads(Path(a.action).read_text(encoding='utf-8-sig'))
        result=execute(action)
        print(dumps(result))
        return 0
    except (ValueError,KeyError,TypeError,IndexError,OSError,sqlite3.Error) as exc:
        # Detailed input can include contact settings; don't echo arbitrary errors.
        print(dumps({'status':'error','error_type':type(exc).__name__,
                     'message':str(exc) if isinstance(exc,ValueError) else 'Invalid action or inaccessible resource'}))
        return 1


if __name__=='__main__':
    sys.exit(main())
