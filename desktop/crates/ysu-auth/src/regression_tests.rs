use super::*;

#[tokio::test]
async fn portal_follows_multiple_html_and_http_hops() {
    let f = Fixture::new();
    f.mutate(|s| s.navigation_hops = 3);
    assert!(!f.client().status().await.unwrap().online);
    assert_eq!(f.count("/nav/"), 4);
    assert_eq!(f.count("/eportal/adaptor/getOnlineUserInfo"), 1);
}

#[tokio::test]
async fn portal_html_loop_is_bounded_before_state_query() {
    let f = Fixture::new();
    f.mutate(|s| s.navigation_loop = true);
    let error = f.client().status().await.unwrap_err();
    assert_eq!(error.code, QUERY_ERROR);
    assert!(error.message.contains("次数限制"));
    assert!(f.count("/nav/") <= 17);
    assert_eq!(f.count("/eportal/adaptor/getOnlineUserInfo"), 0);
}

#[tokio::test]
async fn concurrent_login_before_selection_is_not_overwritten() {
    for owner in ["fixture-user", "other-account"] {
        let f = Fixture::new();
        f.mutate(|s| s.race_at = Some((2, "中国移动".into(), owner.into())));
        assert_eq!(f.client().login().await.unwrap_err().code, OPERATION_ERROR);
        assert_eq!(f.count("/eportal/network/"), 0);
    }
    let f = Fixture::new();
    f.mutate(|s| s.race_at = Some((2, "校园网".into(), "fixture-user".into())));
    assert!(f.client().login().await.unwrap().online);
    assert_eq!(f.count("/eportal/network/"), 0);
}

#[tokio::test]
async fn concurrent_account_after_selection_stops_activation() {
    let f = Fixture::new();
    f.mutate(|s| s.race_at = Some((3, "校园网".into(), "other-account".into())));
    assert_eq!(f.client().login().await.unwrap_err().code, OPERATION_ERROR);
    assert_eq!(f.count("/eportal/network/serviceLogin"), 1);
    assert_eq!(f.count("/eportal/network/userOnline"), 0);
    assert_eq!(f.state.lock().unwrap().owner, "other-account");
}

#[tokio::test]
async fn logout_rechecks_account_after_preflight() {
    let f = Fixture::new();
    f.mutate(|s| {
        s.online = Some("校园网".into());
        s.race_at = Some((2, "校园网".into(), "other-account".into()));
    });
    assert_eq!(f.client().logout().await.unwrap_err().code, OPERATION_ERROR);
    assert_eq!(f.count("/eportal/network/offline"), 0);
}

#[tokio::test]
async fn offline_switch_and_failed_logout_never_login_target() {
    let f = Fixture::new();
    assert_eq!(
        f.client()
            .switch_service("中国移动")
            .await
            .unwrap()
            .service
            .as_deref(),
        Some("中国移动")
    );
    assert_eq!(f.count("/eportal/network/offline"), 0);
    let mut f = Fixture::new();
    f.config.operation_timeout = 1;
    f.mutate(|s| {
        s.online = Some("校园网".into());
        s.offline_ack_only = true;
    });
    let start = Instant::now();
    let error = f.client().switch_service("中国移动").await.unwrap_err();
    assert_eq!(error.code, OPERATION_ERROR);
    assert!(error.message.contains("已独立确认恢复"));
    assert_eq!(f.count("/eportal/network/serviceLogin"), 0);
    assert!(start.elapsed() < Duration::from_secs(2));
}

#[tokio::test]
async fn missing_online_account_blocks_all_mutations() {
    for action in 0..3 {
        let f = Fixture::new();
        f.mutate(|s| {
            s.state_override = Some(
                json!({"data":{"portalOnlineUserInfo":{"result":"success","service":"校园网"}}}),
            )
        });
        let c = f.client();
        let result = match action {
            0 => c.login().await,
            1 => c.logout().await,
            _ => c.switch_service("中国移动").await,
        };
        assert_eq!(result.unwrap_err().code, OPERATION_ERROR);
        assert_eq!(f.count("/eportal/network/"), 0);
    }
}

#[tokio::test]
async fn redirect_cookie_rotation_retains_same_origin_xsrf_and_post_body() {
    let observed = Arc::new(StdMutex::new(Vec::<Request>::new()));
    let requests = observed.clone();
    let server = Server::new(Arc::new(move |r| {
        requests.lock().unwrap().push(r.clone());
        match r.path.as_str() {
            "/seed" => Response::html("seed").cookie("XSRF-TOKEN=old; Path=/"),
            "/post" => {
                let mut response =
                    Response::redirect("/final").cookie("XSRF-TOKEN=new%2Btoken; Path=/");
                response.status = 307;
                response
            }
            _ => Response::html("done"),
        }
    }));
    let config = Config {
        base: server.url(),
        cas_host: server.url(),
        ..Config::default()
    };
    let http = Transport::new(&config, true).unwrap();
    let op = Operation::new(Instant::now() + Duration::from_secs(2));
    http.get(http.endpoint("seed").unwrap(), &op).await.unwrap();
    let url = http.endpoint("post").unwrap();
    http.follow(
        Method::POST,
        url.clone(),
        http.api_headers(&url, None),
        Some(b"private-body".to_vec()),
        &op,
    )
    .await
    .unwrap();
    let requests = observed.lock().unwrap();
    let last = requests.last().unwrap();
    assert_eq!(last.method, "POST");
    assert_eq!(last.body, b"private-body");
    assert_eq!(
        last.headers.get("x-xsrf-token").map(String::as_str),
        Some("new+token")
    );
    assert!(last.headers["cookie"].contains("new%2Btoken"));
}

#[tokio::test]
async fn cross_origin_redirect_strips_sensitive_headers_and_blocks_repost() {
    let observed = Arc::new(StdMutex::new(Vec::<Request>::new()));
    let requests = observed.clone();
    let destination = Server::new(Arc::new(move |r| {
        requests.lock().unwrap().push(r);
        Response::html("done")
    }));
    let target = destination.url();
    let source = Server::new(Arc::new(move |r| {
        let mut reply = Response::redirect(&format!("{target}/collect"));
        if r.path == "/repost" {
            reply.status = 308;
        }
        reply
    }));
    let config = Config {
        base: source.url(),
        cas_host: destination.url(),
        ..Config::default()
    };
    let http = Transport::new(&config, true).unwrap();
    let op = Operation::new(Instant::now() + Duration::from_secs(2));
    let mut headers = HeaderMap::new();
    for name in [
        "cookie",
        "authorization",
        "x-xsrf-token",
        "origin",
        "referer",
    ] {
        headers.insert(name, reqwest::header::HeaderValue::from_static("private"));
    }
    http.follow(
        Method::POST,
        http.endpoint("start").unwrap(),
        headers.clone(),
        Some(b"private-body".to_vec()),
        &op,
    )
    .await
    .unwrap();
    {
        let requests = observed.lock().unwrap();
        assert_eq!(requests.len(), 1);
        assert_eq!(requests[0].method, "GET");
        assert!(requests[0].body.is_empty());
        for name in [
            "cookie",
            "authorization",
            "x-xsrf-token",
            "origin",
            "referer",
        ] {
            assert!(!requests[0].headers.contains_key(name));
        }
    }
    assert!(http
        .follow(
            Method::POST,
            http.endpoint("repost").unwrap(),
            headers,
            Some(b"private-body".to_vec()),
            &op
        )
        .await
        .is_err());
    assert_eq!(observed.lock().unwrap().len(), 1);
}

#[test]
fn portal_navigation_upgrades_only_the_fixed_legacy_entry_target() {
    let fixture: Value = serde_json::from_str(include_str!(
        "../../../../tests/fixtures/portal-navigation.json"
    ))
    .unwrap();
    assert_eq!(fixture["version"], 1);
    let http = Transport::new(&Config::default(), false).unwrap();
    let from = Url::parse(fixture["redirect"].as_str().unwrap()).unwrap();
    let legacy = Url::parse(fixture["legacy_target"].as_str().unwrap()).unwrap();
    let expected = Url::parse(fixture["https_target"].as_str().unwrap()).unwrap();
    let next = http.portal_navigation_target(&from, legacy.clone(), &Method::GET, false);
    assert_eq!(next, expected);
    assert_eq!(next.query(), legacy.query());
    assert!(http.allowed(&next).is_ok());
    // Normalization never makes cleartext transport itself permissible.
    assert!(http.allowed(&legacy).is_err());
}

fn api_portal_html_navigation_bodies(target: &str) -> [String; 5] {
    let escaped = target.replace('&', "&amp;");
    [
        format!("<meta http-equiv='refresh' content='0;url={target}'>"),
        format!("<meta http-equiv='REFRESH' content='0;url={escaped}'>"),
        format!("<script>window.location.href = '{target}';</script>"),
        format!("<script>location.assign('{target}');</script>"),
        format!("<script>location.replace('{target}');</script>"),
    ]
}

fn assert_api_portal_html_navigation_blocked(http: &Transport, from: &Url, target: &Url) {
    assert_eq!(
        http.portal_navigation_target(from, target.clone(), &Method::GET, false),
        *target
    );
    for body in api_portal_html_navigation_bodies(target.as_str()) {
        let error = crate::protocol::next_api_portal_navigation(http, &body, from).unwrap_err();
        assert_eq!(error.code, QUERY_ERROR);
        assert_eq!(error.diagnostic().reason, DiagnosticReason::RedirectBlocked);
    }
}

#[test]
fn api_portal_html_navigation_reuses_the_fixed_legacy_upgrade() {
    // Synthetic compatibility evidence only, not a reconstruction of a new incident.
    let fixture: Value = serde_json::from_str(include_str!(
        "../../../../tests/fixtures/portal-navigation.json"
    ))
    .unwrap();
    assert_eq!(fixture["version"], 1);
    let http = Transport::new(&Config::default(), false).unwrap();
    let from = Url::parse(fixture["redirect"].as_str().unwrap()).unwrap();
    let legacy = Url::parse(fixture["legacy_target"].as_str().unwrap()).unwrap();
    let expected = Url::parse(fixture["https_target"].as_str().unwrap()).unwrap();
    for body in api_portal_html_navigation_bodies(legacy.as_str()) {
        let next = crate::protocol::next_api_portal_navigation(&http, &body, &from)
            .unwrap()
            .unwrap();
        assert_eq!(next, expected);
        assert_eq!(next.query(), legacy.query());
        assert!(http.allowed(&next).is_ok());
    }
    assert!(http.allowed(&legacy).is_err());
}

#[test]
fn api_portal_html_navigation_keeps_terminal_source_and_target_boundaries() {
    let from = Url::parse("https://auth1.ysu.edu.cn/eportal/redirect.jsp").unwrap();
    let legacy =
        Url::parse("http://auth1.ysu.edu.cn/portal/portal-main?sessionId=fixture-session").unwrap();
    for verify_tls in [true, false] {
        let http = Transport::new(
            &Config {
                verify_tls,
                ..Config::default()
            },
            false,
        )
        .unwrap();
        // These are terminal response URLs, even when the original entry was redirect.jsp.
        for source in [
            "http://auth1.ysu.edu.cn/eportal/redirect.jsp",
            "https://auth1.ysu.edu.cn/",
            "https://auth1.ysu.edu.cn/eportal/index.jsp",
            "https://auth1.ysu.edu.cn/portal/portal-main",
            "https://auth1.ysu.edu.cn/eportal/redirect.jsp/other",
            "https://auth1.ysu.edu.cn/eportal/redirect.jsp?other=1",
            "https://auth1.ysu.edu.cn/eportal/redirect.jsp#fragment",
            "https://auth1.ysu.edu.cn:444/eportal/redirect.jsp",
            "https://cer.ysu.edu.cn/eportal/redirect.jsp",
            "https://124.124.124.124/eportal/redirect.jsp",
            "https://outside.invalid/eportal/redirect.jsp",
        ] {
            assert_api_portal_html_navigation_blocked(&http, &Url::parse(source).unwrap(), &legacy);
        }
        for target in [
            "http://outside.invalid/portal/portal-main?sessionId=fixture-session",
            "http://auth1.ysu.edu.cn.outside.invalid/portal/portal-main?sessionId=fixture-session",
            "http://cer.ysu.edu.cn/portal/portal-main?sessionId=fixture-session",
            "http://124.124.124.124/portal/portal-main?sessionId=fixture-session",
            "http://auth1.ysu.edu.cn:8080/portal/portal-main?sessionId=fixture-session",
            "http://user:pass@auth1.ysu.edu.cn/portal/portal-main?sessionId=fixture-session",
            "http://auth1.ysu.edu.cn/eportal/operator/getAccountInfo?sessionId=fixture-session",
            "http://auth1.ysu.edu.cn/portal/portal-main/other?sessionId=fixture-session",
            "http://auth1.ysu.edu.cn/portal/portal-main?sessionId=fixture-session#fragment",
            "http://auth1.ysu.edu.cn/portal/portal-main",
            "http://auth1.ysu.edu.cn/portal/portal-main?sessionId=",
            "http://auth1.ysu.edu.cn/portal/portal-main?sessionId=fixture-session&sessionId=other",
            "http://auth1.ysu.edu.cn/portal/portal-main?sessionId=fixture%0Asession",
            "http://auth1.ysu.edu.cn/portal/portal-main?flowSessionId=fixture-session",
        ] {
            assert_api_portal_html_navigation_blocked(&http, &from, &Url::parse(target).unwrap());
        }
        let oversized = Url::parse(&format!(
            "http://auth1.ysu.edu.cn/portal/portal-main?sessionId={}",
            "s".repeat(1025)
        ))
        .unwrap();
        assert_api_portal_html_navigation_blocked(&http, &from, &oversized);
    }
    let custom_port = Transport::new(
        &Config {
            base: "https://auth1.ysu.edu.cn:444".into(),
            ..Config::default()
        },
        false,
    )
    .unwrap();
    let source = custom_port.endpoint("eportal/redirect.jsp").unwrap();
    assert_api_portal_html_navigation_blocked(&custom_port, &source, &legacy);
}

#[test]
fn api_portal_html_navigation_preserves_absent_and_allowed_https_navigation() {
    let http = Transport::new(&Config::default(), false).unwrap();
    let from = http.endpoint("eportal/index.jsp").unwrap();
    assert!(crate::protocol::next_api_portal_navigation(&http, "<p>No navigation</p>", &from)
        .unwrap()
        .is_none());
    let expected = http
        .endpoint("portal/portal-main?sessionId=fixture-session&ssid=fixture-wifi")
        .unwrap();
    for body in api_portal_html_navigation_bodies(expected.as_str()) {
        assert_eq!(
            crate::protocol::next_api_portal_navigation(&http, &body, &from).unwrap(),
            Some(expected.clone())
        );
    }
    assert_eq!(
        crate::protocol::next_api_portal_navigation(
            &http,
            "<script>location.assign('/portal/portal-main?sessionId=fixture-session&ssid=fixture-wifi');</script>",
            &from,
        )
        .unwrap(),
        Some(expected)
    );
}

#[test]
fn legacy_navigation_upgrade_preserves_trust_and_credential_boundaries() {
    let from = Url::parse("https://auth1.ysu.edu.cn/eportal/redirect.jsp").unwrap();
    let legacy =
        Url::parse("http://auth1.ysu.edu.cn/portal/portal-main?sessionId=fixture-session").unwrap();
    for verify_tls in [true, false] {
        let config = Config {
            verify_tls,
            ..Config::default()
        };
        let http = Transport::new(&config, false).unwrap();
        for value in [
            "http://auth1.ysu.edu.cn/eportal/redirect.jsp",
            "https://auth1.ysu.edu.cn/eportal/index.jsp",
            "https://auth1.ysu.edu.cn/eportal/redirect.jsp?other=1",
            "https://cer.ysu.edu.cn/eportal/redirect.jsp",
            "https://124.124.124.124/eportal/redirect.jsp",
            "https://outside.invalid/eportal/redirect.jsp",
        ] {
            let source = Url::parse(value).unwrap();
            let next = http.portal_navigation_target(&source, legacy.clone(), &Method::GET, false);
            assert_eq!(next, legacy);
            assert!(http.allowed(&next).is_err());
        }
        for value in [
            "http://auth1.ysu.edu.cn.outside.invalid/portal/portal-main?sessionId=fixture-session",
            "http://cer.ysu.edu.cn/portal/portal-main?sessionId=fixture-session",
            "http://124.124.124.124/portal/portal-main?sessionId=fixture-session",
            "http://auth1.ysu.edu.cn:8080/portal/portal-main?sessionId=fixture-session",
            "http://user:pass@auth1.ysu.edu.cn/portal/portal-main?sessionId=fixture-session",
            "http://auth1.ysu.edu.cn/eportal/operator/getAccountInfo?sessionId=fixture-session",
            "http://auth1.ysu.edu.cn/portal/portal-main/other?sessionId=fixture-session",
            "http://auth1.ysu.edu.cn/portal/portal-main",
            "http://auth1.ysu.edu.cn/portal/portal-main?sessionId=",
            "http://auth1.ysu.edu.cn/portal/portal-main?sessionId=fixture-session&sessionId=other",
            "http://auth1.ysu.edu.cn/portal/portal-main?sessionId=fixture%0Asession",
            "http://auth1.ysu.edu.cn/portal/portal-main?sessionId=fixture-session#fragment",
        ] {
            let target = Url::parse(value).unwrap();
            let next = http.portal_navigation_target(&from, target.clone(), &Method::GET, false);
            assert_eq!(next, target);
            assert!(http.allowed(&next).is_err());
        }
        for (method, has_body) in [
            (Method::POST, true),
            (Method::POST, false),
            (Method::GET, true),
            (Method::HEAD, false),
        ] {
            let next = http.portal_navigation_target(&from, legacy.clone(), &method, has_body);
            assert_eq!(next, legacy);
            assert!(http.allowed(&next).is_err());
        }
    }
    let custom_port = Transport::new(
        &Config {
            base: "https://auth1.ysu.edu.cn:444".into(),
            ..Config::default()
        },
        false,
    )
    .unwrap();
    let source = custom_port.endpoint("eportal/redirect.jsp").unwrap();
    assert_eq!(
        custom_port.portal_navigation_target(&source, legacy.clone(), &Method::GET, false),
        legacy
    );
}

#[test]
fn tls_and_exact_origin_boundaries_are_not_relaxed_by_certificate_toggle() {
    for verify_tls in [true, false] {
        let config = Config {
            verify_tls,
            ..Config::default()
        };
        let http = Transport::new(&config, false).unwrap();
        for value in [
            "http://auth1.ysu.edu.cn/",
            "https://auth1.ysu.edu.cn:444/",
            "https://auth1.ysu.edu.cn.outside.invalid/",
            "https://user:pass@cer.ysu.edu.cn/",
            "https://124.124.124.124:444/",
        ] {
            assert!(http.allowed(&Url::parse(value).unwrap()).is_err());
        }
        assert!(http
            .allowed(&Url::parse("https://124.124.124.124/").unwrap())
            .is_ok());
    }
}

#[tokio::test]
async fn captive_navigation_never_accepts_authentication_body() {
    let http = Transport::new(&Config::default(), false).unwrap();
    let op = Operation::new(Instant::now() + Duration::from_millis(30));
    let error = http
        .once(
            Method::POST,
            Url::parse("https://124.124.124.124/collect").unwrap(),
            HeaderMap::new(),
            Some(b"private-body".to_vec()),
            &op,
        )
        .await
        .unwrap_err_for_test();
    assert!(error.message.contains("仅向门户"));
    assert!(!error.message.contains("private"));
}

#[tokio::test]
async fn chunked_and_compressed_bodies_are_bounded_after_decoding() {
    for compressed in [false, true] {
        let mut bytes = vec![b'x'; RESPONSE_LIMIT + 1];
        if compressed {
            let mut encoder =
                flate2::write::GzEncoder::new(Vec::new(), flate2::Compression::default());
            encoder.write_all(&bytes).unwrap();
            bytes = encoder.finish().unwrap();
            assert!(bytes.len() < RESPONSE_LIMIT);
        }
        let server = Server::new(Arc::new(move |_| {
            let mut response = Response::body(200, bytes.clone(), "application/octet-stream");
            response
                .headers
                .push(("Transfer-Encoding".into(), "chunked".into()));
            if compressed {
                response
                    .headers
                    .push(("Content-Encoding".into(), "gzip".into()));
            }
            response
        }));
        let config = Config {
            base: server.url(),
            cas_host: server.url(),
            ..Config::default()
        };
        let http = Transport::new(&config, true).unwrap();
        let op = Operation::new(Instant::now() + Duration::from_secs(2));
        let error = http.get(http.base.clone(), &op).await.unwrap_err_for_test();
        assert_eq!(error.code, QUERY_ERROR);
        assert!(error.message.contains("大小限制"));
    }
}

#[tokio::test]
async fn cancelled_operation_releases_serialization_lock() {
    let f = Fixture::new();
    let client = f.client();
    let held = client.lock.lock().await;
    assert!(
        tokio::time::timeout(Duration::from_millis(20), client.status())
            .await
            .is_err()
    );
    drop(held);
    assert!(!client.status().await.unwrap().online);
}

#[test]
fn missing_account_items_are_empty_and_zero_is_literal() {
    let online = json!({"data":{"portalOnlineUserInfo":{"result":"success","service":"校园网","userId":"u"}}});
    let absent = presentation::summary(
        &online,
        &json!({"data":{"accountInfo":[null,2,{}, {"title":"设备","content":"1 台"}]}}),
    );
    assert_eq!(absent["items"], json!([["设备", "1 台"]]));
    assert!(!absent.to_string().contains("不限量"));
    let zero = presentation::summary(
        &online,
        &json!({"data":{"accountInfo":[{"title":"余额","content":0},{"title":"流量","content":"0 MB"}]}}),
    );
    assert_eq!(zero["items"], json!([["余额", "0"], ["流量", "0 MB"]]));
}

#[tokio::test]
#[ignore = "requires host-installed Chromium; runs against loopback fixtures only"]
async fn chromium_cdp_dom_challenge_and_risk_do_not_submit_credentials() {
    for risk in [false, true] {
        let mut f = Fixture::new();
        f.config.backend = "browser".into();
        // Include host Chromium cold start, as in the other real-browser fixtures.
        // Protocol deadline tests keep their independent short budgets.
        f.config.operation_timeout = 20;
        f.mutate(|s| {
            s.cas_required = true;
            s.dom_captcha = !risk;
            s.risk = risk;
        });
        let error = f.client().login().await.unwrap_err();
        assert_eq!(
            error.code,
            INTERACTION_ERROR,
            "risk={risk}; diagnostic={:?}",
            error.diagnostic()
        );
        assert_eq!(f.count("/eportal/network/serviceLogin"), 0);
        assert_eq!(
            f.state
                .lock()
                .unwrap()
                .requests
                .iter()
                .filter(|r| r.method == "POST" && r.path.starts_with("/authserver/login"))
                .count(),
            0
        );
    }
}

#[tokio::test]
async fn expired_deadline_never_polls_even_immediately_ready_work() {
    let operation = Operation::new(Instant::now() - Duration::from_millis(1));
    let touched = AtomicBool::new(false);
    let result = operation
        .run(async {
            touched.store(true, Ordering::SeqCst);
        })
        .await;
    assert_eq!(result.unwrap_err().code, QUERY_ERROR);
    assert!(!touched.load(Ordering::SeqCst));
}

#[test]
fn duplicate_missing_item_does_not_display_stale_balance() {
    let online = json!({"data":{"portalOnlineUserInfo":{"result":"success","service":"校园网"}}});
    let account = json!({"data":{"accountInfo":[{"title":"余额","content":"100 元"},{"title":"余额","content":null}]}});
    assert_eq!(presentation::summary(&online, &account)["items"], json!([]));
}

#[test]
fn deeply_nested_portal_text_is_cleaned_without_recursive_traversal() {
    let source = format!("{}0 MB{}", "<div>".repeat(2048), "</div>".repeat(2048));
    assert_eq!(presentation::text(&json!(source)), "0 MB");
}

#[test]
fn public_futures_remain_send_and_status_shape_remains_stable() {
    fn send<T: Send>(_: T) {}
    let client = AuthClient::new(Config::default()).unwrap();
    send(client.status());
    send(client.login());
    send(client.logout());
    send(client.info());
    send(client.switch_service("校园网"));
    let status = Status {
        online: false,
        service: None,
        user: String::new(),
        ip: String::new(),
        message: "已确认离线".into(),
    };
    assert_eq!(
        serde_json::to_value(status.clone()).unwrap(),
        json!({"online":false,"service":null,"user":"","ip":"","message":"已确认离线"})
    );
}

#[tokio::test]
async fn oversized_request_headers_fail_before_http_send() {
    let f = Fixture::new();
    let http = Transport::new(&f.config, true).unwrap();
    let op = Operation::new(Instant::now() + Duration::from_secs(1));
    let mut headers = HeaderMap::new();
    headers.insert(
        "x-fixture",
        reqwest::header::HeaderValue::from_str(&"x".repeat(65537)).unwrap(),
    );
    assert!(http
        .once(Method::GET, http.base.clone(), headers, None, &op)
        .await
        .unwrap_err_for_test()
        .message
        .contains("请求头"));
    assert_eq!(f.state.lock().unwrap().requests.len(), 0);
}

#[tokio::test]
#[ignore = "requires host-installed Chromium; runs against loopback fixtures only"]
async fn chromium_subresource_cannot_overwrite_portal_session() {
    let mut fixture = Fixture::new();
    fixture.config.backend = "browser".into();
    fixture.config.operation_timeout = 10;
    fixture.mutate(|state| state.poison_sid = true);
    assert!(!fixture.client().status().await.unwrap().online);
    assert!(fixture.count("/fixture-asset") > 0);
    let state = fixture.state.lock().unwrap();
    for request in state
        .requests
        .iter()
        .filter(|r| r.path.starts_with("/eportal/adaptor/getOnlineUserInfo"))
    {
        let url = Url::parse(&format!("http://fixture{}", request.path)).unwrap();
        assert_eq!(
            protocol::query(&url, "sessionId").as_deref(),
            Some("fixture-session")
        );
    }
}

#[test]
fn matching_cookie_paths_prioritize_cas_token_and_session_deterministically() {
    use reqwest::cookie::CookieStore;
    let config = Config::default();
    let http = Transport::new(&config, false).unwrap();
    let target = http.cas.join("authserver/login").unwrap();
    for _ in 0..32 {
        let jar = crate::cookies::Jar::default();
        let headers = [
            reqwest::header::HeaderValue::from_static("XSRF-TOKEN=portal; Path=/"),
            reqwest::header::HeaderValue::from_static("JSESSIONID=portal; Path=/"),
            reqwest::header::HeaderValue::from_static("XSRF-TOKEN=cas; Path=/authserver"),
            reqwest::header::HeaderValue::from_static("JSESSIONID=cas; Path=/authserver"),
            reqwest::header::HeaderValue::from_static(
                "XSRF-TOKEN=excluded; Path=/authserver/login-other",
            ),
            reqwest::header::HeaderValue::from_static(
                "JSESSIONID=bad; Domain=outside.invalid; Path=/authserver",
            ),
        ];
        jar.set_cookies(&mut headers.iter(), &target);
        let value = jar.cookies(&target).unwrap();
        assert_eq!(
            value.to_str().unwrap(),
            "JSESSIONID=cas; XSRF-TOKEN=cas; JSESSIONID=portal; XSRF-TOKEN=portal"
        );
        jar.set_cookies(
            &mut [reqwest::header::HeaderValue::from_static(
                "XSRF-TOKEN=cas; Path=/authserver; Max-Age=0",
            )]
            .iter(),
            &target,
        );
        assert!(!jar
            .cookies(&target)
            .unwrap()
            .to_str()
            .unwrap()
            .contains("XSRF-TOKEN=cas"));
    }
}

#[tokio::test]
async fn explicit_empty_or_malformed_user_id_never_falls_back_to_display_name() {
    for id in [json!(""), json!(null), json!(0), json!([])] {
        let f = Fixture::new();
        f.mutate(|s| s.state_override = Some(json!({"data":{"portalOnlineUserInfo":{"result":"success","service":"校园网","userId":id,"userName":"fixture-user"}}})));
        let c = f.client();
        assert!(c.status().await.unwrap().user.is_empty());
        assert_eq!(c.login().await.unwrap_err().code, OPERATION_ERROR);
        assert_eq!(c.logout().await.unwrap_err().code, OPERATION_ERROR);
        assert_eq!(
            c.switch_service("中国移动").await.unwrap_err().code,
            OPERATION_ERROR
        );
        assert_eq!(f.count("/eportal/network/"), 0);
    }
}

#[tokio::test]
async fn synchronous_work_cannot_return_success_after_total_deadline() {
    let op = Operation::new(Instant::now() + Duration::from_millis(5));
    let result = op
        .run(async {
            std::thread::sleep(Duration::from_millis(20));
            1
        })
        .await;
    assert_eq!(result.unwrap_err().code, QUERY_ERROR);
}
