import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import test_synthesis
import research
import monitoring
import dashboard
import research_handoff
from research_store import Store, restore, digest


class D45Tests(unittest.TestCase):
    def setUp(self):
        self.fixture=test_synthesis.SynthesisTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.store=self.fixture.store

    def plan(self):
        return monitoring.plan(self.store,'plan',{'name':'Synthetic','sources':[
            {'id':x,'op':'ir','url':'https://example.com/'+x,'producer':'Synthetic'} for x in ('a','b')]})['id']

    def fetch(self,store,source):
        return store.capture({'url':source['url'],'producer':source['producer']},b'Synthetic','text/plain',{})

    def test_run_repeat_does_not_recollect_or_change_judgments(self):
        plan=self.plan();v={'plan_id':plan,'period':'2026-09-14'}
        r=monitoring.run(self.store,'run',v,self.fetch)
        again=monitoring.run(self.store,'run',v,lambda *_:self.fail('recollected'))
        self.assertEqual(r['id'],again['id']);self.assertFalse(again['inserted'])
        self.assertEqual(research.data(self.store,r['id'])['changed_count'],2)
        self.assertEqual(self.store.records('judgment'),[])
        r=monitoring.run(self.store,'run-next',v,self.fetch)
        self.assertEqual(research.data(self.store,r['id'])['changed_count'],0)
        self.assertEqual(research.data(self.store,r['id'])['industry_change'],'not_assessed')

    def test_failure_is_not_unchanged(self):
        plan=self.plan()
        r=monitoring.run(self.store,'failed',{'plan_id':plan,'period':'2026-09-14'},lambda *_: {'status':'configuration_required'})
        v=research.data(self.store,r['id']);self.assertEqual(v['status'],'partial');self.assertEqual(v['failed_count'],2)
        self.assertIn('변화 없음을 확인할 수 없습니다',v['summary'])

    def test_return_to_older_document_is_still_a_source_change(self):
        plan=self.plan();v={'plan_id':plan,'period':'2026-09-14'}
        monitoring.run(self.store,'v1',v,self.fetch)
        def changed(store,source):return store.capture({'url':source['url'],'producer':source['producer']},b'New version','text/plain',{})
        monitoring.run(self.store,'v2',v,changed)
        rid=monitoring.run(self.store,'back-to-v1',v,self.fetch)['id']
        self.assertEqual(research.data(self.store,rid)['changed_count'],2)

    def test_interrupt_resumes_only_unfinished_step(self):
        plan=self.plan();v={'plan_id':plan,'period':'2026-09-14'}
        def crash(store,source):
            if source['id']=='b':raise KeyboardInterrupt()
            return self.fetch(store,source)
        with self.assertRaises(KeyboardInterrupt):monitoring.run(self.store,'resume',v,crash)
        seen=[]
        def resumed(store,source):seen.append(source['id']);return self.fetch(store,source)
        monitoring.run(self.store,'resume',v,resumed);self.assertEqual(seen,['b'])
        with self.assertRaises(ValueError):monitoring.run(self.store,'resume',dict(v,period='2026-09-15'),resumed)

    def test_concurrent_run_is_refused(self):
        plan=self.plan()
        with monitoring.exclusive(self.store):
            with self.assertRaises(ValueError):monitoring.run(self.store,'other',{'plan_id':plan,'period':'2026-09-14'},self.fetch)

    def test_process_crash_releases_lock_and_resumes_checkpoint(self):
        plan=self.plan();root=Path(__file__).resolve().parents[1]
        code='''import sys,os
sys.path.insert(0,sys.argv[1])
from research_store import Store
from monitoring import run
store=Store(sys.argv[2],sys.argv[3])
def collect(store,source):
    if source['id']=='b':os._exit(7)
    return store.capture({'url':source['url'],'producer':source['producer']},b'Synthetic','text/plain',{})
run(store,'killed',{'plan_id':sys.argv[4],'period':'2026-09-14'},collect)
'''
        result=subprocess.run([sys.executable,'-c',code,str(root/'plugin/runtime/core'),str(self.store.folder),self.store.project_id,plan],timeout=15)
        self.assertEqual(result.returncode,7);seen=[]
        def resumed(store,source):seen.append(source['id']);return self.fetch(store,source)
        monitoring.run(self.store,'killed',{'plan_id':plan,'period':'2026-09-14'},resumed)
        self.assertEqual(seen,['b'])

    def test_schedule_is_not_registered_by_packet(self):
        packet=monitoring.schedule_packet(self.store,self.plan())
        self.assertFalse(packet['registered']);self.assertEqual(packet['action_template']['project_id'],self.store.project_id)

    def report_with_relation(self,kind='technical'):
        a,ja=self.fixture.judgment();b,jb=self.fixture.judgment(node='SYNTH-B')
        relation=dashboard.relation(self.store,'relation',{'from_judgment_id':a,'to_judgment_id':b,'kind':kind,
            'reason':'Synthetic relation only','evidence_ids':ja['support_ids'] if kind!='technical' else []})['id']
        rid,r=self.fixture.report(self.fixture.action([a,b]))
        return rid,r,a,b

    def test_dashboard_uses_frozen_report_not_new_state_and_is_readonly(self):
        rid,r,a,b=self.report_with_relation();before=digest(self.store.path.read_bytes())
        view=dashboard.projection(self.store,rid)
        self.assertEqual(view['snapshot_id'],r['snapshot_id']);self.assertEqual(len(view['relations']),1)
        path=Path(self.fixture.tmp.name)/'dashboard.html';dashboard.export(self.store,rid,path)
        self.assertEqual(digest(self.store.path.read_bytes()),before)
        with self.assertRaises(FileExistsError):dashboard.export(self.store,rid,path)
        self.fixture.judgment(node='NEW-STATE')
        self.assertEqual(dashboard.projection(self.store,rid),view)

    def test_relation_future_or_nonobserved_input_refused(self):
        a,ja=self.fixture.judgment(nature='external_forecast');b,_=self.fixture.judgment(node='OTHER')
        with self.assertRaises(ValueError):dashboard.relation(self.store,'wrong',{'from_judgment_id':a,
            'to_judgment_id':b,'kind':'observed','reason':'Forecast is not observation','evidence_ids':ja['support_ids']})

    def test_dashboard_escapes_script_payload(self):
        a,j=self.fixture.judgment();j['conclusion']='</script><script>window.bad=true</script>'
        a=research.judgment(self.store,'injected',j)['id'];rid,_=self.fixture.report(self.fixture.action([a]))
        p=Path(self.fixture.tmp.name)/'escaped.html';dashboard.export(self.store,rid,p)
        html=p.read_text(encoding='utf-8');self.assertNotIn('</script><script>window.bad',html)
        self.assertIn('\\u003c/script',html)

    def test_handoff_requires_real_files_and_preserves_candidates(self):
        j,v=self.fixture.judgment();doc=research.data(self.store,v['support_ids'][0])['document_id']
        args={'purpose':'Synthetic deep research','record_ids':[j],'document_ids':[doc]}
        h=research_handoff.prepare(self.store,'handoff',args)['id']
        self.assertEqual(research.data(self.store,h)['status'],'prepared_not_executed')
        folder=Path(self.fixture.tmp.name);a=folder/'execution.txt';b=folder/'result.md'
        a.write_text('Synthetic host execution evidence');b.write_text('Synthetic returned research')
        v={'handoff_id':h,'entrypoint':'synthetic-test','execution_path':str(a),'result_path':str(b)}
        result=research_handoff.receive(self.store,'return',v)
        self.assertFalse(research_handoff.receive(self.store,'return',v)['inserted'])
        self.assertEqual(research.data(self.store,result['id'])['review_status'],'candidate_requires_review')
        self.assertEqual(len(self.store.records('judgment')),1)
        b.write_text('changed result')
        with self.assertRaises(ValueError):research_handoff.receive(self.store,'return',v)

    def test_backup_reopen_and_cli_dashboard(self):
        rid,r,*_=self.report_with_relation();folder=Path(self.fixture.tmp.name)
        self.store.backup(folder/'backup');restore(folder/'backup',folder/'restored')
        output=folder/'restored.html';action=folder/'action.json'
        action.write_text(json.dumps({'op':'export-dashboard','state_dir':str(folder/'restored'),
            'project_id':self.store.project_id,'report_id':rid,'destination':str(output)}),encoding='utf-8')
        cli=Path(__file__).resolve().parents[1]/'plugin/runtime/research_cli.py'
        done=subprocess.run([sys.executable,'-X','utf8',str(cli),'--action',str(action)],capture_output=True,text=True)
        self.assertEqual(done.returncode,0,done.stdout+done.stderr);self.assertTrue(output.exists())


if __name__=='__main__':unittest.main()
