import copy
import unittest
import test_synthesis
import research_loop as loop
import research
from research_store import Store
from synthesis import make_report

class ResearchLoopTests(unittest.TestCase):
    def setUp(self):
        self.fx=test_synthesis.SynthesisTests();self.fx.setUp();self.addCleanup(self.fx.doCleanups)
        self.store=self.fx.store
        self.cid=loop.start(self.store,'start',{'objective':'Synthetic full inventory review','as_of_date':'2026-09-14'})['id']
        self.state=loop.resume(self.store,self.cid)

    def checkpoint_input(self):
        return {'campaign_id':self.cid,'previous_id':self.state['checkpoint_id'],
                'nodes':copy.deepcopy(self.state['nodes']),'questions':copy.deepcopy(self.state['questions'])}

    def investigated(self):
        j=self.fx.judgment(node='A01')[0];d=research.data(self.store,j)
        doc=research.data(self.store,d['support_ids'][0])['document_id']
        v=self.checkpoint_input()
        for n in v['nodes']:
            n.update(disposition='excluded',reason='Synthetic narrow test scope; not a product coverage claim')
            if n['node_id']=='A01':n.update(disposition='selected',reason='Synthetic source screened',document_ids=[doc])
        v['questions']=[dict(id=dim,node_id='A01',dimension=dim,question=dim,status='resolved',
            attempts=[dict(route='synthetic issuer document',outcome='found',finding='Synthetic direct evidence',document_ids=[doc])],
            answer='Synthetic scope-limited answer',closure_reason='Synthetic review',judgment_ids=[j])for dim in loop.DIMENSIONS]
        return v,j

    def test_inventory_resume_and_idempotence(self):
        self.assertEqual(len(self.state['nodes']),87);self.assertFalse(self.state['ready_for_review'])
        self.assertEqual(len(self.state['pending']),87)
        self.assertFalse(loop.start(self.store,'start',{'objective':'Synthetic full inventory review','as_of_date':'2026-09-14'})['inserted'])
        other=Store(self.store.folder,self.store.project_id)
        self.assertEqual(loop.resume(other,self.cid),self.state)

    def test_small_work_packets_do_not_dump_the_ledger(self):
        packet=loop.next_work(self.store,self.cid,3)
        self.assertEqual(len(packet['next_actions']),3)
        self.assertEqual(packet['pending_count'],87)
        self.assertNotIn('questions',packet)
        with self.assertRaises(ValueError):loop.next_work(self.store,self.cid,True)

    def test_missing_history_question_keeps_research_open(self):
        v,j=self.investigated();v['questions']=[q for q in v['questions'] if q['dimension']!='history']
        loop.checkpoint(self.store,'no-history',v)
        state=loop.resume(self.store,self.cid)
        self.assertFalse(state['ready_for_review'])
        self.assertTrue(any(p.get('dimension')=='history' for p in state['pending']))

    def test_short_run_cannot_be_baseline_but_interim_survives(self):
        v=self.fx.action([self.fx.judgment()[0]])
        v.update(research_stage='baseline_review',campaign_id=self.cid,checkpoint_id=self.cid)
        with self.assertRaisesRegex(ValueError,'incomplete'):make_report(self.store,'premature',v)
        v['research_stage']='interim'
        rid=make_report(self.store,'interim',v)['id']
        self.assertIn('조사 중간 결과',research.data(self.store,rid)['markdown'])

    def test_checkpoints_preserve_work_and_reject_stale_writes(self):
        v,j=self.investigated();rid=loop.checkpoint(self.store,'c1',v)['id']
        self.assertFalse(loop.checkpoint(self.store,'c1',v)['inserted'])
        with self.assertRaisesRegex(ValueError,'Stale'):loop.checkpoint(self.store,'stale',v)
        self.state=loop.resume(self.store,self.cid);v=self.checkpoint_input();v['questions'].pop()
        with self.assertRaisesRegex(ValueError,'erase'):loop.checkpoint(self.store,'erase',v)
        self.assertTrue(self.state['ready_for_review'])

    def test_failure_does_not_close_gap(self):
        v,j=self.investigated();q=v['questions'][0]
        q.update(status='bounded',remaining_uncertainty='Unknown',why_more_search_unlikely='Claimed exhausted')
        q['attempts']=[dict(route='IR',outcome='failed',finding='network error',document_ids=[])]
        with self.assertRaisesRegex(ValueError,'alternative'):loop.checkpoint(self.store,'fail',v)
        q.update(status='blocked',next_action='Try official filing mirror')
        loop.checkpoint(self.store,'blocked',v)
        self.assertFalse(loop.resume(self.store,self.cid)['ready_for_review'])

    def test_wrong_node_and_erased_history_rejected(self):
        v,j=self.investigated();v['questions'][0]['node_id']='A02'
        with self.assertRaisesRegex(ValueError,'mismatch'):loop.checkpoint(self.store,'wrong',v)
        v['questions'][0]['node_id']='A01';loop.checkpoint(self.store,'ok',v)
        self.state=loop.resume(self.store,self.cid);v=self.checkpoint_input()
        v['questions'][0]['attempts'][0]['finding']='Changed history'
        with self.assertRaisesRegex(ValueError,'history'):loop.checkpoint(self.store,'rewrite',v)

    def test_deep_execution_and_scope_required_for_review(self):
        v,j=self.investigated();rid=loop.checkpoint(self.store,'ready',v)['id']
        report=self.fx.action([j]);report.update(research_stage='baseline_review',campaign_id=self.cid,checkpoint_id=rid)
        with self.assertRaisesRegex(ValueError,'execution'):make_report(self.store,'not-run',report)
        report['research_execution']={'status':'excluded_by_user','reason':'Synthetic explicit exclusion fixture'}
        out=make_report(self.store,'review',report)['id']
        self.assertEqual(research.data(self.store,out)['research_stage'],'baseline_review')

if __name__=='__main__':unittest.main()
