use super::*;

async fn fixture(failing: bool) -> (Browser, tokio::task::JoinHandle<Vec<Value>>) {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let peer = tokio::spawn(async move {
        let (socket, _) = listener.accept().await.unwrap();
        let mut socket = tokio_tungstenite::accept_async(socket).await.unwrap();
        let mut commands: Vec<Value> = Vec::new();
        for _ in 0..5 {
            let message = socket.next().await.unwrap().unwrap();
            commands.push(serde_json::from_str(message.to_text().unwrap()).unwrap());
        }
        let probe = socket.next().await.unwrap().unwrap();
        let probe: Value = serde_json::from_str(probe.to_text().unwrap()).unwrap();
        commands.push(probe.clone());
        assert!(commands
            .iter()
            .all(|v| v["method"] != "Runtime.runIfWaitingForDebugger"));
        if failing {
            socket.send(Message::Text(json!({"id":commands[0]["id"],"error":{"code":-1,"message":"fixture setup failed"}}).to_string().into())).await.unwrap();
        } else {
            for command in &commands[..5] {
                socket
                    .send(Message::Text(
                        json!({"id":command["id"],"result":{}}).to_string().into(),
                    ))
                    .await
                    .unwrap();
            }
            let resumed = socket.next().await.unwrap().unwrap();
            let resumed: Value = serde_json::from_str(resumed.to_text().unwrap()).unwrap();
            assert_eq!(resumed["method"], "Runtime.runIfWaitingForDebugger");
            assert_eq!(resumed["sessionId"], "child");
            commands.push(resumed);
            socket
                .send(Message::Text(
                    json!({"id":probe["id"],"result":{"verified":true}})
                        .to_string()
                        .into(),
                ))
                .await
                .unwrap();
        }
        commands
    });
    let (ws, _) = connect_async_with_config(format!("ws://{address}"), None, true)
        .await
        .unwrap();
    let profile = tempfile::tempdir().unwrap();
    let child = Command::new("/bin/sleep")
        .arg("10")
        .process_group(0)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .unwrap();
    let config = Config {
        base: "http://127.0.0.1:1".into(),
        cas_host: "http://127.0.0.1:1".into(),
        ..Config::default()
    };
    let http = Transport::new(&config, true).unwrap();
    let browser = Browser {
        ws,
        _process: Process {
            child: Some(child),
            profile: Some(profile),
        },
        last: http.base.clone(),
        http,
        session: "main".into(),
        main_frame: "main-frame".into(),
        next_id: 1,
        contexts: BTreeSet::new(),
        initialization: BTreeMap::new(),
        initializing_children: BTreeMap::new(),
        redirects: 0,
        requests: 0,
        sid: None,
    };
    (browser, peer)
}

#[tokio::test]
async fn child_is_resumed_only_after_all_initialization_acknowledgements() {
    let (mut browser, peer) = fixture(false).await;
    let op = Operation::new(Instant::now() + std::time::Duration::from_secs(2));
    for session in ["first", "second"] {
        browser.event(json!({"method":"Runtime.executionContextCreated","sessionId":session,
            "params":{"context":{"id":7,"origin":"http://127.0.0.1:1","auxData":{"isDefault":true}}}}), &op).await.unwrap();
    }
    assert_eq!(browser.contexts.len(), 2);
    browser
        .event(
            json!({"method":"Runtime.executionContextsCleared","sessionId":"first","params":{}}),
            &op,
        )
        .await
        .unwrap();
    assert_eq!(browser.contexts.len(), 1);
    assert!(browser.contexts.contains(&("second".into(), 7)));
    browser
        .event(
            json!({"method":"Target.detachedFromTarget","params":{"sessionId":"second"}}),
            &op,
        )
        .await
        .unwrap();
    assert!(browser.contexts.is_empty());
    browser
        .event(
            json!({"method":"Target.attachedToTarget","params":{"sessionId":"child"}}),
            &op,
        )
        .await
        .unwrap();
    assert_eq!(browser.initialization.len(), 5);
    assert_eq!(
        browser
            .rpc("fixtureProbe", json!({}), None, &op)
            .await
            .unwrap()["verified"],
        true
    );
    assert!(browser.initialization.is_empty());
    assert!(browser.initializing_children.is_empty());
    assert_eq!(peer.await.unwrap().len(), 7);
}

#[tokio::test]
async fn child_fetch_setup_error_aborts_without_resuming_or_raw_error_leak() {
    let (mut browser, peer) = fixture(true).await;
    let op = Operation::new(Instant::now() + std::time::Duration::from_secs(2));
    browser
        .event(
            json!({"method":"Target.attachedToTarget","params":{"sessionId":"child"}}),
            &op,
        )
        .await
        .unwrap();
    let error = browser
        .rpc("fixtureProbe", json!({}), None, &op)
        .await
        .unwrap_err();
    assert_eq!(error.code, crate::QUERY_ERROR);
    assert!(!error.message.contains("fixture setup failed"));
    assert_eq!(peer.await.unwrap().len(), 6);
}
