use super::*;
use crate::{Config, transport::{Operation, Transport}};
use serde_json::Value;
use std::sync::Mutex;
use tokio::io::{AsyncReadExt, AsyncWriteExt};

fn recording() -> (Trace, Arc<Mutex<Vec<Value>>>) {
    let events = Arc::new(Mutex::new(Vec::new()));
    let sink = events.clone();
    (Trace::new(move |event| sink.lock().unwrap().push(serde_json::to_value(event).unwrap())), events)
}

#[tokio::test]
async fn response_body_failure_is_distinct_from_connection_failure_without_private_data() {
    for partial_response in [false, true] {
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let address = listener.local_addr().unwrap();
        let server = tokio::spawn(async move {
            let (mut socket, _) = listener.accept().await.unwrap();
            let mut bytes = Vec::new();
            while !bytes.ends_with(b"\r\n\r\n") {
                let mut byte = [0];
                socket.read_exact(&mut byte).await.unwrap(); bytes.push(byte[0]);
            }
            if partial_response {
                socket.write_all(b"HTTP/1.1 200 OK\r\nContent-Length: 4096\r\nSet-Cookie: private-cookie=fixture-secret\r\nConnection: close\r\n\r\nfixture-private-response").await.unwrap();
            }
        });
        let config = Config { base: format!("http://{address}"), ..Config::default() };
        let http = Transport::new(&config, true).unwrap();
        let (trace, events) = recording();
        let result = trace.run(DiagnosticOperation::Status, false, true, 3, async {
            let op = Operation::new(tokio::time::Instant::now() + std::time::Duration::from_secs(3));
            http.get(http.endpoint("eportal/index.jsp?ticket=fixture-private-ticket").unwrap(), &op).await
        }).await;
        assert!(result.is_err()); server.await.unwrap();
        let records = events.lock().unwrap();
        let failure = records.iter().find(|v| v["event"] == "request_finished").unwrap();
        assert_eq!(failure["outcome"], "failed");
        assert_eq!(failure["failure"]["phase"], if partial_response { "read_body" } else { "send" });
        assert_eq!(records.first().unwrap()["event"], "operation_started");
        assert_eq!(records.last().unwrap()["event"], "operation_finished");
        assert_eq!(records.last().unwrap()["outcome"], "failed");
        let serialized = serde_json::to_string(&*records).unwrap();
        for private in ["fixture-private-ticket", "fixture-secret", "private-cookie", "fixture-private-response", "127.0.0.1"] {
            assert!(!serialized.contains(private), "trace leaked a private fixture value");
        }
    }
}

#[tokio::test]
async fn cancelled_operations_have_a_terminal_event_and_ids_do_not_repeat() {
    let (trace, events) = recording();
    assert!(tokio::time::timeout(std::time::Duration::from_millis(5), trace.run(
        DiagnosticOperation::Login, false, true, 3, std::future::pending::<Result<(), AuthError>>()
    )).await.is_err());
    trace.run(DiagnosticOperation::Status, false, true, 3, async { Ok(()) }).await.unwrap();
    let events = events.lock().unwrap();
    assert_eq!(events.len(), 4);
    assert_eq!(events[1]["outcome"], "cancelled");
    assert_eq!(events[1]["operation_id"], 1);
    assert_eq!(events[3]["operation_id"], 2);
    assert_eq!(events[3]["outcome"], "success");
}

#[tokio::test]
async fn free_form_error_messages_cannot_enter_trace_output() {
    let (trace, events) = recording();
    let result: Result<(), AuthError> = trace.run(DiagnosticOperation::Login, false, true, 3,
        async { Err(AuthError::new(2, "fixture-password https://private.invalid/?ticket=fixture-ticket")) }).await;
    assert!(result.is_err());
    let text = serde_json::to_string(&*events.lock().unwrap()).unwrap();
    for private in ["fixture-password", "private.invalid", "fixture-ticket"] { assert!(!text.contains(private)); }
}
