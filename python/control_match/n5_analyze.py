"""N5 preregistered replay, live observation audit and independent task matching."""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime
import json
import math
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_match.n5_config import load
from control_match.n3_holdover import evaluate, distribution, SIDES
from control_match.n3_timing import parse_timing
from control_match.n3_analyze import diagnostics, plots
from control_match.analyze import discover
from control_match.plan_analyze import read_plan, load_side, summarize
from control_match.holdover_analyze import sha256, write_csv
from control_match.control_engine import EngineConfig
from control_match.replay_engine import replay_records


def ratio(n, d):
    return dict(numerator=n, denominator=d, value=n/d if d else None)


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def missing_intervals(plan, stream, side):
    """Consecutive no-decode slots, including censored boundaries and board failures."""
    rows, pending = [], []
    def flush():
        if not pending:
            return
        first, last = pending[0], pending[-1]
        attempted = sum(plan['slots'][s]['board_tx_completed'] for s in pending)
        rows.append(dict(side=side, first_slot=first, last_slot=last, slots=len(pending),
                         nominal_missing_duration_ms=len(pending)*int(plan['stats']['period_ms']),
                         left_observed=first-1 in stream, right_observed=last+1 in stream,
                         left_censored=first-1 not in stream, right_censored=last+1 not in stream,
                         dma_completed_slots=attempted, board_uncompleted_slots=len(pending)-attempted,
                         cause='undetermined; DMA completion is not RF completion'))
        pending.clear()
    for slot in plan['slots']:
        if slot not in stream:
            pending.append(slot)
        else:
            flush()
    flush()
    return rows


def recovery_rows(events, rate, side):
    rows, active = [], None
    for e in events:
        if e['event'] != 'observation_transition':
            continue
        state = e['state']
        if state == 'stale' and active is None:
            active = dict(side=side, stale_sample=e['local_sample'], first_recovery_sample=None,
                          recovered_sample=None, recovery_ms=None, training_packets=None,
                          observation_mode=e.get('observation_mode'), segment=e.get('segment', 0))
        if active is not None:
            if state == 'reacquiring' and active['first_recovery_sample'] is None:
                active['first_recovery_sample'] = e['local_sample']
            if state == 'tracking':
                active.update(recovered_sample=e['local_sample'],
                              recovery_ms=(e['local_sample']-active['stale_sample'])*1000/rate,
                              training_packets=e['training_packets'],
                              acquisition_ms=(e['local_sample']-active['first_recovery_sample'])*1000/rate
                              if active['first_recovery_sample'] is not None else None)
                rows.append(active)
                active = None
            elif state == 'timeline_unverified':
                active['censor_reason'] = 'timeline_unverified'
                rows.append(active)
                active = None
    if active is not None:
        active['censor_reason'] = 'capture_end_without_recovery'
        rows.append(active)
    return rows


def check_plan(c, plan):
    if list(plan['slots']) != c['slots'] or int(plan['stats']['period_ms']) != c['period_ms']:
        raise ValueError('board slot/period differs from registration')
    if plan['stats'].get('rf_mode') != 'standard_secondary_ch3' or plan.get('capacity') or plan.get('compact'):
        raise ValueError('N5 requires standard v1 joint secondary')
    actual = {int(t['command_id']):t for t in plan['tasks'] if int(t['command_id'])}
    if set(actual) != {t['command_id'] for t in c['tasks']}:
        raise ValueError('board task IDs differ from registration')
    for t in c['tasks']:
        for key, value in t.items():
            board_key = 'repeats' if key == 'attempts' else key
            if int(actual[t['command_id']][board_key]) != value:
                raise ValueError('board task differs from registration: '+key)


def run_analysis(root, config_path, output, paths=None, board=None):
    if output.exists():
        raise ValueError('refusing to overwrite analysis')
    raw_config = json.loads(config_path.read_text())
    c = load(config_path, raw_config['run_id'])
    run = c['run_id']
    board = board or (root/'board'/'serial.log' if (root/'board'/'serial.log').exists() else root/'board.board.log')
    plan = read_plan(board, run)
    check_plan(c, plan)
    sides, receivers, rates, streams, live_events, anomalies = {}, {}, {}, {}, {}, {}
    sources = dict(config=config_path, board=board)
    replay_events, recoveries, missing, probe_rows = [], [], [], []
    for side in SIDES:
        path = (paths or {}).get(side) or discover(root, side)
        if path is None:
            raise ValueError('missing capture artifact: '+side)
        sources[side] = path
        receiver_path = path.with_name('rx.summary.json')
        sources[side+'_receiver'] = receiver_path
        receiver = receivers[side] = json.loads(receiver_path.read_text())
        rates[side] = rate = receiver['config']['sample_rate']
        if type(rate) is not int or rate <= 0:
            raise ValueError('invalid sample rate')
        data = sides[side] = load_side(path, side, run, {0, *[t['command_id'] for t in c['tasks']]})
        streams[side] = data['by_slot']
        if data['live_path']:
            sources[side+'_control_summary'] = data['live_path']
        total = receiver['counts'].get('samples_processed', 0)
        raw = read_jsonl(path)
        previous = -1
        for packet in raw:
            start, available = packet.get('sample_start'), packet.get('available_sample')
            if (not isinstance(start, (int,float)) or type(available) is not int or
                    not math.isfinite(start) or not 0 <= start <= available <= total or available < previous):
                raise ValueError(side+': missing/nonmonotonic availability; re-decode IQ')
            previous = available
        for slot, e in streams[side].items():
            if e['record']['version'] != 1 or e['record']['period_ms'] != c['period_ms']:
                raise ValueError('unsupported decoded timing format')
        live_path = path.with_name('rx.control.events.jsonl')
        events = read_jsonl(live_path) if live_path.exists() else []
        if live_path.exists():
            sources[side+'_events'] = live_path
        registrations = [e for e in events if e['event'] == 'registration']
        if registrations and (len(registrations) != 1 or registrations[0]['registration'] != c):
            raise ValueError('capture registration differs from analysis config')
        if registrations and data['live'] and data['live'].get('n5_registration') != c:
            raise ValueError('capture summary registration mismatch')
        live_events[side] = events if registrations else []
        anomalies[side] = [e for e in events if e['event'] == 'timeline_anomaly']
        if receiver.get('status') != 'complete' or receiver.get('error') or receiver.get('capture_stats',{}).get('queue_overflow'):
            anomalies[side].append(dict(reason='receiver_incomplete_or_overflow', local_sample=total))
        # Conservatively exclude the whole side from offline precision scoring on a broken axis.
        # Parsing and missing-slot results remain available.
        recoveries.extend(recovery_rows(live_events[side], rate, side))
        missing.extend(dict(r, timeline_anomalies_present=bool(anomalies[side]),
                            evidence='decoded_packet_absence_with_board_DMA_proxy')
                       for r in missing_intervals(plan, streams[side], side))
        for slot in c['probes']:
            found = [e for e in live_events[side] if e['event']=='probe_score' and e['slot_index']==slot]
            e = found[0] if found else {}
            probe_rows.append(dict(e, side=side, slot_index=slot, duplicates=max(0,len(found)-1),
                                   status=e.get('status', 'probe_missing' if slot not in streams[side] else 'live_score_not_recorded'),
                                   observation_mode=e.get('observation_mode','not_measured')))
        cfg = EngineConfig(side=side, run_id=run, sample_rate=rate,
                           target_ids=frozenset(receiver['config'].get('control_target_id') or [1 if side=='ble' else 2]))
        immediate, _ = replay_records(raw, cfg, total, policy='immediate')
        replay_events.extend(dict(e, observation_mode='replay', deadline_assessed=False) for e in immediate)
    capture_evidence = 'offline_input; independent physical reception not established'
    if all(not receivers[s]['config'].get('iq_file') for s in SIDES):
        try:
            intervals = [(datetime.fromisoformat(receivers[s]['start_utc']),
                          datetime.fromisoformat(receivers[s]['end_utc'])) for s in SIDES]
        except (KeyError, ValueError) as exc:
            raise ValueError('live capture intervals required to audit same-run matching') from exc
        if max(a for a,b in intervals) >= min(b for a,b in intervals):
            raise ValueError('receiver capture windows do not overlap')
        capture_evidence = 'overlapping live capture intervals; hardware identity requires experiment notes'
    integrity, slots, tasks = summarize(plan, sides['ble'], sides['zigbee'])
    for row in slots:
        row['quadrant'] = ('both' if row['ble_valid'] and row['zigbee_valid'] else
                           'ble_only' if row['ble_valid'] else 'zigbee_only' if row['zigbee_valid'] else 'neither')
    scored_streams = {s: {} if anomalies[s] else streams[s] for s in SIDES}
    validation, stats = evaluate(c, scored_streams, rates)
    for row in validation:
        row['observation_mode'] = 'replay'
        for side in SIDES:
            if anomalies[side]:
                row[side+'_status'] = 'timeline_unverified'
    timing = parse_timing(board, plan, True)
    qc, joined, associations, ages = diagnostics(scored_streams, rates, c, timing, validation)
    for task in tasks:
        for side in SIDES:
            selected = [e for e in replay_events if e['side']==side and e.get('command_id')==task['command_id']]
            task[side+'_immediate_replay_processed'] = any(e['event']=='software_processed' for e in selected)
        task['joint_first_attempt_decoded'] = int(all(task[s+'_first_valid_slot']==task['first_slot'] for s in SIDES))
    task_slots = {s for t in c['tasks'] for s in range(t['first_slot'],t['first_slot']+t['attempts'])}
    burst_rows = (plan.get('bursts') or {}).get('rows', [])
    cost_split = {label:dict(slots=sum((s in task_slots)==is_task for s in c['slots']),
        submitted_waveform_us=sum(r['air_us']*r['started'] for r in burst_rows if (r['slot'] in task_slots)==is_task) if burst_rows else None)
        for label,is_task in [('task_specific',True),('shared_sync',False)]}
    result = dict(cost_split=cost_split, schema='b2z_n5_analysis_v1', run_id=run, config_sha256=c['sha256'], integrity=integrity, capture_evidence=capture_evidence,
                  joint_parsing=ratio(sum(t['joint_task_decoded'] for t in tasks),len(c['tasks'])),
                  joint_first_attempt=ratio(sum(t['joint_first_attempt_decoded'] for t in tasks),len(c['tasks'])),
                  observation_modes={s:sorted({e.get('observation_mode','unknown') for e in live_events[s]}) for s in SIDES},
                  anomalies=anomalies, replay_summary=stats,
                  receiver_quality={s:{k:receivers[s].get(k) for k in ('status','error','counts','capture_stats','limitations')} for s in SIDES},
                  live_event_counts={s:dict(Counter(e['event'] for e in live_events[s])) for s in SIDES},
                  live_rejection_reasons={s:dict(Counter(e['reason'] for e in live_events[s] if 'reason' in e)) for s in SIDES},
                  recovery={s:ratio(sum(r['recovered_sample'] is not None for r in recoveries if r['side']==s),
                                    sum(r['side']==s for r in recoveries)) for s in SIDES},
                  live_probe_summary={s:dict(coverage=ratio(sum(r.get('status')=='scored' for r in probe_rows if r['side']==s),len(c['probes'])),
                      residual_ms=distribution([r.get('residual_ms') for r in probe_rows if r['side']==s])) for s in SIDES},
                  sources={k:dict(path=str(p.resolve()),sha256=sha256(p)) for k,p in sources.items()},
                  analysis_sources={p.name:sha256(p) for p in Path(__file__).parent.glob('*.py')},
                  limitations=['Replay is not live evidence; immediate deadlines are not assessed.',
                      'Missing decode causes remain undetermined; DMA is only a transmission proxy.',
                      'No calibrated cross-device clock, RF start or actuator precision is measured.',
                      'Anomalous timelines are excluded from replay precision scoring.',
                      'No hardware-loss warning does not establish gap-free IQ.',
                      '24 probes per policy give descriptive tails, not independent repeated experiments.'])
    output.mkdir(parents=True)
    live_pairs = []
    for slot in c['probes']:
        pair = {s:next(r for r in probe_rows if r['side']==s and r['slot_index']==slot) for s in SIDES}
        valid = all(r.get('status')=='scored' for r in pair.values())
        live_pairs.append(dict(slot=slot, relative_estimate_difference_ms=
            pair['ble']['estimated_ms']-pair['zigbee']['estimated_ms'] if valid else None,
            ble_status=pair['ble']['status'], zigbee_status=pair['zigbee']['status'],
            ble_mode=pair['ble']['observation_mode'], zigbee_mode=pair['zigbee']['observation_mode']))
    tables = {'live_pairs':live_pairs, 'slots':slots,'tasks':tasks,'missing':missing,'recovery':recoveries,'live_probes':probe_rows,
              'replay_probes':validation,'replay_summary':stats,'timing_associations':associations,
              'timing_joined':joined,'quality':qc,
              'transitions':[e for s in SIDES for e in live_events[s] if e['event']=='observation_transition']}
    for name, rows in tables.items():
        write_csv(output/(name+'.csv'),rows)
    (output/'immediate.replay.events.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in replay_events))
    (output/'config.json').write_text(json.dumps(c,indent=2)+'\n')
    (output/'n5.summary.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    plots(output,validation,timing)
    n,d = result['joint_parsing']['numerator'],result['joint_parsing']['denominator']
    lines = ['# N5 软件观测与机制分析','',f'Run {run}；联合命令解析 {n}/{d}；参考质量 uncalibrated。',
             '所有定时事件均为本侧 IQ 样本域软件事件；immediate 为 available_sample 回放，未评估截止时间。',
             '', '|侧|记录模式|探测评分/计划|失更后恢复/失更事件|', '|---|---|---|---|']
    for side in SIDES:
        coverage=result['live_probe_summary'][side]['coverage']; recovery=result['recovery'][side]
        lines.append(f"|{side}|{result['observation_modes'][side] or 'not_measured'}|{coverage['numerator']}/{coverage['denominator']}|{recovery['numerator']}/{recovery['denominator']} ({recovery['value'] if recovery['value'] is not None else 'N/A'})|")
    lines += ['', '逐槽四象限、全六任务、缺失边界、恢复删失及逐探测原因见 CSV；未恢复事件保留在恢复分母。',
              '时间轴异常：'+json.dumps(anomalies,ensure_ascii=False),
              '成本沿用 summary.integrity 的板端代理口径；包含同步槽和失败尝试，不能解释为已测 RF 发射时刻。',
              '', '![回放 CDF](holdover.cdf.png)', '', *result['limitations']]
    (output/'n5.report.md').write_text('\n'.join(lines)+'\n')
    return result


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--experiment-dir',type=Path,required=True)
    p.add_argument('--config',type=Path,required=True)
    p.add_argument('--analysis-id',required=True)
    p.add_argument('--ble-packets',type=Path)
    p.add_argument('--zigbee-packets',type=Path)
    a=p.parse_args()
    if Path(a.analysis_id).name != a.analysis_id or a.analysis_id in ('.','..'):
        p.error('analysis-id must be a single directory name')
    result=run_analysis(a.experiment_dir,a.config,a.experiment_dir/'analyses'/a.analysis_id,
                        dict(ble=a.ble_packets,zigbee=a.zigbee_packets))
    print(json.dumps(result['joint_parsing']))
