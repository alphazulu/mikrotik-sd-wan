"""Verify complete Ethernet/IPv4/TCP checksums in a private TAP capture."""
import argparse,json,struct
from pathlib import Path

def good(blob):
 if len(blob)%2:blob+=b'\0'
 n=sum(struct.unpack('!%dH'%(len(blob)//2),blob));n=(n&65535)+(n>>16);n=(n&65535)+(n>>16);return n==65535

def inspect(path):
 r={'ethernet_frames':0,'ethernet_over_1514':0,'ipv4_tcp_packets':0,'tcp_checksum_invalid':0,'ipv4_checksum_invalid':0,'fragmented_tcp_unchecked':0}
 with Path(path).open('rb') as f:
  header=f.read(24)
  if len(header)!=24 or header[:4]!=b'\xd4\xc3\xb2\xa1' or struct.unpack('<I',header[20:24])[0]!=1:raise ValueError('Require little-endian Ethernet pcap')
  while h:=f.read(16):
   if len(h)!=16:raise ValueError('Truncated packet header')
   _,_,size,original=struct.unpack('<IIII',h);b=f.read(size)
   if len(b)!=size or size!=original or size<14:raise ValueError('Truncated Ethernet frame')
   r['ethernet_frames']+=1;r['ethernet_over_1514']+=size>1514
   if b[12:14]!=b'\x08\x00':continue
   ip=b[14:]
   if len(ip)<20:raise ValueError('Truncated IPv4 header')
   ihl=(ip[0]&15)*4;length=int.from_bytes(ip[2:4],'big')
   if ip[0]>>4!=4 or not 20<=ihl<=len(ip) or not ihl<=length<=len(ip):raise ValueError('Invalid IPv4 length')
   r['ipv4_checksum_invalid']+=not good(ip[:ihl])
   if ip[9]!=6:continue
   if int.from_bytes(ip[6:8],'big')&0x3fff:r['fragmented_tcp_unchecked']+=1;continue
   tcp=ip[ihl:length]
   if len(tcp)<20:raise ValueError('Truncated TCP header')
   pseudo=ip[12:20]+bytes([0,6])+struct.pack('!H',len(tcp));r['ipv4_tcp_packets']+=1;r['tcp_checksum_invalid']+=not good(pseudo+tcp)
 r['pass']=r['ipv4_tcp_packets']>0 and all(r[k]==0 for k in ['ethernet_over_1514','tcp_checksum_invalid','ipv4_checksum_invalid','fragmented_tcp_unchecked'])
 return r

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('capture',type=Path);p.add_argument('--output',type=Path,required=True);a=p.parse_args();result=inspect(a.capture)
 with a.output.open('x') as f:json.dump(result,f,indent=2)
 print(json.dumps(result));raise SystemExit(0 if result['pass'] else 1)
