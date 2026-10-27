use super::*;

fn diagnostic(
    error: &AuthError,
    operation: DiagnosticOperation,
    stage: DiagnosticStage,
    reason: DiagnosticReason,
) {
    assert_eq!(
        error.diagnostic(),
        AuthDiagnostic {
            operation,
            stage,
            reason,
            navigation: error.diagnostic().navigation,
        }
    );
    let serialized = serde_json::to_string(&error.diagnostic()).unwrap();
    for private in [
        "fixture-sensitive-message",
        "fixture-private-query",
        "private-response",
        "fixture-user",
        "192.0.2.1",
    ] {
        assert!(!serialized.contains(private));
    }
}

#[test]
fn legacy_messages_never_become_diagnostic_values() {
    for code in [QUERY_ERROR, OPERATION_ERROR, INTERACTION_ERROR, 99] {
        let error = AuthError::new(
            code,
            "fixture-sensitive-message https://outside.invalid/?token=fixture-private-query",
        );
        assert_eq!(error.code, code);
        diagnostic(
            &error,
            DiagnosticOperation::Unknown,
            DiagnosticStage::Unknown,
            DiagnosticReason::Unknown,
        );
        assert_eq!(
            serde_json::to_value(error.diagnostic()).unwrap(),
            json!({"operation":"unknown","stage":"unknown","reason":"unknown"})
        );
    }
}

#[tokio::test]
async fn common_navigation_errors_identify_the_public_operation_without_network_data() {
    for (reply_status, location, expected_reason) in [
        (
            302,
            Some("http://outside.invalid/collect?sessionId=fixture-private-query"),
            DiagnosticReason::RedirectBlocked,
        ),
        (302, None, DiagnosticReason::ResponseInvalid),
        (500, None, DiagnosticReason::HttpRejected),
    ] {
        let server = Server::new(Arc::new(move |_| {
            let mut response = Response::html("fixture-sensitive-message");
            response.status = reply_status;
            if let Some(location) = location {
                response.headers.push(("Location".into(), location.into()));
            }
            response
        }));
        let config = Config {
            base: server.url(),
            cas_host: server.url(),
            username: "fixture-user".into(),
            password: "fixture-password".into(),
            ..Config::default()
        };
        for operation in [
            DiagnosticOperation::Status,
            DiagnosticOperation::Info,
            DiagnosticOperation::Login,
            DiagnosticOperation::Logout,
            DiagnosticOperation::SwitchService,
            DiagnosticOperation::VerifiedInfo,
        ] {
            let client = AuthClient::new_local_fixture(config.clone()).unwrap();
            let error = match operation {
                DiagnosticOperation::Status => client.status().await.map(|_| ()),
                DiagnosticOperation::Info => client.info().await.map(|_| ()),
                DiagnosticOperation::Login => client.login().await.map(|_| ()),
                DiagnosticOperation::Logout => client.logout().await.map(|_| ()),
                DiagnosticOperation::SwitchService => {
                    client.switch_service("中国移动").await.map(|_| ())
                }
                DiagnosticOperation::VerifiedInfo => client.verified_info().await.map(|_| ()),
                DiagnosticOperation::Unknown => unreachable!(),
            }
            .unwrap_err();
            assert_eq!(error.code, QUERY_ERROR);
            diagnostic(
                &error,
                operation,
                DiagnosticStage::PortalNavigation,
                expected_reason,
            );
        }
    }
}

#[tokio::test]
async fn online_state_http_and_unknown_payload_are_distinct() {
    let f = Fixture::new();
    f.mutate(|state| state.state_http = 500);
    let error = f.client().status().await.unwrap_err();
    diagnostic(
        &error,
        DiagnosticOperation::Status,
        DiagnosticStage::OnlineState,
        DiagnosticReason::HttpRejected,
    );
    f.mutate(|state| {
        state.state_http = 200;
        state.state_override = Some(json!({"data":{"portalOnlineUserInfo":{"result":"fail","message":"fixture-sensitive-message"}}}));
    });
    let error = f.client().info().await.unwrap_err();
    diagnostic(
        &error,
        DiagnosticOperation::Info,
        DiagnosticStage::OnlineState,
        DiagnosticReason::StateUnrecognized,
    );
}

#[tokio::test]
async fn account_business_and_json_errors_never_include_response_content() {
    for malformed in [false, true] {
        let server = Server::new(Arc::new(move |request| {
            if request.path.starts_with("/eportal/index.jsp") {
                Response::redirect("/portal/portal-main?sessionId=fixture-session")
            } else if request.path.starts_with("/portal/") {
                Response::html("portal")
            } else if request
                .path
                .starts_with("/eportal/adaptor/getOnlineUserInfo")
            {
                Response::json(
                    json!({"data":{"portalOnlineUserInfo":{"result":"success","service":"校园网","userId":"fixture-user"}}}),
                )
            } else if malformed {
                Response::html("fixture-sensitive-message")
            } else {
                Response::json(json!({"result":"fail","message":"fixture-sensitive-message"}))
            }
        }));
        let client = AuthClient::new_local_fixture(Config {
            base: server.url(),
            cas_host: server.url(),
            ..Config::default()
        })
        .unwrap();
        let error = client.info().await.unwrap_err();
        assert_eq!(
            error.code,
            if malformed {
                QUERY_ERROR
            } else {
                OPERATION_ERROR
            }
        );
        diagnostic(
            &error,
            DiagnosticOperation::Info,
            DiagnosticStage::AccountInfo,
            if malformed {
                DiagnosticReason::ResponseInvalid
            } else {
                DiagnosticReason::BusinessRejected
            },
        );
    }
}

#[tokio::test]
async fn node_business_failure_has_fixed_stage_and_preserves_query_code() {
    let f = Fixture::new();
    f.mutate(|state| state.node_override = Some(json!({"result":"fail","message":"fixture-sensitive-message","data":{"currentNodePath":"serviceSelection"}})));
    let error = f.client().login().await.unwrap_err();
    assert_eq!(error.code, QUERY_ERROR);
    diagnostic(
        &error,
        DiagnosticOperation::Login,
        DiagnosticStage::FlowNode,
        DiagnosticReason::BusinessRejected,
    );
    assert_eq!(f.count("/eportal/network/"), 0);
}

#[tokio::test]
async fn cas_rejection_and_identity_conflict_keep_original_codes() {
    let f = Fixture::new();
    f.mutate(|state| {
        state.cas_required = true;
        state.cas_reject = 503;
    });
    let error = f.client().login().await.unwrap_err();
    assert_eq!(error.code, QUERY_ERROR);
    diagnostic(
        &error,
        DiagnosticOperation::Login,
        DiagnosticStage::CasSubmit,
        DiagnosticReason::HttpRejected,
    );
    let f = Fixture::new();
    f.mutate(|state| {
        state.online = Some("校园网".into());
        state.owner = "fixture-other".into();
    });
    let error = f.client().login().await.unwrap_err();
    assert_eq!(error.code, OPERATION_ERROR);
    diagnostic(
        &error,
        DiagnosticOperation::Login,
        DiagnosticStage::Verification,
        DiagnosticReason::IdentityMismatch,
    );
}

#[tokio::test]
async fn queue_deadline_and_connection_error_have_separate_fixed_reasons() {
    let mut f = Fixture::new();
    f.config.operation_timeout = 1;
    let client = f.client();
    let held = client.lock.lock().await;
    let error = client.status().await.unwrap_err();
    diagnostic(
        &error,
        DiagnosticOperation::Status,
        DiagnosticStage::Queue,
        DiagnosticReason::Deadline,
    );
    drop(held);
    assert_eq!(f.state.lock().unwrap().requests.len(), 0);
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let address = listener.local_addr().unwrap();
    drop(listener);
    let base = format!("http://{address}");
    let client = AuthClient::new_local_fixture(Config {
        base: base.clone(),
        cas_host: base,
        ..Config::default()
    })
    .unwrap();
    let error = client.status().await.unwrap_err();
    diagnostic(
        &error,
        DiagnosticOperation::Status,
        DiagnosticStage::PortalNavigation,
        DiagnosticReason::Network,
    );
}
