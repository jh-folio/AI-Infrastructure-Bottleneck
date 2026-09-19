"""P4/P5: targeted routing, discovery, resume and existing host ownership boundaries."""
import copy
from datetime import timedelta
from unittest.mock import patch
import unittest
import test_review_reuse as fixtures
import research_impact as impact
import research_loop as loop
import research_coordination as coord
import review_reuse
import source_work


class ImpactTests(unittest.TestCase):
    def setUp(self):
        self.fx=fixtures.ReviewReuseTests();self.fx.setUp();self.addCleanup(self.fx.doCleanups)
        self.store=self.fx.store;self.cid=self.fx.cid;self.n=0

    def scan(self,**kw):
        self.n+=1
        return impact.scan(self.store,'scan-'+str(self.n),dict(campaign_id=self.cid,checkpoint_id=loop.current(self.store,self.cid)[0],**kw))

    def test_baseline_then_shared_source_correction_routes_questions(self):
        first=self.scan();self.assertEqual(first['affected_question_count'],0)
        q=loop.question(self.store,self.cid,self.fx.qid)['question'];doc=self.store.document(q['source_reviews'][0]['document_id'])
        self.store.capture(dict(url=doc['url'],producer=doc['producer']),b'Changed original','text/plain',doc['metadata'])
        changed=self.scan();targets=impact.details(self.store,changed['id'])['targets']
        self.assertEqual({t['node_id'] for t in targets['items']},{'A01'})
        self.assertTrue(all(t['paths'] for t in targets['items']))
        self.assertTrue(any(p['action']=='review_changed_dependencies' for p in loop.resume(self.store,self.cid)['pending']))
        self.assertEqual(self.scan()['affected_question_count'],0)
        self.assertFalse(loop.resume(self.store,self.cid)['ready_for_review'])

    def test_explicit_scan_retry_and_stale(self):
        q=loop.question(self.store,self.cid,self.fx.qid)['question'];doc=q['source_reviews'][0]['document_id']
        value=dict(campaign_id=self.cid,checkpoint_id=loop.current(self.store,self.cid)[0],document_ids=[doc])
        first=impact.scan(self.store,'stable',value)
        self.assertEqual(impact.scan(self.store,'stable',value)['id'],first['id'])
        self.assertFalse(impact.scan(self.store,'stable',value)['inserted'])
        with self.assertRaises(ValueError):impact.scan(self.store,'stable',dict(value,explore=True))
        with self.assertRaises(ValueError):impact.scan(self.store,'bad',dict(value,checkpoint_id='stale'))

    def test_periodic_discovery_is_persistent_and_paginated(self):
        baseline=self.scan(discovery_interval_days=7)
        future=review_reuse.timestamp(baseline['next_discovery_at'])+timedelta(seconds=1)
        with patch('research_impact.clock',return_value=future):
            periodic=self.scan()
        page=impact.details(self.store,periodic['id'],0,3)['targets']
        self.assertEqual(page['total'],435)
        self.assertEqual(page['next_offset'],3)
        self.assertEqual(self.store.record(periodic['id'])['payload']['data']['discovery_interval_days'],7)
        self.assertFalse(loop.resume(self.store,self.cid)['ready_for_review'])

    def test_unknown_new_source_cannot_disappear_from_work(self):
        self.scan()
        self.store.capture(dict(url='https://example.com/unclassified-p4',producer='Synthetic'),b'Unknown scope','text/plain',{})
        result=self.scan()
        self.assertEqual(result['affected_question_count'],435)
        self.assertIn('unclassified_new_source',{r.get('reason') for r in impact.details(self.store,result['id'])['targets']['items']})

    def test_scoped_lead_does_not_reopen_other_domain(self):
        self.scan()
        source_work.source_plan(self.store,'scope-lead',dict(campaign_id=self.cid,
            source=dict(url='https://example.com/scope-lead',producer='Synthetic',kind='public_document'),
            bindings=[dict(node_id='C01',dimensions=['history'],purpose='Read historical manufacturing limits')]))
        result=self.scan();targets=impact.details(self.store,result['id'])['targets']['items']
        self.assertEqual([t['question_id'] for t in targets],['C01-history'])

    def test_current_author_review_acknowledges_routed_legacy_question(self):
        q=loop.question(self.store,self.cid,self.fx.qid)['question']
        result=self.scan(document_ids=[q['source_reviews'][0]['document_id']])
        with self.assertRaises(ValueError):self.fx.seal()
        self.fx.seal(candidate_reviews={result['id']:dict(disposition='not_material',reason='Read routed original; historical scope and conclusion unchanged')})
        pending=impact.pending(self.store,self.cid,loop.current(self.store,self.cid)[1])
        self.assertNotIn(self.fx.qid,{p['question_id'] for p in pending})
        self.assertTrue(review_reuse.status(self.store,dict(campaign_id=self.cid,question_id=self.fx.qid,role='author'))['reuse_allowed'])

    def test_source_relation_routes_downstream_without_scoring(self):
        import supply_view
        self.scan()
        from research import data
        q=loop.question(self.store,self.cid,self.fx.qid)['question']
        eid=data(self.store,q['judgment_ids'][0])['support_ids'][0]
        relation=supply_view.relation(self.store,'technical-edge',dict(campaign_id=self.cid,from_node_id='A01',to_node_id='C01',
            kind='technical',reason='Synthetic dependency only',scope='Synthetic qualified interface',evidence_ids=[eid],as_of_date='2026-09-14'))
        result=self.scan(record_ids=[relation['id']])
        nodes={t['node_id'] for t in impact.details(self.store,result['id'],limit=50)['targets']['items']}
        self.assertTrue({'A01','C01'}<=nodes)
        self.assertNotIn('score',impact.details(self.store,result['id']))

    def test_dispatch_sequential_parallel_and_occupied_domains(self):
        self.scan(explore=True)
        def config(parallel):
            return dict(campaign_id=self.cid,parallel_supported=parallel,automatic_resume_requested=False,
                        concurrency=2,lease_minutes=30,max_runs=5,max_failures=5)
        coord.execute(self.store,'configure','serial',config(False))
        self.assertEqual(len(impact.dispatch(self.store,self.cid)['claim_actions']),1)
        self.cid=loop.start(self.store,'parallel-campaign',dict(objective='Parallel synthetic run',as_of_date='2026-09-14'))['id']
        coord.execute(self.store,'configure','parallel',config(True))
        actions=impact.dispatch(self.store,self.cid)['claim_actions'];self.assertEqual(len(actions),2)
        job=coord.execute(self.store,'claim','claim-one',dict(actions[0]['data'],worker_id='worker'))
        remaining=impact.dispatch(self.store,self.cid)['claim_actions']
        self.assertEqual(len(remaining),1)
        self.assertNotEqual(remaining[0]['data']['domain_id'],actions[0]['data']['domain_id'])
        coord.execute(self.store,'release','release-one',dict(campaign_id=self.cid,job_id=job['id'],reason='Synthetic retry'))
        self.assertNotEqual(impact.dispatch(self.store,self.cid)['claim_actions'][0]['data']['domain_id'],actions[0]['data']['domain_id'])

    def test_failed_refresh_and_unscoped_event_remain_pending(self):
        self.scan()
        q=loop.question(self.store,self.cid,self.fx.qid)['question'];doc=self.store.document(q['source_reviews'][0]['document_id'])
        self.store.capture(dict(url=doc['url'],producer=doc['producer']),None,doc['mime'],{},status='failed')
        result=self.scan()
        self.assertIn(self.fx.qid,{t['question_id'] for t in impact.details(self.store,result['id'])['targets']['items']})
        self.store.append('event','unclassified-event',dict(description='Synthetic unclassified interruption'))
        self.assertEqual(self.scan()['affected_question_count'],435)

    def test_monitor_adapter_failure_without_capture_still_requires_review(self):
        self.fx.seal();self.scan()
        self.store.append('task','adapter-exception',dict(type='monitor_step',source={'id':'synthetic'},result={'status':'failed','error_type':'ValueError'}))
        self.assertEqual(self.scan()['affected_question_count'],435)
        self.assertFalse(self.fx.status()['reuse_allowed'])

    def test_durable_restore_preserves_pending_scan(self):
        import durable_state as durable
        from research_store import Store
        folder=self.store.folder.parent/'impact-backup';folder.mkdir()
        result=self.scan(explore=True)
        durable.sync(self.store,str(folder))
        destination=self.store.folder.parent/'impact-restored'
        durable.restore_latest(str(folder),str(destination),self.store.project_id)
        restored=Store(destination,self.store.project_id)
        self.assertEqual(impact.details(restored,result['id']),impact.details(self.store,result['id']))
        self.assertEqual(loop.resume(restored,self.cid)['pending'],loop.resume(self.store,self.cid)['pending'])

    def test_completed_campaign_with_new_scan_pauses_and_dispatch_does_not_claim(self):
        head=loop.current(self.store,self.cid)[0]
        self.store.append('task','synthetic-finish',dict(type='research_coordination',operation='finish',campaign_id=self.cid,completed_checkpoint=head))
        self.scan(explore=True)
        self.assertEqual(coord.state(self.store,self.cid)['mode'],'paused')
        self.assertEqual(impact.dispatch(self.store,self.cid)['claim_actions'],[])

    def test_changed_judgment_routes_synthesis_review(self):
        from research import data
        q=loop.question(self.store,self.cid,self.fx.qid)['question'];jid=q['judgment_ids'][0]
        report=self.store.append('report','synthetic-report',dict(title='Synthetic report'),[jid])
        result=self.scan(record_ids=[jid])
        self.assertIn(report['id'],impact.details(self.store,result['id'])['affected_report_ids'])


if __name__=='__main__':unittest.main()
