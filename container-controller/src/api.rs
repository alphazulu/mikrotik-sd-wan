//! Bounded synchronous RouterOS API client. No worker pool or web server.
use std::collections::BTreeMap;
use std::io::{self, Read, Write};
use std::net::{SocketAddr, TcpStream};
use std::time::Duration;

pub type Row = BTreeMap<String, String>;
const MAX_WORD: usize = 1024 * 1024;
const MAX_SENTENCE: usize = MAX_WORD + 8192;
const MAX_ROWS: usize = 512;
const MAX_RESPONSE: usize = 2 * MAX_WORD;

fn invalid(message: &'static str) -> io::Error { io::Error::new(io::ErrorKind::InvalidData, message) }

pub fn write_word(out: &mut impl Write, word: &[u8]) -> io::Result<()> {
    let n = u32::try_from(word.len()).map_err(|_| invalid("API word too large"))?;
    if word.len() > MAX_WORD { return Err(invalid("API word limit exceeded")); }
    let prefix = if n < 0x80 { vec![n as u8] }
        else if n < 0x4000 { ((n | 0x8000) as u16).to_be_bytes().to_vec() }
        else if n < 0x20_0000 { let b = (n | 0xc0_0000).to_be_bytes(); b[1..].to_vec() }
        else if n < 0x1000_0000 { (n | 0xe000_0000).to_be_bytes().to_vec() }
        else { let mut b = vec![0xf0]; b.extend(n.to_be_bytes()); b };
    out.write_all(&prefix)?; out.write_all(word)
}

pub fn read_word(input: &mut impl Read) -> io::Result<Vec<u8>> {
    let mut b = [0u8; 1]; input.read_exact(&mut b)?;
    let first = b[0];
    let (extra, mut n): (usize, u32) = match first {
        0x00..=0x7f => (0, first as u32),
        0x80..=0xbf => (1, (first & 0x3f) as u32),
        0xc0..=0xdf => (2, (first & 0x1f) as u32),
        0xe0..=0xef => (3, (first & 0x0f) as u32),
        0xf0 => (4, 0),
        _ => return Err(invalid("Reserved API length prefix")),
    };
    for _ in 0..extra { input.read_exact(&mut b)?; n = (n << 8) | b[0] as u32; }
    if n as usize > MAX_WORD { return Err(invalid("API word limit exceeded")); }
    let mut word = vec![0; n as usize]; input.read_exact(&mut word)?; Ok(word)
}

pub struct Api { stream: TcpStream }
impl Api {
    pub fn connect(endpoint: SocketAddr, username: &str, password: &str) -> io::Result<Self> {
        // This small image deliberately uses the native API only over the local
        // isolated container veth, never an unencrypted Internet endpoint.
        let local = match endpoint.ip() { std::net::IpAddr::V4(ip) => ip.is_private() || ip.is_loopback(), std::net::IpAddr::V6(ip) => ip.is_loopback() };
        if !local { return Err(invalid("API endpoint must be a numeric private or loopback address")); }
        let stream = TcpStream::connect_timeout(&endpoint, Duration::from_secs(3))?;
        stream.set_nodelay(true)?;
        stream.set_read_timeout(Some(Duration::from_secs(3)))?;
        stream.set_write_timeout(Some(Duration::from_secs(3)))?;
        let mut api = Self { stream };
        // Never log request sentences: login words contain credentials.
        api.call(&["/login".into(), format!("=name={username}"), format!("=password={password}")])?;
        Ok(api)
    }
    pub fn call(&mut self, words: &[String]) -> io::Result<Vec<Row>> {
        for word in words { write_word(&mut self.stream, word.as_bytes())?; }
        write_word(&mut self.stream, b"")?; self.stream.flush()?;
        let mut rows = Vec::new(); let mut trap = false; let mut response_bytes = 0;
        loop {
            let mut sentence = Vec::new(); let mut total = 0;
            loop {
                let word = read_word(&mut self.stream)?;
                if word.is_empty() { break; }
                total += word.len();
                response_bytes += word.len();
                if response_bytes > MAX_RESPONSE { return Err(invalid("API response limit exceeded")); }
                if total > MAX_SENTENCE || sentence.len() >= 256 { return Err(invalid("API sentence limit exceeded")); }
                sentence.push(String::from_utf8(word).map_err(|_| invalid("Non UTF-8 API response"))?);
            }
            let Some(kind) = sentence.first() else { continue };
            match kind.as_str() {
                "!empty" => {}, // RouterOS >=7.18; consume following !done.
                "!trap" => trap = true,
                "!fatal" => return Err(invalid("RouterOS API fatal response")),
                "!done" => {
                    if trap { return Err(invalid("RouterOS API rejected the command")); }
                    let done: Row=sentence.iter().skip(1).filter_map(|w|w.strip_prefix('=').and_then(|s|s.split_once('='))).map(|(k,v)|(k.to_owned(),v.to_owned())).collect();
                    if !done.is_empty() { rows.push(done); }
                    return Ok(rows);
                },
                "!re" => {
                    if rows.len() >= MAX_ROWS { return Err(invalid("API row limit exceeded")); }
                    let row = sentence.iter().skip(1).filter_map(|w| w.strip_prefix('=').and_then(|s| s.split_once('='))).map(|(k,v)| (k.to_owned(),v.to_owned())).collect();
                    rows.push(row);
                }
                _ => return Err(invalid("Unexpected API response kind")),
            }
        }
    }
    pub fn identity(&mut self) -> io::Result<String> {
        self.call(&["/system/identity/print".into(), "=.proplist=name".into()])?.first().and_then(|r| r.get("name")).cloned().ok_or_else(|| invalid("Router identity unavailable"))
    }
    pub fn environment(&mut self, name: &str) -> io::Result<Option<String>> {
        let rows = self.call(&["/system/script/environment/print".into(), "=.proplist=name,value".into(), format!("?name={name}")])?;
        if rows.len() > 1 { return Err(invalid("Ambiguous controller environment variable")); }
        Ok(rows.first().and_then(|r| r.get("value")).cloned())
    }
    pub fn active_config(&mut self) -> io::Result<String> {
        if let Some(config)=self.environment("sdwanContainerConfigJSON")? { return Ok(config); }
        for name in ["flash/sdwan-active.json","sdwan-active.json"] {
            let rows=self.call(&["/file/print".into(),"=.proplist=.id,name".into(),format!("?name={name}")])?;
            if rows.len()!=1 { continue; }
            let id=rows[0].get(".id").ok_or_else(||invalid("Config file identifier unavailable"))?;
            let rows=self.call(&["/file/get".into(),format!("=number={id}"),"=value-name=contents".into()])?;
            return rows.first().and_then(|r|r.get("ret")).cloned().ok_or_else(||invalid("Config file contents unavailable"));
        }
        Err(invalid("Active SD-WAN configuration unavailable"))
    }
    pub fn write_intent(&mut self, name: &str, contents: &str) -> io::Result<()> {
        if name != "sdwan-container-intent.json" && name != "flash/sdwan-container-intent.json" { return Err(invalid("Unexpected intent filename")); }
        let rows = self.call(&["/file/print".into(), "=.proplist=.id,name".into(), format!("?name={name}")])?;
        let id = rows.first().filter(|_| rows.len()==1).and_then(|r| r.get(".id")).ok_or_else(|| invalid("Provisioned intent file unavailable"))?;
        self.call(&["/file/set".into(), format!("=.id={id}"), format!("=contents={contents}")])?;
        Ok(())
    }
}

#[cfg(test)] mod tests {
    use super::*;
    #[test] fn codec_boundaries_and_unicode() {
        for len in [0,1,127,128,16383,16384,100000] {
            let data=vec![b'x';len]; let mut bytes=Vec::new();write_word(&mut bytes,&data).unwrap();
            assert_eq!(read_word(&mut &bytes[..]).unwrap(),data);
        }
        let mut bytes=Vec::new();write_word(&mut bytes,"интерфейс".as_bytes()).unwrap();assert_eq!(read_word(&mut &bytes[..]).unwrap(),"интерфейс".as_bytes());
    }
    #[test] fn rejects_unbounded_or_reserved_response() {
        assert!(read_word(&mut &[0xf1u8][..]).is_err());
        assert!(read_word(&mut &[0xf0,0xff,0xff,0xff,0xff][..]).is_err());
        assert!(read_word(&mut &[0x80][..]).is_err());
    }
    #[test] fn public_endpoint_rejected_before_connect() {
        assert!(Api::connect("203.0.113.1:8728".parse().unwrap(),"fixture","fixture").is_err());
    }
    #[test] fn empty_reply_does_not_desynchronize_following_command() {
        use std::net::TcpListener;
        let listener=TcpListener::bind("127.0.0.1:0").unwrap();
        let address=listener.local_addr().unwrap();
        let worker=std::thread::spawn(move || {
            let (mut stream,_)=listener.accept().unwrap();
            for reply in [vec![vec!["!done"]],vec![vec!["!empty"],vec!["!done"]],vec![vec!["!re","=name=fixture"],vec!["!done"]]] {
                loop {if read_word(&mut stream).unwrap().is_empty(){break;}}
                for sentence in reply {for word in sentence {write_word(&mut stream,word.as_bytes()).unwrap();}write_word(&mut stream,b"").unwrap();}
            }
        });
        let mut api=Api::connect(address,"fixture","fixture").unwrap();
        assert!(api.environment("missing").unwrap().is_none());
        assert_eq!(api.identity().unwrap(),"fixture");
        worker.join().unwrap();
    }
}
