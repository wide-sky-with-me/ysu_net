use super::*;
use serde_json::{json, Value};
use std::sync::Mutex as StdMutex;
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::TcpListener,
    task::JoinHandle,
};

fn raw(content: impl Into<Value>) -> Value {
    json!({"accountInfo":[{"title":"剩余流量","content":content.into()}]})
}

#[test]
fn shared_raw_quota_fixtures_full_contract() {
    let fixture: Value = serde_json::from_str(include_str!(
        "../../../../tests/fixtures/account-quota.json"
    ))
    .unwrap();
    assert_eq!(fixture["version"], 1);
    let cases = fixture["cases"].as_array().unwrap();
    assert!(cases.len() >= 25);
    let mut ids = std::collections::BTreeSet::new();
    for case in cases {
        assert!(ids.insert(case["id"].as_str().unwrap()));
        assert_eq!(
            serde_json::to_value(classify_quota(&case["raw"])).unwrap(),
            case["expected"],
            "fixture {}",
            case["id"]
        );
        if case["expected"]["state"] == "unlimited" {
            assert_eq!(case["synthetic_rule"], true);
        }
    }
}

#[test]
fn quota_limits_fail_closed_without_truncation_or_underflow() {
    let mut payload = raw("0 MB");
    let items = payload["accountInfo"].as_array_mut().unwrap();
    items.extend((0..255).map(|_| json!({"title":"在线设备","content":"1 台"})));
    assert_eq!(classify_quota(&payload).state, QuotaState::ZeroReported);
    payload["accountInfo"]
        .as_array_mut()
        .unwrap()
        .push(json!({"title":"在线设备"}));
    assert_eq!(classify_quota(&payload).state, QuotaState::Unknown);
    let mut payload = raw("0 MB");
    for _ in 0..5 {
        payload = json!({"data":payload});
    }
    assert_eq!(classify_quota(&payload).state, QuotaState::ZeroReported);
    assert_eq!(
        classify_quota(&json!({"data":payload})).state,
        QuotaState::Unknown
    );
    assert_eq!(
        classify_quota(&json!({"accountInfo":raw("0 MB")["accountInfo"],"data":1})).state,
        QuotaState::Unknown
    );
    assert_eq!(
        classify_quota(&raw(format!("{} MB", "0".repeat(128)))).state,
        QuotaState::ZeroReported
    );
    assert_eq!(
        classify_quota(&raw(format!("{} MB", "0".repeat(129)))).state,
        QuotaState::Unknown
    );
    assert_eq!(
        classify_quota(&raw(format!("0.{}1 GB", "0".repeat(126)))).state,
        QuotaState::Available
    );
    assert_eq!(
        classify_quota(&raw(format!("0.{}1 GB", "0".repeat(127)))).state,
        QuotaState::Unknown
    );
    let prefix = "0 MB<script>";
    let suffix = "</script>";
    let content = format!(
        "{prefix}{}{suffix}",
        "x".repeat(4096 - prefix.len() - suffix.len())
    );
    assert_eq!(
        classify_quota(&raw(content.clone())).state,
        QuotaState::ZeroReported
    );
    assert_eq!(
        classify_quota(&raw(content + " ")).state,
        QuotaState::Unknown
    );
    assert_eq!(classify_quota(&json!({"accountInfo":[{"title":format!("<b>{}</b>","剩".repeat(1366)),"content":"0 MB"}]})).state,
        QuotaState::Unknown);
}

#[test]
fn quota_status_types_floats_and_hidden_fragments_fail_closed() {
    for code in [
        json!(true),
        json!(false),
        json!(0.0),
        json!("200"),
        Value::Null,
    ] {
        let mut payload = raw("0 MB");
        payload["code"] = code;
        assert_eq!(classify_quota(&payload).state, QuotaState::Unknown);
    }
    for value in [json!(0.0), json!(-0.0), json!(1.0), Value::Null] {
        assert_eq!(
            classify_quota(&json!({"accountInfo":[{"title":"剩余流量(MB)","content":value}]}))
                .state,
            QuotaState::Unknown
        );
    }
    for key in ["result", "success", "online"] {
        let mut payload = raw("0 MB");
        payload[key] = Value::Null;
        assert_eq!(classify_quota(&payload).state, QuotaState::Unknown);
    }
    for tag in ["script", "style", "noscript"] {
        let upper = tag.to_ascii_uppercase();
        assert_eq!(
            classify_quota(&raw(format!("0 MB<{upper}>1 GB</{upper}>"))).state,
            QuotaState::ZeroReported
        );
        assert_eq!(
            classify_quota(&raw(format!("0 MB<{tag}>1 GB"))).state,
            QuotaState::Unknown
        );
        assert_eq!(
            classify_quota(&raw(format!("0 MB</{tag}>"))).state,
            QuotaState::Unknown
        );
    }
    for content in [
        "0 MB<ſcript>1 GB</ſcript>",
        "0 MB<scrİpt>1 GB</scrİpt>",
        "0 MB<!-- 1 GB -->",
        "0&#xD800; MB",
        "0&#4294967296; MB",
        "0&#0; MB",
    ] {
        assert_eq!(classify_quota(&raw(content)).state, QuotaState::Unknown);
    }
}

fn online(owner: &str, service: &str) -> Value {
    json!({"data":{"portalOnlineUserInfo":{"result":"success","userId":owner,
        "userName":"Fixture Person","service":service,"realServiceName":service,"userIp":"127.0.0.1"}}})
}

struct Plan {
    snapshots: Vec<Value>,
    snapshot_count: usize,
    account: Value,
    account_http: u16,
    snapshot_delay: Duration,
    account_delay: Duration,
    requests: Vec<String>,
}
impl Default for Plan {
    fn default() -> Self {
        Self {
            snapshots: vec![online("fixture-user", "校园网")],
            snapshot_count: 0,
            account: json!({"data":{"data":{"accountInfo":raw("0 MB")["accountInfo"]}}}),
            account_http: 200,
            snapshot_delay: Duration::ZERO,
            account_delay: Duration::ZERO,
            requests: Vec::new(),
        }
    }
}
struct Fixture {
    config: Config,
    plan: Arc<StdMutex<Plan>>,
    task: JoinHandle<()>,
}
impl Fixture {
    async fn new(plan: Plan) -> Self {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let base = format!("http://{}", listener.local_addr().unwrap());
        let plan = Arc::new(StdMutex::new(plan));
        let state = plan.clone();
        let task = tokio::spawn(async move {
            while let Ok((mut socket, _)) = listener.accept().await {
                let state = state.clone();
                tokio::spawn(async move {
                    let mut input = Vec::new();
                    let mut buffer = [0; 4096];
                    let header_end = loop {
                        let n = socket.read(&mut buffer).await.unwrap_or(0);
                        if n == 0 {
                            return;
                        }
                        input.extend_from_slice(&buffer[..n]);
                        if let Some(end) = input.windows(4).position(|v| v == b"\r\n\r\n") {
                            break end + 4;
                        }
                        assert!(input.len() < 64 * 1024);
                    };
                    let head = String::from_utf8_lossy(&input[..header_end]);
                    let target = head
                        .lines()
                        .next()
                        .unwrap()
                        .split_whitespace()
                        .nth(1)
                        .unwrap();
                    let path = target.split('?').next().unwrap().to_owned();
                    let length = head
                        .lines()
                        .filter_map(|line| line.split_once(':'))
                        .find(|(key, _)| key.eq_ignore_ascii_case("content-length"))
                        .map(|(_, value)| value.trim().parse::<usize>().unwrap())
                        .unwrap_or(0);
                    while input.len() < header_end + length {
                        let n = socket.read(&mut buffer).await.unwrap_or(0);
                        if n == 0 {
                            return;
                        }
                        input.extend_from_slice(&buffer[..n]);
                    }
                    let (http, body, location, delay) = {
                        let mut plan = state.lock().unwrap();
                        plan.requests.push(path.clone());
                        match path.as_str() {
                            "/eportal/index.jsp" => (
                                302,
                                String::new(),
                                "Location: /entry?flowSessionId=quota-fixture\r\n",
                                Duration::ZERO,
                            ),
                            "/entry" => (200, "fixture portal".into(), "", Duration::ZERO),
                            "/eportal/adaptor/getOnlineUserInfo" => {
                                let index = plan.snapshot_count.min(plan.snapshots.len() - 1);
                                plan.snapshot_count += 1;
                                (
                                    200,
                                    plan.snapshots[index].to_string(),
                                    "",
                                    plan.snapshot_delay,
                                )
                            }
                            "/eportal/operator/getAccountInfo" => (
                                plan.account_http,
                                plan.account.to_string(),
                                "",
                                plan.account_delay,
                            ),
                            _ => (404, "unexpected request".into(), "", Duration::ZERO),
                        }
                    };
                    tokio::time::sleep(delay).await;
                    let response = format!("HTTP/1.1 {http} fixture\r\nContent-Type: application/json\r\n{location}Content-Length: {}\r\nConnection: close\r\n\r\n{body}",body.len());
                    let _ = socket.write_all(response.as_bytes()).await;
                });
            }
        });
        Self {
            config: Config {
                username: "fixture-user".into(),
                password: "fixture-only".into(),
                base: base.clone(),
                cas_host: base,
                backend: "api".into(),
                ..Config::default()
            },
            plan,
            task,
        }
    }
    fn client(&self) -> AuthClient {
        AuthClient::new_local_fixture(self.config.clone()).unwrap()
    }
    fn count(&self, path: &str) -> usize {
        self.plan
            .lock()
            .unwrap()
            .requests
            .iter()
            .filter(|s| s.as_str() == path)
            .count()
    }
    fn read_only(&self) {
        assert!(self
            .plan
            .lock()
            .unwrap()
            .requests
            .iter()
            .all(|path| matches!(
                path.as_str(),
                "/eportal/index.jsp"
                    | "/entry"
                    | "/eportal/adaptor/getOnlineUserInfo"
                    | "/eportal/operator/getAccountInfo"
            )));
    }
}
impl Drop for Fixture {
    fn drop(&mut self) {
        self.task.abort();
    }
}

#[tokio::test]
async fn verified_info_returns_zero_report_only_after_two_raw_state_queries() {
    let f = Fixture::new(Plan::default()).await;
    let summary = tokio::time::timeout(Duration::from_secs(2), f.client().verified_info())
        .await
        .expect("no nested client lock")
        .unwrap();
    assert_eq!(
        summary["quota"],
        json!({"state":"zero_reported","message":"门户报告剩余流量为零"})
    );
    assert_eq!(summary["items"], json!([["剩余流量", "0 MB"]]));
    assert_eq!(f.count("/eportal/adaptor/getOnlineUserInfo"), 2);
    assert_eq!(f.count("/eportal/operator/getAccountInfo"), 1);
    f.read_only();
}

#[tokio::test]
async fn shared_service_fields_gate_both_raw_rotation_snapshots() {
    for case in crate::service_tests::cases() {
        let service = case.expected.as_deref().unwrap_or("校园网");
        let payload = case.online("fixture-user");
        for snapshots in [
            vec![payload.clone()],
            vec![online("fixture-user", service), payload.clone()],
        ] {
            let mut f = Fixture::new(Plan {
                snapshots,
                ..Plan::default()
            })
            .await;
            f.config.service = service.into();
            let result = f.client().verified_info().await;
            assert_eq!(result.is_ok(), case.bound, "{}: {result:?}", case.id);
            if case.bound {
                assert_eq!(result.unwrap()["quota"]["state"], "zero_reported");
                assert_eq!(f.count("/eportal/adaptor/getOnlineUserInfo"), 2);
                assert_eq!(f.count("/eportal/operator/getAccountInfo"), 1);
            }
            f.read_only();
        }
    }
}

#[tokio::test]
async fn verified_info_never_queries_saved_offline_or_foreign_accounts() {
    for before in [
        online("other-account", "校园网"),
        online("fixture-user", "中国移动"),
        json!({"data":{"portalOnlineUserInfo":{"message":"dx.failed.user.offline"}}}),
        json!({"data":{"portalOnlineUserInfo":{"result":"pending","service":"校园网","userId":"fixture-user"}}}),
        online("", "校园网"),
    ] {
        let f = Fixture::new(Plan {
            snapshots: vec![before],
            ..Plan::default()
        })
        .await;
        assert!(f.client().verified_info().await.is_err());
        assert_eq!(f.count("/eportal/operator/getAccountInfo"), 0);
        f.read_only();
    }
}

#[tokio::test]
async fn verified_info_rejects_identity_service_or_state_changes_during_account_request() {
    for after in [
        online("other-account", "校园网"),
        online("fixture-user", "中国移动"),
        json!({"data":{"portalOnlineUserInfo":{"message":"dx.failed.user.offline"}}}),
        json!({"data":{"portalOnlineUserInfo":{"result":"unknown"}}}),
        online("fixture-user\u{200b}", "校园网"),
    ] {
        let f = Fixture::new(Plan {
            snapshots: vec![online("fixture-user", "校园网"), after],
            ..Plan::default()
        })
        .await;
        assert!(f.client().verified_info().await.is_err());
        assert_eq!(f.count("/eportal/operator/getAccountInfo"), 1);
        assert_eq!(f.count("/eportal/adaptor/getOnlineUserInfo"), 2);
        f.read_only();
    }
}

#[tokio::test]
async fn verified_info_requires_original_unambiguous_service_labels() {
    for label in [json!("unrecognized"), json!("中国移动"), json!(1)] {
        let mut ambiguous = online("fixture-user", "校园网");
        ambiguous["data"]["portalOnlineUserInfo"]["realServiceName"] = label;
        for snapshots in [
            vec![ambiguous.clone()],
            vec![online("fixture-user", "校园网"), ambiguous.clone()],
        ] {
            let f = Fixture::new(Plan {
                snapshots,
                ..Plan::default()
            })
            .await;
            assert!(f.client().verified_info().await.is_err());
            f.read_only();
        }
    }
}

#[tokio::test]
async fn verified_info_account_http_and_business_failures_with_zero_never_succeed() {
    for http in [401, 403, 429, 500, 201] {
        let f = Fixture::new(Plan {
            account_http: http,
            ..Plan::default()
        })
        .await;
        assert!(f.client().verified_info().await.is_err());
        assert_eq!(f.count("/eportal/operator/getAccountInfo"), 1);
        assert_eq!(f.count("/eportal/adaptor/getOnlineUserInfo"), 1);
        f.read_only();
    }
    for account in [
        json!({"result":"failed","data":raw("0 MB")}),
        json!({"result":"pending","data":raw("0 MB")}),
        json!({"code":"200","data":raw("0 MB")}),
        json!({"data":{"data":{"result":"error","accountInfo":raw("0 MB")["accountInfo"]}}}),
        json!({"data":{"name":"Fixture Person"}}),
        json!({"online":true,"items":[["剩余流量","0 MB"]]}),
        json!({"success":false,"data":raw("0 MB")}),
    ] {
        let f = Fixture::new(Plan {
            account,
            ..Plan::default()
        })
        .await;
        assert!(f.client().verified_info().await.is_err());
        assert_eq!(f.count("/eportal/adaptor/getOnlineUserInfo"), 1);
        f.read_only();
    }
}

#[tokio::test]
async fn verified_info_unknown_or_duplicate_quota_does_not_become_zero() {
    for account in [
        raw("0"),
        raw("NaN MB"),
        raw("-0 MB"),
        json!({"accountInfo":[]}),
        json!({"accountInfo":[{"title":"剩余流量","content":"1 MB"},{"title":"剩余流量","content":"0 MB"}]}),
    ] {
        let f = Fixture::new(Plan {
            account,
            ..Plan::default()
        })
        .await;
        let summary = f.client().verified_info().await.unwrap();
        assert_eq!(summary["quota"]["state"], "unknown");
        assert_eq!(f.count("/eportal/adaptor/getOnlineUserInfo"), 2);
        f.read_only();
    }
}

#[tokio::test]
async fn original_info_keeps_credential_free_foreign_and_offline_display() {
    let mut f = Fixture::new(Plan {
        snapshots: vec![online("other-account", "校园网")],
        ..Plan::default()
    })
    .await;
    f.config.username.clear();
    f.config.password.clear();
    let summary = f.client().info().await.unwrap();
    assert!(summary["fields"]
        .as_array()
        .unwrap()
        .iter()
        .any(|field| field[1] == "other-account"));
    assert_eq!(summary["quota"]["state"], "zero_reported");
    // info() keeps the foreign-account JSON, but now verifies identity after the read.
    assert_eq!(f.count("/eportal/adaptor/getOnlineUserInfo"), 2);
    assert!(f.client().verified_info().await.is_err());
    f.read_only();
    let f = Fixture::new(Plan {
        snapshots: vec![
            json!({"data":{"portalOnlineUserInfo":{"message":"dx.failed.user.offline"}}}),
        ],
        ..Plan::default()
    })
    .await;
    assert_eq!(
        f.client().info().await.unwrap(),
        json!({"online":false,"fields":[],"items":[]})
    );
    assert_eq!(f.count("/eportal/operator/getAccountInfo"), 0);
    assert_eq!(f.count("/eportal/adaptor/getOnlineUserInfo"), 1);
}

#[tokio::test]
async fn verified_info_budget_includes_lock_queue_without_network() {
    let mut f = Fixture::new(Plan::default()).await;
    f.config.operation_timeout = 1;
    let client = f.client();
    let guard = client.lock.lock().await;
    let start = Instant::now();
    assert_eq!(client.verified_info().await.unwrap_err().code, QUERY_ERROR);
    assert!(start.elapsed() < Duration::from_millis(1500));
    drop(guard);
    assert!(f.plan.lock().unwrap().requests.is_empty());
}

#[tokio::test]
async fn verified_info_has_one_total_budget_for_queue_and_all_queries() {
    let mut f = Fixture::new(Plan {
        snapshot_delay: Duration::from_millis(200),
        account_delay: Duration::from_millis(250),
        ..Plan::default()
    })
    .await;
    f.config.operation_timeout = 1;
    let client = f.client();
    let guard = client.lock.lock().await;
    let start = Instant::now();
    let release = async {
        tokio::time::sleep(Duration::from_millis(650)).await;
        drop(guard);
    };
    let (_, result) = tokio::join!(release, client.verified_info());
    assert_eq!(result.unwrap_err().code, QUERY_ERROR);
    assert!(start.elapsed() < Duration::from_millis(1500));
    assert_eq!(f.count("/eportal/operator/getAccountInfo"), 1);
    assert_eq!(f.count("/eportal/adaptor/getOnlineUserInfo"), 1);
    f.read_only();
}

#[tokio::test]
async fn verified_info_postcheck_also_uses_remaining_budget() {
    let mut f = Fixture::new(Plan {
        snapshot_delay: Duration::from_millis(300),
        account_delay: Duration::from_millis(500),
        ..Plan::default()
    })
    .await;
    f.config.operation_timeout = 1;
    let start = Instant::now();
    assert_eq!(
        f.client().verified_info().await.unwrap_err().code,
        QUERY_ERROR
    );
    assert!(start.elapsed() < Duration::from_millis(1500));
    assert_eq!(f.count("/eportal/operator/getAccountInfo"), 1);
    assert_eq!(f.count("/eportal/adaptor/getOnlineUserInfo"), 2);
    f.read_only();
}

#[tokio::test]
async fn verified_info_rejects_business_envelope_conflicts_in_both_state_queries() {
    for layer in ["outer", "data", "info"] {
        for (key, value) in [
            ("code", json!(500)),
            ("result", json!("pending")),
            ("success", json!(false)),
            ("online", json!(false)),
        ] {
            let mut conflicting = online("fixture-user", "校园网");
            let node = match layer {
                "outer" => &mut conflicting,
                "data" => &mut conflicting["data"],
                _ => &mut conflicting["data"]["portalOnlineUserInfo"],
            };
            node[key] = value;
            for postcheck in [false, true] {
                let snapshots = if postcheck {
                    vec![online("fixture-user", "校园网"), conflicting.clone()]
                } else {
                    vec![conflicting.clone()]
                };
                let f = Fixture::new(Plan {
                    snapshots,
                    ..Plan::default()
                })
                .await;
                assert!(
                    f.client().verified_info().await.is_err(),
                    "{layer}.{key} conflict, postcheck={postcheck}"
                );
                assert_eq!(
                    f.count("/eportal/operator/getAccountInfo"),
                    usize::from(postcheck)
                );
                f.read_only();
            }
        }
    }
}
