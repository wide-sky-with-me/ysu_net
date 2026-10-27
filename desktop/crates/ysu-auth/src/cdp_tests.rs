use super::*;

fn pair() -> (File, File) {
    let (reader, writer) = std::io::pipe().unwrap();
    (
        File::from(OwnedFd::from(reader)),
        File::from(OwnedFd::from(writer)),
    )
}

fn read_message(input: &mut impl std::io::Read) -> Value {
    let mut bytes = Vec::new();
    let mut byte = [0u8; 1];
    loop {
        input.read_exact(&mut byte).unwrap();
        if byte[0] == 0 {
            return serde_json::from_slice(&bytes).unwrap();
        }
        bytes.push(byte[0]);
    }
}

fn write_message(output: &mut impl std::io::Write, value: Value) {
    output.write_all(value.to_string().as_bytes()).unwrap();
    output.write_all(b"\0").unwrap();
}

async fn fixture(failing: bool) -> (Browser, tokio::task::JoinHandle<Vec<Value>>) {
    let (replies, mut peer_out) = pair();
    let (mut peer_in, commands) = pair();
    let peer = tokio::task::spawn_blocking(move || {
        let mut commands: Vec<Value> = Vec::new();
        for _ in 0..5 {
            commands.push(read_message(&mut peer_in));
        }
        let probe = read_message(&mut peer_in);
        commands.push(probe.clone());
        assert!(commands
            .iter()
            .all(|v| v["method"] != "Runtime.runIfWaitingForDebugger"));
        if failing {
            write_message(
                &mut peer_out,
                json!({"id":commands[0]["id"],"error":{"code":-1,"message":"fixture setup failed"}}),
            );
        } else {
            for command in &commands[..5] {
                write_message(&mut peer_out, json!({"id":command["id"],"result":{}}));
            }
            let resumed = read_message(&mut peer_in);
            assert_eq!(resumed["method"], "Runtime.runIfWaitingForDebugger");
            assert_eq!(resumed["sessionId"], "child");
            commands.push(resumed);
            write_message(
                &mut peer_out,
                json!({"id":probe["id"],"result":{"verified":true}}),
            );
        }
        commands
    });
    let pipe = Pipe::new(replies, commands, CDP_MESSAGE_LIMIT).unwrap();
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
        pipe,
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
        portal_bootstrap: false,
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
