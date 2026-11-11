"""Explicit N3 holdover policies. Probes score frozen historical models only."""
from __future__ import annotations
import math
import statistics
from .sync_replay import quantile

SIDES = ('ble', 'zigbee')


def spaced(pool, n):
    if n > len(pool) or n < 1:
        raise ValueError('insufficient candidate span')
    return [pool[-1]] if n == 1 else [pool[(i * (len(pool)-1)) // (n-1)] for i in range(n)]


def default_config(slots=300, period_ms=500, exploratory=False):
    if slots <= 69 or period_ms != 500:
        raise ValueError('preset requires >69 slots and period 500 ms; custom JSON supports other plans')
    policies = []
    def add(name, n, span=60, interval=None, mask=None):
        initial = {side: spaced(list(range(60-span+parity, 60, 2)), n)
                   for parity, side in enumerate(SIDES)}
        updates = {side: list(range(60+parity, slots, interval)) if interval else []
                   for parity, side in enumerate(SIDES)}
        policies.append(dict(name=name, model='offset' if n == 1 else 'affine', n=n,
                             initial=initial, updates=updates, mask=mask or []))
    add('offset', 1)
    for n in (2, 4, 8, 16):
        add(f'freeze_n{n}', n)
    for span in (20, 40):
        add(f'freeze_n8_span{span//2}s', 8, span)
    for interval in (2, 10, 20):
        add(f'update_{interval//2}s', 8, interval=interval)
    if slots >= 180:
        for width in (10, 30, 60):
            add(f'update_1s_mask{width//2}s', 8, interval=2, mask=list(range(120,120+width)))
    probes = list(range(69, slots, 10))
    for p in policies:
        p['updates'] = {side: [s for s in p['updates'][side] if s not in probes] for side in SIDES}
    return dict(schema='b2z_n3_config_v1', exploratory=exploratory, period_ms=period_ms,
                slots=list(range(slots)), probes=probes, policies=policies,
                ieee_marker_offset_us=472, thresholds_us=[10000,50000,100000])


def validate_config(c):
    if c.get('schema') != 'b2z_n3_config_v1' or type(c.get('exploratory')) is not bool:
        raise ValueError('invalid N3 config schema/exploratory flag')
    def unique(values):
        return isinstance(values,list) and all(type(x) is int and x >= 0 for x in values) and len(set(values)) == len(values)
    if not unique(c['slots']) or c['slots'] != list(range(len(c['slots']))) or not c['slots']:
        raise ValueError('slots must explicitly cover consecutive plan slots')
    if not unique(c['probes']) or not c['probes'] or not set(c['probes']) <= set(c['slots']):
        raise ValueError('invalid probes')
    if type(c['period_ms']) is not int or c['period_ms'] <= 0 or c['ieee_marker_offset_us'] != 472:
        raise ValueError('invalid period or unsupported joint marker offset')
    if not c['thresholds_us'] or any(not math.isfinite(v) or v <= 0 for v in c['thresholds_us']):
        raise ValueError('invalid thresholds')
    names = set()
    for p in c['policies']:
        if p['name'] in names or not p['name'] or p['model'] not in ('offset','affine'):
            raise ValueError('invalid policy identity/model')
        names.add(p['name'])
        if type(p['n']) is not int or p['n'] < (1 if p['model']=='offset' else 2):
            raise ValueError('invalid training size')
        if p['model']=='offset' and p['n'] != 1:
            raise ValueError('offset model requires one anchor')
        if not unique(p['mask']) or not set(p['mask']) <= set(c['slots']):
            raise ValueError('invalid update mask')
        for side in SIDES:
            initial, updates = p['initial'][side], p['updates'][side]
            if not unique(initial) or not unique(updates) or len(initial)!=p['n']:
                raise ValueError('invalid training list')
            if set(initial) & set(updates) or set(initial+updates) & set(c['probes']):
                raise ValueError('training/probe overlap')
            if not set(initial+updates) <= set(c['slots']) or max(initial) >= min(c['probes']):
                raise ValueError('initial history must precede evaluation')
    if not names:
        raise ValueError('no policies')


def distribution(values):
    values = [float(v) for v in values if v is not None and math.isfinite(v)]
    if not values:
        return dict(n=0, min=None, median=None, p95=None, p99=None, max=None, mean=None,
                    median_abs=None, p95_abs=None, p99_abs=None, max_abs=None)
    return dict(n=len(values), min=min(values), median=quantile(values,.5), p95=quantile(values,.95),
                p99=quantile(values,.99), max=max(values), mean=statistics.fmean(values),
                **{f'{name}_abs': fun([abs(v) for v in values]) for name,fun in (
                    ('median',lambda x:quantile(x,.5)),('p95',lambda x:quantile(x,.95)),
                    ('p99',lambda x:quantile(x,.99)),('max',max))})


def age_bin(ms):
    for lo,hi in ((0,10000),(10000,30000),(30000,60000),(60000,120000)):
        if lo <= ms < hi:
            return f'[{lo/1000:g},{hi/1000:g})s'
    return '>=120s' if ms >= 120000 else 'negative'


def evaluate(c, streams, rates):
    validate_config(c)
    rows = []
    for p in c['policies']:
        for slot in c['probes']:
            row = dict(policy=p['name'], slot=slot, planned_ms=slot*c['period_ms'], relative_error_us=None)
            estimates = {}
            for side in SIDES:
                events = streams[side]
                probe = events.get(slot)
                prefix = side+'_'
                row.update({prefix+k:v for k,v in dict(observed=probe is not None,status='probe_missing',
                    training_slots=[], n=0, span_ms=None, update_age_ms=None, age_bin=None,
                    slope_ppm=None,residual_us=None,estimated_ms=None,anchor_slot=None,
                    anchor_sample=None,slope_samples_per_ms=None).items()})
                if probe is None:
                    continue
                # Score cutoff is packet start, never decoder availability (which can be later).
                # No probe content/time is fitted. Each receiver uses only its own history.
                candidates = [s for s in p['initial'][side]+p['updates'][side]
                              if s < slot and s not in p['mask'] and s in events and
                              events[s]['available_sample'] < probe['sample_start']]
                if p['updates'][side]:
                    candidates.sort(key=lambda s:(events[s]['available_sample'],s))
                    selected = candidates[-p['n']:]
                else:
                    selected = [s for s in p['initial'][side] if s in candidates]
                selected.sort()
                row[prefix+'training_slots'] = selected
                row[prefix+'n'] = len(selected)
                if len(selected) < p['n']:
                    row[prefix+'status'] = 'training_missing_or_unavailable'
                    continue
                anchor = selected[-1]
                marker_offset = 0 if side=='ble' else c['ieee_marker_offset_us']*rates[side]/1e6
                anchor_x = events[anchor]['sample_start']-marker_offset
                ts = [(s-anchor)*c['period_ms'] for s in selected]
                xs = [events[s]['sample_start']-marker_offset-anchor_x for s in selected]
                mt,mx = statistics.fmean(ts),statistics.fmean(xs)
                slope = rates[side]/1000 if p['model']=='offset' else sum((t-mt)*(x-mx) for t,x in zip(ts,xs))/sum((t-mt)**2 for t in ts)
                if not .99 < slope/(rates[side]/1000) < 1.01:
                    row[prefix+'status'] = 'implausible_rate'
                    continue
                intercept = mx-slope*mt
                observed = probe['sample_start']-marker_offset-anchor_x
                predicted = intercept+slope*(slot-anchor)*c['period_ms']
                estimate = anchor*c['period_ms']+(observed-intercept)/slope
                age = (slot-anchor)*c['period_ms']
                row.update({prefix+k:v for k,v in dict(status='scored',span_ms=(max(selected)-min(selected))*c['period_ms'],
                    update_age_ms=age,age_bin=age_bin(age),slope_ppm=(slope/(rates[side]/1000)-1)*1e6,
                    residual_us=(observed-predicted)*1e6/rates[side],estimated_ms=estimate,
                    anchor_slot=anchor,anchor_sample=anchor_x+intercept,slope_samples_per_ms=slope).items()})
                estimates[side] = estimate
            if len(estimates)==2:
                row['relative_error_us'] = (estimates['ble']-estimates['zigbee'])*1000
            rows.append(row)
    summary=[]
    for p in c['policies']:
        subset=[r for r in rows if r['policy']==p['name']]
        for metric in ('ble_residual_us','zigbee_residual_us','relative_error_us'):
            vals=[r[metric] for r in subset if r[metric] is not None]
            summary.append(dict(policy=p['name'],metric=metric,planned_probes=len(subset),missing_or_unscored=len(subset)-len(vals),
                **distribution(vals),thresholds=[dict(threshold_us=t,numerator=sum(abs(v)<=t for v in vals),
                    planned_denominator=len(subset),conditional_denominator=len(vals)) for t in c['thresholds_us']]))
    return rows,summary
