import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'plugin/runtime/core'), str(ROOT/'plugin/runtime/adapters')]
from research_store import Store, create, restore
import research
from synthesis import make_report


class SynthesisTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)/'state'
        p = create(self.path, {'name':'Synthetic supply chain', 'scope':'Synthetic only', 'as_of_date':'2026-09-14'})
        self.store = Store(self.path, p['project_id']); self.n = 0

    def judgment(self, node='SYNTH-A', asof='2026-09-14', region='Test region', comparison=None,
                 observed='2026-09-01', published='2026-09-02', nature='observation', bottleneck=True):
        self.n += 1
        scope = dict(node_id=node, geography=region, product_spec='Qualified test product', scenario='base',
                     horizon='2026', as_of_date=asof, protocol_version='3.1', methodology_version='3.1')
        doc = self.store.capture({'url':f'https://example.com/{self.n}', 'producer':'Synthetic issuer'},
                                b'<p>Demand exceeds usable supply.</p><p>Alternative supply is qualified.</p>',
                                'text/html', {'published_at':published})['document_id']
        ids=[]
        for i,quote in enumerate(['Demand exceeds usable supply.', 'Alternative supply is qualified.']):
            e=dict(document_id=doc,location=f'block:{i+1}',quote=quote,claim=quote,scope=scope,nature=nature,
                   grade='B',confidence='Low',confidence_reason='Synthetic evidence only',producer_family='synthetic',
                   source_tier=2,decision='accepted',review_reason='Synthetic scope reviewed',published_at=published)
            if observed:e['observed_at']=observed
            ids.append(research.adopt(self.store,f'e-{self.n}-{i}',e)['id'])
        data=dict(question='Where is the synthetic constraint?',scope=scope,
                  conclusion=f'{node}: Shortage within qualified test scope; alternatives may ease it.',
                  support_ids=[ids[0]],counter_ids=[ids[1]],alternatives=['Substitution may work'],
                  unknowns=['Actual schedule delay unconfirmed'],next_actions=['Check next qualified delivery and customer delay report'],
                  confidence='Low',reasoning='Compare demand with usable supply and alternatives.')
        if bottleneck:data['bottleneck']=dict(severity='Customers report a shortage; magnitude unknown',
                                             persistence=None,operational_impact='Schedule impact unconfirmed')
        if comparison:
            data['comparison']=dict(prior_judgment_id=comparison, direction='strengthening', change_cause='new_observation',
                                    reason='Reviewed later observation shows stronger constraint in this scope', evidence_ids=[ids[0]])
        return research.judgment(self.store,f'j-{self.n}',data)['id'],data

    def action(self, ids, previous=None):
        data={'title':'Synthetic supply-chain review', 'as_of_date':'2026-09-14', 'coverage':[
            {'segment':'Test compute', 'status':'reviewed' if ids else 'unreviewed','reason':'Selected test coverage','judgment_ids':ids},
            {'segment':'Test power','status':'missing','reason':'No reviewed evidence yet','judgment_ids':[]}]}
        data['research_execution'] = {'status':'not_run','reason':'Synthetic runtime test; no host research invoked.'}
        data['judgment_reviews'] = []
        for rid in ids:
            j = research.data(self.store, rid, 'judgment')
            data['judgment_reviews'].append(dict(judgment_id=rid, claim_level='constraint',
                demand_supply='Synthetic demand versus qualified supply reviewed.',
                operational_link='Actual schedule impact remains unknown.',
                comparison_basis='Fixed calendar 2026; earlier and later observations reviewed separately.',
                source_fit=[dict(evidence_id=eid, source_scope='Qualified test product in the stated test region',
                    applicability='direct', nature=research.data(self.store,eid)['nature'],
                    reason='Synthetic source explicitly describes this test scope.')
                    for eid in j['support_ids']+j['counter_ids']]))
        if previous:data['previous_report_id']=previous
        if len(ids)>1:
            data['synthesis_claims']=[{'text':'Constraints appear in the reviewed test scopes with alternatives.',
                'judgment_ids':ids,'comparison_scope':'reviewed_subset','reasoning':'Compare reviewed demand and usable supply, without a global ranking.',
                'limitations':['Different scopes are not a common global severity ranking.']}]
        return data

    def report(self, data, request='synthesis'):
        rid=make_report(self.store,request,data)['id']
        return rid,research.data(self.store,rid,'report')

    def test_full_report_keeps_scope_counterevidence_unknowns_and_coverage(self):
        a,_=self.judgment();b,_=self.judgment(node='SYNTH-B',region='Other region')
        _,r=self.report(self.action([a,b]));md=r['markdown']
        for expected in ['핵심 요약','공급망 위치별 비교','탐색 범위','다음 추적 항목','원문과 재조회 위치',
                         'Alternative supply is qualified','Actual schedule delay unconfirmed','Other region','Test power','근거 미확보']:
            self.assertIn(expected,md)
        self.assertIsNone(r['rows'][0]['persistence']);self.assertEqual(r['rows'][0]['trend']['direction'],'unknown')
        self.assertNotIn('tier_confirmed',md)
        self.assertEqual(len(r['rows']),2)

    def test_new_observation_and_previous_report_changes_are_linked(self):
        old,_=self.judgment(asof='2026-01-01',observed='2025-12-01',published='2025-12-02')
        oldaction=self.action([old]);oldaction['as_of_date']='2026-01-01'
        prev,_=self.report(oldaction,'before')
        new,_=self.judgment(comparison=old)
        _,r=self.report(self.action([new],prev),'after')
        self.assertEqual(r['rows'][0]['trend']['direction'],'strengthening')
        self.assertEqual(r['changes'][0]['previous_judgment_id'],old)
        self.assertIn('심화',r['changes'][0]['status'])

    def test_scope_mismatch_prevents_trend(self):
        old,_=self.judgment(asof='2026-01-01',observed='2025-12-01',published='2025-12-02')
        new,_=self.judgment(region='Different geography',comparison=old)
        _,r=self.report(self.action([new]));self.assertEqual(r['rows'][0]['trend']['direction'],'unknown')
        self.assertIn('범위',r['rows'][0]['trend']['reason'])

    def test_recovery_is_not_industry_change(self):
        old,_=self.judgment(asof='2026-01-01',observed='2025-12-01',published='2025-12-02')
        _,j=self.judgment(comparison=old)
        j['comparison']['change_cause']='data_recovery'
        rid=research.judgment(self.store,'recovery',j)['id']
        _,r=self.report(self.action([rid]));self.assertEqual(r['rows'][0]['trend']['direction'],'unknown')
        self.assertIn('자료 회복',r['markdown'])

    def test_forecast_or_missing_observation_cannot_prove_actual_trend(self):
        old,_=self.judgment(asof='2026-01-01',observed='2025-12-01',published='2025-12-02')
        for nature,observed in [('external_forecast','2026-09-01'),('observation',None)]:
            new,_=self.judgment(comparison=old,nature=nature,observed=observed)
            _,r=self.report(self.action([new]),nature)
            self.assertEqual(r['rows'][0]['trend']['direction'],'unknown')

    def test_same_day_is_not_two_point_trend(self):
        old,_=self.judgment();new,_=self.judgment(comparison=old)
        _,r=self.report(self.action([new]));self.assertEqual(r['rows'][0]['trend']['direction'],'unknown')

    def test_missing_fields_remain_unknown_without_guessing(self):
        j,_=self.judgment(bottleneck=False);_,r=self.report(self.action([j]))
        self.assertIsNone(r['rows'][0]['severity']);self.assertIsNone(r['rows'][0]['operational_impact'])
        self.assertIn('미확인',r['markdown'])

    def test_coverage_lie_and_duplicate_scopes_rejected(self):
        j,_=self.judgment();a=self.action([j]);a['coverage'][0]['status']='unreviewed'
        with self.assertRaises(ValueError):self.report(a)
        k,_=self.judgment()
        with self.assertRaises(ValueError):self.report(self.action([j,k]))

    def test_cross_scope_summary_requires_references_and_limits(self):
        a,_=self.judgment();b,_=self.judgment(node='SYNTH-B')
        data=self.action([a,b]);data['synthesis_claims']=[]
        with self.assertRaises(ValueError):self.report(data)
        data=self.action([a,b]);data['synthesis_claims'][0]['judgment_ids']=['missing']
        with self.assertRaises(ValueError):self.report(data)
        data=self.action([a,b]);data['synthesis_claims'][0]['limitations']=[]
        with self.assertRaises(ValueError):self.report(data)

    def test_no_reviewed_rows_is_explicit(self):
        _,r=self.report(self.action([]));self.assertEqual(r['rows'],[])
        self.assertIn('아직 검토된 판단이 없습니다',r['markdown'])

    def test_retry_same_snapshot_and_conflict(self):
        j,_=self.judgment();a=self.action([j]);rid,r=self.report(a)
        again=make_report(self.store,'synthesis',a);self.assertEqual(again['id'],rid);self.assertFalse(again['inserted'])
        a['title']='Changed title'
        with self.assertRaises(ValueError):make_report(self.store,'synthesis',a)
        self.assertEqual(len(self.store.records('report')),1)

    def test_removed_row_not_reported_as_eased(self):
        j,_=self.judgment();prev,_=self.report(self.action([j]),'first')
        _,r=self.report(self.action([],prev),'removed')
        self.assertIn('병목 해소를 뜻하지 않음',r['changes'][0]['status'])

    def test_new_scope_does_not_mean_new_bottleneck(self):
        j,_=self.judgment();prev,_=self.report(self.action([j]),'first')
        k,_=self.judgment(region='Other region');_,r=self.report(self.action([k],prev),'changed')
        self.assertEqual(r['changes'][0]['status'],'범위 변경')

    def test_superseded_evidence_cannot_be_current_row(self):
        j,v=self.judgment();eid=v['support_ids'][0];e=research.data(self.store,eid)
        e.update(supersedes=eid,decision='hold',review_reason='Correction')
        research.adopt(self.store,'hold',e)
        with self.assertRaises(ValueError):self.report(self.action([j]))

    def test_future_judgment_rejected(self):
        j,_=self.judgment(asof='2027-01-01')
        with self.assertRaises(ValueError):self.report(self.action([j]))

    def test_table_markup_escaped_and_unknown_highlight_rejected(self):
        _,v=self.judgment();v['bottleneck']['severity']='<script>x</script>| fake row\nnext'
        j=research.judgment(self.store,'markup',v)['id'];_,r=self.report(self.action([j]))
        self.assertNotIn('<script>',r['markdown']);self.assertIn('&#124;',r['markdown'])
        a=self.action([j]);a['highlight_ids']=['missing']
        with self.assertRaises(ValueError):self.report(a,'invalid')

    def test_export_new_process_and_backup_reopen_preserve_report(self):
        j,_=self.judgment();rid,r=self.report(self.action([j]))
        backup=Path(self.tmp.name)/'backup';self.store.backup(backup)
        restored=Path(self.tmp.name)/'restored';restore(backup,restored)
        a={'op':'export-report','state_dir':str(restored),'project_id':self.store.project_id,'id':rid,
           'destination':str(Path(self.tmp.name)/'report.md')}
        action=Path(self.tmp.name)/'action.json';action.write_text(json.dumps(a),encoding='utf-8')
        result=subprocess.run([sys.executable,'-X','utf8',str(ROOT/'plugin/runtime/research_cli.py'),'--action',str(action)],capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertEqual(Path(a['destination']).read_text(encoding='utf-8'),r['markdown'])
        self.assertEqual(research.audit(self.store)['issues'],[])

    def test_non_scorable_assessment_is_not_published_as_total(self):
        from test_research_d3 import inputs
        _,j=self.judgment()
        value=inputs();value.update(scope=j['scope'],change_cause='initial',direction_evidence_ids=j['support_ids'])
        for factor in value['factors'].values():factor.update(grade='B',evidence_ids=j['support_ids'])
        a=research.assess(self.store,'assessment',value)['id']
        j['assessment_id']=a
        current=research.judgment(self.store,'with-assessment',j)['id']
        _,r=self.report(self.action([current]));self.assertNotIn('근거한정 총점 범위:',r['markdown'])
        self.assertIn('Directionally Assessable',r['markdown'])
        j['scope']=dict(j['scope'],geography='Wrong')
        # Existing valid judgment with a wrong-scope assessment must be refused.
        bad=self.store.append('assessment','bad-scope',{'scope':j['scope']})['id']
        j['scope']['geography']='Test region';j['assessment_id']=bad
        current=research.judgment(self.store,'bad-link',j)['id']
        with self.assertRaises(ValueError):self.report(self.action([current]),'bad-report')

    def test_superseded_historical_evidence_retained_but_not_used_for_trend(self):
        old,j=self.judgment(asof='2026-01-01',observed='2025-12-01',published='2025-12-02')
        eid=j['support_ids'][0];e=research.data(self.store,eid)
        e.update(supersedes=eid,decision='hold',review_reason='Historical correction')
        research.adopt(self.store,'correct-history',e)
        new,_=self.judgment(comparison=old)
        _,r=self.report(self.action([new]))
        self.assertEqual(r['rows'][0]['trend']['direction'],'unknown')
        self.assertIn('이전 근거가 정정',r['markdown'])

    def test_missing_review_cannot_silently_publish(self):
        j,_=self.judgment(); a=self.action([j]); del a['judgment_reviews']
        with self.assertRaisesRegex(ValueError, 'judgment_reviews'): self.report(a)

    def test_missing_segments_block_global_comparison(self):
        j,_=self.judgment(); k,_=self.judgment(node='SYNTH-B');a=self.action([j,k])
        a['synthesis_claims'][0]['comparison_scope']='comprehensive'
        with self.assertRaisesRegex(ValueError, 'comprehensive comparison'): self.report(a)

    def test_generation_queue_cannot_establish_load_connection(self):
        j,_=self.judgment(node='C06'); a=self.action([j])
        review=a['judgment_reviews'][0]
        review['source_fit'][0].update(source_scope='Generation interconnection queue', applicability='context',
                                      reason='Does not measure large-load connection delays')
        with self.assertRaisesRegex(ValueError, 'Context sources alone'): self.report(a)

    def test_forecast_reclassification_requires_evidence_correction(self):
        j,_=self.judgment(); a=self.action([j])
        a['judgment_reviews'][0]['source_fit'][0]['nature']='external_forecast'
        with self.assertRaisesRegex(ValueError, 'correct evidence'): self.report(a)

    def test_planned_supply_cannot_prove_actual_operation(self):
        j,_=self.judgment(nature='external_plan'); a=self.action([j]); review=a['judgment_reviews'][0]
        review.update(claim_level='operational',operational_source_ids=[review['source_fit'][0]['evidence_id']])
        with self.assertRaisesRegex(ValueError, 'directly applicable observations'): self.report(a)

    def test_deep_research_completion_requires_stored_run_and_result(self):
        j,_=self.judgment();a=self.action([j]);a['research_execution'].update(status='completed',entrypoint='test-host',
            execution_document_id='missing-run',result_document_id='missing-result')
        with self.assertRaisesRegex(ValueError, 'stored execution'): self.report(a)
        docs=[]
        for name in ('run','result'):
            docs.append(self.store.capture({'url':'https://example.com/'+name,'producer':'Synthetic host'},
                ('Synthetic '+name).encode(),'text/plain',{})['document_id'])
        a['research_execution'].update(execution_document_id=docs[0],result_document_id=docs[1])
        _,r=self.report(a); self.assertEqual(r['research_execution']['status'],'completed')
        self.assertEqual(research.audit(self.store)['issues'],[])

    def test_internal_identifiers_only_in_appendix_and_unknown_execution_visible(self):
        j,data=self.judgment(); a=self.action([j]);a['research_execution']['status']='unknown'
        _,r=self.report(a);body,appendix=r['markdown'].split('## 부록: 검증과 재조회')
        for identifier in [j,*data['support_ids'],*data['counter_ids'],'SHA-256','snapshot:']:
            self.assertNotIn(identifier,body);self.assertIn(identifier,appendix)
        self.assertIn('실제 실행 여부를 확인할 자료가 없습니다',body)
        self.assertIn('[자료 1](#source-1)',body)
        self.assertIn(data['conclusion'],body.split('## 핵심 요약')[1].split('## 공급망 위치별 비교')[0])

    def test_legacy_report_remains_comparable(self):
        j,_=self.judgment();old,r=self.report(self.action([j]),'current')
        r['generation']='supply-chain-synthesis-1'
        legacy=self.store.append('report','legacy-synthesis',r)['id']
        _,r=self.report(self.action([j],legacy),'new')
        self.assertEqual(r['changes'][0]['previous_judgment_id'],j)

    def test_unrelated_previous_report_is_rejected(self):
        old=research.report(self.store,'legacy-report',[])['id']
        with self.assertRaises(ValueError):self.report(self.action([],old))


if __name__ == '__main__':
    unittest.main()
