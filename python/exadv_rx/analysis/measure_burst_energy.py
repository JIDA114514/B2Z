import sys,json,numpy as np,collections
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiment_tools.reporting import new_directory, refresh_session, resolve_recorded_path
from scipy import signal
sys.path.insert(0,'python/exadv_rx');from decoder import IQDCBlocker
root=new_directory('measure_burst_energy');root.mkdir(parents=True,exist_ok=False);reports=[]
for stem in ['rx_20261026_161955_853914','rx_20261026_162114_151247']:
 v=json.loads((resolve_recorded_path(Path('python/exadv_rx/results')/(stem+'.payload_validation.json'))).read_text());s=v['summary'];rid=int(next(iter(s['run_ids'])));length=int(next(iter(s['payload_lengths'])));known={r['sequence']:r['time_s'] for r in v['rows']};slot0=s['fitted_sequence_zero_time_s'];step=s['fitted_interval_s'];delta=s['diagnostic_delta_us']['median']/1e6
 packets=[json.loads(x) for x in (resolve_recorded_path(Path('python/exadv_rx/results')/(stem+'.packets.jsonl'))).read_text().splitlines()];primary={int(round((p['sample_time_s']+delta-slot0)/step)):p['sample_time_s']+delta for p in packets if p['pdu_hex']=='07074618c80d03e823'}
 taps=signal.firwin(65,850000,fs=8000000);rows=[]
 with open(resolve_recorded_path(Path('python/exadv_rx/results')/(stem+'.ci8')),'rb') as h:
  for seq in range(150):
   center=known.get(seq,primary.get(seq,slot0+seq*step));begin=int((center-.003)*8e6);h.seek(begin*2);raw=h.read(64000*2);a=np.frombuffer(raw,np.int8).astype(np.float32).reshape(-1,2);x=(a[:,0]+1j*a[:,1])/128;x=IQDCBlocker(8000000).feed(x);y=signal.upfirdn(taps,x,down=4);power=np.abs(y)**2;origin=round((center-begin/8e6)*2e6+8)
   noise=power[origin-2000:origin-400].reshape(-1,200).mean(axis=1);floor=max(float(np.median(noise)),1e-12);n=int((4*length+62)*8*2);burst=power[origin:origin+n];bins=burst[:len(burst)//200*200].reshape(-1,200).mean(axis=1);rows.append({'sequence':seq,'received':seq in known,'reference_power':floor,'median_burst_db_over_reference':float(10*np.log10(max(np.median(bins),1e-12)/floor)),'max_burst_db_over_reference':float(10*np.log10(max(max(bins),1e-12)/floor)),'burst_bins_above_reference_10db':int(sum(bins>floor*10))})
 stats={}
 for received in [True,False]:
  group=[r for r in rows if r['received']==received];stats[str(received)]={'n':len(group),'median_burst_energy_ratio_db':float(np.median([r['median_burst_db_over_reference'] for r in group])),'median_peak_energy_ratio_db':float(np.median([r['max_burst_db_over_reference'] for r in group])),'with_peak_above_reference_10db':sum(r['burst_bins_above_reference_10db']>0 for r in group)}
 print(rid,stats,flush=True);reports.append({'run_id':rid,'groups':stats,'rows':rows})
(root/'iq_optimization_energy_diagnostic.summary.json').write_text(json.dumps({'scope':'uncalibrated channel-band energy ratios: 100us bins in predicted packet vs prior0.2-1ms reference; not SNR, no claim of interferer identity','runs':reports},ensure_ascii=False,indent=2)+'\n')

refresh_session(root)
print("完整报告：",root/"report.md",flush=True)
