//! Private CDP transport over anonymous pipes (`--remote-debugging-pipe`).
//! Unlike a loopback debugging port, no other local process can reach the
//! browser, read the injected credentials or drive the login page.
use std::{
    fs::File,
    io::{ErrorKind, Read, Write},
    sync::mpsc as std_mpsc,
};
use tokio::sync::mpsc;

/// Messages are NUL-terminated JSON in both directions.
pub(crate) struct Pipe {
    writer: Option<std_mpsc::Sender<Vec<u8>>>,
    reader: mpsc::Receiver<Vec<u8>>,
}

impl Pipe {
    /// `input` carries Chromium's output; `output` carries Chromium's input.
    /// A message larger than `limit` closes the connection.
    pub fn new(mut input: File, mut output: File, limit: usize) -> std::io::Result<Self> {
        let (writer, commands) = std_mpsc::channel::<Vec<u8>>();
        std::thread::Builder::new()
            .name("ysu-auth-cdp-writer".into())
            .spawn(move || {
                // Dropping `output` on exit signals EOF, which also makes Chromium shut down.
                for mut message in commands {
                    message.push(0);
                    if output.write_all(&message).is_err() {
                        return;
                    }
                }
            })?;
        let (sender, reader) = mpsc::channel(16);
        std::thread::Builder::new()
            .name("ysu-auth-cdp-reader".into())
            .spawn(move || {
                let mut pending = Vec::new();
                let mut chunk = vec![0u8; 64 * 1024];
                loop {
                    let read = match input.read(&mut chunk) {
                        Ok(0) => return,
                        Ok(read) => read,
                        Err(error) if error.kind() == ErrorKind::Interrupted => continue,
                        Err(_) => return,
                    };
                    let searched = pending.len();
                    pending.extend_from_slice(&chunk[..read]);
                    let mut start = 0;
                    let mut scan = searched;
                    while let Some(offset) = pending[scan..].iter().position(|byte| *byte == 0) {
                        let end = scan + offset;
                        if sender.blocking_send(pending[start..end].to_vec()).is_err() {
                            return;
                        }
                        start = end + 1;
                        scan = start;
                    }
                    pending.drain(..start);
                    if pending.len() > limit {
                        return;
                    }
                }
            })?;
        Ok(Self {
            writer: Some(writer),
            reader,
        })
    }

    pub fn send(&self, message: Vec<u8>) -> bool {
        self.writer
            .as_ref()
            .is_some_and(|writer| writer.send(message).is_ok())
    }

    /// `None` once Chromium closed its end, exited or sent an oversized message.
    pub async fn recv(&mut self) -> Option<Vec<u8>> {
        self.reader.recv().await
    }

    #[cfg(test)]
    pub fn close(&mut self) {
        self.writer = None;
    }
}

#[cfg(all(test, unix))]
mod tests {
    use super::*;

    fn pair() -> (File, File) {
        let (reader, writer) = std::io::pipe().unwrap();
        (
            File::from(std::os::fd::OwnedFd::from(reader)),
            File::from(std::os::fd::OwnedFd::from(writer)),
        )
    }

    #[tokio::test]
    async fn splits_nul_terminated_messages_across_reads_and_writes_terminators() {
        let (input, mut peer_out) = pair();
        let (mut peer_in, output) = pair();
        let mut pipe = Pipe::new(input, output, 1024).unwrap();
        peer_out.write_all(b"{\"id\":1}\0{\"id\"").unwrap();
        peer_out.write_all(b":2}\0").unwrap();
        assert_eq!(pipe.recv().await.unwrap(), b"{\"id\":1}");
        assert_eq!(pipe.recv().await.unwrap(), b"{\"id\":2}");
        assert!(pipe.send(b"{\"id\":3}".to_vec()));
        let mut sent = [0u8; 9];
        peer_in.read_exact(&mut sent).unwrap();
        assert_eq!(&sent, b"{\"id\":3}\0");
        drop(peer_out);
        assert!(pipe.recv().await.is_none());
    }

    #[tokio::test]
    async fn oversized_message_closes_the_connection() {
        let (input, mut peer_out) = pair();
        let (_peer_in, output) = pair();
        let mut pipe = Pipe::new(input, output, 8).unwrap();
        peer_out.write_all(&[b'x'; 64]).unwrap();
        assert!(pipe.recv().await.is_none());
    }

    #[tokio::test]
    async fn closing_our_side_signals_eof_to_the_peer() {
        let (input, _peer_out) = pair();
        let (mut peer_in, output) = pair();
        let mut pipe = Pipe::new(input, output, 1024).unwrap();
        pipe.close();
        let mut rest = Vec::new();
        peer_in.read_to_end(&mut rest).unwrap();
        assert!(rest.is_empty());
    }
}
