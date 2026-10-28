use super::*;

fn config() -> Config {
    Config {
        username: "private-user".into(),
        password: "private-password".into(),
        service: "中国移动".into(),
        ..Config::default()
    }
}

fn proof(online: bool, owner: bool, service: bool) -> Proof {
    Proof {
        online,
        service: "mobile",
        owner_matches_config: owner,
        service_matches_config: service,
    }
}

#[test]
fn input_rejects_unknown_arguments_large_json_insecure_transport_and_missing_credentials() {
    assert_eq!(Action::parse(&["login".into()]), Some(Action::Login));
    assert!(Action::parse(&[]).is_none());
    assert!(Action::parse(&["login".into(), "private-password".into()]).is_none());
    assert!(decode(&vec![b' '; INPUT_LIMIT as usize + 1], Action::Status).is_none());
    assert!(decode(br#"{"unknown":"private-password"}"#, Action::Status).is_none());
    assert!(decode(br#"{"verify_tls":false}"#, Action::Status).is_none());
    assert!(decode(br#"{"base":"http://127.0.0.1"}"#, Action::Status).is_none());
    assert!(decode(b"{}", Action::Login).is_none());
    assert!(decode(b"{}", Action::Logout).is_none());
    assert!(decode(b"{}", Action::Status).is_some());
}

#[test]
fn preconditions_exclude_idempotent_actions_and_foreign_connections_from_success_proofs() {
    assert_eq!(
        precondition(Action::Login, &proof(true, true, true)),
        Some(Outcome::ExpectedOffline)
    );
    assert_eq!(
        precondition(Action::Logout, &proof(false, false, false)),
        Some(Outcome::ExpectedOnline)
    );
    assert_eq!(
        precondition(Action::Logout, &proof(true, false, true)),
        Some(Outcome::IdentityMismatch)
    );
    assert_eq!(
        precondition(Action::Logout, &proof(true, true, false)),
        Some(Outcome::ServiceMismatch)
    );
    assert!(precondition(Action::Login, &proof(false, false, false)).is_none());
    assert!(precondition(Action::Logout, &proof(true, true, true)).is_none());
    assert!(precondition(Action::Status, &proof(true, false, false)).is_none());
}

#[test]
fn login_requires_actual_owner_and_service_and_logout_requires_actual_offline() {
    assert!(verified(Action::Login, &proof(true, true, true)));
    for after in [
        proof(false, true, true),
        proof(true, false, true),
        proof(true, true, false),
    ] {
        assert!(!verified(Action::Login, &after));
    }
    assert!(!verified(Action::Logout, &proof(true, true, true)));
    assert!(verified(Action::Logout, &proof(false, false, false)));
}

#[test]
fn serialized_results_never_include_identity_ip_messages_or_unknown_service_values() {
    let mut config = config();
    let status = Status {
        online: true,
        service: Some("private-service".into()),
        user: config.username.clone(),
        ip: "192.0.2.123".into(),
        message: "private-message".into(),
    };
    let mut report = Report::new(Some(Action::Login));
    report.before = Some(Proof::from_status(&status, &config));
    assert!(report.before.as_ref().unwrap().owner_matches_config);
    assert_eq!(report.before.as_ref().unwrap().service, "unknown");
    report.fail(AuthError::new(
        2,
        "private-error https://private.invalid/?ticket=private-ticket",
    ));
    let output = serde_json::to_string(&report).unwrap();
    for value in [
        "private-user",
        "private-password",
        "private-service",
        "192.0.2.123",
        "private-message",
        "private-error",
        "private-ticket",
        "private.invalid",
    ] {
        assert!(!output.contains(value));
    }
    config.username.clear();
    let empty = Status {
        user: String::new(),
        ..status
    };
    assert!(!Proof::from_status(&empty, &config).owner_matches_config);
}
