#!/usr/bin/env python3
"""Audit follow stages; packed demodulated bytes are NOT continuous IQ timestamps."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from control_match.flow_input import load_flow
from control_match.plan_analyze import read_plan,fields
from control_match.holdover_analyze import sha256,write_csv
from control_match.n3_holdover import distribution


def audit(flow_path,board_path,run):
    flow=load_flow(flow_path,run);plan=read_plan(board_path,run)
    summary_path=flow_path.with_name('flow.summary.json');summary=json.loads(summary_path.read_text())
    if flow['expected_attempts']!=len(plan['slots']) or flow['period_ms']!=int(plan['stats']['period_ms']):
        raise ValueError('flow/board plan configuration mismatch')
    expected='ble-only' if plan['stats'].get('rf_mode')=='separate_secondary_ch3' else 'joint'
    if summary.get('payload_mode','joint')!=expected: raise ValueError('flow payload mode differs from board')
    events=[json.loads(l) for l in flow_path.read_text().splitlines() if l.strip()]
    detailed=summary.get('diagnostics_schema')=='b2z_follow_stages_v1'
    rows=[]
    for slot,b in plan['slots'].items():
        primary=slot in flow['primary_slots'];followed=slot in flow['followed_slots']
        events_slot=[e for e in events if e.get('did')==slot or e.get('active_did')==slot]
        counts=Counter(e['event'] for e in events_slot)
        category=('followed' if followed else 'board_not_generated' if not b['board_generated'] else
                  'primary_not_observed' if not primary else 'primary_seen_follow_missing')
        row=dict(slot=slot,command_id=b['command_id'],board_generated=b['board_generated'],
                 board_secondary_completed=b['board_tx_completed'],primary_valid=primary,followed=followed,category=category)
        for k in ('tune_request','tune_return','tune_error','secondary_window_enter','secondary_window_exit','secondary_invalid','identity_mismatch'):
            row[k]=counts[k] if detailed else None
        row['timeline_status']='timeline_unverified'
        rows.append(row)
    groups=Counter(r['category'] for r in rows)
    stages=Counter(e['event'] for e in events)
    result=dict(schema='b2z_n3_follow_audit_v1',run_id=run,diagnostic_detail='new_stage_logs' if detailed else 'legacy_observations_only',
                categories=dict(groups),planned_slots=len(rows),
                follow_per_primary=dict(numerator=len(flow['followed_slots']),denominator=len(flow['primary_slots'])),
                follow_per_plan=dict(numerator=len(flow['followed_slots']),denominator=len(rows)),
                event_counts=dict(stages),host_queue_delay_ms=distribution([e.get('queue_delay_ms') for e in events]),
                host_retune_ms=distribution([e.get('host_retune_ms') for e in events]),
                timeline_status='timeline_unverified',rf_timing_precision=None,
                unknown=['No independently verified retune gap/sample continuity.',
                         'No RF or continuous IQ marker for follow timing.',
                         'No primary candidate is not proof of missing RF transmission.',
                         'Unidentified CRC failures cannot be assigned a slot.',
                         'Device API frequency return is not measured lock/settling time.'],
                sources={k:dict(path=str(p.resolve()),sha256=sha256(p)) for k,p in
                         [('flow',flow_path),('flow_summary',summary_path),('board',board_path)]})
    return result,rows


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--flow',type=Path,required=True);p.add_argument('--board-log',type=Path,required=True)
    p.add_argument('--run-id',type=int,required=True);p.add_argument('--output-dir',type=Path,required=True)
    a=p.parse_args(argv)
    try:
        if a.output_dir.exists():raise ValueError('output directory already exists')
        result,rows=audit(a.flow,a.board_log,a.run_id)
        a.output_dir.mkdir(parents=True)
        write_csv(a.output_dir/'follow.stages.csv',rows)
        (a.output_dir/'follow.audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
        (a.output_dir/'follow.audit.md').write_text('\n'.join(['# N3 跟随观测能力审计','',f'Run {a.run_id}；{result["diagnostic_detail"]}。','',
            *[f'- {k}: {v}/{len(rows)}' for k,v in result['categories'].items()], '',
            '采样连续性未验证；RF/同步精度未测。主机队列/切频时间仅作软件诊断。旧日志缺少的阶段保持未知，不能推断为零失败。','']))
        print(f'run={a.run_id} timeline_unverified output={a.output_dir}')
    except (ValueError,KeyError,OSError) as exc:p.error(str(exc))
    return 0

if __name__=='__main__':raise SystemExit(main())
