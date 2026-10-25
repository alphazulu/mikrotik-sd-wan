use super::*;
fn update(u: u64) -> Update {
    Update::parse(&format!(r#"{{"uptime_seconds":{u},"revision":"test","samples":{{"wan1":{{"interface":"ether2","rtt_us":1000,"jitter_us":10,"loss_basis_points":0,"link_ready":true}}}},"states":{{"default/wan1":{{"state":"healthy"}}}},"selected":{{"default":"wan1"}}}}"#)).unwrap()
}
#[test]
fn bounds_reject_extra_rows_long_text_and_duplicate_names() {
    let names = (0..17)
        .map(|n| format!("\"wan{n}\":{{}}"))
        .collect::<Vec<_>>()
        .join(",");
    assert!(Update::parse(&format!(
        r#"{{"uptime_seconds":1,"revision":"x","samples":{{{names}}}}}"#
    ))
    .is_err());
    assert!(Update::parse(
        r#"{"uptime_seconds":1,"revision":"x","samples":{"wan1":{},"wan1":{}}}"#
    )
    .is_err());
    assert!(Update::parse(&"x".repeat(MAX_RAW + 1)).is_err());
}
#[test]
fn optional_network_rows_are_bounded_and_legacy_empty_arrays_remain_valid() {
    for field in ["maintenance", "vpn_egress", "overlay"] {
        let rows = (0..17)
            .map(|n| format!("\"path{n}\":{{}}"))
            .collect::<Vec<_>>()
            .join(",");
        assert!(Update::parse(&format!(
            r#"{{"uptime_seconds":1,"revision":"x","{field}":{{{rows}}}}}"#
        ))
        .is_err());
        assert!(Update::parse(&format!(
            r#"{{"uptime_seconds":1,"revision":"x","{field}":[]}}"#
        ))
        .is_ok());
    }
    assert!(Update::parse(
        r#"{"uptime_seconds":1,"revision":"x","vpn_egress":{"vpn1":{"underlay":"bad/name"}}}"#
    )
    .is_err());
    assert!(Update::parse(
        r#"{"uptime_seconds":1,"revision":"x","maintenance":{"wan1":{"timeout_seconds":86401}}}"#
    )
    .is_err());
}
#[test]
fn optional_network_export_is_current_only_and_excludes_unknown_secrets() {
    let raw = r#"{"uptime_seconds":1,"revision":"x","samples":{"vpn1":{}},"maintenance":{"vpn1":{"configured":"drain","effective":"drain","admit":false,"elapsed_seconds":5,"timeout_seconds":30}},"vpn_egress":{"vpn1":{"underlay":"wan2","transport_ready":true,"private-key":"must-not-appear"}},"overlay":{"hub-wan1":{"wan":"wan1","healthy":true,"probe_up":true,"sample_age_seconds":1,"cost":10,"reason":"api-secret","password":"must-not-appear"}}}"#;
    let start = Instant::now();
    let mut store = Store::new("default".into(), 5, 12);
    store.ingest(Update::parse(raw).unwrap(), start, None, "api-secret", "");
    let current = store.status(start).current.unwrap();
    assert_eq!(current.transports[0].configured, AdminMode::Drain);
    assert!(!current.transports[0].admit);
    assert_eq!(current.transports[0].vpn_underlay.as_deref(), Some("wan2"));
    assert_eq!(current.transports[0].vpn_ready, Some(true));
    assert!(current.overlay[0].healthy);
    let safe = serde_json::to_string(&current).unwrap();
    assert!(!safe.contains("must-not-appear") && !safe.contains("api-secret"));
    assert!(store
        .export()
        .history
        .wans
        .values()
        .all(|points| points.len() == 1));
    store.ingest(update(2), start + Duration::from_secs(1), None, "", "");
    assert!(store.status(start).current.unwrap().overlay.is_empty());
}
#[test]
fn history_is_bounded_and_epoch_reset_discards_old_rows() {
    let start = Instant::now();
    let mut s = Store::new("default".into(), 5, 12);
    for i in 0..100 {
        s.ingest(
            update(i * 5),
            start + Duration::from_secs(i * 5),
            None,
            "",
            "",
        );
    }
    assert_eq!(s.history(600).wans["wan1"].len(), 12);
    assert_eq!(s.history(2).wans["wan1"].len(), 2);
    let mut u = update(501);
    u.revision.0 = "new".into();
    s.ingest(u, start + Duration::from_secs(501), None, "", "");
    assert_eq!(s.history(600).wans["wan1"].len(), 1);
    assert_eq!(s.status(start).epoch, 2);
}
#[test]
fn no_new_uptime_becomes_stale_and_gaps_are_not_counted() {
    let start = Instant::now();
    let mut s = Store::new("default".into(), 10, 12);
    s.ingest(update(1), start, None, "", "");
    s.ingest(update(1), start + Duration::from_secs(20), None, "", "");
    assert!(s.status(start + Duration::from_secs(20)).stale);
    s.ingest(update(100), start + Duration::from_secs(100), None, "", "");
    assert_eq!(s.status(start).current.unwrap().wans[0].observed_seconds, 0);
}
#[test]
fn counter_reset_unknown_values_and_secret_fields_are_safe() {
    assert_eq!(rate(200, 100, Duration::from_secs(1)), Some(800));
    assert_eq!(rate(1, 100, Duration::from_secs(1)), None);
    assert_eq!(rate(1, 0, Duration::ZERO), None);
    let start = Instant::now();
    let mut s = Store::new("default".into(), 5, 12);
    let mut u = update(1);
    u.revision.0 = "api-fixture-secret".into();
    u.events.0.push(NativeEvent {
        seq: 1,
        reason: Text("web-fixture-token api-fixture-secret".into()),
        ..Default::default()
    });
    s.ingest(u, start, None, "api-fixture-secret", "web-fixture-token");
    let data = serde_json::to_string(&(s.status(start), s.export())).unwrap();
    assert!(!data.contains("api-fixture-secret"));
    assert!(!data.contains("web-fixture-token"));
    assert!(data.contains("redacted"));
    assert!(data.contains("\"rx_bps\":null"));
}
#[test]
fn packet_errors_do_not_clear_good_history() {
    let start = Instant::now();
    let mut s = Store::new("default".into(), 5, 12);
    s.ingest(update(1), start, None, "", "");
    s.invalid();
    assert_eq!(s.status(start).history_points, 1);
    assert_eq!(s.status(start).invalid_snapshots, 1);
}
#[test]
fn worst_case_export_fits_http_budget_and_ring_stops_growing() {
    let mut s = Store::new("default".into(), 5, 600);
    for n in 0..16 {
        let points = VecDeque::from(vec![
            Point(
                u64::MAX,
                Some(u32::MAX),
                Some(u32::MAX),
                Some(10000),
                Some(u64::MAX),
                Some(u64::MAX),
                4,
                7
            );
            600
        ]);
        s.wans.insert(
            format!("wan{n}"),
            WanStore {
                interface: "ether2".into(),
                points,
                counter: None,
                rx: None,
                tx: None,
                observed: 0,
                unhealthy: 0,
            },
        );
    }
    for _ in 0..200 {
        s.event(Event {
            seq: 0,
            uptime_seconds: u64::MAX,
            kind: "\\".repeat(16),
            policy: "\\".repeat(64),
            from: "\\".repeat(32),
            to: "\\".repeat(32),
            reason: "\\".repeat(192),
        });
    }
    assert_eq!(s.events.len(), EVENT_CAP);
    let bytes = serde_json::to_vec(&s.export()).unwrap();
    assert!(bytes.len() + 2048 < 1048576, "{}", bytes.len());
    assert_eq!(
        s.history(600).wans.values().map(Vec::len).sum::<usize>(),
        9600
    );
}
#[test]
fn old_revision_events_are_excluded_and_fallback_is_observed() {
    let start = Instant::now();
    let mut s = Store::new("default".into(), 5, 12);
    let mut u = update(1);
    u.backend.0 = "container".into();
    u.container = Some(Bridge {
        active: true,
        ..Default::default()
    });
    u.events.0.push(NativeEvent {
        seq: 1,
        revision: Text("old-config".into()),
        reason: Text("must-not-appear".into()),
        ..Default::default()
    });
    s.ingest(u.clone(), start, None, "", "");
    u.uptime_seconds = 2;
    u.container.as_mut().unwrap().active = false;
    s.ingest(u, start + Duration::from_secs(1), None, "", "");
    let events = s.events(0);
    assert_eq!(events.events.len(), 2);
    assert_eq!(events.events[1].kind, "actor");
    assert_eq!(events.events[1].to, "routeros-fallback");
    assert!(!serde_json::to_string(&events)
        .unwrap()
        .contains("must-not-appear"));
}
#[test]
fn malformed_containers_bounds_identifiers_and_loss_are_rejected() {
    for raw in [
        "true",
        "42",
        "{}",
        r#"{"uptime_seconds":1,"revision":false}"#,
        r#"{"uptime_seconds":1,"revision":"x","samples":true}"#,
        r#"{"uptime_seconds":1,"revision":"x","samples":[1]}"#,
        r#"{"uptime_seconds":1,"revision":"x","samples":{"Bad/name":{}}}"#,
        r#"{"uptime_seconds":1,"revision":"x","states":{"missing-slash":{"state":"healthy"}}}"#,
        r#"{"uptime_seconds":1,"revision":"x","samples":{"wan1":{"loss_basis_points":10001}}}"#,
        r#"{"uptime_seconds":1,"revision":"x","events":{}}"#,
    ] {
        assert!(Update::parse(raw).is_err(), "{raw}");
    }
    let raw = serde_json::json!({"uptime_seconds":1,"revision":"x".repeat(321)}).to_string();
    assert!(Update::parse(&raw).is_err());
    let raw=serde_json::json!({"uptime_seconds":1,"revision":"x","events":vec![serde_json::json!({});101]}).to_string();
    assert!(Update::parse(&raw).is_err());
    assert!(serde_json::from_str::<Text<3>>("false").is_err());
    assert!(serde_json::from_str::<Text<3>>(r#""ёж""#).is_err());
    assert!(serde_json::from_str::<Map<u8, 1>>("false").is_err());
    assert!(serde_json::from_str::<List<u8, 1>>("false").is_err());
    assert!(serde_json::from_str::<List<u8, 1>>("[1,2]").is_err());
}
#[test]
fn qualities_freshness_interface_replacement_and_counter_resets_are_distinct() {
    let start = Instant::now();
    let mut s = Store::new("default".into(), 1, 12);
    let mut counter = Counter {
        at: start,
        rx: 100,
        tx: 200,
    };
    for i in 0..8 {
        let mut u = update(i + 1);
        let mut c = counter.clone();
        c.at = start + Duration::from_secs(i);
        c.rx += 100 * i;
        c.tx += 200 * i;
        if i == 2 {
            c = counter.clone();
        }
        if i == 3 {
            c.rx = 1;
            c.tx = 1;
        }
        if i == 4 {
            u.samples.0.get_mut("wan1").unwrap().stale = true;
        }
        if i == 5 {
            u.samples.0.get_mut("wan1").unwrap().warming = true;
        }
        if i == 6 {
            u.states.0.get_mut("default/wan1").unwrap().state = Quality::Degraded;
        }
        if i == 7 {
            u.samples.0.get_mut("wan1").unwrap().link_ready = false;
        }
        let counters = BTreeMap::from([("ether2".into(), c.clone())]);
        s.ingest(u, start + Duration::from_secs(i), Some(&counters), "", "");
        if i == 1 {
            assert_eq!(s.status(start).current.unwrap().wans[0].rx_bps, Some(800));
        }
        if i == 3 {
            assert!(s.status(start).current.unwrap().wans[0].rx_bps.is_none());
        }
        counter = c;
    }
    let w = &s.status(start).current.unwrap().wans[0];
    assert!(w.unhealthy_seconds > 0);
    assert_eq!(w.state, Quality::Down);
    let mut u = update(10);
    u.samples.0.get_mut("wan1").unwrap().interface.0 = "new-interface".into();
    s.ingest(u, start + Duration::from_secs(10), None, "", "");
    assert_eq!(s.history(12).wans["wan1"].len(), 1);
    assert_eq!(s.status(start).current.unwrap().wans[0].observed_seconds, 0);
    let mut u = update(11);
    u.samples.0.get_mut("wan1").unwrap().loss_basis_points = Some(10000);
    s.ingest(u, start + Duration::from_secs(11), None, "", "");
    assert!(s.status(start).current.unwrap().wans[0].rtt_us.is_none());
    assert_eq!(rate(u64::MAX, 0, Duration::from_nanos(1)), None);
}
#[test]
fn native_and_inferred_transitions_are_not_double_counted_and_sequence_reset_is_detected() {
    let start = Instant::now();
    let mut s = Store::new("default".into(), 1, 12);
    let mut u = update(1);
    u.events.0.push(NativeEvent {
        seq: 5,
        kind: Text("policy".into()),
        policy: Text("default".into()),
        from: Text("wan2".into()),
        to: Text("wan1".into()),
        ..Default::default()
    });
    s.ingest(u, start, None, "", "");
    assert_eq!(s.status(start).current.unwrap().policies[0].transitions, 0);
    let mut u = update(2);
    u.selected.0.insert("default".into(), Text("wan2".into()));
    u.events.0.push(NativeEvent {
        seq: 1,
        kind: Text("policy".into()),
        policy: Text("default".into()),
        from: Text("wan1".into()),
        to: Text("wan2".into()),
        ..Default::default()
    });
    s.ingest(u, start + Duration::from_secs(1), None, "", "");
    assert_eq!(s.status(start).current.unwrap().policies[0].transitions, 1);
    s.ingest(update(3), start + Duration::from_secs(2), None, "", "");
    assert_eq!(s.status(start).current.unwrap().policies[0].transitions, 2);
    assert_eq!(
        s.events(0).events.last().unwrap().reason,
        "Observed policy selection changed"
    );
    assert_eq!(text("ёжёж", "", "", 3), "ё");
    assert_eq!(
        text("secret\0token", "secret", "token", 64),
        "[redacted] [redacted]"
    );
}
#[test]
fn explicit_event_lists_addresses_and_all_epoch_keys_are_handled() {
    let raw = r#"{"uptime_seconds":1,"revision":"x","events":[{"seq":1,"type":"policy"}],"samples":{"wan1":{"address":"192.0.2.1","link_ready":true}},"container":{"boot_id":"boot","generation":1}}"#;
    let u = Update::parse(raw).unwrap();
    let mut s = Store::new("default".into(), 1, 12);
    assert!(s.epoch_changed(&u));
    s.ingest(u.clone(), Instant::now(), None, "", "");
    assert_eq!(
        s.status(Instant::now()).current.unwrap().wans[0]
            .address
            .as_deref(),
        Some("192.0.2.1")
    );
    assert!(!s.epoch_changed(&u));
    let mut next = u.clone();
    next.container.as_mut().unwrap().generation += 1;
    assert!(s.epoch_changed(&next));
    next = u.clone();
    next.container.as_mut().unwrap().boot_id.0 = "other".into();
    assert!(s.epoch_changed(&next));
    next = u.clone();
    next.revision.0 = "other".into();
    assert!(s.epoch_changed(&next));
}
#[test]
fn the_same_small_text_bound_accepts_valid_utf8_and_rejects_overflow() {
    assert_eq!(serde_json::from_str::<Text<3>>(r#""ok""#).unwrap().0, "ok");
    assert!(serde_json::from_str::<Text<3>>(r#""long""#).is_err());
}
#[test]
fn bounded_map_and_list_decoders_check_success_limits_and_truncated_input() {
    let one: Map<u8, 1> = serde_json::from_str(r#"{"a":1}"#).unwrap();
    assert_eq!(one.0["a"], 1);
    for raw in [r#"{"a":1,"b":2}"#, r#"{"a":"wrong-type"}"#, "{", "[", "[1]"] {
        assert!(serde_json::from_str::<Map<u8, 1>>(raw).is_err(), "{raw}");
    }
    let long_key = serde_json::json!({"x".repeat(65):1}).to_string();
    assert!(serde_json::from_str::<Map<u8, 1>>(&long_key).is_err());
    assert!(serde_json::from_str::<Map<u8, 1>>("[]")
        .unwrap()
        .0
        .is_empty());
    assert_eq!(
        serde_json::from_str::<List<u8, 1>>("[1]").unwrap().0,
        vec![1]
    );
    assert!(serde_json::from_str::<List<u8, 1>>("[").is_err());
    for field in [
        "samples",
        "selected",
        "states",
        "maintenance",
        "vpn_egress",
        "overlay",
    ] {
        let empty = format!(r#"{{"uptime_seconds":1,"revision":"test","{field}":[]}}"#);
        assert!(Update::parse(&empty).is_ok());
        let nonempty = format!(r#"{{"uptime_seconds":1,"revision":"test","{field}":[1]}}"#);
        assert!(Update::parse(&nonempty).is_err());
        let truncated = format!(r#"{{"uptime_seconds":1,"revision":"test","{field}":["#);
        assert!(Update::parse(&truncated).is_err());
    }
}
