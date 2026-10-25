use super::*;
#[test]
fn auth_methods_origins_and_ambiguous_headers_are_rejected() {
    let token = "a".repeat(64);
    assert!(authorized(Some(&format!("Bearer {token}")), &token));
    assert!(!authorized(Some("Bearer wrong"), &token));
    assert!(!authorized(None, &token));
    for text in [
        "POST /api/status HTTP/1.1\r\nHost: x\r\n\r\n",
        "GET / HTTP/1.1\r\nHost: x\r\nOrigin: http://evil\r\n\r\n",
        "GET / HTTP/1.1\r\nHost: x\r\nAuthorization: a\r\nAuthorization: b\r\n\r\n",
        "GET / HTTP/1.1\r\nHost: x\r\nTransfer-Encoding: chunked\r\n\r\n",
    ] {
        assert!(parse(text.as_bytes()).is_err());
    }
    assert!(parse(b"GET /api/status HTTP/1.1\r\nHost: x\r\nOrigin: http://x\r\n\r\n").is_ok());
}
#[test]
fn query_limits_do_not_allow_tokens_or_unbounded_history() {
    let store = Arc::new(Mutex::new(Store::new("default".into(), 10, 360)));
    for target in [
        "/api/history?max=0",
        "/api/history?max=601",
        "/api/status?token=secret",
        "/api/events?since=1&since=2",
    ] {
        assert!(json(target, &store).is_err());
    }
    assert!(json("/api/history?max=600", &store).is_ok());
    let _guard = store.lock().unwrap();
    assert!(matches!(json("/api/status", &store), Err(503)));
}
#[test]
fn static_assets_are_embedded_and_dynamic_html_is_not_used() {
    assert!(HTML.contains("/app.js"));
    assert!(!JS.contains("innerHTML"));
    assert!(!JS.contains("localStorage"));
    assert!(!JS.contains("sessionStorage"));
    assert!(!HTML.contains("https://"));
    assert!(!JS.contains("console.log"));
}
#[test]
fn slow_headers_have_an_absolute_deadline() {
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let addr = listener.local_addr().unwrap();
    let thread = std::thread::spawn(move || {
        let (mut s, _) = listener.accept().unwrap();
        let start = Instant::now();
        let error = request(&mut s).unwrap_err();
        assert_eq!(error, 408);
        assert!(start.elapsed() < Duration::from_secs(2));
    });
    let mut client = TcpStream::connect(addr).unwrap();
    client.write_all(b"G").unwrap();
    std::thread::sleep(Duration::from_millis(500));
    drop(client);
    thread.join().unwrap();
}
#[test]
fn loopback_server_enforces_auth_routes_and_response_headers() {
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let address = listener.local_addr().unwrap();
    listener.set_nonblocking(true).unwrap();
    let store = Arc::new(Mutex::new(Store::new("default".into(), 10, 360)));
    let stop = Arc::new(AtomicBool::new(false));
    let server_stop = stop.clone();
    let token = "a".repeat(64);
    let key = token.clone();
    let server = std::thread::spawn(move || {
        serve(
            listener,
            store,
            key,
            vec![Network::parse("127.0.0.0/8").unwrap()],
            server_stop,
        )
    });
    for (target, authorization, expected) in [
        ("/", "", 200),
        ("/api/status", "", 401),
        ("/api/status", token.as_str(), 200),
        ("/api/export", token.as_str(), 200),
        ("/missing", token.as_str(), 404),
    ] {
        let mut client = TcpStream::connect(address).unwrap();
        client
            .set_read_timeout(Some(Duration::from_secs(2)))
            .unwrap();
        write!(client,"GET {target} HTTP/1.1\r\nHost: localhost\r\nAuthorization: Bearer {authorization}\r\n\r\n").unwrap();
        let mut response = String::new();
        client.read_to_string(&mut response).unwrap();
        assert!(response.starts_with(&format!("HTTP/1.0 {expected} ")));
        assert!(response.contains("Cache-Control: no-store"));
        assert!(!response.contains(&token));
        if target == "/api/export" {
            assert!(response.contains("Content-Disposition: attachment"));
            let (_, body) = response.split_once("\r\n\r\n").unwrap();
            assert!(serde_json::from_str::<serde_json::Value>(body).is_ok());
        }
    }
    stop.store(true, Ordering::Relaxed);
    server.join().unwrap();
}
#[derive(Default)]
struct Memory {
    input: std::io::Cursor<Vec<u8>>,
    out: Vec<u8>,
    bad_read_timeout: bool,
    bad_write_timeout: bool,
    bad_read: bool,
    bad_write: bool,
    fail_at: Option<usize>,
}
impl Read for Memory {
    fn read(&mut self, out: &mut [u8]) -> io::Result<usize> {
        if self.bad_read {
            return Err(io::Error::other("fixture read"));
        }
        self.input.read(out)
    }
}
impl Write for Memory {
    fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
        if self.bad_write || self.fail_at.is_some_and(|limit| self.out.len() >= limit) {
            return Err(io::Error::other("fixture write"));
        }
        self.out.extend_from_slice(bytes);
        Ok(bytes.len())
    }
    fn flush(&mut self) -> io::Result<()> {
        Ok(())
    }
}
impl Stream for Memory {
    fn read_timeout(&self, _: Option<Duration>) -> io::Result<()> {
        if self.bad_read_timeout {
            Err(io::Error::other("fixture timeout"))
        } else {
            Ok(())
        }
    }
    fn write_timeout(&self, _: Option<Duration>) -> io::Result<()> {
        if self.bad_write_timeout {
            Err(io::Error::other("fixture timeout"))
        } else {
            Ok(())
        }
    }
}
#[test]
fn malformed_requests_and_socket_errors_have_bounded_replies() {
    for raw in [
        b"bad".as_slice(),
        b"GET http://other/ HTTP/1.1\r\nHost: x\r\n\r\n",
        b"GET /bad%20 HTTP/1.1\r\nHost: x\r\n\r\n",
        b"GET / HTTP/1.1\r\n(: bad\r\nHost: x\r\n\r\n",
        b"GET / HTTP/1.1\r\nHost: user@x\r\n\r\n",
        b"GET / HTTP/1.1\r\nHost: x\r\nSec-Fetch-Site: cross-site\r\n\r\n",
        &[255],
    ] {
        assert!(parse(raw).is_err());
    }
    for (case, expected) in [(0, 400), (1, 431), (2, 400), (3, 408), (4, 400)] {
        let mut stream = Memory::default();
        match case {
            0 => {}
            1 => stream.input = std::io::Cursor::new(vec![b'x'; HEADER_LIMIT + 1]),
            2 => {
                stream.input =
                    std::io::Cursor::new(b"GET / HTTP/1.1\r\nHost: x\r\n\r\nbody".to_vec())
            }
            3 => stream.bad_read = true,
            _ => stream.bad_read_timeout = true,
        };
        assert_eq!(request(&mut stream).unwrap_err(), expected);
    }
    assert!(!authorized(Some("Basic same"), "same"));
    assert!(!authorized(Some("Bearer xxxx"), "yyyy"));
}
#[test]
fn header_codes_body_limits_deadlines_and_serialization_failures() {
    for code in [200, 400, 401, 403, 404, 405, 408, 429, 431, 503, 418] {
        let mut out = vec![];
        headers(&mut out, code, "text/plain", true).unwrap();
        let text = String::from_utf8(out).unwrap();
        assert!(text.starts_with(&format!("HTTP/1.0 {code}")));
        assert!(text.contains("Content-Disposition"));
        if code == 405 {
            assert!(text.contains("Allow: GET"));
        }
        if code == 429 {
            assert!(text.contains("Retry-After"));
        }
    }
    let mut broken = Memory {
        bad_write: true,
        ..Default::default()
    };
    assert!(headers(&mut broken, 200, "text/plain", false).is_err());
    let mut memory = Memory::default();
    {
        let mut writer = Deadline {
            stream: &mut memory,
            end: Instant::now() + Duration::from_secs(1),
            bytes: BODY_LIMIT,
        };
        assert!(writer.write(b"x").is_err());
    }
    {
        let mut writer = Deadline {
            stream: &mut memory,
            end: Instant::now() - Duration::from_secs(1),
            bytes: 0,
        };
        assert_eq!(
            writer.write(b"x").unwrap_err().kind(),
            io::ErrorKind::TimedOut
        );
    }
    memory.bad_write_timeout = true;
    let mut writer = Deadline {
        stream: &mut memory,
        end: Instant::now() + Duration::from_secs(1),
        bytes: 0,
    };
    assert!(writer.write(b"x").is_err());
    let store = Arc::new(Mutex::new(Store::new("default".into(), 10, 12)));
    for target in ["/api/status", "/api/history", "/api/events", "/api/export"] {
        assert!(json(target, &store).is_ok());
    }
    let mut memory = Memory::default();
    respond(
        &mut memory,
        Request {
            target: "/app.js".into(),
            authorization: None,
        },
        "fixture",
        &store,
    )
    .unwrap();
    assert!(String::from_utf8(memory.out)
        .unwrap()
        .contains("text/javascript"));
    let mut memory = Memory::default();
    respond(
        &mut memory,
        Request {
            target: "/api/history".into(),
            authorization: Some("Bearer fixture".into()),
        },
        "fixture",
        &store,
    )
    .unwrap();
    assert!(String::from_utf8(memory.out).unwrap().contains("200 OK"));
    let mut bucket = Bucket::new();
    for _ in 0..8 {
        assert!(bucket.allow());
    }
    assert!(!bucket.allow());
    bucket.at = Instant::now() - Duration::from_secs(1);
    assert!(bucket.allow());
}
#[test]
fn server_denies_other_source_families_throttles_and_survives_malformed_requests() {
    struct AcceptFailure {
        listener: TcpListener,
        failed: Arc<AtomicBool>,
    }
    impl Listener for AcceptFailure {
        fn accept(&self) -> io::Result<(TcpStream, std::net::SocketAddr)> {
            if self.failed.load(Ordering::Relaxed) {
                return Err(io::Error::other("scripted accept failure"));
            }
            self.listener.accept()
        }
    }
    for (address, allow) in [
        ("127.0.0.1:0", false),
        ("[::1]:0", true),
        ("127.0.0.1:0", true),
    ] {
        let listener = TcpListener::bind(address).unwrap();
        let addr = listener.local_addr().unwrap();
        listener.set_nonblocking(true).unwrap();
        let store = Arc::new(Mutex::new(Store::new("default".into(), 10, 12)));
        let stopped = Arc::new(AtomicBool::new(false));
        let flag = stopped.clone();
        let failed = Arc::new(AtomicBool::new(false));
        let fail_accept = failed.clone();
        let job = std::thread::spawn(move || {
            serve(
                AcceptFailure {
                    listener,
                    failed: fail_accept,
                },
                store,
                "fixture".into(),
                if allow {
                    vec![Network::parse("127.0.0.0/8").unwrap()]
                } else {
                    vec![]
                },
                flag,
            )
        });
        let mut throttled = false;
        for i in 0..if allow && addr.is_ipv4() { 20 } else { 1 } {
            let mut stream = TcpStream::connect(addr).unwrap();
            stream
                .set_read_timeout(Some(Duration::from_secs(2)))
                .unwrap();
            if i == 0 && allow && addr.is_ipv4() {
                stream
                    .write_all(b"POST / HTTP/1.1\r\nHost: x\r\n\r\n")
                    .unwrap();
            } else {
                stream
                    .write_all(b"GET / HTTP/1.1\r\nHost: x\r\n\r\n")
                    .unwrap();
            }
            let mut response = String::new();
            if let Err(error) = stream.read_to_string(&mut response) {
                assert_eq!(error.kind(), io::ErrorKind::ConnectionReset);
                assert!(
                    response.starts_with("HTTP/1.0 403") || response.starts_with("HTTP/1.0 429")
                );
            }
            if !allow || addr.is_ipv6() {
                assert!(response.starts_with("HTTP/1.0 403"));
            } else if i == 0 {
                assert!(response.starts_with("HTTP/1.0 405"));
            }
            throttled |= response.starts_with("HTTP/1.0 429");
        }
        if allow && addr.is_ipv4() {
            assert!(throttled);
        }
        failed.store(true, Ordering::Relaxed);
        job.join().unwrap();
    }
    struct Failed;
    impl Listener for Failed {
        fn accept(&self) -> io::Result<(TcpStream, std::net::SocketAddr)> {
            Err(io::Error::other("fixture accept failure"))
        }
    }
    serve(
        Failed,
        Arc::new(Mutex::new(Store::new("default".into(), 10, 12))),
        "fixture".into(),
        vec![],
        Arc::new(AtomicBool::new(false)),
    );
}
#[test]
fn optional_content_length_https_origin_and_writer_failures_are_tested() {
    assert!(parse(b"GET / HTTP/1.1\r\nHost: localhost\r\nContent-Length: 0\r\nOrigin: https://localhost\r\n\r\n").is_ok());
    assert_eq!(
        parse(b"GET / HTTP/1.1\r\nHost: localhost\r\nContent-Length: 1\r\n\r\n").unwrap_err(),
        400
    );
    let mut base = vec![];
    headers(&mut base, 200, "text/plain", false).unwrap();
    let mut failed = Memory {
        fail_at: Some(base.len() - 2),
        ..Default::default()
    };
    assert!(headers(&mut failed, 200, "text/plain", true).is_err());
    let store = Arc::new(Mutex::new(Store::new("default".into(), 10, 12)));
    let (data, _) = json("/api/status", &store).unwrap();
    let mut failed = Memory {
        bad_write: true,
        ..Default::default()
    };
    assert!(json_response(&mut failed, &data, false).is_err());
    let mut output = Memory::default();
    json_response(&mut output, &data, false).unwrap();
    let header = output
        .out
        .windows(4)
        .position(|p| p == b"\r\n\r\n")
        .unwrap()
        + 4;
    let mut failed = Memory {
        fail_at: Some(header),
        ..Default::default()
    };
    assert!(json_response(&mut failed, &data, false).is_err());
    let mut unauthenticated = Memory::default();
    respond(
        &mut unauthenticated,
        Request {
            target: "/api/status".into(),
            authorization: None,
        },
        "fixture",
        &store,
    )
    .unwrap();
    assert!(String::from_utf8(unauthenticated.out)
        .unwrap()
        .starts_with("HTTP/1.0 401"));
}
#[test]
fn concrete_request_reply_and_header_writers_cover_all_outcomes() {
    let store = Arc::new(Mutex::new(Store::new("default".into(), 10, 12)));
    let mut memory = Memory {
        input: std::io::Cursor::new(
            b"GET /api/status HTTP/1.1\r\nHost: localhost\r\n\r\n".to_vec(),
        ),
        ..Default::default()
    };
    assert_eq!(request(&mut memory).unwrap().target, "/api/status");
    for code in [200, 400, 401, 403, 404, 405, 408, 429, 431, 503, 418] {
        let mut out = Memory::default();
        headers(&mut out, code, "text/plain", true).unwrap();
        let text = String::from_utf8(out.out).unwrap();
        assert!(text.starts_with(&format!("HTTP/1.0 {code}")));
        for marker in [
            "HTTP/1.0",
            "WWW-Authenticate:",
            "Allow: GET",
            "Retry-After:",
            "Content-Disposition:",
        ] {
            if let Some(position) = text.find(marker) {
                let mut fail = Memory {
                    fail_at: Some(position),
                    ..Default::default()
                };
                assert!(
                    headers(&mut fail, code, "text/plain", true).is_err(),
                    "missing writer error for {marker}"
                );
            }
        }
    }
    let mut reply = Memory::default();
    respond(
        &mut reply,
        Request {
            target: "/missing".into(),
            authorization: Some("Bearer fixture".into()),
        },
        "fixture",
        &store,
    )
    .unwrap();
    assert!(String::from_utf8(reply.out)
        .unwrap()
        .starts_with("HTTP/1.0 404"));
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let mut client = TcpStream::connect(listener.local_addr().unwrap()).unwrap();
    let (_peer, _) = listener.accept().unwrap();
    let mut limited = Deadline {
        stream: &mut client,
        end: Instant::now() + Duration::from_secs(1),
        bytes: BODY_LIMIT,
    };
    assert!(limited.write(b"x").is_err());
}
