use super::*;
#[test]
fn disabled_is_default_without_sources() {
    let s = Settings::default();
    assert!(!s.enabled);
    assert!(s.validate().unwrap().is_empty());
}
#[test]
fn private_sources_are_canonical_and_bounded() {
    assert!(Network::parse("192.168.50.0/24")
        .unwrap()
        .contains("192.168.50.101".parse().unwrap()));
    for n in [
        "0.0.0.0/0",
        "8.8.8.0/24",
        "172.0.0.0/8",
        "192.168.50.2/24",
        "127.0.0.1",
        "::1/128",
    ] {
        assert!(Network::parse(n).is_err(), "{n}");
    }
}
#[test]
fn enabled_requires_explicit_safe_settings() {
    let mut s = Settings {
        enabled: true,
        ..Default::default()
    };
    assert!(s.validate().is_err());
    s.allowed_sources = vec!["192.168.50.0/24".into()];
    assert!(s.validate().is_ok());
    s.token_file = "/secrets/api-password".into();
    assert!(s.validate().is_err());
    s.token_file = "/secrets/web-token".into();
    s.history_points = 601;
    assert!(s.validate().is_err());
}
#[test]
fn listener_source_profile_and_sampling_boundaries_are_enforced() {
    for address in ["127.0.0.1:80", "[::1]:8080", "203.0.113.1:8080"] {
        let mut s = Settings {
            enabled: true,
            allowed_sources: vec!["127.0.0.0/8".into()],
            ..Default::default()
        };
        s.listen = address.parse().unwrap();
        assert!(s.validate().is_err());
    }
    for profile in ["", "bad/profile"] {
        let s = Settings {
            enabled: true,
            allowed_sources: vec!["127.0.0.0/8".into()],
            profile: profile.into(),
            ..Default::default()
        };
        assert!(s.validate().is_err());
    }
    for n in [
        "192.168.0.0/16",
        "172.16.0.0/12",
        "10.0.0.0/8",
        "127.0.0.0/8",
    ] {
        assert!(Network::parse(n).is_ok());
    }
    for n in [
        "10.0.0.0/7",
        "172.16.0.0/11",
        "192.168.0.0/15",
        "127.0.0.0/7",
        "1.2.3.4/nope",
        "300.0.0.1/32",
        "1.2.3.4/33",
    ] {
        assert!(Network::parse(n).is_err());
    }
}
