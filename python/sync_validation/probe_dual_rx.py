#!/usr/bin/env python3
"""Diagnostic windows located AFTER BLE decoding; not independent RX scores.

No BLE payload is supplied to the ZigBee decoder. Every recovery still requires
standard DSSS, PHR and FCS. A gain here requires full-stream confirmation.
"""
from pathlib import Path
import json
import sys
import time
import numpy as np

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
sys.path.insert(0,str(HERE.parent/'zigbee_rx'))
from dsp import IQDCBlocker
from zigbee_decoder import ZigBeeDecoder
from zigbee_protocol import parse_test_payload
from validate_saved_iq import ble_identity


def main():
    output=HERE/'results/dual_run10268_diagnostic'
    sources=[('ble_device',ROOT/'python/exadv_rx/results/rx_20261027_154450_562661.ci8',
              ROOT/'python/exadv_rx/results/rx_20261027_154450_562661.packets.jsonl'),
             ('zigbee_device',ROOT/'python/zigbee_rx/results/rx_20261027_154453_216417.ci8',
              output/'zigbee_iq_ble.packets.jsonl')]
    reports=[]
    for name,path,packets in sources:
        windows=[]
        with path.open('rb') as handle:
            for line in packets.read_text().splitlines():
                packet=json.loads(line)
                identities=ble_identity(packet)
                if not identities:
                    continue
                start=max(0,round((packet['sample_time_s']-.003)*8000000))
                handle.seek(start*2)
                values=np.frombuffer(handle.read(80000*2),np.int8).astype(np.float32).reshape(-1,2)
                windows.append((identities[0]['sequence'],(values[:,0]+1j*values[:,1])/128))
        report={'device':name,'iq':str(path.relative_to(ROOT)),
                'ble_valid_sequence_windows':[s for s,_ in windows],'variants':[]}
        variants=[(cutoff,dc,0,80) for cutoff in (700000,850000,1000000,1300000) for dc in (0,1000,5000)]
        variants += [(850000,1000,60000,80),(1300000,1000,60000,80),
                     (850000,1000,0,88),(1300000,1000,0,88)]
        for cutoff,dc,cfo,threshold in variants:
            successes=[];began=time.monotonic()
            for sequence,iq in windows:
                decoder=ZigBeeDecoder(demod='phase',symbol_order='project',cutoff_hz=cutoff,
                                      cfo_hz=cfo,preamble_max_distance=threshold)
                blocker=IQDCBlocker(8000000,dc)
                decoded=[]
                for begin in range(0,len(iq),65536):
                    decoded.extend(decoder.feed(blocker.feed(iq[begin:begin+65536])))
                decoded.extend(decoder.feed([],final=True))
                for packet in decoded:
                    identity=parse_test_payload(bytes.fromhex(packet['payload_hex']))
                    if identity.valid and identity.run_id==10268 and identity.sequence==sequence:
                        successes.append(sequence)
            variant={'cutoff_hz':cutoff,'dc_hz':dc,'cfo_hz':cfo,'preamble_max_distance':threshold,
                     'recovered_sequences':sorted(set(successes)),'count':len(set(successes)),
                     'wall_s':time.monotonic()-began}
            report['variants'].append(variant)
            print(name,cutoff,dc,cfo,threshold,'recovered',variant['count'],flush=True)
        reports.append(report)
    (output/'window_parameter_probe.summary.json').write_text(json.dumps({
        'scope':'BLE-located 10ms windows; reset DC/FIR state; diagnostic only, not an independent full-stream receive result',
        'decoder_input':'raw IQ only; no expected frame/Sequence/payload supplied to DSP',
        'runs':reports},indent=2)+'\n')


if __name__=='__main__':
    main()
