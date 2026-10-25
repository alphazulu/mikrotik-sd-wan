//! Optional read-only RAM telemetry, isolated from the routing cycle.
mod http;
pub mod state;
use crate::process::{read_limited as read, resources};
use crate::{api::Api, telemetry_config::Settings};
use state::{Counter, Counters, Store, Update, MAX_RAW};
use std::io;
use std::net::{SocketAddr, TcpListener};
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{
    mpsc::{self, SyncSender},
    Arc, Mutex,
};
use std::thread::{self, JoinHandle};
use std::time::{Duration, Instant};

pub struct Observer {
    pub endpoint: SocketAddr,
    pub identity: String,
    pub username: String,
    pub password_file: PathBuf,
}
struct Message {
    raw: String,
    at: Instant,
}
pub struct Runtime {
    sender: Option<SyncSender<Message>>,
    stop: Arc<AtomicBool>,
    threads: Vec<JoinHandle<()>>,
}
fn invalid(message: &'static str) -> io::Error {
    io::Error::new(io::ErrorKind::InvalidData, message)
}
fn counters(
    api: &mut Option<Api>,
    observer: &Observer,
    password: &str,
    value: &Update,
) -> io::Result<Counters> {
    let mut names: Vec<String> = value
        .samples
        .0
        .values()
        .map(|s| s.interface.0.clone())
        .filter(|s| !s.is_empty())
        .collect();
    names.sort();
    names.dedup();
    if names.is_empty() {
        return Ok(Counters::new());
    }
    if api.is_none() {
        let mut client = Api::connect_observer(observer.endpoint, &observer.username, password)?;
        if client.identity()? != observer.identity {
            return Err(invalid("Observer router identity changed"));
        }
        *api = Some(client);
    }
    let rows = api
        .as_mut()
        .expect("observer API initialized above")
        .interface_counters(&names)?;
    let at = Instant::now();
    let mut out = Counters::new();
    for row in rows {
        let Some(name) = row.get("name").filter(|s| names.contains(s)) else {
            return Err(invalid("Unexpected observer interface"));
        };
        let (Some(rx), Some(tx)) = (
            row.get("rx-byte").and_then(|s| s.parse::<u64>().ok()),
            row.get("tx-byte").and_then(|s| s.parse::<u64>().ok()),
        ) else {
            continue;
        };
        if out.insert(name.clone(), Counter { at, rx, tx }).is_some() {
            return Err(invalid("Duplicate observer interface"));
        }
    }
    Ok(out)
}
trait Spawn {
    fn spawn(
        &mut self,
        name: &str,
        job: impl FnOnce() + Send + 'static,
    ) -> io::Result<JoinHandle<()>>;
}
struct Threads;
impl Spawn for Threads {
    fn spawn(
        &mut self,
        name: &str,
        job: impl FnOnce() + Send + 'static,
    ) -> io::Result<JoinHandle<()>> {
        thread::Builder::new()
            .name(name.into())
            .stack_size(131072)
            .spawn(job)
    }
}
fn collect(
    receiver: mpsc::Receiver<Message>,
    store: Arc<Mutex<Store>>,
    observer: Observer,
    password: String,
    token: String,
    sample_seconds: u64,
    stop: Arc<AtomicBool>,
) {
    let mut api = None;
    let mut latest = None;
    let mut polled = None;
    while !stop.load(Ordering::Relaxed) {
        let message = match receiver.recv_timeout(Duration::from_millis(100)) {
            Ok(m) => m,
            Err(mpsc::RecvTimeoutError::Timeout) => continue,
            Err(_) => break,
        };
        let value = match Update::parse(&message.raw) {
            Ok(v) => v,
            Err(_) => {
                if let Ok(mut s) = store.lock() {
                    s.invalid();
                }
                continue;
            }
        };
        let epoch_changed = store
            .lock()
            .map(|s| s.epoch_changed(&value))
            .unwrap_or(false);
        if epoch_changed
            || polled.is_none_or(|at: Instant| at.elapsed() >= Duration::from_secs(sample_seconds))
        {
            latest = match counters(&mut api, &observer, &password, &value) {
                Ok(c) => Some(c),
                Err(_) => {
                    api = None;
                    None
                }
            };
            polled = Some(Instant::now());
            let usage = resources();
            if let Ok(mut s) = store.lock() {
                s.resources = usage;
            }
        }
        if let Ok(mut s) = store.lock() {
            s.ingest(value, message.at, latest.as_ref(), &password, &token);
        }
    }
}
fn read_mount(path: &std::path::Path, limit: u64) -> io::Result<String> {
    read(path, limit)
}
impl Runtime {
    pub fn start(settings: Settings, observer: Observer) -> io::Result<Option<Self>> {
        Self::start_with(settings, observer, read_mount)
    }
    fn start_with(
        settings: Settings,
        observer: Observer,
        load: impl FnMut(&std::path::Path, u64) -> io::Result<String>,
    ) -> io::Result<Option<Self>> {
        Self::start_with_spawner(settings, observer, load, &mut Threads)
    }
    fn start_with_spawner(
        settings: Settings,
        observer: Observer,
        mut load: impl FnMut(&std::path::Path, u64) -> io::Result<String>,
        spawner: &mut impl Spawn,
    ) -> io::Result<Option<Self>> {
        if !settings.enabled {
            return Ok(None);
        }
        let networks = settings.validate().map_err(invalid)?;
        let token = load(&settings.token_file, 4096)?.trim().to_owned();
        if token.len() != 64
            || !token
                .bytes()
                .all(|c| c.is_ascii_digit() || (b'a'..=b'f').contains(&c))
        {
            return Err(invalid(
                "Dedicated web token must contain 64 lowercase hex characters",
            ));
        }
        let password = load(&observer.password_file, 4096)?;
        if password == token {
            return Err(invalid("Web token must differ from API password"));
        }
        let listener = TcpListener::bind(settings.listen)?;
        listener.set_nonblocking(true)?;
        let store = Arc::new(Mutex::new(Store::new(
            settings.profile.clone(),
            settings.sample_seconds,
            settings.history_points,
        )));
        let stop = Arc::new(AtomicBool::new(false));
        let (sender, receiver) = mpsc::sync_channel::<Message>(1);
        let http_stop = stop.clone();
        let http_store = store.clone();
        let http_token = token.clone();
        let server = spawner.spawn("sdwan-http", move || {
            http::serve(listener, http_store, http_token, networks, http_stop)
        })?;
        let collector_stop = stop.clone();
        let collector = spawner.spawn("sdwan-ram", move || {
            collect(
                receiver,
                store,
                observer,
                password,
                token,
                settings.sample_seconds,
                collector_stop,
            )
        });
        match collector {
            Ok(collector) => Ok(Some(Self {
                sender: Some(sender),
                stop,
                threads: vec![server, collector],
            })),
            Err(error) => {
                stop.store(true, Ordering::Relaxed);
                let _ = server.join();
                Err(error)
            }
        }
    }
    pub fn observe_optional(runtime: &Option<Self>, raw: String) {
        if let Some(runtime) = runtime {
            runtime.observe(raw);
        }
    }
    /// A full queue or an oversized snapshot is dropped, never awaited.
    pub fn observe(&self, raw: String) {
        if raw.len() <= MAX_RAW {
            if let Some(sender) = &self.sender {
                let _ = sender.try_send(Message {
                    raw,
                    at: Instant::now(),
                });
            }
        }
    }
}
impl Drop for Runtime {
    fn drop(&mut self) {
        self.stop.store(true, Ordering::Relaxed);
        self.sender.take();
        for thread in self.threads.drain(..) {
            let _ = thread.join();
        }
    }
}

#[cfg(test)]
#[path = "../../tests/unit/web_runtime.rs"]
mod tests;
