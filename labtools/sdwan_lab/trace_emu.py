"""Transparent in-memory protocol metadata trace; never logs Ethernet payloads."""
import argparse
from collections import defaultdict, deque
import json
from pathlib import Path
import signal
import struct
import sys
import time


def main():
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True)
    p.add_argument('--trace',type=Path,required=True);p.add_argument('--port-base',type=int,required=True)
    a=p.parse_args();sys.path.insert(0,str(a.source/'lte-rndis-emu'))
    from lte_rndis_emu import usbredir as u
    from lte_rndis_emu.emulator import main as serve
    signal.signal(signal.SIGINT,signal.default_int_handler)
    records=deque(maxlen=50000);expected=defaultdict(deque);counts=defaultdict(int)
    original_handle=u.Session._handle;original_emit=u.Session._emit
    def note(direction,typ,ident,payload,codec):
        row={'monotonic':time.monotonic(),'direction':direction,'type':typ,'id':ident,'bytes':len(payload)}
        if typ==u.BULK:
            row.update(endpoint=payload[0],status=payload[1],length=struct.unpack_from('<H',payload,2)[0])
            if codec.negotiated & u.CAP_32BIT_BULK:row['length']|=struct.unpack_from('<H',payload,8)[0]<<16
            key=payload[0]
            if direction=='request':
                expected[key].append(ident)
                counts['bulk_in_requests' if key&0x80 else 'bulk_out_requests']+=1
                if key&0x80:counts['maximum_bulk_in_length']=max(counts['maximum_bulk_in_length'],row['length'])
            else:
                row['fifo_expected']=expected[key][0] if expected[key] else None
                row['out_of_order']=not expected[key] or expected[key][0]!=ident
                if row['out_of_order']:counts['out_of_order']+=1
                if ident in expected[key]:expected[key].remove(ident)
                if row['status']==u.ST_BABBLE:counts['babble_completions']+=1
        if direction=='request' and typ==u.CANCEL:
            for queue in expected.values():
                if ident in queue:queue.remove(ident)
            counts['cancellations']+=1
        if direction=='request' and typ in (u.RESET,u.HELLO):expected.clear()
        records.append(row);counts['events']+=1
    def handle(self,typ,ident,payload):
        note('request',typ,ident,payload,self.codec);return original_handle(self,typ,ident,payload)
    def emit(self,blob):
        typ,length=struct.unpack_from('<II',blob);wide=self.codec.ids64 and typ!=u.HELLO
        size=16 if wide else 12;ident=struct.unpack_from('<Q' if wide else '<I',blob,8)[0]
        note('completion',typ,ident,blob[size:],self.codec);return original_emit(self,blob)
    u.Session._handle=handle;u.Session._emit=emit
    try:
        return serve(['serve','--uplink',f'socket:127.0.0.1:{a.port_base+4}',
                      '--listen',f'127.0.0.1:{a.port_base+2}','--control',f'127.0.0.1:{a.port_base+3}'])
    finally:
        a.trace.write_text(json.dumps({'counts':dict(counts),'trace_truncated':counts['events']>len(records),'records':list(records)},indent=2)+'\n')


if __name__=='__main__':raise SystemExit(main())
