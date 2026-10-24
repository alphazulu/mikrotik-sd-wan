//! Optional read-only RAM telemetry, isolated from the routing cycle.
pub mod state;
mod http;
use crate::{api::Api,telemetry_config::Settings};
use state::{Store,Update,Counter,Counters,Resources,MAX_RAW};
use std::fs;
use std::io::{self,Read};
use std::net::{SocketAddr,TcpListener};
use std::path::PathBuf;
use std::sync::{Arc,Mutex,mpsc::{self,SyncSender}};
use std::sync::atomic::{AtomicBool,Ordering};
use std::thread::{self,JoinHandle};
use std::time::{Duration,Instant};

pub struct Observer {pub endpoint:SocketAddr,pub identity:String,pub username:String,pub password_file:PathBuf}
struct Message {raw:String,at:Instant}
pub struct Runtime {sender:Option<SyncSender<Message>>,stop:Arc<AtomicBool>,threads:Vec<JoinHandle<()>>}
fn invalid(message:&'static str)->io::Error{io::Error::new(io::ErrorKind::InvalidData,message)}
fn read(path:impl AsRef<std::path::Path>,limit:u64)->io::Result<String>{
    let mut data=Vec::new();fs::File::open(path)?.take(limit+1).read_to_end(&mut data)?;
    if data.len() as u64>limit{return Err(invalid("Observer mounted file exceeds limit"));}
    String::from_utf8(data).map_err(|_|invalid("Observer file is not UTF-8"))
}
fn resources()->Resources{
    let status=read("/proc/self/status",65536).unwrap_or_default();
    let rss=status.lines().find(|s|s.starts_with("VmRSS:")).and_then(|s|s.split_whitespace().nth(1)).and_then(|s|s.parse::<u64>().ok()).and_then(|n|n.checked_mul(1024));
    let stat=read("/proc/self/stat",8192).unwrap_or_default();
    let ticks=stat.rsplit_once(')').map(|(_,t)|t.split_whitespace().collect::<Vec<_>>()).and_then(|v|Some(v.get(11)?.parse::<u64>().ok()?.saturating_add(v.get(12)?.parse::<u64>().ok()?)));
    let io=read("/proc/self/io",8192).unwrap_or_default();
    let writes=io.lines().find_map(|line|line.strip_prefix("write_bytes:").and_then(|s|s.trim().parse::<u64>().ok()));
    Resources{rss_bytes:rss,cpu_ticks:ticks,write_bytes:writes}
}
fn counters(api:&mut Option<Api>,observer:&Observer,password:&str,value:&Update)->io::Result<Counters>{
    let mut names:Vec<String>=value.samples.0.values().map(|s|s.interface.0.clone()).filter(|s|!s.is_empty()).collect();names.sort();names.dedup();
    if names.is_empty(){return Ok(Counters::new());}
    if api.is_none(){let mut client=Api::connect_observer(observer.endpoint,&observer.username,password)?;if client.identity()?!=observer.identity{return Err(invalid("Observer router identity changed"));}*api=Some(client);}
    let rows=api.as_mut().ok_or_else(||invalid("Observer API unavailable"))?.interface_counters(&names)?;
    let at=Instant::now();let mut out=Counters::new();
    for row in rows {
        let Some(name)=row.get("name").filter(|s|names.contains(s)) else {return Err(invalid("Unexpected observer interface"));};
        let (Some(rx),Some(tx))=(row.get("rx-byte").and_then(|s|s.parse::<u64>().ok()),row.get("tx-byte").and_then(|s|s.parse::<u64>().ok())) else {continue;};
        if out.insert(name.clone(),Counter{at,rx,tx}).is_some(){return Err(invalid("Duplicate observer interface"));}
    }
    Ok(out)
}
impl Runtime {
    pub fn start(settings:Settings,observer:Observer)->io::Result<Option<Self>>{
        if !settings.enabled{return Ok(None);}
        let networks=settings.validate().map_err(invalid)?;
        let token=read(&settings.token_file,4096)?.trim().to_owned();
        if token.len()!=64||!token.bytes().all(|c|c.is_ascii_digit()||(b'a'..=b'f').contains(&c)){return Err(invalid("Dedicated web token must contain 64 lowercase hex characters"));}
        let password=read(&observer.password_file,4096)?;
        if password==token{return Err(invalid("Web token must differ from API password"));}
        let listener=TcpListener::bind(settings.listen)?;listener.set_nonblocking(true)?;
        let store=Arc::new(Mutex::new(Store::new(settings.profile.clone(),settings.sample_seconds,settings.history_points)));
        let stop=Arc::new(AtomicBool::new(false));let(sender,receiver)=mpsc::sync_channel::<Message>(1);
        let http_stop=stop.clone();let http_store=store.clone();let http_token=token.clone();
        let server=thread::Builder::new().name("sdwan-http".into()).stack_size(131072).spawn(move||http::serve(listener,http_store,http_token,networks,http_stop))?;
        let collector_stop=stop.clone();
        let collector=thread::Builder::new().name("sdwan-ram".into()).stack_size(131072).spawn(move||{
            let mut api=None;let mut latest=None;let mut polled=None;
            while !collector_stop.load(Ordering::Relaxed){
                let message=match receiver.recv_timeout(Duration::from_millis(100)){Ok(m)=>m,Err(mpsc::RecvTimeoutError::Timeout)=>continue,Err(_)=>break};
                let value=match Update::parse(&message.raw){Ok(v)=>v,Err(_)=>{if let Ok(mut s)=store.lock(){s.invalid();}continue;}};
                let epoch_changed=store.lock().map(|s|s.epoch_changed(&value)).unwrap_or(false);
                if epoch_changed||polled.is_none_or(|at:Instant|at.elapsed()>=Duration::from_secs(settings.sample_seconds)){
                    latest=match counters(&mut api,&observer,&password,&value){Ok(c)=>Some(c),Err(_)=>{api=None;None}};polled=Some(Instant::now());
                    let usage=resources();if let Ok(mut s)=store.lock(){s.resources=usage;}
                }
                if let Ok(mut s)=store.lock(){s.ingest(value,message.at,latest.as_ref(),&password,&token);}
            }
        });
        match collector {Ok(collector)=>Ok(Some(Self{sender:Some(sender),stop,threads:vec![server,collector]})),Err(error)=>{stop.store(true,Ordering::Relaxed);let _=server.join();Err(error)}}
    }
    /// A full queue or an oversized snapshot is dropped, never awaited.
    pub fn observe(&self,raw:String){if raw.len()<=MAX_RAW{if let Some(sender)=&self.sender{let _=sender.try_send(Message{raw,at:Instant::now()});}}}
}
impl Drop for Runtime {fn drop(&mut self){self.stop.store(true,Ordering::Relaxed);self.sender.take();for thread in self.threads.drain(..){let _=thread.join();}}}

#[cfg(test)] mod tests {
    use super::*;
    #[test] fn disabled_runtime_reads_no_files_and_opens_no_listener(){
        let settings=Settings::default();let observer=Observer{endpoint:"127.0.0.1:1".parse().unwrap(),identity:"test".into(),username:"test".into(),password_file:"/missing".into()};
        assert!(Runtime::start(settings,observer).unwrap().is_none());
    }
    #[test] fn full_handoff_drops_immediately(){
        let (sender,_receiver)=mpsc::sync_channel(1);let runtime=Runtime{sender:Some(sender),stop:Arc::new(AtomicBool::new(false)),threads:vec![]};let start=Instant::now();
        for _ in 0..10000{runtime.observe("{}".into());}assert!(start.elapsed()<Duration::from_secs(1));
    }
}
