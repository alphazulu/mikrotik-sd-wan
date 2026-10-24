//! Small GET-only HTTP/1.0 server. Every response closes the connection.
use super::state::{Store,Status,History,Events,Export};
use crate::telemetry_config::Network;
use serde::Serialize;
use std::collections::BTreeMap;
use std::io::{self,Read,Write,BufWriter};
use std::net::{TcpListener,TcpStream,IpAddr};
use std::sync::{Arc,Mutex};
use std::sync::atomic::{AtomicBool,Ordering};
use std::time::{Duration,Instant};

const HEADER_LIMIT:usize=4096;
const BODY_LIMIT:usize=1048576;
const HTML:&str=include_str!("../../web/index.html");
const JS:&str=include_str!("../../web/app.js");
const CSS:&str=include_str!("../../web/style.css");
#[derive(Debug,PartialEq)] struct Request {target:String,authorization:Option<String>}
fn parse(data:&[u8])->Result<Request,u16>{
    let data=std::str::from_utf8(data).map_err(|_|400u16)?;
    let mut lines=data.split("\r\n");let first=lines.next().ok_or(400u16)?;
    let parts:Vec<_>=first.split(' ').collect();
    if parts.len()!=3||!matches!(parts[2],"HTTP/1.0"|"HTTP/1.1"){return Err(400);}
    if parts[0]!="GET"{return Err(405);}
    if !parts[1].starts_with('/')||parts[1].len()>256||parts[1].bytes().any(|c|c<=32||c>=127||c==b'%'){return Err(400);}
    let mut headers=BTreeMap::new();
    for line in lines.take_while(|s|!s.is_empty()){
        let (name,value)=line.split_once(':').ok_or(400u16)?;
        if name.is_empty()||!name.bytes().all(|c|c.is_ascii_alphanumeric()||c==b'-')||value.bytes().any(|c|c<32&&c!=b'\t'||c==127){return Err(400);}
        if headers.insert(name.to_ascii_lowercase(),value.trim()).is_some(){return Err(400);}
    }
    let host=headers.get("host").ok_or(400u16)?;
    if host.is_empty()||host.len()>128||!host.bytes().all(|c|c.is_ascii_alphanumeric()||b".-:[]".contains(&c)){return Err(400);}
    if headers.contains_key("transfer-encoding")||headers.contains_key("expect")||headers.get("content-length").is_some_and(|s|*s!="0"){return Err(400);}
    if headers.get("sec-fetch-site").is_some_and(|s|s.eq_ignore_ascii_case("cross-site")){return Err(403);}
    if let Some(origin)=headers.get("origin"){
        if !origin.strip_prefix("http://").or_else(||origin.strip_prefix("https://")).is_some_and(|s|s.eq_ignore_ascii_case(host)){return Err(403);}
    }
    Ok(Request{target:parts[1].into(),authorization:headers.get("authorization").map(|s|s.to_string())})
}
fn authorized(value:Option<&str>,token:&str)->bool {
    let Some((scheme,value))=value.and_then(|s|s.split_once(' '))else{return false;};
    if !scheme.eq_ignore_ascii_case("Bearer")||value.len()!=token.len(){return false;}
    value.bytes().zip(token.bytes()).fold(0u8,|a,(x,y)|a|(x^y))==0
}
fn request(stream:&mut TcpStream)->Result<Request,u16>{
    let deadline=Instant::now()+Duration::from_millis(250);let mut data=Vec::with_capacity(1024);let mut part=[0u8;1024];
    loop {
        let remaining=deadline.checked_duration_since(Instant::now()).ok_or(408u16)?;
        stream.set_read_timeout(Some(remaining)).map_err(|_|400u16)?;
        let n=stream.read(&mut part).map_err(|_|408u16)?;if n==0{return Err(400);}
        data.extend_from_slice(&part[..n]);if data.len()>HEADER_LIMIT{return Err(431);}
        if let Some(end)=data.windows(4).position(|s|s==b"\r\n\r\n"){
            if end+4!=data.len(){return Err(400);}return parse(&data);
        }
    }
}
fn headers(stream:&mut impl Write,code:u16,mime:&str,attachment:bool)->io::Result<()>{
    let reason=match code{200=>"OK",400=>"Bad Request",401=>"Unauthorized",403=>"Forbidden",404=>"Not Found",405=>"Method Not Allowed",408=>"Request Timeout",429=>"Too Many Requests",431=>"Request Header Fields Too Large",503=>"Service Unavailable",_=>"Error"};
    write!(stream,"HTTP/1.0 {code} {reason}\r\nContent-Type: {mime}\r\nConnection: close\r\nCache-Control: no-store\r\nX-Content-Type-Options: nosniff\r\nReferrer-Policy: no-referrer\r\nX-Frame-Options: DENY\r\nContent-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'\r\n")?;
    if code==401{write!(stream,"WWW-Authenticate: Bearer realm=\"sdwan\"\r\n")?;}
    if code==405{write!(stream,"Allow: GET\r\n")?;}
    if code==429{write!(stream,"Retry-After: 1\r\n")?;}
    if attachment{write!(stream,"Content-Disposition: attachment; filename=\"sdwan-statistics.json\"\r\n")?;}
    write!(stream,"\r\n")
}
struct Deadline<'a>{stream:&'a mut TcpStream,end:Instant,bytes:usize}
impl Write for Deadline<'_>{
    fn write(&mut self,data:&[u8])->io::Result<usize>{
        if data.len()>BODY_LIMIT.saturating_sub(self.bytes){return Err(io::Error::other("HTTP response limit"));}
        let remaining=self.end.checked_duration_since(Instant::now()).ok_or_else(||io::Error::new(io::ErrorKind::TimedOut,"HTTP deadline"))?;
        self.stream.set_write_timeout(Some(remaining.min(Duration::from_millis(250))))?;
        let n=self.stream.write(data)?;self.bytes+=n;Ok(n)
    }
    fn flush(&mut self)->io::Result<()>{self.stream.flush()}
}
#[derive(Serialize)] #[serde(untagged)] enum Data{Status(Status),History(History),Events(Events),Export(Export)}
fn query(value:&str,allowed:&str,default:u64,max:u64)->Result<u64,u16>{
    if value.is_empty(){return Ok(default);}
    let (key,value)=value.split_once('=').ok_or(400u16)?;
    if key!=allowed||value.is_empty()||!value.bytes().all(|c|c.is_ascii_digit()) {return Err(400);}
    let value=value.parse::<u64>().map_err(|_|400u16)?;
    if value>max||(allowed=="max"&&value==0){return Err(400);}Ok(value)
}
fn json(target:&str,store:&Arc<Mutex<Store>>)->Result<(Data,bool),u16>{
    let (path,args)=target.split_once('?').unwrap_or((target,""));
    // Never hold a lock during parsing a request, socket I/O or serialization.
    let store=store.try_lock().map_err(|_|503u16)?;
    match path {
        "/api/status" if args.is_empty()=>Ok((Data::Status(store.status(Instant::now())),false)),
        "/api/history"=>Ok((Data::History(store.history(query(args,"max",120,600)? as usize)),false)),
        "/api/events"=>Ok((Data::Events(store.events(query(args,"since",0,u64::MAX)?)),false)),
        "/api/export" if args.is_empty()=>Ok((Data::Export(store.export()),true)),
        "/api/status"|"/api/export"=>Err(400),_=>Err(404)
    }
}
fn plain(stream:&mut TcpStream,code:u16)->io::Result<()>{
    let mut writer=Deadline{stream,end:Instant::now()+Duration::from_millis(250),bytes:0};headers(&mut writer,code,"text/plain; charset=utf-8",false)?;writer.write_all(b"Request unavailable\n")
}
fn respond(stream:&mut TcpStream,request:Request,token:&str,store:&Arc<Mutex<Store>>)->io::Result<()>{
    let asset=match request.target.as_str(){"/"=>Some((HTML,"text/html; charset=utf-8")),"/app.js"=>Some((JS,"text/javascript; charset=utf-8")),"/style.css"=>Some((CSS,"text/css; charset=utf-8")),_=>None};
    if let Some((data,mime))=asset {let mut writer=Deadline{stream,end:Instant::now()+Duration::from_secs(1),bytes:0};headers(&mut writer,200,mime,false)?;return writer.write_all(data.as_bytes());}
    if !authorized(request.authorization.as_deref(),token){return plain(stream,401);}
    match json(&request.target,store){
        Ok((data,attachment))=>{
            let writer=Deadline{stream,end:Instant::now()+Duration::from_secs(2),bytes:0};let mut writer=BufWriter::with_capacity(8192,writer);
            headers(&mut writer,200,"application/json; charset=utf-8",attachment)?;
            serde_json::to_writer(&mut writer,&data).map_err(io::Error::other)?;writer.flush()
        },Err(code)=>plain(stream,code)
    }
}
struct Bucket {at:Instant,tokens:f64}
impl Bucket {fn new()->Self{Self{at:Instant::now(),tokens:8.0}}fn allow(&mut self)->bool{let now=Instant::now();self.tokens=(self.tokens+now.saturating_duration_since(self.at).as_secs_f64()*2.0).min(8.0);self.at=now;if self.tokens<1.0{false}else{self.tokens-=1.0;true}}}
pub(super) fn serve(listener:TcpListener,store:Arc<Mutex<Store>>,token:String,networks:Vec<Network>,stop:Arc<AtomicBool>){
    let mut bucket=Bucket::new();
    while !stop.load(Ordering::Relaxed){
        match listener.accept(){
            Ok((mut stream,peer))=>{
                let _=stream.set_nodelay(true);
                let allowed=match peer.ip(){IpAddr::V4(ip)=>networks.iter().any(|n|n.contains(ip)),_=>false};
                if !allowed{let _=plain(&mut stream,403);continue;}
                if !bucket.allow(){let _=plain(&mut stream,429);continue;}
                match request(&mut stream){Ok(request)=>{let _=respond(&mut stream,request,&token,&store);},Err(code)=>{let _=plain(&mut stream,code);}}
            },
            Err(e) if e.kind()==io::ErrorKind::WouldBlock=>std::thread::sleep(Duration::from_millis(10)),
            Err(_)=>break
        }
    }
}

#[cfg(test)] mod tests {
    use super::*;
    #[test] fn auth_methods_origins_and_ambiguous_headers_are_rejected(){
        let token="a".repeat(64);assert!(authorized(Some(&format!("Bearer {token}")),&token));assert!(!authorized(Some("Bearer wrong"),&token));assert!(!authorized(None,&token));
        for text in ["POST /api/status HTTP/1.1\r\nHost: x\r\n\r\n","GET / HTTP/1.1\r\nHost: x\r\nOrigin: http://evil\r\n\r\n","GET / HTTP/1.1\r\nHost: x\r\nAuthorization: a\r\nAuthorization: b\r\n\r\n","GET / HTTP/1.1\r\nHost: x\r\nTransfer-Encoding: chunked\r\n\r\n"] {assert!(parse(text.as_bytes()).is_err());}
        assert!(parse(b"GET /api/status HTTP/1.1\r\nHost: x\r\nOrigin: http://x\r\n\r\n").is_ok());
    }
    #[test] fn query_limits_do_not_allow_tokens_or_unbounded_history(){
        let store=Arc::new(Mutex::new(Store::new("default".into(),10,360)));
        for target in ["/api/history?max=0","/api/history?max=601","/api/status?token=secret","/api/events?since=1&since=2"]{assert!(json(target,&store).is_err());}
        assert!(json("/api/history?max=600",&store).is_ok());
        let _guard=store.lock().unwrap();assert!(matches!(json("/api/status",&store),Err(503)));
    }
    #[test] fn static_assets_are_embedded_and_dynamic_html_is_not_used(){
        assert!(HTML.contains("/app.js"));assert!(!JS.contains("innerHTML"));assert!(!JS.contains("localStorage"));assert!(!JS.contains("sessionStorage"));assert!(!HTML.contains("https://"));assert!(!JS.contains("console.log"));
    }
    #[test] fn slow_headers_have_an_absolute_deadline(){
        let listener=TcpListener::bind("127.0.0.1:0").unwrap();let addr=listener.local_addr().unwrap();
        let thread=std::thread::spawn(move||{let(mut s,_)=listener.accept().unwrap();let start=Instant::now();let error=request(&mut s).unwrap_err();assert_eq!(error,408);assert!(start.elapsed()<Duration::from_secs(2));});
        let mut client=TcpStream::connect(addr).unwrap();client.write_all(b"G").unwrap();std::thread::sleep(Duration::from_millis(500));drop(client);thread.join().unwrap();
    }
    #[test] fn loopback_server_enforces_auth_routes_and_response_headers(){
        let listener=TcpListener::bind("127.0.0.1:0").unwrap();let address=listener.local_addr().unwrap();
        listener.set_nonblocking(true).unwrap();
        let store=Arc::new(Mutex::new(Store::new("default".into(),10,360)));let stop=Arc::new(AtomicBool::new(false));let server_stop=stop.clone();
        let token="a".repeat(64);let key=token.clone();let server=std::thread::spawn(move||serve(listener,store,key,vec![Network::parse("127.0.0.0/8").unwrap()],server_stop));
        for (target,authorization,expected) in [("/","",200),("/api/status","",401),("/api/status",token.as_str(),200),("/api/export",token.as_str(),200),("/missing",token.as_str(),404)]{
            let mut client=TcpStream::connect(address).unwrap();client.set_read_timeout(Some(Duration::from_secs(2))).unwrap();
            write!(client,"GET {target} HTTP/1.1\r\nHost: localhost\r\nAuthorization: Bearer {authorization}\r\n\r\n").unwrap();
            let mut response=String::new();client.read_to_string(&mut response).unwrap();assert!(response.starts_with(&format!("HTTP/1.0 {expected} ")));assert!(response.contains("Cache-Control: no-store"));assert!(!response.contains(&token));
            if target=="/api/export"{assert!(response.contains("Content-Disposition: attachment"));let (_,body)=response.split_once("\r\n\r\n").unwrap();assert!(serde_json::from_str::<serde_json::Value>(body).is_ok());}
        }
        stop.store(true,Ordering::Relaxed);server.join().unwrap();
    }
}
