use super::*;
#[test]
fn proc_fields_handle_missing_malformed_truncated_and_overflow_values() {
    let empty = parse("", "", "");
    assert!(empty.rss_bytes.is_none() && empty.cpu_ticks.is_none() && empty.write_bytes.is_none());
    let stat = format!(
        "1 (name with ) spaces) {}",
        (0..14).map(|n| n.to_string()).collect::<Vec<_>>().join(" ")
    );
    let good = parse(
        "VmRSS: 4 kB\nOther: 9",
        &stat,
        "read_bytes: 1\nwrite_bytes: 25\n",
    );
    assert_eq!(good.rss_bytes, Some(4096));
    assert_eq!(good.cpu_ticks, Some(23));
    assert_eq!(good.write_bytes, Some(25));
    for status in ["VmRSS:", "VmRSS: nope", "VmRSS: 18446744073709551615 kB"] {
        assert!(parse(status, &stat, "").rss_bytes.is_none());
    }
    for stat in [
        "1 (x)",
        "1 (x) 0 0 0 0 0 0 0 0 0 0 0 x 0",
        "1 (x) 0 0 0 0 0 0 0 0 0 0 0 1 x",
    ] {
        assert!(parse("", stat, "").cpu_ticks.is_none());
    }
    assert!(parse("", "", "write_bytes: bad").write_bytes.is_none());
    assert!(resources().rss_bytes.is_some());
}
#[test]
fn mounted_file_limits_and_encoding_are_enforced() {
    let p = std::env::temp_dir().join(format!("sdwan-proc-unit-{}", std::process::id()));
    fs::write(&p, b"abcd").unwrap();
    assert_eq!(read_limited(&p, 4).unwrap(), "abcd");
    assert!(read_limited(&p, 3).is_err());
    fs::write(&p, [255]).unwrap();
    assert!(read_limited(&p, 4).is_err());
    fs::remove_file(&p).unwrap();
    assert!(read_limited(&p, 4).is_err());
}
