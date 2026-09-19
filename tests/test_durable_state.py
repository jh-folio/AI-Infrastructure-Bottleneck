"""Claude Cowork durable copies: verified, bounded, opt-in and never a reason to fail a research write."""
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT/'plugin/runtime'
sys.path[:0] = [str(RUNTIME), str(RUNTIME/'core'), str(RUNTIME/'adapters')]
import durable_state as durable
import research_cli
import user_workflow as flow
from research_store import Store, create

CONFIG = {'name': 'Synthetic Cowork', 'scope': 'Synthetic only', 'as_of_date': '2026-09-19'}


def files(folder):
    return {p.relative_to(folder).as_posix(): p.read_bytes() for p in Path(folder).rglob('*') if p.is_file()}


class DurableTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.durable = self.base/'connected'
        self.durable.mkdir()
        self.state = self.base/'session-a'/'state'
        self.state.parent.mkdir()
        self.project = create(self.state, CONFIG)
        self.store = Store(self.state, self.project['project_id'])
        self.n = 0

    def add(self, count=1, store=None):
        for _ in range(count):
            self.n += 1
            (store or self.store).append('task', 'record-%d' % self.n, {'note': 'synthetic record %d' % self.n})

    def sync(self, **kw):
        return durable.sync(self.store, str(self.durable), **kw)

    def project_dir(self):
        return self.durable/durable.ROOT_NAME/self.store.project_id

    def lose_session(self):
        shutil.rmtree(self.state.parent)

    def route(self, intent, **extra):
        return flow.route({'intent': intent, 'host': 'cowork', **extra})

    # ---- folder check ----
    def test_check_creates_only_its_own_folder_leaves_a_probe_and_warns_about_other_files(self):
        (self.durable/'notes.txt').write_text('user file')
        result = durable.check(str(self.durable))
        self.assertEqual(result['status'], 'ready')
        self.assertFalse(result['prior_probe_found'])
        self.assertEqual(result['foreign_entry_count'], 1)
        self.assertTrue(result['warnings'])
        self.assertEqual((self.durable/'notes.txt').read_text(), 'user file')
        self.assertEqual(sorted(p.name for p in (self.durable/durable.ROOT_NAME).iterdir()), ['PROBE.json', 'README.txt'])
        again = durable.check(str(self.durable))
        self.assertTrue(again['prior_probe_found'])
        self.assertEqual(again['probe_created_at'], json.loads((self.durable/durable.ROOT_NAME/'PROBE.json').read_text())['created_at'])
        for bad in ('relative/path', str(self.base/'missing')):
            with self.assertRaises(ValueError):
                durable.check(bad)

    # ---- copies ----
    def test_sync_and_restore_round_trip_leaves_live_state_untouched(self):
        self.add(3)
        before = files(self.state)
        saved = self.sync(trigger='test')
        self.assertEqual(saved['status'], 'saved')
        self.assertEqual(files(self.state), before)
        found = durable.discover(str(self.durable))['projects']
        self.assertEqual([p['project_id'] for p in found], [self.store.project_id])
        self.assertEqual(found[0]['name'], 'Synthetic Cowork')
        restored = self.base/'session-b'/'state'
        restored.parent.mkdir()
        value = durable.restore_latest(str(self.durable), str(restored))
        self.assertEqual(value['status'], 'restored')
        reopened = flow.open_project(restored, self.store.project_id)
        self.assertEqual([r['id'] for r in reopened.records()], [r['id'] for r in self.store.records()])
        self.assertEqual(durable.load_config(restored)['durable_dir'], str(self.durable))
        with self.assertRaises(FileExistsError):
            durable.restore_latest(str(self.durable), str(restored))

    def test_rotation_keeps_the_newest_and_never_touches_foreign_names(self):
        for _ in range(4):
            self.add()
            self.sync(keep=2)
        self.assertEqual(len(list(self.project_dir().iterdir())), 2)
        (self.project_dir()/'19990101T000000000000Z-deadbeef').mkdir()
        (self.project_dir()/'notes').mkdir()
        self.add()
        self.sync(keep=2)
        names = sorted(p.name for p in self.project_dir().iterdir())
        self.assertNotIn('19990101T000000000000Z-deadbeef', names)
        self.assertIn('notes', names)
        self.assertEqual(len([n for n in names if n != 'notes']), 2)
        latest = durable.discover(str(self.durable))['projects'][0]['latest']['backup']
        self.assertEqual(latest, max(n for n in names if n != 'notes'))

    def test_damaged_newest_copy_falls_back_to_the_previous_verified_copy(self):
        self.add()
        first = self.sync()
        self.add()
        second = self.sync()
        newest = self.project_dir()/second['backup']/'research.sqlite'
        raw = newest.read_bytes()
        newest.write_bytes(raw[:-1] + bytes([raw[-1] ^ 1]))
        found = durable.discover(str(self.durable))['projects'][0]
        self.assertEqual(found['latest']['backup'], first['backup'])
        self.assertEqual(found['skipped_damaged'], [second['backup']])
        restored = self.base/'restored'
        durable.restore_latest(str(self.durable), str(restored))
        self.assertEqual(len(flow.open_project(restored).records()), 1)
        for copy in self.project_dir().iterdir():
            (copy/'research.sqlite').write_bytes(b'broken')
        self.assertEqual(durable.discover(str(self.durable))['projects'][0]['status'], 'damaged')
        with self.assertRaisesRegex(ValueError, 'No verified'):
            durable.restore_latest(str(self.durable), str(self.base/'never'))
        self.assertFalse((self.base/'never').exists())

    def test_restore_requires_a_choice_when_several_projects_have_copies(self):
        other_state = self.base/'other'
        other = create(other_state, {**CONFIG, 'name': 'Other'})
        self.add()
        self.sync()
        durable.sync(Store(other_state, other['project_id']), str(self.durable))
        with self.assertRaisesRegex(ValueError, 'project_id'):
            durable.restore_latest(str(self.durable), str(self.base/'r1'))
        self.assertFalse((self.base/'r1').exists())
        value = durable.restore_latest(str(self.durable), str(self.base/'r2'), other['project_id'])
        self.assertEqual(value['project']['project_id'], other['project_id'])

    # ---- CLI hook ----
    def test_checkpoint_like_ops_save_but_failures_never_change_the_operation_result(self):
        durable.configure(str(self.state), str(self.durable))
        request = {'op': 'research-checkpoint', 'state_dir': str(self.state), 'project_id': self.store.project_id}
        self.add()
        saved = durable.after_op(request, {'id': 'x'})
        self.assertEqual((saved['id'], saved['durable']['status'], saved['durable']['trigger']), ('x', 'saved', 'research-checkpoint'))
        result = {'id': 'x'}
        self.assertIs(durable.after_op({**request, 'op': 'research-question'}, result), result)
        self.assertEqual(durable.after_op({**request, 'op': 'research-patch'}, result)['durable']['status'], 'saved')
        shutil.rmtree(self.durable)
        failed = durable.after_op(request, {'id': 'x'})
        self.assertEqual((failed['id'], failed['durable']['status']), ('x', 'failed'))
        self.assertEqual(len(self.store.records()), 1)

    def test_hosts_without_a_durable_folder_are_untouched(self):
        result = {'id': 'x'}
        request = {'op': 'research-checkpoint', 'state_dir': str(self.state), 'project_id': self.store.project_id}
        self.assertIs(durable.after_op(request, result), result)
        self.assertFalse((self.state/durable.CONFIG_NAME).exists())

    def test_explicit_cli_ops(self):
        self.assertEqual(research_cli.execute({'op': 'durable-check', 'durable_dir': str(self.durable)})['status'], 'ready')
        request = {'op': 'durable-sync', 'state_dir': str(self.state), 'project_id': self.store.project_id}
        with self.assertRaisesRegex(ValueError, 'durable_dir'):
            research_cli.execute(request)
        saved = research_cli.execute({**request, 'durable_dir': str(self.durable), 'durable_keep': 3})
        self.assertEqual(saved['status'], 'saved')
        self.assertEqual(durable.load_config(self.state), {'durable_dir': str(self.durable), 'keep': 3})
        self.assertEqual(research_cli.execute(request)['status'], 'saved')

    # ---- workflow routing (Cowork only) ----
    def test_routing_is_unchanged_without_the_cowork_host(self):
        self.assertEqual(flow.route({'intent': 'start'})['status'], 'setup_required')
        self.assertEqual(flow.route({'intent': 'show'})['status'], 'no_project')
        value = flow.route({'intent': 'start', 'durable_dir': str(self.durable)})
        self.assertEqual(value['status'], 'setup_required')
        self.assertNotIn('durable_dir', value)
        lost = str(self.base/'gone'/'state')
        plain = flow.route({'intent': 'resume', 'state_dir': lost})
        self.assertEqual(plain['status'], 'recovery_required')
        self.assertNotIn('durable_candidates', plain)

    def test_cowork_requires_a_durable_folder_unless_the_user_waives_it(self):
        for intent in ('start', 'show', 'resume'):
            self.assertEqual(self.route(intent)['status'], 'durable_location_required')
        waived = self.route('start', durable_waived=True)
        self.assertEqual(waived['status'], 'setup_required')
        self.assertIn('warning', waived)
        self.assertEqual(self.route('show', durable_waived=True)['status'], 'no_project')
        for bad in (str(self.base/'missing'), 'relative'):
            self.assertEqual(self.route('start', durable_dir=bad)['status'], 'durable_location_required')

    def test_cowork_empty_folder_starts_new_with_a_sync_step_and_routing_writes_nothing(self):
        value = self.route('start', durable_dir=str(self.durable))
        self.assertEqual(value['status'], 'setup_required')
        self.assertIn('durable-sync', value['steps'])
        self.assertEqual(value['durable_dir'], str(self.durable))
        self.assertEqual(files(self.durable), {})
        self.assertFalse((self.durable/durable.ROOT_NAME).exists())
        self.assertEqual(self.route('resume', durable_dir=str(self.durable))['status'], 'no_project')

    def test_cowork_offers_restore_instead_of_a_silent_new_project(self):
        self.add()
        self.sync()
        before = files(self.durable)
        self.lose_session()
        for intent in ('start', 'research', 'show', 'resume'):
            value = self.route(intent, durable_dir=str(self.durable))
            self.assertEqual(value['status'], 'durable_restore_available', intent)
            self.assertEqual(value['restore']['project_id'], self.store.project_id)
        self.assertEqual(files(self.durable), before)
        self.assertEqual(self.route('start', durable_dir=str(self.durable), allow_new_project=True)['status'], 'setup_required')
        self.assertEqual(self.route('show', durable_dir=str(self.durable), allow_new_project=True)['status'],
                         'durable_restore_available')

    def test_cowork_selection_among_projects_and_damaged_only_copies(self):
        other_state = self.base/'other'
        other = create(other_state, {**CONFIG, 'name': 'Other'})
        self.add()
        self.sync()
        durable.sync(Store(other_state, other['project_id']), str(self.durable))
        two = self.route('start', durable_dir=str(self.durable))
        self.assertEqual((two['status'], two['source'], len(two['projects'])), ('project_selection_required', 'durable', 2))
        solo = self.base/'solo'
        solo.mkdir()
        state = self.base/'solo-state'
        info = create(state, CONFIG)
        durable.sync(Store(state, info['project_id']), str(solo))
        copy = next((solo/durable.ROOT_NAME/info['project_id']).iterdir())
        (copy/'research.sqlite').write_bytes(b'broken')
        broken = self.route('start', durable_dir=str(solo))
        self.assertEqual((broken['status'], broken['source']), ('recovery_required', 'durable'))
        self.assertEqual(self.route('start', durable_dir=str(solo), allow_new_project=True)['status'], 'setup_required')

    def test_cowork_recovery_lists_durable_candidates_when_the_known_state_vanished(self):
        self.add()
        self.sync()
        lost = str(self.state)
        self.lose_session()
        value = self.route('resume', state_dir=lost, project_id=self.store.project_id, durable_dir=str(self.durable))
        self.assertEqual(value['status'], 'recovery_required')
        self.assertEqual(value['steps'][0], 'durable-restore')
        self.assertEqual(value['durable_candidates'][0]['project_id'], self.store.project_id)

    def test_open_project_reports_durable_state_without_writing(self):
        request = {'state_dir': str(self.state), 'project_id': self.store.project_id}
        before = files(self.state)
        self.assertEqual(self.route('start', **request)['durable']['status'], 'not_configured')
        self.assertEqual(self.route('start', **request, durable_waived=True)['durable']['status'], 'waived')
        self.assertEqual(self.route('start', **request, durable_dir=str(self.durable))['durable']['status'], 'sync_required')
        self.assertEqual(files(self.state), before)
        durable.configure(str(self.state), str(self.durable))
        before = files(self.state)
        self.assertEqual(self.route('start', **request)['durable']['status'], 'configured')
        self.assertEqual(files(self.state), before)
        self.assertNotIn('durable', flow.route({'intent': 'start', **request}))

    # ---- whole session-loss story ----
    def test_session_loss_and_recovery_end_to_end(self):
        first = self.base/'first'/'state'
        first.parent.mkdir()
        created = research_cli.execute({'op': 'init', 'state_dir': str(first), 'durable_dir': str(self.durable),
                                        'config': CONFIG})
        pid = created['project_id']
        self.assertEqual(created['durable']['status'], 'saved')
        self.add(2, Store(first, pid))
        self.assertEqual(research_cli.execute({'op': 'durable-sync', 'state_dir': str(first), 'project_id': pid})['status'], 'saved')
        shutil.rmtree(first.parent)
        checked = research_cli.execute({'op': 'durable-check', 'durable_dir': str(self.durable)})
        self.assertTrue(checked['prior_probe_found'])
        self.assertEqual([p['project_id'] for p in checked['projects']], [pid])
        offered = self.route('start', durable_dir=str(self.durable))
        self.assertEqual(offered['status'], 'durable_restore_available')
        second = self.base/'second'/'state'
        second.parent.mkdir()
        restored = research_cli.execute({'op': 'durable-restore', 'durable_dir': str(self.durable), 'destination': str(second)})
        self.assertEqual(restored['project']['project_id'], pid)
        reopened = self.route('start', state_dir=str(second), project_id=pid)
        self.assertEqual(reopened['durable']['status'], 'configured')
        self.assertEqual(len(flow.open_project(second, pid).records()), 2)
        self.add(1, Store(second, pid))
        again = durable.after_op({'op': 'research-checkpoint', 'state_dir': str(second), 'project_id': pid}, {'id': 'y'})
        self.assertEqual(again['durable']['status'], 'saved')


if __name__ == '__main__':
    unittest.main()
