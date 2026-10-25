use crate::api::{read_word, write_word};
use std::{
    net::{SocketAddr, TcpListener},
    thread::{self, JoinHandle},
    time::Duration,
};
pub fn reply(rows: &[&[&str]]) -> Vec<Vec<String>> {
    rows.iter()
        .map(|r| r.iter().map(|v| (*v).into()).collect())
        .collect()
}
pub fn server(replies: Vec<Vec<Vec<String>>>) -> (SocketAddr, JoinHandle<Vec<Vec<String>>>) {
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let addr = listener.local_addr().unwrap();
    let job = thread::spawn(move || {
        let (mut stream, _) = listener.accept().unwrap();
        stream
            .set_read_timeout(Some(Duration::from_secs(2)))
            .unwrap();
        let mut commands = vec![];
        for response in replies {
            let mut words = vec![];
            loop {
                let bytes = read_word(&mut stream).unwrap();
                if bytes.is_empty() {
                    break;
                }
                words.push(String::from_utf8(bytes).unwrap());
            }
            commands.push(words);
            for sentence in response {
                for word in sentence {
                    write_word(&mut stream, word.as_bytes()).unwrap();
                }
                write_word(&mut stream, b"").unwrap();
            }
        }
        commands
    });
    (addr, job)
}
