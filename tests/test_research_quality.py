import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest

import test_research_loop as fixtures
import research_loop as loop
from research_quality import inspect_questions, completion
from synthesis import make_report
from research_store import Store


class ResearchQualityTests(unittest.TestCase):
    setUp=fixtures.ResearchLoopTests.setUp
    investigated=fixtures.ResearchLoopTests.investigated
    checkpoint_input=fixtures.ResearchLoopTests.checkpoint_input

    def test_administrative_row_numbers_do_not_hide_repeated_conclusions(self):
        v,_=self.investigated(verified=True);qs=v['questions'][5:15]
        for i,q in enumerate(qs):
            q.update(answer=f'원장 행 {i:03}: 동일한 제품 공백 설명',closure_reason='동일 종결',
                     remaining_uncertainty='동일 미확인',why_more_search_unlikely='동일 이유')
        issues=inspect_questions(self.store,v['nodes'],qs)
        self.assertEqual(sum('repeated_conclusion_across_nodes' in x['reasons'] for x in issues),10)

    def test_shared_source_exception_rejects_node_label_only_explanation(self):
        v,_=self.investigated(verified=True);a,b=v['questions'][5],v['questions'][10]
        b['source_reviews']=copy.deepcopy(a['source_reviews'])
        for q in (a,b):
            q['semantic_review']['shared_source_review']=dict(node_specific_application=q['node_id']+' applicability',
                different_from_other_nodes=q['node_id']+' different scope',limitations='Same limits')
        issues=inspect_questions(self.store,v['nodes'],[a,b])
        self.assertEqual(sum('reused_source_packet_across_nodes' in x['reasons'] for x in issues),2)

    def test_background_population_and_index_cannot_close_product_gap(self):
        v,_=self.investigated(verified=True);q=v['questions'][5]
        for source in q['source_reviews']:source['application']['fit']='context'
        issues=inspect_questions(self.store,v['nodes'],[q])
        self.assertIn('gap_needs_target_specific_probe',issues[0]['reasons'])
        q['source_reviews'][0].update(role='direct')
        q['source_reviews'][0]['application']['document_kind']='index'
        self.assertIn('discovery_page_is_not_direct_evidence',inspect_questions(self.store,v['nodes'],[q])[0]['reasons'])

    def test_old_435_answer_template_no_longer_completes_research(self):
        v,j=self.investigated()
        loop.checkpoint(self.store,'paper-only',v)
        state=loop.resume(self.store,self.cid)
        self.assertEqual(len(state['quality_issues']),435)
        self.assertFalse(state['full_inventory_investigated'])
        self.assertFalse(state['ready_for_review'])
        self.assertEqual(loop.next_work(self.store,self.cid,2)['next_actions'][0]['action'],'review_question_sources')
        report=self.fx.action([j]);report.update(research_stage='baseline_review',campaign_id=self.cid,checkpoint_id=state['checkpoint_id'])
        with self.assertRaisesRegex(ValueError,'incomplete'):make_report(self.store,'bad-baseline',report)

    def test_missing_or_false_quote_background_and_unrelated_judgment_stay_open(self):
        v,_=self.investigated(verified=True);q=v['questions'][0]
        q['source_reviews'][0]['quote']='This was never in the document'
        issues=inspect_questions(self.store,v['nodes'],v['questions'])
        self.assertIn('invalid_source_review',issues[0]['reasons'])
        q['source_reviews'][0].update(quote='Demand exceeds usable supply.',role='background')
        self.assertIn('background_only_or_unread_sources',inspect_questions(self.store,v['nodes'],v['questions'])[0]['reasons'])
        q['source_reviews'][0].update(quote='Alternative supply is qualified.',location='block:2',role='direct')
        self.assertIn('resolution_not_linked_to_reviewed_support',inspect_questions(self.store,v['nodes'],v['questions'])[0]['reasons'])

    def test_source_document_ids_or_node_prefix_cannot_hide_reuse(self):
        v,_=self.investigated(verified=True);left,right=v['questions'][5],v['questions'][10]
        right['source_reviews']=copy.deepcopy(left['source_reviews'])
        right['answer']=right['node_id']+' '+left['answer']
        issues=inspect_questions(self.store,v['nodes'],v['questions'])
        row=next(p for p in issues if p['question_id']==right['id'])
        self.assertIn('reused_source_packet_across_nodes',row['reasons'])
        self.assertIn('repeated_conclusion_across_nodes',row['reasons'])

    def test_shared_document_with_different_source_locations_is_allowed(self):
        v,_=self.investigated(verified=True)
        self.assertEqual(v['questions'][5]['source_reviews'][0]['document_id'],v['questions'][10]['source_reviews'][0]['document_id'])
        self.assertEqual(inspect_questions(self.store,v['nodes'],v['questions']),[])

    def test_renaming_failed_routes_is_not_gap_research(self):
        v,_=self.investigated(verified=True);q=v['questions'][5]
        for a in q['attempts']:a['outcome']='failed'
        self.assertIn('access_failure_is_not_bounded_research',inspect_questions(self.store,v['nodes'],v['questions'])[0]['reasons'])

    def test_search_trace_requires_query_in_saved_tool_output(self):
        v,_=self.investigated(verified=True);q=v['questions'][5]
        q['source_reviews'][0].update(role='search_trace',query='invented query')
        self.assertIn('invalid_source_review',inspect_questions(self.store,v['nodes'],v['questions'])[0]['reasons'])

    def test_same_current_answer_cannot_fill_history_and_trend(self):
        v,_=self.investigated(verified=True)
        v['questions'][1]['answer']=v['questions'][0]['answer']
        issues=inspect_questions(self.store,v['nodes'],v['questions'])
        self.assertIn('repeated_review_across_dimensions',issues[0]['reasons'])

    def test_mirror_with_identical_bytes_is_not_another_gap_search(self):
        v,_=self.investigated(verified=True);q=v['questions'][5]
        original=self.store.document(q['source_reviews'][0]['document_id'])
        mirror=self.store.capture({'url':'https://example.com/mirror','producer':'Mirror'},original['raw'],original['mime'],{})['document_id']
        q['attempts'][1]['document_ids']=[mirror]
        q['source_reviews'][1]=dict(q['source_reviews'][0],document_id=mirror)
        self.assertIn('gap_needs_actual_alternative_search',inspect_questions(self.store,v['nodes'],v['questions'])[0]['reasons'])

    def test_malformed_review_cannot_crash_resume_or_close_a_question(self):
        v,_=self.investigated(verified=True)
        v['questions'][0]['source_reviews'][0]['relevance']=[]
        loop.checkpoint(self.store,'invalid-review',v)
        state=loop.resume(self.store,self.cid)
        self.assertFalse(state['ready_for_review'])
        self.assertIn('invalid_source_review',state['quality_issues'][0]['reasons'])

    def test_legacy_checkpoint_is_read_only_and_not_grandfathered(self):
        v,_=self.investigated()
        self.store.append('task','legacy-unverified',{'type':'research_checkpoint',**v},[self.cid])
        before=self.store.path.read_bytes()
        reopened=Store(self.store.folder,self.store.project_id)
        result=completion(reopened,self.cid)
        self.assertFalse(result['ready_to_submit'])
        self.assertEqual(before,self.store.path.read_bytes())

    def test_interim_file_cannot_complete_initial_request_and_cli_checks_it(self):
        report=self.fx.action([self.fx.judgment()[0]])
        rid=make_report(self.store,'interim',report)['id']
        result=completion(self.store,self.cid,rid)
        self.assertFalse(result['ready_to_submit'])
        self.assertIn('interim_does_not_fulfill_request',result['reasons'])
        path=self.store.folder/'completion-action.json'
        path.write_text(json.dumps(dict(op='research-completion',state_dir=str(self.store.folder),
            project_id=self.store.project_id,campaign_id=self.cid,report_id=rid)),encoding='utf-8')
        run=subprocess.run([sys.executable,'-X','utf8',str(Path(loop.__file__).parents[1]/'research_cli.py'),
                            '--action',str(path)],capture_output=True,text=True,encoding='utf-8')
        self.assertEqual(run.returncode,0,run.stderr)
        self.assertFalse(json.loads(run.stdout)['ready_to_submit'])

    def test_current_review_can_be_submitted_but_new_node_requires_more_work(self):
        v,j=self.investigated(verified=True);head=loop.checkpoint(self.store,'ready',v)['id']
        report=self.fx.action([j]);report.update(research_stage='baseline_review',campaign_id=self.cid,checkpoint_id=head)
        report['research_execution']={'status':'excluded_by_user','reason':'Synthetic explicit exclusion fixture'}
        rid=make_report(self.store,'review',report)['id']
        self.assertTrue(completion(self.store,self.cid,rid)['ready_to_submit'])
        loop.change_nodes(self.store,'add',dict(campaign_id=self.cid,previous_id=head,operation='add',source_ids=[],
            new_nodes=[dict(node_id='EXTRA',name='Additional scope',scope='Synthetic')],reason='Test',effective_date='2026-09-14'))
        self.assertFalse(completion(self.store,self.cid,rid)['ready_to_submit'])


if __name__=='__main__':unittest.main()
