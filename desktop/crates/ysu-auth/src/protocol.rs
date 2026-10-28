use crate::{
    browser::Browser,
    crypto::encrypt_password,
    diagnostic::at,
    presentation::text,
    transport::{Operation, Reply, Transport, REDIRECT_LIMIT},
    AuthError, Config, DiagnosticReason as Reason, DiagnosticStage as Stage, NavigationKind,
    Status, SERVICES,
};
use reqwest::{
    header::{HeaderMap, HeaderValue, CONTENT_TYPE, LOCATION},
    Method,
};
use scraper::{ElementRef, Html, Selector};
use serde_json::{json, Value};
use std::collections::BTreeMap;
use url::Url;

const ONLINE: &str = "eportal/adaptor/getOnlineUserInfo";
const NODE: &str = "eportal/workFlow/getCurrentNode";
const SELECT: &str = "eportal/network/serviceLogin";
const USER_ONLINE: &str = "eportal/network/userOnline";
const OFFLINE: &str = "eportal/network/offline";
const ACCOUNT: &str = "eportal/operator/getAccountInfo";
const SAM: &str = "sam/api/protected/guest/enableConfig/info";

pub(crate) struct Snapshot {
    pub status: Status,
    pub payload: Value,
    owner: Option<String>,
}
impl Snapshot {
    pub fn parse(payload: Value) -> Result<Self, AuthError> {
        let info = &payload["data"]["portalOnlineUserInfo"];
        if !crate::quota::successful_envelope(&payload)
            || !crate::quota::successful_envelope(&payload["data"])
        {
            return Err(AuthError::query("在线状态含未知或冲突的业务结果"));
        }
        let online = if info["result"] == "success" {
            true
        } else if info["message"] == "dx.failed.user.offline" {
            false
        } else {
            return Err(AuthError::query("在线状态响应未知，暂不修改连接"));
        };
        let service = if online {
            if !crate::quota::successful_envelope(info)
                // A JSON null raw label is absent; other unknown values stay errors.
                || info.get("realServiceName").is_some_and(|value| {
                    !value.is_null()
                        && value.as_str().is_none_or(|name| !SERVICES.contains(&name))
                })
            {
                return Err(AuthError::query(
                    "在线响应业务结果或原始服务未知，暂不修改连接",
                ));
            }
            let names: Vec<&str> = [info["realServiceName"].as_str(), info["service"].as_str()]
                .into_iter()
                .flatten()
                .filter(|s| SERVICES.contains(s))
                .collect();
            if names.is_empty() || names.iter().any(|s| *s != names[0]) {
                return Err(AuthError::query(
                    "在线响应缺少唯一可识别的服务，暂不修改连接",
                ));
            }
            Some(names[0].to_owned())
        } else {
            None
        };
        // userName may be a display name: an explicit userId is authoritative.
        let owner = match info.get("userId") {
            Some(value) => value.as_str(),
            None => info["userName"].as_str(),
        }
        .filter(|value| !value.is_empty())
        .map(str::to_owned);
        let status = Status {
            online,
            service,
            user: text(&Value::String(owner.clone().unwrap_or_default())),
            ip: text(&info["userIp"]),
            message: if online {
                "已确认在线"
            } else {
                "已确认离线"
            }
            .into(),
        };
        Ok(Self {
            status,
            payload,
            owner,
        })
    }
    pub fn require_owner(&self, expected: &str) -> Result<(), AuthError> {
        if self.status.online && self.owner.as_deref() != Some(expected) {
            Err(
                AuthError::operation("在线账号与当前配置不一致或账号缺失，保留现有连接")
                    .because(Reason::IdentityMismatch)
                    .at(Stage::Verification),
            )
        } else {
            Ok(())
        }
    }
    pub fn require_target(&self, owner: &str, target: &str) -> Result<(), AuthError> {
        self.require_owner(owner)?;
        if !self.status.online || self.status.service.as_deref() != Some(target) {
            Err(
                AuthError::operation("实际在线服务与目标不一致，请显式切换服务")
                    .because(Reason::IdentityMismatch)
                    .at(Stage::Verification),
            )
        } else {
            Ok(())
        }
    }
}

pub(crate) struct Session {
    pub http: Transport,
    sid: String,
    last: Url,
    browser: Option<Browser>,
}
impl Session {
    pub async fn open(http: Transport, config: &Config, op: &Operation) -> Result<Self, AuthError> {
        at(Stage::PortalNavigation, async {
            if config.backend == "browser" {
                let mut browser = Browser::start(http.clone(), op)
                    .await
                    .map_err(|e| e.at(Stage::BrowserInit).or_reason(Reason::BrowserProtocol))?;
                let (sid, last) = browser.portal(op).await?;
                return Ok(Self {
                    http,
                    sid,
                    last,
                    browser: Some(browser),
                });
            }
            for path in ["eportal/index.jsp", "eportal/redirect.jsp", ""] {
                let mut url = http.endpoint(path)?;
                let mut hops = 0;
                loop {
                    let r = http.navigation_get(url, op).await?;
                    r.ensure_success()?;
                    hops += r.chain.len();
                    if hops > REDIRECT_LIMIT + 1 {
                        return Err(
                            AuthError::query("门户导航超过次数限制").because(Reason::RedirectLimit)
                        );
                    }
                    if let Some(sid) = sid_from_chain(&r.chain) {
                        return Ok(Self {
                            http,
                            sid,
                            last: r.url,
                            browser: None,
                        });
                    }
                    let Some(next) =
                        next_api_portal_navigation(&http, &r.text(), &r.url, op).await?
                    else {
                        break;
                    };
                    url = next;
                }
            }
            Err(AuthError::query("门户未返回有效会话，连接状态未知")
                .because(Reason::SessionMissing))
        })
        .await
    }

    pub async fn snapshot(&self, op: &Operation) -> Result<Snapshot, AuthError> {
        at(Stage::OnlineState, async {
            let mut url = self.http.endpoint(ONLINE)?;
            url.query_pairs_mut()
                .append_pair("sessionId", &self.sid)
                .append_pair("version", "ysu-rust-0.1")
                .append_pair("t", &timestamp());
            let r = self
                .http
                .follow(
                    Method::GET,
                    url.clone(),
                    self.http.api_headers(&url, Some(&self.last)),
                    None,
                    op,
                )
                .await?;
            r.ensure_success()?;
            let observed = Snapshot::parse(r.json()?).map_err(|e| e.or_reason(Reason::StateUnrecognized))?;
            op.trace.emit(crate::trace::TraceEvent::OnlineState {
                online: observed.status.online, service_known: observed.status.service.is_some(),
            });
            Ok(observed)
        })
        .await
    }
    async fn node(&self, op: &Operation) -> Result<String, AuthError> {
        at(Stage::FlowNode, async {
            let r = self
                .http
                .json_post(
                    NODE,
                    &json!({"sessionId":self.sid,"flowKey":"portal_auth"}),
                    Some(&self.last),
                    op,
                )
                .await?;
            r.ensure_success()?;
            let value = r.json()?;
            if !crate::quota::successful_envelope(&value)
                || !crate::quota::successful_envelope(&value["data"])
            {
                return Err(AuthError::query("门户流程节点业务结果未确认，暂不修改连接")
                    .because(Reason::BusinessRejected));
            }
            value["data"]["currentNodePath"]
                .as_str()
                .map(str::to_owned)
                .ok_or_else(|| {
                    AuthError::query("门户流程节点未知，暂不修改连接")
                        .because(Reason::StateUnrecognized)
                })
        })
        .await
    }
    pub async fn account(&self, op: &Operation) -> Result<Value, AuthError> {
        at(Stage::AccountInfo, async {
            let r = self
                .http
                .json_post(
                    ACCOUNT,
                    &json!({"sessionId":self.sid}),
                    Some(&self.last),
                    op,
                )
                .await?;
            r.ensure_success()?;
            let v = r.json()?;
            check_action(&r, &v)?;
            Ok(v)
        })
        .await
    }
    pub async fn login(
        &mut self,
        config: &Config,
        target: &str,
        op: &Operation,
    ) -> Result<Status, AuthError> {
        let initial = self.snapshot(op).await?;
        initial.require_owner(&config.username)?;
        if initial.status.online {
            initial.require_target(&config.username, target)?;
            return Ok(initial.status);
        }
        let mut node = self.node(op).await?;
        if node == "authenticate" {
            let url = at(Stage::CasNavigation, async {
                let mut seed = self.http.endpoint("cas-sso/login")?;
                let custom_page = query(&self.last, "customPageId").unwrap_or_default();
                seed.query_pairs_mut()
                    .append_pair("flowSessionId", &self.sid)
                    .append_pair("customPageId", &custom_page)
                    .append_pair("preview", "false")
                    .append_pair("appType", "normal")
                    .append_pair("language", "zh-CN")
                    .append_pair("timer", &timestamp());
                self.http.get(seed, op).await?.ensure_success()?;
                cas_login_url(&self.http, op).await
            })
            .await?;
            if let Some(browser) = self.browser.as_mut() {
                browser.cas_login(url, config, op).await.map_err(|e| {
                    e.at(Stage::CasNavigation)
                        .or_reason(Reason::BrowserProtocol)
                })?;
            } else {
                api_cas_login(&self.http, url, config, op).await?;
            }
            node = self.node(op).await?;
            if node == "authenticate" {
                return Err(AuthError::interaction(
                    "统一认证后仍要求登录，请检查账号密码、验证码或风控状态",
                )
                .at(Stage::FlowNode));
            }
        }
        if node == "serviceSelection" {
            // Check ownership again immediately before any state-changing Portal action.
            let before_select = self.snapshot(op).await?;
            before_select.require_owner(&config.username)?;
            if before_select.status.online {
                before_select.require_target(&config.username, target)?;
                return Ok(before_select.status);
            }
            at(Stage::ServiceSelect, async {
                let r = self
                    .http
                    .json_post(
                        SELECT,
                        &json!({"sessionId":self.sid,"service":target}),
                        Some(&self.last),
                        op,
                    )
                    .await?;
                r.ensure_success()?;
                check_action(&r, &r.json()?)
            })
            .await?;
            // A concurrent login must not be overwritten between selection and activation.
            let before_online = self.snapshot(op).await?;
            before_online.require_owner(&config.username)?;
            if before_online.status.online {
                before_online.require_target(&config.username, target)?;
                return Ok(before_online.status);
            }
            at(Stage::UserOnline, async {
                let r = self
                    .http
                    .json_post(
                        USER_ONLINE,
                        &json!({"sessionId":self.sid}),
                        Some(&self.last),
                        op,
                    )
                    .await?;
                r.ensure_success()?;
                check_action(&r, &r.json()?)
            })
            .await?;
        } else if !matches!(node.as_str(), "finish" | "online" | "userOnline") {
            return Err(AuthError::query("门户流程节点未知，暂不修改连接")
                .at(Stage::FlowNode)
                .because(Reason::StateUnrecognized));
        }
        self.wait_online(config, target, op).await
    }
    async fn wait_online(
        &self,
        config: &Config,
        target: &str,
        op: &Operation,
    ) -> Result<Status, AuthError> {
        at(Stage::Verification, async {
            loop {
                let current = self.snapshot(op).await?;
                current.require_owner(&config.username)?;
                if current.status.online {
                    current.require_target(&config.username, target)?;
                    return Ok(current.status);
                }
                if op.remaining()?.as_millis() <= 200 {
                    return Err(
                        AuthError::operation("登录超时，尚未独立确认目标账号与服务在线")
                            .because(Reason::Deadline),
                    );
                }
                op.pause().await?;
            }
        })
        .await
    }
    pub async fn logout(&mut self, config: &Config, op: &Operation) -> Result<Status, AuthError> {
        let initial = self.snapshot(op).await?;
        initial.require_owner(&config.username)?;
        if !initial.status.online {
            return Ok(initial.status);
        }
        self.prepare_logout(&initial.payload, op).await?;
        let checked = self.snapshot(op).await?;
        checked.require_owner(&config.username)?;
        if !checked.status.online {
            return Ok(checked.status);
        }
        at(Stage::OfflineSubmit, async {
            let url = self.http.endpoint(OFFLINE)?;
            let mut headers = self.http.offline_headers(&url, &self.last);
            headers.insert(
                CONTENT_TYPE,
                HeaderValue::from_static("application/json;charset=UTF-8"),
            );
            let body = serde_json::to_vec(&json!({"sessionId":self.sid}))
                .map_err(|_| AuthError::query("请求编码失败").because(Reason::ResponseInvalid))?;
            let r = self
                .http
                .once(Method::POST, url, headers, Some(body), op)
                .await?;
            r.ensure_success()?;
            check_action(&r, &r.json()?)
        })
        .await?;
        at(Stage::Verification, async {
            loop {
                let current = self.snapshot(op).await?;
                current.require_owner(&config.username)?;
                if !current.status.online {
                    return Ok(current.status);
                }
                if op.remaining()?.as_millis() <= 200 {
                    return Err(AuthError::operation("下线超时，独立查询仍显示在线")
                        .because(Reason::Deadline));
                }
                op.pause().await?;
            }
        })
        .await
    }
    async fn prepare_logout(&mut self, online: &Value, op: &Operation) -> Result<(), AuthError> {
        at(Stage::LogoutPrepare, async {
            let tl = terminal_url(&self.http, &self.last, online)?;
            self.http.get(tl, op).await?.ensure_success()?;
            let finish = self
                .http
                .endpoint("portal/entry/pc/finish;flowParams=undefined;from=")?;
            let r = self.http.get(finish, op).await?;
            r.ensure_success()?;
            self.last = r.url;
            let mut seed = self.http.endpoint(SAM)?;
            seed.query_pairs_mut()
                .append_pair("t", &timestamp())
                .append_pair("version", "ysu-rust-0.1");
            self.http.get(seed, op).await?.ensure_success()?;
            Ok(())
        })
        .await
    }
    pub async fn restore(&mut self, config: &Config, previous: &str, op: &Operation) -> bool {
        async {
            let current = self.snapshot(op).await?;
            current.require_owner(&config.username)?;
            if current.status.service.as_deref() == Some(previous) {
                return Ok::<_, AuthError>(true);
            }
            if current.status.online {
                self.logout(config, op).await?;
            }
            self.login(config, previous, op).await?;
            let verified = self.snapshot(op).await?;
            verified.require_target(&config.username, previous)?;
            Ok(true)
        }
        .await
        .unwrap_or(false)
    }
}

pub(crate) fn query(url: &Url, key: &str) -> Option<String> {
    url.query_pairs()
        .find(|(k, v)| k == key && !v.is_empty() && v.len() <= 1024)
        .map(|(_, v)| v.into_owned())
}
fn sid_from_chain(chain: &[Url]) -> Option<String> {
    chain
        .iter()
        .rev()
        .find_map(|u| query(u, "sessionId").or_else(|| query(u, "flowSessionId")))
}
fn timestamp() -> String {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis()
        .to_string()
}
fn selector(s: &str) -> Selector {
    Selector::parse(s).expect("constant selector")
}

/// Resolve HTML navigation only during the API portal bootstrap.
/// `from` is the terminal response URL of navigation_get's bodyless GET chain,
/// not the original entry URL before redirects. API/CAS requests do not use this.
pub(crate) async fn next_api_portal_navigation(
    http: &Transport,
    body: &str,
    from: &Url,
    op: &Operation,
) -> Result<Option<Url>, AuthError> {
    let Some(next) = next_navigation(body, from) else {
        return Ok(None);
    };
    http.resolve_portal_navigation(
        from,
        next,
        &Method::GET,
        false,
        NavigationKind::HtmlNavigation,
        op,
    )
    .await
    .map(Some)
}

pub(crate) fn next_navigation(body: &str, base: &Url) -> Option<Url> {
    let html = Html::parse_document(body);
    for e in html.select(&selector("meta[http-equiv]")) {
        if e.value()
            .attr("http-equiv")
            .is_some_and(|v| v.eq_ignore_ascii_case("refresh"))
        {
            if let Some(content) = e.value().attr("content") {
                if let Some((_, value)) = content.split_once('=') {
                    if let Ok(next) = base.join(value.trim().trim_matches(['\'', '"'])) {
                        return Some(next);
                    }
                }
            }
        }
    }
    let patterns = [
        r#"(?:window\.)?location(?:\.href|\.replace)?\s*=\s*["']([^"']+)["']"#,
        r#"(?:window\.)?location\.(?:replace|assign)\(\s*["']([^"']+)["']"#,
        r#"(https?://[^\s"'<>]+/(?:portal/portal-main|eportal/index\.jsp)\?[^\s"'<>]+)"#,
    ];
    for pattern in patterns {
        let re = regex::Regex::new(pattern).expect("constant regex");
        if let Some(m) = re.captures(body).and_then(|c| c.get(1)) {
            let decoded = m.as_str().replace("&amp;", "&");
            if let Ok(next) = base.join(&decoded) {
                return Some(next);
            }
        }
    }
    None
}

async fn cas_login_url(http: &Transport, op: &Operation) -> Result<Url, AuthError> {
    let mut url = http.endpoint("cas-sso/clientredirect")?;
    let service = http.endpoint("portal/entry/pc/authenticate;flowParams=undefined;from=")?;
    url.query_pairs_mut()
        .append_pair("client_name", "sidadapter")
        .append_pair("accept-language", "zh-CN")
        .append_pair("service", service.as_str());
    for hop in 0..=REDIRECT_LIMIT {
        if url.origin() == http.cas.origin() && url.path().ends_with("/authserver/login") {
            return Ok(url);
        }
        let r = http
            .once(Method::GET, url.clone(), HeaderMap::new(), None, op)
            .await?;
        if matches!(r.status, 301 | 302 | 303 | 307 | 308) {
            if hop == REDIRECT_LIMIT {
                break;
            }
            url = r
                .headers
                .get(LOCATION)
                .and_then(|v| v.to_str().ok())
                .and_then(|v| url.join(v).ok())
                .ok_or_else(|| AuthError::query("统一认证跳转缺少有效地址"))?;
            http.allowed(&url)?;
        } else {
            r.ensure_success()?;
            break;
        }
    }
    Err(AuthError::query("门户未返回有效统一认证登录地址"))
}

pub(crate) struct LoginForm {
    pub fields: BTreeMap<String, String>,
    pub salt: String,
    pub action: Url,
    pub captcha: bool,
}
impl LoginForm {
    pub fn parse(body: &str, page: &Url, http: &Transport) -> Result<Self, AuthError> {
        if risk_page(body) {
            return Err(AuthError::interaction("统一认证触发风控，请人工处理后重试"));
        }
        let html = Html::parse_document(body);
        let forms = selector("form");
        let inputs = selector("input");
        let score = |e: ElementRef<'_>| {
            e.select(&inputs)
                .map(|i| match i.value().attr("name") {
                    Some("username" | "password") => 3,
                    Some("execution") => 2,
                    _ => 0,
                })
                .sum::<u32>()
        };
        let form = html
            .select(&forms)
            .max_by_key(|e| score(*e))
            .filter(|e| score(*e) >= 6)
            .ok_or_else(|| {
                AuthError::interaction("统一认证登录表单缺失，请检查验证码或风控状态")
            })?;
        let mut fields = BTreeMap::new();
        for input in form.select(&inputs) {
            let attr = input.value();
            if attr.attr("disabled").is_some() {
                continue;
            }
            let kind = attr.attr("type").unwrap_or("").to_ascii_lowercase();
            if matches!(kind.as_str(), "button" | "submit" | "reset" | "file")
                || (matches!(kind.as_str(), "checkbox" | "radio") && attr.attr("checked").is_none())
            {
                continue;
            }
            if let Some(name) = attr.attr("name") {
                fields.insert(
                    name.into(),
                    attr.attr("value")
                        .unwrap_or(if matches!(kind.as_str(), "checkbox" | "radio") {
                            "on"
                        } else {
                            ""
                        })
                        .into(),
                );
            }
        }
        let salt = html
            .select(&selector("#pwdEncryptSalt"))
            .next()
            .and_then(|e| e.value().attr("value"))
            .filter(|s| matches!(s.trim().len(), 16 | 24 | 32))
            .ok_or_else(|| AuthError::interaction("统一认证加密参数缺失，请检查验证码或风控状态"))?
            .to_owned();
        let mut action = page
            .join(form.value().attr("action").unwrap_or(page.as_str()))
            .map_err(|_| AuthError::query("统一认证表单地址异常"))?;
        http.allowed(&action)?;
        if action.origin() != http.cas.origin() {
            return Err(AuthError::query("统一认证表单指向了其他站点"));
        }
        if query(&action, "service").is_none() {
            if let Some(service) = query(page, "service") {
                action.query_pairs_mut().append_pair("service", &service);
            }
        }
        // Other login methods reuse captchaDiv on the real CAS page.
        // Decision: .agents/notes/implemented/desktop/2026-10-27-offline-captive-bootstrap.md
        let captcha = html
            .select(&selector("#captchaDiv"))
            .filter(|e| {
                e.ancestors()
                    .filter_map(ElementRef::wrap)
                    .find(|ancestor| ancestor.value().name() == "form")
                    .is_none_or(|owner| owner.id() == form.id())
            })
            .any(|e| {
                let attr = e.value();
                !attr
                    .attr("class")
                    .unwrap_or("")
                    .split_whitespace()
                    .any(|s| s.contains("hide") || s.contains("hidden"))
                    && !attr
                        .attr("style")
                        .unwrap_or("")
                        .replace(' ', "")
                        .to_ascii_lowercase()
                        .contains("display:none")
                    && attr.attr("hidden").is_none()
            });
        Ok(Self {
            fields,
            salt,
            action,
            captcha,
        })
    }
}
fn risk_page(body: &str) -> bool {
    // Normal portal bundles reference /noSupport in scripts. Only document text
    // is evidence of a returned challenge; resource names are not a rejection.
    // Decision: .agents/notes/implemented/desktop/2026-10-28-cas-callback-risk-text.md
    let html = Html::parse_document(body);
    let mut content = String::new();
    let mut pending = html.root_element().children().rev().collect::<Vec<_>>();
    while let Some(node) = pending.pop() {
        if let Some(element) = ElementRef::wrap(node) {
            if matches!(
                element.value().name(),
                "script" | "style" | "noscript" | "template"
            ) {
                continue;
            }
            pending.extend(element.children().rev());
        } else if let Some(text) = node.value().as_text() {
            content.push_str(text);
        }
    }
    [
        "IP被冻结",
        "访问被拒绝",
        "安全验证",
        "风险验证",
        "访问频繁",
        "noSupport",
    ]
    .iter()
    .any(|s| content.contains(s))
}
fn bool_value(v: &Value) -> Option<bool> {
    v.as_bool()
        .or_else(|| match v.as_str()?.trim().to_ascii_lowercase().as_str() {
            "true" | "1" | "yes" => Some(true),
            "false" | "0" | "no" => Some(false),
            _ => None,
        })
}
pub(crate) async fn captcha_required(
    http: &Transport,
    page: &Url,
    username: &str,
    dom: bool,
    op: &Operation,
) -> Result<bool, AuthError> {
    at(Stage::Captcha, async {
        let mut u = http.cas_endpoint("authserver/checkNeedCaptcha.htl")?;
        u.query_pairs_mut()
            .append_pair("username", username)
            .append_pair("_", &timestamp());
        let r = http
            .follow(
                Method::GET,
                u.clone(),
                http.api_headers(&u, Some(page)),
                None,
                op,
            )
            .await?;
        r.ensure_success()?;
        let v = r.json().ok();
        let api = v.as_ref().and_then(|v| {
            bool_value(v).or_else(|| {
                ["isNeed", "needCaptcha", "isNeedCaptcha", "data", "result"]
                    .iter()
                    .find_map(|key| bool_value(&v[key]))
            })
        });
        // A visible challenge takes precedence over a stale false response.
        Ok(dom || api.unwrap_or(false))
    })
    .await
}
async fn api_cas_login(
    http: &Transport,
    url: Url,
    config: &Config,
    op: &Operation,
) -> Result<(), AuthError> {
    let page = at(Stage::CasNavigation, http.get(url, op)).await?;
    page.ensure_success()
        .map_err(|e| e.at(Stage::CasNavigation))?;
    let mut form = LoginForm::parse(&page.text(), &page.url, http)
        .map_err(|e| e.at(Stage::CasForm).or_reason(Reason::ResponseInvalid))?;
    if captcha_required(http, &page.url, &config.username, form.captcha, op).await? {
        return Err(
            AuthError::interaction("统一认证需要验证码，请人工处理后重试").at(Stage::Captcha),
        );
    }
    form.fields
        .insert("username".into(), config.username.clone());
    form.fields.insert(
        "password".into(),
        encrypt_password(&config.password, &form.salt)
            .map_err(|e| e.at(Stage::CasForm).or_reason(Reason::ResponseInvalid))?,
    );
    form.fields
        .entry("_eventId".into())
        .or_insert_with(|| "submit".into());
    form.fields
        .entry("cllt".into())
        .or_insert_with(|| "userNameLogin".into());
    form.fields
        .entry("dllt".into())
        .or_insert_with(|| "generalLogin".into());
    form.fields.entry("lt".into()).or_default();
    if form.fields.get("captcha").is_some_and(String::is_empty) {
        form.fields.remove("captcha");
    }
    let body = url::form_urlencoded::Serializer::new(String::new())
        .extend_pairs(form.fields.iter())
        .finish()
        .into_bytes();
    let mut headers = http.api_headers(&form.action, Some(&page.url));
    headers.remove("isportal");
    headers.insert(
        CONTENT_TYPE,
        HeaderValue::from_static("application/x-www-form-urlencoded"),
    );
    let r = at(Stage::CasSubmit, async {
        let r = http
            .once(Method::POST, form.action, headers, Some(body), op)
            .await?;
        if matches!(r.status, 429 | 500..=599) {
            return Err(AuthError::query("统一认证服务暂时不可用，请稍后重试")
                .because(Reason::HttpRejected));
        }
        if !matches!(r.status, 301 | 302 | 303) {
            return Err(AuthError::interaction(
                "统一认证未确认登录，请检查账号密码、验证码或风控状态",
            )
            .because(Reason::BusinessRejected));
        }
        Ok(r)
    })
    .await?;
    at(Stage::CasCallback, async {
        let next = r
            .headers
            .get(LOCATION)
            .and_then(|v| v.to_str().ok())
            .and_then(|v| r.url.join(v).ok())
            .ok_or_else(|| {
                AuthError::query("统一认证返回缺少有效跳转地址").because(Reason::ResponseInvalid)
            })?;
        let after = http.get(next, op).await?;
        after.ensure_success()?;
        if after.url.origin() != http.base.origin() {
            return Err(
                AuthError::interaction("统一认证未完成门户回跳，请人工处理后重试")
                    .because(Reason::RedirectBlocked),
            );
        }
        if risk_page(&after.text()) {
            return Err(
                AuthError::interaction("统一认证未完成门户回跳，请人工处理后重试")
                    .because(Reason::BusinessRejected),
            );
        }
        Ok(())
    })
    .await
}

pub(crate) fn check_action(r: &Reply, v: &Value) -> Result<(), AuthError> {
    if !v.is_object() {
        return Err(AuthError::operation("门户操作响应格式异常").because(Reason::ResponseInvalid));
    }
    for item in [v, &v["data"]] {
        if !item.is_object() {
            continue;
        }
        let messages = [item["message"].as_str(), item["authMessage"].as_str()];
        for msg in messages.into_iter().flatten() {
            if msg.contains("同时在线用户数量上限") {
                return Err(AuthError::interaction(
                    "运营商同时在线数量已达上限，请先在其他终端下线",
                ));
            }
            if [
                "账号密码错误",
                "用户名或密码错误",
                "验证码",
                "风控",
                "IP被冻结",
            ]
            .iter()
            .any(|term| msg.contains(term))
            {
                return Err(AuthError::interaction(
                    "运营商认证需要人工处理，请检查账号绑定、密码、验证码或风控状态",
                ));
            }
        }
        let rejected_online = item["online"] == false
            && messages
                .into_iter()
                .flatten()
                .any(|msg| msg.contains("认证失败"));
        if matches!(
            item["result"].as_str(),
            Some("fail" | "failed" | "failure" | "error")
        ) || item
            .get("authResult")
            .is_some_and(|value| value != "success")
            || item["success"] == false
            || rejected_online
            || item["code"].as_i64().is_some_and(|c| c != 0 && c != 200)
        {
            return Err(AuthError::operation("门户操作未被确认").because(Reason::BusinessRejected));
        }
    }
    if r.status != 200 {
        return Err(AuthError::operation("门户操作请求未被确认").because(Reason::HttpRejected));
    }
    Ok(())
}

fn terminal_url(http: &Transport, main: &Url, online: &Value) -> Result<Url, AuthError> {
    let keys = [
        "sessionId",
        "userIp",
        "ssid",
        "nasIp",
        "customPageId",
        "redirectUrl",
        "samPortalRedirectUrl",
        "clearIdentitySelect",
        "guestFlow",
    ];
    let mut params = serde_json::Map::new();
    let mut inner = url::form_urlencoded::Serializer::new(String::new());
    for key in keys {
        let val = query(main, key).unwrap_or_else(|| {
            match key {
                "clearIdentitySelect" => "true",
                "guestFlow" => "false",
                _ => "",
            }
            .into()
        });
        inner.append_pair(key, &val);
        params.insert(key.into(), Value::String(val));
    }
    let pu = &online["data"]["portalOnlineUserInfo"];
    let oi = json!({"result":pu["result"],"userIndex":pu["userIndex"]});
    let mut url = http.endpoint("portal/entry/pc/terminalLoad")?;
    url.query_pairs_mut()
        .append_pair("url", &format!("/entry?{}", inner.finish()))
        .append_pair("onlineInfo", &oi.to_string())
        .append_pair("routrQueryParams", &Value::Object(params).to_string());
    Ok(url)
}
