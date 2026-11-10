//! Selection and coercion rules for the self-service device list.
use crate::selfservice::{is_self_page, parse_flow, parse_package, seed_service, select, text_of};
use crate::SelfDevice;
use serde_json::json;
use url::Url;

fn device(index: u32, online: bool, current: bool, unified: bool) -> SelfDevice {
    SelfDevice {
        device_name: "我的设备".into(),
        device_type: if index == 1 { "电脑" } else { "手机" }.into(),
        user_mac: format!("02-00-00-00-00-0{index}"),
        user_ipv4: Some(format!("10.0.0.{index}")),
        online_duration: "0时01分".into(),
        auth_type: "无线标准Portal接入".into(),
        current_device: current,
        unified_authentication: unified,
        online_user_uuid: format!("uuid-{index}"),
        online,
    }
}

fn rows() -> Vec<SelfDevice> {
    vec![
        device(1, true, true, true),
        device(2, true, false, false),
        device(3, false, false, false),
    ]
}

#[test]
fn index_is_one_based() {
    let picked = select(&rows(), "1").unwrap();
    assert_eq!(picked.len(), 1);
    assert_eq!(picked[0].online_user_uuid, "uuid-1");
    let picked = select(&rows(), "2").unwrap();
    assert_eq!(picked[0].online_user_uuid, "uuid-2");
}

#[test]
fn all_keeps_only_online_devices() {
    let picked = select(&rows(), "all").unwrap();
    let ids: Vec<&str> = picked.iter().map(|d| d.online_user_uuid.as_str()).collect();
    assert_eq!(ids, ["uuid-1", "uuid-2"]);
}

#[test]
fn offline_target_is_refused() {
    let error = select(&rows(), "3").unwrap_err();
    assert!(error.message.contains("不在线"), "{}", error.message);
}

#[test]
fn bad_index_and_out_of_range_are_refused() {
    for selector in ["", "abc", "0", "9", "-1"] {
        assert!(select(&rows(), selector).is_err(), "accepted {selector}");
    }
}

#[test]
fn missing_portal_identifier_is_refused() {
    let mut devices = rows();
    devices[0].online_user_uuid.clear();
    let error = select(&devices, "1").unwrap_err();
    assert!(error.message.contains("门户标识"), "{}", error.message);
}

#[test]
fn empty_online_set_has_nothing_to_kick() {
    let devices = vec![device(3, false, false, false)];
    assert!(select(&devices, "all").is_err());
}

#[test]
fn text_coercion_never_invents_values() {
    assert_eq!(text_of(&json!("  10 GB ")), "10 GB");
    assert_eq!(text_of(&json!(0)), "0");
    assert_eq!(text_of(&json!(null)), "");
    assert_eq!(text_of(&json!(true)), "");
    assert_eq!(text_of(&json!({"a": 1})), "");
}

#[test]
fn device_deserializes_from_portal_shape() {
    let raw = json!({
        "deviceName": "我的设备", "deviceType": "手机", "userMac": "02-00-00-00-00-02",
        "userIpv4": null, "onlineDuration": "3时20分", "authType": "无线标准Portal接入",
        "currentDevice": false, "unifiedAuthentication": false,
        "onlineUserUuid": "uuid-x"
    });
    let parsed: SelfDevice = serde_json::from_value(raw).unwrap();
    assert_eq!(parsed.device_type, "手机");
    assert_eq!(parsed.user_ipv4, None);
    assert!(!parsed.online, "online 由分组决定，默认 false");
    assert_eq!(parsed.online_user_uuid, "uuid-x");
}

#[test]
fn null_package_and_flow_data_do_not_abort_device_read() {
    let pkg = parse_package(&json!({ "code": 200, "data": null })).unwrap();
    assert_eq!(pkg.package, "");
    assert_eq!(pkg.percent, None);
    let flow = parse_flow(&json!({ "code": 200, "data": null })).unwrap();
    assert!(flow.is_empty());

    assert!(parse_package(&json!({ "code": 200 })).is_err());
    assert!(parse_package(&json!({ "code": 200, "data": "x" })).is_err());
    assert!(parse_flow(&json!({ "code": 200 })).is_err());
    assert!(parse_flow(&json!({ "code": 200, "data": "x" })).is_err());
}

#[test]
fn seed_service_extracts_same_origin_oauth_callback_and_rejects_foreign() {
    let base = Url::parse("https://auth1.ysu.edu.cn/").unwrap();
    let oauth_cb = "https://auth1.ysu.edu.cn/cas-sso/oauth2.0/callbackAuthorize?client_id=20231026142058188-9037-986575215&redirect_uri=https%3A%2F%2Fauth1.ysu.edu.cn%2Flogin%252Foauth2%252Fcode%252Fcustom-self&response_type=code&client_name=CasOAuthClient";
    let mut seed = Url::parse("https://auth1.ysu.edu.cn/cas-sso/login").unwrap();
    seed.query_pairs_mut().append_pair("service", oauth_cb);
    assert_eq!(seed_service(&seed, &base).as_deref(), Some(oauth_cb));

    for bad in [
        "https://auth1.ysu.edu.cn/cas-sso/login",
        "https://auth1.ysu.edu.cn/cas-sso/login?service=https%3A%2F%2Foutside.invalid%2Fcb",
        "https://auth1.ysu.edu.cn/cas-sso/login?service=http%3A%2F%2Fauth1.ysu.edu.cn%2Fcb",
        "https://auth1.ysu.edu.cn/cas-sso/login?service=https%3A%2F%2Fuser%3Apass%40auth1.ysu.edu.cn%2Fcb",
    ] {
        let u = Url::parse(bad).unwrap();
        assert_eq!(seed_service(&u, &base), None, "accepted {bad}");
    }
}

#[test]
fn is_self_page_distinguishes_self_routes_from_cas_bounces() {
    let bounce = "https://auth1.ysu.edu.cn/cas-sso/login?service=https%3A%2F%2Fauth1.ysu.edu.cn%2Fself%2Findex";
    assert!(is_self_page(
        &Url::parse("https://auth1.ysu.edu.cn/self/index").unwrap()
    ));
    assert!(is_self_page(
        &Url::parse("https://auth1.ysu.edu.cn/self").unwrap()
    ));
    assert!(!is_self_page(&Url::parse(bounce).unwrap()));
    assert!(!is_self_page(
        &Url::parse("https://auth1.ysu.edu.cn/portal/portal-main").unwrap()
    ));
}
