"""Parse software timing observations without converting them into RF timestamps."""
from pathlib import Path
import re
from .plan_analyze import fields, one
from .n3_holdover import distribution

BURST_STAGES=('call','stop_clear','cache_flush','dac_sync','submit_write','poll')
SLOT_STAGES=('generation','retune_secondary','retune_primary')


def tick(row,key):
    value=row[key]
    if not re.fullmatch('[0-9a-fA-F]{16}',value):
        raise ValueError(f'invalid 64-bit tick: {key}')
    return int(value,16)


def parse_timing(path,plan,allow_legacy=False):
    run=int(plan['stats']['run_id'])
    def matching(prefix):
        return [fields(line) for line in Path(path).read_text().splitlines()
                if line.startswith(prefix+' ') and fields(line).get('run_id')==str(run)]
    slot_rows={}
    for r in matching('CONTROL_PLAN_SLOT'):
        slot=int(r['slot'])
        slot_rows[slot]=dict(slot=slot,**{k:int(r[k]) if k in r else None for k in (
            'secondary_dma_late_us','auxptr_dma_delta_us','retune_secondary_us','dma_timeout','deadline_miss')})
    traces=matching('CONTROL_TIME_META')
    any_new=any(line.startswith('CONTROL_TIME_') and fields(line).get('run_id')==str(run)
                for line in Path(path).read_text().splitlines())
    if not traces:
        if any_new or not allow_legacy:
            raise ValueError('missing CONTROL_TIME_META; legacy data requires --allow-legacy-timing')
        return dict(status='legacy_missing_stages',slots=slot_rows,stages=[],meta=None)
    meta=one(traces,'CONTROL_TIME_META')
    if meta.get('schema')!='1' or meta.get('enabled')!='1':
        raise ValueError('unsupported or disabled N3 timing')
    end=one(matching('CONTROL_TIME_END'),'CONTROL_TIME_END')
    n=len(plan['slots']);hz=int(meta['tick_hz']);epoch=tick(meta,'epoch_ticks')
    if hz<=0 or int(meta['overflow']) or int(end['overflow']) or int(end['slots'])!=n or int(meta['slots_capacity'])<n:
        raise ValueError('N3 clock/capacity/overflow/end count invalid')
    raw_slots=matching('CONTROL_TIME_SLOT');late=matching('CONTROL_TIME_LATE')
    for records,label in ((raw_slots,'slot'),(late,'late')):
        if len(records)!=n or {int(r['slot']) for r in records}!=set(plan['slots']):
            raise ValueError(f'missing/duplicate N3 {label} rows')
    targets={};anchors={}
    interval=(hz*int(plan['stats']['period_ms'])+999)//1000
    aux_us=int(plan['stats']['aux_offset_us'])
    for r in raw_slots:
        slot=int(r['slot']);planned=tick(r,'planned_ticks');anchor=tick(r,'anchor_ticks');target=tick(r,'target_ticks')
        if planned!=epoch+slot*interval or r['anchor_valid'] not in ('0','1'):
            raise ValueError('plan tick or anchor validity mismatch')
        if r['anchor_valid']=='0':
            if anchor or target: raise ValueError('invalid anchor carries nonzero ticks')
            anchors[slot]=targets[slot]=None
        else:
            if anchor<epoch or target!=anchor+(hz*aux_us+999999)//1000000:
                raise ValueError('invalid software AuxOffset target')
            anchors[slot],targets[slot]=anchor,target
        slot_rows[slot].update({k:int(r[k]) for k in ('frame_us','mapping_us','gfsk_us')})
    kinds=(0,1,2,3) if plan['stats'].get('rf_mode')=='separate_secondary_ch3' else (0,1,3)
    expected={(s,k,stage) for s in plan['slots'] for k in kinds for stage in (SLOT_STAGES if k==3 else BURST_STAGES)}
    seen={};rows=[]
    for r in matching('CONTROL_TIME_STAGE'):
        slot,kind,stage=int(r['slot']),int(r['kind']),r['stage'];key=(slot,kind,stage)
        if key not in expected or key in seen: raise ValueError('duplicate/unknown N3 stage')
        valid=int(r['valid']);before,after=tick(r,'before_ticks'),tick(r,'after_ticks');status=int(r['status']);remaining=int(r['remaining_bytes'])
        if valid not in (0,1,3) or remaining<0: raise ValueError('invalid stage mask/remaining')
        if (not valid&1 and before) or (not valid&2 and after) or (valid&1 and before<epoch) or (valid==3 and after<before):
            raise ValueError('invalid stage timestamps/order')
        seen[key]=(before if valid&1 else None,after if valid&2 else None,status,remaining)
        # Integer subtraction first: never lose precision by floating large absolute ticks.
        row=dict(slot=slot,kind=kind,stage=stage,valid=valid,before_ticks=r['before_ticks'],after_ticks=r['after_ticks'],
                 before_us=(before-epoch)*1e6/hz if valid&1 else None,after_us=(after-epoch)*1e6/hz if valid&2 else None,
                 duration_us=(after-before)*1e6/hz if valid==3 else None,status=status if valid&2 else None,
                 remaining_bytes=remaining,first_submit_only=kind!=3,software_only=True)
        rows.append(row)
        slot_rows[slot][f'kind{kind}_{stage}_us']=row['duration_us']
        slot_rows[slot][f'kind{kind}_{stage}_status']=row['status']
    if set(seen)!=expected: raise ValueError('incomplete N3 stage matrix')
    burst_map={(int(r['slot']), {'primary':0,'secondary':1,'ieee':2}[r['kind']]):r
               for r in (plan.get('bursts') or {}).get('rows',[])}
    for slot in plan['slots']:
        for kind in kinds:
            if kind==3: continue
            cb,ca,call_status,_=seen[slot,kind,'call']
            observed=burst_map.get((slot,kind))
            if observed:
                if bool(observed['attempted']) != (cb is not None and ca is not None):
                    raise ValueError('N3 call bracket disagrees with burst attempt')
                if ca is not None and bool(observed['started']) != (call_status >= 0):
                    raise ValueError('N3 call status disagrees with burst start')
                pb,pa,ps,_=seen[slot,kind,'poll']
                if bool(observed['started']) != (pb is not None and pa is not None):
                    raise ValueError('N3 poll bracket disagrees with burst start')
                if pa is not None and bool(observed['completed']) != (ps >= 0):
                    raise ValueError('N3 poll status disagrees with burst completion')
            previous_end=cb
            for stage in BURST_STAGES[1:-1]:
                b,a,_,_=seen[slot,kind,stage]
                if b is not None and (cb is None or b<cb or (ca is not None and (a or b)>ca)):
                    raise ValueError('stage outside DMA call bracket')
                if b is not None and previous_end is not None and b < previous_end:
                    raise ValueError('DMA stage chronology invalid')
                if a is not None: previous_end=a
            pb,pa,_,_=seen[slot,kind,'poll']
            if pb is not None and (ca is None or pb<ca): raise ValueError('poll precedes DMA return')
        for stage in ('call','submit_write'):
            for endpoint,index in (('before',0),('after',1)):
                b=seen[slot,0,stage][index];s=seen[slot,1,stage][index]
                slot_rows[slot][f'primary_secondary_{stage}_{endpoint}_delta_us']=(s-b)*1e6/hz if b is not None and s is not None else None
                slot_rows[slot][f'primary_secondary_{stage}_{endpoint}_offset_error_us']=(s-b)*1e6/hz-aux_us if b is not None and s is not None else None
    for r in late:
        slot=int(r['slot']);target=targets[slot]
        for flag,key,stage,idx in (('call_valid','pre_call_us','call',0),('submit_valid','pre_submit_us','submit_write',0),('return_valid','post_return_us','call',1)):
            t=seen[slot,1,stage][idx];valid=target is not None and t is not None
            if r[flag] not in ('0','1') or int(r[flag])!=int(valid): raise ValueError('late validity mismatch')
            delta=t-target if valid else 0
            rounded=(abs(delta)*1000000//hz)*(1 if delta>=0 else -1)
            if int(r[key])!=rounded: raise ValueError('late value differs from raw ticks')
            slot_rows[slot][key]=delta*1e6/hz if valid else None
    return dict(status='complete_software_trace',meta=meta,slots=slot_rows,stages=rows)


def timing_distributions(timing):
    rows=[]
    keys=sorted({k for r in timing['slots'].values() for k in r if k.endswith('_us')})
    for k in keys:
        ordered=sorted(timing['slots'].items())
        vals=[r.get(k) for _,r in ordered]
        rows.append(dict(metric=k,scope='all_slots',missing=sum(v is None for v in vals),**distribution(vals)))
        diffs=[b[k]-a[k] for (s,a),(t,b) in zip(ordered,ordered[1:]) if t==s+1 and a.get(k) is not None and b.get(k) is not None]
        rows.append(dict(metric=k,scope='adjacent_slot_difference',missing=max(0,len(ordered)-1)-len(diffs),**distribution(diffs)))
    return rows
