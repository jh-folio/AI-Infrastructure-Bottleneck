"""Inspect package bytes without importing or executing the candidate package."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from urllib.parse import unquote

SKILLS = {'initialize-project', 'build-baseline', 'monitor-update', 'audit-research', 'build-dashboard'}


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def package_file(root, name):
    if not isinstance(name, str) or '\\' in name or ':' in name:
        raise ValueError('Invalid package path')
    parts = PurePosixPath(name)
    if parts.is_absolute() or not parts.parts or any(p in ('.', '..') for p in parts.parts):
        raise ValueError('Package path escapes root')
    path = root.joinpath(*parts.parts)
    if not path.resolve().is_relative_to(root) or any(p.is_symlink() for p in [path, *path.parents] if p != root.parent):
        raise ValueError('Package links are not permitted')
    return path


def verify_package(folder):
    root = Path(folder).resolve()
    rows = read_json(root/'PACKAGE_CONTENTS.json')
    if not isinstance(rows, list) or not rows:
        raise ValueError('Package contents missing')
    names = set()
    for row in rows:
        name = row['path']
        if name in names or name == 'PACKAGE_CONTENTS.json':
            raise ValueError('Duplicate or recursive package entry')
        names.add(name)
        path = package_file(root, name)
        if hashlib.sha256(path.read_bytes()).hexdigest() != row['sha256']:
            raise ValueError('Package checksum mismatch: '+name)
    # Generated interpreter cache and Git administration are not distribution assets.
    actual = {p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()
              and '.git' not in p.relative_to(root).parts and '__pycache__' not in p.relative_to(root).parts}
    if actual != names | {'PACKAGE_CONTENTS.json'}:
        raise ValueError('Package has missing or unlisted files')
    required = {'plugin.json', '.codex-plugin/plugin.json', '.claude-plugin/plugin.json',
                '.claude-plugin/marketplace.json', '.agents/plugins/marketplace.json', 'VERSION', 'README.md',
                'plugin/runtime/compatibility.json', 'plugin/workflows/USER_WORKFLOW.md'}
    if not required <= names:
        raise ValueError('Package entrypoints missing')
    manifest = read_json(root/'plugin.json')
    overlay = read_json(root/'.codex-plugin/plugin.json')
    claude_manifest = read_json(root/'.claude-plugin/plugin.json')
    marketplace = read_json(root/'.claude-plugin/marketplace.json')
    codex_marketplace = read_json(root/'.agents/plugins/marketplace.json')
    version = (root/'VERSION').read_text(encoding='utf-8').strip()
    if manifest['name'] != 'ai-infrastructure-bottleneck' or overlay['name'] != manifest['name'] \
            or claude_manifest['name'] != manifest['name']:
        raise ValueError('Unexpected plugin identity')
    if not version or manifest['version'] != version or overlay['version'] != version \
            or claude_manifest['version'] != version:
        raise ValueError('Package versions differ')
    if manifest['extensions']['com.openai']['interface'] != overlay['interface']:
        raise ValueError('Plugin presentation differs between manifests')
    listed = {p['name'] for p in marketplace.get('plugins', [])}
    if manifest['name'] not in listed:
        raise ValueError('Marketplace listing does not include the plugin')
    codex_listed = {p['name'] for p in codex_marketplace.get('plugins', [])}
    if overlay['name'] not in codex_listed:
        raise ValueError('Codex marketplace listing does not include the plugin')
    skills = {p.split('/')[1] for p in names if p.startswith('skills/') and p.endswith('/SKILL.md')}
    if skills != SKILLS or overlay.get('skills') != './skills/':
        raise ValueError('Expected the five workflow skills')
    links = 0
    for name in names:
        if not name.endswith('.md'):
            continue
        text = (root/name).read_text(encoding='utf-8')
        for target in re.findall(r'\[[^\]\n]*\]\(([^)\n]+)\)', text):
            target = target.strip('<>').split('#')[0]
            if not target or re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*:', target):
                continue
            linked = ((root/name).parent/unquote(target)).resolve()
            if not linked.is_relative_to(root) or not linked.is_file():
                raise ValueError('Unresolved package link in '+name+': '+target)
            links += 1
    contract = read_json(root/'plugin/runtime/compatibility.json')
    return {'version': version, 'name': manifest['name'], 'files': len(names)+1,
            'skills': sorted(skills), 'local_links': links, 'compatibility': contract,
            'contents_sha256': hashlib.sha256((root/'PACKAGE_CONTENTS.json').read_bytes()).hexdigest(),
            'trust_boundary': 'Hashes check consistency, not publisher authenticity. Use a trusted distribution source.'}
