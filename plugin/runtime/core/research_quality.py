"""Source-backed completion checks, not an automated research-quality verdict."""
from collections import defaultdict
from functools import lru_cache
import re
import unicodedata

from extraction import locate, segments
from research import data


def normalized(value, labels=()):
    value=unicodedata.normalize('NFKC', str(value)).casefold()
    for label in sorted(labels,key=len,reverse=True):
        value=value.replace(str(label).casefold(),' ')
    return re.sub(r'[\W_]+','',value)


def inspect_questions(store, nodes, questions, cutoff=None):
    """Read referenced bytes. Preserve old ledgers; return work for invalid closures."""
    active={n['node_id'] for n in nodes if n.get('lifecycle','active')=='active'}
    labels=[str(n[k]) for n in nodes for k in ('node_id','name') if n.get(k)]
    issues=defaultdict(set);packets=defaultdict(list);prose=defaultdict(list);dimension_reviews=defaultdict(list)
    document=lru_cache(None)(store.document)
    record=lru_cache(None)(lambda rid: data(store,rid))
    blocks=lru_cache(None)(lambda rid: {b['location']:b['text'] for b in segments(document(rid))[0]})
    excerpt=lru_cache(None)(lambda rid,loc: locate(document(rid),loc) if loc.startswith('/') else blocks(rid)[loc])
    closed=[q for q in questions if q['node_id'] in active and q['status'] in ('resolved','bounded')]
    for q in closed:
        qid=q['id'];reviews=q.get('source_reviews',[]);usable=[];routes=set();direct=[]
        from semantic_review import inspect
        issues[qid].update(inspect(q,document,cutoff))
        if not isinstance(reviews,list) or not reviews:
            issues[qid].add('missing_source_reviews');continue
        attempt_docs={d for a in q['attempts'] for d in a.get('document_ids',[])}
        for review in reviews:
            try:
                keys=('document_id','location','quote','finding','relevance','role')
                if not all(isinstance(review.get(k),str) and review[k].strip() for k in keys):
                    raise ValueError('empty review')
                role=review['role']
                if role not in ('direct','gap_probe','search_trace','background'):
                    raise ValueError('invalid review role')
                doc=document(review['document_id'])
                if doc['id'] not in attempt_docs:raise ValueError('review is not in attempted sources')
                if review['quote'] not in excerpt(doc['id'],review['location']):
                    raise ValueError('quote not at source location')
                if role=='background':continue
                if role=='search_trace':
                    if not isinstance(review.get('query'),str) or not review['query'].strip():
                        raise ValueError('search query missing')
                    if review['query'] not in excerpt(doc['id'],review['location']):
                        raise ValueError('query not in saved tool output')
                # Compare actual excerpts, not IDs/URLs that can be relabeled.
                signature=normalized(review['quote'],labels)
                if not signature:raise ValueError('empty source content')
                usable.append(signature)
                routes.add((doc['sha256'],review.get('query','')))
                if role=='direct':direct.append(review)
            except (ValueError,KeyError,TypeError,IndexError):
                issues[qid].add('invalid_source_review')
        if not usable:issues[qid].add('background_only_or_unread_sources')
        if q['status']=='bounded':
            # Failed access alone is blocked, not a conclusion about unavailable evidence.
            if len(routes)<2:issues[qid].add('gap_needs_actual_alternative_search')
            if not any(a['outcome'] in ('found','irrelevant') for a in q['attempts']):
                issues[qid].add('access_failure_is_not_bounded_research')
        else:
            supported=set()
            for rid in q.get('judgment_ids',[]):
                judgment=record(rid)
                for eid in judgment.get('support_ids',[]):
                    ev=record(eid)
                    if ev.get('decision')=='accepted' and ev.get('scope',{}).get('node_id')==q['node_id']:
                        supported.add((ev['document_id'],ev['location'],ev['quote']))
                        for source in direct:
                            if (source['document_id'],source['location'],source['quote']) == (ev['document_id'],ev['location'],ev['quote']):
                                if source.get('application',{}).get('nature') != ev['nature']:
                                    issues[qid].add('source_nature_differs_from_adopted_evidence')
            if not any((r['document_id'],r['location'],r['quote']) in supported for r in direct):
                issues[qid].add('resolution_not_linked_to_reviewed_support')
        if usable:packets[tuple(sorted(set(usable)))].append(q)
        # A short repeated Unknown label is fine; repeating the full review is not.
        body=' '.join(str(q.get(k,'')) for k in ('answer','closure_reason','remaining_uncertainty','why_more_search_unlikely'))
        key=normalized(body,labels)
        if key:prose[key].append(q)
        review_text=' '.join(str(r.get('finding',''))+' '+str(r.get('relevance','')) for r in reviews)
        dimension_reviews[(q['node_id'],normalized(body+' '+review_text,labels))].append(q)
    for groups,reason in ((packets,'reused_source_packet_across_nodes'),(prose,'repeated_conclusion_across_nodes')):
        for group in groups.values():
            if len({q['node_id'] for q in group})>1:
                for q in group:
                    from semantic_review import justified_shared_source
                    if reason == 'reused_source_packet_across_nodes' and justified_shared_source(q):
                        continue
                    issues[q['id']].add(reason)
    for group in dimension_reviews.values():
        if len({q['dimension'] for q in group})>1:
            for q in group:issues[q['id']].add('repeated_review_across_dimensions')
    return [dict(node_id=q['node_id'],question_id=q['id'],dimension=q['dimension'],
                 action='review_question_sources',reasons=sorted(issues[q['id']]))
            for q in closed if issues[q['id']]]


def completion(store,campaign_id,report_id=None):
    """Read-only delivery check. Passing means reviewable, never user acceptance."""
    from research_loop import resume
    state=resume(store,campaign_id)
    reasons=[]
    if not state['ready_for_review']:reasons.append('research_incomplete')
    if report_id is None:reasons.append('baseline_review_report_required')
    else:
        report=data(store,report_id,'report')
        if report.get('research_stage')!='baseline_review':reasons.append('interim_does_not_fulfill_request')
        if report.get('campaign_id')!=campaign_id or report.get('checkpoint_id')!=state['checkpoint_id']:
            reasons.append('report_does_not_match_current_research')
        if report.get('research_execution',{}).get('status') not in ('completed','excluded_by_user'):
            reasons.append('research_execution_missing')
        if report.get('research_quality_version')!=2:reasons.append('report_needs_current_quality_review')
    ready=not reasons
    return {'campaign_id':campaign_id,'checkpoint_id':state['checkpoint_id'],'report_id':report_id,
            'ready_to_submit':ready,'reasons':reasons,'pending_count':len(state['pending']),
            'next_actions':state['pending'][:10],
            'instruction':('Review source meaning and reader clarity before submitting for user review.' if ready else
                           'Continue this execution. Internal interim saves do not complete the first-report request.'),
            'boundary':'Checks source references and repeated content; cannot authenticate host execution or certify interpretation.'}
