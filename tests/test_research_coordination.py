"""Synthetic coordination lifecycle, conflict and persistence tests; no host claims."""
import copy
import json
from datetime import timedelta
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
import test_research_loop as fixtures
import research_loop as loop
import research_coordination as coord
from research import data
from research_store import Store,digest

class CoordinationTests(unittest.TestCase):
    setUp=fixtures.ResearchLoopTests.setUp

    def call(self,op,request,**value):
        return coord.execute(self.store,op,request,dict(campaign_id=self.cid,**value))

    def configure(self,**kwargs):
        cfg=dict(concurrency=2,lease_minutes=30,max_runs=5,max_failures=5,
                 parallel_supported=True,automatic_resume_requested=True);cfg.update(kwargs)
        return self.call('configure','config',**cfg)

    def claim(self,node='A01',domain='semiconductors',request='job'):
        return self.call('claim',request,domain_id=domain,node_ids=[node],worker_id='worker-'+node)['id']

    def submit(self,job,node='A01',request='submission'):
        n=copy.deepcopy(next(n for n in loop.current(self.store,self.cid)[1]['nodes'] if n['node_id']==node))
        q=dict(id=node+'-demand',node_id=node,dimension='demand_supply',question='What constrains this product?',
               status='open',attempts=[],next_action='Read the manufacturer capacity release')
        result=dict(nodes=[n],questions=[q],summary='Investigation question prepared; not yet researched',remaining_work=['Read release'])
        rid=self.call('submit',request,job_id=job,result=result)['id']
        return rid,digest(result)

    def apply(self,job,sha,request='apply'):
        return self.call('apply',request,job_id=job,result_sha256=sha,
             review=dict(reviewer='coordinator',source_checks='No closed evidence proposed',scope_checks='Assigned product retained',counterargument_checks='Still open'))

    def test_default_mapping_is_exact_and_status_read_only(self):
        self.configure();before=self.store.path.read_bytes();s=coord.status(self.store,self.cid)
        self.assertEqual([len(d['node_ids']) for d in s['domains']],[11,9,14,9,9,10,12,0,13])
        self.assertFalse(s['unmapped_node_ids']);self.assertEqual(s['pending_count'],87)
        self.assertEqual(before,self.store.path.read_bytes())

    def test_parallel_capacity_domain_exclusion_and_serial_fallback(self):
        self.configure();self.claim();self.claim('C01','grid','grid')
        with self.assertRaisesRegex(ValueError,'Concurrency'):self.claim('B01','facilities','third')

    def test_same_domain_and_duplicate_request(self):
        self.configure();a=self.claim();self.assertEqual(a,self.claim())
        with self.assertRaisesRegex(ValueError,'active'):self.claim('A02',request='duplicate-domain')

    def test_serial_fallback(self):
        self.configure(parallel_supported=False);self.claim()
        with self.assertRaisesRegex(ValueError,'Concurrency'):self.claim('C01','grid','grid')

    def test_expired_lease_reclaimed_and_old_submission_rejected(self):
        self.configure();j=self.claim();future=coord.clock()+timedelta(hours=1)
        with patch.object(coord,'clock',return_value=future):
            new=self.claim(request='retry');self.assertNotEqual(j,new)
            with self.assertRaisesRegex(ValueError,'expired'):self.submit(j)
            self.assertEqual(coord.status(self.store,self.cid)['failure_count'],1)

    def test_renew_replaces_token_without_losing_scope(self):
        self.configure();j=self.claim();r=self.call('renew','renew',job_id=j)['id']
        self.assertEqual(coord.packet(self.store,self.cid,r)['job']['node_ids'],['A01'])
        with self.assertRaisesRegex(ValueError,'active'):self.submit(j)
        self.submit(r)

    def test_other_domain_commit_rebases_without_loss_and_apply_is_atomic_idempotent(self):
        self.configure();a=self.claim();b=self.claim('C01','grid','grid')
        _,sa=self.submit(a);_,sb=self.submit(b,'C01','subgrid')
        ca=self.apply(a,sa)['id'];cb=self.apply(b,sb,'applygrid')['id']
        self.assertNotEqual(ca,cb)
        self.assertFalse(self.apply(b,sb,'applygrid')['inserted'])
        self.assertEqual(len(loop.current(self.store,self.cid)[1]['questions']),2)
        self.assertEqual(coord.status(self.store,self.cid)['active_jobs'],[])
        self.assertIn('coordination_event',data(self.store,cb))
        self.assertEqual(coord.status(Store(self.store.folder,self.store.project_id),self.cid),coord.status(self.store,self.cid))

    def test_same_node_change_conflicts_and_tampered_review_hash_rejected(self):
        self.configure();j=self.claim();_,sha=self.submit(j)
        with self.assertRaisesRegex(ValueError,'hash'):self.apply(j,'wrong')
        p=coord.packet(self.store,self.cid,j);n=copy.deepcopy(p['nodes'][0]);n['reason']='Changed by another writer'
        loop.patch(self.store,'external',dict(campaign_id=self.cid,previous_id=self.cid,nodes=[n]))
        with self.assertRaisesRegex(ValueError,'changed'):self.apply(j,sha)

    def test_out_of_scope_submission_and_question_collision_rejected(self):
        self.configure();j=self.claim()
        with self.assertRaisesRegex(ValueError,'outside'):self.submit(j,'C01')

    def test_pause_blocks_claim_submit_and_active_schedule(self):
        self.configure();j=self.claim();self.call('control','pause',mode='paused',reason='User stop')
        with self.assertRaisesRegex(ValueError,'paused'):self.submit(j)
        with self.assertRaisesRegex(ValueError,'paused'):self.claim('C01','grid','new')
        self.assertEqual(coord.schedule_packet(self.store,self.cid)['desired_action'],'stop')

    def test_schedule_packet_is_not_registration_and_receipts_do_not_prove_execution(self):
        self.configure();before=self.store.path.read_bytes();p=coord.schedule_packet(self.store,self.cid)
        self.assertFalse(p['registered']);self.assertEqual(before,self.store.path.read_bytes())
        self.call('schedule','schedule',schedule_id='host-1',status='active',host='synthetic-host',receipt='synthetic receipt')
        self.assertFalse(coord.status(self.store,self.cid)['automatic_execution_verified'])
        with self.assertRaisesRegex(ValueError,'existing'):self.call('schedule','second',schedule_id='host-2',status='active',host='test',receipt='test')
        self.call('control','pause',mode='paused',reason='User stop')
        self.assertEqual(coord.status(self.store,self.cid)['next_action'],'stop_schedule')
        self.call('schedule','stop',schedule_id='host-1',status='stopped',host='synthetic-host',receipt='synthetic stopped')
        self.assertEqual(coord.status(self.store,self.cid)['next_action'],'paused')

    def test_scheduled_run_identity_checkpoint_and_limit(self):
        self.configure(max_runs=1)
        self.call('schedule','schedule',schedule_id='host',status='active',host='test',receipt='synthetic')
        with self.assertRaisesRegex(ValueError,'latest'):self.call('run','wrong',host_run_id='r1',schedule_id='host',observed_checkpoint='old')
        args=dict(host_run_id='r1',schedule_id='host',observed_checkpoint=self.cid)
        self.call('run','run',**args);self.assertFalse(self.call('run','run',**args)['inserted'])
        self.claim()  # final permitted run may still do its work
        with self.assertRaisesRegex(ValueError,'limit'):self.call('run','run2',host_run_id='r2',schedule_id='host',observed_checkpoint=self.cid)

    def test_dynamic_nodes_inherit_and_new_nodes_require_explicit_domain(self):
        self.configure();v=dict(campaign_id=self.cid,previous_id=self.cid,operation='split',source_ids=['A01'],
            new_nodes=[dict(node_id=n,name=n,scope='Synthetic') for n in ['X','Y']],reason='Split test',effective_date='2026-09-14')
        head=loop.change_nodes(self.store,'split',v)['id'];s=coord.status(self.store,self.cid)
        self.assertIn('X',s['domains'][0]['node_ids']);self.assertNotIn('A01',s['domains'][0]['node_ids'])
        v.update(previous_id=head,operation='add',source_ids=[],new_nodes=[dict(node_id='NEW',name='NEW',scope='Synthetic')])
        loop.change_nodes(self.store,'add',v);self.assertEqual(coord.status(self.store,self.cid)['unmapped_node_ids'],['NEW'])
        with self.assertRaisesRegex(ValueError,'unmapped'):self.claim('A02')
        self.call('assign','assign',assignments={'NEW':'network'})
        self.assertFalse(coord.status(self.store,self.cid)['unmapped_node_ids'])

    def test_failure_limit_and_premature_finish(self):
        self.configure(max_failures=1);j=self.claim();self.call('release','failed',job_id=j,reason='Source access failed')
        self.assertEqual(coord.status(self.store,self.cid)['next_action'],'limit_reached')
        with self.assertRaisesRegex(ValueError,'limit'):self.claim(request='again')
        with self.assertRaises(ValueError):self.call('finish','finish',report_id='missing',meaning_review='Cannot finish')

    def test_completed_campaign_stops_schedule_and_reopens_only_after_changed_state(self):
        self.configure()
        value,j=fixtures.ResearchLoopTests.investigated(self,verified=True)
        head=loop.checkpoint(self.store,'full',value)['id']
        from synthesis import make_report
        report=self.fx.action([j]);report.update(research_stage='baseline_review',campaign_id=self.cid,checkpoint_id=head,
            research_execution={'status':'excluded_by_user','reason':'Synthetic full coverage fixture'})
        rid=make_report(self.store,'report',report)['id']
        self.call('schedule','schedule',schedule_id='host',status='active',host='test',receipt='synthetic')
        self.call('finish','finish',report_id=rid,meaning_review='Synthetic structure only; not real acceptance')
        self.assertEqual(coord.status(self.store,self.cid)['next_action'],'stop_schedule')
        with self.assertRaisesRegex(ValueError,'completed'):self.claim()
        self.call('schedule','stop',schedule_id='host',status='stopped',host='test',receipt='synthetic stop')
        self.assertEqual(coord.status(self.store,self.cid)['next_action'],'completed')
        loop.change_nodes(self.store,'added',dict(campaign_id=self.cid,previous_id=head,operation='add',source_ids=[],
            new_nodes=[dict(node_id='EXTRA',name='New node',scope='Synthetic')],reason='New scope',effective_date='2026-09-14'))
        self.assertEqual(coord.status(self.store,self.cid)['mode'],'paused')

    checkpoint_input=fixtures.ResearchLoopTests.checkpoint_input

    def test_invalid_closed_result_does_not_advance_checkpoint(self):
        self.configure();j=self.claim('A02');v,_=fixtures.ResearchLoopTests.investigated(self)
        result=dict(nodes=[n for n in v['nodes'] if n['node_id']=='A02'],
                    questions=[q for q in v['questions'] if q['node_id']=='A02'],summary='Synthetic template failure',remaining_work=[])
        self.call('submit','bad-result',job_id=j,result=result)
        with self.assertRaisesRegex(ValueError,'closure'):self.apply(j,digest(result))
        self.assertEqual(loop.current(self.store,self.cid)[0],self.cid)

    def test_workflow_respects_pause_instead_of_starting_new_work(self):
        import user_workflow
        self.configure();self.call('control','pause',mode='paused',reason='User pause')
        result=user_workflow.route(dict(intent='resume',state_dir=str(self.store.folder),project_id=self.store.project_id))
        self.assertEqual(result['status'],'coordinated_research')
        self.assertEqual(result['coordination']['next_action'],'paused')

    def test_concurrent_processes_cannot_claim_same_domain(self):
        self.configure();cli=Path(loop.__file__).parents[1]/'research_cli.py';processes=[]
        for i in range(2):
            action=dict(op='coordination-claim',state_dir=str(self.store.folder),project_id=self.store.project_id,
                request_id='race-'+str(i),data=dict(campaign_id=self.cid,domain_id='semiconductors',node_ids=['A01'],worker_id='w'+str(i)))
            file=self.store.folder/('race-'+str(i)+'.json');file.write_text(json.dumps(action))
            processes.append(subprocess.Popen([sys.executable,'-X','utf8',str(cli),'--action',str(file)],stdout=subprocess.PIPE,stderr=subprocess.PIPE))
        codes=[]
        for p in processes:p.communicate(timeout=20);codes.append(p.returncode)
        self.assertEqual(sorted(codes),[0,1]);self.assertEqual(len(coord.status(self.store,self.cid)['active_jobs']),1)

    def test_real_separate_process_cli_restores_coordinator_state(self):
        self.configure();self.claim();f=self.store.folder/'read-action.json'
        f.write_text(json.dumps(dict(op='coordination-status',state_dir=str(self.store.folder),project_id=self.store.project_id,campaign_id=self.cid)))
        cli=Path(loop.__file__).parents[1]/'research_cli.py'
        p=subprocess.run([sys.executable,'-X','utf8',str(cli),'--action',str(f)],capture_output=True,text=True,encoding='utf-8')
        self.assertEqual(p.returncode,0,p.stderr);self.assertEqual(len(json.loads(p.stdout)['active_jobs']),1)

if __name__=='__main__':unittest.main()
