import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from urllib.error import HTTPError

MODULE = Path(__file__).resolve().parents[1] / 'plugin/runtime/adapters/source_probe.py'
spec = importlib.util.spec_from_file_location('source_probe', MODULE)
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)
URL = 'https://data.sec.gov/submissions/CIK0000000001.json'


class Response(io.BytesIO):
    status = 200
    def __init__(self, raw, mime):
        super().__init__(raw)
        self.headers = {'Content-Type': mime}
    def geturl(self):
        return URL


class Sources(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name) / 'sources'
        p.init(self.folder)

    def capture(self, raw=b'{"facts":{"unit":"USD","value":null}}', mime='application/json'):
        return p.capture(self.folder, URL, 'test-contact', lambda *a, **k: Response(raw, mime))

    def test_roundtrip_duplicate_and_revision(self):
        first = self.capture()
        self.assertEqual(first['status'], 'success')
        self.assertEqual(self.capture()['status'], 'unchanged')
        second = self.capture(b'{"facts":{"value":2}}')
        self.assertNotEqual(first['document_id'], second['document_id'])
        result = p.query(self.folder, first['document_id'], '/facts/value')
        self.assertEqual(result['preview'], 'null')
        self.assertFalse(result['truncated'])

    def test_failure_does_not_become_unchanged(self):
        good = self.capture()
        bad = self.capture(b'<html>Blocked</html>', 'text/html')
        self.assertEqual(bad['status'], 'parse_failed')
        self.assertIsNone(bad['document_id'])
        self.assertEqual(p.query(self.folder, good['document_id'], '/facts/unit')['preview'], '"USD"')

    def test_http_rate_limit(self):
        def fail(*args, **kwargs):
            raise HTTPError(URL, 429, 'limited', {}, None)
        result = p.capture(self.folder, URL, 'contact', fail)
        self.assertEqual(result['status'], 'rate_limited')
        self.assertNotIn('contact', json.dumps(result))

    def test_empty_invalid_and_oversize(self):
        for raw in (b'', b'not json', b'{}', b'{"x":NaN}', b'x' * (p.LIMIT + 1)):
            result = self.capture(raw)
            self.assertIn(result['status'], ('parse_failed', 'partial'))
            self.assertIsNone(result['document_id'])

    def test_query_budget_and_pointer(self):
        result = self.capture(b'{"a/b":["long text"]}')
        q = p.query(self.folder, result['document_id'], '/a~1b/0', 4)
        self.assertTrue(q['truncated'])
        self.assertEqual(len(q['preview']), 4)
        with self.assertRaises(ValueError):
            p.query(self.folder, result['document_id'], '/a~1b/-1')

    def test_url_restrictions(self):
        for url in ('http://data.sec.gov/a', 'https://localhost/a', URL+'?token=secret', 'https://user:pass@data.sec.gov/a'):
            with self.assertRaises(ValueError):
                p.safe_url(url)

    def test_hash_tamper(self):
        doc = self.capture()['document_id']
        with p.connect(self.folder) as db, db:
            db.execute('UPDATE documents SET sha256=?', ('wrong',))
        with self.assertRaises(ValueError):
            p.query(self.folder, doc)


if __name__ == '__main__':
    unittest.main()
