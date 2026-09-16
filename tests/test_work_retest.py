import copy
import json
from pathlib import Path
import unittest
import test_research_loop as fixtures
import research_loop as loop
import research
import dashboard
import delivery
import supply_view
from research_quality import inspect_questions
from synthesis import make_report
from research_store import digest


class WorkRetestTests(unittest.TestCase):
    setUp=fixtures.ResearchLoopTests.setUp
    investigated=fixtures.ResearchLoopTests.investigated
    checkpoint_input=fixtures.ResearchLoopTests.checkpoint_input

    def view(self,ids=None,request='view'):
        value=self.fx.action(ids or [])
        value.update(campaign_id=self.cid)
        rid=make_report(self.store,request,value)['id']
        return rid,dashboard.projection(self.store,rid)

    def issues(self,modify):
        v,_=self.investigated(verified=True)
        q=v['questions'][5]
        modify(q)
        issues=inspect_questions(self.store,v['nodes'],[q],'2026-09-14')
        return set(issues[0]['reasons']) if issues else set()

    def test_all_active_nodes_visible_without_judgments_or_scores(self):
        rid,view=self.view()
        self.assertEqual(len(view['nodes']),87)
        self.assertTrue(all(not n['judgments'] for n in view['nodes']))
        self.assertGreater(len(view['node_relations']),180)
        self.assertTrue(all(e['kind']=='reference' for e in view['node_relations']))
        self.assertIn('전체 조사 목록',research.data(self.store,rid)['markdown'])

    def test_split_keeps_old_snapshot_and_does_not_transfer_edges(self):
        rid,old=self.view()
        loop.change_nodes(self.store,'split',dict(campaign_id=self.cid,previous_id=self.cid,operation='split',
            source_ids=['A01'],new_nodes=[dict(node_id=x,name=x,scope='Test') for x in ('AA','AB')],reason='Fixture',effective_date='2026-09-14'))
        _,view=self.view(request='after')
        self.assertEqual(len(view['nodes']),88)
        self.assertNotIn('A01',{n['node_id'] for n in view['nodes']})
        self.assertFalse(any(e['from_node_id'] in ('AA','AB') or e['to_node_id'] in ('AA','AB') for e in view['node_relations']))
        self.assertEqual(dashboard.projection(self.store,rid),old)

    def test_multiple_scopes_remain_separate_on_same_node(self):
        a,_=self.fx.judgment(node='A03');b,_=self.fx.judgment(node='A03',region='Other')
        _,view=self.view([a,b])
        node=next(n for n in view['nodes'] if n['node_id']=='A03')
        self.assertEqual(len(node['judgments']),2)
        self.assertNotIn('score',node)

    def test_technical_node_edge_without_judgments_requires_source(self):
        _,j=self.fx.judgment(node='A03')
        v=dict(campaign_id=self.cid,from_node_id='A03',to_node_id='A01',kind='technical',reason='Synthetic technical dependency',
               scope='Synthetic scope',evidence_ids=[],as_of_date='2026-09-14')
        with self.assertRaisesRegex(ValueError,'source evidence'):supply_view.relation(self.store,'bad',v)
        v['evidence_ids']=j['support_ids'];supply_view.relation(self.store,'edge',v)
        _,view=self.view()
        matching=[e for e in view['node_relations'] if e['from_node_id']=='A03' and e['to_node_id']=='A01']
        self.assertEqual([e['kind'] for e in matching],['technical'])
        self.assertTrue(matching[0]['sources'][0]['url'].startswith('https://'))

    def test_events_without_score_survive_projection_and_snapshot(self):
        _,j=self.fx.judgment(node='A03',nature='external_plan')
        research.event(self.store,'plan',dict(scope=j['scope'],event_type='plan',event_date='2027-01-01',
            description='Synthetic target; not realized',evidence_ids=j['support_ids'],materiality='Test',review_reason='Plan only'))
        _,view=self.view()
        n=next(n for n in view['nodes'] if n['node_id']=='A03')
        self.assertEqual(len(n['events']),1)
        self.assertEqual(n['events'][0]['sources'][0]['nature'],'external_plan')
        self.assertFalse(n['judgments'])

    def test_bundle_identity_counts_hashes_and_no_database_write(self):
        rid,view=self.view()
        before=self.store.path.read_bytes();folder=Path(self.fx.tmp.name)/'delivery'
        result=delivery.export(self.store,rid,folder)
        manifest=json.loads((folder/'DELIVERY.json').read_text(encoding='utf8'))
        for item in manifest['files']:self.assertEqual(digest((folder/item['path']).read_bytes()),item['sha256'])
        completion=json.loads((folder/'completion_manifest.json').read_text())
        self.assertEqual(completion['active_nodes'],87)
        self.assertEqual(completion['snapshot_id'],view['snapshot_id'])
        self.assertEqual(before,self.store.path.read_bytes())
        with self.assertRaises(FileExistsError):delivery.export(self.store,rid,folder)

    def test_plan_is_not_current_realization(self):
        reasons=self.issues(lambda q:q['source_reviews'][0]['application'].update(nature='external_plan',time_use='current'))
        self.assertIn('plan_or_forecast_is_not_current_realization',reasons)

    def test_old_observation_needs_explicit_current_validity(self):
        reasons=self.issues(lambda q:q['source_reviews'][0]['application'].update(observation_date='2024-01-01',time_use='current'))
        self.assertIn('current_claim_needs_dated_observation_and_validity',reasons)

    def test_generator_population_cannot_directly_resolve_load_question(self):
        v,_=self.investigated(verified=True);q=v['questions'][0]
        q['source_reviews'][0]['application'].update(source_population='Generation interconnection',target_population='Large load connection',fit='context')
        reasons=inspect_questions(self.store,v['nodes'],[q])[0]['reasons']
        self.assertIn('context_population_cannot_resolve_target',reasons)

    def test_outstanding_promising_lead_prevents_gap_closure(self):
        self.assertIn('promising_lead_remains_open',self.issues(lambda q:q['semantic_review']['gap']['leads'][0].update(disposition='pending')))

    def test_search_traces_alone_cannot_close_gap(self):
        def change(q):
            for s in q['source_reviews']:s.update(role='search_trace',query='query')
        self.assertIn('original_review_required_before_closure',self.issues(change))

    def test_shared_quote_can_support_distinct_nodes_with_application_review(self):
        v,_=self.investigated(verified=True);a,b=v['questions'][5],v['questions'][10]
        b['source_reviews']=copy.deepcopy(a['source_reviews'])
        for q in (a,b):q['semantic_review']['shared_source_review']=dict(node_specific_application=q['node_id']+' applicability',
            different_from_other_nodes=q['node_id']+' different scope',limitations='Common source not independent corroboration')
        self.assertEqual(inspect_questions(self.store,v['nodes'],[a,b]),[])
        b['answer']=a['answer']
        self.assertIn('repeated_conclusion_across_nodes',inspect_questions(self.store,v['nodes'],[a,b])[0]['reasons'])

    def test_unreviewed_semantics_and_single_date_trend_return_to_queue(self):
        self.assertIn('missing_semantic_review',self.issues(lambda q:q.pop('semantic_review')))
        v,_=self.investigated(verified=True);q=v['questions'][1];q['semantic_review']['chronology']=[]
        self.assertIn('history_or_trend_needs_distinct_dated_events',inspect_questions(self.store,v['nodes'],[q])[0]['reasons'])

    def test_internal_tool_url_not_exposed_as_original_link(self):
        source=supply_view.public_source({},dict(id='id',url='web-open:internal',producer='Host',sha256='hash',metadata='{}'))
        self.assertIsNone(source['url']);self.assertEqual(source['source_status'],'original_url_missing')

    def test_future_observation_rejected_at_adoption(self):
        with self.assertRaisesRegex(ValueError,'Future target'):self.fx.judgment(observed='2027-01-01')

    def test_legacy_unsourced_relation_is_not_presented_as_reviewed(self):
        a,_=self.fx.judgment(node='A03');b,_=self.fx.judgment(node='A01')
        dashboard.relation(self.store,'legacy',dict(from_judgment_id=a,to_judgment_id=b,kind='technical',reason='Legacy only',evidence_ids=[]))
        _,view=self.view([a,b])
        legacy=[e for e in view['node_relations'] if e.get('review_status')=='legacy_source_review_required']
        self.assertEqual(len(legacy),1);self.assertEqual(legacy[0]['kind'],'reference')

    def test_future_plan_cannot_be_stored_as_realized_event(self):
        _,j=self.fx.judgment(node='A03',nature='external_plan')
        with self.assertRaisesRegex(ValueError,'Realization events'):
            research.event(self.store,'fake-realization',dict(scope=j['scope'],event_type='realization',event_date='2026-09-01',
                description='A plan is not realized',evidence_ids=j['support_ids'],materiality='Test',review_reason='Test'))

    def test_easing_label_cannot_bypass_comparable_trend(self):
        _,j=self.fx.judgment(node='A03');j['bottleneck']['state']='easing'
        jid=research.judgment(self.store,'bad-easing',j)['id']
        with self.assertRaisesRegex(ValueError,'easing needs'):self.view([jid])

    def test_partial_checkpoint_preserves_other_questions_and_retry(self):
        v,_=self.investigated(verified=True);head=loop.checkpoint(self.store,'first',v)['id']
        before=copy.deepcopy(v['questions']);q=copy.deepcopy(before[0]);q['answer']='Changed only this answer'
        action=dict(campaign_id=self.cid,previous_id=head,questions=[q])
        result=loop.patch(self.store,'one-question',action)
        self.assertFalse(loop.patch(self.store,'one-question',action)['inserted'])
        after=loop.current(self.store,self.cid)[1]
        self.assertEqual(after['questions'][1:],before[1:])
        self.assertEqual(after['nodes'],v['nodes'])
        self.assertEqual(loop.question(self.store,self.cid,q['id'])['question'],q)
        with self.assertRaisesRegex(ValueError,'Conflicting'):loop.patch(self.store,'one-question',dict(action,questions=[]))

    def test_patch_rejects_stale_or_erased_attempts(self):
        v,_=self.investigated(verified=True);head=loop.checkpoint(self.store,'first',v)['id']
        q=copy.deepcopy(v['questions'][0]);q['attempts']=[]
        with self.assertRaises(ValueError):loop.patch(self.store,'erase-attempt',dict(campaign_id=self.cid,previous_id=head,questions=[q]))
        with self.assertRaisesRegex(ValueError,'Stale'):loop.patch(self.store,'stale',dict(campaign_id=self.cid,previous_id=self.cid,questions=[]))

    def test_patch_can_add_new_question_without_dumping_other_nodes(self):
        q=dict(id='new',node_id='A03',dimension='history',question='What changed?',status='open',attempts=[],next_action='Read prior source')
        head=loop.patch(self.store,'add-question',dict(campaign_id=self.cid,previous_id=self.cid,questions=[q]))['id']
        before=self.store.path.read_bytes();packet=loop.question(self.store,self.cid,'new')
        self.assertEqual(packet['checkpoint_id'],head);self.assertNotIn('nodes',packet)
        self.assertEqual(before,self.store.path.read_bytes())
        self.assertEqual(len(loop.current(self.store,self.cid)[1]['nodes']),87)


if __name__=='__main__':unittest.main()
