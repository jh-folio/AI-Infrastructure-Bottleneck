"""Versioned campaign scope. Never delete catalog nodes or reinterpret old campaigns."""
from datetime import date

CONTEXT_IDS = frozenset(('E01','E02','E03','E04','E05','E06','E08','E10','E11','E12'))
DEFAULT = 'investment-supply-v1'
LEGACY = 'full-catalog-v1'


def profile(name, effective_date, reason):
    if name not in (DEFAULT, LEGACY):
        raise ValueError('Unknown research scope profile')
    date.fromisoformat(effective_date)
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError('Scope change needs a reason')
    return {'version': name, 'effective_date': effective_date, 'reason': reason}


def resolve(state):
    """New descendants require research even when their parents were context-only."""
    spec = state.get('scope_profile', {'version': LEGACY})
    if spec['version'] not in (DEFAULT, LEGACY):
        raise ValueError('Unsupported research scope version')
    active = [n['node_id'] for n in state['nodes'] if n.get('lifecycle','active') == 'active']
    context = [nid for nid in active if spec['version'] == DEFAULT and nid in CONTEXT_IDS]
    return {**spec, 'catalog_count':len(state['nodes']), 'active_count':len(active),
            'included_node_ids':[nid for nid in active if nid not in context],
            'context_node_ids':context,
            'dynamic_policy':'New and replacement nodes require investigation; no automatic exclusion.'}


def included(state):
    return set(resolve(state)['included_node_ids'])
