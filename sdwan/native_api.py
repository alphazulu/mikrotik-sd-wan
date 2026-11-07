"""RouterOS sentence API, using the current /login protocol (RouterOS >= 6.43)."""
import socket
import ssl
import struct
import threading
import urllib.parse

MAX_WORD=16*1024*1024


def encode_length(length):
    if not 0 <= length <= 0xFFFFFFFF:raise ValueError('Invalid API word length')
    if length < 0x80:return bytes([length])
    if length < 0x4000:return struct.pack('!H',length|0x8000)
    if length < 0x200000:return (length|0xC00000).to_bytes(3,'big')
    if length < 0x10000000:return struct.pack('!I',length|0xE0000000)
    return b'\xf0'+struct.pack('!I',length)


class NativeAPI:
    def __init__(self,host,port,username,password,tls=False,ca=None):
        self.host=host;self.port=port;self.username=username;self.password=password
        self.tls=tls;self.ca=ca;self.sock=None;self.lock=threading.Lock()

    def close(self):
        if self.sock is not None:
            self.sock.close();self.sock=None

    def _read(self,length):
        chunks=[]
        while length:
            chunk=self.sock.recv(length)
            if not chunk:raise ConnectionError('MikroTik API closed the connection')
            chunks.append(chunk);length-=len(chunk)
        return b''.join(chunks)

    def _word(self,binary=False):
        first=self._read(1)[0]
        if first<0x80:length=first
        elif first<0xC0:length=((first&0x3F)<<8)|self._read(1)[0]
        elif first<0xE0:length=((first&0x1F)<<16)|int.from_bytes(self._read(2),'big')
        elif first<0xF0:length=((first&0x0F)<<24)|int.from_bytes(self._read(3),'big')
        elif first==0xF0:length=int.from_bytes(self._read(4),'big')
        else:raise RuntimeError('Unsupported RouterOS API control byte')
        if length>MAX_WORD:raise RuntimeError('RouterOS API response word exceeds limit')
        data=self._read(length) if length else b''
        return data if binary else data.decode('utf-8',errors='replace')

    def _talk(self,words,binary=False):
        payload=bytearray()
        for word in words:
            data=word if isinstance(word,bytes) else word.encode('utf-8');payload.extend(encode_length(len(data)));payload.extend(data)
        payload.append(0);self.sock.sendall(payload)
        rows=[];errors=[]
        while True:
            sentence=[]
            while True:
                word=self._word(binary=True) if binary else self._word()
                if not word:break
                sentence.append(word)
            if not sentence:continue
            kind=sentence[0].decode('ascii') if binary else sentence[0];values={}
            for word in sentence[1:]:
                marker=b'=' if binary else '='
                if word.startswith(marker):
                    key,_,value=word[1:].partition(marker)
                    if binary:key=key.decode('ascii')
                    values[key]=value
            if kind=='!re':rows.append(values)
            elif kind=='!trap':
                message=values.get('message',b'API command rejected' if binary else 'API command rejected')
                errors.append(message.decode('utf-8',errors='replace') if binary else message)
            elif kind=='!fatal':
                message=values.get('message',b'RouterOS API fatal error' if binary else 'RouterOS API fatal error')
                raise ConnectionError(message.decode('utf-8',errors='replace') if binary else message)
            elif kind=='!done':
                if errors:raise RuntimeError('; '.join(errors))
                return rows,values
            elif kind!='!empty':raise RuntimeError('Unexpected RouterOS API reply '+kind)

    def _connect(self):
        self.sock=socket.create_connection((self.host,self.port),timeout=8)
        self.sock.settimeout(45)
        try:
            if self.tls:
                ctx=ssl.create_default_context(cafile=self.ca)
                self.sock=ctx.wrap_socket(self.sock,server_hostname=self.host)
            self._talk(['/login','=name='+self.username,'=password='+self.password])
        except Exception:
            self.close();raise

    def command(self,command,attributes=None,queries=(),*,binary=False):
        attrs=attributes or {};words=[command]
        for k,v in attrs.items():
            if isinstance(v,bool):v='yes' if v else 'no'
            if isinstance(v,list):v=','.join(str(x) for x in v)
            if isinstance(v,bytes):
                if not binary:raise ValueError('Binary API values require explicit binary mode')
                words.append(('='+k+'=').encode('ascii')+v)
            else:words.append('='+k+'='+str(v))
        words.extend('?'+q for q in queries)
        with self.lock:
            try:
                if self.sock is None:self._connect()
                return self._talk(words,binary=True) if binary else self._talk(words)
            except (OSError,RuntimeError,UnicodeError):
                self.close();raise

    def call(self,path,data=None,method=None):
        """Compatibility with the REST-shaped configuration/deployment client."""
        parsed=urllib.parse.urlsplit('/'+path.lstrip('/'))
        path=parsed.path.strip('/');parts=path.split('/');attrs=dict(data or {})
        method=method or ('POST' if data is not None else 'GET')
        queries=[]
        for k,v in urllib.parse.parse_qsl(parsed.query,keep_blank_values=True):
            if k.startswith('.'):attrs[k]=v
            else:queries.append(k+'='+v)
        singleton=path in ('system/identity','system/resource','ip/dns','ip/ssh','ip/settings','ip/firewall/connection/tracking','certificate/settings')
        if method=='GET':
            identifier=None
            if parts[-1].startswith('*'):
                identifier=parts.pop();queries.append('.id='+identifier)
            rows,_=self.command('/'+'/'.join(parts)+'/print',attrs,queries)
            if singleton or identifier:
                if not rows:raise RuntimeError('API resource not found: '+path)
                return rows[0]
            return rows
        if method in ('PATCH','DELETE'):
            if not parts[-1].startswith('*'):raise ValueError('API mutation requires a resource identifier')
            identifier=parts.pop();menu='/'.join(parts)
            attrs['.id']=identifier
            self.command('/'+menu+('/set' if method=='PATCH' else '/remove'),attrs)
            return self.call(menu+'/'+identifier) if method=='PATCH' else None
        if method=='PUT':
            _,done=self.command('/'+path+'/add',attrs)
            identifier=done.get('ret')
            if identifier:return self.call(path+'/'+identifier)
            return done or []
        if method=='POST':
            extra=attrs.pop('.query',[])
            if isinstance(extra,str):extra=[extra]
            rows,done=self.command('/'+path,attrs,list(queries)+list(extra))
            return rows if rows else (done or [])
        raise ValueError('Unsupported API method '+method)
