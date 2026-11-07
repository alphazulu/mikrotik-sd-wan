use sdwan_router_controller::process::read_limited;
use sdwan_router_controller::{
    api::Api,
    engine::{Engine, Mode},
    model::{self, Config, Metrics},
};
use serde::Deserialize;
use std::fs;
use std::io::{self, Read};
use std::net::{SocketAddr, UdpSocket};
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::{Duration, Instant};

static STOP: AtomicBool = AtomicBool::new(false);
extern "C" fn stop(_: libc::c_int) {
    STOP.store(true, Ordering::Relaxed);
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Settings {
    endpoint: SocketAddr,
    identity: String,
    username: String,
    password_file: PathBuf,
    #[serde(default)]
    mode: Mode,
    #[serde(default = "poll_ms")]
    poll_ms: u64,
    #[serde(default = "heartbeat_port")]
    heartbeat_port: u16,
    #[serde(default)]
    metrics_every_seconds: u64,
    #[serde(default)]
    telemetry: Option<sdwan_router_controller::telemetry_config::Settings>,
}
fn poll_ms() -> u64 {
    1000
}
fn heartbeat_port() -> u16 {
    45999
}
fn invalid(message: &'static str) -> io::Error {
    io::Error::new(io::ErrorKind::InvalidData, message)
}
fn nonce() -> io::Result<String> {
    let mut bytes = [0u8; 16];
    fs::File::open("/dev/urandom")?.read_exact(&mut bytes)?;
    Ok(bytes.iter().map(|b| format!("{b:02x}")).collect())
}
fn resources() -> serde_json::Value {
    let data = sdwan_router_controller::process::resources();
    serde_json::json!({"rss_bytes":data.rss_bytes,"cpu_ticks":data.cpu_ticks})
}

fn service(settings: Settings) -> Result<(), Box<dyn std::error::Error>> {
    service_until(settings, &STOP)
}
fn service_until(
    settings: Settings,
    stopped: &AtomicBool,
) -> Result<(), Box<dyn std::error::Error>> {
    if !(500..=2000).contains(&settings.poll_ms)
        || settings.identity.is_empty()
        || settings.username.is_empty()
    {
        return Err(invalid("Invalid controller identity/poll interval (500..2000 ms)").into());
    }
    #[cfg(feature = "web")]
    let web = settings.telemetry.clone().and_then(|cfg| {
        let observer = sdwan_router_controller::web::Observer {
            endpoint: settings.endpoint,
            identity: settings.identity.clone(),
            username: settings.username.clone(),
            password_file: settings.password_file.clone(),
        };
        match sdwan_router_controller::web::Runtime::start(cfg, observer) {
            Ok(runtime) => runtime,
            Err(_) => {
                eprintln!("Optional web telemetry unavailable; routing continues");
                None
            }
        }
    });
    #[cfg(not(feature = "web"))]
    if settings.telemetry.as_ref().is_some_and(|cfg| cfg.enabled) {
        eprintln!("Web feature is absent from this image; routing continues");
    }
    let instance = nonce()?;
    let heartbeat = SocketAddr::new(settings.endpoint.ip(), settings.heartbeat_port);
    let bind_address = if heartbeat.is_ipv4() {
        "0.0.0.0:0"
    } else {
        "[::]:0"
    };
    let socket = UdpSocket::bind(bind_address)?;
    socket.set_write_timeout(Some(Duration::from_secs(1)))?;
    let mut api: Option<Api> = None;
    let mut engine = Engine::new(settings.mode, instance);
    let mut last_state = String::new();
    let mut last_metrics = Instant::now();
    while !stopped.load(Ordering::Relaxed) {
        let begin = Instant::now();
        let cycle = (|| -> Result<String, Box<dyn std::error::Error>> {
            if api.is_none() {
                // Read exactly; provisioning writes the password without a newline.
                let password = read_limited(&settings.password_file, 4096)?;
                let mut client = Api::connect(settings.endpoint, &settings.username, &password)?;
                if client.identity()? != settings.identity {
                    return Err(invalid("Router identity differs from configured identity").into());
                }
                api = Some(client);
                engine.reset_session();
            }
            let client = api.as_mut().expect("API session initialized above");
            let raw = client
                .environment("sdwanStatusJSON")?
                .ok_or_else(|| invalid("Controller metrics not initialized"))?;
            let metrics: Metrics = serde_json::from_str(&raw)?;
            #[cfg(feature = "web")]
            sdwan_router_controller::web::Runtime::observe_optional(&web, raw);
            let outcome = engine.step(client, &metrics, Instant::now, || {
                socket.send_to(b"s", heartbeat).map(|_| ())
            })?;
            if outcome.state != last_state {
                if let Some(selected) = &outcome.selected {
                    let mut event = serde_json::json!({"mode":settings.mode.name(),"revision":metrics.revision,"selected":selected});
                    if settings.mode == Mode::Shadow {
                        event["writes"] = serde_json::json!(0);
                    }
                    println!("{event}");
                }
            }
            let state = outcome.state;
            Ok(state)
        })();
        match cycle {
            Ok(state) => {
                if state != last_state
                    && !state.starts_with("shadow:")
                    && !state.starts_with("active:")
                {
                    eprintln!("{state}");
                }
                last_state = state;
            }
            Err(error) => {
                let state = format!("unavailable: {error}");
                if state != last_state {
                    eprintln!("{state}; heartbeat stopped, native fallback remains responsible");
                }
                last_state = state;
                api = None;
                engine.reset_session();
            }
        }
        if settings.metrics_every_seconds > 0
            && last_metrics.elapsed() >= Duration::from_secs(settings.metrics_every_seconds)
        {
            println!(
                "{}",
                serde_json::json!({"resources":resources(),"mode":if settings.mode==Mode::Shadow{"shadow"}else{"active"}})
            );
            last_metrics = Instant::now();
        }
        if let Some(delay) = Duration::from_millis(settings.poll_ms).checked_sub(begin.elapsed()) {
            std::thread::sleep(delay);
        }
    }
    // A crashed process is handled by lease expiry. A graceful release is a
    // single optional write; it never changes routes directly.
    Ok(())
}

fn main() -> std::process::ExitCode {
    entry(&std::env::args().collect::<Vec<_>>())
}
fn entry(args: &[String]) -> std::process::ExitCode {
    unsafe {
        libc::signal(libc::SIGTERM, stop as *const () as libc::sighandler_t);
        libc::signal(libc::SIGINT, stop as *const () as libc::sighandler_t);
    }
    let result = execute(args);
    if let Err(error) = result {
        eprintln!("{error}");
        return std::process::ExitCode::FAILURE;
    }
    std::process::ExitCode::SUCCESS
}
fn execute(args: &[String]) -> Result<(), Box<dyn std::error::Error>> {
    match args.get(1).map(String::as_str) {
        Some("--version") => println!(
            "sdwan-router-controller {} web={}",
            env!("CARGO_PKG_VERSION"),
            cfg!(feature = "web")
        ),
        Some("plan") if args.len() == 4 => {
            let metrics: Metrics = serde_json::from_str(&read_limited(&args[2], 1048576)?)?;
            let config: Config = serde_json::from_str(&read_limited(&args[3], 1048576)?)?;
            println!(
                "{}",
                serde_json::to_string(&model::choose(&config, &metrics)?)?
            );
        }
        Some("run") if args.len() == 3 => {
            service(serde_json::from_str(&read_limited(&args[2], 65536)?)?)?
        }
        _ => return Err(invalid(
            "Usage: sdwan-controller run SETTINGS.json | plan STATUS.json CONFIG.json | --version",
        )
        .into()),
    }
    Ok(())
}

#[cfg(test)]
#[path = "../tests/unit/entrypoint.rs"]
mod tests;
