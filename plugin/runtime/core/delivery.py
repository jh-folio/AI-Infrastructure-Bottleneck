"""One read-only delivery bundle from the report's frozen input snapshot."""
import json
from pathlib import Path
from research import data
from research_store import digest
from dashboard import projection, render_html


def export(store, report_id, destination):
    report = data(store, report_id, 'report')
    view = projection(store, report_id)
    snap = store.read_snapshot(report['snapshot_id'])
    catalog = report.get('map_catalog', {})
    nodes = catalog.get('nodes', [])
    questions = [q for n in nodes if n.get('lifecycle', 'active') == 'active' for q in n.get('questions', [])]
    identity = {'report_id': report_id, 'snapshot_id': report['snapshot_id'], 'projection_sha256': view['projection_sha256']}
    completion = {**identity, 'research_stage': report.get('research_stage', 'interim'),
        'quality_version': report.get('research_quality_version'), 'inventory_scope': view['inventory_scope'],
        'active_nodes': len(view['nodes']), 'retired_nodes': sum(n.get('lifecycle') == 'retired' for n in nodes),
        'judgment_scopes': len(view['rows']), 'scored_scopes': sum(r['score'] is not None for r in view['rows']),
        'node_research_states': {s:sum(n['research_status']==s for n in view['nodes']) for s in ('uninvestigated','in_progress','review_recorded')},
        'question_states': {s: sum(q['status'] == s for q in questions) for s in ('open', 'blocked', 'resolved', 'bounded')},
        'relations': {s: sum(e['kind'] == s for e in view['node_relations']) for s in ('reference','technical','observed','conditional')},
        'research_execution': report.get('research_execution'),
        'meaning': 'Frozen report record; counts and structural checks do not certify research interpretation or user acceptance.'}
    payloads = {'report.md': report['markdown'], 'dashboard.html': render_html(view),
        'dashboard-data.json': view, 'completion_manifest.json': completion,
        'node_review_ledger.json': {**identity, 'nodes': nodes},
        'research_review.json': {**identity, 'judgment_reviews': report['judgment_reviews'],
                                 'synthesis_claims': report['synthesis_claims'], 'research_execution': report['research_execution']},
        'source_index.json': {**identity, 'documents': snap['documents'], 'attempts': snap['attempts']}}
    # Snapshot documents contain metadata, not raw bytes or private contact config.
    folder = Path(destination).resolve()
    folder.mkdir(exist_ok=False)
    manifest = []
    for name, value in payloads.items():
        raw = (value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2)).encode('utf-8')
        (folder/name).write_bytes(raw)
        manifest.append({'path': name, 'sha256': digest(raw)})
    (folder/'DELIVERY.json').write_text(json.dumps({**identity,'files':manifest},ensure_ascii=False,indent=2),encoding='utf-8')
    return {**identity, 'path': str(folder), 'files': len(manifest)+1, 'read_only': True}
