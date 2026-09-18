"""Scope preservation, bounded transport, replay and measured output regressions."""
import copy
import json
import sys
import unittest
from pathlib import Path
import test_source_work as fixtures
import research_loop as loop
import research_scope as scope
import research_efficiency as efficiency
import research_coordination as coord
import source_work
from research_store import Store, dumps


class EfficiencyTests(unittest.TestCase):
    setUp=fixtures.SourceWorkTests.setUp
    question=fixtures.SourceWorkTests.question
    plan=fixtures.SourceWorkTests.plan

    def test_default_scope_keeps_inventory_and_required_investigation(self):
        value=loop.resume(self.store,self.cid)
        self.assertEqual(len(value['nodes']),88)
        self.assertEqual(len(value['scope_profile']['included_node_ids']),78)
        self.assertEqual(len(value['pending']),78)
        self.assertTrue({'E07','E09','E13'}<=set(value['scope_profile']['included_node_ids']))
        self.assertFalse(value['ready_for_review'])
        self.assertFalse(scope.CONTEXT_IDS & {p['node_id'] for p in value['pending']})

    def test_old_unversioned_campaign_stays_full(self):
        root=copy.deepcopy(loop.current(self.store,self.cid)[1]);root.pop('scope_profile');root.pop('catalog_version');root['nodes']=[n for n in root['nodes'] if n['node_id']!='F01']
        old=self.store.append('task','legacy',root)['id']
        self.assertEqual(len(loop.resume(self.store,old)['pending']),87)

    def test_explicit_scope_change_preserves_questions_and_replays(self):
        self.question()
        head,before=loop.current(self.store,self.cid)
        value=dict(campaign_id=self.cid,previous_id=head,profile=scope.LEGACY,
                   reason='Explicit scope expansion',effective_date='2026-01-01')
        result=loop.change_scope(self.store,'expand',value)
        self.assertFalse(loop.change_scope(self.store,'expand',value)['inserted'])
        self.assertEqual(loop.current(self.store,self.cid)[1]['questions'],before['questions'])
        self.assertEqual(len(loop.resume(self.store,self.cid)['scope_profile']['included_node_ids']),88)
        with self.assertRaises(ValueError):loop.change_scope(self.store,'stale',value)
        self.assertEqual(loop.current(Store(self.store.folder,self.store.project_id),self.cid)[0],result['id'])

    def test_dynamic_nodes_are_not_silently_excluded(self):
        head,_=loop.current(self.store,self.cid)
        loop.change_nodes(self.store,'split-context',dict(campaign_id=self.cid,previous_id=head,
            operation='split',source_ids=['E01'],new_nodes=[dict(node_id='permit-a',name='Scope A',scope='a'),
            dict(node_id='permit-b',name='Scope B',scope='b')],reason='Separate scopes',effective_date='2026-01-01'))
        after=loop.resume(self.store,self.cid)
        self.assertTrue({'permit-a','permit-b'}<=set(after['scope_profile']['included_node_ids']))
        self.assertEqual(len(after['scope_profile']['context_node_ids']),9)

    def test_context_risk_attached_to_included_question_remains_open(self):
        q=self.question('C01');head,_=loop.current(self.store,self.cid)
        loop.update_question(self.store,'permit-risk',dict(campaign_id=self.cid,previous_id=head,question_id=q['id'],
            set={'next_action':'Read permit decision to distinguish supply shortage from approval delay'}))
        pending=loop.resume(self.store,self.cid)['pending']
        self.assertTrue(any(p.get('question_id')==q['id'] for p in pending))

    def test_compact_resume_pages_do_not_lose_actions(self):
        full=loop.resume(self.store,self.cid);offset=0;rows=[]
        while offset is not None:
            view=efficiency.resume_view(self.store,self.cid,offset,7)
            self.assertNotIn('questions',view);rows+=view['pending']['items'];offset=view['pending']['next_offset']
        self.assertEqual(rows,full['pending'])
        self.assertLess(len(dumps(efficiency.resume_view(self.store,self.cid))),len(dumps(full))*.5)
        self.question()
        with self.assertRaises(ValueError):
            efficiency.resume_view(self.store,self.cid,7,7,checkpoint_id=full['checkpoint_id'])

    def test_delta_update_preserves_history_and_rejects_identity_change(self):
        q=self.question();head,_=loop.current(self.store,self.cid)
        attempt=dict(route='Synthetic official archive',outcome='unavailable',finding='Not accessible',document_ids=[])
        value=dict(campaign_id=self.cid,previous_id=head,question_id=q['id'],attempts_add=[attempt],
                   set={'next_action':'Try another official route'})
        loop.update_question(self.store,'delta',value)
        self.assertFalse(loop.update_question(self.store,'delta',value)['inserted'])
        self.assertEqual(loop.question(self.store,self.cid,q['id'])['question']['attempts'],[attempt])
        with self.assertRaises(ValueError):
            loop.update_question(self.store,'bad',dict(value,previous_id=loop.current(self.store,self.cid)[0],set={'node_id':'C01'}))

    def test_known_segment_does_not_drop_counter_cursor_or_change_original(self):
        doc=self.store.capture({'url':'https://example.com/segments','producer':'Synthetic issuer'},
                              self.raw,'text/html',{})['document_id']
        original=self.store.document(doc)['sha256']
        first=source_work.context(self.store,doc,['Demand'],['Alternative'],400)
        ids=[s['segment_id'] for lane in first['lanes'].values() for s in lane['segments']]
        repeated=source_work.context(self.store,doc,['Demand'],['Alternative'],400,known_segments=ids)
        for name,lane in repeated['lanes'].items():
            self.assertEqual(lane['next_cursor'],first['lanes'][name]['next_cursor'])
            self.assertTrue(all('text' not in s and 'text_omitted' in s for s in lane['segments']))
        self.assertEqual(source_work.context(self.store,doc,['Demand'],['Alternative'],400),first)
        self.assertEqual(self.store.document(doc)['sha256'],original)

    def test_metrics_never_store_source_or_contact(self):
        secret='private@example.invalid'
        efficiency.record_metric(self.store,{'op':'read-document','secret':secret},{'text':secret})
        efficiency.record_metric(self.store,{'op':'read-document','secret':secret},{'text':secret})
        raw=(self.store.folder/'usage_metrics.jsonl').read_text()
        self.assertNotIn(secret,raw)
        summary=efficiency.usage_summary(self.store)
        self.assertIsNone(summary['actual_host_tokens'])
        self.assertEqual(summary['repeated_response_count'],1)

    def test_batch_partial_failure_and_replay(self):
        plan_value={'campaign_id':self.cid,'source':{'url':'https://example.com/batch','producer':'Synthetic',
                    'kind':'public_document'},'bindings':[{'node_id':'A01','dimensions':['history'],'purpose':'Actual chronology'}]}
        bundle={'items':[{'key':'plan','op':'source-plan','data':plan_value},
                         {'key':'bad','op':'adopt','data':{}}]}
        first=efficiency.batch(self.store,'bundle',bundle)
        self.assertEqual(first['status'],'partial');self.assertEqual(first['failed_key'],'bad')
        second=efficiency.batch(self.store,'bundle',bundle)
        self.assertEqual(first['ids'],second['ids']);self.assertFalse(second['receipts'][0]['inserted'])
        with self.assertRaises(ValueError):efficiency.batch(self.store,'unsupported',{'items':[{'key':'x','op':'backup','data':{}}]})

    def test_export_is_exclusive_and_does_not_dump_state(self):
        path=self.store.folder/'full-state.json'
        result=efficiency.export_state(self.store,self.cid,path)
        self.assertNotIn('nodes',result)
        self.assertEqual(len(json.loads(path.read_text())['nodes']),88)
        with self.assertRaises(FileExistsError):efficiency.export_state(self.store,self.cid,path)

    def test_cli_default_is_compact_and_full_is_explicit(self):
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'plugin/runtime'))
        from research_cli import execute
        action=dict(op='research-resume',state_dir=str(self.store.folder),project_id=self.store.project_id,campaign_id=self.cid)
        self.assertEqual(execute(action)['view'],'compact-v1')
        self.assertIn('questions',execute(dict(action,view='full')))

    def test_coordination_scope_and_packet(self):
        coord.execute(self.store,'configure','config',dict(campaign_id=self.cid,parallel_supported=True,
            automatic_resume_requested=False,concurrency=2,lease_minutes=30,max_runs=5,max_failures=5))
        value=coord.status(self.store,self.cid)
        self.assertEqual(value['domains'][-1]['node_ids'],['E07','E09','E13'])
        q=self.question()
        job=coord.execute(self.store,'claim','job',dict(campaign_id=self.cid,domain_id='semiconductors',
             worker_id='worker',node_ids=['A01']))['id']
        compact=efficiency.packet_view(self.store,self.cid,job)
        self.assertEqual(compact['questions']['items'][0]['id'],q['id'])
        self.assertNotIn('attempts',compact['questions']['items'][0])
        with self.assertRaises(ValueError):
            loop.change_scope(self.store,'change-active',dict(campaign_id=self.cid,previous_id=loop.current(self.store,self.cid)[0],
               profile=scope.LEGACY,reason='Cannot change active work',effective_date='2026-01-01'))

    def test_scope_survives_checkpoint(self):
        self.question()
        self.assertEqual(loop.resume(self.store,self.cid)['scope_profile']['version'],scope.DEFAULT)

    def test_model_suppliers_are_one_required_node_and_one_domain(self):
        state=loop.resume(self.store,self.cid)
        model=[n for n in state['nodes'] if n['node_id']=='F01']
        self.assertEqual(len(model),1)
        self.assertIn('models',model[0]['scope'])
        group=next(g for g in coord.status(self.store,self.cid)['domains'] if g['domain_id']=='model_supply')
        self.assertEqual(group['node_ids'],['F01'])
        model[0].update(disposition='investigated',reason='Synthetic investigation started')
        loop.patch(self.store,'model-screen',dict(campaign_id=self.cid,previous_id=state['checkpoint_id'],nodes=model))
        pending=[p for p in loop.resume(self.store,self.cid)['pending'] if p['node_id']=='F01']
        self.assertEqual({p['dimension'] for p in pending},set(loop.DIMENSIONS))

    def test_model_extension_does_not_modify_original_catalog(self):
        from research_catalog import load,BASE_VERSION
        base=load(BASE_VERSION);latest=load()
        self.assertEqual(latest['nodes'][:87],base['nodes'])
        self.assertEqual(len(latest['nodes']),88)
        self.assertEqual(latest['nodes'][-1]['Node_ID'],'F01')
        from supply_view import freeze_catalog
        frozen=freeze_catalog(self.store,{'campaign_id':self.cid,'as_of_date':'2026-01-01'},[])
        edges=[e for e in frozen['reference_edges'] if e['to_node_id']=='F01']
        self.assertEqual({e['from_node_id'] for e in edges},{'A01','B02'})
        self.assertTrue(all(e['kind']=='reference' and not e['evidence_ids'] for e in edges))

    def test_new_campaign_adds_extension_after_legacy_catalog_change(self):
        legacy=loop.start(self.store,'legacy-start',dict(objective='Historical catalog',as_of_date='2026-01-01',
            catalog_version='legacy-id-map-1.0'))['id']
        head=loop.change_nodes(self.store,'legacy-add',dict(campaign_id=legacy,previous_id=legacy,
            operation='add',source_ids=[],new_nodes=[dict(node_id='NEW',name='New scope',scope='Synthetic')],
            reason='Synthetic addition',effective_date='2026-01-01'))['id']
        new=loop.start(self.store,'new-campaign',dict(objective='Latest catalog',as_of_date='2026-01-01'))['id']
        self.assertNotIn('F01',{n['node_id'] for n in loop.current(self.store,legacy)[1]['nodes']})
        self.assertTrue({'F01','NEW'}<={n['node_id'] for n in loop.current(self.store,new)[1]['nodes']})
        self.assertEqual(loop.current(self.store,legacy)[0],head)

    def test_batch_document_reference_and_changed_bytes_rejected(self):
        path=self.store.folder/'source.txt';path.write_text('Synthetic supply observation.',encoding='utf-8')
        plan=self.plan()
        value={'items':[{'key':'original','op':'source-import','data':dict(plan_id=plan,path=str(path),
            mime='text/plain',capture_kind='extracted_text',acquisition_note='Synthetic original text fixture')} ]}
        first=efficiency.batch(self.store,'capture-batch',value)
        self.assertEqual(first['status'],'complete')
        self.assertIn('original.document_id',first['ids'])
        again=efficiency.batch(self.store,'capture-batch',value)
        self.assertFalse(again['receipts'][0]['inserted'])
        path.write_text('Changed input bytes.',encoding='utf-8')
        self.assertEqual(efficiency.batch(self.store,'capture-batch',value)['status'],'partial')

    def test_scope_projection_keeps_all_definitions_but_filters_default_map(self):
        from supply_view import freeze_catalog,expand
        frozen=freeze_catalog(self.store,{'campaign_id':self.cid,'as_of_date':'2026-01-01'},[])
        self.assertEqual(len(frozen['nodes']),88)
        report={'map_catalog':frozen,'as_of_date':'2026-01-01'}
        nodes,edges,_=expand(report,[],{}, {}, [])
        ids={n['node_id'] for n in nodes}
        self.assertEqual(len(nodes),78)
        self.assertTrue(all(e['from_node_id'] in ids and e['to_node_id'] in ids for e in edges))
        head,_=loop.current(self.store,self.cid)
        loop.change_scope(self.store,'expand-scope',dict(campaign_id=self.cid,previous_id=head,
            profile=scope.LEGACY,reason='Explicit full scope',effective_date='2026-01-01'))
        self.assertEqual(len(expand(report,[],{}, {}, [])[0]),78)
        full=freeze_catalog(self.store,{'campaign_id':self.cid,'as_of_date':'2026-01-01'},[])
        self.assertEqual(len(expand({'map_catalog':full,'as_of_date':'2026-01-01'},[],{}, {}, [])[0]),88)


if __name__=='__main__':unittest.main()
