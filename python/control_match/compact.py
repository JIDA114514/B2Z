"""C1 decoding and bounded, local BLE fragment reassembly (no cross-side input)."""
from collections import Counter, OrderedDict
import binascii


def compact_record(data, side):
    try:
        from .protocol import capacity_extension
    except ImportError:
        from protocol import capacity_extension
    if side not in ('ble','zigbee') or len(data)<26 or data[0]!=0xc1:
        raise ValueError('compact_shape')
    n=data[23]
    if n>(26 if side=='ble' else 6) or len(data)!=26+n:
        raise ValueError('compact_length')
    if binascii.crc_hqx(data[:-2],0xffff)!=int.from_bytes(data[-2:],'little'):
        raise ValueError('app_crc16')
    u=lambda a,b:int.from_bytes(data[a:b],'little')
    run,slot,period,command=u(2,4),u(4,8),u(8,10),u(10,14)
    ref=slot*period; valid=ref+u(19,21); execute=ref+u(21,23)
    target,opcode,arg=u(14,16),data[16],u(17,19)
    if (data[1]!=1 or not run or not period or not command or not target or
        opcode>2 or (opcode==0 and arg!=0) or not ref<=valid<execute<=0xffffffff):
        raise ValueError('compact_semantics')
    if data[24:-2]!=capacity_extension(run,slot,side,n):
        raise ValueError('capacity_content')
    return dict(magic='c1',version=3,format='C1',flags=1,run_id=run,slot_index=slot,
                ref_tick_ms=ref,period_ms=period,command_id=command,target_id=target,
                opcode=opcode,arg=arg,execute_at_ms=execute,valid_until_ms=valid,
                app_crc16=u(len(data)-2,len(data)),record_bytes=len(data),extra_len=n,
                extra_hex=data[24:-2].hex(),capacity_content_ok=True,ieee_marker_offset_us=None)


class BLEControlExtractor:
    """Reassemble only CRC-valid legacy manufacturer frames. Timeout uses IQ seconds.

    Identity includes AdvA/run/command. Completed/conflicting keys remain bounded
    tombstones, preventing subsequent fragments from repairing a known conflict.
    """
    def __init__(self, timeout=2.0, limit=1024):
        self.timeout,self.limit=timeout,limit
        self.pending=OrderedDict();self.closed=OrderedDict();self.counts=Counter()
        self.last_time=None

    def expire(self, now):
        for key,state in list(self.pending.items()):
            if now-state['first']>=self.timeout:
                del self.pending[key];self._close(key);self.counts['timeout']+=1

    def _close(self,key):
        self.closed[key]=True
        while len(self.closed)>self.limit:self.closed.popitem(last=False)

    def finish(self):
        self.counts['incomplete_at_end']+=len(self.pending)
        self.pending.clear()

    def __call__(self,packet):
        try:
            from .analyze import extract_ble
        except ImportError:
            from analyze import extract_ble
        if packet.get('kind')!='legacy':return extract_ble(packet)
        if not packet.get('crc_ok'):return None
        ads=packet.get('extended',{}).get('ad_structures',[])
        candidates=[bytes.fromhex(a['data_hex'])[2:] for a in ads
                    if a.get('type')==255 and a.get('company_id')==65535]
        if not candidates:return None
        if len(candidates)!=1:raise ValueError('compact_legacy_ad')
        data=candidates[0]
        if not data or data[0] not in (0xc1,0xc2):return None
        now=float(packet['sample_time_s'])
        if self.last_time is not None and now<self.last_time:raise ValueError('fragment_time_order')
        self.last_time=now;self.expire(now)
        if data[0]==0xc1:
            if len(data)>27:raise ValueError('legacy_record_length')
            compact_record(data,'ble');return data
        self.counts['fragments']+=1
        if len(data)<11:raise ValueError('fragment_header')
        run=int.from_bytes(data[1:3],'little');command=int.from_bytes(data[3:7],'little')
        index,count,total=data[7:10]
        if not run or not command or not 28<=total<=52 or count!=(total+16)//17 or index>=count or len(data)!=10+min(17,total-index*17):
            raise ValueError('fragment_shape')
        sender=packet['extended'].get('adva')
        if not sender:raise ValueError('fragment_sender')
        key=(sender,run,command)
        if key in self.closed:
            old=self.closed[key]
            if isinstance(old,dict) and ((old['total'],old['count'])!=(total,count) or old['parts'].get(index)!=data[10:]):
                self.counts['conflict']+=1
                raise ValueError('fragment_conflict')
            self.counts['closed_duplicate']+=1;return None
        if key not in self.pending:
            if len(self.pending)>=self.limit:
                old,_=self.pending.popitem(last=False);self._close(old);self.counts['evicted']+=1
            self.pending[key]=dict(first=now,total=total,count=count,parts={})
        state=self.pending[key];parts=state['parts']
        if (state['total'],state['count'])!=(total,count) or (index in parts and parts[index]!=data[10:]):
            del self.pending[key];self._close(key);self.counts['conflict']+=1
            raise ValueError('fragment_conflict')
        if index in parts:self.counts['duplicate']+=1
        parts[index]=data[10:]
        if len(parts)!=count:return None
        del self.pending[key];self._close(key);self.closed[key]=state
        record=b''.join(parts[i] for i in range(count))
        decoded=compact_record(record,'ble')
        if (decoded['run_id'],decoded['command_id'])!=(run,command):raise ValueError('fragment_identity')
        packet['compact_reassembly']={'first_sample_time_s':state['first'],
            'last_sample_time_s':now,'span_s':now-state['first'],'fragment_count':count}
        self.counts['complete']+=1
        return record
