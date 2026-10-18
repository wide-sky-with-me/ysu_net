//! Native Portal/CAS authentication. No sidecar, persisted sessions or credential logging.
//! Decision: .agents/notes/proposals/desktop/2026-10-14-rust-desktop.md
mod browser;
#[cfg(windows)]
mod browser_process;
mod cookies;
mod crypto;
mod presentation;
mod protocol;
mod quota;
mod transport;

use serde::{Deserialize, Serialize};
use std::{fmt, sync::Arc, time::Duration};
use tokio::{sync::Mutex, time::Instant};
use transport::{Operation, Transport};

pub use browser::system_chromium as browser_path;
pub use quota::{classify_quota, Quota, QuotaState};
pub const SERVICES: [&str; 4] = ["校园网", "中国移动", "中国联通", "中国电信"];
pub const QUERY_ERROR: i32 = 2;
pub const OPERATION_ERROR: i32 = 3;
pub const INTERACTION_ERROR: i32 = 4;

#[derive(Clone, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct Config {
    pub username: String,
    pub password: String,
    pub service: String,
    pub backend: String,
    pub base: String,
    pub cas_host: String,
    pub verify_tls: bool,
    pub check_interval: u64,
    pub retry_interval: u64,
    pub max_retry_interval: u64,
    pub operation_timeout: u64,
}

impl Default for Config {
    fn default() -> Self {
        Self {
            username: String::new(),
            password: String::new(),
            service: SERVICES[0].into(),
            backend: "api".into(),
            base: "https://auth1.ysu.edu.cn".into(),
            cas_host: "https://cer.ysu.edu.cn".into(),
            verify_tls: true,
            check_interval: 15,
            retry_interval: 30,
            max_retry_interval: 900,
            operation_timeout: 180,
        }
    }
}

// Config serialization is for the caller's protected configuration store, not diagnostics.
impl fmt::Debug for Config {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("Config")
            .field("credentials", &"<redacted>")
            .field("service", &self.service)
            .field("backend", &self.backend)
            .finish_non_exhaustive()
    }
}

impl Config {
    pub fn validate(&self) -> Result<(), AuthError> {
        self.validate_transport(false)
    }

    fn validate_transport(&self, local: bool) -> Result<(), AuthError> {
        if !SERVICES.contains(&self.service.as_str()) {
            return Err(AuthError::query(
                "服务须为校园网、中国移动、中国联通或中国电信",
            ));
        }
        if !matches!(self.backend.as_str(), "api" | "browser") {
            return Err(AuthError::query("认证后端须为 api 或 browser"));
        }
        for value in [&self.base, &self.cas_host] {
            let u = url::Url::parse(value)
                .map_err(|_| AuthError::query("门户和统一认证地址须为有效 HTTPS URL"))?;
            let scheme_ok =
                u.scheme() == "https" || (local && u.scheme() == "http" && is_loopback(&u));
            if !scheme_ok
                || u.host_str().is_none()
                || !u.username().is_empty()
                || u.password().is_some()
                || u.query().is_some()
                || u.fragment().is_some()
            {
                return Err(AuthError::query(
                    "门户和统一认证地址须为不含凭据与查询参数的 HTTPS URL",
                ));
            }
            if local && !is_loopback(&u) {
                return Err(AuthError::query("测试 transport 仅接受本地回环地址"));
            }
        }
        for n in [
            self.check_interval,
            self.retry_interval,
            self.max_retry_interval,
            self.operation_timeout,
        ] {
            if !(1..=86400).contains(&n) {
                return Err(AuthError::query("时间间隔须为 1 至 86400 秒的整数"));
            }
        }
        if self.max_retry_interval < self.retry_interval {
            return Err(AuthError::query("最大重试间隔须大于或等于重试间隔"));
        }
        if self.username.len() > 256
            || self.password.len() > 4096
            || self.username.trim() != self.username
            || self.username.chars().any(char::is_control)
        {
            return Err(AuthError::query("账号或密码格式异常"));
        }
        Ok(())
    }

    fn require_credentials(&self) -> Result<(), AuthError> {
        if self.username.is_empty() || self.password.is_empty() {
            Err(AuthError::interaction("请先配置账号和密码"))
        } else {
            Ok(())
        }
    }
}

pub(crate) fn is_loopback(u: &url::Url) -> bool {
    match u.host() {
        Some(url::Host::Ipv4(ip)) => ip.is_loopback(),
        Some(url::Host::Ipv6(ip)) => ip.is_loopback(),
        // Do not trust a DNS name to resolve to loopback in fixture mode.
        _ => false,
    }
}

#[derive(Clone, Serialize)]
pub struct AuthError {
    pub code: i32,
    pub message: String,
}

impl AuthError {
    pub(crate) fn query(message: &str) -> Self {
        Self {
            code: QUERY_ERROR,
            message: message.into(),
        }
    }
    pub(crate) fn operation(message: &str) -> Self {
        Self {
            code: OPERATION_ERROR,
            message: message.into(),
        }
    }
    pub(crate) fn interaction(message: &str) -> Self {
        Self {
            code: INTERACTION_ERROR,
            message: message.into(),
        }
    }
    pub(crate) fn timeout() -> Self {
        Self::query("操作超过时限，请重新查询连接状态")
    }
}
impl fmt::Display for AuthError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.message)
    }
}
impl fmt::Debug for AuthError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        fmt::Display::fmt(self, f)
    }
}
impl std::error::Error for AuthError {}

#[derive(Clone, Serialize, Debug)]
pub struct Status {
    pub online: bool,
    pub service: Option<String>,
    pub user: String,
    pub ip: String,
    pub message: String,
}

/// Calls on the same client are serialized. No credentials are required for status/info.
/// Each public operation has one deadline including queueing and bounded recovery.
pub struct AuthClient {
    config: Config,
    local: bool,
    lock: Arc<Mutex<()>>,
}

impl AuthClient {
    pub fn new(config: Config) -> Result<Self, AuthError> {
        config.validate()?;
        Ok(Self {
            config,
            local: false,
            lock: Arc::new(Mutex::new(())),
        })
    }

    /// Explicit fixture escape hatch; never enabled by a config field or UI parameter.
    #[cfg(any(test, feature = "local-fixtures"))]
    pub fn new_local_fixture(config: Config) -> Result<Self, AuthError> {
        config.validate_transport(true)?;
        Ok(Self {
            config,
            local: true,
            lock: Arc::new(Mutex::new(())),
        })
    }

    fn operation(&self) -> Operation {
        Operation::new(Instant::now() + Duration::from_secs(self.config.operation_timeout))
    }

    async fn session(&self, op: &Operation) -> Result<protocol::Session, AuthError> {
        let http = Transport::new(&self.config, self.local)?;
        protocol::Session::open(http, &self.config, op).await
    }

    pub async fn status(&self) -> Result<Status, AuthError> {
        let op = self.operation();
        let _guard = op.run(self.lock.lock()).await?;
        self.session(&op)
            .await?
            .snapshot(&op)
            .await
            .map(|v| v.status)
    }

    pub async fn info(&self) -> Result<serde_json::Value, AuthError> {
        let op = self.operation();
        let _guard = op.run(self.lock.lock()).await?;
        let session = self.session(&op).await?;
        let online = session.snapshot(&op).await?;
        if !online.status.online {
            return Ok(serde_json::json!({"online":false,"fields":[],"items":[]}));
        }
        let account = session.account(&op).await?;
        let mut summary = presentation::summary(&online.payload, &account);
        summary["quota"] = serde_json::to_value(classify_quota(&account))
            .expect("quota contains only an enum and text");
        op.remaining()?;
        Ok(summary)
    }

    /// Rotation evidence: only this configured online account/service, checked twice.
    /// One deadline includes lock queueing, navigation, account lookup and verification.
    pub async fn verified_info(&self) -> Result<serde_json::Value, AuthError> {
        self.config.require_credentials()?;
        let op = self.operation();
        let _guard = op.run(self.lock.lock()).await?;
        let session = self.session(&op).await?;
        let before = session.snapshot(&op).await?;
        self.require_current_account(&before)?;
        let account = session.account(&op).await?;
        quota::require_account(&account)?;
        let after = session.snapshot(&op).await?;
        self.require_current_account(&after)?;
        let mut summary = presentation::summary(&after.payload, &account);
        summary["quota"] = serde_json::to_value(classify_quota(&account))
            .expect("quota contains only an enum and text");
        op.remaining()?;
        Ok(summary)
    }

    fn require_current_account(&self, snapshot: &protocol::Snapshot) -> Result<(), AuthError> {
        let info = &snapshot.payload["data"]["portalOnlineUserInfo"];
        for envelope in [&snapshot.payload, &snapshot.payload["data"], info] {
            if !quota::successful_envelope(envelope) {
                return Err(AuthError::query("在线状态含未知或冲突的业务结果"));
            }
        }
        snapshot.require_target(&self.config.username, &self.config.service)?;
        // Snapshot's display parser ignores unrecognized service labels. Evidence must not.
        for field in ["realServiceName", "service"] {
            if info
                .get(field)
                .is_some_and(|value| value.as_str() != Some(&self.config.service))
            {
                return Err(AuthError::query("在线原始服务未知或与当前配置不一致"));
            }
        }
        Ok(())
    }

    pub async fn login(&self) -> Result<Status, AuthError> {
        self.config.require_credentials()?;
        let op = self.operation();
        let _guard = op.run(self.lock.lock()).await?;
        let mut session = self.session(&op).await?;
        session.login(&self.config, &self.config.service, &op).await
    }

    pub async fn logout(&self) -> Result<Status, AuthError> {
        self.config.require_credentials()?;
        let op = self.operation();
        let _guard = op.run(self.lock.lock()).await?;
        let mut session = self.session(&op).await?;
        session.logout(&self.config, &op).await
    }

    pub async fn switch_service(&self, target: &str) -> Result<Status, AuthError> {
        if !SERVICES.contains(&target) {
            return Err(AuthError::query("目标服务无效"));
        }
        self.config.require_credentials()?;
        let op = self.operation();
        let _guard = op.run(self.lock.lock()).await?;
        let mut session = self.session(&op).await?;
        let before = session.snapshot(&op).await?;
        before.require_owner(&self.config.username)?;
        let previous = before.status.service.clone();
        if previous.as_deref() == Some(target) {
            return Ok(before.status);
        }

        // Reserve a third of the total budget for at most one recovery, not an unbounded retry.
        let primary = if previous.is_some() {
            op.fraction(2, 3)
        } else {
            op.clone()
        };
        let changed = previous.is_some();
        let result: Result<Status, AuthError> = async {
            if changed {
                session.logout(&self.config, &primary).await?;
            }
            session.login(&self.config, target, &primary).await?;
            let verified = session.snapshot(&primary).await?;
            verified.require_target(&self.config.username, target)?;
            Ok(verified.status)
        }
        .await;
        match result {
            Ok(value) => Ok(value),
            Err(mut error) => {
                if let Some(previous) = previous {
                    let restored = session.restore(&self.config, &previous, &op).await;
                    error.message.push_str(if restored {
                        "；已独立确认恢复原服务"
                    } else {
                        "；原连接恢复未确认，请查询状态"
                    });
                }
                Err(error)
            }
        }
    }
}

#[cfg(test)]
mod quota_tests;
#[cfg(test)]
mod tests;
