"""Source routing, bounded context and explicit adoption regressions."""
import copy
import io
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

import test_research_d3 as fixtures
import research
import research_loop as loop
import source_work as flow
from extraction import locate
from research_store import Store


class Response(io.BytesIO):
    def __init__(self, url, raw, mime='text/html'):
        super().__init__(raw)
        self.url, self.status, self.headers = url, 200, {'Content-Type': mime}

    def geturl(self):
        return self.url


class SourceWorkTests(unittest.TestCase):
    def setUp(self):
        self.fx = fixtures.D3()
        self.fx.setUp()
        self.addCleanup(self.fx.doCleanups)
        self.store = self.fx.store
        self.cid = loop.start(self.store, 'start', {'objective': 'Synthetic research', 'as_of_date': '2026-01-01'})['id']
        self.state = loop.resume(self.store, self.cid)
        self.raw = b'<p>Demand exceeds qualified HBM supply.</p><p>Capacity targets are future plans.</p><p>Alternative suppliers passed qualification.</p>'

    def plan(self, request='route', nodes=('A01',), **changes):
        source = {'url': 'https://example.com/report', 'producer': 'Synthetic issuer',
                  'kind': 'public_document', 'published_at': '2025-12-01'}
        source.update(changes)
        return flow.source_plan(self.store, request, {'campaign_id': self.cid, 'source': source,
            'bindings': [{'node_id': n, 'dimensions': ['demand_supply', 'alternatives'],
                          'purpose': 'Inspect product-specific supply and customer qualification'} for n in nodes]})['id']

    def question(self, node='A01'):
        state = loop.resume(self.store, self.cid)
        for n in state['nodes']:
            n.update(disposition='investigated', reason='Synthetic queue exercise')
        q = {'id': node + '-supply', 'node_id': node, 'dimension': 'demand_supply',
             'question': 'Does qualified supply satisfy customer demand?', 'status': 'open',
             'attempts': [], 'next_action': 'Read original supply and alternative qualification statements'}
        loop.checkpoint(self.store, 'question-' + node, {'campaign_id': self.cid,
            'previous_id': state['checkpoint_id'], 'nodes': state['nodes'], 'questions': state['questions'] + [q]})
        return q

    def acquire(self, pid, request='acquire', raw=None, mime='text/html'):
        def opener(req, **kw):
            return Response(req.full_url, self.raw if raw is None else raw, mime)
        return flow.acquire(self.store, request, {'plan_id': pid}, opener)

    def test_fetch_cache_refresh_and_conflicting_requests(self):
        pid = self.plan()
        first = self.acquire(pid)
        self.assertEqual(first['status'], 'success')
        self.assertEqual(flow.acquire(self.store, 'acquire', {'plan_id': pid})['document_id'], first['document_id'])
        with patch('research_sources.fetch', side_effect=AssertionError('Unexpected network')):
            cached = flow.acquire(self.store, 'cache', {'plan_id': pid})
            self.assertEqual(cached['status'], 'cached')
            self.assertFalse(cached['network_performed'])
        with self.assertRaisesRegex(ValueError, 'Conflicting'):
            flow.acquire(self.store, 'acquire', {'plan_id': pid, 'refresh': True})
        refreshed = flow.acquire(self.store, 'refresh', {'plan_id': pid, 'refresh': True},
            lambda req, **kw: Response(req.full_url, self.raw + b'<p>Revision</p>'))
        self.assertNotEqual(refreshed['document_id'], first['document_id'])
        self.assertEqual(self.store.document(first['document_id'])['raw'], self.raw)

    def test_one_source_maps_to_two_nodes_without_creating_judgments(self):
        pid = self.plan(nodes=('A01', 'A02'))
        result = self.acquire(pid)
        q1 = self.question('A01')
        q2 = self.question('A02')
        for q in (q1, q2):
            packet = flow.question_packet(self.store, self.cid, q['id'], ['HBM'], ['alternative'])
            self.assertEqual(packet['sources'][0]['document_id'], result['document_id'])
            self.assertTrue(packet['sources'][0]['lanes']['counter']['segments'])
            self.assertEqual(packet['status'], 'open')
        self.assertFalse(self.store.records('judgment'))
        self.assertFalse(self.store.records('evidence'))
        state = loop.resume(self.store, self.cid)
        action = next(a for a in flow.next_details(self.store, self.cid, state, state['pending']) if a.get('question_id') == q1['id'])
        self.assertEqual(action['source_plan_ids'], [pid])
        self.assertEqual(action['packet_action']['op'], 'question-packet')

    def test_context_pages_do_not_lose_long_source_tail_or_counter_lane(self):
        text = 'Demand ' + ('x' * 1400) + '\nBridge\nAlternative supply qualified.'
        did = self.store.capture({'url': 'https://example.com/long', 'producer': 'Synthetic'}, text.encode(), 'text/plain', {})['document_id']
        first = flow.context(self.store, did, ['demand'], ['alternative'], 400)
        self.assertIn('Alternative', ''.join(s['text'] for s in first['lanes']['counter']['segments']))
        parts = [s['text'] for s in first['lanes']['focus']['segments'] if s['location'] == 'block:1']
        cursor = first['lanes']['focus']['next_cursor']
        while cursor:
            page = flow.context(self.store, did, ['demand'], ['alternative'], 400, {'focus': cursor})
            parts.extend(s['text'] for s in page['lanes']['focus']['segments'] if s['location'] == 'block:1')
            cursor = page['lanes']['focus']['next_cursor']
        self.assertEqual(''.join(parts), locate(self.store.document(did), 'block:1'))

    def test_failed_route_is_visible_and_does_not_close_question(self):
        pid = self.plan()
        def blocked(req, **kw):
            raise HTTPError(req.full_url, 403, 'Forbidden', {}, None)
        result = flow.acquire(self.store, 'failed', {'plan_id': pid}, blocked)
        self.assertEqual(result['status'], 'forbidden')
        q = self.question()
        packet = flow.question_packet(self.store, self.cid, q['id'], ['supply'], ['alternative'])
        self.assertEqual(packet['routes'][0]['latest_result']['status'], 'forbidden')
        self.assertEqual(packet['total_documents'], 0)
        self.assertEqual(packet['status'], 'open')

    def test_host_import_trace_cannot_be_adopted_and_import_is_idempotent(self):
        pid = self.plan()
        path = self.store.folder / 'host.txt'
        path.write_text('Demand is strong.', encoding='utf-8')
        value = {'plan_id': pid, 'path': str(path), 'mime': 'text/plain',
                 'capture_kind': 'search_trace', 'acquisition_note': 'Synthetic tool response, not original text'}
        result = flow.import_source(self.store, 'import', value)
        self.assertFalse(flow.import_source(self.store, 'import', value)['inserted'])
        with self.assertRaisesRegex(ValueError, 'discovery'):
            self.fx.evidence(doc=result['document_id'])
        self.assertEqual(flow.context(self.store, result['document_id'], ['Demand'], ['alternative'])['capture_kind'], 'search_trace')
        path.write_text('Different source contents', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'Conflicting'):
            flow.import_source(self.store, 'import', value)

    def test_imported_original_connects_to_existing_adoption_and_judgment(self):
        pid = self.plan()
        path = self.store.folder / 'original.html'
        path.write_bytes(b'<p>Demand is strong.</p>')
        result = flow.import_source(self.store, 'original', {'plan_id': pid, 'path': str(path),
            'mime': 'text/html', 'capture_kind': 'original_bytes', 'acquisition_note': 'Synthetic raw document'})
        s = fixtures.scope()
        s['node_id'] = 'A01'
        eid = self.fx.evidence(doc=result['document_id'], scope=s)
        out = research.judgment(self.store, 'judgment', dict(question='Demand?', scope=s, conclusion='Demand is strong; shortage unproven',
            support_ids=[eid], counter_ids=[], alternatives=['Customer qualification could differ'], unknowns=['Usable supply'],
            next_actions=['Read qualification data'], confidence='Low', reasoning='The source reports demand, not actual shortage',
            counter_search_limit='Synthetic case does not contain a counter observation'))
        self.assertEqual(research.data(self.store, out['id'])['support_ids'], [eid])

    def test_csv_location_and_json_pointer_handoff(self):
        pid = self.plan(url='https://example.com/data.csv')
        doc = self.acquire(pid, raw=b'product,lead_time,unit\nHBM,10,weeks\nAlternative,6,weeks', mime='text/csv')['document_id']
        packet = flow.context(self.store, doc, ['HBM'], ['Alternative'])
        self.assertIn('lead_time: 10', locate(self.store.document(doc), 'row:2'))
        self.assertEqual(packet['lanes']['focus']['segments'][0]['location'], 'row:1')
        jsonplan = self.plan(request='json-plan', url='https://example.com/data.json')
        jsondoc = self.acquire(jsonplan, request='json-acquire', raw=b'{"supply":10}', mime='application/json')['document_id']
        self.assertTrue(flow.context(self.store, jsondoc, ['supply'], ['alternative'])['structured_read_required'])
        self.assertEqual(locate(self.store.document(jsondoc), '/supply'), '10')

    def test_invalid_plan_scope_date_url_and_source_identity(self):
        for changes in ({'url': 'http://example.com/report'}, {'url': 'https://user:password@example.com/a'},
                        {'published_at': '2027-01-01'}):
            with self.assertRaises(ValueError):
                self.plan(**changes)
        with self.assertRaises(ValueError):
            self.plan(nodes=('UNKNOWN',))
        did = self.fx.document()
        value = {'campaign_id': self.cid, 'document_id': did, 'source': {'url': 'https://example.com/other',
                 'producer': 'Synthetic issuer', 'kind': 'public_document'},
                 'bindings': [{'node_id': 'A01', 'dimensions': ['history'], 'purpose': 'Compare prior plan'}]}
        with self.assertRaisesRegex(ValueError, 'does not match'):
            flow.source_plan(self.store, 'bad-link', value)

    def test_public_route_still_rejects_private_network_when_fetching(self):
        pid = self.plan(url='https://internal.example/report')
        with patch('research_sources.socket.getaddrinfo', return_value=[(0, 0, 0, '', ('127.0.0.1', 443))]):
            result = flow.acquire(self.store, 'private', {'plan_id': pid})
        self.assertEqual(result['status'], 'parse_failed')
        self.assertIsNone(result['document_id'])
        self.assertFalse(result['network_performed'])

    def test_acquisition_failure_after_success_preserves_context_and_failure(self):
        pid = self.plan()
        success = self.acquire(pid)
        q = self.question()
        def fail(req, **kw):
            raise HTTPError(req.full_url, 429, 'Rate limited', {}, None)
        flow.acquire(self.store, 'rate-limit', {'plan_id':pid, 'refresh':True}, fail)
        packet = flow.question_packet(self.store,self.cid,q['id'],['HBM'],['alternative'])
        self.assertEqual(packet['routes'][0]['latest_result']['status'],'rate_limited')
        self.assertEqual(packet['sources'][0]['document_id'],success['document_id'])
        self.assertEqual(packet['status'],'open')
        flow.acquire(self.store,'cached-after-failure',{'plan_id':pid})
        packet = flow.question_packet(self.store,self.cid,q['id'],['HBM'],['alternative'])
        self.assertEqual(packet['routes'][0]['latest_result']['status'],'cached')
        self.assertEqual(packet['routes'][0]['latest_network_result']['status'],'rate_limited')
        self.assertEqual(packet['routes'][0]['latest_network_result']['detail']['http_status'],429)

    def test_route_pagination_preserves_all_plans(self):
        q = self.question()
        expected = {self.plan(request='route-'+str(i),url='https://example.com/report-'+str(i)) for i in range(22)}
        first = flow.question_packet(self.store,self.cid,q['id'],['HBM'],['alternative'])
        second = flow.question_packet(self.store,self.cid,q['id'],['HBM'],['alternative'],route_offset=first['next_route_offset'])
        self.assertEqual({p['plan_id'] for p in first['routes']+second['routes']},expected)
        self.assertIsNone(second['next_route_offset'])

    def test_plan_lookup_does_not_load_all_historical_checkpoint_bodies(self):
        pid = self.plan()
        with patch.object(self.store,'records',side_effect=AssertionError('Do not load all task bodies')):
            self.assertEqual(flow.plans(self.store,self.cid)[0]['id'],pid)

    def test_future_document_excluded_and_missing_date_flagged(self):
        q = self.question()
        future = self.store.capture({'url':'https://example.com/future','producer':'Synthetic'},self.raw,'text/html',
                                    {'published_at':'2027-01-01'})['document_id']
        undated = self.store.capture({'url':'https://example.com/undated','producer':'Synthetic'},self.raw,'text/html',{})['document_id']
        state = loop.resume(self.store,self.cid)
        state['questions'][0]['attempts'] = [{'route':'explicit existing sources','outcome':'found','finding':'Not yet reviewed',
                                             'document_ids':[future,undated]}]
        loop.checkpoint(self.store,'existing-sources',{'campaign_id':self.cid,'previous_id':state['checkpoint_id'],
                        'nodes':state['nodes'],'questions':state['questions']})
        packet = flow.question_packet(self.store,self.cid,q['id'],['HBM'],['alternative'])
        self.assertEqual(packet['sources'][0]['excluded'],'after_campaign_cutoff')
        self.assertNotIn('lanes',packet['sources'][0])
        self.assertTrue(packet['sources'][1]['date_review_required'])

    def test_many_short_segments_and_completed_lane_are_bounded(self):
        raw = '\n'.join('supply '+str(i) for i in range(200)).encode()
        did = self.store.capture({'url':'https://example.com/many','producer':'Synthetic'},raw,'text/plain',{})['document_id']
        packet = flow.context(self.store,did,['supply'],['alternative'],24000)
        self.assertEqual(len(packet['lanes']['focus']['segments']),40)
        self.assertEqual(packet['lanes']['focus']['next_cursor']['offset'],40)
        resumed = flow.context(self.store,did,['supply'],['alternative'],24000,
                               {'focus':packet['lanes']['focus']['next_cursor'],'counter':None})
        self.assertEqual(resumed['lanes']['focus']['segments'][0]['location'],'block:41')
        self.assertTrue(resumed['lanes']['counter']['already_exhausted'])

    def test_sec_filing_html_and_missing_contact_status(self):
        pid = self.plan(kind='sec_filing',url='https://www.sec.gov/Archives/edgar/data/1/report.htm')
        with patch.dict('os.environ',{},clear=True):
            result = flow.acquire(self.store,'sec-missing-contact',{'plan_id':pid})
        self.assertEqual(result['status'],'configuration_required')
        self.assertFalse(result['network_performed'])
        with patch.dict('os.environ',{'SEC_USER_AGENT':'Synthetic contact test@example.invalid'}):
            result = self.acquire(pid,request='sec-filing')
        self.assertEqual(result['status'],'success')
        self.assertEqual(self.store.document(result['document_id'])['mime'],'text/html')

    def test_question_packet_read_only_cross_process_and_cutoff(self):
        q = self.question()
        pid = self.plan()
        self.acquire(pid)
        before = (self.store.folder / 'research.sqlite').read_bytes()
        action = {'op': 'question-packet', 'state_dir': str(self.store.folder), 'project_id': self.store.project_id,
                  'campaign_id': self.cid, 'question_id': q['id'], 'focus_terms': ['supply'], 'counter_terms': ['alternative']}
        action_file = self.store.folder / 'packet.json'
        action_file.write_text(json.dumps(action), encoding='utf-8')
        cli = Path(__file__).resolve().parents[1] / 'plugin/runtime/research_cli.py'
        p = subprocess.run([sys.executable, '-X', 'utf8', str(cli), '--action', str(action_file)], capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual((self.store.folder / 'research.sqlite').read_bytes(), before)
        self.assertIn('Synthetic issuer', p.stdout)

    def test_cursors_budgets_and_mismatched_question_fail(self):
        did = self.fx.document()
        for args in ({'max_chars': True}, {'max_chars': 0}, {'cursors': {'focus': {'offset': -1}}},
                     {'cursors': {'focus': {'offset': 0, 'char_offset': 999999}}}):
            with self.assertRaises(ValueError):
                flow.context(self.store, did, ['Demand'], ['substitute'], **args)
        with self.assertRaises(ValueError):
            flow.question_packet(self.store, self.cid, 'missing', ['Demand'], ['substitute'])


if __name__ == '__main__':
    unittest.main()
