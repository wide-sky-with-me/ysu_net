//! Public diagnostics contain only fixed categories, never error text or network data.
use crate::{AuthError, NavigationDiagnostic};
use serde::Serialize;
use std::future::Future;

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum DiagnosticOperation {
    #[default]
    Unknown,
    Status,
    Info,
    Login,
    Logout,
    SwitchService,
    VerifiedInfo,
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum DiagnosticStage {
    #[default]
    Unknown,
    Config,
    Queue,
    PortalNavigation,
    OnlineState,
    AccountInfo,
    FlowNode,
    CasNavigation,
    CasForm,
    Captcha,
    CasSubmit,
    CasCallback,
    ServiceSelect,
    UserOnline,
    LogoutPrepare,
    OfflineSubmit,
    Verification,
    Recovery,
    BrowserInit,
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum DiagnosticReason {
    #[default]
    Unknown,
    ConfigInvalid,
    Deadline,
    Network,
    RedirectBlocked,
    RedirectLimit,
    HttpRejected,
    ResponseInvalid,
    SessionMissing,
    StateUnrecognized,
    BusinessRejected,
    IdentityMismatch,
    InteractionRequired,
    BrowserProtocol,
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize)]
pub struct AuthDiagnostic {
    pub operation: DiagnosticOperation,
    pub stage: DiagnosticStage,
    pub reason: DiagnosticReason,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub navigation: Option<NavigationDiagnostic>,
}

pub(crate) async fn at<T>(
    stage: DiagnosticStage,
    future: impl Future<Output = Result<T, AuthError>>,
) -> Result<T, AuthError> {
    future.await.map_err(|error| error.at(stage))
}

pub(crate) async fn operation<T>(
    operation: DiagnosticOperation,
    future: impl Future<Output = Result<T, AuthError>>,
) -> Result<T, AuthError> {
    future.await.map_err(|mut error| {
        error.diagnostic.operation = operation;
        error
    })
}
