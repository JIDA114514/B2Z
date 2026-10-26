import sys,json
from pathlib import Path
sys.path.insert(0,'python/exadv_rx')
import decoder
decoder.OUTPUT_RATE=4000000;decoder.SPS=4;decoder.MAX_PACKET_SAMPLES=(1+4+2+255+3)*8*4
from receive import main
code=main(sys.argv[1:]);prefix=Path(sys.argv[sys.argv.index('--output')+1]);p=Path(str(prefix)+'.summary.json');s=json.loads(p.read_text());s['diagnostic_internal_output_rate_hz']=4000000;s['receiver_version']+='-diagnostic4M';s['diagnostic_note']='Internal phase rate changed to4Msps only in this independent process; production default unchanged';p.write_text(json.dumps(s,ensure_ascii=False,indent=2)+'\n');raise SystemExit(code)
