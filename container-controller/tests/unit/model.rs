use super::*;
fn config() -> Config {
    serde_json::from_str(r#"{"schema_version":1,"revision":"fixture","policies":[{"name":"voice","profile":"voice","mode":"prefer","wans":["wan1","wan2"],"allow_degraded":false},{"name":"strict","profile":"voice","mode":"strict","wans":["wan1"],"allow_degraded":false}]}"#).unwrap()
}
fn metrics(a: &str, b: &str) -> Metrics {
    Metrics {
        revision: "fixture".into(),
        uptime_seconds: 1,
        states: BTreeMap::from([
            ("voice/wan1".into(), State { state: a.into() }),
            ("voice/wan2".into(), State { state: b.into() }),
        ]),
        container: None,
    }
}
#[test]
fn failover_strict_and_priority() {
    let c = config();
    assert_eq!(
        choose(&c, &metrics("healthy", "healthy")).unwrap()["voice"],
        "wan1"
    );
    let p = choose(&c, &metrics("down", "healthy")).unwrap();
    assert_eq!(p["voice"], "wan2");
    assert_eq!(p["strict"], "none");
}
#[test]
fn degraded_requires_explicit_permission_and_never_beats_healthy() {
    let mut c = config();
    assert_eq!(
        choose(&c, &metrics("degraded", "down")).unwrap()["voice"],
        "none"
    );
    c.policies[0].allow_degraded = true;
    assert_eq!(
        choose(&c, &metrics("degraded", "down")).unwrap()["voice"],
        "wan1"
    );
    assert_eq!(
        choose(&c, &metrics("degraded", "healthy")).unwrap()["voice"],
        "wan2"
    );
}
#[test]
fn unknown_recovering_and_missing_metrics_stay_closed() {
    let p = choose(&config(), &metrics("unknown", "recovering")).unwrap();
    assert!(p.values().all(|v| v == "none"));
}
#[test]
fn drain_and_emergency_down_refuse_new_connections_without_changing_sla() {
    let mut c = config();
    c.wans = vec![
        Wan {
            name: "wan1".into(),
            admin_state: "drain".into(),
        },
        Wan {
            name: "wan2".into(),
            admin_state: "enabled".into(),
        },
    ];
    let m = metrics("healthy", "healthy");
    let p = choose(&c, &m).unwrap();
    assert_eq!(p["voice"], "wan2");
    assert_eq!(p["strict"], "none");
    c.wans[1].admin_state = "down".into();
    assert!(choose(&c, &m).unwrap().values().all(|w| w == "none"));
    c.wans[0].admin_state = "enabled".into();
    assert_eq!(choose(&c, &m).unwrap()["voice"], "wan1");
    c.wans[0].admin_state = "typo".into();
    assert!(choose(&c, &m).is_err());
}
#[test]
fn mismatched_revision_rejected() {
    let mut m = metrics("healthy", "healthy");
    m.revision = "old".into();
    assert!(choose(&config(), &m).is_err());
}
#[test]
fn strict_with_backup_rejected() {
    let mut c = config();
    c.policies[1].wans.push("wan2".into());
    assert!(choose(&c, &metrics("healthy", "healthy")).is_err());
}
#[test]
fn declared_wans_default_enabled_and_all_invalid_contracts_are_rejected() {
    let mut c = config();
    let m = metrics("healthy", "healthy");
    c.wans = serde_json::from_str(r#"[{"name":"wan1"},{"name":"wan2"}]"#).unwrap();
    assert_eq!(choose(&c, &m).unwrap()["voice"], "wan1");
    for case in 0..8 {
        let mut c = config();
        match case {
            0 => c.schema_version = 2,
            1 => c.policies.clear(),
            2 => {
                c.policies = (0..65)
                    .map(|_| Policy {
                        name: "x".into(),
                        profile: "voice".into(),
                        mode: "strict".into(),
                        wans: vec!["wan1".into()],
                        allow_degraded: false,
                    })
                    .collect()
            }
            3 => {
                c.wans = (0..17)
                    .map(|n| Wan {
                        name: format!("wan{n}"),
                        admin_state: "enabled".into(),
                    })
                    .collect()
            }
            4 => {
                c.wans = vec![
                    Wan {
                        name: "x".into(),
                        admin_state: "enabled".into(),
                    },
                    Wan {
                        name: "x".into(),
                        admin_state: "enabled".into(),
                    },
                ]
            }
            5 => c.policies[0].wans.clear(),
            6 => c.policies[0].mode = "unknown".into(),
            _ => c.policies[1].name = "voice".into(),
        };
        assert!(choose(&c, &m).is_err());
    }
    let mut m = metrics("healthy", "healthy");
    m.states.clear();
    assert!(choose(&config(), &m).unwrap().values().all(|w| w == "none"));
}
