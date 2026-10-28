use super::*;

fn fixture() -> (Arc<Runtime>, Worker, String) {
    let store = Store::open(None, true).unwrap();
    store.save_account(json!({"username":"fixture-b","password":"fixture-b-secret","label":"Backup","service":"中国移动","backend":"api","enabled":true})).unwrap();
    let id = store
        .load_accounts(&store.load_config(false).unwrap())
        .unwrap()
        .accounts[0]
        .id
        .clone();
    let (runtime, receiver) = Runtime::new(store, Arc::new(|_| {})).unwrap();
    let worker = Worker::new(runtime.clone(), receiver);
    (runtime, worker, id)
}
fn demo(runtime: &Runtime) -> Arc<Mutex<Demo>> {
    let Backend::Demo(demo) = &runtime.backend else {
        panic!("demo fixture")
    };
    demo.clone()
}
fn online(runtime: &Runtime) {
    let demo = demo(runtime);
    let mut state = demo.lock().unwrap();
    state.online = true;
    state.user = "20260001".into();
    state.service = Some("校园网".into());
}
async fn rotate_ready(runtime: &Runtime, worker: &mut Worker) {
    runtime.set_rotation(true).await.unwrap();
    worker.guard = Some(worker.acquire().await.unwrap());
    demo(runtime).lock().unwrap().quota =
        Some(json!({"state":"zero_reported","message":"门户报告剩余流量 0 MB"}));
}
fn age_zero(worker: &mut Worker) {
    worker.rotation.next_check = Instant::now();
    if let Some((_, when)) = &mut worker.rotation.zero {
        *when = Instant::now() - Duration::from_secs(60);
    }
}

#[tokio::test]
async fn hot_switch_verifies_identity_and_persists_only_after_login() {
    let (runtime, mut worker, id) = fixture();
    online(&runtime);
    worker
        .execute(Action::SwitchAccount(id.clone()))
        .await
        .unwrap();
    let snapshot = runtime.snapshot();
    assert_eq!(snapshot["status"]["user"], "fixture-b");
    assert_eq!(snapshot["status"]["service"], "中国移动");
    assert_eq!(snapshot["config"]["username"], "fixture-b");
    assert!(snapshot["accounts"]["items"]
        .as_array()
        .unwrap()
        .iter()
        .any(|account| account["id"] == id && account["current"] == true));
    assert!(!snapshot.to_string().contains("fixture-b-secret"));
    assert_eq!(demo(&runtime).lock().unwrap().logouts, 1);
}

async fn mobile_source_and_campus_target(runtime: &Runtime, id: &str) {
    runtime
        .save_config(json!({"service":"中国移动"}).as_object().unwrap().clone())
        .await
        .unwrap();
    runtime
        .request(
            "save_account",
            json!({"id":id,"username":"fixture-b","password":"",
        "label":"Backup","service":"校园网","backend":"api","enabled":true}),
        )
        .await
        .unwrap();
    online(runtime);
    demo(runtime).lock().unwrap().service = Some("中国移动".into());
}

fn state_event(requested: &str, owner: &str, service: Option<&str>) -> AccountEvent {
    AccountEvent::Status {
        requested: requested.into(),
        online: service.is_some(),
        owner: owner.into(),
        service: service.map(str::to_owned),
    }
}

fn mutation_event(action: &'static str, requested: &str, service: &str) -> AccountEvent {
    AccountEvent::Mutation {
        action,
        requested: requested.into(),
        service: service.into(),
    }
}

#[tokio::test]
async fn observed_pool_order_holds_config_until_independent_target_verification() {
    let (runtime, mut worker, id) = fixture();
    mobile_source_and_campus_target(&runtime, &id).await;
    let gate = Arc::new(tokio::sync::Notify::new());
    demo(&runtime).lock().unwrap().status_gate_at = Some((4, gate.clone()));
    let inspect = async {
        tokio::time::timeout(Duration::from_secs(5), async {
            while demo(&runtime).lock().unwrap().status_calls < 4 {
                tokio::task::yield_now().await;
            }
        })
        .await
        .expect("target verification reached its gate");
        assert_eq!(demo(&runtime).lock().unwrap().user, "fixture-b");
        let persisted = runtime.store.load_config(false).unwrap();
        assert_eq!(persisted.username, "20260001");
        assert_eq!(persisted.service, "中国移动");
        assert_eq!(runtime.snapshot()["config"]["username"], "20260001");
        gate.notify_one();
    };
    let (result, ()) = tokio::join!(worker.execute(Action::SwitchAccount(id)), inspect);
    result.unwrap();
    let persisted = runtime.store.load_config(false).unwrap();
    assert_eq!(persisted.username, "fixture-b");
    assert_eq!(persisted.service, "校园网");
    assert_eq!(
        demo(&runtime).lock().unwrap().account_events,
        vec![
            state_event("20260001", "20260001", Some("中国移动")),
            mutation_event("logout", "20260001", "中国移动"),
            state_event("20260001", "", None),
            state_event("fixture-b", "", None),
            mutation_event("login", "fixture-b", "校园网"),
            state_event("fixture-b", "fixture-b", Some("校园网")),
        ]
    );
}

#[tokio::test]
async fn target_verification_failure_keeps_old_config_and_restores_original_account() {
    let (runtime, mut worker, id) = fixture();
    mobile_source_and_campus_target(&runtime, &id).await;
    demo(&runtime).lock().unwrap().status_failure_at = Some((4, 2));
    assert!(worker.execute(Action::SwitchAccount(id)).await.is_err());
    let persisted = runtime.store.load_config(false).unwrap();
    assert_eq!(persisted.username, "20260001");
    assert_eq!(persisted.service, "中国移动");
    let state = demo(&runtime);
    let state = state.lock().unwrap();
    assert!(state.online);
    assert_eq!(state.user, "20260001");
    assert_eq!(state.service.as_deref(), Some("中国移动"));
    let mutations = state
        .account_events
        .iter()
        .filter(|event| matches!(event, AccountEvent::Mutation { .. }))
        .cloned()
        .collect::<Vec<_>>();
    assert_eq!(
        mutations,
        vec![
            mutation_event("logout", "20260001", "中国移动"),
            mutation_event("login", "fixture-b", "校园网"),
            mutation_event("logout", "fixture-b", "校园网"),
            mutation_event("login", "20260001", "中国移动"),
        ]
    );
}

#[tokio::test]
async fn account_switch_preserves_typed_portal_failure_after_successful_recovery() {
    let (runtime, mut worker, id) = fixture();
    online(&runtime);
    {
        let state = demo(&runtime);
        let mut state = state.lock().unwrap();
        state.login_failures.insert("fixture-b".into(), 2);
        state.login_diagnostics.insert(
            "fixture-b".into(),
            AuthDiagnostic {
                operation: DiagnosticOperation::Login,
                stage: DiagnosticStage::PortalNavigation,
                reason: DiagnosticReason::RedirectBlocked,
                ..AuthDiagnostic::default()
            },
        );
    }
    assert!(worker.execute(Action::SwitchAccount(id)).await.is_err());
    assert_eq!(
        runtime.store.load_config(false).unwrap().username,
        "20260001"
    );
    let snapshot = runtime.snapshot();
    assert!(snapshot["logs"].as_array().unwrap().iter().any(|entry| {
        let message = entry["message"].as_str().unwrap();
        message.contains("action=switch_account phase=user_online code=2 operation=login")
            && message.contains("stage=portal_navigation reason=redirect_blocked")
    }));
    assert!(!snapshot
        .to_string()
        .contains("fixture candidate login failure"));
    assert!(!snapshot.to_string().contains("fixture-b-secret"));
}

#[tokio::test]
async fn failed_target_restores_original_actual_service_and_keeps_config() {
    let (runtime, mut worker, id) = fixture();
    online(&runtime);
    demo(&runtime).lock().unwrap().service = Some("中国电信".into());
    demo(&runtime)
        .lock()
        .unwrap()
        .login_failures
        .insert("fixture-b".into(), 4);
    assert!(worker.execute(Action::SwitchAccount(id)).await.is_err());
    let snapshot = runtime.snapshot();
    assert_eq!(snapshot["status"]["user"], "20260001");
    assert_eq!(snapshot["status"]["service"], "中国电信");
    assert_eq!(snapshot["config"]["username"], "20260001");
    assert_eq!(snapshot["config"]["service"], "校园网");
    assert_eq!(demo(&runtime).lock().unwrap().logins, 2);
}

#[tokio::test]
async fn unknown_or_foreign_owner_is_never_logged_out() {
    for unknown in [false, true] {
        let (runtime, mut worker, id) = fixture();
        online(&runtime);
        if unknown {
            demo(&runtime).lock().unwrap().status_error = Some(2);
        } else {
            demo(&runtime).lock().unwrap().user = "foreign-fixture".into();
        }
        assert!(worker.execute(Action::SwitchAccount(id)).await.is_err());
        let demo = demo(&runtime);
        let state = demo.lock().unwrap();
        assert_eq!(state.logouts, 0);
        assert_eq!(state.logins, 0);
        assert_eq!(runtime.snapshot()["config"]["username"], "20260001");
    }
}

#[tokio::test]
async fn failed_switch_from_offline_does_not_login_original_account() {
    let (runtime, mut worker, id) = fixture();
    demo(&runtime)
        .lock()
        .unwrap()
        .login_failures
        .insert("fixture-b".into(), 4);
    assert!(worker.execute(Action::SwitchAccount(id)).await.is_err());
    let demo = demo(&runtime);
    let state = demo.lock().unwrap();
    assert!(!state.online);
    assert_eq!(state.logins, 1);
    assert_eq!(state.logouts, 0);
}

#[tokio::test]
async fn two_separated_zero_reports_switch_once_and_cool_original() {
    let (runtime, mut worker, _) = fixture();
    online(&runtime);
    rotate_ready(&runtime, &mut worker).await;
    let config = runtime.config().await.unwrap();
    let status = demo(&runtime).lock().unwrap().status();
    assert!(!worker.rotate_if_needed(&config, &status).await);
    assert_eq!(demo(&runtime).lock().unwrap().logouts, 0);
    assert!(!worker.rotate_if_needed(&config, &status).await);
    assert_eq!(demo(&runtime).lock().unwrap().logouts, 0);
    age_zero(&mut worker);
    assert!(worker.rotate_if_needed(&config, &status).await);
    assert_eq!(runtime.snapshot()["config"]["username"], "fixture-b");
    let selected = runtime.config().await.unwrap();
    let status = demo(&runtime).lock().unwrap().status();
    worker.rotation.next_check = Instant::now();
    assert!(!worker.rotate_if_needed(&selected, &status).await);
    age_zero(&mut worker);
    assert!(!worker.rotate_if_needed(&selected, &status).await);
    assert_eq!(demo(&runtime).lock().unwrap().logouts, 1);
    assert!(runtime.snapshot()["accounts"]["message"]
        .as_str()
        .unwrap()
        .contains("冷却"));
}

#[tokio::test]
async fn unknown_positive_and_unlimited_reset_zero_streak() {
    for state in ["unknown", "available", "unlimited"] {
        let (runtime, mut worker, _) = fixture();
        online(&runtime);
        rotate_ready(&runtime, &mut worker).await;
        let config = runtime.config().await.unwrap();
        let status = demo(&runtime).lock().unwrap().status();
        worker.rotate_if_needed(&config, &status).await;
        age_zero(&mut worker);
        demo(&runtime).lock().unwrap().quota =
            Some(json!({"state":state,"message":"fixture quota"}));
        assert!(!worker.rotate_if_needed(&config, &status).await);
        assert!(worker.rotation.zero.is_none());
        assert_eq!(demo(&runtime).lock().unwrap().logouts, 0);
    }
}

#[tokio::test]
async fn quota_query_failure_and_identity_mismatch_do_not_rotate() {
    let (runtime, mut worker, _) = fixture();
    online(&runtime);
    rotate_ready(&runtime, &mut worker).await;
    let config = runtime.config().await.unwrap();
    let status = demo(&runtime).lock().unwrap().status();
    worker.rotate_if_needed(&config, &status).await;
    age_zero(&mut worker);
    demo(&runtime).lock().unwrap().info_error = true;
    assert!(!worker.rotate_if_needed(&config, &status).await);
    assert!(worker.rotation.zero.is_none());
    demo(&runtime).lock().unwrap().info_error = false;
    demo(&runtime).lock().unwrap().user = "foreign-fixture".into();
    worker.rotation.next_check = Instant::now();
    assert!(!worker.rotate_if_needed(&config, &status).await);
    assert_eq!(demo(&runtime).lock().unwrap().logouts, 0);
}

#[tokio::test]
async fn candidate_failure_cools_and_does_not_loop_back_to_same_credentials() {
    let (runtime, mut worker, _) = fixture();
    online(&runtime);
    rotate_ready(&runtime, &mut worker).await;
    demo(&runtime)
        .lock()
        .unwrap()
        .login_failures
        .insert("fixture-b".into(), 4);
    let config = runtime.config().await.unwrap();
    let status = demo(&runtime).lock().unwrap().status();
    worker.rotate_if_needed(&config, &status).await;
    age_zero(&mut worker);
    assert!(worker.rotate_if_needed(&config, &status).await);
    assert_eq!(runtime.snapshot()["config"]["username"], "20260001");
    let logins = demo(&runtime).lock().unwrap().logins;
    age_zero(&mut worker);
    assert!(!worker.rotate_if_needed(&config, &status).await);
    assert_eq!(demo(&runtime).lock().unwrap().logins, logins);
}

#[tokio::test]
async fn disabled_rotation_or_auto_never_consumes_old_zero_observation() {
    let (runtime, mut worker, _) = fixture();
    online(&runtime);
    rotate_ready(&runtime, &mut worker).await;
    let config = runtime.config().await.unwrap();
    let status = demo(&runtime).lock().unwrap().status();
    worker.rotate_if_needed(&config, &status).await;
    age_zero(&mut worker);
    runtime.set_rotation(false).await.unwrap();
    runtime.set_rotation(true).await.unwrap();
    assert!(!worker.rotate_if_needed(&config, &status).await);
    assert_eq!(demo(&runtime).lock().unwrap().logouts, 0);
    runtime.set_desired(false).await.unwrap();
    age_zero(&mut worker);
    assert!(!worker.rotate_if_needed(&config, &status).await);
    assert_eq!(demo(&runtime).lock().unwrap().logouts, 0);
}

#[tokio::test]
async fn total_switch_deadline_covers_logout_login_and_independent_queries() {
    let (runtime, mut worker, id) = fixture();
    online(&runtime);
    runtime
        .save_config(json!({"operation_timeout":1}).as_object().unwrap().clone())
        .await
        .unwrap();
    demo(&runtime).lock().unwrap().delay = Duration::from_millis(600);
    worker.execute(Action::SwitchAccount(id)).await.unwrap();
    assert_eq!(runtime.snapshot()["status"]["online"], Value::Null);
    assert_eq!(runtime.snapshot()["config"]["username"], "20260001");
    assert_eq!(demo(&runtime).lock().unwrap().cancelled, 1);
    assert!(runtime.snapshot()["logs"]
        .as_array()
        .unwrap()
        .iter()
        .any(|entry| {
            entry["message"]
                .as_str()
                .unwrap()
                .contains("phase=user_online")
                && entry["message"]
                    .as_str()
                    .unwrap()
                    .contains("reason=deadline")
        }));
}

#[test]
fn new_requests_are_strict_and_do_not_accept_arbitrary_paths() {
    assert!(valid_request("rotation", &json!({"enabled":false})));
    assert!(!valid_request("rotation", &json!({"enabled":0})));
    assert!(valid_request(
        "action",
        &json!({"name":"switch_account","value":"current"})
    ));
    assert!(!valid_request(
        "action",
        &json!({"name":"switch_account","value":"../fixture"})
    ));
    assert!(!valid_request(
        "delete_account",
        &json!({"id":"current","password":"fixture"})
    ));
}

#[tokio::test]
async fn source_changed_before_preparation_does_not_rebase_old_quota_evidence() {
    let (runtime, mut worker, id) = fixture();
    let expected = runtime.config().await.unwrap();
    runtime
        .save_config(
            json!({"username":"fixture-c","password":"fixture-c-secret"})
                .as_object()
                .unwrap()
                .clone(),
        )
        .await
        .unwrap();
    {
        let demo = demo(&runtime);
        let mut state = demo.lock().unwrap();
        state.online = true;
        state.user = "fixture-c".into();
        state.service = Some("校园网".into());
    }
    let before = std::fs::read(runtime.store.path.with_extension("accounts.json")).unwrap();
    assert!(worker
        .switch_account_bound(&id, true, Some(expected))
        .await
        .is_err());
    assert_eq!(
        std::fs::read(runtime.store.path.with_extension("accounts.json")).unwrap(),
        before
    );
    assert_eq!(
        runtime.store.load_config(false).unwrap().username,
        "fixture-c"
    );
    assert_eq!(demo(&runtime).lock().unwrap().logouts, 0);
    assert_eq!(demo(&runtime).lock().unwrap().logins, 0);
}

#[tokio::test]
async fn public_identity_remains_round_trippable_when_passwords_equal_usernames() {
    let (runtime, _worker, id) = fixture();
    runtime.request("save_account",json!({"id":id,"username":"fixture-b","password":"fixture-b","label":"Backup","service":"中国移动","backend":"api","enabled":true})).await.unwrap();
    runtime
        .request("save_config", json!({"password":"20260001"}))
        .await
        .unwrap();
    let snapshot = runtime.snapshot();
    let items = snapshot["accounts"]["items"].as_array().unwrap();
    assert!(items.iter().any(|item| item["username"] == "20260001"));
    assert!(items.iter().any(|item| item["username"] == "fixture-b"));
    assert!(items.iter().all(|item| item.get("password").is_none()));
    assert_eq!(snapshot["config"]["username"], "20260001");
}

#[tokio::test]
async fn candidate_changed_before_recovery_does_not_trigger_old_password_restore() {
    let (runtime, worker, id) = fixture();
    online(&runtime);
    let plan = runtime.store.prepare_account(&id).unwrap();
    let original = demo(&runtime).lock().unwrap().status();
    demo(&runtime).lock().unwrap().online = false;
    runtime.request("save_account",json!({"id":id,"username":"fixture-b","password":"new-fixture-only","label":"Backup","service":"中国移动","backend":"api","enabled":true})).await.unwrap();
    assert!(!worker.restore_account(&plan, &original).await);
    assert_eq!(demo(&runtime).lock().unwrap().logins, 0);
}
