use crate::{
    presentation, protocol::Snapshot, AuthError, DiagnosticReason, DiagnosticStage, Status,
};
use serde_json::{json, Value};

/// Account information bound to the actual status observed during its read.
/// This metadata is internal observation evidence, not an additional IPC info field.
/// Missing fields stay missing; matching reads are not an atomic snapshot or proof
/// against hidden identity changes or an intervening change back to the same tuple.
#[derive(Clone, Debug)]
pub struct InfoObservation {
    pub status: Status,
    pub info: Value,
}

impl InfoObservation {
    /// Compare actual observations, never configured credentials or display fields.
    pub fn matches_status(&self, status: &Status) -> bool {
        self.status.online == status.online
            && self.status.user == status.user
            && self.status.service == status.service
            && self.status.ip == status.ip
    }

    pub(crate) fn offline(status: Status) -> Self {
        Self {
            status,
            info: json!({"online":false,"fields":[],"items":[]}),
        }
    }

    pub(crate) fn from_snapshots(
        before: &Snapshot,
        account: &Value,
        after: Snapshot,
    ) -> Result<Self, AuthError> {
        let observation = Self {
            status: after.status,
            info: Value::Null,
        };
        if !before.status.online || !observation.matches_status(&before.status) {
            return Err(verification_error());
        }
        let mut info = presentation::summary(&after.payload, account);
        info["quota"] = serde_json::to_value(crate::classify_quota(account))
            .expect("quota contains only an enum and text");
        Ok(Self {
            info,
            ..observation
        })
    }
}

pub(crate) fn verification_error() -> AuthError {
    AuthError::query("账户读取期间连接身份发生变化，请重新读取")
        .because(DiagnosticReason::IdentityMismatch)
        .at(DiagnosticStage::Verification)
}

pub(crate) fn postcheck_error(error: AuthError) -> AuthError {
    let diagnostic = error.diagnostic();
    let fixed = AuthError::query("账户读取后的连接状态未能核验，请重新读取")
        .because(diagnostic.reason)
        .at(DiagnosticStage::Verification);
    match diagnostic.navigation {
        Some(navigation) => fixed.with_navigation(navigation),
        None => fixed,
    }
}
