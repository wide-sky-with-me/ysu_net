//! Offline fixtures only. These tests never reach a campus portal or private info endpoint.
use super::*;

fn fixture() -> (Arc<Runtime>, mpsc::Receiver<Action>) {
    Runtime::new(Store::open(None, true).unwrap(), Arc::new(|_| {})).unwrap()
}

fn demo(runtime: &Runtime) -> Arc<Mutex<Demo>> {
    match &runtime.backend {
        Backend::Demo(demo) => demo.clone(),
        _ => panic!("observer fixture must be isolated"),
    }
}

async fn wait(runtime: &Runtime, predicate: impl Fn(&Value) -> bool) {
    tokio::time::timeout(Duration::from_secs(5), async {
        loop {
            if predicate(&runtime.snapshot()) {
                break;
            }
            tokio::time::sleep(Duration::from_millis(5)).await;
        }
    })
    .await
    .expect("observer fixture did not settle");
}

fn assert_passive(runtime: &Runtime) {
    let demo = demo(runtime);
    let demo = demo.lock().unwrap();
    assert_eq!(
        demo.info_calls, 0,
        "passive work must not read private info"
    );
    assert_eq!(demo.logins, 0, "passive work must never authenticate");
    assert_eq!(demo.logouts, 0, "passive work must never mutate a session");
}

// A broken past-deadline loop must not starve this test's timeout/stop executor.
// Run the real worker on a separate thread, so even a spinning old implementation
// can be stopped and its admission-attempt count asserted without hanging CI.
fn run_worker_thread(
    mut worker: Worker,
) -> (
    std::thread::JoinHandle<()>,
    std::sync::mpsc::Receiver<Worker>,
) {
    let (sent, returned) = std::sync::mpsc::channel();
    let thread = std::thread::spawn(move || {
        {
            let executor = tokio::runtime::Builder::new_current_thread()
                .enable_time()
                .build()
                .unwrap();
            executor.block_on(worker.run_loop());
        }
        let _ = sent.send(worker);
    });
    (thread, returned)
}

async fn finish_worker_thread(
    runtime: &Runtime,
    thread: std::thread::JoinHandle<()>,
    returned: std::sync::mpsc::Receiver<Worker>,
) -> Worker {
    runtime.stop.send_replace(true);
    let worker = tokio::task::spawn_blocking(move || returned.recv_timeout(Duration::from_secs(2)))
        .await
        .unwrap()
        .expect("worker did not stop while waiting for its observation gate");
    thread.join().unwrap();
    worker
}

fn online() -> Status {
    Status {
        online: true,
        service: Some("校园网".into()),
        user: "external-fixture-user".into(),
        ip: "192.0.2.10".into(),
        message: "untrusted portal text".into(),
    }
}

#[test]
fn periodic_timer_runs_auto_off_and_near_due_auto_samples_are_reused() {
    let now = Instant::now();
    let mut observation = Observation::new(now);
    let due = now + OBSERVE_INTERVAL;
    assert_eq!(observation.deadline(false, now), due);
    assert_eq!(observation.deadline(true, due), due + OBSERVE_BUDGET);
    assert_eq!(
        observation.deadline(true, due + Duration::from_secs(90)),
        due,
        "long reconnect backoff must not suspend independent observation"
    );
    observation.sampled(now + Duration::from_secs(15), true);
    assert_eq!(
        observation.deadline(false, now),
        now + Duration::from_secs(45),
        "a manual/auto status sample satisfies the next periodic observation"
    );
    observation.request();
    assert_eq!(
        observation.deadline(false, now),
        now + Duration::from_secs(17)
    );
    observation.request();
    assert_eq!(
        observation.deadline(false, now),
        now + Duration::from_secs(17),
        "repeated focus/online triggers coalesce behind the short cooldown"
    );
    assert_eq!(
        observation.deadline(true, now + Duration::from_secs(17)),
        now + Duration::from_secs(19),
        "an explicit trigger also reuses a near-due automatic sample"
    );
    observation.sample_started();
    observation.sampled(now + Duration::from_secs(17), true);
    assert_eq!(
        observation.deadline(false, now),
        now + Duration::from_secs(47),
        "a sample starting after the trigger satisfies the request"
    );
}

#[test]
fn observer_failure_backoff_and_log_limit_are_independent_of_reconnect() {
    let now = Instant::now();
    let mut observation = Observation::new(now);
    for seconds in [60, 120, 240, 300, 300] {
        observation.sample_started();
        observation.sampled(now, false);
        let due = now + Duration::from_secs(seconds);
        assert_eq!(observation.deadline(false, now), due);
        let failures = observation.failures;
        for _ in 0..100 {
            observation.request();
            assert_eq!(
                observation.deadline(false, now),
                now + OBSERVE_INTERVAL,
                "advisory requests use healthy cadence, not the longer background backoff"
            );
            assert!(observation.deadline(false, now) > now + Duration::from_secs(29));
            assert_eq!(
                observation.failures, failures,
                "requests must not reset failures"
            );
        }
    }
    assert!(observation.log_error(now));
    assert!(!observation.log_error(now + Duration::from_secs(59)));
    assert!(observation.log_error(now + Duration::from_secs(60)));
    observation.sampled(now, true);
    assert_eq!(observation.failures, 0);
    assert_eq!(observation.deadline(false, now), now + OBSERVE_BUDGET);
}

#[test]
fn failed_advisory_storm_samples_at_most_once_per_healthy_interval() {
    let now = Instant::now();
    let mut observation = Observation::new(now);
    observation.sampled(now, false);
    assert_eq!(
        observation.deadline(false, now),
        now + Duration::from_secs(60)
    );
    let mut attempts = Vec::new();
    for seconds in 1..=95 {
        let event = now + Duration::from_secs(seconds);
        let failures = observation.failures;
        for _ in 0..100 {
            observation.request();
        }
        assert_eq!(observation.failures, failures);
        if observation.deadline(false, now) <= event {
            observation.sample_started();
            observation.sampled(event, false);
            attempts.push(seconds);
        }
    }
    assert_eq!(attempts, vec![30, 60, 90]);
    assert_eq!(observation.failures, 4);
    assert_eq!(observation.request_after, now + Duration::from_secs(120));
    assert_eq!(observation.next_periodic, now + Duration::from_secs(390));
    observation.sample_started();
    assert_eq!(
        observation.deadline(false, now),
        now + Duration::from_secs(390),
        "without a pending advisory request the background exponential deadline still wins"
    );
}

#[tokio::test]
async fn real_worker_gate_denial_is_bounded_and_recovers_after_release() {
    let (runtime, receiver) = fixture();
    let before = runtime.snapshot();
    let held = runtime.begin_auth().unwrap();
    let worker = Worker::new(runtime.clone(), receiver);
    let reconnect_due = worker.next_check;
    let deferrals = {
        let mut observation = worker.observation.lock().unwrap();
        observation.next_periodic = Instant::now();
        observation.gate_deferrals.clone()
    };
    let started = Instant::now();
    let (thread, returned) = run_worker_thread(worker);
    wait(&runtime, |_| deferrals.load(Ordering::Acquire) > 0).await;
    for _ in 0..100 {
        runtime.request("observe", json!({})).await.unwrap();
    }
    tokio::time::sleep(Duration::from_millis(50)).await;
    let held_snapshot = runtime.snapshot();
    let held_calls = demo(&runtime).lock().unwrap().status_calls;
    let held_deferrals = deferrals.load(Ordering::Acquire);
    let maximum = 2 + started.elapsed().as_nanos() / OBSERVE_BUDGET.as_nanos();
    drop(held);
    wait(&runtime, |snapshot| {
        snapshot["status"]["online"] == false && !runtime.auth_gate.lock().unwrap().active
    })
    .await;
    let worker = finish_worker_thread(&runtime, thread, returned).await;
    assert_eq!(
        held_snapshot, before,
        "gate refusal must not publish business state"
    );
    assert_eq!(held_calls, 0);
    assert!(
        u128::from(held_deferrals) <= maximum,
        "past-due timer spun on a held gate"
    );
    assert_eq!(worker.next_check, reconnect_due);
    assert_eq!(demo(&runtime).lock().unwrap().status_calls, 1);
    assert_eq!(runtime.snapshot()["busy"], false);
    assert_eq!(runtime.snapshot()["logs"], before["logs"]);
    assert_passive(&runtime);
}

#[tokio::test]
async fn real_worker_stop_exits_while_observation_gate_remains_held() {
    let (runtime, receiver) = fixture();
    let before = runtime.snapshot();
    let held = runtime.begin_auth().unwrap();
    let worker = Worker::new(runtime.clone(), receiver);
    let reconnect_due = worker.next_check;
    let deferrals = {
        let mut observation = worker.observation.lock().unwrap();
        observation.next_periodic = Instant::now();
        observation.request();
        observation.gate_deferrals.clone()
    };
    let started = Instant::now();
    let (thread, returned) = run_worker_thread(worker);
    wait(&runtime, |_| deferrals.load(Ordering::Acquire) > 0).await;
    tokio::time::sleep(Duration::from_millis(50)).await;
    let maximum = 2 + started.elapsed().as_nanos() / OBSERVE_BUDGET.as_nanos();
    let worker = finish_worker_thread(&runtime, thread, returned).await;
    let attempts = deferrals.load(Ordering::Acquire);
    let gate_still_held = runtime.auth_gate.lock().unwrap().active;
    drop(held);
    assert!(
        u128::from(attempts) <= maximum,
        "held gate caused a busy retry loop"
    );
    assert!(
        gate_still_held,
        "stop must not release another operation's admission"
    );
    assert_eq!(worker.next_check, reconnect_due);
    assert_eq!(runtime.snapshot(), before);
    assert_eq!(demo(&runtime).lock().unwrap().status_calls, 0);
    assert_passive(&runtime);
}

#[tokio::test]
async fn auto_off_worker_timer_refreshes_without_a_frontend_request() {
    let (runtime, receiver) = fixture();
    let before = runtime.snapshot();
    {
        let demo = demo(&runtime);
        let mut demo = demo.lock().unwrap();
        demo.online = true;
        demo.user = "external-fixture-user".into();
        demo.service = Some("中国移动".into());
    }
    let mut worker = Worker::new(runtime.clone(), receiver);
    worker.observation.lock().unwrap().next_periodic = Instant::now();
    let task = tokio::spawn(async move { worker.run_loop().await });
    wait(&runtime, |snapshot| {
        snapshot["status"]["online"] == true && !runtime.auth_gate.lock().unwrap().active
    })
    .await;
    assert_eq!(demo(&runtime).lock().unwrap().status_calls, 1);
    assert_eq!(
        runtime.snapshot()["status"]["user"],
        "external-fixture-user"
    );
    for key in ["prefs", "config", "accounts", "auto", "logs", "busy"] {
        assert_eq!(runtime.snapshot()[key], before[key]);
    }
    runtime.stop.send_replace(true);
    tokio::time::timeout(Duration::from_secs(1), task)
        .await
        .unwrap()
        .unwrap();
    assert_passive(&runtime);
}

#[tokio::test]
async fn near_due_auto_check_satisfies_pending_observation_without_a_duplicate_query() {
    let (runtime, receiver) = fixture();
    let config = runtime.state.lock().unwrap().config.clone();
    {
        let demo = demo(&runtime);
        let mut demo = demo.lock().unwrap();
        demo.online = true;
        demo.user = config.username;
        demo.service = Some(config.service);
    }
    runtime.desired.store(true, Ordering::Release);
    let mut worker = Worker::new(runtime.clone(), receiver);
    worker.observation.lock().unwrap().request();
    let task = tokio::spawn(async move {
        worker.run_loop().await;
        worker
    });
    wait(&runtime, |snapshot| {
        snapshot["status"]["online"] == true
            && snapshot["busy"] == false
            && !runtime.auth_gate.lock().unwrap().active
    })
    .await;
    runtime.stop.send_replace(true);
    let worker = tokio::time::timeout(Duration::from_secs(1), task)
        .await
        .unwrap()
        .unwrap();
    assert!(!worker.observation.lock().unwrap().requested);
    assert_eq!(demo(&runtime).lock().unwrap().status_calls, 1);
    assert_eq!(runtime.snapshot()["logs"].as_array().unwrap().len(), 0);
    assert_passive(&runtime);
}

#[tokio::test]
async fn observe_contract_is_empty_and_does_not_consume_manual_queue_capacity() {
    let (runtime, receiver) = fixture();
    assert!(valid_request("observe", &json!({})));
    for args in [
        json!(null),
        json!([]),
        json!({"name":"login"}),
        json!({"force":true}),
    ] {
        assert!(!valid_request("observe", &args));
        assert!(runtime.request("observe", args).await.is_err());
    }
    assert!(!valid_request("action", &json!({"name":"observe"})));
    for _ in 0..QUEUE_SIZE {
        runtime.sender.try_send(Action::Status).unwrap();
    }
    let before = runtime.snapshot();
    for _ in 0..128 {
        assert_eq!(runtime.request("observe", json!({})).await.unwrap(), before);
    }
    assert_eq!(receiver.len(), QUEUE_SIZE);
    let worker = Worker::new(runtime.clone(), receiver);
    assert!(worker.observation.lock().unwrap().requested);
    assert_eq!(demo(&runtime).lock().unwrap().status_calls, 0);
    assert_passive(&runtime);
}

#[tokio::test]
async fn passive_auto_off_observation_is_silent_and_never_saves_external_identity() {
    let events = Arc::new(Mutex::new(Vec::new()));
    let captured = events.clone();
    let (runtime, receiver) = Runtime::new(
        Store::open(None, true).unwrap(),
        Arc::new(move |event| captured.lock().unwrap().push(event)),
    )
    .unwrap();
    let before = runtime.snapshot();
    let saved = std::fs::read(&runtime.store.path).unwrap();
    let prefs = serde_json::to_value(runtime.store.load_prefs()).unwrap();
    {
        let demo = demo(&runtime);
        let mut demo = demo.lock().unwrap();
        demo.online = true;
        demo.user = "external-fixture-user".into();
        demo.service = Some("中国移动".into());
    }
    let mut worker = Worker::new(runtime.clone(), receiver);
    let reconnect_due = worker.next_check;
    worker.reconnect.failures = 3;
    worker.reconnect.blocked = Some("fixture paused identity".into());
    for _ in 0..3 {
        worker.observe().await;
    }
    let after = runtime.snapshot();
    assert_eq!(after["status"]["online"], true);
    assert_eq!(after["status"]["user"], "external-fixture-user");
    assert_eq!(after["status"]["service"], "中国移动");
    assert_eq!(after["status"]["message"], "校园网已连接");
    assert_eq!(after["logs"], before["logs"]);
    for key in [
        "config",
        "prefs",
        "accounts",
        "auto",
        "busy",
        "busy_message",
    ] {
        assert_eq!(after[key], before[key], "passive work changed {key}");
    }
    assert!(events
        .lock()
        .unwrap()
        .iter()
        .all(|event| event["busy"] == false));
    assert_eq!(std::fs::read(&runtime.store.path).unwrap(), saved);
    assert_eq!(
        serde_json::to_value(runtime.store.load_prefs()).unwrap(),
        prefs
    );
    assert!(!runtime.desired.load(Ordering::Acquire));
    assert_eq!(runtime.auto_version.load(Ordering::Acquire), 0);
    assert_eq!(runtime.rotation_version.load(Ordering::Acquire), 0);
    assert_eq!(worker.next_check, reconnect_due);
    assert_eq!(worker.reconnect.failures, 3);
    assert_eq!(
        worker.reconnect.blocked.as_deref(),
        Some("fixture paused identity")
    );
    assert_passive(&runtime);
}

#[tokio::test]
async fn passive_browser_setting_uses_api_copy_without_changing_manual_or_auto_backend() {
    let (runtime, receiver) = fixture();
    runtime
        .request("save_config", json!({"backend":"browser"}))
        .await
        .unwrap();
    let before = runtime.snapshot();
    let saved = std::fs::read(&runtime.store.path).unwrap();
    let mut worker = Worker::new(runtime.clone(), receiver);
    worker.observe().await;
    assert_eq!(demo(&runtime).lock().unwrap().status_backends, vec!["api"]);
    assert_eq!(runtime.snapshot()["busy"], false);
    assert_eq!(runtime.snapshot()["logs"], before["logs"]);
    for key in ["config", "prefs", "accounts", "auto"] {
        assert_eq!(runtime.snapshot()[key], before[key]);
    }
    demo(&runtime).lock().unwrap().status_error = Some(2);
    worker.observe().await;
    assert!(runtime.snapshot()["status"]["online"].is_null());
    assert_eq!(runtime.snapshot()["busy"], false);
    assert_eq!(std::fs::read(&runtime.store.path).unwrap(), saved);
    assert_eq!(runtime.snapshot()["config"]["backend"], "browser");
    assert_eq!(
        demo(&runtime).lock().unwrap().status_backends,
        vec!["api", "api"]
    );
    assert_passive(&runtime);

    // Explicit/manual and automatic work retain the user's browser backend. The Demo
    // records the selected path without starting a real browser or touching the network.
    demo(&runtime).lock().unwrap().status_error = None;
    worker.execute(Action::Status).await.unwrap();
    worker.tick().await;
    assert_eq!(
        demo(&runtime).lock().unwrap().status_backends,
        vec!["api", "api", "browser", "browser"]
    );
    assert_eq!(std::fs::read(&runtime.store.path).unwrap(), saved);
    assert_eq!(runtime.snapshot()["config"]["backend"], "browser");
    assert_passive(&runtime);
}

#[tokio::test]
async fn actual_account_service_and_ip_changes_invalidate_info_and_old_read_errors() {
    let (runtime, receiver) = fixture();
    let worker = Worker::new(runtime.clone(), receiver);
    let saved = runtime.snapshot()["config"].clone();
    for field in ["user", "service", "ip"] {
        let original = online();
        worker.publish_status(&Ok(original.clone()), true);
        runtime.update(|state| {
            state.info = json!({"online":true,"fields":[["账号","old-user"]],"items":[]});
        });
        worker.publish_status(&Ok(original.clone()), true);
        assert_eq!(runtime.snapshot()["info"]["online"], true);
        let mut changed = original;
        match field {
            "user" => changed.user = "another-external-user".into(),
            "service" => changed.service = Some("中国联通".into()),
            "ip" => changed.ip = "192.0.2.11".into(),
            _ => unreachable!(),
        }
        worker.publish_status(&Ok(changed.clone()), true);
        assert!(
            runtime.snapshot()["info"].is_null(),
            "stale info survived {field}"
        );
        runtime.update(|state| state.info_error = "valid same-identity read failure".into());
        worker.publish_status(&Ok(changed), true);
        assert_eq!(
            runtime.snapshot()["info_error"],
            "valid same-identity read failure"
        );
        worker.publish_status(&Ok(online()), true);
        assert_eq!(
            runtime.snapshot()["info_error"],
            "",
            "old error survived {field}"
        );
        assert_eq!(runtime.snapshot()["config"], saved);
    }
    assert_passive(&runtime);
}

#[tokio::test]
async fn unknown_and_offline_invalidate_info_without_fabricating_offline_or_losing_identity() {
    let (runtime, receiver) = fixture();
    let worker = Worker::new(runtime.clone(), receiver);
    worker.publish_status(&Ok(online()), true);
    runtime.update(|state| {
        state.info = json!({"online":true,"fields":[],"items":[]});
    });
    let failure = local_auth_error(
        2,
        DiagnosticOperation::Status,
        DiagnosticStage::OnlineState,
        DiagnosticReason::Network,
    );
    worker.publish_status(&Err(failure.clone()), true);
    assert!(runtime.snapshot()["status"]["online"].is_null());
    assert!(runtime.snapshot()["info"].is_null());
    runtime.update(|state| state.info_error = "same-identity private read failure".into());
    worker.publish_status(&Err(failure), true);
    worker.publish_status(&Ok(online()), true);
    assert_eq!(
        runtime.snapshot()["info_error"],
        "same-identity private read failure"
    );
    let mut changed = online();
    changed.user = "different-external-user".into();
    worker.publish_status(&Ok(changed), true);
    assert_eq!(runtime.snapshot()["info_error"], "");
    runtime.update(|state| {
        state.info = json!({"online":true,"fields":[],"items":[]});
    });
    let mut offline = online();
    offline.online = false;
    worker.publish_status(&Ok(offline), true);
    assert_eq!(runtime.snapshot()["status"]["online"], false);
    assert_eq!(
        runtime.snapshot()["info"],
        json!({"online":false,"fields":[],"items":[]})
    );
    assert_eq!(runtime.snapshot()["info_error"], "");
    assert_passive(&runtime);
}

#[tokio::test]
async fn passive_failures_are_unknown_redacted_and_rate_limited() {
    let (runtime, receiver) = fixture();
    demo(&runtime).lock().unwrap().status_error = Some(2);
    let mut worker = Worker::new(runtime.clone(), receiver);
    for _ in 0..3 {
        worker.observe().await;
    }
    let after = runtime.snapshot();
    assert!(after["status"]["online"].is_null());
    assert!(after["info"].is_null());
    assert_eq!(after["busy"], false);
    assert_eq!(after["logs"].as_array().unwrap().len(), 1);
    assert!(after["status"]["message"]
        .as_str()
        .unwrap()
        .contains("action=observe"));
    for private in [
        "fixture query",
        "portal.invalid",
        "fixture-secret",
        "fixture-token",
    ] {
        assert!(!after.to_string().contains(private));
    }
    assert_eq!(worker.observation.lock().unwrap().failures, 3);
    assert_eq!(worker.reconnect.failures, 0);
    assert_passive(&runtime);
}

#[tokio::test]
async fn busy_focus_burst_coalesces_and_queued_manual_authentication_wins() {
    let (runtime, receiver) = fixture();
    demo(&runtime).lock().unwrap().status_delay = Duration::from_millis(100);
    runtime.launch(receiver);
    wait(&runtime, |_| {
        demo(&runtime).lock().unwrap().status_calls == 1
    })
    .await;
    for _ in 0..128 {
        runtime.request("observe", json!({})).await.unwrap();
    }
    runtime
        .request("action", json!({"name":"login"}))
        .await
        .unwrap();
    wait(&runtime, |_| {
        let demo = demo(&runtime);
        let demo = demo.lock().unwrap();
        demo.logins == 1 && demo.status_calls >= 2
    })
    .await;
    assert_eq!(demo(&runtime).lock().unwrap().status_calls, 2);
    wait(&runtime, |snapshot| {
        snapshot["busy"] == false && !runtime.auth_gate.lock().unwrap().active
    })
    .await;
    assert_eq!(demo(&runtime).lock().unwrap().status_calls, 2);
    // The queued login's verification satisfied the busy burst. A later burst requests
    // one new sample, without producing a second authentication or success message.
    for _ in 0..128 {
        runtime.request("observe", json!({})).await.unwrap();
    }
    wait(&runtime, |snapshot| {
        demo(&runtime).lock().unwrap().status_calls == 3
            && snapshot["busy"] == false
            && !runtime.auth_gate.lock().unwrap().active
    })
    .await;
    assert_eq!(demo(&runtime).lock().unwrap().info_calls, 0);
    assert_eq!(demo(&runtime).lock().unwrap().logins, 1);
    assert_eq!(runtime.snapshot()["logs"].as_array().unwrap().len(), 1);
    runtime.shutdown().await;
    assert_eq!(demo(&runtime).lock().unwrap().status_calls, 3);
}

#[tokio::test]
async fn triggers_during_a_busy_status_are_retained_without_auto_or_manual_work() {
    let (runtime, receiver) = fixture();
    demo(&runtime).lock().unwrap().status_delay = Duration::from_millis(100);
    runtime.launch(receiver);
    wait(&runtime, |_| {
        demo(&runtime).lock().unwrap().status_calls == 1
    })
    .await;
    for _ in 0..128 {
        runtime.request("observe", json!({})).await.unwrap();
    }
    wait(&runtime, |snapshot| {
        demo(&runtime).lock().unwrap().status_calls == 2
            && snapshot["busy"] == false
            && !runtime.auth_gate.lock().unwrap().active
    })
    .await;
    assert_eq!(runtime.snapshot()["logs"].as_array().unwrap().len(), 0);
    assert!(!runtime.desired.load(Ordering::Acquire));
    runtime.shutdown().await;
    assert_eq!(demo(&runtime).lock().unwrap().status_calls, 2);
    assert_passive(&runtime);
}

#[tokio::test]
async fn passive_network_budget_is_short_even_with_a_long_authentication_timeout() {
    let (runtime, receiver) = fixture();
    demo(&runtime).lock().unwrap().status_delay = Duration::from_secs(180);
    let mut worker = Worker::new(runtime.clone(), receiver);
    let started = Instant::now();
    tokio::time::timeout(Duration::from_millis(2500), worker.observe())
        .await
        .expect("passive work must not inherit the 180-second auth budget");
    assert!(started.elapsed() >= OBSERVE_BUDGET);
    assert_eq!(runtime.snapshot()["busy"], false);
    assert!(runtime.snapshot()["status"]["online"].is_null());
    assert!(runtime.snapshot()["status"]["message"]
        .as_str()
        .unwrap()
        .contains("reason=deadline"));
    assert!(!runtime.auth_gate.lock().unwrap().active);
    assert_passive(&runtime);
}

#[tokio::test]
async fn passive_gate_respects_update_admission_and_shutdown_cancels_inflight_status() {
    let (paused, receiver) = fixture();
    paused.request("observe", json!({})).await.unwrap();
    paused.pause_for_update().unwrap();
    assert!(paused.request("observe", json!({})).await.is_err());
    let mut worker = Worker::new(paused.clone(), receiver);
    worker.observe().await;
    assert_eq!(demo(&paused).lock().unwrap().status_calls, 0);
    assert_passive(&paused);

    let (runtime, receiver) = fixture();
    demo(&runtime).lock().unwrap().status_delay = Duration::from_secs(180);
    let before = runtime.snapshot();
    let mut worker = Worker::new(runtime.clone(), receiver);
    let task = tokio::spawn(async move { worker.observe().await });
    wait(&runtime, |_| {
        demo(&runtime).lock().unwrap().status_calls == 1
    })
    .await;
    assert_eq!(runtime.snapshot()["busy"], false);
    assert!(
        runtime.pause_for_update().is_err(),
        "the hidden read still owns the auth gate"
    );
    runtime.stop.send_replace(true);
    tokio::time::timeout(Duration::from_secs(1), task)
        .await
        .unwrap()
        .unwrap();
    assert!(!runtime.auth_gate.lock().unwrap().active);
    assert_eq!(
        runtime.snapshot(),
        before,
        "a cancelled read must not publish late state"
    );
    assert_passive(&runtime);
}
