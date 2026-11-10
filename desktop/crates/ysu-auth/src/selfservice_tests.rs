//! Selection and coercion rules for the self-service device list.
use crate::selfservice::{select, text_of};
use crate::SelfDevice;
use serde_json::json;

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
