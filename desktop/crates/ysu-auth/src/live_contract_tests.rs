//! Synthetic contracts derived from the 123 trace; no live response data.
use super::*;
use crate::protocol::check_action;
use crate::transport::Reply;

fn cases(source: &str) -> Vec<Value> {
    let fixture: Value = serde_json::from_str(source).unwrap();
    assert_eq!(fixture["version"], 1);
    fixture["cases"].as_array().unwrap().clone()
}

#[test]
fn captcha_is_scoped_to_password_login_and_standalone_challenges() {
    let http = Transport::new(&Config::default(), false).unwrap();
    let page = http.cas_endpoint("authserver/login").unwrap();
    for case in cases(include_str!(
        "../../../../tests/fixtures/cas-login-methods.json"
    )) {
        let form = LoginForm::parse(case["html"].as_str().unwrap(), &page, &http).unwrap();
        assert_eq!(
            form.captcha,
            case["captcha"].as_bool().unwrap(),
            "{}",
            case["id"]
        );
    }
}

#[tokio::test]
async fn failed_service_authentication_never_activates_the_session() {
    for case in cases(include_str!(
        "../../../../tests/fixtures/portal-action-results.json"
    )) {
        let reply = Reply {
            url: Url::parse("https://portal.fixture.invalid/eportal/network/serviceLogin").unwrap(),
            status: 200,
            headers: HeaderMap::new(),
            body: Vec::new(),
            chain: Vec::new(),
        };
        let expected = case["code"].as_i64().unwrap() as i32;
        let result = check_action(&reply, &case["payload"]);
        assert_eq!(
            result.err().map_or(0, |error| error.code),
            expected,
            "{}",
            case["id"]
        );
        if expected == 0 {
            continue;
        }
        let fixture = Fixture::new();
        fixture.mutate(|state| state.select_override = Some(case["payload"].clone()));
        let error = fixture.client().login().await.unwrap_err();
        assert_eq!(error.code, expected, "{}", case["id"]);
        assert_eq!(error.diagnostic().stage, DiagnosticStage::ServiceSelect);
        assert_eq!(fixture.count("/eportal/network/serviceLogin"), 1);
        assert_eq!(fixture.count("/eportal/network/userOnline"), 0);
    }
}

#[tokio::test]
async fn mobile_cas_login_and_logout_accept_observed_envelopes_and_fresh_status_sessions() {
    let mut fixture = Fixture::new();
    fixture.config.service = "中国移动".into();
    fixture.mutate(|state| {
        state.cas_required = true;
        state.bootstrap_index_empty = true;
        state.observed_action_envelopes = true;
        state.callback_body = Some(
            "<html><script>if (false) location='/noSupport';</script><body>Portal</body></html>"
                .into(),
        );
    });
    let client = fixture.client();
    assert!(!client.status().await.unwrap().online);
    let login_start = fixture.state.lock().unwrap().requests.len();
    let logged_in = client.login().await.unwrap();
    assert!(logged_in.online);
    assert_eq!(logged_in.service.as_deref(), Some("中国移动"));
    let verification_start = fixture.state.lock().unwrap().requests.len();
    let independent = fixture.client().status().await.unwrap();
    assert!(independent.online);
    assert_eq!(independent.user, fixture.config.username);
    assert_eq!(independent.service.as_deref(), Some("中国移动"));
    let logout_start = fixture.state.lock().unwrap().requests.len();
    assert!(!client.logout().await.unwrap().online);
    assert!(!fixture.client().status().await.unwrap().online);

    let state = fixture.state.lock().unwrap();
    let login = &state.requests[login_start..verification_start];
    let at = |path: &str, method: &str| {
        login
            .iter()
            .position(|r| {
                r.method == method
                    && Url::parse(&format!("http://fixture{}", r.path))
                        .unwrap()
                        .path()
                        == path
            })
            .unwrap()
    };
    assert!(at("/eportal/index.jsp", "GET") < at("/eportal/redirect.jsp", "GET"));
    assert!(at("/eportal/redirect.jsp", "GET") < at("/portal/portal-main", "GET"));
    assert!(at("/cas-sso/login", "GET") < at("/cas-sso/clientredirect", "GET"));
    assert!(at("/authserver/login", "POST") < at("/eportal/network/serviceLogin", "POST"));
    assert!(
        at("/eportal/network/serviceLogin", "POST") < at("/eportal/network/userOnline", "POST")
    );
    assert_eq!(
        login
            .iter()
            .filter(|r| r.method == "POST" && r.path.starts_with("/authserver/login"))
            .count(),
        1
    );
    assert!(!state.requests[verification_start]
        .headers
        .contains_key("cookie"));
    let logout = &state.requests[logout_start..];
    let sam = logout
        .iter()
        .position(|r| {
            r.path
                .starts_with("/sam/api/protected/guest/enableConfig/info")
        })
        .unwrap();
    let offline = logout
        .iter()
        .position(|r| r.method == "POST" && r.path.starts_with("/eportal/network/offline"))
        .unwrap();
    assert!(sam < offline);
    assert_eq!(
        logout
            .iter()
            .filter(|r| r.method == "POST" && r.path.starts_with("/eportal/network/offline"))
            .count(),
        1
    );
}

#[test]
fn cas_form_does_not_treat_resources_or_script_dictionaries_as_a_challenge() {
    let http = Transport::new(&Config::default(), false).unwrap();
    let page = http.cas_endpoint("authserver/login").unwrap();
    let body = format!("{FORM}<script>const route='/noSupport'; const message='安全验证';</script><style>.noSupport {{ display:none }}</style><!-- 风险验证 -->");
    assert!(LoginForm::parse(&body, &page, &http).is_ok());
    for warning in [
        "IP被冻结",
        "访问被拒绝",
        "安全验证",
        "风险验证",
        "访问频繁",
        "noSupport",
    ] {
        assert!(LoginForm::parse(&format!("{body}<h1>{warning}</h1>"), &page, &http).is_err());
    }
}

#[tokio::test]
async fn actual_callback_document_challenges_still_stop_before_service_actions() {
    for body in [
        "<title>IP被冻结</title>",
        "<h1>安全验证</h1>",
        "<p>noSupport</p>",
        "<div>风险<span>验证</span></div>",
        "<p>Portal</p><p>安全验证</p>",
    ] {
        let fixture = Fixture::new();
        fixture.mutate(|state| {
            state.cas_required = true;
            state.callback_body = Some(body.into());
        });
        let error = fixture.client().login().await.unwrap_err();
        assert_eq!(error.code, INTERACTION_ERROR);
        assert_eq!(error.diagnostic().stage, DiagnosticStage::CasCallback);
        assert_eq!(
            error.diagnostic().reason,
            DiagnosticReason::BusinessRejected
        );
        assert_eq!(fixture.count("/eportal/network/serviceLogin"), 0);
        assert_eq!(fixture.count("/eportal/network/userOnline"), 0);
    }
}
