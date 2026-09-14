"""Freeze an input packet and attach actual host execution and returned artifacts."""
from pathlib import Path
from research_store import required, digest
from research import data, existing_action


def prepare(store, request, value):
    required(value, 'purpose', 'document_ids', 'record_ids')
    action={'type':'research_handoff', **value}
    old=existing_action(store,'task',request,action)
    if old:return old
    for doc in value['document_ids']:store.document(doc)
    for rid in value['record_ids']:store.record(rid)
    snap=store.snapshot()
    return store.append('task',request,{'type':'research_handoff','action_sha256':digest(action),
        **value,'snapshot_id':snap['snapshot_id'], 'status':'prepared_not_executed',
        'instructions':'실제 심층 리서치 기능에 목적과 이 고정 자료를 전달하세요. 원문은 위치 지정으로 읽고 부족한 자료만 보강하세요. 원문 범위·관측/전망·수요/가용 공급·가동 영향·반증을 대조하고 결과를 한국어 문장으로 작성하세요. 반환 결과는 채택 후보이며 점수나 승인 상태를 직접 변경하지 않습니다.'},
        value['record_ids'],value['document_ids'])


def receive(store, request, value):
    required(value,'handoff_id','entrypoint','execution_path','result_path')
    mode=value.get('execution_mode','host_tool')
    if mode not in ('skill_direct','host_tool'):raise ValueError('Invalid research execution mode')
    handoff=data(store,value['handoff_id'],'task')
    if handoff.get('type')!='research_handoff':raise ValueError('Expected prepared research handoff')
    paths=[Path(value[k]).resolve() for k in ('execution_path','result_path')]
    if paths[0]==paths[1]:raise ValueError('Execution evidence and returned result must be separate files')
    raw=[p.read_bytes() for p in paths]
    if any(not b or len(b)>24*1024*1024 for b in raw):raise ValueError('Empty or oversized research artifact')
    action={'type':'research_return', **value, 'artifact_hashes':[digest(b) for b in raw]}
    old=existing_action(store,'task',request,action)
    if old:return old
    docs=[store.capture({'url':p.as_uri(),'producer':'User project host research'},b,'text/plain',
                       {'role':role,'entrypoint':value['entrypoint'],'handoff_id':value['handoff_id']})['document_id']
          for p,b,role in zip(paths,raw,('execution','result'))]
    execution={'status':'completed','reason':'실행자가 수행 기록과 반환 자료를 등록했습니다. 독립 실행 감사는 별도입니다.',
        'execution_mode':mode,
        'entrypoint':value['entrypoint'],'execution_document_id':docs[0],'result_document_id':docs[1]}
    return store.append('task',request,{'type':'research_return','action_sha256':digest(action),
        'handoff_id':value['handoff_id'],'research_execution':execution,'review_status':'candidate_requires_review'},
        [value['handoff_id']],docs)
