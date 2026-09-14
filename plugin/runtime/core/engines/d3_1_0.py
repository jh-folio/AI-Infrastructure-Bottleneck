"""Protocol 3.1 / Scoring 3.1 arithmetic on adopted, reviewed factors only."""
from decimal import Decimal
import math

VERSION = '3.1'
ENGINE = 'd3-1.0'
WEIGHTS = dict(shortage=15, access=15, elasticity=15, build=10, demand=10,
               substitution=5, system_criticality=15, regulatory=10, concentration=5)
AXES = {'severity': ['shortage', 'access'],
        'persistence': ['elasticity', 'build', 'demand', 'substitution'],
        'criticality': ['system_criticality', 'regulatory', 'concentration']}
CORE = ('shortage', 'access', 'system_criticality')


def calculate(inputs):
    if inputs.get('methodology_version') != VERSION:
        raise ValueError('Only Scoring 3.1 is implemented')
    factors = inputs['factors']
    if set(factors) != set(WEIGHTS):
        raise ValueError('Provide all nine factor states explicitly')
    confidence = inputs['confidence']
    if confidence not in ('Low', 'Medium', 'High') or not inputs.get('confidence_reason'):
        raise ValueError('Confidence and explanation required')
    bounds, grades, na = {}, {}, False
    for name, f in factors.items():
        status = f['status']
        if status in ('Unknown', 'ResearchMissing', 'N/A'):
            if f.get('low') is not None or f.get('high') is not None:
                raise ValueError('Unknown/Missing/N/A must not contain numeric observed bounds')
            bounds[name] = (Decimal(0), Decimal(5)) if status != 'N/A' else (None, None)
            grades[name] = None
            na |= status == 'N/A'
        elif status == 'EvidenceBounded':
            if f.get('grade') not in ('A', 'B', 'C', 'D'):
                raise ValueError('Invalid evidence grade')
            for key in ('low', 'high'):
                v = f[key]
                if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
                    raise ValueError('Finite numeric bounds required')
            lo, hi = Decimal(str(f['low'])), Decimal(str(f['high']))
            if not 0 <= lo <= hi <= 5:
                raise ValueError('Factor bounds out of range')
            if not all(f.get(k) for k in ('evidence_ids', 'reason_low', 'reason_high', 'mechanism')):
                raise ValueError('Endpoints and evidence must be justified')
            if f['grade'] == 'D' and (lo == 0 or hi == 5):
                raise ValueError('D-only evidence cannot justify extreme endpoints')
            bounds[name], grades[name] = (lo, hi), f['grade']
        else:
            raise ValueError('Unknown factor status')
    unknown = sum(WEIGHTS[k] for k, f in factors.items() if f['status'] in ('Unknown', 'ResearchMissing'))
    if unknown and confidence != 'Low':
        raise ValueError('D3 requires Low confidence with unknown factors; exception needs separate validated robustness contract')
    ab = sum(WEIGHTS[k] for k, g in grades.items() if g in ('A', 'B'))
    abc = sum(WEIGHTS[k] for k, g in grades.items() if g in ('A', 'B', 'C'))
    axis_coverage = {axis: sum(WEIGHTS[k] for k in names if grades[k] in ('A', 'B', 'C')) / sum(WEIGHTS[k] for k in names) for axis, names in AXES.items()}
    values = {}
    for axis, names in AXES.items():
        if any(bounds[k][0] is None for k in names):
            values[axis] = {'low': None, 'high': None, 'mid': None}
        else:
            lo, hi = [sum(Decimal(WEIGHTS[k]) * bounds[k][i] / 5 for k in names) * 100 / sum(WEIGHTS[k] for k in names) for i in (0, 1)]
            values[axis] = {'low': float(lo), 'high': float(hi), 'mid': None if any(grades[k] is None for k in names) else float((lo+hi)/2)}
    low, high = (None, None) if na else tuple(sum(Decimal(WEIGHTS[k]) * bounds[k][i] / 5 for k in WEIGHTS) for i in (0, 1))
    independent = inputs.get('independent_producers', 0) >= 2 and inputs.get('tier12_present') is True
    coherent = inputs.get('scope_coherent') is True
    conflicts = inputs.get('conflicts')
    fully = (not na and unknown == 0 and ab >= 70 and abc >= 90
             and all(grades[k] in ('A', 'B') for k in CORE) and independent and coherent
             and conflicts == 'resolved' and high-low <= 10 and confidence in ('Medium', 'High'))
    provisional = (not na and abc >= 60 and min(axis_coverage.values()) >= .4 and unknown <= 20
                   and all(grades[k] in ('A', 'B', 'C') for k in CORE) and independent and coherent
                   and conflicts in ('resolved', 'bounded') and high-low <= 25)
    scoreability = ('Fully Scorable' if fully else 'Provisionally Scorable' if provisional else
                    'Directionally Assessable' if inputs.get('direction_evidence_ids') else 'Not Scorable')
    tiers = set()
    if fully or provisional:
        # Continuous intervals: Tier2/3/4 feasibility depends on overall interval.
        if low < 45:
            tiers.add(4)
        if high >= 45 and low < 60:
            tiers.add(3)
        if high >= 60:
            tiers.add(2)
        eligible = inputs.get('tier1_core_evidence_qualified') is True and confidence in ('Medium', 'High')
        def tier1(i):
            return eligible and (low if i == 0 else high) >= 75 and values['criticality'][('low','high')[i]] >= 70 and bounds['system_criticality'][i] >= 4 and bounds['shortage'][i] >= 3
        if tier1(1):
            tiers.add(1)
        if tier1(0):
            tiers = {1}
    return {'methodology_version': VERSION, 'engine_version': ENGINE, 'axes': values,
            'overall': {'low': None if low is None else float(low), 'high': None if high is None else float(high),
                        'mid': None if na or unknown else float((low+high)/2)},
            'range_provenance': 'NotApplicable' if na else 'UnknownBounded' if unknown == 100 else 'Mixed' if unknown else 'EvidenceBounded',
            'coverage_AB': ab / 100, 'coverage_ABC': abc / 100, 'unknown_weight': unknown / 100,
            'inference_weight': sum(WEIGHTS[k] for k, g in grades.items() if g == 'D') / 100,
            'axis_coverage': axis_coverage, 'confidence': confidence, 'scoreability': scoreability,
            'tier_confirmed': next(iter(tiers)) if len(tiers) == 1 else None, 'possible_tiers': sorted(tiers),
            'tier_basis': 'conservative outer interval candidates', 'binding_status': inputs.get('binding_status', 'NotDemonstrated')}


def compare(old, new):
    dimensions = ('node_id', 'geography', 'product_spec', 'scenario', 'horizon', 'protocol_version', 'methodology_version')
    if any(old['scope'].get(k) != new['scope'].get(k) for k in dimensions):
        return {'comparable': False, 'reason': 'scope_or_method_changed', 'delta': None}
    if new.get('change_cause') != 'new_observation':
        return {'comparable': False, 'reason': 'not_an_observed_industry_change', 'delta': None}
    return {'comparable': True, 'delta': None, 'reason': 'compare supported bounds and evidence; no midpoint momentum inferred'}
