//! Bounded synchronous RouterOS API client. No worker pool or web server.
use std::collections::BTreeMap;
use std::io::{self, Read, Write};
use std::net::{SocketAddr, TcpStream};
use std::time::{Duration, Instant};

pub type Row = BTreeMap<String, String>;
const MAX_WORD: usize = 1024 * 1024;
const MAX_SENTENCE: usize = MAX_WORD + 8192;
const MAX_ROWS: usize = 512;
const MAX_RESPONSE: usize = 2 * MAX_WORD;

fn invalid(message: &'static str) -> io::Error {
    io::Error::new(io::ErrorKind::InvalidData, message)
}

pub fn write_word(out: &mut impl Write, word: &[u8]) -> io::Result<()> {
    if word.len() > MAX_WORD {
        return Err(invalid("API word limit exceeded"));
    }
    // MAX_WORD is below u32::MAX; the checked bound makes this cast lossless.
    let prefix = length_prefix(word.len() as u32);
    out.write_all(&prefix)?;
    out.write_all(word)
}

fn length_prefix(n: u32) -> Vec<u8> {
    if n < 0x80 {
        vec![n as u8]
    } else if n < 0x4000 {
        ((n | 0x8000) as u16).to_be_bytes().to_vec()
    } else if n < 0x20_0000 {
        let b = (n | 0xc0_0000).to_be_bytes();
        b[1..].to_vec()
    } else if n < 0x1000_0000 {
        (n | 0xe000_0000).to_be_bytes().to_vec()
    } else {
        let mut b = vec![0xf0];
        b.extend(n.to_be_bytes());
        b
    }
}

pub fn read_word(input: &mut impl Read) -> io::Result<Vec<u8>> {
    read_word_limit(input, MAX_WORD)
}
fn read_word_limit(input: &mut impl Read, limit: usize) -> io::Result<Vec<u8>> {
    let mut b = [0u8; 1];
    input.read_exact(&mut b)?;
    let first = b[0];
    let (extra, mut n): (usize, u32) = match first {
        0x00..=0x7f => (0, first as u32),
        0x80..=0xbf => (1, (first & 0x3f) as u32),
        0xc0..=0xdf => (2, (first & 0x1f) as u32),
        0xe0..=0xef => (3, (first & 0x0f) as u32),
        0xf0 => (4, 0),
        _ => return Err(invalid("Reserved API length prefix")),
    };
    for _ in 0..extra {
        input.read_exact(&mut b)?;
        n = (n << 8) | b[0] as u32;
    }
    if n as usize > MAX_WORD.min(limit) {
        return Err(invalid("API word limit exceeded"));
    }
    let mut word = vec![0; n as usize];
    input.read_exact(&mut word)?;
    Ok(word)
}

pub struct Api {
    stream: TcpStream,
    limit: usize,
    rows: usize,
    columns: usize,
    budget: Option<Duration>,
}
struct TimedRead<'a> {
    stream: &'a mut TcpStream,
    end: Instant,
}
impl Read for TimedRead<'_> {
    fn read(&mut self, data: &mut [u8]) -> io::Result<usize> {
        let remaining = self
            .end
            .checked_duration_since(Instant::now())
            .ok_or_else(|| io::Error::new(io::ErrorKind::TimedOut, "API command deadline"))?;
        self.stream
            .set_read_timeout(Some(remaining.min(Duration::from_millis(500))))?;
        self.stream.read(data)
    }
}
impl Api {
    pub fn connect(endpoint: SocketAddr, username: &str, password: &str) -> io::Result<Self> {
        Self::connect_limits(
            endpoint,
            username,
            password,
            Duration::from_secs(3),
            MAX_RESPONSE,
            MAX_ROWS,
        )
    }
    #[cfg(feature = "web")]
    pub fn connect_observer(
        endpoint: SocketAddr,
        username: &str,
        password: &str,
    ) -> io::Result<Self> {
        Self::connect_limits(
            endpoint,
            username,
            password,
            Duration::from_millis(500),
            65536,
            32,
        )
    }
    fn connect_limits(
        endpoint: SocketAddr,
        username: &str,
        password: &str,
        timeout: Duration,
        limit: usize,
        rows: usize,
    ) -> io::Result<Self> {
        // This small image deliberately uses the native API only over the local
        // isolated container veth, never an unencrypted Internet endpoint.
        let local = match endpoint.ip() {
            std::net::IpAddr::V4(ip) => ip.is_private() || ip.is_loopback(),
            std::net::IpAddr::V6(ip) => ip.is_loopback(),
        };
        if !local {
            return Err(invalid(
                "API endpoint must be a numeric private or loopback address",
            ));
        }
        let stream = TcpStream::connect_timeout(&endpoint, timeout)?;
        stream.set_nodelay(true)?;
        stream.set_read_timeout(Some(timeout))?;
        stream.set_write_timeout(Some(timeout))?;
        let mut api = Self {
            stream,
            limit,
            rows,
            columns: if rows <= 32 { 16 } else { 256 },
            budget: if rows <= 32 {
                Some(Duration::from_secs(2))
            } else {
                None
            },
        };
        // Never log request sentences: login words contain credentials.
        api.call(&[
            "/login".into(),
            format!("=name={username}"),
            format!("=password={password}"),
        ])?;
        Ok(api)
    }
    pub fn call(&mut self, words: &[String]) -> io::Result<Vec<Row>> {
        let end = self.budget.map(|budget| Instant::now() + budget);
        for word in words {
            write_word(&mut self.stream, word.as_bytes())?;
        }
        write_word(&mut self.stream, b"")?;
        self.stream.flush()?;
        let mut rows = Vec::new();
        let mut trap = false;
        let mut response_bytes = 0;
        loop {
            let mut sentence = Vec::new();
            let mut total = 0;
            loop {
                let word = match end {
                    Some(end) => read_word_limit(
                        &mut TimedRead {
                            stream: &mut self.stream,
                            end,
                        },
                        self.limit.saturating_sub(response_bytes),
                    ),
                    None => {
                        read_word_limit(&mut self.stream, self.limit.saturating_sub(response_bytes))
                    }
                }?;
                if word.is_empty() {
                    break;
                }
                total += word.len();
                response_bytes += word.len();
                if total > MAX_SENTENCE || sentence.len() >= self.columns {
                    return Err(invalid("API sentence limit exceeded"));
                }
                sentence
                    .push(String::from_utf8(word).map_err(|_| invalid("Non UTF-8 API response"))?);
            }
            let Some(kind) = sentence.first() else {
                continue;
            };
            match kind.as_str() {
                "!empty" => {} // RouterOS >=7.18; consume following !done.
                "!trap" => trap = true,
                "!fatal" => return Err(invalid("RouterOS API fatal response")),
                "!done" => {
                    if trap {
                        return Err(invalid("RouterOS API rejected the command"));
                    }
                    let done: Row = sentence
                        .iter()
                        .skip(1)
                        .filter_map(|w| w.strip_prefix('=').and_then(|s| s.split_once('=')))
                        .map(|(k, v)| (k.to_owned(), v.to_owned()))
                        .collect();
                    if !done.is_empty() {
                        rows.push(done);
                    }
                    return Ok(rows);
                }
                "!re" => {
                    if rows.len() >= self.rows {
                        return Err(invalid("API row limit exceeded"));
                    }
                    let row = sentence
                        .iter()
                        .skip(1)
                        .filter_map(|w| w.strip_prefix('=').and_then(|s| s.split_once('=')))
                        .map(|(k, v)| (k.to_owned(), v.to_owned()))
                        .collect();
                    rows.push(row);
                }
                _ => return Err(invalid("Unexpected API response kind")),
            }
        }
    }
    pub fn identity(&mut self) -> io::Result<String> {
        self.call(&["/system/identity/print".into(), "=.proplist=name".into()])?
            .first()
            .and_then(|r| r.get("name"))
            .cloned()
            .ok_or_else(|| invalid("Router identity unavailable"))
    }
    #[cfg(feature = "web")]
    pub fn interface_counters(&mut self, names: &[String]) -> io::Result<Vec<Row>> {
        if names.is_empty()
            || names.len() > 16
            || names.iter().any(|s| s.is_empty() || s.len() > 256)
        {
            return Err(invalid("Observer interface bounds exceeded"));
        }
        let mut words = vec![
            "/interface/print".into(),
            "=.proplist=name,rx-byte,tx-byte".into(),
            "=stats=".into(),
        ];
        words.extend(names.iter().map(|n| format!("?name={n}")));
        words.extend((1..names.len()).map(|_| "?#|".into()));
        self.call(&words)
    }
    pub fn environment(&mut self, name: &str) -> io::Result<Option<String>> {
        let rows = self.call(&[
            "/system/script/environment/print".into(),
            "=.proplist=name,value".into(),
            format!("?name={name}"),
        ])?;
        if rows.len() > 1 {
            return Err(invalid("Ambiguous controller environment variable"));
        }
        Ok(rows.first().and_then(|r| r.get("value")).cloned())
    }
    pub fn active_config(&mut self) -> io::Result<String> {
        if let Some(config) = self.environment("sdwanContainerConfigJSON")? {
            return Ok(config);
        }
        for name in ["flash/sdwan-active.json", "sdwan-active.json"] {
            let rows = self.call(&[
                "/file/print".into(),
                "=.proplist=.id,name".into(),
                format!("?name={name}"),
            ])?;
            if rows.len() != 1 {
                continue;
            }
            let id = rows[0]
                .get(".id")
                .ok_or_else(|| invalid("Config file identifier unavailable"))?;
            let rows = self.call(&[
                "/file/get".into(),
                format!("=number={id}"),
                "=value-name=contents".into(),
            ])?;
            return rows
                .first()
                .and_then(|r| r.get("ret"))
                .cloned()
                .ok_or_else(|| invalid("Config file contents unavailable"));
        }
        Err(invalid("Active SD-WAN configuration unavailable"))
    }
    pub fn write_intent(&mut self, name: &str, contents: &str) -> io::Result<()> {
        if name != "sdwan-container-intent.json" && name != "flash/sdwan-container-intent.json" {
            return Err(invalid("Unexpected intent filename"));
        }
        let rows = self.call(&[
            "/file/print".into(),
            "=.proplist=.id,name".into(),
            format!("?name={name}"),
        ])?;
        let id = rows
            .first()
            .filter(|_| rows.len() == 1)
            .and_then(|r| r.get(".id"))
            .ok_or_else(|| invalid("Provisioned intent file unavailable"))?;
        self.call(&[
            "/file/set".into(),
            format!("=.id={id}"),
            format!("=contents={contents}"),
        ])?;
        Ok(())
    }
}

#[cfg(test)]
#[path = "../tests/unit/api.rs"]
mod tests;
