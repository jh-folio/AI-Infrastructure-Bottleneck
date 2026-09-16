"""Synthetic user-state/upgrade regressions; not a test of real research quality."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import unittest

import test_synthesis
import test_research_loop
import research_loop
import research
from research_store import Store, create, restore
from synthesis import make_report
import user_workflow as flow
from package_integrity import verify_package, SKILLS


def bytes_in(folder):
    return {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in folder.rglob('*') if p.is_file()}


def seal(folder):
    rows = [{'path': p.relative_to(folder).as_posix(), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
            for p in sorted(folder.rglob('*')) if p.is_file() and p.name != 'PACKAGE_CONTENTS.json']
    (folder/'PACKAGE_CONTENTS.json').write_text(json.dumps(rows), encoding='utf-8')


def synthetic_package(folder):
    folder.mkdir()
    interface = {'defaultPrompt': ['처음 시작해줘']}
    files = {
        'plugin.json': json.dumps({'name': 'ai-infrastructure-bottleneck', 'version': flow.package_version(),
                                  'extensions': {'com.openai': {'interface': interface}}}),
        '.codex-plugin/plugin.json': json.dumps({'name': 'ai-infrastructure-bottleneck', 'version': flow.package_version(),
                                                'skills': './skills/', 'interface': interface}),
        'VERSION': flow.package_version(), 'README.md': '[Workflow](plugin/workflows/USER_WORKFLOW.md)',
        'plugin/workflows/USER_WORKFLOW.md': '# Synthetic workflow',
        'plugin/runtime/compatibility.json': json.dumps({'format': flow.FORMAT, 'read_schema_versions': [1], 'write_schema_versions': [1]}),
    }
    files.update({f'skills/{s}/SKILL.md': f'---\nname: {s}\ndescription: Synthetic test\n---\n' for s in SKILLS})
    for name, value in files.items():
        path = folder/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding='utf-8')
    seal(folder)
    return folder


class UserWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.fx = test_synthesis.SynthesisTests()
        self.fx.setUp()
        self.addCleanup(self.fx.doCleanups)
        self.store = self.fx.store
        self.path = self.fx.path
        self.common = {'state_dir': str(self.path), 'project_id': self.store.project_id}

    def route(self, intent, **kw):
        before = bytes_in(self.path)
        value = flow.route({**self.common, 'intent': intent, **kw})
        self.assertEqual(bytes_in(self.path), before, 'Workflow routing must not write research state')
        return value

    def campaign(self, request='campaign', asof='2026-09-14'):
        return research_loop.start(self.store, request, {'objective': 'Synthetic full research', 'as_of_date': asof})['id']

    def report(self, campaign=None):
        action = self.fx.action([])
        if campaign:
            action['campaign_id'] = campaign
        return make_report(self.store, 'report-'+str(campaign), action)['id']

    def test_help_does_not_open_state_or_initialize(self):
        missing = self.path.parent/'missing'
        result = flow.route({'intent': 'help', 'state_dir': str(missing)})
        self.assertEqual(result['status'], 'help')
        self.assertFalse(missing.exists())
        self.assertGreaterEqual(len(result['examples']), 6)

    def test_new_start_continues_after_setup(self):
        value = flow.route({'intent': 'start'})
        self.assertEqual(value['status'], 'setup_required')
        self.assertEqual(value['continue_to'], 'build-baseline')
        self.assertEqual(value['steps'][-1], 'continue_requested_research')

    def test_show_without_state_does_not_start_research(self):
        self.assertEqual(flow.route({'intent': 'show'})['status'], 'no_project')

    def test_missing_known_state_requires_recovery(self):
        missing = self.path.parent/'lost'
        self.assertEqual(flow.route({'intent': 'start', 'state_dir': str(missing)})['status'], 'recovery_required')
        self.assertFalse(missing.exists())

    def test_wrong_project_and_unsupported_schema_not_reinitialized(self):
        self.assertEqual(self.route('start', project_id='wrong')['status'], 'recovery_required')
        path = self.path/'project.json'
        p = json.loads(path.read_text()); p['schema_version'] = 99
        path.write_text(json.dumps(p))
        self.assertEqual(self.route('start')['status'], 'recovery_required')

    def test_empty_project_start_and_show(self):
        self.assertEqual(self.route('start')['status'], 'start_research')
        self.assertEqual(self.route('show')['status'], 'no_report')
        self.assertEqual(self.route('resume')['status'], 'no_campaign')

    def test_discovery_multiple_projects_never_picks_arbitrarily(self):
        other = self.path.parent/'other'
        create(other, {'name': 'Other', 'scope': 'Synthetic', 'as_of_date': '2026-09-15'})
        paths = [str(self.path/'project.json'), str(other/'project.json')]
        out = flow.route({'intent': 'start', 'project_files': paths})
        self.assertEqual(out['status'], 'project_selection_required')
        self.assertEqual(len(out['projects']), 2)
        one = flow.route({'intent': 'start', 'project_files': paths[:1]})
        self.assertEqual(one['project']['project_id'], self.store.project_id)

    def test_single_invalid_candidate_does_not_fall_through_to_setup(self):
        value = flow.route({'intent': 'start', 'project_files': [str(self.path.parent/'lost/project.json')]})
        self.assertEqual(value['status'], 'project_selection_required')

    def test_incomplete_campaign_and_interim_report_resume(self):
        cid = self.campaign()
        self.report(cid)
        value = self.route('start')
        self.assertEqual(value['status'], 'resume_research')
        self.assertEqual(value['campaign_id'], cid)
        self.assertGreater(value['pending_count'], 0)
        self.assertFalse(value['ready_to_submit'])

    def test_display_interim_does_not_start_research(self):
        cid = self.campaign(); rid = self.report(cid)
        value = self.route('show')
        self.assertEqual(value['status'], 'display_saved')
        self.assertEqual(value['report']['report_id'], rid)
        self.assertEqual(value['report']['research_stage'], 'interim')
        self.assertEqual(value['steps'][0], 'export-dashboard')

    def test_simple_report_is_exported_without_inventing_dashboard(self):
        research.report(self.store, 'simple', [], mode='weekly_brief', title='Synthetic brief')
        value = self.route('show')
        self.assertEqual(value['steps'][0], 'export-report')

    def test_explanation_and_summary_only_read(self):
        for intent in ('explain', 'brief'):
            value = self.route(intent)
            self.assertEqual(value['status'], 'read_saved')
            self.assertNotIn('research-start', value['steps'])

    def test_focused_question_and_update_do_not_force_full_pending_research(self):
        self.campaign()
        for intent in ('research', 'update'):
            value = self.route(intent, scope_mode='focused')
            self.assertEqual(value['status'], 'focused_research')
            self.assertNotIn('research_loop', value['steps'])

    def test_new_period_preserves_pending_campaign(self):
        cid = self.campaign()
        value = self.route('update', as_of_date='2026-09-16')
        self.assertEqual(value['status'], 'new_period')
        self.assertEqual(value['previous_campaign_id'], cid)
        self.assertEqual(len([r for r in self.store.records('task') if r['payload']['data']['type'] == 'research_campaign']), 1)

    def test_resume_does_not_silently_change_cutoff(self):
        self.campaign()
        self.assertEqual(self.route('resume', as_of_date='2026-09-16')['status'], 'date_selection_required')

    def test_multiple_campaigns_require_context_selection(self):
        first = self.campaign()
        self.campaign('second', '2026-09-15')
        self.assertEqual(self.route('resume')['status'], 'campaign_selection_required')
        self.assertEqual(self.route('resume', campaign_id=first)['campaign_id'], first)

    def test_wrong_report_or_campaign_fails(self):
        with self.assertRaises(ValueError): self.route('show', report_id='nonexistent')
        with self.assertRaises(ValueError): self.route('resume', campaign_id='nonexistent')

    def test_cli_help_and_new_process_reaccess(self):
        action = self.path.parent/'action.json'
        action.write_text(json.dumps({'op': 'workflow', 'intent': 'start', **self.common}), encoding='utf-8')
        cli = Path(__file__).resolve().parents[1]/'plugin/runtime/research_cli.py'
        result = subprocess.run([sys.executable, '-X', 'utf8', str(cli), '--action', str(action)], capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['project']['project_id'], self.store.project_id)


class DeliveryRoutingTests(unittest.TestCase):
    def test_structural_readiness_transitions_to_delivery_then_update(self):
        fx = test_research_loop.ResearchLoopTests(); fx.setUp(); self.addCleanup(fx.doCleanups)
        value, judgment = fx.investigated(verified=True)
        head = research_loop.checkpoint(fx.store, 'ready', value)['id']
        common = {'state_dir': str(fx.store.folder), 'project_id': fx.store.project_id, 'campaign_id': fx.cid}
        before = bytes_in(fx.store.folder)
        self.assertEqual(flow.route({**common, 'intent': 'resume'})['status'], 'prepare_delivery')
        self.assertEqual(bytes_in(fx.store.folder), before)
        report = fx.fx.action([judgment])
        report.update(research_stage='baseline_review', campaign_id=fx.cid, checkpoint_id=head)
        report['research_execution'] = {'status': 'excluded_by_user', 'reason': 'Synthetic explicit exclusion fixture, not real research'}
        rid = make_report(fx.store, 'review', report)['id']
        before = bytes_in(fx.store.folder)
        self.assertEqual(flow.route({**common, 'intent': 'resume'})['status'], 'reviewable')
        update = flow.route({**common, 'intent': 'update'})
        self.assertEqual(update['status'], 'update_existing')
        self.assertEqual(update['previous_report_id'], rid)
        self.assertEqual(bytes_in(fx.store.folder), before)


class UpgradeTests(unittest.TestCase):
    def setUp(self):
        UserWorkflowTests.setUp(self)
        self.package = synthetic_package(self.path.parent/'package')
        self.backup = self.path.parent/'backup'
        self.action = {**self.common, 'target_package': str(self.package), 'destination': str(self.backup)}
        self.fx.judgment()
        self.store.snapshot()

    def test_prepare_verify_restore_and_append_preserve_original(self):
        before = bytes_in(self.path)
        result = flow.upgrade_prepare(self.action)
        self.assertFalse(result['installed'])
        self.assertEqual(bytes_in(self.path), before)
        self.fx.judgment()
        verified = flow.upgrade_verify({**self.action, 'backup_dir': str(self.backup)})
        self.assertEqual(verified['status'], 'history_preserved')
        self.assertFalse(verified['host_installation_verified'])
        restored_path = self.path.parent/'restored'
        restored = restore(self.backup, restored_path)
        self.assertEqual(restored['project_id'], self.store.project_id)
        self.assertEqual(flow.inventory(Store(restored_path, self.store.project_id)), json.loads((self.backup/'upgrade.json').read_text(encoding='utf-8'))['inventory'])
        with self.assertRaises(FileExistsError): restore(self.backup, restored_path)

    def test_unsupported_candidate_does_not_create_backup(self):
        p = self.package/'plugin/runtime/compatibility.json'
        v = json.loads(p.read_text()); v['write_schema_versions'] = [2]
        p.write_text(json.dumps(v)); seal(self.package)
        with self.assertRaisesRegex(ValueError, 'schema'): flow.upgrade_prepare(self.action)
        self.assertFalse(self.backup.exists())

    def test_corrupt_candidate_and_extra_secret_fail_before_backup(self):
        p = self.package/'README.md'; p.write_text('Changed')
        with self.assertRaisesRegex(ValueError, 'checksum'): flow.upgrade_prepare(self.action)
        self.assertFalse(self.backup.exists())
        seal(self.package)
        (self.package/'.env').write_text('SYNTHETIC_ONLY=true')
        with self.assertRaisesRegex(ValueError, 'unlisted'): flow.upgrade_prepare(self.action)

    def test_changed_target_requires_new_preparation(self):
        flow.upgrade_prepare(self.action)
        (self.package/'README.md').write_text('Changed package')
        seal(self.package)
        with self.assertRaisesRegex(ValueError, 'changed since'): flow.upgrade_verify({**self.action, 'backup_dir': str(self.backup)})

    def test_backup_corruption_and_receipt_tampering_fail(self):
        flow.upgrade_prepare(self.action)
        p = self.backup/'upgrade.json'; v = json.loads(p.read_text(encoding='utf-8')); v['inventory']['records'] = {}
        p.write_text(json.dumps(v))
        with self.assertRaisesRegex(ValueError, 'receipt'): flow.upgrade_verify({**self.action, 'backup_dir': str(self.backup)})
        (self.backup/'research.sqlite').write_bytes(b'broken')
        with self.assertRaisesRegex(ValueError, 'checksum'): flow.upgrade_verify({**self.action, 'backup_dir': str(self.backup)})

    def test_changed_or_removed_history_fails(self):
        flow.upgrade_prepare(self.action)
        with self.store.connection(True) as db:
            db.execute('DELETE FROM snapshots')
        with self.assertRaisesRegex(ValueError, 'history'): flow.upgrade_verify({**self.action, 'backup_dir': str(self.backup)})

    def test_backup_cannot_live_inside_state_or_package(self):
        for folder in (self.path/'backup', self.package/'backup'):
            with self.assertRaisesRegex(ValueError, 'outside'): flow.upgrade_prepare({**self.action, 'destination': str(folder)})
            self.assertFalse(folder.exists())

    def test_bad_manifest_path_or_version_or_link(self):
        p = self.package/'PACKAGE_CONTENTS.json'; rows = json.loads(p.read_text()); rows[0]['path'] = '../escape'
        p.write_text(json.dumps(rows))
        with self.assertRaises(ValueError): verify_package(self.package)
        seal(self.package)
        (self.package/'VERSION').write_text('different')
        seal(self.package)
        with self.assertRaisesRegex(ValueError, 'versions'): verify_package(self.package)
        (self.package/'VERSION').write_text(flow.package_version())
        (self.package/'README.md').write_text('[Missing](outside.md)')
        seal(self.package)
        with self.assertRaisesRegex(ValueError, 'link'): verify_package(self.package)


if __name__ == '__main__':
    unittest.main()
