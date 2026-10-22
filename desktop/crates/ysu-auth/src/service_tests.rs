use super::*;
use crate::protocol::Snapshot;
use serde_json::{json, Value};

#[derive(Deserialize)]
pub(super) struct ServiceCase {
    pub id: String,
    pub fields: Value,
    pub expected: Option<String>,
    pub bound: bool,
}
impl ServiceCase {
    pub fn online(&self, owner: &str) -> Value {
        let mut info = self.fields.clone();
        info["result"] = json!("success");
        info["userId"] = json!(owner);
        json!({"data":{"portalOnlineUserInfo":info}})
    }
}
pub(super) fn cases() -> Vec<ServiceCase> {
    #[derive(Deserialize)]
    struct Fixture {
        version: u32,
        cases: Vec<ServiceCase>,
    }
    let fixture: Fixture = serde_json::from_str(include_str!(
        "../../../../tests/fixtures/online-service.json"
    ))
    .unwrap();
    assert_eq!(fixture.version, 1);
    fixture.cases
}

#[test]
fn shared_service_resolution_and_account_evidence_contract() {
    let mut ids = std::collections::BTreeSet::new();
    for case in cases() {
        assert!(ids.insert(case.id.clone()));
        let snapshot = Snapshot::parse(case.online("fixture-user"));
        if let Some(expected) = case.expected.as_ref() {
            let snapshot = snapshot.unwrap_or_else(|error| panic!("{}: {error}", case.id));
            assert_eq!(
                snapshot.status.service.as_ref(),
                Some(expected),
                "{}",
                case.id
            );
            let client = AuthClient::new(Config {
                username: "fixture-user".into(),
                service: expected.clone(),
                ..Config::default()
            })
            .unwrap();
            assert_eq!(
                client.require_current_account(&snapshot).is_ok(),
                case.bound,
                "{}",
                case.id
            );
        } else {
            assert_eq!(snapshot.err().unwrap().code, QUERY_ERROR, "{}", case.id);
        }
    }
}
