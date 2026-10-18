//! Integration-review regressions; these use isolated state, not campus authentication.
use super::*;

#[test]
fn snapshot_publication_allows_read_only_reentrancy() {
    let reference = Arc::new(Mutex::new(std::sync::Weak::<Runtime>::new()));
    let sink_reference = reference.clone();
    let (sent, received) = std::sync::mpsc::channel();
    let (runtime, _) = Runtime::new(
        Store::open(None, true).unwrap(),
        Arc::new(move |event| {
            if let Some(runtime) = sink_reference.lock().unwrap().upgrade() {
                assert!(
                    runtime.snapshot()["sequence"].as_u64().unwrap()
                        >= event["sequence"].as_u64().unwrap()
                );
                sent.send(()).unwrap();
            }
        }),
    )
    .unwrap();
    *reference.lock().unwrap() = Arc::downgrade(&runtime);
    let updating = runtime.clone();
    let thread = std::thread::spawn(move || updating.update(|state| state.log("info", "fixture")));
    received
        .recv_timeout(Duration::from_secs(1))
        .expect("a snapshot callback must not retain the state lock");
    thread.join().unwrap();
}

#[test]
fn interaction_pause_survives_noncredential_setting_changes() {
    let config = Config::default();
    let mut reconnect = Reconnect {
        blocked: Some(Reconnect::identity(&config)),
        ..Reconnect::default()
    };
    let changes: [fn(&mut Config); 4] = [
        |config| config.check_interval += 1,
        |config| config.retry_interval += 1,
        |config| config.operation_timeout += 1,
        |config| config.verify_tls = !config.verify_tls,
    ];
    for change in changes {
        let mut candidate = config.clone();
        change(&mut candidate);
        assert!(
            reconnect.paused(&candidate),
            "timer or TLS changes must not retry the same rejected credentials"
        );
    }
    let mut changed = config.clone();
    changed.password = "new-fixture-password".into();
    assert!(!reconnect.paused(&changed));
}

#[tokio::test]
async fn credential_scrubbing_preserves_canonical_status_service() {
    let (runtime, receiver) =
        Runtime::new(Store::open(None, true).unwrap(), Arc::new(|_| {})).unwrap();
    runtime
        .request("save_config", json!({"password":"校园网"}))
        .await
        .unwrap();
    Worker::new(runtime.clone(), receiver)
        .execute(Action::Login)
        .await
        .unwrap();
    let snapshot = runtime.snapshot();
    assert_eq!(snapshot["status"]["service"], "校园网");
    assert_eq!(snapshot["config"]["service"], "校园网");
    assert!(snapshot["config"].get("password").is_none());
}

#[test]
fn reconnect_snapshot_uses_readable_wait_seconds() {
    let (runtime, receiver) =
        Runtime::new(Store::open(None, true).unwrap(), Arc::new(|_| {})).unwrap();
    runtime.desired.store(true, Ordering::Release);
    let mut worker = Worker::new(runtime.clone(), receiver);
    worker.schedule(30.123456789, "fixture");
    assert_eq!(runtime.snapshot()["auto"]["delay"], 31.0);
}

#[test]
fn tray_can_stop_busy_reconnect_but_cannot_start_it_or_take_external_control() {
    assert!(crate::auto_control_available(
        &json!({"busy":true,"auto":{"state":"on"}})
    ));
    assert!(!crate::auto_control_available(
        &json!({"busy":true,"auto":{"state":"off"}})
    ));
    assert!(!crate::auto_control_available(
        &json!({"busy":false,"auto":{"state":"external"}})
    ));
    assert!(crate::auto_control_available(
        &json!({"busy":false,"auto":{"state":"off"}})
    ));
}

#[test]
fn diagnostic_environment_is_the_frontend_rust_contract() {
    let value = environment(true);
    assert_eq!(value.as_object().unwrap().len(), 6);
    assert_eq!(value["runtime"], "rust");
    for key in ["rust", "version", "platform"] {
        assert!(value[key].is_string());
    }
    for key in ["browser_available", "browser_component_available"] {
        assert!(value[key].is_boolean());
    }
}

#[tokio::test]
async fn native_action_deadline_includes_post_mutation_verification() {
    let (runtime, receiver) =
        Runtime::new(Store::open(None, true).unwrap(), Arc::new(|_| {})).unwrap();
    runtime
        .request("save_config", json!({"operation_timeout":1}))
        .await
        .unwrap();
    if let Backend::Demo(demo) = &runtime.backend {
        let mut demo = demo.lock().unwrap();
        demo.delay = Duration::from_millis(900);
        demo.status_delay = Duration::from_millis(900);
    }
    let mut worker = Worker::new(runtime.clone(), receiver);
    tokio::time::timeout(Duration::from_millis(1500), worker.execute(Action::Login))
        .await
        .expect("mutation and independent verification must share a total deadline")
        .unwrap();
    assert!(runtime.snapshot()["status"]["online"].is_null());
    assert!(runtime.store.acquire_run().is_ok());
}

#[tokio::test]
async fn native_action_deadline_bounds_the_whole_reconnect_attempt() {
    let (runtime, receiver) =
        Runtime::new(Store::open(None, true).unwrap(), Arc::new(|_| {})).unwrap();
    runtime
        .request("save_config", json!({"operation_timeout":1}))
        .await
        .unwrap();
    runtime.desired.store(true, Ordering::Release);
    if let Backend::Demo(demo) = &runtime.backend {
        let mut demo = demo.lock().unwrap();
        demo.delay = Duration::from_millis(900);
        demo.status_delay = Duration::from_millis(900);
    }
    let mut worker = Worker::new(runtime.clone(), receiver);
    worker.guard = Some(runtime.store.acquire_run().unwrap());
    tokio::time::timeout(Duration::from_millis(1500), worker.tick())
        .await
        .expect("query, login and verification must share a total reconnect deadline");
    assert!(runtime.snapshot()["status"]["online"].is_null());
    assert!(runtime.snapshot()["auto"]["delay"].as_f64().unwrap() >= 30.0);
}
