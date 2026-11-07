use super::*;
#[test]
fn codec_boundaries_and_unicode() {
    for len in [0, 1, 127, 128, 16383, 16384, 100000] {
        let data = vec![b'x'; len];
        let mut bytes = Vec::new();
        write_word(&mut bytes, &data).unwrap();
        assert_eq!(read_word(&mut &bytes[..]).unwrap(), data);
    }
    let mut bytes = Vec::new();
    write_word(&mut bytes, "интерфейс".as_bytes()).unwrap();
    assert_eq!(read_word(&mut &bytes[..]).unwrap(), "интерфейс".as_bytes());
}
#[test]
fn rejects_unbounded_or_reserved_response() {
    assert!(read_word(&mut &[0xf1u8][..]).is_err());
    assert!(read_word(&mut &[0xf0, 0xff, 0xff, 0xff, 0xff][..]).is_err());
    assert!(read_word(&mut &[0x80][..]).is_err());
}
#[test]
fn public_endpoint_rejected_before_connect() {
    assert!(Api::connect("203.0.113.1:8728".parse().unwrap(), "fixture", "fixture").is_err());
}
#[test]
fn empty_reply_does_not_desynchronize_following_command() {
    use std::net::TcpListener;
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let address = listener.local_addr().unwrap();
    let worker = std::thread::spawn(move || {
        let (mut stream, _) = listener.accept().unwrap();
        for reply in [
            vec![vec!["!done"]],
            vec![vec!["!empty"], vec!["!done"]],
            vec![vec!["!re", "=name=fixture"], vec!["!done"]],
        ] {
            loop {
                if read_word(&mut stream).unwrap().is_empty() {
                    break;
                }
            }
            for sentence in reply {
                for word in sentence {
                    write_word(&mut stream, word.as_bytes()).unwrap();
                }
                write_word(&mut stream, b"").unwrap();
            }
        }
    });
    let mut api = Api::connect(address, "fixture", "fixture").unwrap();
    assert!(api.environment("missing").unwrap().is_none());
    assert_eq!(api.identity().unwrap(), "fixture");
    worker.join().unwrap();
}
#[cfg(feature = "web")]
#[test]
fn observer_only_requests_bounded_exact_interface_counters() {
    use std::net::TcpListener;
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let address = listener.local_addr().unwrap();
    let worker = std::thread::spawn(move || {
        let (mut stream, _) = listener.accept().unwrap();
        for step in 0..3 {
            let mut words = Vec::new();
            loop {
                let word = read_word(&mut stream).unwrap();
                if word.is_empty() {
                    break;
                }
                words.push(String::from_utf8(word).unwrap());
            }
            match step {
                0 => assert_eq!(words[0], "/login"),
                1 => assert_eq!(words, vec!["/system/identity/print", "=.proplist=name"]),
                _ => assert_eq!(
                    words,
                    vec![
                        "/interface/print",
                        "=.proplist=name,rx-byte,tx-byte",
                        "=stats=",
                        "?name=ether2",
                        "?name=pppoe-wan",
                        "?#|"
                    ]
                ),
            }
            if step > 0 {
                for word in if step == 1 {
                    vec!["!re", "=name=test"]
                } else {
                    vec!["!re", "=name=ether2", "=rx-byte=100", "=tx-byte=200"]
                } {
                    write_word(&mut stream, word.as_bytes()).unwrap();
                }
                write_word(&mut stream, b"").unwrap();
            }
            write_word(&mut stream, b"!done").unwrap();
            write_word(&mut stream, b"").unwrap();
        }
    });
    let mut api = Api::connect_observer(address, "fixture", "fixture").unwrap();
    assert_eq!(api.identity().unwrap(), "test");
    let counters = api
        .interface_counters(&["ether2".into(), "pppoe-wan".into()])
        .unwrap();
    assert_eq!(counters[0]["rx-byte"], "100");
    worker.join().unwrap();
    assert!(api.interface_counters(&vec!["ether2".into(); 17]).is_err());
    let mut prefix = Vec::new();
    write_word(&mut prefix, &vec![b'x'; 65537]).unwrap();
    assert_eq!(
        read_word_limit(&mut &prefix[..4], 65536)
            .unwrap_err()
            .kind(),
        io::ErrorKind::InvalidData
    );
}
use crate::test_support::{reply, server};
#[test]
fn length_formats_limits_and_transport_failures() {
    for (n, expected) in [
        (0, vec![0]),
        (127, vec![127]),
        (128, vec![128, 128]),
        (16384, vec![192, 64, 0]),
        (0x20_0000, vec![224, 32, 0, 0]),
        (0x1000_0000, vec![240, 16, 0, 0, 0]),
        (u32::MAX, vec![240, 255, 255, 255, 255]),
    ] {
        assert_eq!(length_prefix(n), expected);
    }
    assert_eq!(read_word(&mut &[224, 0, 0, 1, b'x'][..]).unwrap(), b"x");
    assert_eq!(read_word(&mut &[240, 0, 0, 0, 1, b'x'][..]).unwrap(), b"x");
    assert!(write_word(&mut vec![], &vec![0; MAX_WORD + 1]).is_err());
    struct Broken;
    impl Write for Broken {
        fn write(&mut self, _: &[u8]) -> io::Result<usize> {
            Err(io::Error::other("fixture write failure"))
        }
        fn flush(&mut self) -> io::Result<()> {
            Ok(())
        }
    }
    assert!(write_word(&mut Broken, b"x").is_err());
    assert!(Api::connect("[2001:db8::1]:8728".parse().unwrap(), "fixture", "fixture").is_err());
    let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
    let mut client = TcpStream::connect(listener.local_addr().unwrap()).unwrap();
    let (mut peer, _) = listener.accept().unwrap();
    let mut timed = TimedRead {
        stream: &mut client,
        end: Instant::now() - Duration::from_secs(1),
    };
    assert_eq!(
        timed.read(&mut [0]).unwrap_err().kind(),
        io::ErrorKind::TimedOut
    );
    peer.write_all(b"x").unwrap();
    let mut timed = TimedRead {
        stream: &mut client,
        end: Instant::now() + Duration::from_secs(1),
    };
    let mut byte = [0];
    assert_eq!(timed.read(&mut byte).unwrap(), 1);
    assert_eq!(byte[0], b'x');
}
#[test]
fn response_kinds_attributes_and_all_aggregate_budgets() {
    for (case, response) in [
        (0, reply(&[&["!fatal"]])),
        (
            1,
            reply(&[&["!trap", "=message=fixture-auth-secret"], &["!done"]]),
        ),
        (2, reply(&[&["!unexpected"]])),
        (
            3,
            reply(&[
                &[],
                &["!empty"],
                &["!done", "=ret=a=b", "ignored", "=unterminated"],
            ]),
        ),
        (4, reply(&[&["!re", "=k=1"], &["!re", "=k=2"], &["!done"]])),
        (5, reply(&[&["!re", "=column=1", "=other=2"], &["!done"]])),
        (6, reply(&[&["!re", "=long-value=too-large"], &["!done"]])),
    ] {
        let (addr, job) = server(vec![reply(&[&["!done"]]), response]);
        let mut api = Api::connect(addr, "fixture", "fixture").unwrap();
        match case {
            4 => api.rows = 1,
            5 => api.columns = 2,
            6 => api.limit = 8,
            _ => {}
        }
        let result = api.call(&["/fixture".into()]);
        if case == 3 {
            assert_eq!(result.unwrap()[0]["ret"], "a=b");
        } else {
            let error = result.unwrap_err().to_string();
            assert!(!error.contains("auth-secret"));
        }
        drop(api);
        job.join().unwrap();
    }
    let response = vec![vec!["!re".into(), "x".repeat(MAX_WORD), "x".repeat(8193)]];
    let (addr, job) = server(vec![reply(&[&["!done"]]), response]);
    let mut api = Api::connect(addr, "fixture", "fixture").unwrap();
    assert!(api.call(&["/fixture".into()]).is_err());
    drop(api);
    job.join().unwrap();
}
#[test]
fn config_ram_cache_and_both_storage_fallbacks_validate_identifiers_and_contents() {
    let (addr, job) = server(vec![
        reply(&[&["!done"]]),
        reply(&[&["!re", "=value=ram-config"], &["!done"]]),
    ]);
    let mut api = Api::connect(addr, "fixture", "fixture").unwrap();
    assert_eq!(api.active_config().unwrap(), "ram-config");
    drop(api);
    job.join().unwrap();
    for case in 0..5 {
        let mut replies = vec![reply(&[&["!done"]]), reply(&[&["!done"]])];
        if case == 0 {
            replies.push(reply(&[&["!re", "=.id=*1"], &["!done"]]));
            replies.push(reply(&[&["!done", "=ret=flash-config"]]));
        } else if case == 2 {
            replies.push(reply(&[&["!re", "=name=missing-id"], &["!done"]]));
        } else if case == 4 {
            replies.push(reply(&[&["!re", "=.id=*1"], &["!done"]]));
            replies.push(reply(&[&["!done"]]));
        } else {
            replies.push(reply(&[&["!done"]]));
            if case == 1 {
                replies.push(reply(&[&["!re", "=.id=*2"], &["!done"]]));
                replies.push(reply(&[&["!done", "=ret=root-config"]]));
            } else {
                replies.push(reply(&[&["!done"]]));
            }
        }
        let (addr, job) = server(replies);
        let mut api = Api::connect(addr, "fixture", "fixture").unwrap();
        let result = api.active_config();
        if case == 0 {
            assert_eq!(result.unwrap(), "flash-config");
        } else if case == 1 {
            assert_eq!(result.unwrap(), "root-config");
        } else {
            assert!(result.is_err());
        }
        drop(api);
        job.join().unwrap();
    }
}
#[test]
fn environment_identity_and_intent_file_ownership_are_checked() {
    for kind in 0..4 {
        let response = match kind {
            0 => reply(&[&["!done"]]),
            1 => reply(&[&["!re", "=value=a"], &["!re", "=value=b"], &["!done"]]),
            2 => reply(&[&["!re", "=name=missing-value"], &["!done"]]),
            _ => reply(&[&["!re", "=name=fixture"], &["!done"]]),
        };
        let (addr, job) = server(vec![reply(&[&["!done"]]), response]);
        let mut api = Api::connect(addr, "fixture", "fixture").unwrap();
        match kind {
            0 => assert!(api.identity().is_err()),
            1 => assert!(api.environment("x").is_err()),
            2 => assert!(api.environment("x").unwrap().is_none()),
            _ => assert_eq!(api.identity().unwrap(), "fixture"),
        };
        drop(api);
        job.join().unwrap();
    }
    for case in 0..5 {
        let mut replies = vec![reply(&[&["!done"]])];
        if case != 0 {
            replies.push(if case == 1 {
                reply(&[&["!done"]])
            } else if case == 2 {
                reply(&[&["!re", "=name=missing-id"], &["!done"]])
            } else {
                reply(&[&["!re", "=.id=*7"], &["!done"]])
            });
            if case >= 3 {
                replies.push(reply(&[&["!done"]]));
            }
        }
        let (addr, job) = server(replies);
        let mut api = Api::connect(addr, "fixture", "fixture").unwrap();
        let name = if case == 0 {
            "foreign.json"
        } else if case == 4 {
            "flash/sdwan-container-intent.json"
        } else {
            "sdwan-container-intent.json"
        };
        let result = api.write_intent(name, "fixture-intent");
        assert_eq!(result.is_ok(), case >= 3);
        drop(api);
        let commands = job.join().unwrap();
        if case >= 3 {
            assert_eq!(
                commands[2],
                vec!["/file/set", "=.id=*7", "=contents=fixture-intent"]
            );
        }
    }
}
#[test]
fn invalid_utf8_response_is_rejected_without_echoing_payload() {
    let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
    let addr = listener.local_addr().unwrap();
    let job = std::thread::spawn(move || {
        let (mut s, _) = listener.accept().unwrap();
        for step in 0..2 {
            loop {
                if read_word(&mut s).unwrap().is_empty() {
                    break;
                }
            }
            if step == 0 {
                write_word(&mut s, b"!done").unwrap();
                write_word(&mut s, b"").unwrap();
            } else {
                write_word(&mut s, b"!re").unwrap();
                write_word(&mut s, &[255]).unwrap();
                write_word(&mut s, b"").unwrap();
            }
        }
    });
    let mut api = Api::connect(addr, "fixture", "fixture").unwrap();
    assert_eq!(
        api.call(&["/fixture".into()]).unwrap_err().to_string(),
        "Non UTF-8 API response"
    );
    drop(api);
    job.join().unwrap();
}
#[test]
fn bounded_command_deadlines_apply_in_the_base_profile_too() {
    let (addr, job) = server(vec![
        reply(&[&["!done"]]),
        reply(&[&["!re", "=name=fixture"], &["!done"]]),
    ]);
    let mut api = Api::connect_limits(
        addr,
        "fixture",
        "fixture",
        Duration::from_millis(500),
        65536,
        32,
    )
    .unwrap();
    assert!(api.budget.is_some());
    assert_eq!(api.identity().unwrap(), "fixture");
    drop(api);
    job.join().unwrap();
}
