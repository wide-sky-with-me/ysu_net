use crate::{
    cookies::Jar, is_loopback, AuthError, Config, DiagnosticReason as Reason, NavigationDiagnostic,
    NavigationKind,
};
use reqwest::{
    cookie::CookieStore,
    header::{HeaderMap, HeaderValue, CONTENT_TYPE, COOKIE, LOCATION, SET_COOKIE},
    Method,
};
use std::{
    future::Future,
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc, Mutex,
    },
    time::Duration,
};
use tokio::time::{timeout_at, Instant};
use url::Url;

pub(crate) const RESPONSE_LIMIT: usize = 2 * 1024 * 1024;
pub(crate) const REDIRECT_LIMIT: usize = 16;
const HEADER_LIMIT: usize = 64 * 1024;

#[derive(Clone)]
pub(crate) struct Operation {
    pub deadline: Instant,
    pub(crate) trace: crate::trace::Context,
}
impl Operation {
    pub fn new(deadline: Instant) -> Self {
        Self { deadline, trace: crate::trace::Context::current() }
    }
    pub async fn run<F: Future>(&self, f: F) -> Result<F::Output, AuthError> {
        self.remaining()?;
        let result = timeout_at(self.deadline, f)
            .await
            .map_err(|_| AuthError::timeout())?;
        self.remaining()?;
        Ok(result)
    }
    pub fn remaining(&self) -> Result<Duration, AuthError> {
        self.deadline
            .checked_duration_since(Instant::now())
            .filter(|v| !v.is_zero())
            .ok_or_else(AuthError::timeout)
    }
    pub fn fraction(&self, n: u32, d: u32) -> Self {
        let now = Instant::now();
        Self { deadline: now + self.deadline.saturating_duration_since(now) * n / d, trace: self.trace.clone() }
    }
    pub async fn pause(&self) -> Result<(), AuthError> {
        self.run(tokio::time::sleep(Duration::from_millis(200)))
            .await
    }
}

pub(crate) struct Reply {
    pub url: Url,
    pub status: u16,
    pub headers: HeaderMap,
    pub body: Vec<u8>,
    pub chain: Vec<Url>,
}
impl Reply {
    pub fn text(&self) -> String {
        String::from_utf8_lossy(&self.body).into_owned()
    }
    pub fn json(&self) -> Result<serde_json::Value, AuthError> {
        serde_json::from_slice(&self.body).map_err(|_| {
            AuthError::query("门户响应格式异常，连接状态未知").because(Reason::ResponseInvalid)
        })
    }
    pub fn ensure_success(&self) -> Result<(), AuthError> {
        let result = match self.status {
            200..=299 => Ok(()),
            401 | 403 => Err(AuthError::interaction(
                "认证会话失效或需要人工处理，请重新登录",
            )),
            429 | 500..=599 => Err(AuthError::query("认证服务暂时不可用，请稍后重试")),
            _ => Err(AuthError::query("门户请求失败，连接状态未知")),
        };
        result.map_err(|e| e.because(Reason::HttpRejected))
    }
}

#[derive(Clone)]
pub(crate) struct Transport {
    client: reqwest::Client,
    jar: Arc<Jar>,
    pub base: Url,
    pub cas: Url,
    local: bool,
    sam_session: Arc<Mutex<Option<String>>>,
    captive_read: Arc<AtomicBool>,
}
impl Transport {
    pub fn new(config: &Config, local: bool) -> Result<Self, AuthError> {
        let parse = |s: &str| {
            Url::parse(&format!("{}/", s.trim_end_matches('/')))
                .map_err(|_| AuthError::query("认证地址格式异常"))
        };
        let jar = Arc::new(Jar::default());
        let client = reqwest::Client::builder()
            .cookie_provider(jar.clone())
            .redirect(reqwest::redirect::Policy::none())
            .no_proxy()
            .dns_resolver(Arc::new(crate::dns::CampusResolver))
            .danger_accept_invalid_certs(!config.verify_tls)
            .user_agent("Mozilla/5.0 YSU-Native-Auth/0.1")
            .connect_timeout(Duration::from_secs(10))
            .build()
            .map_err(|_| AuthError::query("HTTP 客户端初始化失败"))?;
        Ok(Self {
            client,
            jar,
            base: parse(&config.base)?,
            cas: parse(&config.cas_host)?,
            local,
            sam_session: Arc::new(Mutex::new(None)),
            captive_read: Arc::new(AtomicBool::new(false)),
        })
    }
    pub fn endpoint(&self, path: &str) -> Result<Url, AuthError> {
        self.base
            .join(path.trim_start_matches('/'))
            .map_err(|_| AuthError::query("门户路径异常"))
    }
    pub fn cas_endpoint(&self, path: &str) -> Result<Url, AuthError> {
        self.cas
            .join(path.trim_start_matches('/'))
            .map_err(|_| AuthError::query("统一认证路径异常"))
    }
    pub fn allowed(&self, u: &Url) -> Result<(), AuthError> {
        if !u.username().is_empty()
            || u.password().is_some()
            || (u.scheme() != "https" && !(self.local && u.scheme() == "http" && is_loopback(u)))
        {
            return Err(AuthError::query("认证跳转使用了不支持的地址或协议")
                .because(Reason::RedirectBlocked));
        }
        if u.origin() != self.base.origin() && u.origin() != self.cas.origin() {
            // Captive navigation only; this host never receives credentials or session API calls.
            if !self.local
                && u.host_str() == Some("124.124.124.124")
                && u.scheme() == "https"
                && u.port_or_known_default() == Some(443)
            {
                return Ok(());
            }
            return Err(
                AuthError::query("认证跳转超出门户与统一认证地址").because(Reason::RedirectBlocked)
            );
        }
        Ok(())
    }
    pub fn api_headers(&self, url: &Url, referer: Option<&Url>) -> HeaderMap {
        let mut h = HeaderMap::new();
        h.insert(
            "accept",
            HeaderValue::from_static("application/json, text/plain, */*"),
        );
        h.insert(
            "x-requested-with",
            HeaderValue::from_static("XMLHttpRequest"),
        );
        h.insert("isportal", HeaderValue::from_static("true"));
        if let Ok(origin) = HeaderValue::from_str(&url.origin().ascii_serialization()) {
            h.insert("origin", origin);
        }
        // Referer can contain tickets/session ids; keep it strictly same-origin.
        if let Some(r) = referer.filter(|r| r.origin() == url.origin()) {
            if let Ok(value) = HeaderValue::from_str(r.as_str()) {
                h.insert("referer", value);
            }
        }
        if let Some(cookies) = self
            .jar
            .cookies(url)
            .and_then(|v| v.to_str().ok().map(str::to_owned))
        {
            for pair in cookies.split(';') {
                if let Some((name, val)) = pair.trim().split_once('=') {
                    if ["XSRF-TOKEN", "XSRF_TOKEN", "CSRF-TOKEN", "CSRF_TOKEN"].contains(&name) {
                        if let Ok(value) = HeaderValue::from_str(&decode_cookie(val)) {
                            h.insert("x-xsrf-token", value);
                        }
                        break;
                    }
                }
            }
        }
        h
    }
    pub fn offline_headers(&self, url: &Url, referer: &Url) -> HeaderMap {
        let mut h = self.api_headers(url, Some(referer));
        if let Ok(guard) = self.sam_session.lock() {
            if let Some(sid) = guard.as_ref() {
                if let Ok(v) = HeaderValue::from_str(&format!("JSESSIONID={sid}")) {
                    h.insert(COOKIE, v);
                }
            }
        }
        h
    }
    pub async fn once(
        &self,
        method: Method,
        url: Url,
        headers: HeaderMap,
        body: Option<Vec<u8>>,
        op: &Operation,
    ) -> Result<Reply, AuthError> {
        self.allowed(&url)?;
        if url.origin() != self.base.origin()
            && url.origin() != self.cas.origin()
            && (body.is_some() || !matches!(method, Method::GET | Method::HEAD))
        {
            return Err(AuthError::query("认证内容仅向门户或统一认证站点提交"));
        }
        self.send_once(&self.client, method, url, headers, body, op)
            .await
    }
    async fn send_once(
        &self,
        client: &reqwest::Client,
        method: Method,
        url: Url,
        headers: HeaderMap,
        body: Option<Vec<u8>>,
        op: &Operation,
    ) -> Result<Reply, AuthError> {
        let endpoint = NavigationDiagnostic::capture(NavigationKind::HttpLocation,
            &url, &url, &self.base, &self.cas, method.as_str(), body.is_some());
        let mut trace = op.trace.request(endpoint, method == Method::POST);
        let result = async {
        if headers
            .iter()
            .map(|(key, value)| key.as_str().len() + value.as_bytes().len())
            .sum::<usize>()
            > HEADER_LIMIT
        {
            return Err(AuthError::query("请求头超过大小限制"));
        }
        if body.as_ref().is_some_and(|v| v.len() > RESPONSE_LIMIT) {
            return Err(AuthError::query("请求内容超过限制"));
        }
        let mut request = client
            .request(method, url.clone())
            .headers(headers)
            .timeout(op.remaining()?);
        if let Some(body) = body {
            request = request.body(body);
        }
        let mut r = trace.network(op.run(request.send()).await, crate::trace::NetworkPhase::Send)?;
        let status = r.status().as_u16();
        trace.headers(status);
        let headers = r.headers().clone();
        if headers
            .iter()
            .map(|(k, v)| k.as_str().len() + v.as_bytes().len())
            .sum::<usize>()
            > HEADER_LIMIT
        {
            return Err(AuthError::query("响应头超过限制"));
        }
        if r.content_length()
            .is_some_and(|n| n > RESPONSE_LIMIT as u64)
        {
            return Err(AuthError::query("门户响应超过大小限制"));
        }
        if url.origin() == self.base.origin() {
            for value in headers.get_all(SET_COOKIE) {
                if let Ok(cookie) = value.to_str() {
                    let mut parts = cookie.split(';');
                    let first = parts.next().unwrap_or("");
                    let sam_path = parts.any(|p| p.trim().eq_ignore_ascii_case("path=/sam"));
                    if sam_path {
                        if let Some(value) = first.strip_prefix("JSESSIONID=") {
                            if let Ok(mut slot) = self.sam_session.lock() {
                                *slot = Some(value.to_owned());
                            }
                        }
                    }
                }
            }
        }
        let mut bytes = Vec::new();
        while let Some(chunk) = trace.network(op.run(r.chunk()).await, crate::trace::NetworkPhase::ReadBody)? {
            if bytes.len().saturating_add(chunk.len()) > RESPONSE_LIMIT {
                return Err(AuthError::query("门户响应超过大小限制"));
            }
            bytes.extend_from_slice(&chunk);
            trace.bytes = bytes.len();
        }
        Ok(Reply {
            url: url.clone(),
            status,
            headers,
            body: bytes,
            chain: vec![url],
        })
        }.await;
        trace.finish(&result);
        result
    }
    pub async fn follow(
        &self,
        method: Method,
        url: Url,
        headers: HeaderMap,
        body: Option<Vec<u8>>,
        op: &Operation,
    ) -> Result<Reply, AuthError> {
        self.follow_inner(method, url, headers, body, op, false)
            .await
    }
    pub(crate) fn portal_navigation_target(
        &self,
        from: &Url,
        mut next: Url,
        method: &Method,
        has_body: bool,
    ) -> Url {
        // The HTTPS redirect.jsp emits a legacy HTTP portal-main Location, whose
        // HTTP endpoint only upgrades back to HTTPS. Skip that cleartext hop;
        // this exception is a URL rewrite, never permission to send HTTP.
        // Decision: .agents/notes/implemented/desktop/2026-10-27-portal-entry-variants.md
        let entry = self.endpoint("eportal/redirect.jsp").ok();
        let history_entry = entry.as_ref().map(|url| {
            let mut url = url.clone();
            url.set_query(Some("mode=history"));
            url
        });
        let portal = self.endpoint("portal/portal-main").ok();
        let mut ids = next.query_pairs().filter(|(key, _)| key == "sessionId");
        let valid_sid = ids.next().is_some_and(|(_, value)| {
            !value.is_empty() && value.len() <= 1024 && !value.chars().any(char::is_control)
        }) && ids.next().is_none();
        if !self.local
            && method == Method::GET
            && !has_body
            && self.base.scheme() == "https"
            && self.base.port_or_known_default() == Some(443)
            && (entry.as_ref() == Some(from) || history_entry.as_ref() == Some(from))
            && next.scheme() == "http"
            && next.port_or_known_default() == Some(80)
            && next.host() == self.base.host()
            && portal.as_ref().is_some_and(|url| next.path() == url.path())
            && next.username().is_empty()
            && next.password().is_none()
            && next.fragment().is_none()
            && valid_sid
        {
            let _ = next.set_scheme("https");
        }
        next
    }
    pub(crate) fn checked_portal_navigation_target(
        &self,
        from: &Url,
        next: Url,
        method: &Method,
        has_body: bool,
        kind: NavigationKind,
    ) -> Result<Url, AuthError> {
        let diagnostic = NavigationDiagnostic::capture(
            kind,
            from,
            &next,
            &self.base,
            &self.cas,
            method.as_str(),
            has_body,
        );
        let next = self.portal_navigation_target(from, next, method, has_body);
        self.allowed(&next)
            .map_err(|error| error.with_navigation(diagnostic))?;
        Ok(next)
    }
    // Decision: .agents/notes/implemented/desktop/2026-10-27-offline-captive-bootstrap.md
    pub(crate) fn is_captive_bootstrap(
        &self,
        from: &Url,
        next: &Url,
        method: &Method,
        has_body: bool,
    ) -> bool {
        !self.local
            && self.base.scheme() == "https"
            && self.base.port_or_known_default() == Some(443)
            && self.endpoint("eportal/redirect.jsp").as_ref().ok() == Some(from)
            && method == Method::GET
            && !has_body
            && next.as_str() == "http://124.124.124.124/"
    }
    pub(crate) async fn resolve_captive_navigation(
        &self,
        from: &Url,
        next: &Url,
        method: &Method,
        has_body: bool,
        op: &Operation,
    ) -> Result<Option<Url>, AuthError> {
        if !self.is_captive_bootstrap(from, next, method, has_body) {
            return Ok(None);
        }
        if self.captive_read.swap(true, Ordering::SeqCst) {
            return Err(AuthError::query("门户 captive 引导重复，连接状态未知")
                .because(Reason::RedirectLimit));
        }
        // No cookie jar or inherited headers, and no automatic HTTP redirects.
        let client = captive_client()?;
        let reply = self
            .send_once(
                &client,
                Method::GET,
                next.clone(),
                HeaderMap::new(),
                None,
                op,
            )
            .await?;
        self.captive_page_target(&reply).map(Some)
    }
    // Decision: .agents/notes/implemented/desktop/2026-10-28-shared-bootstrap-navigation.md
    pub(crate) async fn resolve_portal_navigation(
        &self,
        from: &Url,
        next: Url,
        method: &Method,
        has_body: bool,
        kind: NavigationKind,
        op: &Operation,
    ) -> Result<Url, AuthError> {
        let diagnostic = NavigationDiagnostic::capture(
            kind,
            from,
            &next,
            &self.base,
            &self.cas,
            method.as_str(),
            has_body,
        );
        op.trace.emit(crate::trace::TraceEvent::Navigation { navigation: diagnostic });
        if let Some(target) = self
            .resolve_captive_navigation(from, &next, method, has_body, op)
            .await
            .map_err(|error| error.with_navigation(diagnostic))?
        {
            return Ok(target);
        }
        self.checked_portal_navigation_target(from, next, method, has_body, kind)
    }
    fn captive_page_target(&self, reply: &Reply) -> Result<Url, AuthError> {
        // The unsigned page may only hint at a fresh HTTPS index request. Its
        // scripts, cookies, redirect headers and session IDs are never trusted.
        let target = (reply.status == 200)
            .then(|| crate::protocol::next_navigation(&reply.text(), &reply.url))
            .flatten()
            .filter(|url| {
                url.origin() == self.base.origin()
                    && self
                        .endpoint("eportal/index.jsp")
                        .is_ok_and(|index| url.path() == index.path())
                    && url.username().is_empty()
                    && url.password().is_none()
                    && url.fragment().is_none()
                    && !url.query_pairs().any(|(key, _)| {
                        matches!(key.as_ref(), "sessionId" | "flowSessionId" | "ticket")
                    })
            })
            .ok_or_else(|| {
                AuthError::query("门户 captive 引导未返回可信 HTTPS 入口")
                    .because(Reason::RedirectBlocked)
            })?;
        self.allowed(&target)?;
        Ok(target)
    }
    async fn follow_inner(
        &self,
        mut method: Method,
        mut url: Url,
        mut headers: HeaderMap,
        mut body: Option<Vec<u8>>,
        op: &Operation,
        portal_navigation: bool,
    ) -> Result<Reply, AuthError> {
        let mut chain = Vec::new();
        for hop in 0..=REDIRECT_LIMIT {
            let mut r = self
                .once(
                    method.clone(),
                    url.clone(),
                    headers.clone(),
                    body.clone(),
                    op,
                )
                .await?;
            chain.push(url.clone());
            if !matches!(r.status, 301 | 302 | 303 | 307 | 308) {
                r.chain = chain;
                return Ok(r);
            }
            if hop == REDIRECT_LIMIT {
                return Err(
                    AuthError::query("认证重定向超过次数限制").because(Reason::RedirectLimit)
                );
            }
            let next = r
                .headers
                .get(LOCATION)
                .and_then(|v| v.to_str().ok())
                .and_then(|v| url.join(v).ok())
                .ok_or_else(|| {
                    AuthError::query("认证重定向缺少有效地址").because(Reason::ResponseInvalid)
                })?;
            let next = if portal_navigation {
                self.resolve_portal_navigation(
                    &url,
                    next,
                    &method,
                    body.is_some(),
                    NavigationKind::HttpLocation,
                    op,
                )
                .await?
            } else {
                self.allowed(&next)?;
                next
            };
            let origin_changed = next.origin() != url.origin();
            if origin_changed && body.is_some() && matches!(r.status, 307 | 308) {
                return Err(
                    AuthError::query("认证表单跨站重复提交已停止").because(Reason::RedirectBlocked)
                );
            }
            if r.status == 303 || (matches!(r.status, 301 | 302) && method == Method::POST) {
                method = Method::GET;
                body = None;
                headers.remove(CONTENT_TYPE);
            }
            // Recompute domain-scoped cookies/XSRF; never forward original Cookie/Authorization.
            let had_xsrf = headers.contains_key("x-xsrf-token");
            headers.remove(COOKIE);
            headers.remove("authorization");
            headers.remove("x-xsrf-token");
            if origin_changed {
                headers.remove("origin");
                headers.remove("referer");
            } else if had_xsrf {
                if let Some(token) = self.api_headers(&next, None).get("x-xsrf-token") {
                    headers.insert("x-xsrf-token", token.clone());
                }
            }
            url = next;
        }
        Err(AuthError::query("认证重定向超过次数限制").because(Reason::RedirectLimit))
    }
    pub async fn get(&self, url: Url, op: &Operation) -> Result<Reply, AuthError> {
        self.follow(Method::GET, url, HeaderMap::new(), None, op)
            .await
    }
    pub async fn navigation_get(&self, url: Url, op: &Operation) -> Result<Reply, AuthError> {
        self.follow_inner(Method::GET, url, HeaderMap::new(), None, op, true)
            .await
    }
    pub async fn json_post(
        &self,
        path: &str,
        payload: &serde_json::Value,
        referer: Option<&Url>,
        op: &Operation,
    ) -> Result<Reply, AuthError> {
        let url = self.endpoint(path)?;
        let mut headers = self.api_headers(&url, referer);
        headers.insert(
            CONTENT_TYPE,
            HeaderValue::from_static("application/json;charset=UTF-8"),
        );
        let body = serde_json::to_vec(payload).map_err(|_| AuthError::query("请求编码失败"))?;
        // State-changing API redirects are not success acknowledgements.
        self.once(Method::POST, url, headers, Some(body), op).await
    }
}
fn captive_client() -> Result<reqwest::Client, AuthError> {
    reqwest::Client::builder()
        .redirect(reqwest::redirect::Policy::none())
        .no_proxy()
        .user_agent("Mozilla/5.0 YSU-Native-Auth/0.1")
        .connect_timeout(Duration::from_secs(10))
        .build()
        .map_err(|_| AuthError::query("门户引导客户端初始化失败"))
}
pub(crate) fn network_error(e: reqwest::Error) -> AuthError {
    if e.is_timeout() {
        AuthError::timeout()
    } else if e.is_connect() {
        AuthError::query("连接认证服务失败，请检查网络和证书").because(Reason::Network)
    } else {
        AuthError::query("读取认证响应失败，连接状态未知").because(Reason::Network)
    }
}
fn decode_cookie(s: &str) -> String {
    // Query decoding treats '+' as a space; cookies need percent decoding only.
    url::form_urlencoded::parse(format!("v={}", s.replace('+', "%2B")).as_bytes())
        .next()
        .map(|(_, v)| v.into_owned())
        .unwrap_or_default()
}

#[cfg(test)]
#[path = "captive_tests.rs"]
mod captive_tests;
