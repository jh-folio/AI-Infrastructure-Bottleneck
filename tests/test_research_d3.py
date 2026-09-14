import importlib.util
import io
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

RUNTIME=Path(__file__).resolve().parents[1]/'plugin/runtime'
sys.path[:0]=[str(RUNTIME),str(RUNTIME/'core'),str(RUNTIME/'adapters')]
from research_store import Store,create,restore,digest
from research_sources import sec,prices,fetch
from extraction import fact_candidates,text_packet,filings
from scoring import calculate,WEIGHTS
import research


def scope():
    return dict(node_id='SYNTH-01',geography='Test',product_spec='Test',scenario='base',horizon='test-period',
                as_of_date='2026-01-01',protocol_version='3.1',methodology_version='3.1')


def factors(score=4):
    return {k:dict(status='EvidenceBounded',low=score,high=score,grade='A',evidence_ids=['e'],
                   reason_low='test anchor',reason_high='test anchor',mechanism='distinct mechanism') for k in WEIGHTS}


def inputs():
    return dict(methodology_version='3.1',factors=factors(),confidence='Medium',confidence_reason='reviewed',
                independent_producers=2,tier12_present=True,conflicts='resolved',scope_coherent=True,
                direction_evidence_ids=['e'],tier1_core_evidence_qualified=True)


class D3(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.folder=Path(self.temp.name)/'research'
        self.project=create(self.folder,{'name':'Synthetic','scope':'Test','as_of_date':'2026-01-01','ir_hosts':['example.com']})
        self.store=Store(self.folder,self.project['project_id'])

    def document(self,text=b'<p>Demand is strong.</p><p>Supply expanded but shortages persist.</p><p>Customers can substitute.</p>'):
        return self.store.capture({'url':'https://example.com/report','producer':'Synthetic issuer'},text,'text/html',{'published_at':'2025-12-01'})['document_id']

    def evidence(self,doc=None,family='issuer',request='ev',quote='Demand is strong.',location='block:1',**extra):
        doc=doc or self.document()
        value=dict(document_id=doc,location=location,quote=quote,claim=quote,scope=scope(),nature='observation',grade='A',
                   confidence='Medium',confidence_reason='reviewed',producer_family=family,source_tier=1,
                   decision='accepted',review_reason='test direct evidence')
        value.update(extra)
        return research.adopt(self.store,request,value)['id']

    def test_identity_append_reopen_backup_restore(self):
        doc=self.document();eid=self.evidence(doc)
        before=self.store.snapshot()
        with self.assertRaises(ValueError):Store(self.folder,'wrong')
        backup=Path(self.temp.name)/'backup';self.store.backup(backup)
        restored=Path(self.temp.name)/'restored';restore(backup,restored)
        self.assertEqual(Store(restored,self.project['project_id']).record(eid),self.store.record(eid))
        with self.assertRaises(FileExistsError):restore(backup,restored)
        self.assertEqual(before['records'],self.store.snapshot()['records'])

    def test_idempotent_and_conflicting_request(self):
        first=self.store.append('task','r',{'question':'one'})
        self.assertFalse(self.store.append('task','r',{'question':'one'})['inserted'])
        with self.assertRaises(ValueError):self.store.append('task','r',{'question':'two'})
        with self.assertRaises(ValueError):self.store.append('task','other',{},refs=['missing'])
        self.assertEqual(len(self.store.records()),1)

    def test_rejected_and_scope_mismatch_cannot_support_judgment(self):
        eid=self.evidence(decision='hold')
        value=dict(question='Q',scope=scope(),conclusion='C',support_ids=[eid],counter_ids=[],alternatives=['A'],
                   unknowns=['U'],next_actions=['N'],confidence='Low',reasoning='R',counter_search_limit='No independent counter source')
        with self.assertRaises(ValueError):research.judgment(self.store,'j',value)
        accepted=self.evidence(request='accepted');value['support_ids']=[accepted];value['scope']=dict(scope(),geography='other')
        with self.assertRaises(ValueError):research.judgment(self.store,'j',value)

    def test_quote_and_future_publication_refused(self):
        with self.assertRaises(ValueError):self.evidence(quote='invented')
        with self.assertRaises(ValueError):self.evidence(published_at='2027-01-01')

    def test_superseded_evidence_blocks_reuse(self):
        eid=self.evidence();doc=research.data(self.store,eid,'evidence')['document_id']
        self.evidence(doc,request='rev',decision='rejected',supersedes=eid)
        with self.assertRaises(ValueError):research.current_evidence(self.store,[eid],scope())

    def test_ir_context_and_bounded_packet(self):
        doc=self.store.document(self.document())
        packet=text_packet(doc,['strong'])
        self.assertIn('shortages persist',json.dumps(packet))
        self.assertEqual(packet['segments'][0]['location'],'block:1')

    def test_sec_facts_keep_ytd_vintages_and_units(self):
        raw={'cik':1,'facts':{'us-gaap':{'Revenue':{'label':'Revenue','description':'Test', 'units':{'USD':[
            {'val':10,'start':'2025-01-01','end':'2025-03-31','filed':'2025-04-01','accn':'a'},
            {'val':25,'start':'2025-01-01','end':'2025-06-30','filed':'2025-07-01','accn':'b'},
            {'val':27,'start':'2025-01-01','end':'2025-06-30','filed':'2026-02-01','accn':'c'}], 'EUR':[{'val':9,'filed':'2025-04-01'}]}}}}}
        docid=self.store.capture({'url':'https://data.sec.gov/facts','producer':'SEC'},json.dumps(raw).encode(),'application/json',{'adapter':'sec_companyfacts'})['document_id']
        rows=fact_candidates(self.store.document(docid),'us-gaap','Revenue','2026-01-01')
        self.assertEqual([r['value'] for r in rows],[10,25,9])
        self.assertEqual({r['unit'] for r in rows},{'USD','EUR'})
        self.assertEqual(rows[1]['start'],'2025-01-01')

    def test_failure_does_not_overwrite_document(self):
        doc=self.document();raw=self.store.document(doc)['raw']
        self.store.capture({'url':'https://example.com/report','producer':'Synthetic issuer'},None,'',{},'forbidden')
        self.assertEqual(self.store.document(doc)['raw'],raw)
        self.assertEqual(self.store.snapshot()['attempts'][-1]['status'],'forbidden')

    def test_report_snapshot_lineage_and_audit(self):
        doc=self.document();e=self.evidence(doc);c=self.evidence(doc,family='customer',request='counter',quote='Customers can substitute.',location='block:3')
        j=research.judgment(self.store,'j',dict(question='What limits deployment?',scope=scope(),conclusion='Conditional test conclusion',support_ids=[e],counter_ids=[c],alternatives=['Substitution'],unknowns=['Schedule'],next_actions=['Check float'],confidence='Low',reasoning='Demand and alternatives both matter'))['id']
        report=research.report(self.store,'report',[j])['id']
        text=research.data(self.store,report,'report')['markdown']
        self.assertIn('Customers can substitute',text);self.assertIn('https://example.com/report',text)
        self.assertEqual(research.audit(self.store)['issues'],[])
        snapshot=self.store.read_snapshot(research.data(self.store,report,'report')['snapshot_id'])
        self.assertNotIn(report,[r['id'] for r in snapshot['records']])

    def test_assessment_uses_adopted_evidence_and_reproducible_engine(self):
        e=self.evidence()
        doc=self.store.capture({'url':'https://example.com/customer','producer':'Synthetic customer'},b'<p>Demand is strong.</p>','text/html',{'published_at':'2025-12-01'})['document_id']
        c=self.evidence(doc,family='customer',request='c')
        value=inputs();value.update(scope=scope(),change_cause='initial',direction_evidence_ids=[e,c])
        for f in value['factors'].values():f['evidence_ids']=[e,c]
        result=research.assess(self.store,'a',value)['id']
        self.assertEqual(research.data(self.store,result,'assessment')['result']['tier_confirmed'],1)
        self.assertEqual(research.audit(self.store)['issues'],[])

    def test_cli_new_process_reads_existing_record(self):
        rid=self.store.append('task','r',{'question':'resume'})['id']
        action=Path(self.temp.name)/'read.json';action.write_text(json.dumps({'op':'record','state_dir':str(self.folder),'project_id':self.project['project_id'],'id':rid}),encoding='utf-8')
        result=subprocess.run([sys.executable,'-X','utf8',str(RUNTIME/'research_cli.py'),'--action',str(action)],capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertEqual(json.loads(result.stdout)['id'],rid)


    def test_registered_historical_engine_replay_after_default_changes(self):
        from scoring import replay
        eid=self.evidence();value=inputs();value.update(scope=scope(),change_cause='initial',direction_evidence_ids=[eid])
        for f in value['factors'].values():f['evidence_ids']=[eid]
        rid=research.assess(self.store,'history',value)['id'];v=research.data(self.store,rid)
        with patch('scoring.ENGINE','future-default'):
            self.assertEqual(replay(v['inputs'],v['result'],v['engine_artifacts']),v['result'])
        v['engine_artifacts']['engines/d3_1_0.py']['sha256']='bad'
        with self.assertRaises(ValueError):replay(v['inputs'],v['result'],v['engine_artifacts'])

    def test_one_source_cannot_manufacture_independent_producers(self):
        e=self.evidence();c=self.evidence(family='invented second family',request='fake-independent')
        value=inputs();value.update(scope=scope(),change_cause='initial',direction_evidence_ids=[e,c])
        for f in value['factors'].values():f['evidence_ids']=[e,c]
        rid=research.assess(self.store,'single-source',value)['id'];v=research.data(self.store,rid)
        self.assertEqual(v['inputs']['independent_producers'],1)
        self.assertEqual(v['result']['scoreability'],'Directionally Assessable')

    def test_long_block_can_resume_without_loop(self):
        doc=self.document(('<p>Demand '+('x'*5000)+'</p>').encode())
        packet=text_packet(self.store.document(doc),['demand'],100)
        self.assertIsNone(packet['next_offset']);self.assertEqual(packet['segments'][0]['continuation']['char_offset'],100)
        from research_cli import execute
        result=execute(dict(op='read-document',state_dir=str(self.folder),project_id=self.project['project_id'],document_id=doc,location='block:1',char_offset=100,max_chars=100))
        self.assertEqual(len(result['text']),100);self.assertEqual(result['next_char_offset'],200)

    def test_http_unchanged_and_429_preserve_bytes(self):
        from urllib.error import HTTPError
        class Response(io.BytesIO):
            headers={'Content-Type':'application/json'};status=200
            def geturl(self):return 'https://data.sec.gov/submissions/CIK0000000001.json'
        raw=b'{"cik":1,"filings":{"recent":{}}}'
        with patch.dict('os.environ',{'SEC_USER_AGENT':'synthetic-test'}):
            first=sec(self.store,1,'submissions',opener=lambda *a,**k:Response(raw))
            second=sec(self.store,1,'submissions',opener=lambda *a,**k:Response(raw))
            def blocked(*a,**k):raise HTTPError('https://data.sec.gov',429,'limited',{},None)
            failed=sec(self.store,1,'submissions',opener=blocked)
        self.assertEqual(first['status'],'success');self.assertEqual(second['status'],'unchanged')
        self.assertEqual(first['document_id'],second['document_id']);self.assertEqual(failed['status'],'rate_limited')
        self.assertEqual(self.store.document(first['document_id'])['raw'],raw)

    def test_invalid_json_response_not_saved(self):
        class Response(io.BytesIO):
            headers={'Content-Type':'application/json'};status=200
            def geturl(self):return 'https://data.sec.gov/submissions/CIK0000000001.json'
        with patch.dict('os.environ',{'SEC_USER_AGENT':'synthetic-test'}):
            result=sec(self.store,1,'submissions',opener=lambda *a,**k:Response(b'{"cik":1,"filings":{},"x":NaN}'))
        self.assertEqual(result['status'],'parse_failed');self.assertEqual(len(self.store.snapshot()['documents']),0)

    def test_unregistered_url_and_secret_query_rejected(self):
        from research_sources import public_url
        for url in ('https://evil.example/data','https://example.com/data?token=secret','http://example.com/a','https://user:pass@example.com/a'):
            with self.assertRaises(ValueError):public_url(url,{'example.com'},resolve=False)

    def test_yfinance_preserves_nulls_adjustment_and_partial_currency(self):
        class Timestamp:
            def isoformat(self):return '2025-12-01T00:00:00-05:00'
        class Frame:
            empty=False
            def iterrows(self):return iter([(Timestamp(),{'Close':10,'Adj Close':9,'Volume':float('nan')})])
        class Ticker:
            def history(self,**kwargs):
                assert kwargs['auto_adjust'] is False and kwargs['actions'] is True
                return Frame()
            def get_history_metadata(self):return {'exchangeTimezoneName':'America/New_York'}
        result=prices(self.store,'SYNTH','2025-12-01','2025-12-03',factory=lambda _:Ticker())
        self.assertEqual(result['status'],'partial')
        saved=json.loads(self.store.document(result['document_id'])['raw'])
        self.assertIsNone(saved['rows'][0]['Volume']);self.assertIsNone(saved['metadata']['currency'])

    def test_unknown_schema_and_corrupted_backup_refused(self):
        backup=Path(self.temp.name)/'backup';self.store.backup(backup)
        with (backup/'research.sqlite').open('ab') as f:f.write(b'corruption')
        with self.assertRaises(ValueError):restore(backup,Path(self.temp.name)/'restore')
        db=sqlite3.connect(self.folder/'research.sqlite')
        try:
            db.execute('UPDATE identity SET schema_version=99');db.commit()
        finally:db.close()
        with self.assertRaises(ValueError):Store(self.folder,self.project['project_id'])

    def test_transaction_rollback_does_not_leave_partial_write(self):
        before=self.store.snapshot()['records']
        with self.assertRaises(RuntimeError):
            with self.store.connection(True) as db:
                db.execute("INSERT INTO records VALUES ('bad','task','bad','{}','bad','now')")
                raise RuntimeError('simulate failed transaction')
        self.assertEqual(self.store.snapshot()['records'],before)

    def test_weekly_brief_event_citations(self):
        eid=self.evidence()
        rid=research.event(self.store,'event',dict(scope=scope(),event_type='actual',event_date='2025-12-01',description='Synthetic event',evidence_ids=[eid],materiality='test',review_reason='test'))['id']
        report=research.report(self.store,'weekly',[],mode='weekly_brief',event_ids=[rid])['id']
        md=research.data(self.store,report)['markdown']
        self.assertIn('Synthetic event',md);self.assertIn('https://example.com/report',md)


    def test_generated_assessment_retry_uses_same_request_snapshot(self):
        eid=self.evidence();value=inputs();value.update(scope=scope(),change_cause='initial',direction_evidence_ids=[eid])
        for f in value['factors'].values():f['evidence_ids']=[eid]
        first=research.assess(self.store,'retry-assess',value)
        second=research.assess(self.store,'retry-assess',value)
        self.assertEqual(first['id'],second['id']);self.assertFalse(second['inserted'])
        value['confidence_reason']='different review'
        with self.assertRaises(ValueError):research.assess(self.store,'retry-assess',value)

    def test_generated_report_retry_and_conflict(self):
        first=research.report(self.store,'retry-report',[])
        second=research.report(self.store,'retry-report',[])
        self.assertEqual(first['id'],second['id']);self.assertFalse(second['inserted'])
        with self.assertRaises(ValueError):research.report(self.store,'retry-report',[],title='Different')
        self.assertEqual(len(self.store.records('report')),1)

    def test_document_provenance_corruption_detected(self):
        doc=self.document()
        with self.store.connection(True) as db:db.execute("UPDATE documents SET url='https://example.com/wrong' WHERE id=?",(doc,))
        with self.assertRaises(ValueError):self.store.document(doc)
        with self.assertRaises(ValueError):self.store.snapshot()


class Arithmetic(unittest.TestCase):
    def test_all_four_is_80(self):
        r=calculate(inputs());self.assertEqual(r['overall'],{'low':80.,'high':80.,'mid':80.})
        self.assertEqual(r['tier_confirmed'],1)

    def test_criticality_gate(self):
        v=inputs();v['factors']['system_criticality'].update(low=2,high=2)
        for k in ('regulatory','concentration'):v['factors'][k].update(low=5,high=5)
        r=calculate(v);self.assertEqual(r['axes']['criticality']['low'],70.)
        self.assertNotIn(1,r['possible_tiers'])

    def test_unknown_not_midpoint_and_not_tier4(self):
        v=inputs();v['factors']={k:{'status':'Unknown','low':None,'high':None} for k in WEIGHTS};v['confidence']='Low';v['direction_evidence_ids']=[]
        r=calculate(v);self.assertEqual(r['overall'],{'low':0.,'high':100.,'mid':None})
        self.assertEqual(r['scoreability'],'Not Scorable');self.assertEqual(r['possible_tiers'],[])

    def test_na_no_weight_redistribution(self):
        v=inputs();v['factors']['build']={'status':'N/A','low':None,'high':None}
        r=calculate(v);self.assertIsNone(r['overall']['low']);self.assertEqual(r['axes']['severity']['low'],80)

    def test_invalid_bounds_rejected(self):
        for score in (True,float('nan'),6,-1):
            v=inputs();v['factors']['access']['low']=score
            with self.assertRaises(ValueError):calculate(v)


if __name__=='__main__':unittest.main()
