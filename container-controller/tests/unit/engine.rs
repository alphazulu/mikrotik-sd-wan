use super::*;
use crate::model::{Bridge, State};
#[derive(Default)]
struct Fake {
    reads: usize,
    writes: Vec<(String, serde_json::Value)>,
    fail_read: bool,
    fail_write: bool,
    bad_json: bool,
}
impl Client for Fake {
    fn active_config(&mut self) -> io::Result<String> {
        self.reads += 1;
        if self.fail_read {
            return Err(io::Error::other("fixture read failure"));
        }
        if self.bad_json {
            return Ok("{".into());
        }
        Ok(r#"{"schema_version":1,"revision":"test","policies":[{"name":"default","profile":"default","mode":"prefer","wans":["vpn","wan"],"allow_degraded":false}]}"#.into())
    }
    fn write_intent(&mut self, name: &str, text: &str) -> io::Result<()> {
        if self.fail_write {
            return Err(io::Error::other("fixture write failure"));
        }
        self.writes.push((name.into(), serde_json::from_str(text)?));
        Ok(())
    }
}
fn metrics() -> Metrics {
    Metrics {
        revision: "test".into(),
        uptime_seconds: 1,
        states: BTreeMap::from([
            (
                "default/vpn".into(),
                State {
                    state: "healthy".into(),
                },
            ),
            (
                "default/wan".into(),
                State {
                    state: "healthy".into(),
                },
            ),
        ]),
        container: Some(Bridge {
            protocol: 1,
            boot_id: "boot".into(),
            generation: 1,
            intent_file: "sdwan-container-intent.json".into(),
            owner_instance: String::new(),
            lease_remaining_seconds: 3,
        }),
    }
}
fn step(
    e: &mut Engine,
    f: &mut Fake,
    m: &Metrics,
    t: Instant,
    h: &mut usize,
) -> Result<Outcome, Box<dyn std::error::Error>> {
    e.step(
        f,
        m,
        || t,
        || {
            *h += 1;
            Ok(())
        },
    )
}
#[test]
fn shadow_computes_without_writes_or_heartbeat() {
    let t = Instant::now();
    let mut e = Engine::new(Mode::Shadow, "self".into());
    let mut f = Fake::default();
    let mut h = 0;
    let mut m = metrics();
    m.container = None;
    let a = step(&mut e, &mut f, &m, t, &mut h).unwrap();
    assert_eq!(a.state, "shadow:{\"default\":\"vpn\"}");
    assert_eq!(a.selected.unwrap()["default"], "vpn");
    assert!(f.writes.is_empty());
    assert_eq!(h, 0);
    assert_eq!(f.reads, 1);
    step(&mut e, &mut f, &m, t + Duration::from_secs(1), &mut h).unwrap();
    assert_eq!(f.reads, 1);
}
#[test]
fn no_bridge_old_protocol_and_another_owner_are_read_only() {
    for kind in 0..3 {
        let mut e = Engine::new(Mode::Active, "self".into());
        let mut f = Fake::default();
        let mut m = metrics();
        match kind {
            0 => m.container = None,
            1 => m.container.as_mut().unwrap().protocol = 9,
            _ => m.container.as_mut().unwrap().owner_instance = "other".into(),
        };
        let mut h = 0;
        let a = step(&mut e, &mut f, &m, Instant::now(), &mut h).unwrap();
        assert!(a.selected.is_none());
        assert!(f.writes.is_empty());
        assert_eq!(h, 0);
        assert!(a.state.contains(if kind == 2 {
            "another controller"
        } else {
            "protocol1"
        }));
    }
}
#[test]
fn expired_lease_only_sends_ram_heartbeat_even_if_old_owner_exists() {
    let mut e = Engine::new(Mode::Active, "self".into());
    let mut f = Fake::default();
    let mut m = metrics();
    m.container.as_mut().unwrap().lease_remaining_seconds = 0;
    m.container.as_mut().unwrap().owner_instance = "old".into();
    let mut h = 0;
    for i in 0..100 {
        m.uptime_seconds += 1;
        let a = step(
            &mut e,
            &mut f,
            &m,
            Instant::now() + Duration::from_secs(i),
            &mut h,
        )
        .unwrap();
        assert!(a.state.contains("RAM heartbeat"));
    }
    assert_eq!(h, 100);
    assert!(f.writes.is_empty());
}
#[test]
fn unchanged_claim_writes_once_and_live_owner_only_heartbeats() {
    let t = Instant::now();
    let mut e = Engine::new(Mode::Active, "self".into());
    let mut f = Fake::default();
    let mut m = metrics();
    let mut h = 0;
    let out = step(&mut e, &mut f, &m, t, &mut h).unwrap();
    assert!(out.state.starts_with("active:"));
    m.container.as_mut().unwrap().owner_instance = "self".into();
    for i in 1..100 {
        m.uptime_seconds += 1;
        step(&mut e, &mut f, &m, t + Duration::from_secs(i), &mut h).unwrap();
    }
    assert_eq!(h, 100);
    assert_eq!(f.reads, 1);
    assert_eq!(f.writes.len(), 1);
    let (name, intent) = &f.writes[0];
    assert_eq!(name, "sdwan-container-intent.json");
    assert_eq!(intent["instance"], "self");
    assert_eq!(intent["seq"], 1);
    assert_eq!(intent["boot_id"], "boot");
    assert_eq!(intent["generation"], 1);
    assert_eq!(intent["observed_uptime"], 1);
    assert_eq!(intent["selected"]["default"], "vpn");
    assert_eq!(intent["release"], false);
}
#[test]
fn unacknowledged_claim_retries_only_after_six_seconds() {
    let t = Instant::now();
    let mut e = Engine::new(Mode::Active, "self".into());
    let mut f = Fake::default();
    let mut m = metrics();
    let mut h = 0;
    for millis in [0, 1000, 5999, 6000, 6001] {
        m.uptime_seconds += 1;
        step(
            &mut e,
            &mut f,
            &m,
            t + Duration::from_millis(millis),
            &mut h,
        )
        .unwrap();
    }
    assert_eq!(f.writes.len(), 2);
    assert_eq!(f.writes[1].1["seq"], 2);
}
#[test]
fn policy_failure_failback_epoch_and_reconnect_invalidate_only_required_state() {
    let t = Instant::now();
    let mut e = Engine::new(Mode::Active, "self".into());
    let mut f = Fake::default();
    let mut m = metrics();
    let mut h = 0;
    step(&mut e, &mut f, &m, t, &mut h).unwrap();
    m.container.as_mut().unwrap().owner_instance = "self".into();
    m.states.get_mut("default/vpn").unwrap().state = "down".into();
    m.uptime_seconds += 1;
    step(&mut e, &mut f, &m, t, &mut h).unwrap();
    assert_eq!(f.writes[1].1["selected"]["default"], "wan");
    m.states.get_mut("default/vpn").unwrap().state = "healthy".into();
    m.uptime_seconds += 1;
    step(&mut e, &mut f, &m, t, &mut h).unwrap();
    assert_eq!(f.writes[2].1["selected"]["default"], "vpn");
    m.container.as_mut().unwrap().generation += 1;
    m.uptime_seconds += 1;
    step(&mut e, &mut f, &m, t, &mut h).unwrap();
    assert_eq!(f.reads, 2);
    assert_eq!(f.writes[3].1["generation"], 2);
    m.container.as_mut().unwrap().boot_id = "new-boot".into();
    m.uptime_seconds = 0;
    step(&mut e, &mut f, &m, t, &mut h).unwrap();
    assert_eq!(f.reads, 3);
    assert_eq!(f.writes[4].1["boot_id"], "new-boot");
    e.reset_session();
    step(&mut e, &mut f, &m, t, &mut h).unwrap();
    assert_eq!(f.reads, 4);
    assert_eq!(f.writes[5].1["seq"], 6);
}
#[test]
fn stalled_telemetry_blocks_writes_and_heartbeat_but_new_uptime_recovers() {
    let t = Instant::now();
    let mut e = Engine::new(Mode::Active, "self".into());
    let mut f = Fake::default();
    let mut m = metrics();
    let mut h = 0;
    step(&mut e, &mut f, &m, t, &mut h).unwrap();
    assert!(
        step(&mut e, &mut f, &m, t + Duration::from_secs(11), &mut h)
            .unwrap_err()
            .to_string()
            .contains("stalled")
    );
    assert_eq!(h, 1);
    assert_eq!(f.writes.len(), 1);
    m.uptime_seconds += 1;
    step(&mut e, &mut f, &m, t + Duration::from_secs(12), &mut h).unwrap();
    assert_eq!(h, 2);
}
#[test]
fn config_read_parse_revision_and_write_errors_stop_heartbeat() {
    for case in 0..4 {
        let mut e = Engine::new(Mode::Active, "self".into());
        let mut f = Fake::default();
        let mut m = metrics();
        match case {
            0 => f.fail_read = true,
            1 => f.bad_json = true,
            2 => m.revision = "wrong".into(),
            _ => f.fail_write = true,
        };
        let mut h = 0;
        assert!(step(&mut e, &mut f, &m, Instant::now(), &mut h).is_err());
        assert_eq!(h, 0);
        assert!(f.writes.is_empty());
    }
}
#[test]
fn heartbeat_failure_and_sequence_exhaustion_are_errors() {
    let mut e = Engine::new(Mode::Active, "self".into());
    let mut f = Fake::default();
    let mut m = metrics();
    m.container.as_mut().unwrap().lease_remaining_seconds = 0;
    assert!(e
        .step(&mut f, &m, Instant::now, || Err(io::Error::other(
            "fixture UDP failure"
        )))
        .is_err());
    assert!(f.writes.is_empty());
    m.container.as_mut().unwrap().lease_remaining_seconds = 3;
    e.seq = u64::MAX;
    assert!(e
        .step(&mut f, &m, Instant::now, || Ok(()))
        .unwrap_err()
        .to_string()
        .contains("sequence exhausted"));
    assert!(f.writes.is_empty());
}
#[test]
fn claim_retry_timer_starts_after_the_api_write_finishes() {
    use std::cell::Cell;
    struct Delayed<'a> {
        fake: Fake,
        clock: &'a Cell<Instant>,
        delay: Duration,
    }
    impl Client for Delayed<'_> {
        fn active_config(&mut self) -> io::Result<String> {
            self.fake.active_config()
        }
        fn write_intent(&mut self, name: &str, text: &str) -> io::Result<()> {
            self.fake.write_intent(name, text)?;
            self.clock.set(self.clock.get() + self.delay);
            Ok(())
        }
    }
    let start = Instant::now();
    let clock = Cell::new(start);
    let mut client = Delayed {
        fake: Fake::default(),
        clock: &clock,
        delay: Duration::from_secs(5),
    };
    let mut engine = Engine::new(Mode::Active, "self".into());
    let mut m = metrics();
    engine
        .step(&mut client, &m, || clock.get(), || Ok(()))
        .unwrap();
    assert_eq!(client.fake.writes.len(), 1);
    client.delay = Duration::ZERO;
    clock.set(start + Duration::from_secs(6));
    m.uptime_seconds += 1;
    engine
        .step(&mut client, &m, || clock.get(), || Ok(()))
        .unwrap();
    assert_eq!(
        client.fake.writes.len(),
        1,
        "slow API writes must not shorten the flash retry interval"
    );
    clock.set(start + Duration::from_secs(11));
    m.uptime_seconds += 1;
    engine
        .step(&mut client, &m, || clock.get(), || Ok(()))
        .unwrap();
    assert_eq!(client.fake.writes.len(), 2);
}
