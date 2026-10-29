#!/usr/bin/env python3
"""Independent dual decoding on each IQ; validate packet-reference timing only."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
import csv
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[1]
sys.path.insert(0, str(HERE.parent))
from experiment_tools.reporting import new_directory, refresh_session, resolve_recorded_path
sys.path.insert(0, str(HERE.parent / 'zigbee_rx'))
from zigbee_protocol import frame_payload, parse_test_payload, symbols_to_bytes

_spec = importlib.util.spec_from_file_location('_reference_validation_ble_protocol', HERE.parent / 'exadv_rx/protocol.py')
BLE = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(BLE)

# Exact inverse of the transmitted BlueBee representation, AFTER independent
# BLE CRC decoding. Never supplied to the standard-DSSS ZigBee receiver.
WORDS = (0x419F, 0x0E77, 0x999E, 0x667A, 0x9DC3, 0x770E, 0xDC39, 0x70E7,
         0xBCF5, 0xB3D7, 0xCD5F, 0x357F, 0xD5FC, 0x57F3, 0x5BCF, 0x6F3D)
INVERSE = {word: index for index, word in enumerate(WORDS)}


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def dump(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def ble_identity(packet):
    """Parse identity and on-air byte offset using this BLE result alone."""
    if not packet.get('crc_ok'):
        raise ValueError('BLE CRC not valid')
    pdu = bytes.fromhex(packet['pdu_hex'])
    crc = bytes.fromhex(packet['crc_hex'])
    if crc != BLE.crc24(pdu):
        raise ValueError('BLE CRC recomputation failed')
    parsed = BLE.parse_pdu(pdu, packet['channel'])
    if parsed['extended'].get('adva') != 'C1:A2:A3:A4:A5:A6':
        return []
    adv_start = 2 + 1 + (pdu[2] & 63)
    adv = pdu[adv_start:]
    air_pdu = BLE.whiten(pdu, packet['whitening_channel'])
    results = []
    pos = 0
    while pos < len(adv) and adv[pos]:
        end = pos + 1 + adv[pos]
        if end > len(adv):
            raise ValueError('truncated AD structure')
        if adv[pos] >= 3 and adv[pos + 1] == 255 and adv[pos + 2:pos + 4] == b'\xff\xff':
            start = adv_start + pos + 4
            raw = air_pdu[start:adv_start + end]
            if not raw or len(raw) % 4:
                raise ValueError('BlueBee encoding not whole PHY bytes')
            accepted = None
            for inverse_polarity in (False, True):
                try:
                    symbols = [INVERSE[int.from_bytes(raw[i:i+2], 'little') ^ (65535 if inverse_polarity else 0)]
                               for i in range(0, len(raw), 2)]
                    frame = symbols_to_bytes(symbols, 'project')
                    payload = frame_payload(frame)
                    identity = parse_test_payload(payload)
                    if not identity.valid:
                        raise ValueError('invalid test payload')
                    accepted = {'run_id':identity.run_id, 'sequence':identity.sequence,
                                'payload_len':len(payload), 'frame_hex':frame.hex(),
                                'pdu_byte_offset':start, 'layout_delta_us':(5 + start) * 8,
                                'sample_start':packet['sample_start'],
                                'decode_method':packet['decode_method']}
                    break
                except (ValueError, KeyError):
                    pass
            if accepted is None:
                raise ValueError('BLE-decoded embedded frame fails exact mapping/FCS/test validation')
            results.append(accepted)
        pos = end
    return results


def statistics(values):
    array = np.asarray(values, dtype=float)
    if not len(array):
        return {'n':0}
    absolute = np.abs(array)
    return {'n':len(array), 'mean_us':float(array.mean()), 'median_us':float(np.median(array)),
            'std_us':float(array.std()), 'min_us':float(array.min()), 'max_us':float(array.max()),
            'abs_p95_us':float(np.percentile(absolute,95)), 'abs_p99_us':float(np.percentile(absolute,99)),
            'abs_max_us':float(absolute.max())}


def match_sequences(ble, zigbee, run_id, expected, sample_rate):
    """No cross-capture matching or guessed identity/timing for missing frames."""
    a, b = defaultdict(list), defaultdict(list)
    for packets, target in ((ble,a),(zigbee,b)):
        for p in packets:
            if p['run_id'] == run_id:
                target[p['sequence']].append(p)
    records = []
    for sequence in range(expected):
        aa, bb = a[sequence], b[sequence]
        row = {'run_id':run_id,'sequence':sequence,
               'state':'both' if aa and bb else 'ble_only' if aa else 'zigbee_only' if bb else 'neither',
               'ble_occurrences':len(aa),'zigbee_occurrences':len(bb), 'timing_status':'not_joint'}
        if aa and bb:
            if len(aa) != 1 or len(bb) != 1:
                row['timing_status'] = 'ambiguous_repeated_sequence'
            elif aa[0]['frame_hex'] != bb[0]['frame_hex']:
                row['timing_status'] = 'frame_mismatch'
            else:
                p, q = aa[0], bb[0]
                delta = (q['sample_start'] - p['sample_start']) / sample_rate * 1e6
                row.update(timing_status='matched',ble_sample=p['sample_start'],zigbee_sample=q['sample_start'],
                           ble_time_s=p['sample_start']/sample_rate,delta_us=delta,
                           layout_delta_us=p['layout_delta_us'],layout_error_us=delta-p['layout_delta_us'],
                           frame_hex=p['frame_hex'],ble_method=p['decode_method'],zigbee_method=q['decode_method'])
        records.append(row)
    return records, {'ble_out_of_range':sorted(s for s,v in a.items() if v and not 0<=s<expected),
                     'zigbee_out_of_range':sorted(s for s,v in b.items() if v and not 0<=s<expected)}


def assign_calibration(rows, calibration):
    training = [r for r in rows if r['timing_status']=='matched' and
                r['run_id']==calibration['run_id'] and r['sequence']<calibration['sequence_lt']]
    if not training:
        raise ValueError('no joint calibration samples')
    bias = float(np.median([r['layout_error_us'] for r in training]))
    for row in rows:
        row['partition'] = ('calibration' if row['run_id']==calibration['run_id'] and
                            row['sequence']<calibration['sequence_lt'] else 'validation')
        if row['timing_status']=='matched':
            row['calibrated_error_us'] = row['layout_error_us'] - bias
    return {'rule':calibration,'joint_training_samples':len(training),'fixed_bias_us':bias,
            'scope':'one constant only, no slope fit or per-packet alignment; no validation sample used for calibration'}


def replay_prefix(directory, rid, role):
    return directory/'analyses'/f'run_{rid}'/role/'rx'


def replay(recording, config, directory):
    iq = resolve_recorded_path(PROJECT / recording['iq'])
    source_summary = iq.with_suffix('.summary.json')
    meta = json.loads(source_summary.read_text())
    if meta['status']!='complete' or iq.stat().st_size % 2 or iq.stat().st_size==0:
        raise ValueError(f'invalid IQ capture: {iq}')
    for key, value in (('sample_rate',config['sample_rate']),('center_hz',config['center_hz'])):
        if meta['config'][key]!=value:
            raise ValueError(f'capture {key} mismatch: {iq}')
    if meta['counts']['samples_processed']*2 != iq.stat().st_size:
        raise ValueError('capture length does not match processed samples')
    common = ['--iq-file',str(iq),'--format','ci8','--sample-rate',str(config['sample_rate']),
              '--center-hz',str(config['center_hz']),'--duration','0','--quiet']
    rid = recording['run_id']
    commands = {
        'ble':[sys.executable,str(HERE.parent/'exadv_rx/receive.py'),*common,'--channels','39',
               '--whitening-channels','39','--run-id',str(rid),'--output',str(replay_prefix(directory,rid,'ble'))],
        'zigbee':[sys.executable,str(HERE.parent/'zigbee_rx/receive.py'),*common,'--channel','26',
                  '--demod','phase','--symbol-order','project','--run-id',str(rid),
                  '--payload-len',str(recording['payload_len']),'--expected-packets',str(recording['expected_packets']),
                  '--output',str(replay_prefix(directory,rid,'zigbee'))]
    }
    def run(item):
        name, command = item
        print(f'run {rid}: independent {name} replay started',flush=True)
        prefix = replay_prefix(directory,rid,name)
        prefix.parent.mkdir(parents=True,exist_ok=True)
        with Path(str(prefix)+'.console.log').open('x') as log:
            result = subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,cwd=PROJECT)
        if result.returncode:
            raise RuntimeError(f'{name} replay failed; see {log.name}')
        summary = json.loads(Path(str(prefix)+'.summary.json').read_text())
        if summary['status']!='complete' or summary['counts']['samples_processed']*2 != iq.stat().st_size:
            raise ValueError('replay incomplete')
        print(f'run {rid}: {name} replay complete',flush=True)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(run,commands.items()))
    return {'recording':recording,'iq_sha256':sha256(iq),'iq_bytes':iq.stat().st_size,
            'capture_summary_sha256':sha256(source_summary),'commands':commands}


def analyze(recording, directory, sample_rate):
    rid = recording['run_id']
    ble, zigbee, errors = [], [], Counter()
    for line in Path(str(replay_prefix(directory,rid,'ble'))+'.packets.jsonl').read_text().splitlines():
        packet = json.loads(line)
        try:
            identities = ble_identity(packet)
            for value in identities:
                if value['run_id']==rid and value['payload_len']==recording['payload_len']:
                    ble.append(value)
                else:
                    errors['ble_identity_filter'] += 1
        except ValueError as exc:
            errors[str(exc)] += 1
    for line in Path(str(replay_prefix(directory,rid,'zigbee'))+'.packets.jsonl').read_text().splitlines():
        packet = json.loads(line)
        payload = frame_payload(bytes.fromhex(packet['frame_hex']))
        parsed = parse_test_payload(payload)
        if parsed.valid and parsed.run_id==rid and len(payload)==recording['payload_len']:
            zigbee.append({'run_id':parsed.run_id,'sequence':parsed.sequence,'frame_hex':packet['frame_hex'],
                           'sample_start':packet['sample_start'],'decode_method':packet['decode_method']})
        else:
            errors['zigbee_identity_filter'] += 1
    rows, extra = match_sequences(ble,zigbee,rid,recording['expected_packets'],sample_rate)
    return rows, {'identity_errors':dict(errors),**extra}


def figures(rows, destination):
    os.environ.setdefault('MPLCONFIGDIR','/tmp/b2z-sync-matplotlib')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(2,2,figsize=(11,7),layout='constrained')
    runs = sorted({r['run_id'] for r in rows})
    for rid in runs:
        joint = [r for r in rows if r['run_id']==rid and r['timing_status']=='matched']
        holdout = [r for r in joint if r['partition']=='validation']
        axes[0,0].scatter([r['ble_time_s'] for r in joint],[r['delta_us'] for r in joint],s=12,label=str(rid))
        axes[0,1].scatter([r['ble_time_s'] for r in holdout],[r['calibrated_error_us'] for r in holdout],s=12,label=str(rid))
        if holdout:
            ordered = np.sort(np.abs([r['calibrated_error_us'] for r in holdout]))
            axes[1,0].step(ordered,np.arange(1,len(ordered)+1)/len(ordered),where='post',label=str(rid))
    axes[0,0].set(xlabel='Time within each recording (s)',ylabel='ZigBee minus BLE reference (us)',title='Raw reference position difference')
    axes[0,1].set(xlabel='Time within each recording (s)',ylabel='Calibrated residual (us)',title='Held-out joint frames only')
    axes[1,0].set(xlabel='Absolute residual (us)',ylabel='Empirical CDF',title='Held-out conditional timing distribution')
    base=np.zeros(len(runs))
    for state in ('both','ble_only','zigbee_only','neither'):
        values=np.array([sum(r['run_id']==rid and r['state']==state for r in rows) for rid in runs])
        axes[1,1].bar([str(r) for r in runs],values,bottom=base,label=state);base+=values
    axes[1,1].set(xlabel='Run ID',ylabel='Planned slots',title='Decode outcomes; expected 150 per run')
    for ax in axes.flat:
        ax.grid(alpha=.2);ax.legend(fontsize=8)
    fig.suptitle('Same-IQ independent decoding; no independent-device synchronization claim')
    for extension in ('png','pdf'):
        fig.savefig(destination/f'reference_validation.{extension}',dpi=180)
    plt.close(fig)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,default=HERE/'recordings.config.json')
    parser.add_argument('--output',type=Path,default=new_directory('same_iq_validation'))
    args=parser.parse_args(argv)
    config=json.loads(args.config.read_text())
    directory=args.output.resolve();directory.mkdir(parents=True,exist_ok=False)
    sources=list((HERE.parent/'exadv_rx').glob('*.py'))+list((HERE.parent/'zigbee_rx').glob('*.py'))
    sources += [HERE/'validate_saved_iq.py',HERE.parent/'perf_test/bluebee_perf_protocol.py']
    manifest={'config':config,'config_sha256':sha256(args.config),
              'start_utc':datetime.now(timezone.utc).isoformat(),
              'sources_sha256':{str(p.relative_to(PROJECT)):sha256(p) for p in sources},'replays':[]}
    dump(directory/'validation.manifest.json',manifest)
    rows, details=[],{}
    for recording in config['recordings']:
        manifest['replays'].append(replay(recording,config,directory))
        dump(directory/'validation.manifest.json',manifest)
        records,detail=analyze(recording,directory,config['sample_rate'])
        rows.extend(records);details[recording['run_id']]=detail
    calibration=assign_calibration(rows,config['calibration'])
    summary={'schema':'same_iq_reference_validation_v1','calibration':calibration,'runs':[],
             'sample_rate_hz':config['sample_rate'],'input_sample_period_us':1e6/config['sample_rate'],
             'scope':'conditional common-packet reference consistency in the same IQ, not independent clocks or execution',
             'matching':'run_id + sequence + identical complete FCS-validated PHY frame; repeated identities excluded from timing'}
    for recording in config['recordings']:
        rid=recording['run_id'];subset=[r for r in rows if r['run_id']==rid]
        joint=[r for r in subset if r['timing_status']=='matched']
        validation=[r for r in joint if r['partition']=='validation']
        counts=Counter(r['state'] for r in subset)
        summary['runs'].append({'run_id':rid,'payload_len':recording['payload_len'],
            'planned':len(subset),'outcomes':dict(counts),'ble_unique':counts['both']+counts['ble_only'],
            'zigbee_unique':counts['both']+counts['zigbee_only'],
            'joint_decode':{'numerator':counts['both'],'denominator':len(subset),'value':counts['both']/len(subset)},
            'raw_delta':statistics([r['delta_us'] for r in joint]),
            'layout_only_error':statistics([r['layout_error_us'] for r in joint]),
            'held_out_error':statistics([r['calibrated_error_us'] for r in validation]),
            'tolerance_results':[{'tolerance_us':tol,'numerator':sum(r['timing_status']=='matched' and abs(r['calibrated_error_us'])<=tol for r in subset if r['partition']=='validation'),
                                  'denominator':sum(r['partition']=='validation' for r in subset),
                                  'scope':'planned held-out slots, joint decoding plus reference residual bound; not execution success'} for tol in (.25,.5,1,5)],
            'timing_exclusions':dict(Counter(r['timing_status'] for r in subset if r['state']=='both' and r['timing_status']!='matched')),
            **details[rid]})
    summary['pooled_held_out_error']=statistics([r['calibrated_error_us'] for r in rows if r['timing_status']=='matched' and r['partition']=='validation'])
    summary['limitations']=['same IQ shared clock and path, not two simultaneously receiving devices',
        'timestamps have DSP and sample grid quantization; input sample period is not achieved accuracy',
        'calibration uses first-half joint sequences of run10265; all other samples held out',
        'conditional error excludes missing frames; per-slot outcomes and tolerance denominators retain them',
        '150 planned slots are receiver configuration, not verified board TX counters',
        'no sync fields, clock drift compensation, software timer execution or actuator events tested',
        'fixed same-channel secondary experiment, not complete AuxPtr following']
    dump(directory/'reference_validation.summary.json',summary)
    fields=sorted({key for row in rows for key in row})
    with (directory/'per_sequence.metrics.csv').open('w',newline='') as handle:
        writer=csv.DictWriter(handle,fieldnames=fields);writer.writeheader();writer.writerows(rows)
    figures(rows,directory)
    manifest['end_utc']=datetime.now(timezone.utc).isoformat()
    manifest['artifacts_sha256']={p.name:sha256(p) for p in directory.iterdir() if p.is_file() and p.suffix in ('.csv','.png','.pdf')}
    dump(directory/'validation.manifest.json',manifest)
    refresh_session(directory)
    print('同 IQ 参考验证已完成；不代表独立设备时钟或执行同步。',flush=True)
    print('完整报告：',directory/'report.md',flush=True)
    return 0


if __name__=='__main__':
    sys.exit(main())
