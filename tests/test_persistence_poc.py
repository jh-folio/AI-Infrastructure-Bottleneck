"""D1 local behavioral checks. These cannot certify Work persistence."""
import importlib.util
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

MODULE = Path(__file__).resolve().parents[1] / 'plugin/runtime/core/persistence_poc.py'
spec = importlib.util.spec_from_file_location('poc', MODULE)
poc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(poc)


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name) / 'project'
        self.project = poc.initialize(self.folder)['project_id']

    def record(self, id='N1', kind='node', **extra):
        return dict(synthetic=True, id=id, kind=kind, **extra)

    def run_code(self, code):
        prefix = f"import sys; sys.path.insert(0, {str(MODULE.parent)!r}); import persistence_poc as p; "
        return subprocess.run([sys.executable, '-X', 'utf8', '-c', prefix + code],
                              capture_output=True, text=True, timeout=10)

    def test_reopen_in_another_process_and_append_history(self):
        for i in range(3):
            poc.append(self.folder, self.project, f'n{i}', self.record(f'N{i}'))
        poc.append(self.folder, self.project, 'source', self.record('S1', 'source'))
        for i in range(5):
            poc.append(self.folder, self.project, f'e{i}', self.record(f'E{i}', 'evidence',
                       refs=[{'kind': 'source', 'id': 'S1'}, {'kind': 'node', 'id': 'N0'}]))
        before = poc.inspect(self.folder, self.project)
        result = self.run_code(f"print(p.canonical(p.inspect({str(self.folder)!r}, {self.project!r})))")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), before)
        payload = self.record('score-v1', 'score', overall=None, methodology_version='synthetic',
                              refs=[{'kind': 'evidence', 'id': 'E0'}])
        result = self.run_code(f"p.append({str(self.folder)!r}, {self.project!r}, 'score1', {payload!r})")
        self.assertEqual(result.returncode, 0, result.stderr)
        poc.append(self.folder, self.project, 'score2', dict(payload, id='score-v2'))
        after = poc.inspect(self.folder, self.project)
        self.assertEqual(after['records'][:9], before['records'])
        self.assertIsNone(after['records'][-1]['payload']['overall'])

    def test_idempotency_and_conflicting_reuse(self):
        self.assertTrue(poc.append(self.folder, self.project, 'r', self.record())['inserted'])
        self.assertFalse(poc.append(self.folder, self.project, 'r', self.record())['inserted'])
        before = poc.inspect(self.folder, self.project)
        with self.assertRaises(ValueError):
            poc.append(self.folder, self.project, 'r', self.record('N2'))
        with self.assertRaises(ValueError):
            poc.append(self.folder, self.project, 'another', self.record())
        self.assertEqual(before, poc.inspect(self.folder, self.project))

    def test_wrong_project_and_existing_folder_refused(self):
        other = Path(self.temp.name) / 'other'
        project_b = poc.initialize(other)['project_id']
        with self.assertRaises(ValueError):
            poc.append(self.folder, project_b, 'r', self.record())
        with self.assertRaises(FileExistsError):
            poc.initialize(self.folder)
        self.assertEqual(poc.inspect(self.folder, self.project)['count'], 0)
        self.assertEqual(poc.inspect(other, project_b)['count'], 0)

    def test_missing_path_not_created_by_read(self):
        missing = Path(self.temp.name) / 'missing'
        with self.assertRaises(sqlite3.OperationalError):
            poc.inspect(missing, self.project)
        self.assertFalse(missing.exists())

    def test_real_data_and_dangling_reference_refused(self):
        for payload in [dict(self.record(), synthetic=False), self.record(value=float('nan')),
                        self.record(refs=[{'kind': 'source', 'id': 'absent'}])]:
            with self.assertRaises(ValueError):
                poc.append(self.folder, self.project, 'r', payload)
        self.assertEqual(poc.inspect(self.folder, self.project)['count'], 0)

    def test_killed_writer_rolls_back(self):
        poc.append(self.folder, self.project, 'r', self.record())
        before = poc.inspect(self.folder, self.project)
        code = (f"import sqlite3, os; d=sqlite3.connect({str(self.folder / 'poc.sqlite')!r}); "
                "d.execute('BEGIN IMMEDIATE'); d.execute('DELETE FROM records'); os._exit(23)")
        self.assertEqual(self.run_code(code).returncode, 23)
        self.assertEqual(before, poc.inspect(self.folder, self.project))
        poc.append(self.folder, self.project, 'next', self.record('N2'))

    def test_locked_writer_fails_then_retry_succeeds(self):
        with poc.connect(self.folder, self.project) as db:
            db.execute('BEGIN IMMEDIATE')
            with self.assertRaises(sqlite3.OperationalError):
                poc.append(self.folder, self.project, 'r', self.record(), timeout=0.01)
            db.rollback()
        self.assertTrue(poc.append(self.folder, self.project, 'r', self.record())['inserted'])

    def test_failed_schema_change_rolls_back(self):
        with poc.connect(self.folder, self.project) as db:
            with self.assertRaises(sqlite3.OperationalError):
                with poc.transaction(db):
                    db.execute('CREATE TABLE migration_probe (id TEXT)')
                    db.execute('INSERT INTO migrations VALUES (2)')
                    db.execute('INSERT INTO nonexistent VALUES (1)')
            self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='migration_probe'").fetchone())
        self.assertEqual(poc.inspect(self.folder, self.project)['count'], 0)

    def test_tampered_payload_detected(self):
        poc.append(self.folder, self.project, 'r', self.record())
        with poc.connect(self.folder, self.project) as db:
            db.execute('UPDATE records SET sha256=?', ('invalid',))
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            poc.inspect(self.folder, self.project)


if __name__ == '__main__':
    unittest.main()
