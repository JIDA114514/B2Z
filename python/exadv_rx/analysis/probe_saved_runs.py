import sys,json,time,inspect,collections,numpy as np
from pathlib import Path
sys.path.insert(0,'python/exadv_rx')
import decoder
from decoder import ChannelDecoder,IQDCBlocker
from protocol import whiten
src=inspect.getsource(ChannelDecoder._decode)
# Unknown-data, robust two-level CFO estimate; never use expected payload bits.
src=src.replace('bits = ((values - cfo) * amplitude > 0).astype(np.uint8)', '''if count > 56:
                low, high = np.percentile(values[40:], [20, 80])
                cfo = float((low + high) / 2)
            bits = ((values - cfo) * amplitude > 0).astype(np.uint8)''')
ns=decoder.__dict__.copy();exec('class RobustThreshold(ChannelDecoder):\n'+src,ns);RobustThreshold=ns['RobustThreshold']
root=Path('python/exadv_rx/results');stems=['rx_20261026_161955_853914','rx_20261026_162114_151247'];out=[]
for stem in stems:
 data=json.loads((root/(stem+'.payload_validation.json')).read_text());s=data['summary'];rid=int(next(iter(s['run_ids'])));length=int(next(iter(s['payload_lengths'])));anchor=s['fitted_sequence_zero_time_s'];step=s['fitted_interval_s'];records=[]
 with open(root/(stem+'.ci8'),'rb') as h:
  for seq in range(150):
   begin=int((anchor+seq*step-.005)*8e6);h.seek(begin*2);raw=h.read(96000*2);v=np.frombuffer(raw,np.int8).astype(np.float32).reshape(-1,2);records.append((seq,begin,(v[:,0]+1j*v[:,1])/128))
 baseline={r['sequence'] for r in data['rows']};result={'stem':stem,'run_id':rid,'payload_len':length,'full_stream_baseline_count':len(baseline),'probes':[]}
 for rate,cutoff,cfo,klass in [(2000000,850000,0,ChannelDecoder),(2000000,700000,0,ChannelDecoder),(4000000,850000,0,ChannelDecoder),(4000000,700000,0,ChannelDecoder),(2000000,850000,60000,ChannelDecoder),(2000000,700000,60000,ChannelDecoder),(4000000,700000,60000,ChannelDecoder),(2000000,850000,0,RobustThreshold),(4000000,850000,0,RobustThreshold)]:
  decoder.OUTPUT_RATE=rate;decoder.SPS=rate//1000000;decoder.MAX_PACKET_SAMPLES=(1+4+2+255+3)*8*decoder.SPS;RobustThreshold._decode.__globals__['SPS']=decoder.SPS
  success=[];packets=[];t=time.monotonic()
  for seq,begin,iq in records:
   d=klass(8000000,2480000000-cfo,39,cutoff_hz=cutoff);dc=IQDCBlocker(8000000);ps=[]
   for i in range(0,len(iq),65536):ps.extend(d.feed(dc.feed(iq[i:i+65536])))
   ps.extend(d.feed([],final=True));good=[p for p in ps if p['extended'].get('adva')=='C1:A2:A3:A4:A5:A6']
   if good:
    success.append(seq)
    for p in good:p['source_sample_start']=begin;packets.append(p)
  probe={'output_rate':rate,'cutoff_hz':cutoff,'manual_cfo_shift_hz':cfo,'algorithm':klass.__name__,'count':len(success),'slot_success':success,'gained_vs_full_stream':sorted(set(success)-baseline),'lost_vs_full_stream':sorted(baseline-set(success)),'wall_s':time.monotonic()-t,'packets':packets}
  result['probes'].append(probe);print(rid,rate,cutoff,cfo,klass.__name__,'n',len(success),'new',probe['gained_vs_full_stream'],'lost',probe['lost_vs_full_stream'],'wall',round(probe['wall_s'],2),flush=True)
 out.append(result)
packet_archive=root/'iq_optimization_feasibility_probes.packets.jsonl'
with packet_archive.open('w') as archive:
 for run in out:
  for probe in run['probes']:
   packets=probe.pop('packets',[]);probe['packet_records']=len(packets)
   for packet in packets:archive.write(json.dumps({'run_id':run['run_id'],'variant':{k:probe[k] for k in ['output_rate','cutoff_hz','manual_cfo_shift_hz','algorithm']},'packet':packet})+'\n')
(root/'iq_optimization_feasibility_probes.summary.json').write_text(json.dumps({'method':'12 ms independently initialized snippets on 150 predicted slots; baseline vs full-stream may differ; manual CFO is diagnostic only','runs':out},ensure_ascii=False,indent=2)+'\n')
