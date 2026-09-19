"""Opt-in durable copies of the research DB for hosts whose workspace can disappear (Claude Cowork).

The live SQLite file stays in the session workspace. Verified copies are written into a dedicated
sub-folder of a user-connected folder and restored into a new workspace folder. Nothing here runs
unless a durable folder is given, so other hosts keep their existing behavior.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile
import uuid

from research_store import Store, FORMAT, dumps, restore as restore_backup

ROOT_NAME = 'AI-Bottleneck-State'
CONFIG_NAME = 'durable.json'
CONFIG_FORMAT = 'ai-bottleneck-durable-v1'
PROJECT_ID = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
STAMP = re.compile(r'^\d{8}T\d{12}Z-[0-9a-f]{8}$')
KEEP_DEFAULT = 5
IGNORED = {'.ds_store', 'desktop.ini', 'thumbs.db'}
AUTO_OPS = frozenset({'init', 'research-start', 'research-checkpoint', 'research-return', 'node-change',
                      'research-scope', 'coordination-apply', 'coordination-finish', 'synthesize',
                      'export-delivery','research-batch','research-questions-update','research-question-update','research-patch',
                      'review-seal','review-use','impact-scan'})
README = ('이 폴더는 AI Bottleneck 연구 DB의 검증된 백업을 보관합니다.\n'
          'Claude Cowork의 기본 작업공간은 세션이 끝나면 사라질 수 있어, 새 세션에서 연구를 이어가려면 이 폴더가 필요합니다.\n'
          '삭제하거나 이름을 바꾸지 마세요. 프로젝트 ID 폴더 안의 각 하위 폴더가 백업 하나입니다.\n')


def _sha(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def _keep(value):
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 20:
        raise ValueError('keep must be an integer from 1 to 20')
    return value


def _folder(durable_dir):
    if not isinstance(durable_dir, str) or not Path(durable_dir).is_absolute():
        raise ValueError('Durable folder must be an absolute path')
    path = Path(durable_dir).resolve()
    if not path.is_dir():
        raise ValueError('Durable folder is not an existing directory')
    return path


def _root(durable_dir, create=False):
    root = _folder(durable_dir) / ROOT_NAME
    if root.is_symlink():
        raise ValueError('Durable state folder must not be a link')
    if root.exists() and not root.is_dir():
        raise ValueError('Durable state name is occupied by a file')
    if create and not root.exists():
        root.mkdir()
        (root / 'README.txt').write_text(README, encoding='utf-8')
    if create and not (root / 'PROBE.json').is_file():
        (root / 'PROBE.json').write_text(dumps({'format': CONFIG_FORMAT, 'purpose': 'persistence probe',
                                                'created_at': datetime.now(timezone.utc).isoformat()}), encoding='utf-8')
    return root


def _copies(project_dir):
    rows = [p for p in project_dir.iterdir() if p.is_dir() and not p.is_symlink() and STAMP.match(p.name)]
    return sorted(rows, key=lambda p: p.name, reverse=True)


def _verified(copy, project_id):
    """Checked manifest of one copy, or None. Reads bytes only; never opens SQLite on the durable folder."""
    try:
        manifest = json.loads((copy / 'backup.json').read_text(encoding='utf-8'))
        if (manifest.get('format') != FORMAT or manifest.get('project_id') != project_id
                or manifest.get('database') != 'research.sqlite' or manifest.get('schema_version') != 1
                or _sha(copy / 'research.sqlite') != manifest.get('sha256')):
            return None
        return manifest
    except (OSError, ValueError, TypeError, AttributeError):
        return None


def discover(durable_dir):
    """Read-only list of projects with a verified copy. A missing state folder is not an error."""
    base = _folder(durable_dir)
    root = base / ROOT_NAME
    projects = []
    if root.is_dir() and not root.is_symlink():
        for project_dir in sorted(root.iterdir()):
            if not (project_dir.is_dir() and not project_dir.is_symlink() and PROJECT_ID.match(project_dir.name)):
                continue
            copies = _copies(project_dir)
            if not copies:
                continue
            damaged = []
            for copy in copies:
                manifest = _verified(copy, project_dir.name)
                if manifest is None:
                    damaged.append(copy.name)
                    continue
                projects.append({'project_id': project_dir.name, 'name': manifest.get('name'),
                                 'as_of_date': manifest.get('as_of_date'), 'status': 'available',
                                 'latest': {'backup': copy.name, 'created_at': manifest.get('created_at'),
                                            'bytes': (copy / 'research.sqlite').stat().st_size,
                                            'trigger': manifest.get('trigger')},
                                 'copies': len(copies), 'skipped_damaged': damaged})
                break
            else:
                projects.append({'project_id': project_dir.name, 'status': 'damaged', 'copies': len(copies),
                                 'message': '저장된 사본이 모두 검증에 실패했습니다.'})
    return {'durable_dir': str(base), 'root_exists': root.is_dir(), 'projects': projects, 'read_only': True}


def check(durable_dir):
    """Prove the folder is writable and report whether this tool's marker already survived from before."""
    marker, earlier = _folder(durable_dir) / ROOT_NAME / 'PROBE.json', None
    if marker.is_file():
        try:
            earlier = json.loads(marker.read_text(encoding='utf-8')).get('created_at')
        except (OSError, ValueError, AttributeError):
            earlier = None
    root = _root(durable_dir, create=True)
    token = uuid.uuid4().hex
    probe = root / ('.write-test-' + token)
    probe.write_text(token, encoding='utf-8')
    returned = probe.read_text(encoding='utf-8')
    probe.unlink()
    if returned != token:
        raise ValueError('Durable folder did not return the bytes just written')
    foreign = [p for p in _folder(durable_dir).iterdir() if p.name != ROOT_NAME and p.name.lower() not in IGNORED]
    out = {'status': 'ready', 'durable_dir': str(_folder(durable_dir)), 'root': str(root), 'writable': True,
           'prior_probe_found': earlier is not None, 'probe_created_at': earlier,
           'foreign_entry_count': len(foreign), 'projects': discover(durable_dir)['projects']}
    if foreign:
        out['warnings'] = ['연결한 폴더에 다른 파일·폴더가 %d개 있습니다. 이 연구 전용 빈 폴더를 연결하는 것이 안전합니다.' % len(foreign)]
    return out


def configure(state_dir, durable_dir, keep=KEEP_DEFAULT):
    value = {'format': CONFIG_FORMAT, 'durable_dir': str(_folder(durable_dir)), 'keep': _keep(keep)}
    (Path(state_dir).resolve() / CONFIG_NAME).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    return value


def load_config(state_dir):
    try:
        value = json.loads((Path(state_dir) / CONFIG_NAME).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    if not isinstance(value, dict) or value.get('format') != CONFIG_FORMAT or not isinstance(value.get('durable_dir'), str):
        return None
    try:
        keep = _keep(value.get('keep', KEEP_DEFAULT))
    except ValueError:
        keep = KEEP_DEFAULT
    return {'durable_dir': value['durable_dir'], 'keep': keep}


def _prune(project_dir, newest, keep):
    removed = 0
    older = [c for c in _copies(project_dir) if c.name != newest]
    complete = [c for c in older if (c / 'backup.json').is_file()]
    doomed = [c for c in older if c not in complete] + complete[max(keep - 1, 0):]
    for copy in doomed:
        shutil.rmtree(copy, ignore_errors=True)
        removed += 1
    return removed


def sync(store, durable_dir, keep=KEEP_DEFAULT, trigger=None):
    """Save one verified copy of the live DB; only this project's own stamped folders are ever removed."""
    keep = _keep(keep)
    if not PROJECT_ID.match(store.project_id):
        raise ValueError('Unexpected project id')
    root = _root(durable_dir, create=True)
    project_dir = root / store.project_id
    if project_dir.is_symlink():
        raise ValueError('Durable project folder must not be a link')
    project_dir.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='ai-bottleneck-durable-') as scratch:
        manifest = store.backup(Path(scratch) / 'copy')
        source = Path(scratch) / 'copy' / 'research.sqlite'
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '-' + manifest['sha256'][:8]
        final = project_dir / stamp
        if final.exists():
            shutil.rmtree(final)
        final.mkdir()
        try:
            shutil.copyfile(source, final / 'research.sqlite')
            if _sha(final / 'research.sqlite') != manifest['sha256']:
                raise ValueError('Durable copy checksum mismatch')
            saved = {**manifest, 'name': store.config.get('name'), 'as_of_date': store.config.get('as_of_date'),
                     'trigger': trigger}
            (final / 'backup.json').write_text(dumps(saved), encoding='utf-8')
            if _verified(final, store.project_id) is None:
                raise ValueError('Durable copy did not verify after writing')
        except BaseException:
            shutil.rmtree(final, ignore_errors=True)
            raise
    pruned = _prune(project_dir, stamp, keep)
    return {'status': 'saved', 'project_id': store.project_id, 'backup': stamp, 'created_at': manifest['created_at'],
            'bytes': (final / 'research.sqlite').stat().st_size, 'kept': len(_copies(project_dir)),
            'pruned': pruned, 'durable_dir': str(_folder(durable_dir)), 'trigger': trigger}


def restore_latest(durable_dir, destination, project_id=None, keep=KEEP_DEFAULT):
    """Restore the newest verified copy into a new folder and keep syncing to the same durable folder."""
    usable = [p for p in discover(durable_dir)['projects'] if p['status'] == 'available']
    if project_id is not None:
        usable = [p for p in usable if p['project_id'] == project_id]
    if not usable:
        raise ValueError('No verified durable copy found')
    if len(usable) > 1:
        raise ValueError('Several projects have durable copies; provide project_id')
    chosen = usable[0]
    source = _root(durable_dir) / chosen['project_id'] / chosen['latest']['backup']
    with tempfile.TemporaryDirectory(prefix='ai-bottleneck-restore-') as scratch:
        shutil.copytree(source, Path(scratch) / 'copy')
        project = restore_backup(Path(scratch) / 'copy', destination)
    configure(destination, durable_dir, keep)
    return {'status': 'restored', 'state_dir': str(Path(destination).resolve()), 'project': project,
            'restored_from': chosen['latest'], 'durable_configured': True,
            'note': '이 백업 이후에 저장된 변경은 포함되지 않습니다. 복구 뒤 workflow를 다시 호출해 재개 위치를 확인하세요.'}


def after_op(action, result):
    """Best-effort copy after checkpoint-like operations; never changes whether the operation succeeded."""
    op = action.get('op')
    if op not in AUTO_OPS or not isinstance(result, dict):
        return result
    state_dir = action.get('state_dir')
    project_id = action.get('project_id') or result.get('project_id')
    if not state_dir or not project_id:
        return result
    config = load_config(state_dir)
    durable_dir = action.get('durable_dir') or (config or {}).get('durable_dir')
    if not durable_dir:
        return result
    keep = action.get('durable_keep', (config or {}).get('keep', KEEP_DEFAULT))
    try:
        if not config or config['durable_dir'] != str(_folder(durable_dir)):
            configure(state_dir, durable_dir, keep)
        return {**result, 'durable': sync(Store(state_dir, project_id), durable_dir, keep, op)}
    except (OSError, ValueError, sqlite3.Error) as exc:
        message = str(exc) if isinstance(exc, ValueError) else 'The durable folder could not be written.'
        return {**result, 'durable': {'status': 'failed', 'error_type': type(exc).__name__, 'message': message,
                                      'note': 'The research state itself is unchanged; the durable copy is not current.'}}
