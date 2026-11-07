use super::*;
#[test]
fn disabled_runtime_reads_no_files_and_opens_no_listener() {
    let settings = Settings::default();
    let observer = Observer {
        endpoint: "127.0.0.1:1".parse().unwrap(),
        identity: "test".into(),
        username: "test".into(),
        password_file: "/missing".into(),
    };
    assert!(Runtime::start(settings, observer).unwrap().is_none());
}
#[test]
fn full_handoff_drops_immediately() {
    let (sender, _receiver) = mpsc::sync_channel(1);
    let runtime = Runtime {
        sender: Some(sender),
        stop: Arc::new(AtomicBool::new(false)),
        threads: vec![],
    };
    let start = Instant::now();
    for _ in 0..10000 {
        runtime.observe("{}".into());
    }
    assert!(start.elapsed() < Duration::from_secs(1));
}
use crate::test_support::{reply, server};
use std::io::{Read, Write};
use std::net::TcpStream;
fn observer(endpoint: SocketAddr) -> Observer {
    Observer {
        endpoint,
        identity: "fixture".into(),
        username: "fixture".into(),
        password_file: "/fixture-password".into(),
    }
}
fn enabled() -> Settings {
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let listen = listener.local_addr().unwrap();
    Settings {
        enabled: true,
        listen,
        allowed_sources: vec!["127.0.0.0/8".into()],
        ..Default::default()
    }
}
fn mounted(path: &std::path::Path, _: u64) -> io::Result<String> {
    Ok(if path == std::path::Path::new("/secrets/web-token") {
        "a".repeat(64)
    } else {
        "fixture-password".into()
    })
}
fn snapshot(address: SocketAddr) -> serde_json::Value {
    let mut s = TcpStream::connect(address).unwrap();
    s.set_read_timeout(Some(Duration::from_secs(2))).unwrap();
    write!(
        s,
        "GET /api/status HTTP/1.1\r\nHost: localhost\r\nAuthorization: Bearer {}\r\n\r\n",
        "a".repeat(64)
    )
    .unwrap();
    let mut text = String::new();
    s.read_to_string(&mut text).unwrap();
    assert!(text.starts_with("HTTP/1.0 200"));
    serde_json::from_str(text.split_once("\r\n\r\n").unwrap().1).unwrap()
}
#[test]
fn mounted_secrets_listener_and_spawner_failures_are_isolated() {
    let o = || observer("127.0.0.1:1".parse().unwrap());
    assert!(
        Runtime::start_with(enabled(), o(), |_, _| Err(io::Error::other(
            "missing mount"
        )))
        .is_err()
    );
    for token in ["bad".into(), "G".repeat(64)] {
        assert!(Runtime::start_with(enabled(), o(), |_, _| Ok(token.clone())).is_err());
    }
    assert!(Runtime::start_with(enabled(), o(), |_, _| Ok("a".repeat(64))).is_err());
    let settings = enabled();
    let listener = TcpListener::bind(settings.listen).unwrap();
    assert!(Runtime::start_with(settings, o(), mounted).is_err());
    drop(listener);
    struct Failing {
        at: usize,
        calls: usize,
    }
    impl Spawn for Failing {
        fn spawn(
            &mut self,
            name: &str,
            job: impl FnOnce() + Send + 'static,
        ) -> io::Result<JoinHandle<()>> {
            self.calls += 1;
            if self.calls == self.at {
                Err(io::Error::other("fixture spawn failure"))
            } else {
                Threads.spawn(name, job)
            }
        }
    }
    for at in [1, 2] {
        let settings = enabled();
        let addr = settings.listen;
        let mut spawner = Failing { at, calls: 0 };
        assert!(Runtime::start_with_spawner(settings, o(), mounted, &mut spawner).is_err());
        assert_eq!(spawner.calls, at);
        assert!(TcpListener::bind(addr).is_ok());
    }
}
#[test]
fn enabled_runtime_collects_in_ram_and_joins_all_threads() {
    let settings = enabled();
    let address = settings.listen;
    let runtime =
        Runtime::start_with(settings, observer("127.0.0.1:1".parse().unwrap()), mounted).unwrap();
    Runtime::observe_optional(
        &runtime,
        r#"{"uptime_seconds":1,"revision":"fixture"}"#.into(),
    );
    std::thread::sleep(Duration::from_millis(30));
    let value = snapshot(address);
    assert_eq!(value["current"]["uptime_seconds"], 1);
    assert_eq!(value["observer_available"], true);
    runtime.as_ref().unwrap().observe("x".repeat(MAX_RAW + 1));
    runtime.as_ref().unwrap().observe("{".into());
    std::thread::sleep(Duration::from_millis(100));
    let value = snapshot(address);
    assert_eq!(value["invalid_snapshots"], 1);
    drop(runtime);
    assert!(TcpListener::bind(address).is_ok());
    Runtime::observe_optional(&None, "{}".into());
    let runtime = Runtime {
        sender: None,
        stop: Arc::new(AtomicBool::new(false)),
        threads: vec![],
    };
    runtime.observe("{}".into());
}
#[test]
fn interface_observer_validates_identity_rows_and_reuses_session() {
    let empty = Update::parse(r#"{"uptime_seconds":1,"revision":"fixture"}"#).unwrap();
    assert!(counters(
        &mut None,
        &observer("127.0.0.1:1".parse().unwrap()),
        "fixture",
        &empty
    )
    .unwrap()
    .is_empty());
    let raw =
        r#"{"uptime_seconds":1,"revision":"fixture","samples":{"wan1":{"interface":"ether2"}}}"#;
    let value = Update::parse(raw).unwrap();
    for variant in 0..4 {
        let rows = match variant {
            0 => reply(&[
                &["!re", "=name=other", "=rx-byte=1", "=tx-byte=2"],
                &["!done"],
            ]),
            1 => reply(&[
                &["!re", "=name=ether2", "=rx-byte=1", "=tx-byte=2"],
                &["!re", "=name=ether2", "=rx-byte=1", "=tx-byte=2"],
                &["!done"],
            ]),
            2 => reply(&[&["!re", "=name=ether2", "=rx-byte=bad"], &["!done"]]),
            _ => reply(&[
                &["!re", "=name=ether2", "=rx-byte=1", "=tx-byte=2"],
                &["!done"],
            ]),
        };
        let (mut replies) = vec![
            reply(&[&["!done"]]),
            reply(&[&["!re", "=name=fixture"], &["!done"]]),
            rows.clone(),
        ];
        if variant == 3 {
            replies.push(rows);
        }
        let (addr, job) = server(replies);
        let mut api = None;
        let result = counters(&mut api, &observer(addr), "fixture", &value);
        if variant < 2 {
            assert!(result.is_err());
        } else if variant == 2 {
            assert!(result.unwrap().is_empty());
        } else {
            assert_eq!(result.unwrap()["ether2"].rx, 1);
            assert_eq!(
                counters(&mut api, &observer(addr), "fixture", &value).unwrap()["ether2"].tx,
                2
            );
        }
        drop(api);
        let commands = job.join().unwrap();
        assert_eq!(commands[2][0], "/interface/print");
    }
    let (addr, job) = server(vec![
        reply(&[&["!done"]]),
        reply(&[&["!re", "=name=wrong"], &["!done"]]),
    ]);
    assert!(counters(&mut None, &observer(addr), "fixture", &value).is_err());
    job.join().unwrap();
}
#[test]
fn collector_handles_timeouts_disconnect_invalid_input_and_counter_failures() {
    let store = Arc::new(Mutex::new(Store::new("default".into(), 5, 12)));
    let (tx, rx) = mpsc::sync_channel(1);
    let target = store.clone();
    let flag = Arc::new(AtomicBool::new(false));
    let worker = std::thread::spawn(move || {
        collect(
            rx,
            target,
            observer("127.0.0.1:1".parse().unwrap()),
            "fixture".into(),
            "token".into(),
            5,
            flag,
        )
    });
    std::thread::sleep(Duration::from_millis(120));
    for (u, raw) in [
        (
            1,
            r#"{"uptime_seconds":1,"revision":"fixture","samples":{"wan1":{"interface":"ether2"}}}"#,
        ),
        (2, r#"{"uptime_seconds":2,"revision":"fixture"}"#),
    ] {
        tx.send(Message {
            raw: raw.into(),
            at: Instant::now(),
        })
        .unwrap();
        let end = Instant::now() + Duration::from_secs(2);
        while store
            .lock()
            .unwrap()
            .status(Instant::now())
            .current
            .as_ref()
            .is_none_or(|c| c.uptime_seconds != u)
        {
            assert!(Instant::now() < end);
            std::thread::sleep(Duration::from_millis(1));
        }
    }
    drop(tx);
    worker.join().unwrap();
    assert!(
        !store
            .lock()
            .unwrap()
            .status(Instant::now())
            .observer_available
    );
}
#[test]
fn real_mount_adapter_is_bounded_without_accessing_host_secrets() {
    let path = std::env::temp_dir().join(format!("sdwan-mount-unit-{}", std::process::id()));
    std::fs::write(&path, b"fixture").unwrap();
    assert_eq!(read_mount(&path, 7).unwrap(), "fixture");
    assert!(read_mount(&path, 6).is_err());
    std::fs::remove_file(path).unwrap();
}
#[test]
fn one_startup_factory_covers_success_and_each_cleanup_stage() {
    struct Factory {
        fail_at: usize,
        calls: usize,
    }
    impl Spawn for Factory {
        fn spawn(
            &mut self,
            name: &str,
            job: impl FnOnce() + Send + 'static,
        ) -> io::Result<JoinHandle<()>> {
            self.calls += 1;
            if self.calls == self.fail_at {
                return Err(io::Error::other("scripted thread failure"));
            }
            Threads.spawn(name, job)
        }
    }
    for scenario in 0..=10 {
        let mut cfg = enabled();
        let address = cfg.listen;
        if scenario == 0 {
            cfg.enabled = false;
        }
        if scenario == 1 {
            cfg.sample_seconds = 1;
        }
        let occupied = if scenario == 7 {
            Some(TcpListener::bind(address).unwrap())
        } else {
            None
        };
        let mut factory = Factory {
            fail_at: if scenario == 8 {
                1
            } else if scenario == 9 {
                2
            } else {
                0
            },
            calls: 0,
        };
        let mut loads = 0;
        let load = |path: &std::path::Path, _limit: u64| -> io::Result<String> {
            loads += 1;
            if scenario == 2 || (scenario == 5 && loads == 2) {
                return Err(io::Error::other("scripted missing mount"));
            }
            if path == std::path::Path::new("/secrets/web-token") {
                Ok(match scenario {
                    3 => "short".into(),
                    4 => "G".repeat(64),
                    _ => "a".repeat(64),
                })
            } else {
                Ok(if scenario == 6 {
                    "a".repeat(64)
                } else {
                    "fixture-password".into()
                })
            }
        };
        let result = Runtime::start_with_spawner(
            cfg,
            observer("127.0.0.1:1".parse().unwrap()),
            load,
            &mut factory,
        );
        if scenario == 0 {
            assert!(result.unwrap().is_none());
            assert_eq!(loads, 0);
        } else if scenario == 10 {
            let runtime = result.unwrap();
            assert!(runtime.is_some());
            drop(runtime);
        } else {
            assert!(result.is_err(), "scenario {scenario}");
        }
        drop(occupied);
        assert!(
            TcpListener::bind(address).is_ok(),
            "listener leaked in scenario {scenario}"
        );
    }
}
