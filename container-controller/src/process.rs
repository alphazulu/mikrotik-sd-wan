//! Bounded mounted/proc readers and pure resource parsing shared by both images.
use serde::Serialize;
use std::{
    fs,
    io::{self, Read},
    path::Path,
};
#[derive(Clone, Default, Debug, Serialize)]
pub struct Resources {
    pub rss_bytes: Option<u64>,
    pub cpu_ticks: Option<u64>,
    pub write_bytes: Option<u64>,
}
pub fn read_limited(path: impl AsRef<Path>, limit: u64) -> io::Result<String> {
    let mut bytes = Vec::new();
    fs::File::open(path)?
        .take(limit.saturating_add(1))
        .read_to_end(&mut bytes)?;
    if bytes.len() as u64 > limit {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "Mounted file exceeds size limit",
        ));
    }
    String::from_utf8(bytes)
        .map_err(|_| io::Error::new(io::ErrorKind::InvalidData, "Mounted file is not UTF-8"))
}
pub fn parse(status: &str, stat: &str, io: &str) -> Resources {
    let rss = status
        .lines()
        .find(|s| s.starts_with("VmRSS:"))
        .and_then(|s| s.split_whitespace().nth(1))
        .and_then(|s| s.parse::<u64>().ok())
        .and_then(|n| n.checked_mul(1024));
    let ticks = stat
        .rsplit_once(')')
        .map(|(_, t)| t.split_whitespace().collect::<Vec<_>>())
        .and_then(|v| {
            Some(
                v.get(11)?
                    .parse::<u64>()
                    .ok()?
                    .saturating_add(v.get(12)?.parse::<u64>().ok()?),
            )
        });
    let writes = io.lines().find_map(|line| {
        line.strip_prefix("write_bytes:")
            .and_then(|s| s.trim().parse::<u64>().ok())
    });
    Resources {
        rss_bytes: rss,
        cpu_ticks: ticks,
        write_bytes: writes,
    }
}
pub fn resources() -> Resources {
    parse(
        &read_limited("/proc/self/status", 65536).unwrap_or_default(),
        &read_limited("/proc/self/stat", 8192).unwrap_or_default(),
        &read_limited("/proc/self/io", 8192).unwrap_or_default(),
    )
}
#[cfg(test)]
#[path = "../tests/unit/process.rs"]
mod tests;
