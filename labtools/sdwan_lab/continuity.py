"""External echo continuity measurement. All times use the client's monotonic clock."""
import argparse
import ipaddress
import json
import selectors
import socket
import struct
import time
import uuid
from pathlib import Path

PACKET=struct.Struct('!4s16sQ')
MAGIC=b'SDW1'


def analyze(events, duration_ns, interval_ns):
    result={}
    for protocol in ('udp','tcp'):
        sent={};received={};duplicates=0;reordered=0;highest=-1;sessions=set();disconnects=0
        for e in events:
            if e['protocol']!=protocol:continue
            if e['event']=='connected':sessions.add(e['session'])
            elif e['event']=='disconnected':disconnects+=1
            elif e['event'] in ('sent','offered'):sent[e['seq']]=e['ns']
            elif e['event']=='received' and e['seq'] in sent:
                if e['seq'] in received:duplicates+=1;continue
                if e['seq']<highest:reordered+=1
                highest=max(highest,e['seq']);received[e['seq']]=e['ns']
        stamps=sorted(received.values());rtts=[(t-sent[q])/1e6 for q,t in received.items()]
        gaps=[b-a for a,b in zip(stamps,stamps[1:])]
        result[protocol]={'offered':len(sent),'received':len(received),'unanswered':len(set(sent)-set(received)),
          'duplicates':duplicates,'reordered':reordered,'established_sessions':len(sessions),'disconnects':disconnects,
          'first_success_ms':stamps[0]/1e6 if stamps else None,
          'max_success_gap_ms':max(gaps)/1e6 if gaps else None,
          'max_gap_above_interval_ms':max(0,max(gaps)-interval_ns)/1e6 if gaps else None,
          'trailing_silence_ms':max(0,duration_ns-stamps[-1])/1e6 if stamps else duration_ns/1e6,
          'rtt_max_ms':max(rtts) if rtts else None}
    return {'protocols':result,'scope':'echo observations, not exact network outage; gap includes probe interval, RTT and scheduling',
            'single_client_clock':True,'tcp_offered_is_application_queue_not_wire_transmission':True,'interval_ms':interval_ns/1e6,'duration_ms':duration_ns/1e6}


def serve(host,port):
    sel=selectors.DefaultSelector();tcp=socket.socket();udp=socket.socket(type=socket.SOCK_DGRAM)
    tcp.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
    clients={}
    try:
        tcp.bind((host,port));port=tcp.getsockname()[1];tcp.listen(16);udp.bind((host,port))
        for sock in (tcp,udp):sock.setblocking(False);sel.register(sock,selectors.EVENT_READ)
        print(f'ready {host}:{port}',flush=True)
        while True:
            for key,mask in sel.select(.1):
                sock=key.fileobj
                if sock is udp:
                    data,peer=udp.recvfrom(2048)
                    if len(data)==PACKET.size and data[:4]==MAGIC:udp.sendto(data,peer)
                elif sock is tcp:
                    client,_=tcp.accept();client.setblocking(False);clients[client]=bytearray();sel.register(client,selectors.EVENT_READ)
                else:
                    try:
                        if mask&selectors.EVENT_READ:
                            data=sock.recv(4096)
                            if not data:raise ConnectionError('EOF')
                            clients[sock].extend(data)
                            if len(clients[sock])>65536:raise ConnectionError('Echo backlog limit')
                        if mask&selectors.EVENT_WRITE and clients[sock]:
                            n=sock.send(clients[sock]);del clients[sock][:n]
                        sel.modify(sock,selectors.EVENT_READ|(selectors.EVENT_WRITE if clients[sock] else 0))
                    except (ConnectionError,OSError):sel.unregister(sock);clients.pop(sock,None);sock.close()
    except KeyboardInterrupt:return
    finally:
        for sock in list(clients)+[tcp,udp]:sock.close()
        sel.close()


def measure(host,port,seconds,interval_ms,drain_seconds=2,source_address=None):
    if not 1<=seconds<=3600 or not 5<=interval_ms<=1000 or seconds*1000/interval_ms>30000:raise ValueError('seconds 1..3600, interval-ms 5..1000, at most 30000 probes/protocol')
    if source_address is not None:
        source_address=str(ipaddress.IPv4Address(source_address))
        parsed=ipaddress.IPv4Address(source_address)
        if parsed.is_unspecified or parsed.is_multicast:raise ValueError('Source must identify a unicast IPv4 address')
    # DNS resolution occurs before measurement. Each reply must match this run's nonce.
    host=socket.gethostbyname(host);token=uuid.uuid4().bytes;events=[];origin=time.monotonic_ns();interval=int(interval_ms*1e6)
    end=origin+int(seconds*1e9);finish=end+int(drain_seconds*1e9);next_send=origin;retry=origin
    udp=socket.socket(type=socket.SOCK_DGRAM)
    try:
        if source_address is not None:udp.bind((source_address,0))
        udp.connect((host,port));udp.setblocking(False)
    except BaseException:
        udp.close();raise
    udp_tuple={'local':list(udp.getsockname()),'peer':list(udp.getpeername())}
    tcp=None;seq=0;session=0;buffer=bytearray();out=bytearray()
    def event(proto,kind,**extra):events.append(dict(protocol=proto,event=kind,ns=time.monotonic_ns()-origin,**extra))
    try:
        while time.monotonic_ns()<finish:
            now=time.monotonic_ns()
            if tcp is None and now>=retry and now<end:
                try:
                    tcp=socket.create_connection((host,port),timeout=.1,source_address=(source_address,0) if source_address is not None else None);tcp.setblocking(False);session+=1
                    event('tcp','connected',session=session,local=list(tcp.getsockname()),peer=list(tcp.getpeername()))
                    buffer.clear();out.clear()
                except OSError:
                    if tcp is not None:tcp.close()
                    tcp=None;retry=time.monotonic_ns()+int(200e6)
            if now>=next_send and now<end:
                payload=PACKET.pack(MAGIC,token,seq)
                try:udp.send(payload);event('udp','sent',seq=seq)
                except OSError:event('udp','send_error',seq=seq)
                if tcp is not None:
                    # Queue bounded: do not accumulate traffic during a long TCP stall.
                    if len(out)<4096:out.extend(payload);event('tcp','offered',seq=seq,session=session)
                seq+=1;next_send=max(next_send+interval,time.monotonic_ns())
            try:
                if tcp is not None and out:
                    try:n=tcp.send(out);del out[:n]
                    except BlockingIOError:pass
                if tcp is not None:
                    try:
                        data=tcp.recv(4096)
                        if not data:raise ConnectionError('EOF')
                        buffer.extend(data)
                        while len(buffer)>=PACKET.size:
                            magic,nonce,q=PACKET.unpack(buffer[:PACKET.size]);del buffer[:PACKET.size]
                            if magic!=MAGIC or nonce!=token:raise ConnectionError('Invalid echo')
                            event('tcp','received',seq=q,session=session)
                    except BlockingIOError:pass
            except OSError:
                event('tcp','disconnected',session=session);tcp.close();tcp=None;out.clear();buffer.clear();retry=time.monotonic_ns()+int(200e6)
            for _ in range(256):
                try:
                    data=udp.recv(2048)
                    if len(data)==PACKET.size:
                        magic,nonce,q=PACKET.unpack(data)
                        if magic==MAGIC and nonce==token:event('udp','received',seq=q)
                except BlockingIOError:break
                except OSError as error:event('udp','receive_error',errno=error.errno);break
            time.sleep(.001)
        duration=end-origin
        return dict(analyze(events,duration,interval),events=events,source_address=source_address,udp_tuple=udp_tuple,origin_monotonic_ns=origin,run_token=token.hex(),measurement_seconds=seconds,drain_seconds=drain_seconds)
    finally:
        udp.close()
        if tcp is not None:tcp.close()


def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    s=sub.add_parser('serve');s.add_argument('--listen',default='127.0.0.1');s.add_argument('--port',type=int,default=25351)
    m=sub.add_parser('measure');m.add_argument('--host',required=True);m.add_argument('--port',type=int,default=25351);m.add_argument('--seconds',type=float,default=10);m.add_argument('--interval-ms',type=float,default=20);m.add_argument('--output',type=Path,required=True);m.add_argument('--source-address',help='Existing local IPv4 to select a client/WAN policy')
    a=p.parse_args()
    if a.command=='serve':serve(a.listen,a.port)
    else:
        # Reserve result path before generating traffic, never overwrite another run.
        with a.output.open('x') as stream:
            result=measure(a.host,a.port,a.seconds,a.interval_ms,source_address=a.source_address);json.dump(result,stream,indent=2);stream.write('\n')
        print(json.dumps({k:v for k,v in result.items() if k!='events'},indent=2))

if __name__=='__main__':main()
