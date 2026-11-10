//! Read-only self-service portal (`/self`) plus device kick-off.
//!
//! The portal is a separate OAuth2 client (`custom-self`) that shares the CAS
//! identity but keeps its own session. Login delegates back to
//! `cer.ysu.edu.cn` through `/cas-sso/clientredirect`, landing on the classic CAS
//! form `protocol::api_cas_login` already drives — only `service` differs.
//!
//! Contract verified against the live portal on 2026-11-09/10: cookie-only auth
//! (no Bearer token, no request-body encryption).
//!
//! Decision: .agents/notes/proposals/desktop/2026-11-09-self-service-protocol.md
use crate::{
    diagnostic::at,
    protocol,
    transport::{Operation, Transport},
    AuthError, Config, DiagnosticReason as Reason, DiagnosticStage as Stage,
};
use serde::{Deserialize, Serialize};
use serde_json::json;
use std::collections::HashMap;
use std::sync::OnceLock;
use std::time::{Duration, Instant};

const CALLBACK: &str = "login/oauth2/code/custom-self";
const SELF_INDEX: &str = "self/index";
const DEVICES: &str = "sam/api/userself/devices";
const PACKAGE: &str = "sam/api/userself/package/overview";
const FLOW: &str = "sam/api/userself/package/flow";
const REMEMBER: &str = "sam/api/userself/rememberService/current";
const KICK: &str = "sam/api/userself/devices/kick-offline/batch";

/// The portal updates its online list asynchronously; a single immediate re-read
/// reports a false failure. Bounded retries mirror the CLI behaviour.
const VERIFY_ATTEMPTS: u32 = 4;
const VERIFY_PAUSE_MS: u64 = 3_000;

/// Process-local session cache.
///
/// Repeated reads inside one application run must not re-run a password login:
/// unified auth freezes the client IP after a burst of full logins. The cache is
/// deliberately in memory only — persisting session cookies would need a
/// `cookie_store` feature change and would leave live tickets on disk, which the
/// CLI accepts for its own cache but the desktop does not need.
const SESSION_TTL: Duration = Duration::from_secs(1_800);

fn sessions() -> &'static tokio::sync::Mutex<HashMap<String, (Instant, Transport)>> {
    static CACHE: OnceLock<tokio::sync::Mutex<HashMap<String, (Instant, Transport)>>> =
        OnceLock::new();
    CACHE.get_or_init(|| tokio::sync::Mutex::new(HashMap::new()))
}

fn session_key(config: &Config, local: bool) -> String {
    format!("{}|{}|{local}", config.base, config.username)
}

/// Drop one cached session (used when a read proves it no longer works).
pub(crate) async fn forget_session(config: &Config, local: bool) {
    sessions().lock().await.remove(&session_key(config, local));
}

/// One entry from `onlineDevices` / `offlineDevices`.
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct SelfDevice {
    #[serde(default)]
    pub device_name: String,
    #[serde(default)]
    pub device_type: String,
    #[serde(default)]
    pub user_mac: String,
    #[serde(default)]
    pub user_ipv4: Option<String>,
    #[serde(default)]
    pub online_duration: String,
    #[serde(default)]
    pub auth_type: String,
    #[serde(default)]
    pub current_device: bool,
    #[serde(default)]
    pub unified_authentication: bool,
    /// Portal identifier; never rendered, used for the kick request and checks.
    #[serde(default)]
    pub online_user_uuid: String,
    /// Filled from the group the device came from, not from the portal JSON.
    #[serde(default)]
    pub online: bool,
}

#[derive(Clone, Debug, Default, Deserialize)]
#[serde(rename_all = "camelCase")]
struct DeviceGroups {
    #[serde(default)]
    online_devices: Vec<SelfDevice>,
    #[serde(default)]
    offline_devices: Vec<SelfDevice>,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct SelfFlow {
    pub name: String,
    pub total: String,
    pub left: String,
    pub percent: Option<f64>,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct SelfPackage {
    pub package: String,
    pub rule: String,
    pub period: String,
    pub used: String,
    pub percent: Option<f64>,
    pub balance: String,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct SelfRemember {
    pub remembered: Option<bool>,
    pub service: String,
    pub expires: String,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct SelfSnapshot {
    pub devices: Vec<SelfDevice>,
    pub online: usize,
    pub package: SelfPackage,
    pub flow: Vec<SelfFlow>,
    pub remember: SelfRemember,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct SelfKick {
    pub kicked: Vec<String>,
    pub online_before: usize,
    pub online_after: usize,
    pub devices: Vec<SelfDevice>,
}

/// Cookie-only client for the self-service portal.
pub(crate) struct SelfService {
    http: Transport,
}

impl SelfService {
    /// Open a client with a usable `/self` session, reusing the cached one.
    pub async fn open(config: &Config, local: bool, op: &Operation) -> Result<Self, AuthError> {
        let key = session_key(config, local);
        let cached = {
            let guard = sessions().lock().await;
            guard
                .get(&key)
                .filter(|(saved, _)| saved.elapsed() < SESSION_TTL)
                .map(|(_, transport)| transport.clone())
        };
        if let Some(transport) = cached {
            if authorised(&transport, op).await {
                return Ok(Self { http: transport });
            }
            forget_session(config, local).await;
        }

        let mut http = Transport::new(config, local)
            .map_err(|e| e.at(Stage::Config).or_reason(Reason::ConfigInvalid))?;
        Self::login(&mut http, config, op).await?;
        {
            let mut guard = sessions().lock().await;
            guard.retain(|_, (saved, _)| saved.elapsed() < SESSION_TTL);
            guard.insert(key, (Instant::now(), http.clone()));
        }
        Ok(Self { http })
    }

    /// Log in through the delegated CAS chain and land on `/self`.
    async fn login(http: &mut Transport, config: &Config, op: &Operation) -> Result<(), AuthError> {
        let seed = at(Stage::CasNavigation, async {
            let reply = http.get(http.endpoint(SELF_INDEX)?, op).await?;
            reply.ensure_success()?;
            Ok::<_, AuthError>(reply)
        })
        .await?;
        if is_self_page(&seed.url) {
            return Ok(());
        }
        let service = match seed_service(&seed.url, &http.base) {
            Some(url) => url,
            None => http.endpoint(CALLBACK)?.to_string(),
        };
        let url = at(
            Stage::CasNavigation,
            protocol::cas_login_url_with(http, op, &service),
        )
        .await?;
        protocol::api_cas_login(http, url, config, op).await?;
        if !authorised(http, op).await {
            return Err(AuthError::interaction("自助服务登录后仍未进入自助服务页")
                .at(Stage::CasNavigation)
                .or_reason(Reason::ResponseInvalid));
        }
        Ok(())
    }

    fn index_url(&self) -> Result<url::Url, AuthError> {
        self.http.endpoint(SELF_INDEX)
    }

    async fn post(
        &self,
        path: &str,
        body: &serde_json::Value,
        op: &Operation,
    ) -> Result<serde_json::Value, AuthError> {
        let url = self.http.endpoint(path)?;
        let referer = self.index_url().ok();
        let mut headers = self.http.api_headers(&url, referer.as_ref());
        headers.remove("isportal");
        headers.insert(
            "clienttype",
            reqwest::header::HeaderValue::from_static("self"),
        );
        headers.insert(
            reqwest::header::CONTENT_TYPE,
            reqwest::header::HeaderValue::from_static("application/json;charset=UTF-8"),
        );
        let bytes = serde_json::to_vec(body).map_err(|_| AuthError::query("请求编码失败"))?;
        let reply = self
            .http
            .once(reqwest::Method::POST, url, headers, Some(bytes), op)
            .await?;
        // State-changing calls never follow redirects, so a 3xx here means the
        // portal bounced us to the login page: the session is gone.
        if (300..400).contains(&reply.status) {
            return Err(AuthError::interaction("自助服务会话已失效，请重新读取")
                .at(Stage::CasNavigation)
                .or_reason(Reason::SessionMissing));
        }
        reply.ensure_success()?;
        let payload = reply.json().map_err(|_| {
            AuthError::query("自助服务响应格式异常")
                .at(Stage::Unknown)
                .or_reason(Reason::ResponseInvalid)
        })?;
        if payload["code"] != json!(200) {
            return Err(AuthError::query("自助服务接口业务结果未确认")
                .at(Stage::Unknown)
                .or_reason(Reason::ResponseInvalid));
        }
        Ok(payload)
    }

    async fn devices(&self, op: &Operation) -> Result<Vec<SelfDevice>, AuthError> {
        let payload = self.post(DEVICES, &json!({}), op).await?;
        let groups: DeviceGroups =
            serde_json::from_value(payload["data"].clone()).map_err(|_| {
                AuthError::query("自助服务设备响应结构异常")
                    .at(Stage::Unknown)
                    .or_reason(Reason::ResponseInvalid)
            })?;
        let mut rows = Vec::new();
        for mut device in groups.online_devices {
            device.online = true;
            rows.push(device);
        }
        for mut device in groups.offline_devices {
            device.online = false;
            rows.push(device);
        }
        Ok(rows)
    }

    pub async fn snapshot(&self, op: &Operation) -> Result<SelfSnapshot, AuthError> {
        let devices = self.devices(op).await?;
        let online = devices.iter().filter(|d| d.online).count();

        let package = parse_package(&self.post(PACKAGE, &json!({}), op).await?)?;
        let flow = parse_flow(&self.post(FLOW, &json!({}), op).await?)?;
        let remember = parse_remember(&self.post(REMEMBER, &json!({}), op).await?)?;

        Ok(SelfSnapshot {
            devices,
            online,
            package,
            flow,
            remember,
        })
    }

    /// Kick one device by 1-based index, or every online device with `all`.
    pub async fn kick(&self, op: &Operation, selector: &str) -> Result<SelfKick, AuthError> {
        let before = self.devices(op).await?;
        let targets = select(&before, selector)?;
        let online_before = before.iter().filter(|d| d.online).count();

        let mut kicked = Vec::new();
        for device in &targets {
            // Mirror the portal rule: kicking yourself keeps the SSO session so
            // you can log back in; kicking another device ends its SSO too.
            let unified = !(device.unified_authentication && device.current_device);
            self.post(
                KICK,
                &json!({
                    "onlineUserUuids": [device.online_user_uuid.clone()],
                    "kickUnifiedAuthOffline": unified,
                }),
                op,
            )
            .await?;
            kicked.push(device.online_user_uuid.clone());
        }

        let (after, still) = self.await_offline(op, &kicked).await?;
        if !still.is_empty() {
            return Err(AuthError::interaction("下线请求已提交，但仍有设备显示在线")
                .at(Stage::Verification)
                .or_reason(Reason::StateUnrecognized));
        }
        Ok(SelfKick {
            kicked,
            online_before,
            online_after: after.iter().filter(|d| d.online).count(),
            devices: after,
        })
    }

    async fn await_offline(
        &self,
        op: &Operation,
        uuids: &[String],
    ) -> Result<(Vec<SelfDevice>, Vec<String>), AuthError> {
        let mut last = Vec::new();
        let mut still: Vec<String> = uuids.to_vec();
        for attempt in 0..VERIFY_ATTEMPTS {
            let devices = self.devices(op).await?;
            let online: Vec<&str> = devices
                .iter()
                .filter(|d| d.online)
                .map(|d| d.online_user_uuid.as_str())
                .collect();
            still = uuids
                .iter()
                .filter(|u| online.contains(&u.as_str()))
                .cloned()
                .collect();
            last = devices;
            if still.is_empty() {
                return Ok((last, still));
            }
            if attempt + 1 < VERIFY_ATTEMPTS {
                let pause = Duration::from_millis(VERIFY_PAUSE_MS);
                // Do not sleep past the operation deadline; a read after that
                // would fail anyway and only delay the error.
                if op.remaining().map(|left| left <= pause).unwrap_or(true) {
                    break;
                }
                tokio::time::sleep(pause).await;
            }
        }
        Ok((last, still))
    }
}

pub(crate) fn is_self_page(url: &url::Url) -> bool {
    (url.path() == "/self" || url.path().starts_with("/self/"))
        && !url.path().contains("/cas-sso/")
}

pub(crate) fn seed_service(seed_url: &url::Url, base: &url::Url) -> Option<String> {
    let raw = protocol::query(seed_url, "service")?;
    let parsed = url::Url::parse(&raw).ok()?;
    (parsed.origin() == base.origin()
        && parsed.username().is_empty()
        && parsed.password().is_none())
    .then_some(raw)
}

/// One lightweight GET decides whether a session still reaches `/self`.
async fn authorised(http: &Transport, op: &Operation) -> bool {
    let Ok(url) = http.endpoint(SELF_INDEX) else {
        return false;
    };
    match at(Stage::CasNavigation, http.get(url, op)).await {
        Ok(page) => page.status == 200 && is_self_page(&page.url),
        Err(_) => false,
    }
}

pub(crate) fn parse_package(payload: &serde_json::Value) -> Result<SelfPackage, AuthError> {
    let Some(data) = payload.get("data") else {
        return Err(AuthError::query("自助服务套餐响应结构异常")
            .at(Stage::Unknown)
            .or_reason(Reason::ResponseInvalid));
    };
    if data.is_null() {
        return Ok(SelfPackage {
            package: String::new(),
            rule: String::new(),
            period: String::new(),
            used: String::new(),
            percent: None,
            balance: String::new(),
        });
    }
    if !data.is_object() {
        return Err(AuthError::query("自助服务套餐响应结构异常")
            .at(Stage::Unknown)
            .or_reason(Reason::ResponseInvalid));
    }
    Ok(SelfPackage {
        package: text_of(&data["policyInfo"]["packageName"]),
        rule: text_of(&data["policyInfo"]["periodAndTimeOrFlowDetail"]),
        period: text_of(&data["periodInfo"]["dateRangeDesc"]),
        used: text_of(&data["usedInfo"]["usedFreeDesc"]),
        percent: data["usedInfo"]["flowUsingPercentages"].as_f64(),
        balance: text_of(&data["accountInfo"]["currentFee"]),
    })
}

pub(crate) fn parse_flow(payload: &serde_json::Value) -> Result<Vec<SelfFlow>, AuthError> {
    let Some(data) = payload.get("data") else {
        return Err(AuthError::query("自助服务流量响应结构异常")
            .at(Stage::Unknown)
            .or_reason(Reason::ResponseInvalid));
    };
    if data.is_null() {
        return Ok(Vec::new());
    }
    if !data.is_object() {
        return Err(AuthError::query("自助服务流量响应结构异常")
            .at(Stage::Unknown)
            .or_reason(Reason::ResponseInvalid));
    }
    let mut rows = Vec::new();
    if let Some(groups) = data["availableFreeItems"].as_array() {
        for group in groups {
            let Some(items) = group["chargeItems"].as_array() else {
                continue;
            };
            for item in items {
                rows.push(SelfFlow {
                    name: text_of(&item["name"]),
                    total: text_of(&item["totalFreeValueDesc"]),
                    left: text_of(&item["leftFreeValueDesc"]),
                    percent: item["usingPercentages"].as_f64(),
                });
            }
        }
    }
    Ok(rows)
}

pub(crate) fn parse_remember(payload: &serde_json::Value) -> Result<SelfRemember, AuthError> {
    let data = &payload["data"];
    if !data.is_object() {
        return Ok(SelfRemember {
            remembered: None,
            service: String::new(),
            expires: String::new(),
        });
    }
    Ok(SelfRemember {
        remembered: data["remembered"].as_bool(),
        service: text_of(&data["service"]),
        expires: text_of(&data["expirationDate"]),
    })
}

pub(crate) fn text_of(value: &serde_json::Value) -> String {
    match value {
        serde_json::Value::String(s) => s.trim().to_string(),
        serde_json::Value::Number(n) => n.to_string(),
        _ => String::new(),
    }
}

/// Resolve `all` or a 1-based index against the list just rendered.
pub(crate) fn select(devices: &[SelfDevice], selector: &str) -> Result<Vec<SelfDevice>, AuthError> {
    let wanted = selector.trim();
    if wanted.eq_ignore_ascii_case("all") || wanted == "全部" {
        let rows: Vec<SelfDevice> = devices
            .iter()
            .filter(|d| d.online && !d.online_user_uuid.is_empty())
            .cloned()
            .collect();
        if rows.is_empty() {
            return Err(AuthError::query("没有可下线的在线设备"));
        }
        return Ok(rows);
    }
    let index: usize = wanted
        .parse()
        .map_err(|_| AuthError::query("设备编号无法识别"))?;
    if index == 0 || index > devices.len() {
        return Err(AuthError::query("设备编号超出范围"));
    }
    let device = &devices[index - 1];
    if !device.online {
        return Err(AuthError::query("该设备当前不在线"));
    }
    if device.online_user_uuid.is_empty() {
        return Err(AuthError::query("该设备缺少门户标识"));
    }
    Ok(vec![device.clone()])
}
