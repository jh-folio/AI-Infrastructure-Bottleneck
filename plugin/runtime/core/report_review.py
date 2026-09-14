"""Require explicit source-to-claim review; never infer scientific validity from text."""
from research_store import required


def validate_review(value, rows, evidence, documents):
    required(value, 'research_execution', 'judgment_reviews')
    execution = value['research_execution']
    required(execution, 'status', 'reason')
    if execution['status'] not in ('completed', 'unavailable', 'not_run', 'unknown', 'excluded_by_user'):
        raise ValueError('Invalid deep research execution status')
    if not isinstance(execution['reason'], str) or not execution['reason'].strip():
        raise ValueError('Explain the actual execution status')
    doc_ids = []
    if execution['status'] == 'completed':
        required(execution, 'entrypoint', 'execution_document_id', 'result_document_id')
        if not isinstance(execution['entrypoint'], str) or not execution['entrypoint'].strip():
            raise ValueError('Record the actual host skill or tool entrypoint')
        doc_ids = [execution['execution_document_id'], execution['result_document_id']]
        if len(set(doc_ids)) != 2 or any(d not in documents for d in doc_ids):
            raise ValueError('Completed research needs stored execution evidence and returned result')
    reviews = value['judgment_reviews']
    if not isinstance(reviews, list):
        raise ValueError('Judgment reviews must be a list')
    by_id = {}
    for review in reviews:
        required(review, 'judgment_id', 'claim_level', 'source_fit', 'demand_supply', 'operational_link', 'comparison_basis')
        if review['judgment_id'] in by_id:
            raise ValueError('Duplicate judgment review')
        if review['claim_level'] not in ('context_only', 'constraint', 'operational'):
            raise ValueError('Invalid claim level')
        for field in ('demand_supply', 'operational_link', 'comparison_basis'):
            if not isinstance(review[field], str) or not review[field].strip():
                raise ValueError('Explain demand, usable supply, actual impact and comparable periods')
        by_id[review['judgment_id']] = review
    if set(by_id) != {r['judgment_id'] for r in rows}:
        raise ValueError('Review every current judgment, without unrelated reviews')
    for row in rows:
        review = by_id[row['judgment_id']]
        fits = review['source_fit']
        if not isinstance(fits, list):
            raise ValueError('Source fit must be a list')
        seen, direct, observed = set(), set(), set()
        for fit in fits:
            required(fit, 'evidence_id', 'source_scope', 'applicability', 'nature', 'reason')
            eid = fit['evidence_id']
            if eid in seen or eid not in row['support_ids'] + row['counter_ids']:
                raise ValueError('Source fit must cover linked evidence once')
            seen.add(eid)
            if fit['applicability'] not in ('direct', 'context'):
                raise ValueError('Unsupported evidence must be corrected before synthesis')
            for field in ('source_scope', 'reason'):
                if not isinstance(fit[field], str) or not fit[field].strip():
                    raise ValueError('Preserve original source population and mapping rationale')
            if fit['nature'] != evidence[eid]['nature']:
                raise ValueError('Nature review differs from evidence; correct evidence before synthesis')
            if fit['applicability'] == 'direct':
                direct.add(eid)
                if fit['nature'] == 'observation':
                    observed.add(eid)
        if seen != set(row['support_ids'] + row['counter_ids']):
            raise ValueError('Missing source applicability review')
        if review['claim_level'] != 'context_only' and not direct.intersection(row['support_ids']):
            raise ValueError('Context sources alone cannot establish a constraint in this scope')
        if review['claim_level'] == 'context_only':
            # Keep original judgments in the ledger; do not publish them as established physical constraints.
            raise ValueError('Context-only judgment: narrow/correct the claim or keep this segment unreviewed with a reason')
        if review['claim_level'] == 'operational':
            links = review.get('operational_source_ids', [])
            if not isinstance(links, list) or not links or not set(links) <= observed.intersection(row['support_ids']):
                raise ValueError('Actual operational impact needs directly applicable observations')
        if row['trend']['direction'] != 'unknown' and not set(row['trend'].get('evidence_ids', [])).intersection(observed):
            row['trend'].update(direction='unknown', label='추세 미확인', reason='같은 대상에 직접 적용되는 새 관측이 없어 변화를 판단하지 않았습니다.')
    return execution, reviews, doc_ids
