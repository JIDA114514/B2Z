#!/usr/bin/env python3
"""N3 fixed-IQ holdover and board software-timing audit; never RF synchronization accuracy."""
from __future__ import annotations
import argparse
import json
import math
from pathlib import Path
import sys
import tempfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from control_match.analyze import capture_interval, discover
from control_match.plan_analyze import read_plan, load_side, summarize
from control_match.holdover_analyze import sha256, write_csv
from control_match.n3_holdover import default_config, validate_config, evaluate, distribution, SIDES
from control_match.n3_timing import parse_timing, timing_distributions


def load_inputs(root,run,config,board,paths):
    validate_config(config)
    plan=read_plan(board,run)
    if plan['stats'].get('rf_mode') not in ('standard_secondary_ch3','same_channel_diagnostic'):
        raise ValueError('holdover requires joint waveform; separate transmission has no common RF marker')
    if list(plan['slots'])!=config['slots'] or int(plan['stats']['period_ms'])!=config['period_ms']:
        raise ValueError('config slot list/period differs from board plan')
    commands={int(t['command_id']) for t in plan['tasks']}
    sides={};receivers={};rates={};sources={'board':board}
    intervals=[]
    for side in SIDES:
        path=paths.get(side) or discover(root,side)
        if path is None: raise ValueError(f'missing {side} capture')
        sources[side]=path; intervals.append(capture_interval(path))
        summary_path=path.with_name('rx.summary.json');sources[side+'_summary']=summary_path
        receiver=json.loads(summary_path.read_text());receivers[side]=receiver
        if receiver.get('status')!='complete' or receiver.get('error'):
            raise ValueError(f'{side} capture incomplete')
        rate=receiver['config']['sample_rate'];total=receiver['counts']['samples_processed']
        if type(rate) is not int or rate<=0 or receiver['config'].get('control_layout','joint')!='joint':
            raise ValueError('invalid sample rate/layout')
        rates[side]=rate;sides[side]=load_side(path,side,run,commands)
        raw=[json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        for slot,e in sides[side]['by_slot'].items():
            if e['record']['period_ms']!=config['period_ms']:
                raise ValueError('decoded period differs from frozen config')
            start,available=e['sample_start'],e['available_sample']
            if (not isinstance(start,(float,int)) or not math.isfinite(start) or
                type(available) is not int or not 0<=start<=available<=total):
                raise ValueError('missing/invalid sample or availability; re-decode saved IQ, never infer it')
            packet=raw[e['line_no']-1]
            e['quality']={k:packet.get(k) for k in ('sync_score','preamble_distance','mean_chip_distance','clock_search_ppm','decode_method','cfo_hz','estimated_cfo_hz')}
        ordered=sorted(sides[side]['by_slot'].items())
        if any(b['sample_start']<=a['sample_start'] for (_,a),(_,b) in zip(ordered,ordered[1:])):
            raise ValueError('nonmonotonic packet sample markers')
    if max(a for a,b in intervals)>=min(b for a,b in intervals):
        raise ValueError('receiver capture windows do not overlap')
    integrity,slots,tasks=summarize(plan,sides['ble'],sides['zigbee'])
    return plan,sides,rates,receivers,sources,integrity


def diagnostics(streams,rates,config,timing,validation):
    qc=[]
    for side in SIDES:
        last=None
        for slot,e in sorted(streams[side].items()):
            row=dict(side=side,slot=slot,sample_start=e['sample_start'],available_sample=e['available_sample'],
                     decode_available_us=(e['available_sample']-e['sample_start'])*1e6/rates[side],**e.get('quality',{}))
            row['interval_deviation_us']=None
            if last:
                s,prior=last
                row['previous_slot']=s
                row['interval_deviation_us']=(e['sample_start']-prior['sample_start'])*1e6/rates[side]-(slot-s)*config['period_ms']*1000
            qc.append(row);last=slot,e
    qcmap={(r['side'],r['slot']):r for r in qc}
    joined=[]
    for r in validation:
        row={**timing['slots'][r['slot']],**r}
        for side in SIDES:
            q=qcmap.get((side,r['slot']),{})
            for k in ('interval_deviation_us','decode_available_us','sync_score','preamble_distance','mean_chip_distance','clock_search_ppm'):
                row[side+'_'+k]=q.get(k)
        joined.append(row)
    # Descriptive only: no causal claim, no per-slot delay subtraction.
    from scipy.stats import spearmanr
    associations=[]
    predictors=sorted({k for r in timing['slots'].values() for k in r if k.endswith('_us')})
    for policy in config['policies']:
        chosen=[r for r in joined if r['policy']==policy['name']]
        for predictor in predictors:
            for metric in ('ble_residual_us','zigbee_residual_us','relative_error_us'):
                pairs=[(r[predictor],r[metric]) for r in chosen if r.get(predictor) is not None and r.get(metric) is not None]
                x=[a for a,b in pairs];y=[b for a,b in pairs]
                rho=float(spearmanr(x,y).statistic) if len(pairs)>=3 and len(set(x))>1 and len(set(y))>1 else None
                associations.append(dict(policy=policy['name'],predictor=predictor,metric=metric,n=len(pairs),
                                         missing=len(chosen)-len(pairs),spearman_rho=rho))
    ages=[]
    for p in config['policies']:
        for side in SIDES:
            for label in ('[0,10)s','[10,30)s','[30,60)s','[60,120)s','>=120s'):
                vals=[r[side+'_residual_us'] for r in validation if r['policy']==p['name'] and r[side+'_age_bin']==label]
                ages.append(dict(policy=p['name'],side=side,age_bin=label,**distribution(vals)))
    return qc,joined,associations,ages


def plots(output,rows,timing):
    import os
    os.environ.setdefault('MPLCONFIGDIR',str(Path(tempfile.gettempdir())/'b2z_mpl_cache'))
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(1,3,figsize=(15,4))
    for ax,metric in zip(axes,('ble_residual_us','zigbee_residual_us','relative_error_us')):
        for policy in dict.fromkeys(r['policy'] for r in rows):
            vals=sorted(abs(r[metric])/1000 for r in rows if r['policy']==policy and r[metric] is not None)
            if vals: ax.step(vals,[(i+1)/len(vals) for i in range(len(vals))],where='post',label=policy)
        ax.set(xlabel='Absolute error (ms)',ylabel='Conditional ECDF',title=metric);ax.grid(alpha=.3)
    if axes[0].lines: axes[0].legend(fontsize=6)
    fig.tight_layout();fig.savefig(output/'holdover.cdf.png',dpi=150);plt.close(fig)
    fig,axes=plt.subplots(1,2,figsize=(12,4))
    for ax,side in zip(axes,SIDES):
        for policy in dict.fromkeys(r['policy'] for r in rows):
            sub=[r for r in rows if r['policy']==policy and r[side+'_residual_us'] is not None]
            if sub: ax.plot([r[side+'_update_age_ms']/1000 for r in sub],[r[side+'_residual_us']/1000 for r in sub],'.',label=policy)
        ax.set(xlabel='Update age (s)',ylabel='Signed residual (ms)',title=side);ax.grid(alpha=.3)
    fig.tight_layout();fig.savefig(output/'holdover.age.png',dpi=150);plt.close(fig)
    fig,ax=plt.subplots(figsize=(10,4))
    for key in ('secondary_dma_late_us','pre_call_us','pre_submit_us','post_return_us'):
        sub=[r for r in timing['slots'].values() if r.get(key) is not None]
        if sub: ax.plot([r['slot'] for r in sub],[r[key]/1000 for r in sub],label=key)
    ax.set(xlabel='Slot',ylabel='Software proxy delay (ms)',title='Different reference definitions; not RF timing')
    if ax.lines: ax.legend()
    fig.tight_layout();fig.savefig(output/'timing.trace.png',dpi=150);plt.close(fig)


def run_analysis(root,run,config_path,board,paths,output,allow_legacy=False):
    if output.exists(): raise ValueError(f'output exists: {output}')
    config=json.loads(config_path.read_text())
    plan,sides,rates,receivers,sources,integrity=load_inputs(root,run,config,board,paths)
    timing=parse_timing(board,plan,allow_legacy)
    streams={side:sides[side]['by_slot'] for side in SIDES}
    rows,stats=evaluate(config,streams,rates)
    qc,joined,associations,ages=diagnostics(streams,rates,config,timing,rows)
    sources['config']=config_path
    result=dict(schema='b2z_n3_analysis_v1',run_id=run,exploratory=config['exploratory'],config=config,
        timing_status=timing['status'],timing_meta=timing['meta'],sample_rates=rates,summary=stats,
        integrity=integrity,receiver_quality={s:{k:receivers[s].get(k) for k in ('status','error','capture_returncode','capture_stats','counts','limitations')} for s in SIDES},
        sources={k:dict(path=str(v.resolve()),sha256=sha256(v)) for k,v in sources.items()},
        analysis_sources={p.name:sha256(p) for p in Path(__file__).parent.glob('n3_*.py')},
        limitations=['Offline replay; training masks are simulated loss, not new RF experiments.',
            'Independent sample origins are not subtracted or realigned per probe.',
            'Relative prediction is not absolute clock synchronization or actuator accuracy.',
            'No detected queue error does not establish gap-free IQ.',
            'Software timing correlation does not identify actual RF start or unique cause.',
            'Missing probes cannot bound error during loss; small n cannot establish tail guarantees.'])
    output.mkdir(parents=True)
    for name,data in [('holdover.validation',rows),('holdover.summary',stats),('holdover.age',ages),('timing.stages',timing['stages']),
                      ('timing.slots',list(timing['slots'].values())),('timing.summary',timing_distributions(timing)),
                      ('timing.qc',qc),('timing.joined',joined),('timing.associations',associations)]:
        write_csv(output/(name+'.csv'),data)
    (output/'config.json').write_text(json.dumps(config,ensure_ascii=False,indent=2)+'\n')
    plots(output,rows,timing)
    (output/'n3.summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    lines=['# N3 相对预测与软件取时分析','',f'Run {run}；探索性分析：{config["exploratory"]}；取时：{timing["status"]}。',
           f'计划 {len(config["slots"])} 槽，预定探测 {len(config["probes"])} 槽；BLE/IEEE有效 {len(streams["ble"])}/{len(streams["zigbee"])}。',
           '', '|策略|相对差有效/计划|绝对差中位数 µs|P95 µs|最大 µs|','|---|---:|---:|---:|---:|']
    for r in stats:
        if r['metric']=='relative_error_us':
            fmt=lambda x:'N/A' if x is None else f'{x:.3f}'
            lines.append(f'|{r["policy"]}|{r["n"]}/{r["planned_probes"]}|{fmt(r["median_abs"])}|{fmt(r["p95_abs"])}|{fmt(r["max_abs"])}|')
    lines += ['', '![CDF](holdover.cdf.png)','![更新年龄](holdover.age.png)','![软件取时](timing.trace.png)','',
              '单侧残差、模型训练槽、更新年龄、阈内计数和缺失数见 CSV/JSON。冻结配置中的探测包不会更新模型。',
              '原始 tick 先以整数相减再转换；历史缺失阶段保持缺失，不能用平均值回填。',
              '此结果不是绝对同步、RF AuxPtr精度或物理执行证据；小样本 P99 不构成尾部保证。']
    (output/'n3.report.md').write_text('\n'.join(lines)+'\n')
    print(f'run={run} timing={timing["status"]} probes={len(config["probes"])} output={output}')
    return result


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--write-config',type=Path,help='create an explicit preset before capture; never overwrite')
    p.add_argument('--slots',type=int,default=300)
    p.add_argument('--period-ms',type=int,default=500)
    p.add_argument('--exploratory',action='store_true',help='preset is for already-observed data')
    p.add_argument('--config',type=Path)
    p.add_argument('--experiment-dir',type=Path)
    p.add_argument('--run-id',type=int)
    p.add_argument('--board-log',type=Path)
    p.add_argument('--ble-packets',type=Path)
    p.add_argument('--zigbee-packets',type=Path)
    p.add_argument('--output-dir',type=Path)
    p.add_argument('--allow-legacy-timing',action='store_true',help='explicitly allow old logs with no N3 stages')
    a=p.parse_args(argv)
    try:
        if a.write_config:
            c=default_config(a.slots,a.period_ms,a.exploratory);validate_config(c)
            a.write_config.parent.mkdir(parents=True,exist_ok=True)
            with a.write_config.open('x') as f: json.dump(c,f,indent=2);f.write('\n')
            print(f'config={a.write_config}');return 0
        if not all((a.config,a.experiment_dir,a.run_id,a.output_dir)):
            p.error('--config, --experiment-dir, --run-id and --output-dir are required')
        run_analysis(a.experiment_dir,a.run_id,a.config,a.board_log or a.experiment_dir/'board.board.log',
                     {'ble':a.ble_packets,'zigbee':a.zigbee_packets},a.output_dir,a.allow_legacy_timing)
    except (ValueError,KeyError,OSError) as exc: p.error(str(exc))
    return 0

if __name__=='__main__':
    raise SystemExit(main())
