#!/usr/bin/env python3
"""Record B-only -> A+B -> B-only under one continuous board run.

Does not start/stop the board or claim synchronization/PRR. Both devices stay
connected; only receiver activity changes. Run the printed board command first.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
sys.path.insert(0,str(HERE.parent))
from experiment_tools.reporting import new_directory, refresh_session


def inspect_devices(args):
    executable=shutil.which('hackrf_info')
    if not executable:
        raise RuntimeError('hackrf_info not found; install HackRF tools before starting the experiment')
    result=subprocess.run([executable],capture_output=True,text=True,timeout=10)
    output=result.stdout+'\n'+result.stderr
    detected=sorted(set(s.lower() for s in re.findall(r'Serial number:\s*([0-9a-fA-F]{32})\b',output)))
    required=[args.ble_serial.lower(),args.zigbee_serial.lower()]
    return {'command':[executable],'returncode':result.returncode,'raw_output':output,
            'detected_serials':detected,'missing_serials':[s for s in required if s not in detected]}


def receiver_result(directory,stage,kind,proc):
    prefix=receiver_prefix(directory,stage,kind)
    path=Path(str(prefix)+'.summary.json')
    info={'summary':str(path),'console_log':str(Path(str(prefix)+'.console.log')),
          'process_returncode':proc.returncode}
    try:
        value=json.loads(path.read_text())
        for key in ('status','error','counts','capture_stats','receiver','run_id','stderr_tail'):
            if key in value:
                info[key]=value[key]
        info['source_sha256']=value.get('sources_sha256')
    except (OSError,ValueError) as exc:
        info['summary_read_error']=str(exc)
    return info


def failure_message(directory,stage,failed):
    reasons=[]
    for kind,code in failed:
        prefix=receiver_prefix(directory,stage,kind)
        path=Path(str(prefix)+'.summary.json')
        try:
            value=json.loads(path.read_text())
            lines=value.get('stderr_tail',[])
            relevant=[line for line in lines if any(token in line.lower() for token in
                ("couldn't transfer",'failed:','streaming stopped','queue overflow','capture stalled'))]
            # Preserve the first transfer error, rather than only cleanup errors.
            cause='; '.join(relevant[:3] or lines[-3:]) or value.get('error') or 'unknown error'
        except (OSError,ValueError):
            cause='no receiver summary available'
        reasons.append(f'{kind} exited {code}: {cause}; log={prefix}.console.log')
    return 'receiver failed: '+' | '.join(reasons)


def receiver_prefix(directory,stage,kind):
    return directory/'captures'/stage/kind/'rx'


def commands(args, directory, stage, dual):
    common=['--duration',str(args.phase_seconds),'--run-id',str(args.run_id),
            '--save-iq' if args.save_iq else '--no-save-iq']
    result={'zigbee':[sys.executable,str(HERE.parent/'zigbee_rx/receive.py'),
        '--serial',args.zigbee_serial,'--channel','26','--demod','phase','--symbol-order','project',
        '--cutoff-hz','700000','--dc-block-hz','1000',
        '--payload-len',str(args.payload_len),'--quiet',*common,'--output',str(receiver_prefix(directory,stage,'zigbee'))]}
    if dual:
        result['ble']=[sys.executable,str(HERE.parent/'exadv_rx/receive.py'),
            '--serial',args.ble_serial,'--channels','39','--quiet',*common,
            '--output',str(receiver_prefix(directory,stage,'ble'))]
    return result


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--ble-serial',required=True)
    p.add_argument('--zigbee-serial',required=True)
    p.add_argument('--run-id',type=int,required=True)
    p.add_argument('--payload-len',type=int,default=30)
    p.add_argument('--phase-seconds',type=int,default=30)
    p.add_argument('--save-iq',action=argparse.BooleanOptionalAction,default=True)
    p.add_argument('--output',type=Path,default=new_directory('single_dual'))
    p.add_argument('--dry-run',action='store_true')
    args=p.parse_args(argv)
    if args.ble_serial.lower()==args.zigbee_serial.lower():
        p.error('two distinct HackRF serial numbers are required')
    for serial in (args.ble_serial,args.zigbee_serial):
        if len(serial)!=32 or any(c not in '0123456789abcdefABCDEF' for c in serial):
            p.error('serial must be the full 32-digit hexadecimal identifier from hackrf_info')
    if not 0<=args.run_id<=65535 or not 10<=args.payload_len<=46 or not 10<=args.phase_seconds<=60:
        p.error('run-id 0..65535, payload-len 10..46 and phase-seconds 10..60 required')
    directory=args.output.resolve()
    stages=[('single_before',False),('dual',True),('single_after',False)]
    board=f'bluebee_exadv_perf_start?{args.payload_len} 200000 0 {args.run_id}'
    print('Start a continuous board run BEFORE this script:',board,flush=True)
    print('Keep antennas, gain, RF parameters, device positions and USB cables unchanged.',flush=True)
    print('Stop other receiver programs first. This script controls receiver activity only.',flush=True)
    print('Both HackRFs must remain connected by USB in ALL stages, including B-only stages.',flush=True)
    if args.dry_run:
        print(json.dumps({name:commands(args,directory,name,dual) for name,dual in stages},indent=2))
        return 0
    directory.mkdir(parents=True,exist_ok=False)
    report={'schema':'single_dual_single_rx_v2','status':'running','start_utc':datetime.now(timezone.utc).isoformat(),
            'assumed_board_command':board,'board_start_or_counters_verified':False,
            'scope':'single/dual activity control, no PRR or clock synchronization result',
            'source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'stages':[]}
    def save():
        (directory/'single_dual.summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
        refresh_session(directory)
    save()
    active=[]
    try:
        for stage,dual in stages:
            print(f'Stage {stage}: {args.phase_seconds}s, receivers={"A+B" if dual else "B only"}',flush=True)
            entry={'stage':stage,'commands':commands(args,directory,stage,dual),
                   'start_utc':datetime.now(timezone.utc).isoformat(),'receivers':{}}
            report['stages'].append(entry);save()
            entry['device_check']=inspect_devices(args);save()
            check=entry['device_check']
            if check['missing_serials']:
                raise RuntimeError('required HackRF not detected: '+', '.join(check['missing_serials'])+
                    '; detected: '+(', '.join(check['detected_serials']) or 'none')+
                    '; keep BOTH devices connected by USB throughout the experiment')
            if check['returncode']:
                raise RuntimeError('hackrf_info failed before capture: '+check['raw_output'].strip())
            logs=[];active=[]
            try:
                for kind,command in entry['commands'].items():
                    prefix=receiver_prefix(directory,stage,kind)
                    prefix.parent.mkdir(parents=True,exist_ok=True)
                    log=Path(str(prefix)+'.console.log').open('x');logs.append(log)
                    active.append((kind,subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT,cwd=ROOT)))
                deadline=time.monotonic()+args.phase_seconds+40
                while any(proc.poll() is None for _,proc in active):
                    failed=[(kind,proc.returncode) for kind,proc in active if proc.poll() not in (None,0)]
                    if failed:
                        raise RuntimeError(failure_message(directory,stage,failed))
                    if time.monotonic()>deadline:
                        raise RuntimeError('receiver exceeded bounded stage timeout')
                    time.sleep(.1)
            finally:
                for _,proc in active:
                    if proc.poll() is None:
                        proc.send_signal(signal.SIGINT)
                for _,proc in active:
                    try:
                        proc.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        proc.kill();proc.wait()
                for log in logs:
                    log.close()
                for kind,proc in active:
                    entry['receivers'][kind]=receiver_result(directory,stage,kind,proc)
                entry['end_utc']=datetime.now(timezone.utc).isoformat();save()
            for kind,proc in active:
                value=entry['receivers'][kind]
                if proc.returncode or value.get('status')!='complete':
                    raise RuntimeError(f'{stage}/{kind} incomplete; inspect {value["console_log"]}')
                if kind=='zigbee':
                    print(f"  ZigBee run={value['run_id']} unique={value['receiver']['unique']} "
                          f"queue_max={value['capture_stats'].get('queue_high_water',0)}",flush=True)
            entry['status']='complete';save()
    except BaseException as exc:
        report['status']='error';report['error']=f'{type(exc).__name__}: {exc}';save()
        raise
    finally:
        print('Stop the continuous board run manually: bluebee_perf_stop?',flush=True)
    report['status']='complete';report['end_utc']=datetime.now(timezone.utc).isoformat();save()
    print('Saved:',directory,flush=True)
    return 0


if __name__=='__main__':
    try:
        sys.exit(main())
    except (RuntimeError,OSError,subprocess.SubprocessError) as exc:
        print(f'error: {exc}',file=sys.stderr)
        sys.exit(1)
