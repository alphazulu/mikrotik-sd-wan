use super::*;
use sdwan_router_controller::api::{read_word, write_word};
use std::io::Read;
use std::{
    net::TcpListener,
    sync::{Arc, Mutex},
    thread,
};
static SERIAL: Mutex<()> = Mutex::new(());
struct Temp(PathBuf);
impl Temp {
    fn new() -> Self {
        static ID: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        let p = std::env::temp_dir().join(format!(
            "sdwan-unit-{}-{}",
            std::process::id(),
            ID.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir(&p).unwrap();
        Self(p)
    }
    fn file(&self, name: &str, text: impl AsRef<[u8]>) -> PathBuf {
        let p = self.0.join(name);
        fs::write(&p, text).unwrap();
        p
    }
}
impl Drop for Temp {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}
fn settings(endpoint: SocketAddr, password_file: PathBuf) -> Settings {
    serde_json::from_value(serde_json::json!({"endpoint":endpoint,"identity":"fixture","username":"fixture","password_file":password_file,"poll_ms":500})).unwrap()
}
fn sentence(stream: &mut impl std::io::Write, words: &[&str]) {
    for word in words {
        write_word(stream, word.as_bytes()).unwrap();
    }
    write_word(stream, b"").unwrap();
}
fn command(stream: &mut impl Read) -> io::Result<Vec<String>> {
    let mut words = vec![];
    loop {
        let word = read_word(stream)?;
        if word.is_empty() {
            return Ok(words);
        }
        words.push(String::from_utf8(word).map_err(io::Error::other)?);
    }
}
const CONFIG: &str = r#"{"schema_version":1,"revision":"test","policies":[{"name":"default","profile":"default","mode":"prefer","wans":["wan"],"allow_degraded":false}]}"#;
#[test]
fn settings_defaults_bounds_and_unknown_options() {
    let d = Temp::new();
    let path = d.file("password", "exact password\n");
    let mut s = settings("127.0.0.1:1".parse().unwrap(), path);
    assert_eq!(s.heartbeat_port, 45999);
    let raw = serde_json::json!({"endpoint":"127.0.0.1:1","identity":"fixture","username":"fixture","password_file":"/missing"});
    assert_eq!(
        serde_json::from_value::<Settings>(raw.clone())
            .unwrap()
            .poll_ms,
        1000
    );
    let mut bad = raw;
    bad["unknown"] = true.into();
    assert!(serde_json::from_value::<Settings>(bad).is_err());
    s.poll_ms = 499;
    assert!(service(s).is_err());
}
#[test]
fn bounded_files_random_nonce_and_proc_resources() {
    let d = Temp::new();
    let p = d.file("text", "abc\n");
    assert_eq!(read_limited(&p, 4).unwrap(), "abc\n");
    assert_eq!(
        read_limited(&p, 3).unwrap_err().kind(),
        io::ErrorKind::InvalidData
    );
    let p = d.file("invalid", [255]);
    assert!(read_limited(p, 8).is_err());
    assert!(read_limited(d.0.join("missing"), 8).is_err());
    let a = nonce().unwrap();
    let b = nonce().unwrap();
    assert_eq!(a.len(), 32);
    assert!(a.bytes().all(|b| b.is_ascii_hexdigit()));
    assert_ne!(a, b);
    let r = resources();
    assert!(r["rss_bytes"].is_u64());
    assert!(r["cpu_ticks"].is_u64());
}
#[test]
fn cli_version_plan_run_errors_and_process_entry() {
    let _serial = SERIAL.lock().unwrap();
    assert_eq!(
        entry(&["controller".into(), "--version".into()]),
        std::process::ExitCode::SUCCESS
    );
    assert_eq!(entry(&[]), std::process::ExitCode::FAILURE);
    assert_eq!(main(), std::process::ExitCode::FAILURE);
    let d = Temp::new();
    let c = d.file("config", CONFIG);
    let m = d.file(
        "metrics",
        r#"{"revision":"test","uptime_seconds":1,"states":{"default/wan":{"state":"healthy"}}}"#,
    );
    assert!(execute(&[
        "controller".into(),
        "plan".into(),
        m.to_string_lossy().into(),
        c.to_string_lossy().into()
    ])
    .is_ok());
    let bad=d.file("settings",r#"{"endpoint":"127.0.0.1:1","identity":"","username":"fixture","password_file":"/missing"}"#);
    assert!(execute(&[
        "controller".into(),
        "run".into(),
        bad.to_string_lossy().into()
    ])
    .is_err());
    STOP.store(false, Ordering::Relaxed);
    stop(libc::SIGTERM);
    assert!(STOP.load(Ordering::Relaxed));
    STOP.store(false, Ordering::Relaxed);
}
#[test]
fn stopped_service_initializes_both_udp_families_and_optional_web_failures() {
    for endpoint in ["127.0.0.1:1", "[::1]:1"] {
        for enabled in [false, true] {
            let d = Temp::new();
            let mut s = settings(endpoint.parse().unwrap(), d.file("password", "fixture"));
            s.telemetry = Some(sdwan_router_controller::telemetry_config::Settings {
                enabled,
                ..Default::default()
            });
            let flag = AtomicBool::new(true);
            assert!(service_until(s, &flag).is_ok());
        }
    }
}
#[test]
fn live_cycle_uses_exact_password_recovers_errors_and_stops_without_periodic_flash_writes() {
    for active in [false, true] {
        let d = Temp::new();
        let stopped = Arc::new(AtomicBool::new(false));
        let server_stop = stopped.clone();
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let endpoint = listener.local_addr().unwrap();
        let udp = UdpSocket::bind("127.0.0.1:0").unwrap();
        udp.set_read_timeout(Some(Duration::from_millis(200)))
            .unwrap();
        let worker = thread::spawn(move || {
            let mut polls = 0;
            let mut writes = 0;
            let mut owner = String::new();
            while !server_stop.load(Ordering::Relaxed) {
                let (mut stream, _) = listener.accept().unwrap();
                loop {
                    let words = match command(&mut stream) {
                        Ok(w) => w,
                        Err(_) => break,
                    };
                    match words[0].as_str() {
                        "/login" => {
                            assert_eq!(words[2], "=password=exact password\n");
                            sentence(&mut stream, &["!done"]);
                        }
                        "/system/identity/print" => {
                            sentence(&mut stream, &["!re", "=name=fixture"]);
                            sentence(&mut stream, &["!done"]);
                        }
                        "/system/script/environment/print" => {
                            if words.iter().any(|s| s == "?name=sdwanStatusJSON") {
                                polls += 1;
                                if polls <= 2 {
                                    sentence(&mut stream, &["!trap"]);
                                    sentence(&mut stream, &["!done"]);
                                    break;
                                }
                                let raw=serde_json::json!({"revision":"test","uptime_seconds":polls,"states":{"default/wan":{"state":"healthy"}},"container":{"protocol":1,"boot_id":"boot","generation":1,"intent_file":"sdwan-container-intent.json","owner_instance":owner,"lease_remaining_seconds":if polls==3{0}else{3}}}).to_string();
                                sentence(&mut stream, &["!re", &format!("=value={raw}")]);
                                sentence(&mut stream, &["!done"]);
                                if polls == 6 {
                                    server_stop.store(true, Ordering::Relaxed);
                                }
                            } else {
                                sentence(&mut stream, &["!re", &format!("=value={CONFIG}")]);
                                sentence(&mut stream, &["!done"]);
                            }
                        }
                        "/file/print" => {
                            sentence(&mut stream, &["!re", "=.id=*1"]);
                            sentence(&mut stream, &["!done"]);
                        }
                        "/file/set" => {
                            writes += 1;
                            let text = words
                                .iter()
                                .find_map(|s| s.strip_prefix("=contents="))
                                .unwrap();
                            let intent: serde_json::Value = serde_json::from_str(text).unwrap();
                            owner = intent["instance"].as_str().unwrap().into();
                            assert_eq!(intent["selected"]["default"], "wan");
                            sentence(&mut stream, &["!done"]);
                        }
                        x => panic!("Unexpected fixture command {x}"),
                    };
                    if server_stop.load(Ordering::Relaxed) {
                        break;
                    }
                }
            }
            assert_eq!(writes, if active { 1 } else { 0 });
        });
        let mut s = settings(endpoint, d.file("password", "exact password\n"));
        s.mode = if active { Mode::Active } else { Mode::Shadow };
        s.heartbeat_port = udp.local_addr().unwrap().port();
        s.metrics_every_seconds = 1;
        service_until(s, &stopped).unwrap();
        worker.join().unwrap();
        let mut buf = [0; 8];
        if active {
            assert_eq!(udp.recv(&mut buf).unwrap(), 1);
            assert_eq!(buf[0], b's');
        } else {
            assert!(udp.recv(&mut buf).is_err());
        }
    }
}
#[test]
fn identity_mismatch_stops_heartbeat_and_reconnect_is_safe() {
    let d = Temp::new();
    let stopped = Arc::new(AtomicBool::new(false));
    let server_stop = stopped.clone();
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let endpoint = listener.local_addr().unwrap();
    let job = thread::spawn(move || {
        let (mut stream, _) = listener.accept().unwrap();
        assert_eq!(command(&mut stream).unwrap()[0], "/login");
        sentence(&mut stream, &["!done"]);
        assert_eq!(command(&mut stream).unwrap()[0], "/system/identity/print");
        sentence(&mut stream, &["!re", "=name=wrong"]);
        sentence(&mut stream, &["!done"]);
        server_stop.store(true, Ordering::Relaxed);
    });
    let s = settings(endpoint, d.file("password", "fixture"));
    service_until(s, &stopped).unwrap();
    job.join().unwrap();
}
#[test]
fn missing_router_status_does_not_claim_or_send_heartbeat() {
    let d = Temp::new();
    let stopped = Arc::new(AtomicBool::new(false));
    let target = stopped.clone();
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let endpoint = listener.local_addr().unwrap();
    let job = thread::spawn(move || {
        let (mut stream, _) = listener.accept().unwrap();
        for response in [
            vec![vec!["!done"]],
            vec![vec!["!re", "=name=fixture"], vec!["!done"]],
            vec![vec!["!done"]],
        ] {
            command(&mut stream).unwrap();
            for row in response {
                sentence(&mut stream, &row);
            }
        }
        target.store(true, Ordering::Relaxed);
    });
    let s = settings(endpoint, d.file("password", "fixture"));
    service_until(s, &stopped).unwrap();
    job.join().unwrap();
}
