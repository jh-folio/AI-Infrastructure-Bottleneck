"""Review receipt validity is not semantic certification. All inputs are synthetic."""
import copy
from datetime import datetime, timezone, timedelta
import unittest
from unittest.mock import patch
import test_research_loop as fixtures
import research_loop as loop
import review_reuse as reuse
import source_work
from research import data
from research_quality import completion


class ReviewReuseTests(unittest.TestCase):
    def setUp(self):
        self.fx=fixtures.ResearchLoopTests();self.fx.setUp();self.addCleanup(self.fx.doCleanups)
        self.store=self.fx.store;self.cid=self.fx.cid
        state,_=self.fx.investigated(verified=True)
        loop.checkpoint(self.store,'verified-fixture',state)
        self.qid=state['questions'][0]['id']
        self.n=0

    def value(self,**extra):
        value=dict(campaign_id=self.cid,checkpoint_id=loop.current(self.store,self.cid)[0],question_id=self.qid,
                   role='author',reviewer='synthetic-author',review_note='Reviewed source scope and competing supply explanation',
                   next_review_at=(reuse.now()+timedelta(days=1)).isoformat(),trigger_notes='Recheck planned commissioning or new counterevidence')
        value.update(extra);return value

    def seal(self,**extra):
        self.n+=1
        return reuse.seal(self.store,'review-'+str(self.n),self.value(**extra))

    def status(self,**extra):
        return reuse.status(self.store,dict(campaign_id=self.cid,question_id=self.qid,role='author',**extra))

    def test_same_campaign_valid_reuse_and_replay(self):
        self.assertEqual(self.status()['status'],'missing')
        value=self.value();record=reuse.seal(self.store,'seal',value)
        self.assertFalse(reuse.seal(self.store,'seal',value)['inserted'])
        self.assertTrue(self.status()['reuse_allowed'])
        action=dict(campaign_id=self.cid,question_id=self.qid,role='author',review_id=record['id'])
        result=reuse.reuse(self.store,'use',action)
        self.assertFalse(reuse.reuse(self.store,'use',action)['inserted'])
        self.assertEqual(data(self.store,result['id'])['review_id'],record['id'])
        self.assertTrue(loop.resume(self.store,self.cid)['ready_for_review'])

    def test_unrelated_checkpoint_and_scoped_source_do_not_invalidate(self):
        self.seal();head,state=loop.current(self.store,self.cid)
        other=copy.deepcopy(state['questions'][5]);other['next_action']='Unrelated inspection note'
        loop.patch(self.store,'other-node',dict(campaign_id=self.cid,previous_id=head,questions=[other]))
        source_work.source_plan(self.store,'other-plan',dict(campaign_id=self.cid,
            source={'url':'https://example.com/unrelated','producer':'Synthetic','kind':'public_document'},
            bindings=[dict(node_id='A02',dimensions=['history'],purpose='Other node chronology')]))
        self.store.capture({'url':'https://example.com/unrelated','producer':'Synthetic'},b'Other node source','text/plain',{'published_at':'2026-01-01'})
        self.assertEqual(self.status()['status'],'valid')

    def test_new_unknown_source_blocks_completion_until_explicit_review(self):
        self.seal()
        doc=self.store.capture({'url':'https://example.com/new','producer':'Synthetic'},b'Potential new evidence','text/plain',{'published_at':'2026-01-01'})['document_id']
        status=self.status()
        self.assertEqual(status['status'],'pending_relevance')
        self.assertFalse(loop.resume(self.store,self.cid)['ready_for_review'])
        self.assertIn('research_incomplete',completion(self.store,self.cid)['reasons'])
        with self.assertRaises(ValueError):self.seal()
        self.seal(candidate_reviews={doc:dict(disposition='not_material',reason='Inspected original; concerns a different product population')})
        self.assertTrue(self.status()['reuse_allowed'])

    def test_new_same_url_version_requires_review_and_paged_candidates(self):
        self.seal();q=loop.question(self.store,self.cid,self.qid)['question']
        doc=self.store.document(q['source_reviews'][0]['document_id'])
        for i in range(3):self.store.capture({'url':doc['url'],'producer':doc['producer']},('Corrected '+str(i)).encode(),'text/plain',doc['metadata'])
        result=self.status(limit=1)
        self.assertEqual(result['candidates']['total'],3)
        self.assertEqual(result['candidates']['next_offset'],1)
        self.assertEqual(result['candidates']['items'][0]['reason'],'source_version')
        self.store.capture({'url':'https://example.com/another','producer':'Synthetic'},b'New candidate','text/plain',{})
        with self.assertRaises(ValueError):self.status(limit=1,offset=1,inventory_sha256=result['inventory_sha256'])

    def test_corrected_current_evidence_can_be_reviewed_with_history_preserved(self):
        self.seal();q=copy.deepcopy(loop.question(self.store,self.cid,self.qid)['question'])
        judgment=copy.deepcopy(data(self.store,q['judgment_ids'][0]));eid=judgment['support_ids'][0]
        evidence=copy.deepcopy(data(self.store,eid));evidence.update(supersedes=eid,review_reason='Reviewed correction; exact quote retained')
        import research
        replacement=research.adopt(self.store,'corrected-accepted',evidence)['id']
        judgment['support_ids']=[replacement];judgment['reasoning']='Correction reviewed; original scope remains supported'
        q['judgment_ids']=[research.judgment(self.store,'corrected-judgment',judgment)['id']]
        loop.patch(self.store,'corrected-question',dict(campaign_id=self.cid,previous_id=loop.current(self.store,self.cid)[0],questions=[q]))
        decisions={c['id']:dict(disposition='incorporated',reason='Correction incorporated in current judgment') for c in self.status()['candidates']['items']}
        self.seal(candidate_reviews=decisions)
        self.assertTrue(self.status()['reuse_allowed'])
        self.assertEqual(data(self.store,replacement)['supersedes'],eid)

    def test_failed_refresh_is_not_unchanged_source(self):
        self.seal();q=loop.question(self.store,self.cid,self.qid)['question']
        doc=self.store.document(q['source_reviews'][0]['document_id'])
        self.store.capture({'url':doc['url'],'producer':doc['producer']},None,doc['mime'],{},status='failed',detail={'reason':'Synthetic unavailable'})
        result=self.status()
        self.assertEqual(result['status'],'pending_relevance')
        self.assertEqual(result['candidates']['items'][0]['reason'],'source_refresh_failed')
        self.assertFalse(loop.resume(self.store,self.cid)['ready_for_review'])

    def test_question_leads_scope_and_interpretation_changes_invalidate(self):
        self.seal();q=copy.deepcopy(loop.question(self.store,self.cid,self.qid)['question'])
        q['semantic_review']['counterargument']='New rival explanation requiring original review'
        loop.patch(self.store,'meaning-change',dict(campaign_id=self.cid,previous_id=loop.current(self.store,self.cid)[0],questions=[q]))
        self.assertEqual(self.status()['status'],'review_required')
        self.assertIn('review_dependencies_changed',self.status()['reasons'])

    def test_time_trigger_and_extraction_version_invalidate_unchanged_bytes(self):
        self.seal()
        with patch('review_reuse.now',return_value=datetime.now(timezone.utc)+timedelta(days=2)):
            self.assertIn('review_time_due',self.status()['reasons'])
        with patch('review_reuse.methods',return_value='changed-extraction'):
            self.assertIn('review_dependencies_changed',self.status()['reasons'])

    def test_author_cannot_satisfy_coordinator_role(self):
        self.seal()
        with self.assertRaises(ValueError):self.seal(role='coordinator')
        self.seal(role='coordinator',reviewer='synthetic-coordinator')
        self.assertTrue(reuse.status(self.store,dict(campaign_id=self.cid,question_id=self.qid,role='coordinator'))['reuse_allowed'])
        with self.assertRaises(ValueError):self.seal(role='final_synthesis')

    def test_missing_metadata_is_fail_closed(self):
        record=self.seal();value=copy.deepcopy(data(self.store,record['id']))
        for field in ('dependency_ids','reviewer','review_note','reviewed_at','trigger_notes'):
            missing=copy.deepcopy(value);missing.pop(field)
            self.assertEqual(reuse.inspect_receipt(self.store,missing)['status'],'review_required')
        value=copy.deepcopy(data(self.store,record['id']));value['dependencies']['documents']['missing']={}
        self.assertEqual(reuse.inspect_receipt(self.store,value)['status'],'review_required')

    def test_other_campaign_never_reuses_receipt(self):
        self.seal()
        cid=loop.start(self.store,'other',dict(objective='Another cutoff',as_of_date='2026-09-15'))['id']
        self.assertEqual(reuse.status(self.store,dict(campaign_id=cid,question_id=self.qid,role='author'))['status'],'missing')

    def test_superseded_evidence_cannot_be_resealed(self):
        self.seal();q=loop.question(self.store,self.cid,self.qid)['question']
        judgment=data(self.store,q['judgment_ids'][0]);eid=judgment['support_ids'][0]
        ev=copy.deepcopy(data(self.store,eid));ev.update(supersedes=eid,decision='rejected')
        import research
        research.adopt(self.store,'correction',ev)
        self.assertEqual(self.status()['status'],'review_required')
        with self.assertRaises(ValueError):self.seal()

    def test_new_scoped_counterevidence_and_lead_block_reuse(self):
        self.seal()
        q=loop.question(self.store,self.cid,self.qid)['question']
        eid=data(self.store,q['judgment_ids'][0])['counter_ids'][0]
        ev=copy.deepcopy(data(self.store,eid));ev['claim']='New counterevidence interpretation'
        import research
        research.adopt(self.store,'counter-update',ev)
        source_work.source_plan(self.store,'new-lead',dict(campaign_id=self.cid,
            source=dict(url='https://example.com/counter-route',producer='Synthetic',kind='public_document'),
            bindings=[dict(node_id='A01',dimensions=['demand_supply'],purpose='Material counterevidence route')]))
        result=self.status()
        self.assertEqual(result['status'],'pending_relevance')
        self.assertEqual(result['candidates']['total'],2)
        self.assertTrue(any(c['reason']=='new_lead' for c in result['candidates']['items']))

    def test_missing_original_and_scope_retirement_refuse_reuse(self):
        self.seal()
        with patch.object(self.store,'document',side_effect=ValueError('Unavailable original')):
            self.assertEqual(self.status()['status'],'review_required')
        head=loop.current(self.store,self.cid)[0]
        loop.change_nodes(self.store,'split-reviewed',dict(campaign_id=self.cid,previous_id=head,operation='split',
            source_ids=['A01'],new_nodes=[dict(node_id='A01-X',name='New product',scope='One product'),
                                        dict(node_id='A01-Y',name='Other product',scope='Another product')],
            reason='Distinct supply qualifications',effective_date='2026-09-14'))
        self.assertFalse(self.status()['reuse_allowed'])

    def test_stale_seal_different_input_and_use_refused(self):
        value=self.value();first=reuse.seal(self.store,'stable-seal',value)
        use=dict(campaign_id=self.cid,question_id=self.qid,role='author',review_id=first['id'])
        used=reuse.reuse(self.store,'old-use',use)
        with self.assertRaises(ValueError):reuse.seal(self.store,'stable-seal',dict(value,review_note='Changed statement'))
        q=copy.deepcopy(loop.question(self.store,self.cid,self.qid)['question']);q['answer']+=' revised'
        loop.patch(self.store,'revise',dict(campaign_id=self.cid,previous_id=value['checkpoint_id'],questions=[q]))
        with self.assertRaises(ValueError):reuse.seal(self.store,'stale-seal',value)
        with self.assertRaises(ValueError):reuse.reuse(self.store,'invalid-use',dict(campaign_id=self.cid,question_id=self.qid,role='author',review_id=first['id']))
        replay=reuse.reuse(self.store,'old-use',use)
        self.assertEqual(replay['id'],used['id'])
        self.assertFalse(replay['reuse_allowed'])

    def test_explicit_upstream_dependency_and_new_event(self):
        upstream=self.fx.fx.judgment(node='A02')[0]
        self.seal(dependency_ids=[upstream])
        self.store.append('event','upstream-delay',dict(scope={'node_id':'A02'},description='Synthetic upstream commissioning delay'))
        self.assertEqual(self.status()['status'],'pending_relevance')

    def test_bounded_gap_reuses_only_after_original_metadata_review(self):
        self.qid='A02-demand_supply'
        with self.assertRaises(ValueError):self.seal()
        q=copy.deepcopy(loop.question(self.store,self.cid,self.qid)['question'])
        replacements={}
        for review in q['source_reviews']:
            doc=self.store.document(review['document_id'])
            updated=self.store.capture({'url':doc['url'],'producer':doc['producer']},doc['raw'],doc['mime'],
                {'capture_kind':'original_bytes','published_at':'2026-09-01'})['document_id']
            replacements[doc['id']]=updated;review['document_id']=updated
        for attempt in list(q['attempts']):
            addition=copy.deepcopy(attempt);addition['document_ids']=[replacements[d] for d in attempt['document_ids']]
            q['attempts'].append(addition)
        loop.patch(self.store,'gap-metadata-review',dict(campaign_id=self.cid,previous_id=loop.current(self.store,self.cid)[0],questions=[q]))
        self.seal()
        self.assertTrue(self.status()['reuse_allowed'])

    def test_cli_usage_and_durable_receipt(self):
        import sys
        from pathlib import Path
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'plugin/runtime'))
        from research_cli import execute
        durable=self.store.folder.parent/'durable-reviews';durable.mkdir()
        common=dict(state_dir=str(self.store.folder),project_id=self.store.project_id,durable_dir=str(durable))
        result=execute(dict(common,op='review-seal',request_id='cli-seal',data=self.value()))
        self.assertEqual(result['durable']['status'],'saved')
        use=dict(campaign_id=self.cid,question_id=self.qid,role='author',review_id=result['id'])
        execute(dict(common,op='review-use',request_id='cli-use',data=use))
        execute(dict(common,op='review-use',request_id='cli-use',data=use))
        self.store.capture(dict(url='https://example.com/new-unclassified',producer='Synthetic'),b'New source','text/plain',{})
        for _ in range(2):execute(dict(common,op='review-status',data=dict(campaign_id=self.cid,question_id=self.qid,role='author')))
        from research_efficiency import usage_summary
        summary=usage_summary(self.store)
        self.assertEqual(summary['reused_review_count'],1)
        self.assertEqual(summary['invalidated_review_count'],1)
        self.assertEqual(summary['new_review_count'],1)
        self.assertIsNone(summary['actual_host_tokens'])


if __name__=='__main__':unittest.main()
