use super::*;
use serde_json::{json, Value};
use url::Url;

fn capture(target: &str) -> NavigationDiagnostic {
    NavigationDiagnostic::capture(
        NavigationKind::HttpLocation,
        &Url::parse("https://portal.fixture.invalid/eportal/redirect.jsp?mode=history").unwrap(),
        &Url::parse(target).unwrap(),
        &Url::parse("https://portal.fixture.invalid/").unwrap(),
        &Url::parse("https://cas.fixture.invalid/").unwrap(),
        "GET",
        false,
    )
}

fn assert_fixed_detail(navigation: NavigationDiagnostic) {
    let values = [
        "http_location", "html_navigation", "browser_document", "get", "other", "true", "false",
        "http", "https", "portal", "cas", "captive", "root", "index", "redirect", "portal_main",
        "cas_login", "none", "exact_history", "default", "absent", "one_valid", "multiple",
        "invalid", "flow_only",
    ];
    let fields = [
        "scheme", "role", "host_role", "route", "query", "port", "userinfo", "fragment", "sid",
    ];
    let detail = navigation.detail();
    assert_eq!(detail.split_whitespace().count(), 21);
    for item in detail.split_whitespace() {
        let (key, value) = item.split_once('=').expect("fixed key/token pair");
        assert!(values.contains(&value), "unexpected navigation value {value}");
        let endpoint_key = key
            .strip_prefix("nav_source_")
            .or_else(|| key.strip_prefix("nav_target_"));
        assert!(
            ["nav_kind", "nav_method", "nav_body"].contains(&key)
                || endpoint_key.is_some_and(|field| fields.contains(&field)),
            "unexpected navigation key {key}"
        );
    }
}

#[test]
fn known_navigation_categories_do_not_imply_permission_or_same_host_origin() {
    let navigation =
        capture("http://portal.fixture.invalid/portal/portal-main?sessionId=private-sid");
    let value = serde_json::to_value(navigation).unwrap();
    assert_eq!(value["kind"], "http_location");
    assert_eq!(value["method"], "get");
    assert_eq!(value["has_body"], false);
    assert_eq!(value["source"]["scheme"], "https");
    assert_eq!(value["source"]["role"], "portal");
    assert_eq!(value["source"]["host_role"], "portal");
    assert_eq!(value["source"]["route"], "redirect");
    assert_eq!(value["source"]["query"], "exact_history");
    assert_eq!(value["source"]["sid"], "absent");
    assert_eq!(value["target"]["scheme"], "http");
    assert_eq!(value["target"]["role"], "other");
    assert_eq!(value["target"]["host_role"], "portal");
    assert_eq!(value["target"]["route"], "portal_main");
    assert_eq!(value["target"]["query"], "other");
    assert_eq!(value["target"]["port"], "default");
    assert_eq!(value["target"]["sid"], "one_valid");
    assert_fixed_detail(navigation);
}

#[test]
fn same_portal_http_and_outside_http_have_distinct_host_evidence_without_raw_hosts() {
    let same = capture(concat!(
        "http://portal.fixture.invalid/portal/portal-main",
        "?sessionId=same-private-sid"
    ));
    let outside = capture(concat!(
        "http://outside.fixture.invalid/portal/portal-main",
        "?sessionId=same-private-sid"
    ));
    let same_value = serde_json::to_value(same).unwrap();
    let outside_value = serde_json::to_value(outside).unwrap();
    for value in [&same_value, &outside_value] {
        assert_eq!(value["target"]["scheme"], "http");
        assert_eq!(value["target"]["port"], "default");
        assert_eq!(value["target"]["role"], "other");
        assert_eq!(value["target"]["route"], "portal_main");
        assert_eq!(value["target"]["sid"], "one_valid");
    }
    assert_eq!(same_value["target"]["host_role"], "portal");
    assert_eq!(outside_value["target"]["host_role"], "other");
    assert!(same.detail().contains("nav_target_host_role=portal"));
    assert!(outside.detail().contains("nav_target_host_role=other"));
    for navigation in [same, outside] {
        let public = format!(
            "{} {:?} {}",
            serde_json::to_value(navigation).unwrap(),
            navigation,
            navigation.detail()
        );
        for private in [
            "portal.fixture.invalid",
            "outside.fixture.invalid",
            "same-private-sid",
            "http://",
        ] {
            assert!(!public.contains(private));
        }
        assert_fixed_detail(navigation);
    }
}

#[test]
fn only_exact_routes_queries_and_configured_origins_receive_named_categories() {
    for (target, role, route, port) in [
        ("https://portal.fixture.invalid/", "portal", "root", "default"),
        ("https://portal.fixture.invalid/eportal/index.jsp", "portal", "index", "default"),
        ("https://cas.fixture.invalid/authserver/login", "cas", "cas_login", "default"),
        ("https://124.124.124.124/", "captive", "root", "default"),
        ("https://portal.fixture.invalid:8443/", "other", "root", "other"),
        ("https://portal.fixture.invalid.outside.invalid/", "other", "root", "default"),
        ("https://portal.fixture.invalid/dynamic/authserver/login", "portal", "other", "default"),
        ("https://portal.fixture.invalid/portal/%70ortal-main", "portal", "other", "default"),
        ("https://portal.fixture.invalid/portal/portal-main/private", "portal", "other", "default"),
    ] {
        let navigation = capture(target);
        let value = serde_json::to_value(navigation).unwrap();
        assert_eq!(value["target"]["role"], role);
        assert_eq!(value["target"]["route"], route);
        assert_eq!(value["target"]["port"], port);
        assert_fixed_detail(navigation);
    }
    for (query, expected) in [
        ("mode=history", "exact_history"),
        ("%6dode=history", "other"),
        ("mode=%68istory", "other"),
        ("mode=history&mode=history", "other"),
        ("mode=history&private=secret", "other"),
        ("", "other"),
    ] {
        let navigation = capture(&format!("https://portal.fixture.invalid/?{query}"));
        assert_eq!(serde_json::to_value(navigation).unwrap()["target"]["query"], expected);
    }
}

#[test]
fn sid_shapes_cover_duplicates_encoded_keys_and_control_characters_without_values() {
    for (query, expected) in [
        ("private=secret", "absent"),
        ("sessionId=private-sid", "one_valid"),
        ("%73essionId=private-encoded-sid", "one_valid"),
        ("sessionId=same&sessionId=same", "multiple"),
        ("sessionId=first&sessionId=second", "multiple"),
        ("sessionId=same&%73essionId=same", "multiple"),
        ("sessionId=one&flowSessionId=two", "multiple"),
        ("flowSessionId=same&flowSessionId=same", "multiple"),
        ("sessionId=", "invalid"),
        ("sessionId=private%00sid", "invalid"),
        ("sessionId=private%0Asid", "invalid"),
        ("sessionId=private%0D%0Asid", "invalid"),
        ("sessionId=private%C2%85sid", "invalid"),
        ("flowSessionId=private-flow", "flow_only"),
        ("flowSessionId=", "invalid"),
    ] {
        let navigation = capture(&format!("https://portal.fixture.invalid/?{query}"));
        assert_eq!(serde_json::to_value(navigation).unwrap()["target"]["sid"], expected);
        assert_fixed_detail(navigation);
    }
    let secret = "x".repeat(1025);
    let navigation = capture(&format!("https://portal.fixture.invalid/?sessionId={secret}"));
    assert_eq!(serde_json::to_value(navigation).unwrap()["target"]["sid"], "invalid");
    assert!(!navigation.detail().contains(&secret));
}

#[test]
fn malicious_url_material_is_absent_from_serialization_debug_and_detail() {
    let source = Url::parse(
        "https://portal.fixture.invalid/dynamic/fixture-source-path?ticket=fixture-source-ticket",
    )
    .unwrap();
    let target = Url::parse(concat!(
        "https://fixture-user:fixture-password@portal.fixture.invalid",
        "/dynamic/fixture-target-path?sessionId=fixture-session",
        "&ticket=fixture-ticket&userId=fixture-account#fixture-fragment",
    ))
    .unwrap();
    for kind in [
        NavigationKind::HttpLocation,
        NavigationKind::HtmlNavigation,
        NavigationKind::BrowserDocument,
    ] {
        let navigation = NavigationDiagnostic::capture(
            kind,
            &source,
            &target,
            &Url::parse("https://portal.fixture.invalid/").unwrap(),
            &Url::parse("https://cas.fixture.invalid/").unwrap(),
            "POST fixture-method-secret\r\nCookie: fixture-cookie",
            true,
        );
        let value = serde_json::to_value(navigation).unwrap();
        assert_eq!(value["target"]["userinfo"], true);
        assert_eq!(value["target"]["fragment"], true);
        assert_eq!(value["target"]["route"], "other");
        assert_eq!(value["method"], "other");
        assert_eq!(value["has_body"], true);
        let public = format!("{} {:?} {}", value, navigation, navigation.detail());
        for private in [
            "fixture-user", "fixture-password", "fixture-source-path", "fixture-source-ticket",
            "fixture-target-path", "fixture-session", "fixture-ticket", "fixture-account",
            "fixture-fragment", "fixture-method-secret", "fixture-cookie", "portal.fixture.invalid",
            "cas.fixture.invalid", "sessionId", "userId", "Cookie", "https://",
        ] {
            assert!(!public.contains(private), "navigation leaked {private}");
        }
        assert_fixed_detail(navigation);
    }
    for target in [
        "https://192.0.2.71/dynamic/private-ip-path?ticket=private-ip-ticket",
        "file:///private/fixture-file?sessionId=fixture-file-secret",
        "javascript:fixture-private-script",
    ] {
        let navigation = capture(target);
        let public = format!(
            "{} {:?} {}",
            serde_json::to_value(navigation).unwrap(),
            navigation,
            navigation.detail()
        );
        for private in [
            "192.0.2.71",
            "private-ip-path",
            "private-ip-ticket",
            "fixture-file",
            "fixture-private-script",
        ] {
            assert!(!public.contains(private));
        }
        assert_fixed_detail(navigation);
    }
}

#[test]
fn empty_query_fragment_and_method_categories_match_policy_boundaries() {
    let source = Url::parse("https://portal.fixture.invalid/?").unwrap();
    let target = Url::parse("https://portal.fixture.invalid/#").unwrap();
    let portal = Url::parse("https://portal.fixture.invalid/").unwrap();
    let cas = Url::parse("https://cas.fixture.invalid/").unwrap();
    for (method, expected) in [
        ("GET", "get"),
        ("get", "other"),
        ("GeT", "other"),
        ("POST", "other"),
        ("GET\n", "other"),
    ] {
        let navigation = NavigationDiagnostic::capture(
            NavigationKind::HtmlNavigation,
            &source,
            &target,
            &portal,
            &cas,
            method,
            false,
        );
        let value = serde_json::to_value(navigation).unwrap();
        assert_eq!(value["source"]["query"], "other");
        assert_eq!(value["target"]["query"], "none");
        assert_eq!(value["source"]["fragment"], false);
        assert_eq!(value["target"]["fragment"], true);
        assert_eq!(value["method"], expected);
        assert_fixed_detail(navigation);
    }
}

#[tokio::test]
async fn public_operation_wrapper_preserves_navigation_and_existing_categories() {
    let navigation = capture("https://portal.fixture.invalid/?sessionId=fixture-secret");
    let error = AuthError::new(OPERATION_ERROR, "fixture-private-error")
        .at(DiagnosticStage::CasNavigation)
        .because(DiagnosticReason::RedirectBlocked)
        .with_navigation(navigation);
    let error = crate::diagnostic::operation(DiagnosticOperation::Info, async {
        Err::<(), AuthError>(error)
    })
    .await
    .unwrap_err();
    assert_eq!(error.code, OPERATION_ERROR);
    assert_eq!(error.diagnostic().operation, DiagnosticOperation::Info);
    assert_eq!(error.diagnostic().stage, DiagnosticStage::CasNavigation);
    assert_eq!(error.diagnostic().reason, DiagnosticReason::RedirectBlocked);
    assert_eq!(error.diagnostic().navigation, Some(navigation));
    assert!(!serde_json::to_string(&error.diagnostic()).unwrap().contains("fixture-"));
}

#[test]
fn optional_navigation_preserves_none_json_copy_and_original_error_categories() {
    fn copy_value<T: Copy>(value: T) -> T {
        value
    }
    let plain = AuthError::new(QUERY_ERROR, "fixture-private-error");
    assert!(copy_value(plain.diagnostic()).navigation.is_none());
    assert_eq!(
        serde_json::to_value(plain.diagnostic()).unwrap(),
        json!({"operation":"unknown","stage":"unknown","reason":"unknown"})
    );
    let navigation = copy_value(capture(
        "https://portal.fixture.invalid/?sessionId=fixture-secret",
    ));
    let mut original = AuthError::new(OPERATION_ERROR, "fixture-private-error")
        .at(DiagnosticStage::CasNavigation)
        .because(DiagnosticReason::RedirectBlocked);
    original.diagnostic.operation = DiagnosticOperation::SwitchService;
    let error = original
        .with_navigation(navigation)
        .at(DiagnosticStage::Verification)
        .or_reason(DiagnosticReason::Network);
    assert_eq!(error.code, OPERATION_ERROR);
    assert_eq!(error.diagnostic().operation, DiagnosticOperation::SwitchService);
    assert_eq!(error.diagnostic().stage, DiagnosticStage::CasNavigation);
    assert_eq!(error.diagnostic().reason, DiagnosticReason::RedirectBlocked);
    assert_eq!(copy_value(error.diagnostic()).navigation, Some(navigation));
    let public = serde_json::to_string(&error.diagnostic()).unwrap();
    assert!(!public.contains("fixture-secret"));
    assert!(!public.contains("fixture-private-error"));
    assert!(!public.contains("portal.fixture.invalid"));
    assert!(serde_json::from_str::<Value>(&public).unwrap()["navigation"].is_object());
}
