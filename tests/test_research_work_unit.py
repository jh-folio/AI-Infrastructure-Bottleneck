"""P0-P2: real record boundaries, fail-closed ownership and retry, synthetic data only."""
import copy
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
import test_source_work as fixtures
import research_loop as loop
import research_efficiency as efficiency
import research_coordination as coord
import research_work_unit as unit
from research_store import Store, dumps


class WorkUnitTests(unittest.TestCase):
    setUp=fixtures.SourceWorkTests.setUp
    question=fixtures.SourceWorkTests.question
    plan=fixtures.SourceWorkTests.plan

    def deltas(self):
        self.question('A01');self.question('A02')
        return {'campaign_id':self.cid,'previous_id':loop.current(self.store,self.cid)[0],
                'updates':[{'question_id':nid+'-supply','set':{'next_action':'Read scope-specific original '+nid},
                            'attempts_add':[{'route':'Synthetic issuer '+nid,'outcome':'unavailable',
                                             'finding':'Try an alternative original','document_ids':[]}]}
                           for nid in ('A01','A02')]}

    def test_multi_delta_one_checkpoint_replay_stale_and_conflict(self):
        value=self.deltas();before=len(self.store.records('task'))
        first=unit.update(self.store,'multi',value)
        self.assertEqual(len(self.store.records('task')),before+1)
        self.assertFalse(unit.update(Store(self.store.folder,self.store.project_id),'multi',value)['inserted'])
        self.assertEqual(first['id'],loop.current(self.store,self.cid)[0])
        self.assertTrue(all(len(q['attempts'])==1 for q in loop.current(self.store,self.cid)[1]['questions']))
        with self.assertRaises(ValueError):unit.update(self.store,'different-request',value)
        changed=copy.deepcopy(value);changed['updates'][0]['set']['next_action']='changed'
        with self.assertRaises(ValueError):unit.update(self.store,'multi',changed)

    def test_batch_partial_then_resume_preserves_original_id(self):
        value=self.deltas()
        plan={'campaign_id':self.cid,'source':{'url':'https://example.com/shared','producer':'Synthetic','kind':'public_document'},
              'bindings':[{'node_id':'A01','dimensions':['demand_supply'],'purpose':'Qualified supply'}]}
        bad=copy.deepcopy(value);bad['previous_id']='stale'
        bundle={'items':[{'key':'plan','op':'source-plan','data':plan},
                         {'key':'questions','op':'research-questions-update','data':bad}]}
        partial=efficiency.batch(self.store,'bundle',bundle)
        self.assertEqual(partial['status'],'partial');self.assertEqual(partial['failed_key'],'questions')
        bundle['items'][1]['data']=value
        complete=efficiency.batch(self.store,'bundle',bundle)
        self.assertEqual(complete['status'],'complete')
        self.assertEqual(complete['ids']['plan'],partial['ids']['plan'])
        self.assertFalse(complete['receipts'][0]['inserted'])
        replay=efficiency.batch(self.store,'bundle',bundle)
        self.assertEqual(replay['ids'],complete['ids'])
        self.assertTrue(all(r['inserted'] is False for r in replay['receipts']))
        self.assertEqual(replay['next_action']['op'],'research-next')

    def test_packet_shared_document_no_source_and_stale(self):
        value=self.deltas()
        doc=self.store.capture({'url':'https://example.com/unit','producer':'Synthetic'},self.raw,'text/html',{})['document_id']
        request={'campaign_id':self.cid,'checkpoint_id':value['previous_id'],
                 'question_ids':['A01-supply','A02-supply'],'document_ids':[doc],
                 'reason':'One original covers two distinct product qualifications',
                 'expected_output':'Separate applicability and remaining uncertainty'}
        packet=unit.packet(self.store,request)
        self.assertEqual(len(packet['documents']),1)
        self.assertEqual(len(packet['questions']),2)
        self.assertNotIn('raw',dumps(packet))
        self.assertEqual(unit.packet(self.store,dict(request,document_ids=[]))['documents'],[])
        unit.update(self.store,'advance',value)
        with self.assertRaises(ValueError):unit.packet(self.store,request)

    def test_active_job_cannot_be_bypassed(self):
        value=self.deltas()
        coord.execute(self.store,'configure','cfg',dict(campaign_id=self.cid,parallel_supported=True,
            automatic_resume_requested=False,concurrency=2,lease_minutes=30,max_runs=5,max_failures=5))
        job=coord.execute(self.store,'claim','job',dict(campaign_id=self.cid,domain_id='semiconductors',worker_id='worker',node_ids=['A01']))['id']
        with self.assertRaises(ValueError):unit.update(self.store,'bypass',value)
        with self.assertRaises(ValueError):unit.packet(self.store,dict(campaign_id=self.cid,checkpoint_id=value['previous_id'],
            job_id=job,question_ids=['A02-supply'],reason='Outside job',expected_output='Forbidden'))

    def test_bad_closure_and_identity_leave_checkpoint_unchanged(self):
        value=self.deltas();head=value['previous_id']
        for fields in ({'node_id':'A03'},{'status':'resolved','answer':'Unsupported','closure_reason':'Done','judgment_ids':[]}):
            bad=copy.deepcopy(value);bad['updates'][0]['set']=fields
            with self.assertRaises(ValueError):unit.update(self.store,'bad-'+str(len(fields)),bad)
            self.assertEqual(loop.current(self.store,self.cid)[0],head)

    def test_atomic_deltas_no_first_question_commit_on_second_failure(self):
        value=self.deltas();value['updates'][1]['attempts_add']=[{'outcome':'found','route':'x','finding':'x','document_ids':[]}]
        with self.assertRaises(ValueError):unit.update(self.store,'invalid-second',value)
        self.assertTrue(all(q['attempts']==[] for q in loop.current(self.store,self.cid)[1]['questions']))

    def test_metrics_privacy_old_rows_repeated_segments_and_failure(self):
        secret='contact@example.invalid /private/path'
        action={'op':'source-context','telemetry':{'run_id':secret,'work_unit_id':secret,'phase':'initial'}}
        result={'lanes':{'focus':{'segments':[{'segment_id':'shared','text':secret}]}}}
        for _ in range(2):efficiency.record_metric(self.store,action,result)
        path=self.store.folder/'usage_metrics.jsonl'
        with path.open('a',encoding='utf-8') as out:
            out.write(dumps({'operation':'legacy','input_bytes':1,'output_bytes':2,'response_sha256':'old'})+'\nnot-json\n')
        self.assertNotIn(secret,path.read_text())
        summary=efficiency.usage_summary(self.store)
        self.assertEqual(summary['repeated_segment_count'],1)
        self.assertEqual(summary['malformed_rows'],1)
        self.assertEqual(summary['operations']['legacy']['calls'],1)
        self.assertIsNone(summary['actual_host_tokens'])
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'plugin/runtime'))
        from research_cli import execute
        with self.assertRaises(ValueError):execute(dict(op='missing-op',state_dir=str(self.store.folder),project_id=self.store.project_id))
        self.assertEqual(efficiency.usage_summary(self.store)['operations']['missing-op']['errors'],1)

    def test_durable_sync_and_metric_failure_do_not_undo_checkpoint(self):
        value=self.deltas()
        (self.store.folder.parent/'durable').mkdir()
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'plugin/runtime'))
        from research_cli import execute
        action=dict(op='research-batch',state_dir=str(self.store.folder),project_id=self.store.project_id,
            request_id='durable-unit',durable_dir=str(self.store.folder.parent/'durable'),
            data={'items':[{'key':'questions','op':'research-questions-update','data':value}]})
        with patch('research_efficiency.record_metric',side_effect=OSError('No metrics')):
            result=execute(action)
        self.assertEqual(result['status'],'complete')
        self.assertEqual(result['metrics_status'],'unavailable')
        self.assertNotEqual(result['durable']['status'],'failed')
        self.assertEqual(result['checkpoint_id'],loop.current(self.store,self.cid)[0])

    def test_same_inputs_individual_vs_grouped_state(self):
        value=self.deltas()
        doc=self.fx.document()
        for delta in value['updates']:
            delta['attempts_add']=[{'route':'Synthetic shared original','outcome':'found',
                'finding':'Demand statement requires product-specific supply follow-up','document_ids':[doc]}]
            delta['source_reviews_add']=[{'document_id':doc,'location':'block:1','quote':'Demand is strong.',
                'finding':'Aggregate demand is not proof of shortage for '+delta['question_id'],
                'relevance':'Background only; product qualification remains open','role':'background'}]
        backup=self.store.folder.parent/'comparison-backup'
        self.store.backup(backup)
        from research_store import restore
        dest=self.store.folder.parent/'comparison'
        restore(backup,dest);other=Store(dest,self.store.project_id)
        calls=[]
        for i,delta in enumerate(value['updates']):
            data=dict(delta,campaign_id=self.cid,previous_id=loop.current(other,self.cid)[0])
            result=loop.update_question(other,'separate-'+str(i),data)
            calls.append(efficiency.measure({'op':'research-question-update','data':data},result))
        grouped=unit.update(self.store,'grouped',value)
        self.assertEqual(loop.current(other,self.cid)[1]['questions'],loop.current(self.store,self.cid)[1]['questions'])
        self.assertEqual(loop.current(other,self.cid)[1]['nodes'],loop.current(self.store,self.cid)[1]['nodes'])
        self.assertLess(len(dumps(grouped)),sum(c['output_chars'] for c in calls))

    def test_batch_coordinator_review_and_hash_reference_replay(self):
        self.question('A01')
        coord.execute(self.store,'configure','cfg',dict(campaign_id=self.cid,parallel_supported=True,
            automatic_resume_requested=False,concurrency=2,lease_minutes=30,max_runs=5,max_failures=5))
        job=coord.execute(self.store,'claim','job',dict(campaign_id=self.cid,domain_id='semiconductors',worker_id='worker',node_ids=['A01']))['id']
        q=copy.deepcopy(loop.current(self.store,self.cid)[1]['questions'][0]);q['next_action']='Check a second official original'
        bundle={'items':[{'key':'submission','op':'coordination-submit','data':dict(campaign_id=self.cid,job_id=job,
            result={'nodes':[],'questions':[q],'summary':'New source route identified','remaining_work':['Read original']})},
            {'key':'apply','op':'coordination-apply','data':dict(campaign_id=self.cid,job_id=job,
                result_sha256={'$ref':'submission.result_sha256'},review={'reviewer':'coordinator',
                'source_checks':'No new claim adopted','scope_checks':'Only A01','counterargument_checks':'Alternative still open'})}]}
        result=efficiency.batch(self.store,'review-batch',bundle)
        self.assertEqual(result['status'],'complete',result)
        self.assertEqual(efficiency.batch(self.store,'review-batch',bundle)['ids'],result['ids'])
        self.assertEqual(coord.state(self.store,self.cid)['jobs'][job]['status'],'applied')

    def test_record_success_question_failure_and_durable_failure_are_distinct(self):
        value=self.deltas();value['previous_id']='stale'
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'plugin/runtime'))
        from research_cli import execute
        plan={'campaign_id':self.cid,'source':{'url':'https://example.com/partial','producer':'Synthetic','kind':'public_document'},
              'bindings':[{'node_id':'A01','dimensions':['history'],'purpose':'Chronology'}]}
        result=execute(dict(op='research-batch',state_dir=str(self.store.folder),project_id=self.store.project_id,
            request_id='partial-durable',durable_dir=str(self.store.folder.parent/'missing'),data={'items':[
                {'key':'source','op':'source-plan','data':plan},
                {'key':'questions','op':'research-questions-update','data':value}]}))
        self.assertEqual(result['status'],'partial')
        self.assertEqual(result['durable']['status'],'failed')
        self.assertEqual(len(result['receipts']),1)
        self.assertIsNotNone(self.store.record(result['ids']['source']))

    def test_guidance_scope_and_supported_paths(self):
        root=Path(__file__).resolve().parents[1]
        skills=root/'plugin/skills'
        if not skills.exists():skills=root/'skills'
        baseline=(skills/'build-baseline/SKILL.md').read_text(encoding='utf-8')
        self.assertNotIn('첫 실행에서는 기존 87개 노드 모두',baseline)
        self.assertIn('EFFICIENT_RESEARCH.md',baseline)
        execution=(root/'plugin/workflows/RESEARCH_EXECUTION.md').read_text(encoding='utf-8')
        self.assertNotIn('첫 실행은 기존 87개 노드 전수 조사다',execution)
        self.assertNotIn('435개 질문마다',execution)
        guide=(root/'plugin/workflows/EFFICIENT_RESEARCH.md').read_text(encoding='utf-8')
        for term in ('research-work-unit','research-questions-update','known_segments','새 세션','78','coordination-submit'):
            self.assertIn(term,guide)

    def test_shared_original_import_adopt_and_question_application(self):
        from test_research_d3 import scope
        value=self.deltas()
        original=self.store.folder/'shared.html';original.write_bytes(self.raw)
        items=[{'key':'plan','op':'source-plan','data':{'campaign_id':self.cid,
                'source':{'url':'https://example.com/shared-original','producer':'Synthetic','kind':'public_document','published_at':'2025-12-01'},
                'bindings':[{'node_id':nid,'dimensions':['demand_supply'],'purpose':'Scope-specific follow-up'} for nid in ('A01','A02')]}},
               {'key':'original','op':'source-import','data':{'plan_id':{'$ref':'plan'},'path':str(original),
                'mime':'text/html','capture_kind':'original_bytes','acquisition_note':'Synthetic original fixture'}}]
        for i,nid in enumerate(('A01','A02')):
            evidence=dict(document_id={'$ref':'original.document_id'},location='block:1',quote='Demand exceeds qualified HBM supply.',
                claim='Demand observation for '+nid,scope=dict(scope(),node_id=nid),nature='observation',grade='A',confidence='Medium',
                confidence_reason='Synthetic only',producer_family='issuer',source_tier=1,decision='accepted',review_reason='Explicit scope '+nid)
            items.append({'key':'evidence-'+nid,'op':'adopt','data':evidence})
            value['updates'][i]['attempts_add']=[{'route':'Shared issuer original','outcome':'found',
                'finding':'Need independent confirmation for '+nid,'document_ids':[{'$ref':'original.document_id'}]}]
            value['updates'][i]['source_reviews_add']=[{'document_id':{'$ref':'original.document_id'},'location':'block:1',
                'quote':'Demand exceeds qualified HBM supply.','finding':'Follow up '+nid,'relevance':'Synthetic scope exercise','role':'background'}]
        items.append({'key':'questions','op':'research-questions-update','data':value})
        result=efficiency.batch(self.store,'full-unit',{'items':items})
        self.assertEqual(result['status'],'complete',result)
        for nid in ('A01','A02'):
            record=self.store.record(result['ids']['evidence-'+nid])['payload']['data']
            self.assertEqual(record['scope']['node_id'],nid)
            self.assertEqual(record['document_id'],result['ids']['original.document_id'])
        questions=loop.current(self.store,self.cid)[1]['questions']
        self.assertTrue(all(q['status']=='open' for q in questions))
        self.assertEqual(efficiency.batch(self.store,'full-unit',{'items':items})['ids'],result['ids'])
        original.write_bytes(b'Changed source bytes')
        self.assertEqual(efficiency.batch(self.store,'full-unit',{'items':items})['failed_key'],'original')


if __name__=='__main__':unittest.main()
