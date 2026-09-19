"""Read-only routing for agent-interpreted intent; no natural-language guessing or research."""
from datetime import date
import json
from pathlib import Path
import sqlite3

from research_store import Store, FORMAT, digest
import durable_state
TEMP_WARNING = 'Claude Cowork의 기본 작업공간은 세션이 끝나면 사라질 수 있습니다. 연구를 이어가려면 작업 폴더에 검증된 사본이 필요합니다.'


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def is_work_skill():
    return (Path(__file__).resolve().parents[3]/'WORK_SKILL.json').is_file()


INTENTS = {'help', 'start', 'research', 'resume', 'update', 'show', 'explain', 'brief'}
HELP = [
    {'request': '처음 시작해줘', 'purpose': '환경과 기존 연구를 확인하고 필요한 설정부터 조사·보고서까지 이어갑니다.'},
    {'request': 'HBM만 더 조사해줘', 'purpose': '지정한 질문만 보강합니다.'},
    {'request': '이어서 조사해줘', 'purpose': '저장한 질문과 원문부터 미완료 연구를 재개합니다.'},
    {'request': '지난 보고서 이후 바뀐 내용을 업데이트해줘', 'purpose': '새 자료를 검토하고 이전 판단과 변화를 비교합니다.'},
    {'request': '저장된 보고서와 지도를 보여줘', 'purpose': '저장 결과를 표시합니다. 새로운 조사를 시작하지 않습니다.'},
    {'request': '왜 그렇게 판단했는지 설명해줘', 'purpose': '저장된 근거와 불확실성을 설명합니다.'},
    {'request': '플러그인 업데이트를 준비해줘', 'purpose': '신뢰하는 새 패키지와 호환성을 확인하고 기존 연구를 백업합니다.'},
]


def package_version():
    root = Path(__file__).resolve().parents[3]
    return (root/'VERSION').read_text(encoding='utf-8').strip()


def open_project(folder, project_id=None):
    """Explicit location only. Never initializes a missing or incompatible project."""
    folder = Path(folder).resolve()
    p = read_json(folder/'project.json')
    if p.get('format') != FORMAT or p.get('schema_version') != 1 or p.get('database') != 'research.sqlite':
        raise ValueError('Unsupported project format or schema; preserve original state')
    if project_id is not None and p['project_id'] != project_id:
        raise ValueError('Project identity mismatch')
    store = Store(folder, p['project_id'])
    if p.get('config') != store.config:
        raise ValueError('Project manifest and database differ')
    return store


def discover(project_files):
    """Agent supplies known project.json paths; no implicit home/drive-wide scan."""
    if not isinstance(project_files, list) or len(project_files) > 50:
        raise ValueError('Provide at most 50 known project files')
    results = []
    seen = set()
    for value in project_files:
        path = Path(value).resolve()
        if path.name != 'project.json':
            raise ValueError('Expected explicit project.json paths')
        if path in seen:
            continue
        seen.add(path)
        try:
            s = open_project(path.parent)
            results.append({'state_dir': str(s.folder), 'project_id': s.project_id,
                            'name': s.config['name'], 'as_of_date': s.config['as_of_date'], 'status': 'available'})
        except (ValueError, KeyError, TypeError, OSError, sqlite3.Error):
            results.append({'state_dir': str(path.parent), 'status': 'unavailable',
                            'message': '기존 상태를 열 수 없습니다. 원본 위치·백업·호환성을 확인하세요.'})
    return {'projects': results, 'read_only': True}


def durable_gate(action, intent, out, result):
    """Claude Cowork only. Never start a new project silently while a durable copy may exist. Read-only."""
    target = action.get('durable_dir')
    if not target:
        if action.get('durable_waived'):
            out['durable'] = {'status': 'waived', 'warning': TEMP_WARNING}
            return None
        return result('durable_location_required', 'initialize-project',
                      ['ask_connect_work_folder_or_waive', 'durable-check', 'retry_workflow'],
                      TEMP_WARNING + ' 연결된 작업 폴더가 있으면 그 경로를 durable_dir로 넘기세요. 없으면 사용자에게 이 연구 전용 빈 폴더 연결을 안내하거나, 사라질 수 있음을 알린 뒤 임시 저장으로 진행할지 한 번만 확인하세요.')
    try:
        found = durable_state.discover(target)
    except (ValueError, OSError):
        return result('durable_location_required', 'initialize-project',
                      ['ask_connect_work_folder_or_waive', 'durable-check', 'retry_workflow'],
                      '연결한 폴더를 사용할 수 없습니다. 절대 경로·존재·쓰기 권한을 확인하거나 다른 작업 폴더를 연결하세요.',
                      durable_dir=str(target))
    usable = [p for p in found['projects'] if p['status'] == 'available']
    damaged = [p for p in found['projects'] if p['status'] != 'available']
    new_ok = intent in ('start', 'research') and bool(action.get('allow_new_project'))
    out['durable'] = {'status': 'checked', 'durable_dir': found['durable_dir'], 'projects': len(usable)}
    if usable and not new_ok:
        if len(usable) > 1:
            return result('project_selection_required', 'initialize-project', ['select_or_recover_project', 'durable-restore'],
                          '작업 폴더에 검증된 사본이 있는 프로젝트가 여러 개입니다. 대화의 대상과 일치하는 project_id를 선택해 복구하세요.',
                          projects=usable, source='durable', durable_dir=found['durable_dir'])
        return result('durable_restore_available', 'initialize-project',
                      ['durable-restore', 'retry_workflow_with_restored_state_dir'],
                      '작업 폴더에서 이전 연구의 검증된 사본을 찾았습니다. 새로 시작하지 말고 복구해 이어가세요. 사용자가 새 프로젝트를 명시적으로 원할 때만 allow_new_project=true로 다시 호출하세요.',
                      restore=usable[0], durable_dir=found['durable_dir'])
    if damaged and not usable and not new_ok:
        return result('recovery_required', 'initialize-project', ['report_damaged_durable_copies'],
                      '작업 폴더에 연구 사본이 있지만 모두 검증에 실패했습니다. 새로 초기화하지 말고 사용자에게 알리세요.',
                      projects=damaged, source='durable', durable_dir=found['durable_dir'])
    return None


def route(action):
    intent = action.get('intent', 'help')
    if intent not in INTENTS:
        raise ValueError('Unknown workflow intent')
    if action.get('scope_mode', 'full') not in ('full', 'focused'):
        raise ValueError('Use full or focused scope_mode')
    if action.get('as_of_date'):
        date.fromisoformat(action['as_of_date'])
    out = {'intent': intent, 'plugin_version': package_version(), 'read_only': True,
           'guide': 'plugin/workflows/USER_WORKFLOW.md', 'research_executed': False}

    def result(status, skill, steps, message, **extra):
        value = {**out, 'status': status, 'skill': skill, 'steps': steps, 'message': message, **extra}
        if is_work_skill():
            value['distribution'] = 'chatgpt-work-skill'
            value['instructions'] = f'skills/{skill}/INSTRUCTIONS.md'
        return value

    if intent == 'help':
        return result('help', 'initialize-project', ['explain_features'],
                      '할 수 있는 작업과 요청 예시를 안내합니다. 도움말만으로 연구를 시작하지 않습니다.', examples=HELP[:-1] + [{'request': '스킬 ZIP 업데이트 방법을 알려줘', 'purpose': '기존 연구를 백업하고 새 ZIP으로 갱신한 뒤 동일 상태에 재접근합니다.'}] if is_work_skill() else HELP)
    state_dir = action.get('state_dir')
    if not state_dir and action.get('project_files'):
        projects = discover(action['project_files'])['projects']
        if len(projects) != 1 or projects[0]['status'] != 'available':
            return result('project_selection_required', 'initialize-project', ['select_or_recover_project'],
                          '기존 프로젝트를 선택하거나 접근 문제를 해결해야 합니다.', projects=projects)
        state_dir = projects[0]['state_dir']
    cowork = action.get('host') == 'cowork'
    if not state_dir:
        gate = durable_gate(action, intent, out, result) if cowork else None
        if gate:
            return gate
        if intent in ('start', 'research'):
            steps, extra = ['capabilities', 'resolve_writable_state_location', 'init', 'continue_requested_research'], {}
            if cowork and action.get('durable_dir'):
                steps.insert(3, 'durable-sync')
                extra['durable_dir'] = str(action['durable_dir'])
            if cowork and out.get('durable', {}).get('status') == 'waived':
                extra['warning'] = TEMP_WARNING
            return result('setup_required', 'initialize-project', steps,
                          '접근 가능한 저장 위치를 확인하고 설정부터 요청한 연구까지 같은 실행에서 이어갑니다.',
                          continue_to='build-baseline', scope_mode=action.get('scope_mode', 'full'), **extra)
        return result('no_project', 'initialize-project', ['explain_missing_state'],
                      '읽을 연구 상태가 없습니다. 기존 프로젝트 위치를 확인하거나 최초 연구를 요청하세요.')
    try:
        store = open_project(state_dir, action.get('project_id'))
        records = store.records()
    except (ValueError, KeyError, TypeError, OSError, sqlite3.Error):
        steps, extra = ['locate_original_or_verified_backup'], {}
        if cowork and action.get('durable_dir'):
            try:
                usable = [p for p in durable_state.discover(action['durable_dir'])['projects'] if p['status'] == 'available']
            except (ValueError, OSError):
                usable = []
            if usable:
                steps = ['durable-restore', 'retry_workflow_with_restored_state_dir']
                extra = {'durable_candidates': usable, 'durable_dir': str(action['durable_dir'])}
        return result('recovery_required', 'initialize-project', steps,
                      '기존 연구를 열 수 없습니다. 초기화하지 말고 원본·프로젝트 ID·호환성·백업을 확인하세요.', **extra)
    out['project'] = {'state_dir': str(store.folder), 'project_id': store.project_id,
                      'name': store.config['name'], 'as_of_date': store.config['as_of_date']}
    if cowork:
        config, wanted = durable_state.load_config(store.folder), action.get('durable_dir')
        if wanted and (not config or config['durable_dir'] != str(Path(wanted).resolve())):
            out['durable'] = {'status': 'sync_required', 'action': 'durable-sync', 'durable_dir': str(wanted)}
        elif config:
            out['durable'] = {'status': 'configured', 'durable_dir': config['durable_dir']}
        elif action.get('durable_waived'):
            out['durable'] = {'status': 'waived', 'warning': TEMP_WARNING}
        else:
            out['durable'] = {'status': 'not_configured', 'warning': TEMP_WARNING,
                              'action': 'ask_connect_work_folder_or_waive'}
    reports = [r for r in records if r['kind'] == 'report']
    campaigns = [r for r in records if r['kind'] == 'task' and r['payload']['data'].get('type') == 'research_campaign']
    out['counts'] = {k: sum(r['kind'] == k for r in records) for k in ('report', 'judgment', 'evidence')}
    selected_report = next((r for r in reports if r['id'] == action.get('report_id')), None)
    if action.get('report_id') and selected_report is None:
        raise ValueError('Requested report not found in this project')
    if intent in ('show', 'explain', 'brief'):
        if not selected_report:
            candidates = [r for r in reports if r['payload']['data'].get('mode') == 'synthesis'] if intent == 'show' else reports
            selected_report = candidates[-1] if candidates else (reports[-1] if reports else None)
        if selected_report:
            value = selected_report['payload']['data']
            out['report'] = {'report_id': selected_report['id'], 'snapshot_id': value['snapshot_id'],
                             'research_stage': value.get('research_stage', 'not_a_baseline'), 'title': value['title']}
            store.read_snapshot(value['snapshot_id'])
        if intent == 'show':
            if not selected_report:
                return result('no_report', 'build-dashboard', ['explain_missing_report'],
                              '아직 저장된 보고서가 없습니다. 조사 진행 상태를 안내하고 최초 조사 또는 재개 방법을 알려주세요.')
            mode = selected_report['payload']['data'].get('mode')
            steps = ['export-dashboard', 'open_artifact', 'explain_scope_and_next_actions'] if mode == 'synthesis' else ['export-report', 'open_artifact']
            return result('display_saved', 'build-dashboard', steps, '저장된 결과를 엽니다. 중간 결과는 중간 결과로 표시합니다.')
        return result('read_saved', 'audit-research' if intent == 'explain' else 'monitor-update',
                      ['record', 'read-document', 'explain_or_summarize_saved_state'],
                      '저장된 판단·근거를 사용합니다. 자료가 없으면 없다고 안내하고 새 조사나 채점을 하지 않습니다.')
    if intent in ('research', 'update') and action.get('scope_mode') == 'focused':
        return result('focused_research', 'build-baseline' if intent == 'research' else 'monitor-update', ['source_work', 'review_evidence', 'answer_focused_question'],
                      '요청한 질문만 보강합니다. 전체 전수 조사나 종합보고서로 범위를 넓히지 않습니다.')
    cid = action.get('campaign_id')
    if cid and not any(r['id'] == cid for r in campaigns):
        raise ValueError('Requested campaign not found in this project')
    if not cid and len(campaigns) > 1:
        return result('campaign_selection_required', 'initialize-project', ['select_campaign'],
                      '기준일과 목적이 다른 연구가 있습니다. 대화의 대상과 일치하는 연구를 선택하세요.',
                      campaigns=[{'campaign_id': r['id'], 'as_of_date': r['payload']['data']['as_of_date'],
                                  'objective': r['payload']['data']['objective']} for r in campaigns])
    cid = cid or (campaigns[0]['id'] if campaigns else None)
    if cid:
        from research_loop import next_work
        from research_quality import completion
        campaign = next(r['payload']['data'] for r in campaigns if r['id'] == cid)
        packet = next_work(store, cid, 5)
        associated = [r for r in reports if r['payload']['data'].get('campaign_id') == cid]
        rid = associated[-1]['id'] if associated else None
        gate = completion(store, cid, rid)
        out.update(campaign_id=cid, checkpoint_id=packet['checkpoint_id'], scope_profile=packet.get('scope_profile'),
                   pending_count=packet['pending_count'], ready_to_submit=gate['ready_to_submit'],
                   completion_reasons=gate['reasons'], next_actions=packet['next_actions'])
        # An explicit new cutoff is a different investigation, not a rewrite of old history.
        if action.get('as_of_date') and action['as_of_date'] != campaign['as_of_date'] and intent != 'resume':
            return result('new_period', 'build-baseline', ['research-start', 'compare_prior_sources', 'research_loop', 'review_and_deliver'],
                          '새 기준일의 연구를 추가하고 이전 원장과 보고서는 보존합니다.', previous_campaign_id=cid, previous_report_id=rid)
        if intent == 'resume' and action.get('as_of_date') and action['as_of_date'] != campaign['as_of_date']:
            return result('date_selection_required', 'initialize-project', ['clarify_resume_or_new_period'],
                          '재개는 원래 기준일을 유지합니다. 새 기간 연구인지 확인하세요.')
        from research_coordination import state as coordination_state, status as coordination_status
        cs=coordination_state(store,cid)
        if cs['config'] and (cs['mode']!='completed' or intent=='resume' or
                              (cs['schedule'] and cs['schedule']['status'] in ('active','failed'))):
            coordinated=coordination_status(store,cid)
            return result('coordinated_research', 'build-baseline',
                          ['coordination-status', coordinated['next_action']],
                          '분야별 상태를 확인합니다. 실행 중이면 다음 작업을 배정하고 중지·완료 상태이면 예약을 정리하세요.',
                          coordination=coordinated)
        if not gate['ready_to_submit']:
            if packet['ready_for_review']:
                return result('prepare_delivery', 'build-baseline', ['review_source_meaning', 'synthesize', 'research-completion', 'export-delivery'],
                              '조사 원장의 구조 조건은 갖췄습니다. 원문 의미와 실제 연구 수행을 검토하고 최신 보고서·화면을 생성하세요.')
            return result('resume_research', 'build-baseline', ['coordination-configure', 'research-next', 'source_work', 'research-patch', 'repeat_until_reviewable', 'review_and_deliver'],
                          '미완료 연구를 현재 checkpoint부터 같은 실행에서 이어갑니다. 기존 보고서가 있어도 완료로 간주하지 않습니다.')
        if intent == 'resume':
            return result('reviewable', 'audit-research', ['review_meaning_and_delivery'],
                          '구조상 제출 가능한 연구입니다. 의미 검토와 사용자 인수는 별도이며 새 연구를 자동 시작하지 않습니다.')
        return result('update_existing', 'monitor-update', ['collect_changes', 'review_evidence', 'synthesize', 'export-delivery'],
                      '기존 판단과 새 근거를 비교하고 변경 요약·보고서·화면을 연결합니다.', previous_report_id=rid)
    if intent == 'resume':
        return result('no_campaign', 'initialize-project', ['explain_missing_campaign'], '재개할 조사 원장이 없습니다. 기존 자료를 확인하고 조사 시작 방법을 안내하세요.')
    if intent == 'update' and not reports:
        return result('no_baseline', 'initialize-project', ['explain_first_research'], '갱신할 보고서가 없습니다. 최초 연구가 필요합니다.')
    return result('start_research', 'build-baseline', ['research-start', 'coordination-configure', 'research_loop', 'review_and_deliver'],
                  '기존 자료를 확인하고 최초 종합 연구를 수행합니다. 중간 저장 후에도 같은 실행을 계속합니다.')


def inventory(store):
    """Hash identity of original data for non-destructive upgrade verification."""
    records = store.records()
    for record in records:
        for ref in record['payload']['refs']:
            store.record(ref)
        for doc in record['payload']['documents']:
            store.document(doc)
    with store.connection() as db:
        if db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
            raise ValueError('Research database integrity failure')
        docs = [r[0] for r in db.execute('SELECT id FROM documents ORDER BY id')]
        snapshots = [r[0] for r in db.execute('SELECT id FROM snapshots ORDER BY id')]
        attempts = [dict(r) for r in db.execute('SELECT * FROM attempts ORDER BY id')]
    return {'project_id': store.project_id, 'config_sha256': digest(store.config),
            'records': {r['id']: r['sha256'] for r in records},
            'documents': {doc: store.document(doc)['sha256'] for doc in docs},
            'snapshots': {sid: digest(store.read_snapshot(sid)) for sid in snapshots},
            'attempts': {str(r['id']): digest(r) for r in attempts}}


def upgrade_check(action):
    if is_work_skill():
        raise ValueError('Work skill ZIP: plugin upgrade commands are unavailable; follow README.md backup and skill update steps')
    from package_integrity import verify_package
    package = verify_package(action['target_package'])
    store = open_project(action['state_dir'], action.get('project_id'))
    contract = package['compatibility']
    if contract.get('format') != FORMAT or 1 not in contract.get('read_schema_versions', []) or 1 not in contract.get('write_schema_versions', []):
        raise ValueError('Target package cannot read and write this schema; no automatic migration')
    before = inventory(store)
    return {'status': 'compatible', 'read_only': True, 'target': package,
            'project_id': store.project_id, 'state_dir': str(store.folder),
            'inventory_sha256': digest(before), 'schema_migration_required': False,
            'rescoring_performed': False, 'next': 'upgrade-prepare before replacing the installed package'}


def upgrade_prepare(action):
    checked = upgrade_check(action)
    store = open_project(action['state_dir'], action.get('project_id'))
    destination = Path(action['destination']).resolve()
    package_root = Path(action['target_package']).resolve()
    running_root = Path(__file__).resolve().parents[3]
    if destination.is_relative_to(store.folder) or destination.is_relative_to(package_root) or destination.is_relative_to(running_root):
        raise ValueError('Keep upgrade backup outside research state and plugin package')
    store.backup(destination)
    # Capture the backup, not a second live read; concurrent additions remain detectable.
    baseline = inventory(Store(destination, store.project_id))
    receipt = {'format': 'ai-bottleneck-upgrade-v1', 'project_id': store.project_id,
               'preparation_runtime_version': package_version(), 'target_version': checked['target']['version'],
               'target_contents_sha256': checked['target']['contents_sha256'], 'inventory': baseline}
    (destination/'upgrade.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
    return {'status': 'backup_prepared', 'backup_dir': str(destination), 'project_id': store.project_id,
            'target_version': receipt['target_version'], 'installed': False,
            'next': 'Update through the existing trusted plugin source; open a new chat and run upgrade-verify.'}


def upgrade_verify(action):
    checked = upgrade_check(action)
    backup = Path(action['backup_dir']).resolve()
    receipt = read_json(backup/'upgrade.json')
    manifest = read_json(backup/'backup.json')
    if receipt.get('format') != 'ai-bottleneck-upgrade-v1' or receipt['project_id'] != checked['project_id'] or manifest['project_id'] != checked['project_id']:
        raise ValueError('Upgrade backup belongs to another project')
    if digest((backup/'research.sqlite').read_bytes()) != manifest['sha256']:
        raise ValueError('Upgrade backup checksum mismatch')
    old = inventory(Store(backup, checked['project_id']))
    if old != receipt['inventory']:
        raise ValueError('Upgrade receipt does not match the backup')
    if receipt['target_version'] != checked['target']['version'] or receipt['target_contents_sha256'] != checked['target']['contents_sha256']:
        raise ValueError('Target package changed since backup preparation')
    new = inventory(open_project(action['state_dir'], checked['project_id']))
    preserved = old['config_sha256'] == new['config_sha256'] and all(
        all(new[k].get(key) == value for key, value in old[k].items()) for k in ('records', 'documents', 'snapshots', 'attempts'))
    if not preserved:
        raise ValueError('Original research history was changed or removed; preserve both states and restore to a new folder')
    return {'status': 'history_preserved', 'read_only': True, 'project_id': checked['project_id'],
            'target_version': receipt['target_version'], 'runtime_version': package_version(),
            'runtime_version_matches_target': package_version() == receipt['target_version'],
            'host_installation_verified': False,
            'boundary': 'Package and saved data verified. Confirm the host loaded this package and reopened the same project.'}
