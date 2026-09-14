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

    def investigated(self,verified=False):
        j=self.fx.judgment(node='A01')[0];d=research.data(self.store,j)
        doc=research.data(self.store,d['support_ids'][0])['document_id']
        v=self.checkpoint_input()
        for n in v['nodes']:
            n.update(disposition='investigated',reason='Synthetic investigation found no accessible data')
            if n['node_id']=='A01':n.update(disposition='selected',reason='Synthetic source screened',document_ids=[doc])
        v['questions']=[dict(id=dim,node_id='A01',dimension=dim,question=dim,status='resolved',
            attempts=[dict(route='synthetic issuer document',outcome='found',finding='Synthetic direct evidence',document_ids=[doc])],
            answer='Synthetic scope-limited answer',closure_reason='Synthetic review',judgment_ids=[j])for dim in loop.DIMENSIONS]
        for n in v['nodes']:
            if n['node_id']=='A01':continue
            for dim in loop.DIMENSIONS:
                v['questions'].append(dict(id=n['node_id']+'-'+dim,node_id=n['node_id'],dimension=dim,
                    question='Synthetic '+dim,status='bounded',answer='Unknown after synthetic investigation',
                    closure_reason='Synthetic routes exhausted',remaining_uncertainty='No usable data',
                    why_more_search_unlikely='Synthetic fixture only; actual source availability was not assessed',
                    attempts=[dict(route=route,outcome='unavailable',finding='Synthetic access limit',document_ids=[])
                              for route in ('official archive','independent source')]))
        if verified:
            # Synthetic source-location coverage, not realistic research sufficiency.
            # Keep the old paper-only fixture for the explicit regression below.
            lines=[[f'Synthetic registry case {i+1000}: delivery information is not disclosed for this test item.'
                    for i in range(len(v['questions']))],
                   [f'Synthetic permit case {i+1000}: approval listed; operational schedule not reported.'
                    for i in range(len(v['questions']))]]
            docs=[self.store.capture({'url':f'https://example.com/registry-{i}','producer':f'Test registry {i}'},
                 '\n'.join(lines[i]).encode(),'text/plain',{})['document_id'] for i in range(2)]
            for i,q in enumerate(v['questions']):
                if q['node_id']=='A01':
                    q['answer']='Synthetic response for dimension '+q['dimension']
                    q['source_reviews']=[dict(document_id=doc,location='block:1',quote='Demand exceeds usable supply.',
                        role='direct',finding='Test support',relevance='Synthetic scope only')]
                else:
                    q['answer']=f'Registry case {i+1000} lacks delivery disclosure; no quantitative conclusion.'
                    q['attempts']=[dict(route=f'registry-{a}',outcome='irrelevant',finding=lines[a][i],document_ids=[d])
                                   for a,d in enumerate(docs)]
                    q['source_reviews']=[dict(document_id=d,location=f'block:{i+1}',quote=lines[a][i],role='gap_probe',
                        finding=lines[a][i],relevance='Test missing disclosure, not a physical shortage') for a,d in enumerate(docs)]
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
        v,j=self.investigated();v['questions']=[q for q in v['questions'] if not(q['node_id']=='A01' and q['dimension']=='history')]
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
        v,j=self.investigated(verified=True);rid=loop.checkpoint(self.store,'c1',v)['id']
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
        v,j=self.investigated(verified=True);rid=loop.checkpoint(self.store,'ready',v)['id']
        report=self.fx.action([j]);report.update(research_stage='baseline_review',campaign_id=self.cid,checkpoint_id=rid)
        with self.assertRaisesRegex(ValueError,'execution'):make_report(self.store,'not-run',report)
        report['research_execution']={'status':'excluded_by_user','reason':'Synthetic explicit exclusion fixture'}
        out=make_report(self.store,'review',report)['id']
        self.assertEqual(research.data(self.store,out)['research_stage'],'baseline_review')

    def test_unselected_node_without_investigation_cannot_pass(self):
        v,j=self.investigated()
        v['questions']=[q for q in v['questions'] if q['node_id']!='A02']
        loop.checkpoint(self.store,'uninvestigated',v)
        state=loop.resume(self.store,self.cid)
        self.assertFalse(state['ready_for_review'])
        self.assertFalse(state['full_inventory_investigated'])
        self.assertEqual(len([p for p in state['pending'] if p['node_id']=='A02']),5)

    def test_exclusion_cannot_bypass_initial_census(self):
        v,j=self.investigated();v['nodes'][1]['disposition']='excluded'
        with self.assertRaisesRegex(ValueError,'exclusion'):loop.checkpoint(self.store,'exclude',v)

    def test_legacy_excluded_node_returns_to_pending(self):
        v,j=self.investigated();v['nodes'][1]['disposition']='excluded'
        self.store.append('task','legacy',{'type':'research_checkpoint',**v},[self.cid])
        state=loop.resume(self.store,self.cid)
        self.assertFalse(state['full_inventory_investigated'])
        self.assertTrue(any(p['node_id']==v['nodes'][1]['node_id'] and p['action']=='screen' for p in state['pending']))

    def test_gaps_after_every_node_investigated_are_allowed(self):
        v,j=self.investigated(verified=True);loop.checkpoint(self.store,'full',v)
        state=loop.resume(self.store,self.cid)
        self.assertTrue(state['full_inventory_investigated'])
        self.assertTrue(state['ready_for_review'])
        self.assertEqual(len({q['node_id'] for q in state['questions']}),87)
        self.assertTrue(any(q['status']=='bounded' for q in state['questions']))

class NodeEvolutionTests(unittest.TestCase):
    setUp=ResearchLoopTests.setUp
    investigated=ResearchLoopTests.investigated
    checkpoint_input=ResearchLoopTests.checkpoint_input
    # Keep the shared fixture, without re-running inherited test methods.
    def change(self,op,sources,new,request='change'):
        state=loop.resume(self.store,self.cid)
        return loop.change_nodes(self.store,request,dict(campaign_id=self.cid,previous_id=state['checkpoint_id'],
            operation=op,source_ids=sources,new_nodes=[dict(node_id=i,name=i,scope='Synthetic differentiated scope') for i in new],
            reason='Synthetic catalog change',effective_date='2026-09-14'))

    def test_add_split_merge_preserves_history_and_restarts_research(self):
        v,j=self.investigated();loop.checkpoint(self.store,'initial',v)
        before=research.data(self.store,j)
        self.change('add',[],['NEW-1'],'add')
        self.change('split',['A01'],['A01-X','A01-Y'],'split')
        self.change('merge',['A01-X','A01-Y'],['A01-Z'],'merge')
        state=loop.resume(self.store,self.cid);nodes={n['node_id']:n for n in state['nodes']}
        self.assertEqual(len(nodes),91)
        self.assertEqual(sum(loop.active(n) for n in nodes.values()),88)
        self.assertEqual(nodes['A01']['replacement_ids'],['A01-X','A01-Y'])
        self.assertEqual(nodes['A01-Z']['predecessor_ids'],['A01-X','A01-Y'])
        self.assertFalse(state['ready_for_review'])
        self.assertEqual(research.data(self.store,j),before)
        self.assertTrue(any(q['node_id']=='A01' for q in state['questions']))
        self.assertTrue(any(p['node_id']=='A01-Z' for p in state['pending']))
        cid=loop.start(self.store,'next-campaign',{'objective':'Next study','as_of_date':'2026-09-14'})['id']
        self.assertEqual(len(loop.resume(self.store,cid)['nodes']),91)

    def test_id_reuse_and_direct_retirement_rejected(self):
        self.change('split',['A01'],['X','Y'])
        with self.assertRaisesRegex(ValueError,'reuse'):self.change('add',[],['A01'],'reuse')
        with self.assertRaisesRegex(ValueError,'active'):self.change('split',['A01'],['Q','R'],'retired')
        self.state=loop.resume(self.store,self.cid);v=self.checkpoint_input()
        v['nodes'][1]['lifecycle']='retired'
        with self.assertRaisesRegex(ValueError,'definitions'):loop.checkpoint(self.store,'tamper',v)
        v['nodes'][1]['lifecycle']=None
        with self.assertRaisesRegex(ValueError,'definitions'):loop.checkpoint(self.store,'null-retire',v)

    def test_retry_stale_and_cross_campaign_catalog_conflict(self):
        value=dict(campaign_id=self.cid,previous_id=self.cid,operation='add',source_ids=[],
            new_nodes=[dict(node_id='N',name='New',scope='Synthetic')],reason='Synthetic',effective_date='2026-09-14')
        cid=loop.start(self.store,'parallel',{'objective':'Parallel','as_of_date':'2026-09-14'})['id']
        r=loop.change_nodes(self.store,'once',value)
        self.assertEqual(loop.change_nodes(self.store,'once',value)['id'],r['id'])
        with self.assertRaisesRegex(ValueError,'Stale'):loop.change_nodes(self.store,'stale',value)
        value.update(campaign_id=cid,previous_id=cid)
        with self.assertRaisesRegex(ValueError,'Catalog advanced'):loop.change_nodes(self.store,'cross',value)

    def test_bad_cardinality_and_future_effective_date(self):
        with self.assertRaisesRegex(ValueError,'cardinality'):self.change('merge',['A01'],['N'])
        with self.assertRaisesRegex(ValueError,'cardinality'):self.change('split',['A01'],['N'])
        value=dict(campaign_id=self.cid,previous_id=self.cid,operation='add',source_ids=[],
            new_nodes=[dict(node_id='N',name='New',scope='Synthetic')],reason='Synthetic',effective_date='2026-09-15')
        with self.assertRaisesRegex(ValueError,'cutoff'):loop.change_nodes(self.store,'future',value)

if __name__=='__main__':unittest.main()
