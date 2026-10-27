use super::*;
use crate::protocol::Snapshot;
use serde_json::{json, Value};

fn observation_snapshot(user: &str, service: &str, ip: &str) -> Snapshot {
    Snapshot::parse(json!({"data":{"portalOnlineUserInfo":{
        "result":"success", "userId":user, "service":service, "userIp":ip
    }}}))
    .unwrap()
}

fn observation_account() -> Value {
    json!({"data":{"accountInfo":[{"title":"剩余流量","content":"1024 MB"}]}})
}

fn assert_observation_verification_error(error: &AuthError) {
    assert_eq!(error.code, QUERY_ERROR);
    assert_eq!(error.diagnostic().stage, DiagnosticStage::Verification);
    assert_eq!(
        error.diagnostic().reason,
        DiagnosticReason::IdentityMismatch
    );
    let public = serde_json::to_string(&error.diagnostic()).unwrap();
    for private in [
        "external-account",
        "192.0.2.1",
        "fixture-session",
        "1024 MB",
    ] {
        assert!(!public.contains(private));
        assert!(!error.message.contains(private));
    }
}

#[test]
fn info_observation_binds_actual_identity_without_changing_summary_json() {
    let before = observation_snapshot("external-account", "中国联通", "192.0.2.1");
    let after = observation_snapshot("external-account", "中国联通", "192.0.2.1");
    let account = observation_account();
    let mut expected = presentation::summary(&before.payload, &account);
    expected["quota"] = serde_json::to_value(classify_quota(&account)).unwrap();
    let observation = InfoObservation::from_snapshots(&before, &account, after).unwrap();
    assert!(observation.matches_status(&before.status));
    assert_eq!(observation.info, expected);
    assert!(observation.info.get("status").is_none());
    let mut message_only = before.status.clone();
    message_only.message = "An unrelated display message".into();
    assert!(observation.matches_status(&message_only));
}

#[test]
fn info_observation_rejects_each_identity_change_and_offline_transition() {
    let before = observation_snapshot("external-account", "校园网", "192.0.2.1");
    let account = observation_account();
    let mut changed = vec![
        observation_snapshot("other-account", "校园网", "192.0.2.1"),
        observation_snapshot("external-account", "中国移动", "192.0.2.1"),
        observation_snapshot("external-account", "校园网", "192.0.2.2"),
    ];
    changed.push(
        Snapshot::parse(json!({"data":{"portalOnlineUserInfo":{
            "message":"dx.failed.user.offline"
        }}}))
        .unwrap(),
    );
    let observation = InfoObservation {
        status: before.status.clone(),
        info: Value::Null,
    };
    for after in changed {
        assert!(!observation.matches_status(&after.status));
        let error = InfoObservation::from_snapshots(&before, &account, after).unwrap_err();
        assert_observation_verification_error(&error);
    }
}

#[test]
fn info_observation_preserves_partial_identity_without_guessing_missing_fields() {
    for missing in ["userId", "userIp"] {
        let mut payload = json!({"data":{"portalOnlineUserInfo":{
            "result":"success", "userId":"external-account", "service":"校园网",
            "userIp":"192.0.2.1"
        }}});
        payload["data"]["portalOnlineUserInfo"]
            .as_object_mut()
            .unwrap()
            .remove(missing);
        let before = Snapshot::parse(payload.clone()).unwrap();
        let after = Snapshot::parse(payload).unwrap();
        let account = observation_account();
        let mut expected = presentation::summary(&before.payload, &account);
        expected["quota"] = serde_json::to_value(classify_quota(&account)).unwrap();
        let observation = InfoObservation::from_snapshots(&before, &account, after).unwrap();
        assert!(observation.matches_status(&before.status));
        assert_eq!(observation.info, expected);
        if missing == "userId" {
            assert!(observation.status.user.is_empty());
        } else {
            assert!(observation.status.ip.is_empty());
        }
        let known = observation_snapshot("external-account", "校园网", "192.0.2.1");
        let error = InfoObservation::from_snapshots(&before, &account, known).unwrap_err();
        assert_observation_verification_error(&error);
    }
    assert!(Snapshot::parse(json!({"data":{"portalOnlineUserInfo":{
        "result":"success", "userId":"external-account", "userIp":"192.0.2.1"
    }}}))
    .is_err());
    // Exact matching itself also supports the existing Demo's blank observations.
    let blank = Status {
        online: true,
        user: String::new(),
        service: None,
        ip: String::new(),
        message: String::new(),
    };
    let observation = InfoObservation {
        status: blank.clone(),
        info: Value::Null,
    };
    assert!(observation.matches_status(&blank));
}

#[test]
fn offline_info_observation_keeps_the_original_empty_json_shape() {
    let offline = Snapshot::parse(json!({"data":{"portalOnlineUserInfo":{
        "message":"dx.failed.user.offline"
    }}}))
    .unwrap();
    let observation = InfoObservation::offline(offline.status.clone());
    assert!(observation.matches_status(&offline.status));
    assert_eq!(
        observation.info,
        json!({"online":false,"fields":[],"items":[]})
    );
}

#[test]
fn postcheck_failures_preserve_reason_including_deadline_without_raw_materials() {
    for reason in [
        DiagnosticReason::Network,
        DiagnosticReason::RedirectBlocked,
        DiagnosticReason::ResponseInvalid,
        DiagnosticReason::StateUnrecognized,
        DiagnosticReason::Deadline,
        DiagnosticReason::HttpRejected,
        DiagnosticReason::Unknown,
    ] {
        let original = AuthError::new(
            QUERY_ERROR,
            "fixture-sensitive-message https://outside.invalid/?sessionId=fixture-private-query",
        )
        .because(reason)
        .at(DiagnosticStage::OnlineState);
        let error = crate::info_observation::postcheck_error(original);
        assert_eq!(error.code, QUERY_ERROR);
        assert_eq!(error.diagnostic().stage, DiagnosticStage::Verification);
        assert_eq!(error.diagnostic().reason, reason);
        assert!(error.diagnostic().navigation.is_none());
        assert_ne!(
            error.diagnostic().reason,
            DiagnosticReason::IdentityMismatch
        );
        let public = serde_json::to_string(&error.diagnostic()).unwrap();
        for raw in [
            "fixture-sensitive-message",
            "outside.invalid",
            "fixture-private-query",
        ] {
            assert!(!error.message.contains(raw));
            assert!(!public.contains(raw));
        }
    }
}

#[test]
fn postcheck_keeps_closed_navigation_categories_without_reintroducing_material() {
    let portal = url::Url::parse("https://portal.invalid").unwrap();
    let cas = url::Url::parse("https://cas.invalid").unwrap();
    let source = url::Url::parse("https://SOURCE_USER:SOURCE_PASSWORD@portal.invalid/eportal/redirect.jsp?ticket=SOURCE_QUERY#SOURCE_FRAGMENT").unwrap();
    let target = url::Url::parse("http://TARGET_USER:TARGET_PASSWORD@portal.invalid/portal/portal-main?sessionId=TARGET_SID&userIp=192.0.2.9").unwrap();
    let navigation = NavigationDiagnostic::capture(
        NavigationKind::HttpLocation,
        &source,
        &target,
        &portal,
        &cas,
        "GET",
        false,
    );
    let original = AuthError::new(QUERY_ERROR, "RAW_CAUSE SOURCE_PASSWORD TARGET_SID")
        .because(DiagnosticReason::RedirectBlocked)
        .at(DiagnosticStage::OnlineState)
        .with_navigation(navigation);
    let fixed = crate::info_observation::postcheck_error(original);
    assert_eq!(fixed.code, QUERY_ERROR);
    assert_eq!(fixed.diagnostic().stage, DiagnosticStage::Verification);
    assert_eq!(fixed.diagnostic().reason, DiagnosticReason::RedirectBlocked);
    assert_eq!(fixed.diagnostic().navigation, Some(navigation));
    let public = serde_json::to_string(&fixed.diagnostic()).unwrap();
    let detail = navigation.detail();
    for private in [
        "portal.invalid", "cas.invalid", "SOURCE_USER", "SOURCE_PASSWORD",
        "SOURCE_QUERY", "SOURCE_FRAGMENT", "TARGET_USER", "TARGET_PASSWORD",
        "TARGET_SID", "192.0.2.9", "RAW_CAUSE",
    ] {
        assert!(!fixed.message.contains(private));
        assert!(!public.contains(private));
        assert!(!detail.contains(private));
    }
}
