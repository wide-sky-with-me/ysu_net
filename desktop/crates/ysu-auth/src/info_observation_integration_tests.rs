use super::*;

fn assert_info_verification_error(error: &AuthError, reason: DiagnosticReason) {
    assert_eq!(error.code, QUERY_ERROR);
    assert_eq!(error.diagnostic().operation, DiagnosticOperation::Info);
    assert_eq!(error.diagnostic().stage, DiagnosticStage::Verification);
    assert_eq!(error.diagnostic().reason, reason);
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

#[tokio::test]
async fn library_info_observation_rechecks_actual_identity_in_the_same_session() {
    let mut f = Fixture::new();
    f.config.username.clear();
    f.config.password.clear();
    f.mutate(|state| {
        state.online = Some("中国联通".into());
        state.owner = "external-account".into();
    });
    let observation = f.client().info_observation().await.unwrap();
    assert_eq!(observation.status.user, "external-account");
    assert_eq!(observation.status.service.as_deref(), Some("中国联通"));
    assert_eq!(observation.status.ip, "192.0.2.1");
    assert_eq!(f.count("/portal/portal-main"), 1);
    assert_eq!(f.count("/eportal/adaptor/getOnlineUserInfo"), 2);
    assert_eq!(f.count("/eportal/operator/getAccountInfo"), 1);
    assert_eq!(f.count("/eportal/network/"), 0);
    {
        let state = f.state.lock().unwrap();
        let reads: Vec<_> = state
            .requests
            .iter()
            .filter(|request| {
                request
                    .path
                    .starts_with("/eportal/adaptor/getOnlineUserInfo")
                    || request.path.starts_with("/eportal/operator/getAccountInfo")
            })
            .collect();
        assert_eq!(reads.len(), 3);
        assert_eq!(reads[0].method, "GET");
        assert_eq!(reads[1].method, "POST");
        assert_eq!(reads[2].method, "GET");
        for request in [reads[0], reads[2]] {
            assert!(request.path.contains("sessionId=fixture-session"));
        }
        let account: Value = serde_json::from_slice(&reads[1].body).unwrap();
        assert_eq!(account["sessionId"], "fixture-session");
    }
    assert_eq!(f.client().info().await.unwrap(), observation.info);
}

#[tokio::test]
async fn library_info_observation_rejects_changed_identity_or_failed_postcheck() {
    for case in 0..3 {
        let f = Fixture::new();
        f.mutate(|state| {
            state.online = Some("校园网".into());
            match case {
                0 => state.race_at = Some((2, "校园网".into(), "external-account".into())),
                1 => state.race_at = Some((2, "中国移动".into(), "fixture-user".into())),
                _ => state.state_failure_at = Some(2),
            }
        });
        let client = f.client();
        let error = if case == 2 {
            client.info().await.unwrap_err()
        } else {
            client.info_observation().await.unwrap_err()
        };
        let reason = if case == 2 {
            DiagnosticReason::StateUnrecognized
        } else {
            DiagnosticReason::IdentityMismatch
        };
        assert_info_verification_error(&error, reason);
        assert_eq!(f.count("/portal/portal-main"), 1);
        assert_eq!(f.count("/eportal/adaptor/getOnlineUserInfo"), 2);
        assert_eq!(f.count("/eportal/operator/getAccountInfo"), 1);
        assert_eq!(f.count("/eportal/network/"), 0);
    }
}

#[tokio::test]
async fn library_info_observation_preserves_partial_online_data() {
    let f = Fixture::new();
    f.mutate(|state| {
        state.state_override = Some(json!({"data":{"portalOnlineUserInfo":{
            "result":"success", "service":"校园网", "userId":"external-account"
        }}}));
    });
    let observation = f.client().info_observation().await.unwrap();
    assert!(observation.status.online);
    assert_eq!(observation.status.user, "external-account");
    assert!(observation.status.ip.is_empty());
    assert_eq!(f.count("/eportal/adaptor/getOnlineUserInfo"), 2);
    assert_eq!(f.count("/eportal/operator/getAccountInfo"), 1);
    assert_eq!(f.client().info().await.unwrap(), observation.info);
}

#[tokio::test]
async fn library_info_observation_offline_and_initial_failure_never_read_account() {
    let f = Fixture::new();
    let observation = f.client().info_observation().await.unwrap();
    assert!(!observation.status.online);
    assert_eq!(
        observation.info,
        json!({"online":false,"fields":[],"items":[]})
    );
    assert_eq!(f.count("/eportal/adaptor/getOnlineUserInfo"), 1);
    assert_eq!(f.count("/eportal/operator/getAccountInfo"), 0);

    let f = Fixture::new();
    f.mutate(|state| state.state_failure_at = Some(1));
    let error = f.client().info_observation().await.unwrap_err();
    assert_eq!(error.code, QUERY_ERROR);
    assert_eq!(error.diagnostic().operation, DiagnosticOperation::Info);
    assert_eq!(error.diagnostic().stage, DiagnosticStage::OnlineState);
    assert_eq!(f.count("/eportal/adaptor/getOnlineUserInfo"), 1);
    assert_eq!(f.count("/eportal/operator/getAccountInfo"), 0);
}
