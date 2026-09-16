"""Explicit interpretation review. Checks declarations; does not infer source meaning."""
from datetime import date


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def inspect(question, document, cutoff=None):
    issues = set()
    review = question.get('semantic_review')
    if not isinstance(review, dict):
        return {'missing_semantic_review'}
    for field in ('scope', 'interpretation', 'counterargument', 'residual_uncertainty', 'next_observation'):
        if not nonempty(review.get(field)):
            issues.add('incomplete_semantic_review')
    originals = []
    for index, source in enumerate(question.get('source_reviews', [])):
        if not isinstance(source,dict):
            issues.add('invalid_source_application');continue
        if source.get('role') in ('background', 'search_trace'):
            continue
        app = source.get('application', {})
        if not isinstance(app, dict) or not all(nonempty(app.get(k)) for k in
                ('source_population', 'target_population', 'scope_reason', 'time_reason')):
            issues.add('source_application_review_missing')
            continue
        if app.get('fit') not in ('direct', 'context', 'outside'):
            issues.add('invalid_source_population_fit')
        nature = app.get('nature')
        if nature not in ('observation', 'external_plan', 'external_forecast', 'inference', 'scenario'):
            issues.add('invalid_source_time_nature')
        use = app.get('time_use')
        if use not in ('current', 'historical', 'future', 'undated'):
            issues.add('invalid_source_time_use')
        if nature != 'observation' and use == 'current':
            issues.add('plan_or_forecast_is_not_current_realization')
        try:
            doc = document(source['document_id'])
            published = doc.get('metadata', {}).get('published_at')
            if cutoff and published and published > cutoff:
                issues.add('source_after_cutoff')
            if doc.get('metadata', {}).get('capture_kind') == 'search_trace' or doc['url'].startswith(('web-search:', 'web-open:')):
                issues.add('search_summary_is_not_original_review')
            else:
                originals.append(index)
            when = app.get('observation_date')
            if when:
                date.fromisoformat(when)
                if cutoff and use == 'current' and when > cutoff:
                    issues.add('future_event_is_not_observed')
            if use == 'current' and (not when or not nonempty(app.get('current_validity'))):
                issues.add('current_claim_needs_dated_observation_and_validity')
            if nature in ('external_plan', 'external_forecast') and app.get('target_date'):
                date.fromisoformat(app['target_date'])
        except (KeyError, TypeError, ValueError):
            issues.add('invalid_temporal_source_review')
    if not originals:
        issues.add('original_review_required_before_closure')
    if question['status'] == 'resolved':
        if not any(s.get('role') == 'direct' and s.get('application', {}).get('fit') == 'direct'
                   for s in question.get('source_reviews', [])):
            issues.add('context_population_cannot_resolve_target')
        if question['dimension'] in ('history', 'trend'):
            chronology = review.get('chronology', [])
            dates = set()
            for item in chronology if isinstance(chronology, list) else []:
                try:
                    date.fromisoformat(item['date'])
                    if item['source_review_index'] not in originals or not nonempty(item['event']):
                        raise ValueError()
                    if item.get('state') not in ('plan', 'revision', 'realization', 'observation'):
                        raise ValueError()
                    dates.add(item['date'])
                except (KeyError, TypeError, ValueError):
                    issues.add('invalid_chronology_reference')
            if len(dates) < 2:
                issues.add('history_or_trend_needs_distinct_dated_events')
    if question['status'] == 'bounded':
        gap = review.get('gap', {})
        if not isinstance(gap, dict) or not all(nonempty(gap.get(k)) for k in
                ('public_data_limit', 'why_remaining_search_would_not_change_answer', 'reopen_when')):
            issues.add('gap_closure_review_missing')
        else:
            leads = gap.get('leads')
            if not isinstance(leads, list) or not leads:
                issues.add('gap_alternative_leads_not_reviewed')
            else:
                for lead in leads:
                    if not isinstance(lead, dict) or not nonempty(lead.get('route')) or not nonempty(lead.get('reason')):
                        issues.add('invalid_gap_lead')
                        continue
                    if lead.get('disposition') not in ('investigated', 'unavailable', 'not_material'):
                        issues.add('promising_lead_remains_open')
                    if lead.get('disposition') == 'investigated' and not any(
                            a['route'] == lead['route'] and a['outcome'] in ('found', 'irrelevant')
                            for a in question['attempts']):
                        issues.add('gap_lead_has_no_source_attempt')
    return issues


def justified_shared_source(question):
    """A reuse review permits common bytes, never duplicate conclusions."""
    semantic = question.get('semantic_review', {})
    reuse = semantic.get('shared_source_review', {}) if isinstance(semantic,dict) else {}
    return isinstance(reuse, dict) and all(nonempty(reuse.get(k)) for k in
            ('node_specific_application', 'different_from_other_nodes', 'limitations'))
