//! These tests exercise runtime policy with in-memory authentication, not the campus protocol.
use super::*;

fn fixture() -> (Arc<Runtime>, mpsc::Receiver<Action>) {
    Runtime::new(Store::open(None, true).unwrap(), Arc::new(|_| {})).unwrap()
}
fn demo(runtime: &Runtime) -> Arc<Mutex<Demo>> {
    match &runtime.backend {
        Backend::Demo(demo) => demo.clone(),
        _ => panic!("fixture must be isolated"),
    }
}
async fn wait(runtime: &Runtime, predicate: impl Fn(&Value) -> bool) {
    tokio::time::timeout(Duration::from_secs(3), async {
        loop {
            if predicate(&runtime.snapshot()) {
                break;
            }
            tokio::time::sleep(Duration::from_millis(5)).await;
        }
    })
    .await
    .expect("fixture state did not settle");
}
async fn action(runtime: &Runtime, name: &str) {
    runtime
        .request("action", json!({"name":name}))
        .await
        .unwrap();
}

#[test]
fn request_boundaries_are_strict() {
    for command in ["snapshot", "diagnostics", "browser_install"] {
        assert!(valid_request(command, &json!({})));
        assert!(!valid_request(command, &json!([])));
        assert!(!valid_request(command, &json!({"exec":"anything"})));
    }
    for value in [
        json!({"name":"unknown"}),
        json!({"name":"login","value":false}),
        json!({"name":"set_auto","value":1}),
        json!({"name":"switch","value":"unknown"}),
        json!({"name":"status","extra":true}),
    ] {
        assert!(!valid_request("action", &value));
    }
    assert!(!valid_request("shutdown", &json!({})));
    assert!(!valid_request(
        "save_config",
        &json!({"password":"x".repeat(MAX_REQUEST)})
    ));
    assert!(!valid_request(
        "save_config",
        &json!({"operation_timeout":1.1})
    ));
    assert!(!valid_request("save_config", &json!({"password_set":true})));
    assert!(!valid_request(
        "save_prefs",
        &json!({"auto_reconnect":true})
    ));
    assert!(valid_request(
        "action",
        &json!({"name":"switch","value":"中国移动"})
    ));
    assert!(valid_request(
        "save_config",
        &json!({"password":"","verify_tls":false})
    ));
    for accent in ["teal", "blue", "indigo", "violet", "rose", "amber"] {
        assert!(valid_request("save_prefs", &json!({"accent":accent})));
        assert!(valid_request(
            "save_prefs",
            &json!({"accent":accent,"theme":"dark","close_to_tray":false})
        ));
    }
    for accent in [
        json!("future-accent"),
        json!("TEAL"),
        json!("teal "),
        json!(""),
        json!(null),
        json!(false),
        json!(1),
        json!([]),
        json!({}),
    ] {
        assert!(!valid_request("save_prefs", &json!({"accent":accent})));
    }
    assert!(!valid_request(
        "save_prefs",
        &json!({"accent":"blue","auto_reconnect":true})
    ));
    assert!(!valid_request(
        "save_prefs",
        &json!({"accent":"blue","extra":true})
    ));
}

#[tokio::test]
async fn passwords_past_and_current_are_scrubbed_and_logs_are_bounded() {
    let (runtime, _) = fixture();
    runtime
        .request("save_config", json!({"password":"old-secret"}))
        .await
        .unwrap();
    runtime
        .request("save_config", json!({"password":"new-secret"}))
        .await
        .unwrap();
    runtime.update(|state| {
        for _ in 0..2005 { state.log("info", &format!("old-secret new-secret{}", "x".repeat(3000))); }
        state.info = json!({"online":true,"fields":[["label","new-secret"]],"items":[["old-secret","text"]]});
    });
    let snapshot = runtime.snapshot();
    let serialized = snapshot.to_string();
    assert!(!serialized.contains("old-secret"));
    assert!(!serialized.contains("new-secret"));
    assert!(snapshot["config"].get("password").is_none());
    assert_eq!(snapshot["config"]["password_set"], true);
    assert_eq!(snapshot["logs"].as_array().unwrap().len(), 2000);
    assert!(
        snapshot["logs"][0]["message"]
            .as_str()
            .unwrap()
            .chars()
            .count()
            <= 2048
    );
    assert!(chrono::DateTime::parse_from_rfc3339(
        snapshot["logs"][0]["timestamp"].as_str().unwrap()
    )
    .is_ok());
}

#[tokio::test]
async fn queue_has_fixed_capacity_and_actions_only_acknowledge_queueing() {
    let (runtime, receiver) = fixture();
    for _ in 0..QUEUE_SIZE {
        action(&runtime, "login").await;
    }
    assert!(runtime
        .request("action", json!({"name":"login"}))
        .await
        .unwrap_err()
        .contains("队列已满"));
    assert!(runtime.snapshot()["status"].is_null());
    assert_eq!(demo(&runtime).lock().unwrap().logins, 0);
    drop(receiver);
    assert!(runtime
        .request("action", json!({"name":"status"}))
        .await
        .is_err());
}

#[tokio::test]
async fn snapshot_settings_diagnostics_do_not_wait_for_authentication_and_shutdown_cancels() {
    let (runtime, receiver) = fixture();
    demo(&runtime).lock().unwrap().delay = Duration::from_secs(180);
    runtime.launch(receiver);
    action(&runtime, "login").await;
    wait(&runtime, |s| {
        s["busy_message"] == "正在登录并确认连接" && demo(&runtime).lock().unwrap().in_flight == 1
    })
    .await;
    tokio::time::timeout(Duration::from_millis(500), async {
        runtime.request("snapshot", json!({})).await.unwrap();
        runtime
            .request("save_config", json!({"username":"concurrent-user"}))
            .await
            .unwrap();
        runtime
            .request("save_prefs", json!({"theme":"dark","accent":"blue"}))
            .await
            .unwrap();
        let snapshot = runtime.snapshot();
        assert_eq!(snapshot["prefs"]["accent"], "blue");
        assert_eq!(runtime.store.load_prefs().accent, "blue");
        assert_eq!(snapshot["busy"], true);
        assert_eq!(snapshot["prefs"]["auto_reconnect"], false);
        runtime.request("browser_install", json!({})).await.unwrap();
    })
    .await
    .unwrap();
    tokio::time::timeout(Duration::from_secs(1), runtime.shutdown())
        .await
        .unwrap();
    assert!(runtime.store.acquire_run().is_ok());
    assert_eq!(demo(&runtime).lock().unwrap().logins, 1);
    assert_eq!(demo(&runtime).lock().unwrap().cancelled, 1);
    assert!(runtime.request("snapshot", json!({})).await.is_err());
}

#[tokio::test]
async fn demo_runs_full_native_action_flow_without_external_resources() {
    let (runtime, receiver) = fixture();
    runtime.launch(receiver);
    wait(&runtime, |s| s["status"]["online"] == false).await;
    action(&runtime, "login").await;
    wait(&runtime, |s| {
        s["status"]["online"] == true && s["busy"] == false
    })
    .await;
    runtime
        .request("action", json!({"name":"switch","value":"中国移动"}))
        .await
        .unwrap();
    wait(&runtime, |s| {
        s["status"]["service"] == "中国移动" && s["busy"] == false
    })
    .await;
    action(&runtime, "info").await;
    wait(&runtime, |s| {
        s["info"]["online"] == true && s["busy"] == false
    })
    .await;
    runtime
        .request("action", json!({"name":"set_auto","value":true}))
        .await
        .unwrap();
    wait(&runtime, |s| s["auto"]["state"] == "on").await;
    action(&runtime, "logout").await;
    wait(&runtime, |s| {
        s["status"]["online"] == false && s["busy"] == false && s["auto"]["state"] == "off"
    })
    .await;
    assert!(!runtime.store.load_prefs().auto_reconnect);
    let environment = runtime.snapshot()["environment"].clone();
    assert_eq!(environment.as_object().unwrap().len(), 6);
    assert_eq!(environment["runtime"], "rust");
    assert!(environment.get("python").is_none());
    assert!(environment.get("node_available").is_none());
    runtime.shutdown().await;
}

#[tokio::test]
async fn logout_intent_is_persisted_even_when_queue_is_full() {
    let (runtime, _receiver) = fixture();
    runtime
        .request("action", json!({"name":"set_auto","value":true}))
        .await
        .unwrap();
    for _ in 0..QUEUE_SIZE {
        action(&runtime, "status").await;
    }
    assert!(runtime
        .request("action", json!({"name":"logout"}))
        .await
        .is_err());
    assert!(!runtime.desired.load(Ordering::Acquire));
    assert!(!runtime.store.load_prefs().auto_reconnect);
    assert_eq!(runtime.snapshot()["auto"]["state"], "off");
}

#[tokio::test]
async fn disabling_auto_cancels_inflight_reconnect_without_logout() {
    let (runtime, receiver) = fixture();
    demo(&runtime).lock().unwrap().delay = Duration::from_secs(180);
    runtime.launch(receiver);
    runtime
        .request("action", json!({"name":"set_auto","value":true}))
        .await
        .unwrap();
    wait(&runtime, |s| {
        s["auto"]["state"] == "on"
            && s["busy"] == true
            && demo(&runtime).lock().unwrap().in_flight == 1
    })
    .await;
    runtime
        .request("action", json!({"name":"set_auto","value":false}))
        .await
        .unwrap();
    wait(&runtime, |s| {
        s["busy"] == false && s["auto"]["state"] == "off"
    })
    .await;
    assert_eq!(demo(&runtime).lock().unwrap().logins, 1);
    assert_eq!(demo(&runtime).lock().unwrap().cancelled, 1);
    assert!(runtime.store.acquire_run().is_ok());
    runtime.shutdown().await;
}

#[tokio::test]
async fn coalesced_rotation_disable_enable_cancels_the_previous_automatic_operation() {
    let (runtime, receiver) = fixture();
    runtime.request("save_account",json!({"username":"fixture-b","password":"fixture-only","label":"Backup","service":"校园网","backend":"api","enabled":true})).await.unwrap();
    runtime.set_rotation(true).await.unwrap();
    demo(&runtime).lock().unwrap().delay = Duration::from_secs(180);
    runtime.launch(receiver);
    wait(&runtime, |_| demo(&runtime).lock().unwrap().in_flight == 1).await;
    // A watch receiver may only observe the final enabled flag after off/on.
    runtime.rotation_version.fetch_add(2, Ordering::AcqRel);
    runtime.wake();
    wait(&runtime, |_| demo(&runtime).lock().unwrap().cancelled >= 1).await;
    assert!(runtime.desired.load(Ordering::Acquire));
    assert!(runtime.rotation_enabled.load(Ordering::Acquire));
    assert_eq!(demo(&runtime).lock().unwrap().logouts, 0);
    runtime.shutdown().await;
}

#[tokio::test]
async fn external_lock_blocks_mutations_but_not_reads_or_settings() {
    let (runtime, receiver) = fixture();
    let guard = runtime.store.acquire_run().unwrap();
    let mut worker = Worker::new(runtime.clone(), receiver);
    worker.execute(Action::Login).await.unwrap();
    assert_eq!(demo(&runtime).lock().unwrap().logins, 0);
    assert_eq!(runtime.snapshot()["auto"]["state"], "external");
    worker.execute(Action::Status).await.unwrap();
    assert_eq!(runtime.snapshot()["status"]["online"], false);
    runtime
        .request("save_config", json!({"service":"中国移动"}))
        .await
        .unwrap();
    let before = runtime.snapshot();
    let saved = runtime
        .request("save_prefs", json!({"accent":"amber"}))
        .await
        .unwrap();
    assert_eq!(saved["prefs"]["accent"], "amber");
    assert_eq!(runtime.store.load_prefs().accent, "amber");
    for key in ["auto", "accounts", "status", "config", "busy"] {
        assert_eq!(saved[key], before[key]);
    }
    assert!(!runtime.desired.load(Ordering::Acquire));
    assert_eq!(demo(&runtime).lock().unwrap().logins, 0);
    drop(guard);
    worker.execute(Action::Login).await.unwrap();
    assert_eq!(demo(&runtime).lock().unwrap().logins, 1);
}

#[tokio::test]
async fn unknown_status_never_triggers_automatic_login() {
    let (runtime, receiver) = fixture();
    runtime.desired.store(true, Ordering::Release);
    demo(&runtime).lock().unwrap().status_error = Some(2);
    let mut worker = Worker::new(runtime.clone(), receiver);
    worker.guard = Some(runtime.store.acquire_run().unwrap());
    worker.tick().await;
    assert!(runtime.snapshot()["status"]["online"].is_null());
    assert_eq!(demo(&runtime).lock().unwrap().logins, 0);
    assert_eq!(worker.reconnect.failures, 1);
}

#[tokio::test]
async fn interaction_pause_only_clears_on_configuration_change_or_manual_login() {
    let (runtime, receiver) = fixture();
    runtime.desired.store(true, Ordering::Release);
    demo(&runtime).lock().unwrap().operation_error = Some(4);
    let mut worker = Worker::new(runtime.clone(), receiver);
    worker.guard = Some(runtime.store.acquire_run().unwrap());
    worker.tick().await;
    worker.tick().await;
    assert_eq!(demo(&runtime).lock().unwrap().logins, 1);
    demo(&runtime).lock().unwrap().online = true;
    worker.tick().await;
    demo(&runtime).lock().unwrap().online = false;
    worker.tick().await;
    assert_eq!(demo(&runtime).lock().unwrap().logins, 1);
    runtime
        .request("save_config", json!({"password":"changed-password"}))
        .await
        .unwrap();
    worker.tick().await;
    assert_eq!(demo(&runtime).lock().unwrap().logins, 2);
    worker.execute(Action::Login).await.unwrap();
    assert_eq!(demo(&runtime).lock().unwrap().logins, 3);
}

#[test]
fn exponential_backoff_and_jitter_never_exceed_cap() {
    let config = Config {
        retry_interval: 30,
        max_retry_interval: 100,
        ..Config::default()
    };
    let mut reconnect = Reconnect::default();
    assert_eq!(reconnect.delay(&config, 0.1), 33.0);
    assert_eq!(reconnect.delay(&config, 0.0), 60.0);
    assert_eq!(reconnect.delay(&config, 0.1), 100.0);
    for _ in 0..100 {
        assert_eq!(reconnect.delay(&config, 1.0), 100.0);
    }
}

#[tokio::test]
async fn account_failure_clears_account_without_faking_offline() {
    let (runtime, receiver) = fixture();
    let mut worker = Worker::new(runtime.clone(), receiver);
    worker.execute(Action::Login).await.unwrap();
    worker.execute(Action::Info).await.unwrap();
    assert_eq!(runtime.snapshot()["info"]["online"], true);
    demo(&runtime).lock().unwrap().info_error = true;
    worker.execute(Action::Info).await.unwrap();
    assert!(runtime.snapshot()["info"].is_null());
    assert_eq!(runtime.snapshot()["status"]["online"], true);
}

#[tokio::test]
async fn failed_switch_keeps_real_service_and_saved_configuration() {
    let (runtime, receiver) = fixture();
    let mut worker = Worker::new(runtime.clone(), receiver);
    worker.execute(Action::Login).await.unwrap();
    demo(&runtime).lock().unwrap().operation_error = Some(3);
    worker
        .execute(Action::Switch("中国移动".into()))
        .await
        .unwrap();
    assert_eq!(runtime.snapshot()["status"]["service"], "校园网");
    assert_eq!(runtime.store.load_config(false).unwrap().service, "校园网");
}

#[tokio::test]
async fn successful_switch_merges_concurrent_account_changes() {
    let (runtime, receiver) = fixture();
    let mut worker = Worker::new(runtime.clone(), receiver);
    worker.execute(Action::Login).await.unwrap();
    demo(&runtime).lock().unwrap().delay = Duration::from_millis(80);
    let changing = async {
        tokio::time::sleep(Duration::from_millis(20)).await;
        runtime
            .request(
                "save_config",
                json!({"username":"latest-account","password":"latest-secret"}),
            )
            .await
            .unwrap();
    };
    let (result, _) = tokio::join!(worker.execute(Action::Switch("中国移动".into())), changing);
    result.unwrap();
    let config = runtime.store.load_config(false).unwrap();
    assert_eq!(config.username, "latest-account");
    assert_eq!(config.password, "latest-secret");
    assert_eq!(config.service, "中国移动");
    assert_eq!(runtime.snapshot()["status"]["user"], "20260001");
}

#[tokio::test]
async fn restored_auto_preference_and_sequence_order_are_preserved() {
    let store = Store::open(None, true).unwrap();
    store
        .update_prefs(json!({"auto_reconnect":true}).as_object().unwrap().clone())
        .unwrap();
    let events = Arc::new(Mutex::new(Vec::<u64>::new()));
    let sink = events.clone();
    let (runtime, receiver) = Runtime::new(
        store,
        Arc::new(move |v| sink.lock().unwrap().push(v["sequence"].as_u64().unwrap())),
    )
    .unwrap();
    runtime.launch(receiver);
    wait(&runtime, |s| {
        s["auto"]["state"] == "on" && s["status"]["online"] == true
    })
    .await;
    runtime
        .request("save_prefs", json!({"close_to_tray":false}))
        .await
        .unwrap();
    runtime.shutdown().await;
    let events = events.lock().unwrap();
    assert!(events.windows(2).all(|v| v[0] < v[1]));
}

#[tokio::test]
async fn force_stop_drops_inflight_authentication_and_lifetime_lock() {
    let (runtime, receiver) = fixture();
    demo(&runtime).lock().unwrap().delay = Duration::from_secs(180);
    runtime.launch(receiver);
    action(&runtime, "login").await;
    wait(&runtime, |_| demo(&runtime).lock().unwrap().in_flight == 1).await;
    runtime.force_stop();
    wait(&runtime, |_| demo(&runtime).lock().unwrap().cancelled == 1).await;
    assert!(runtime.store.acquire_run().is_ok());
}

#[tokio::test]
async fn a_contended_write_does_not_block_snapshots_or_cancellation() {
    use fs2::FileExt;
    let (runtime, receiver) = fixture();
    runtime.launch(receiver);
    let path = runtime.store.path.with_file_name("config.json.write.lock");
    let lock = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(path)
        .unwrap();
    FileExt::lock_exclusive(&lock).unwrap();
    let updating = runtime.clone();
    let request = tokio::spawn(async move {
        updating
            .request("save_config", json!({"service":"中国移动"}))
            .await
    });
    tokio::time::sleep(Duration::from_millis(30)).await;
    tokio::time::timeout(
        Duration::from_millis(100),
        runtime.request("snapshot", json!({})),
    )
    .await
    .unwrap()
    .unwrap();
    runtime.shutdown().await;
    assert!(tokio::time::timeout(Duration::from_secs(1), request)
        .await
        .unwrap()
        .unwrap()
        .is_err());
    drop(lock);
}

#[tokio::test]
async fn schema_enums_survive_passwords_matching_structural_words() {
    let (runtime, _) = fixture();
    runtime
        .request("save_config", json!({"password":"rust"}))
        .await
        .unwrap();
    runtime
        .request("save_config", json!({"password":"api"}))
        .await
        .unwrap();
    let snapshot = runtime.snapshot();
    assert_eq!(snapshot["environment"]["runtime"], "rust");
    assert_eq!(snapshot["config"]["backend"], "api");
    assert_eq!(snapshot["logs"][0]["level"], "success");
}

#[tokio::test]
async fn configuration_changed_during_status_is_rechecked_before_auto_login() {
    let (runtime, receiver) = fixture();
    runtime.desired.store(true, Ordering::Release);
    demo(&runtime).lock().unwrap().status_delay = Duration::from_millis(100);
    let mut worker = Worker::new(runtime.clone(), receiver);
    worker.guard = Some(runtime.store.acquire_run().unwrap());
    let changing = async {
        wait(&runtime, |_| {
            demo(&runtime).lock().unwrap().status_calls > 0
        })
        .await;
        runtime
            .request("save_config", json!({"username":"fresh-account"}))
            .await
            .unwrap();
    };
    tokio::join!(worker.tick(), changing);
    assert_eq!(demo(&runtime).lock().unwrap().logins, 0);
    worker.tick().await;
    assert_eq!(demo(&runtime).lock().unwrap().logins, 1);
    assert_eq!(runtime.snapshot()["status"]["user"], "fresh-account");
}

#[tokio::test]
async fn logout_while_manual_login_is_busy_preserves_the_stop_intent() {
    let (runtime, receiver) = fixture();
    demo(&runtime).lock().unwrap().delay = Duration::from_millis(100);
    runtime.launch(receiver);
    action(&runtime, "login").await;
    wait(&runtime, |_| demo(&runtime).lock().unwrap().in_flight == 1).await;
    runtime
        .request("action", json!({"name":"set_auto","value":true}))
        .await
        .unwrap();
    action(&runtime, "logout").await;
    assert!(!runtime.store.load_prefs().auto_reconnect);
    assert!(!runtime.desired.load(Ordering::Acquire));
    assert_eq!(runtime.snapshot()["auto"]["state"], "off");
    wait(&runtime, |s| {
        s["status"]["online"] == false && s["busy"] == false
    })
    .await;
    assert_eq!(demo(&runtime).lock().unwrap().logins, 1);
    runtime.shutdown().await;
}

#[tokio::test]
async fn broken_configuration_is_unknown_and_account_reads_do_not_change_status() {
    let (runtime, receiver) = fixture();
    let mut worker = Worker::new(runtime.clone(), receiver);
    worker.execute(Action::Login).await.unwrap();
    std::fs::write(&runtime.store.path, b"invalid fixture").unwrap();
    worker.execute(Action::Info).await.unwrap();
    assert!(runtime.snapshot()["info"].is_null());
    assert_eq!(runtime.snapshot()["status"]["online"], true);
    worker.execute(Action::Status).await.unwrap();
    assert!(runtime.snapshot()["status"]["online"].is_null());
    assert_eq!(demo(&runtime).lock().unwrap().logins, 1);
}

#[tokio::test]
async fn concurrent_auto_requests_keep_memory_and_persisted_intent_consistent() {
    let (runtime, _) = fixture();
    for _ in 0..10 {
        let (first, second) = tokio::join!(
            runtime.request("action", json!({"name":"set_auto","value":true})),
            runtime.request("action", json!({"name":"set_auto","value":false}))
        );
        first.unwrap();
        second.unwrap();
        let desired = runtime.desired.load(Ordering::Acquire);
        assert_eq!(runtime.snapshot()["prefs"]["auto_reconnect"], desired);
        assert_eq!(runtime.store.load_prefs().auto_reconnect, desired);
    }
}

#[tokio::test]
async fn accent_snapshots_round_trip_preserve_authentication_and_auto_intent() {
    let events = Arc::new(Mutex::new(Vec::new()));
    let captured = events.clone();
    let store = Store::open(None, true).unwrap();
    let config_before = std::fs::read(&store.path).unwrap();
    let (runtime, _) = Runtime::new(
        store.clone(),
        Arc::new(move |value| {
            captured.lock().unwrap().push(value);
        }),
    )
    .unwrap();
    assert_eq!(runtime.snapshot()["prefs"]["accent"], "teal");
    for accent in ["teal", "blue", "indigo", "violet", "rose", "amber"] {
        let before = runtime.snapshot();
        let saved = runtime
            .request("save_prefs", json!({"accent":accent}))
            .await
            .unwrap();
        assert_eq!(saved["prefs"]["accent"], accent);
        assert_eq!(
            runtime.persisted_prefs_for_smoke().await.unwrap(),
            saved["prefs"]
        );
        assert_eq!(
            events.lock().unwrap().last().unwrap()["prefs"],
            saved["prefs"]
        );
        let (reopened, _) = Runtime::new(store.clone(), Arc::new(|_| {})).unwrap();
        assert_eq!(reopened.snapshot()["prefs"], saved["prefs"]);
        for key in ["config", "accounts", "status", "auto", "busy", "info"] {
            assert_eq!(saved[key], before[key]);
        }
        assert!(!runtime.desired.load(Ordering::Acquire));
    }
    runtime
        .request("action", json!({"name":"set_auto","value":true}))
        .await
        .unwrap();
    assert_eq!(runtime.snapshot()["prefs"]["accent"], "amber");
    runtime
        .request("save_prefs", json!({"accent":"indigo","theme":"dark"}))
        .await
        .unwrap();
    assert!(runtime.desired.load(Ordering::Acquire));
    assert!(runtime.store.load_prefs().auto_reconnect);
    runtime
        .request("action", json!({"name":"set_auto","value":false}))
        .await
        .unwrap();
    assert_eq!(runtime.store.load_prefs().accent, "indigo");
    assert_eq!(runtime.snapshot()["prefs"]["theme"], "dark");
    assert_eq!(demo(&runtime).lock().unwrap().logins, 0);
    assert_eq!(std::fs::read(&store.path).unwrap(), config_before);
}

#[tokio::test]
async fn invalid_accent_requests_leave_disk_snapshot_and_publication_unchanged() {
    let (runtime, _) = fixture();
    let path = runtime.store.path.with_file_name("gui.json");
    assert!(runtime
        .request("save_prefs", json!({"accent":null}))
        .await
        .is_err());
    assert!(!path.exists());
    runtime
        .request("save_prefs", json!({"accent":"violet"}))
        .await
        .unwrap();
    let before = runtime.snapshot();
    let bytes = std::fs::read(&path).unwrap();
    for accent in [
        json!("future-accent"),
        json!("TEAL"),
        json!("teal "),
        json!(""),
        json!(null),
        json!(false),
        json!(1),
        json!([]),
        json!({}),
    ] {
        assert!(runtime
            .request("save_prefs", json!({"accent":accent,"theme":"light"}))
            .await
            .is_err());
        assert_eq!(runtime.snapshot(), before);
        assert_eq!(std::fs::read(&path).unwrap(), bytes);
    }
}

#[tokio::test]
async fn failed_auto_preference_save_does_not_start_authentication() {
    let (runtime, receiver) = fixture();
    std::fs::create_dir(runtime.store.path.with_file_name("gui.json")).unwrap();
    runtime.launch(receiver);
    assert!(runtime
        .request("action", json!({"name":"set_auto","value":true}))
        .await
        .is_err());
    assert!(!runtime.desired.load(Ordering::Acquire));
    assert_eq!(runtime.snapshot()["prefs"]["auto_reconnect"], false);
    assert_eq!(demo(&runtime).lock().unwrap().logins, 0);
    runtime.shutdown().await;
}
