import sys,json,inspect,numpy as np,collections
from pathlib import Path
sys.path.insert(0,'python/exadv_rx');import decoder
from decoder import ChannelDecoder,IQDCBlocker
from protocol import crc24,whiten
source=inspect.getsource(ChannelDecoder._decode).replace('if data[-3:] != crc24(data[:-3]):\n            return None, True','if data[-3:] != crc24(data[:-3]):\n            self.rejected_pdus.append((self.buffer_base + start, data, score, window_fraction))\n            return None, True')
assert 'self.rejected_pdus.append' in source, 'receiver structure changed; recheck diagnostic hook'
ns=decoder.__dict__.copy();exec('class InspectDecoder(ChannelDecoder):\n'+source,ns);InspectDecoder=ns['InspectDecoder']
root=Path('python/exadv_rx/results');mapping=[0x419F,0x0E77,0x999E,0x667A,0x9DC3,0x770E,0xDC39,0x70E7,0xBCF5,0xB3D7,0xCD5F,0x357F,0xD5FC,0x57F3,0x5BCF,0x6F3D]
def crc16(data):
 crc=0
 for byte in data:
  crc^=byte
  for _ in range(8):crc=(crc>>1)^(0x8408 if crc&1 else 0)
 return crc.to_bytes(2,'little')
def expected(seq,rid,length):
 payload=bytearray.fromhex('b25a010a')+int(rid).to_bytes(2,'little')+int(seq).to_bytes(4,'little');state=0xb25a5a2d^(rid<<16)^seq
 for _ in range(length-10):state=(state*1664525+1013904223)&0xffffffff;payload.append(state>>24)
 frame=bytes.fromhex('00000000a7')+bytes([length+2])+payload+crc16(payload);bb=bytearray()
 for byte in frame:
  bits=format(byte,'08b')[::-1]
  for i in (0,4):bb+=mapping[int(bits[i:i+4],2)].to_bytes(2,'little')
 prefix=bytes([0x47,4*length+52])+bytes.fromhex('4909a6a5a4a3a2c1c80d020106020953')+bytes([len(bb)+3,0xff,0xff,0xff]);pdu=prefix+bb;mask=whiten(bytes(len(pdu)),39);pdu=prefix+bytes(b^mask[i+22] for i,b in enumerate(bb));return pdu+crc24(pdu)
reports=[]
for stem in ['rx_20261026_161955_853914','rx_20261026_162114_151247']:
 data=json.loads((root/(stem+'.payload_validation.json')).read_text());info=data['summary'];rid=int(next(iter(info['run_ids'])));length=int(next(iter(info['payload_lengths'])));missing=set(range(150))-{r['sequence'] for r in data['rows']};results=[]
 # Verify the expected on-air PDU model against every already CRC-valid target.
 model_ok=True
 for line in (root/(stem+'.packets.jsonl')).read_text().splitlines():
  p=json.loads(line)
  if p['extended'].get('adva')!='C1:A2:A3:A4:A5:A6':continue
  row=next(r for r in data['rows'] if r['packet_no']==p['packet_no']);model_ok &= bytes.fromhex(p['pdu_hex'])==expected(row['sequence'],rid,length)[:-3]
 with open(root/(stem+'.ci8'),'rb') as h:
  for seq in sorted(missing):
   start=int((info['fitted_sequence_zero_time_s']+seq*info['fitted_interval_s']-.005)*8e6);h.seek(start*2);raw=h.read(96000*2);v=np.frombuffer(raw,np.int8).astype(np.float32).reshape(-1,2);iq=(v[:,0]+1j*v[:,1])/128
   d=InspectDecoder(8000000,2480000000,39);d.rejected_pdus=[];dc=IQDCBlocker(8000000);ps=d.feed(dc.feed(iq))+d.feed([],final=True);truth=expected(seq,rid,length);errors=[]
   for offset,packet,score,width in d.rejected_pdus:
    if len(packet)!=len(truth) or abs((offset*d.decimation-32)/8e6-.005)>.0025:continue
    prefix_error=sum((a^b).bit_count() for a,b in zip(packet[:12],truth[:12]))
    if prefix_error<=4:errors.append(sum((a^b).bit_count() for a,b in zip(packet,truth)))
   results.append({'sequence':seq,'recovered_in_isolated_snippet':any(p['extended'].get('adva')=='C1:A2:A3:A4:A5:A6' for p in ps),'target_header_compatible_crc_failure':bool(errors),'minimum_bit_errors_diagnostic_only':min(errors) if errors else None,'candidate_stats':dict(d.stats)})
 categories=collections.Counter('no_header_compatible_candidate' if r['minimum_bit_errors_diagnostic_only'] is None else '1_to_2_bit' if r['minimum_bit_errors_diagnostic_only']<=2 else '3_to_16_bit' if r['minimum_bit_errors_diagnostic_only']<=16 else 'over_16_bit' for r in results)
 report={'run_id':rid,'length':length,'stem':stem,'expected_pdu_model_verified_against_all_valid_packets':bool(model_ok),'missing_count_assuming_150_slots':len(missing),'categories':dict(categories),'isolated_recovered':sum(r['recovered_in_isolated_snippet'] for r in results),'rows':results};reports.append(report);print(rid,'model verified',model_ok,'missing',len(missing),'categories',categories,'snippet_recovered',report['isolated_recovered'],flush=True)
(root/'iq_optimization_feasibility_losses.summary.json').write_text(json.dumps({'method':'12ms isolated snippets; target-header compatibility <=4 bit errors within first12 bytes; known payload used only to count offline errors, never by receiver; predicted slots do not prove TX completion','runs':reports},ensure_ascii=False,indent=2)+'\n')
