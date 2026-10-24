use std::collections::BTreeMap;
use std::fs;
use std::io::{self, Read};
use std::net::{SocketAddr,UdpSocket};
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool,Ordering};
use std::time::{Duration,Instant};
use serde::Deserialize;
use sdwan_router_controller::{api::Api,model::{self,Config,Metrics,Intent}};

static STOP:AtomicBool=AtomicBool::new(false);
extern "C" fn stop(_:libc::c_int) { STOP.store(true,Ordering::Relaxed); }
#[derive(Clone,Copy,Deserialize,PartialEq,Default)]
#[serde(rename_all="lowercase")]
enum Mode { #[default] Shadow, Active }
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Settings {
    endpoint:SocketAddr, identity:String, username:String, password_file:PathBuf,
    #[serde(default)] mode:Mode,
    #[serde(default="poll_ms")] poll_ms:u64,
    #[serde(default="heartbeat_port")] heartbeat_port:u16,
    #[serde(default)] metrics_every_seconds:u64,
    #[serde(default)] telemetry:Option<sdwan_router_controller::telemetry_config::Settings>,
}
fn poll_ms()->u64 {1000}
fn heartbeat_port()->u16 {45999}
fn invalid(message:&'static str)->io::Error {io::Error::new(io::ErrorKind::InvalidData,message)}
fn read_limited(path:impl AsRef<std::path::Path>,limit:u64)->io::Result<String> {
    let mut bytes=Vec::new();fs::File::open(path)?.take(limit+1).read_to_end(&mut bytes)?;
    if bytes.len() as u64>limit {return Err(invalid("Mounted controller file exceeds size limit"));}
    String::from_utf8(bytes).map_err(|_|invalid("Controller file is not UTF-8"))
}
fn nonce()->io::Result<String> {
    let mut bytes=[0u8;16];fs::File::open("/dev/urandom")?.read_exact(&mut bytes)?;
    Ok(bytes.iter().map(|b|format!("{b:02x}")).collect())
}
fn resources()->serde_json::Value {
    let status=fs::read_to_string("/proc/self/status").unwrap_or_default();
    let rss=status.lines().find(|l|l.starts_with("VmRSS:")).and_then(|l|l.split_whitespace().nth(1)).and_then(|s|s.parse::<u64>().ok()).map(|n|n*1024);
    let stat=fs::read_to_string("/proc/self/stat").unwrap_or_default();
    let ticks=stat.rsplit_once(')').map(|(_,tail)|tail.split_whitespace().collect::<Vec<_>>()).and_then(|fields|Some(fields.get(11)?.parse::<u64>().ok()?+fields.get(12)?.parse::<u64>().ok()?));
    serde_json::json!({"rss_bytes":rss,"cpu_ticks":ticks})
}

fn service(settings:Settings)->Result<(),Box<dyn std::error::Error>> {
    if !(500..=2000).contains(&settings.poll_ms) || settings.identity.is_empty() || settings.username.is_empty() {return Err(invalid("Invalid controller identity/poll interval (500..2000 ms)").into());}
    #[cfg(feature="web")]
    let web=settings.telemetry.clone().and_then(|cfg|{
        let observer=sdwan_router_controller::web::Observer{endpoint:settings.endpoint,identity:settings.identity.clone(),username:settings.username.clone(),password_file:settings.password_file.clone()};
        match sdwan_router_controller::web::Runtime::start(cfg,observer){Ok(runtime)=>runtime,Err(_)=>{eprintln!("Optional web telemetry unavailable; routing continues");None}}
    });
    #[cfg(not(feature="web"))]
    if settings.telemetry.as_ref().is_some_and(|cfg|cfg.enabled){eprintln!("Web feature is absent from this image; routing continues");}
    let instance=nonce()?;
    let heartbeat=SocketAddr::new(settings.endpoint.ip(),settings.heartbeat_port);
    let socket=UdpSocket::bind(if heartbeat.is_ipv4(){"0.0.0.0:0"}else{"[::]:0"})?;
    socket.set_write_timeout(Some(Duration::from_secs(1)))?;
    let mut api:Option<Api>=None;
    let mut config:Option<Config>=None;
    let mut config_key=String::new();
    let mut last_written:Option<(String,u64,BTreeMap<String,String>)>=None;
    let mut last_claim:Option<Instant>=None;
    let mut last_observed:Option<(u64,Instant)>=None;
    let mut last_state=String::new();
    let mut seq=0u64;
    let mut last_metrics=Instant::now();
    while !STOP.load(Ordering::Relaxed) {
        let begin=Instant::now();
        let cycle=(||->Result<String,Box<dyn std::error::Error>> {
            if api.is_none() {
                // Read exactly; provisioning writes the password without a newline.
                let password=read_limited(&settings.password_file,4096)?;
                let mut client=Api::connect(settings.endpoint,&settings.username,&password)?;
                if client.identity()?!=settings.identity {return Err(invalid("Router identity differs from configured identity").into());}
                api=Some(client);config=None;config_key.clear();last_written=None;
            }
            let client=api.as_mut().ok_or_else(||invalid("API session unavailable"))?;
            let raw=client.environment("sdwanStatusJSON")?.ok_or_else(||invalid("Controller metrics not initialized"))?;
            let metrics:Metrics=serde_json::from_str(&raw)?;
            #[cfg(feature="web")]
            if let Some(web)=&web{web.observe(raw);}
            if let Some((uptime,since))=&last_observed {
                if *uptime==metrics.uptime_seconds && since.elapsed()>Duration::from_secs(10) {return Err(invalid("Router controller telemetry stalled").into());}
            }
            if last_observed.as_ref().is_none_or(|(t,_)|*t!=metrics.uptime_seconds) {last_observed=Some((metrics.uptime_seconds,Instant::now()));}
            let key=metrics.container.as_ref().map(|b|format!("{}:{}:{}",b.boot_id,b.generation,metrics.revision)).unwrap_or_else(||metrics.revision.clone());
            if config.is_none() || key!=config_key {config=Some(serde_json::from_str(&client.active_config()?)?);config_key=key;}
            let cfg=config.as_ref().ok_or_else(||invalid("Configuration unavailable"))?;
            let plan=model::choose(cfg,&metrics)?;
            if settings.mode==Mode::Shadow {
                let state=format!("shadow:{}",serde_json::to_string(&plan)?);
                if state!=last_state {println!("{}",serde_json::json!({"mode":"shadow","revision":metrics.revision,"selected":plan,"writes":0}));}
                return Ok(state);
            }
            let Some(bridge)=metrics.container.as_ref().filter(|b|b.protocol==1) else {return Ok("waiting for provisioned RouterOS bridge protocol1; no writes".into())};
            if !bridge.owner_instance.is_empty() && bridge.owner_instance!=instance && bridge.lease_remaining_seconds>0 {return Ok("another controller owns the live lease; no writes or heartbeat".into());}
            if bridge.lease_remaining_seconds==0 {
                // Confirm the RAM heartbeat path before writing any claim.
                // An isolated/filtered UDP path must never trigger flash writes
                // on every poll while RouterOS correctly falls back to native.
                socket.send_to(b"s",heartbeat)?;
                return Ok("waiting for RAM heartbeat lease; no intent writes".into());
            }
            let changed=last_written.as_ref().is_none_or(|(boot,generation,selected)|boot!=&bridge.boot_id || *generation!=bridge.generation || selected!=&plan);
            let retry_claim=bridge.owner_instance.is_empty() && last_claim.is_none_or(|since|since.elapsed()>=Duration::from_secs(6));
            if changed || retry_claim {
                seq=seq.checked_add(1).ok_or_else(||invalid("Intent sequence exhausted"))?;
                let intent=Intent{protocol:1,instance:&instance,seq,boot_id:&bridge.boot_id,generation:bridge.generation,observed_uptime:metrics.uptime_seconds,revision:&cfg.revision,selected:&plan,release:false};
                client.write_intent(&bridge.intent_file,&serde_json::to_string(&intent)?)?;
                last_written=Some((bridge.boot_id.clone(),bridge.generation,plan.clone()));
                last_claim=Some(Instant::now());
            }
            // Liveness is RAM-only on RouterOS, not a periodic flash write.
            socket.send_to(b"s",heartbeat)?;
            let state=format!("active:{}",serde_json::to_string(&plan)?);
            if state!=last_state {println!("{}",serde_json::json!({"mode":"active","revision":metrics.revision,"selected":plan}));}
            Ok(state)
        })();
        match cycle {
            Ok(state)=>{if state!=last_state && !state.starts_with("shadow:") && !state.starts_with("active:"){eprintln!("{state}");}last_state=state;},
            Err(error)=>{
                let state=format!("unavailable: {error}");if state!=last_state {eprintln!("{state}; heartbeat stopped, native fallback remains responsible");}
                last_state=state;api=None;config=None;last_written=None;
            }
        }
        if settings.metrics_every_seconds>0 && last_metrics.elapsed()>=Duration::from_secs(settings.metrics_every_seconds) {println!("{}",serde_json::json!({"resources":resources(),"mode":if settings.mode==Mode::Shadow{"shadow"}else{"active"}}));last_metrics=Instant::now();}
        if let Some(delay)=Duration::from_millis(settings.poll_ms).checked_sub(begin.elapsed()) {std::thread::sleep(delay);}
    }
    // A crashed process is handled by lease expiry. A graceful release is a
    // single optional write; it never changes routes directly.
    Ok(())
}

fn main() {
    unsafe {libc::signal(libc::SIGTERM,stop as *const () as libc::sighandler_t);libc::signal(libc::SIGINT,stop as *const () as libc::sighandler_t);}
    let args:Vec<String>=std::env::args().collect();
    let result=(||->Result<(),Box<dyn std::error::Error>> {
        match args.get(1).map(String::as_str) {
            Some("--version")=>println!("sdwan-router-controller {} web={}",env!("CARGO_PKG_VERSION"),cfg!(feature="web")),
            Some("plan") if args.len()==4=>{
                let metrics:Metrics=serde_json::from_str(&read_limited(&args[2],1048576)?)?;
                let config:Config=serde_json::from_str(&read_limited(&args[3],1048576)?)?;
                println!("{}",serde_json::to_string(&model::choose(&config,&metrics)?)?);
            }
            Some("run") if args.len()==3=>service(serde_json::from_str(&read_limited(&args[2],65536)?)?)?,
            _=>return Err(invalid("Usage: sdwan-controller run SETTINGS.json | plan STATUS.json CONFIG.json | --version").into()),
        }
        Ok(())
    })();
    if let Err(error)=result {eprintln!("{error}");std::process::exit(1);}
}
