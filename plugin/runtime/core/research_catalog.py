"""Additive definitions; preserve the original identity file and historic campaigns."""
import json
from pathlib import Path
from research_store import digest

BASE_VERSION = 'legacy-id-map-1.0'
CURRENT_VERSION = 'model-providers-v1'


def load(version=CURRENT_VERSION):
    folder=Path(__file__).resolve().parents[2]/'ontology'
    base=json.loads((folder/'node_ids_v1.json').read_text(encoding='utf-8'))
    if version==BASE_VERSION:return base
    if version!=CURRENT_VERSION:raise ValueError('Unknown catalog version')
    extension=json.loads((folder/'node_extensions_v1.json').read_text(encoding='utf-8'))
    ids={n['Node_ID'] for n in base['nodes']}
    for node in extension['nodes']:
        if node['Node_ID'] in ids:raise ValueError('Extension must not reuse an existing ID')
        ids.add(node['Node_ID'])
    return {'version':CURRENT_VERSION,'source_sha256':digest({'base':base,'extension':extension}),
            'base_source_sha256':base['source_sha256'],'nodes':base['nodes']+extension['nodes']}
