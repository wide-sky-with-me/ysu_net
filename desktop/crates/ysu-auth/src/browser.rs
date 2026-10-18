//! System Chromium driven directly over CDP. Fetch substitutes Chromium's network
//! layer with the same bounded Rust transport; there is no browser/sidecar fallback.
#[cfg(windows)]
use crate::browser_process::Child;
use crate::{
    cdp_pipe::Pipe,
    protocol::{captcha_required, query},
    transport::{Operation, Transport, REDIRECT_LIMIT, RESPONSE_LIMIT},
    AuthError, Config,
};
use base64::{engine::general_purpose::STANDARD, Engine};
use reqwest::{
    header::{HeaderName, HeaderValue},
    Method,
};
use serde_json::{json, Value};
#[cfg(unix)]
use std::os::{
    fd::{AsRawFd, OwnedFd},
    unix::process::CommandExt,
};
#[cfg(any(test, windows))]
use std::path::Path;
#[cfg(not(windows))]
use std::process::{Child, Stdio};
use std::{
    collections::{BTreeMap, BTreeSet},
    fs::File,
    path::PathBuf,
    process::Command,
};
use tempfile::TempDir;
use tokio::time::Instant;
use url::Url;

/// CDP messages carry base64 Fetch bodies, so allow twice the response limit.
const CDP_MESSAGE_LIMIT: usize = RESPONSE_LIMIT * 2;

struct Process {
    child: Option<Child>,
    profile: Option<TempDir>,
}
impl Process {
    #[cfg(test)]
    fn id(&self) -> u32 {
        self.child.as_ref().expect("live child").id()
    }
    #[cfg(test)]
    fn profile_path(&self) -> &Path {
        self.profile.as_ref().expect("live profile").path()
    }
}
impl Drop for Process {
    fn drop(&mut self) {
        let Some(mut child) = self.child.take() else {
            return;
        };
        #[cfg(unix)]
        unsafe {
            // This group belongs to the isolated browser, never a user's existing process.
            libc::kill(-(child.id() as libc::pid_t), libc::SIGKILL);
        }
        let _ = child.kill();
        let reaper = Reaper {
            child,
            profile: self.profile.take(),
        };
        // The owned tree/profile move together; cancellation never leaves unowned work.
        let _ = std::thread::Builder::new()
            .name("ysu-auth-browser-reaper".into())
            .spawn(move || drop(reaper));
    }
}

struct Reaper {
    child: Child,
    profile: Option<TempDir>,
}
impl Drop for Reaper {
    fn drop(&mut self) {
        // Keep the Job/process and profile together until the owned tree has stopped.
        while self.child.wait().is_err() {
            let _ = self.child.kill();
            std::thread::sleep(std::time::Duration::from_millis(50));
        }
        if let Some(profile) = self.profile.take() {
            let path = profile.path().to_owned();
            if profile.close().is_err() {
                let _ = std::thread::Builder::new()
                    .name("ysu-auth-profile-reaper".into())
                    .spawn(move || {
                        for _ in 0..100 {
                            if !path.exists() || std::fs::remove_dir_all(&path).is_ok() {
                                return;
                            }
                            std::thread::sleep(std::time::Duration::from_millis(50));
                        }
                    });
            }
        }
    }
}

pub(crate) struct Browser {
    pipe: Pipe,
    _process: Process,
    http: Transport,
    session: String,
    next_id: u64,
    main_frame: String,
    contexts: BTreeSet<(String, i64)>,
    initialization: BTreeMap<u64, String>,
    initializing_children: BTreeMap<String, usize>,
    redirects: usize,
    requests: usize,
    sid: Option<String>,
    last: Url,
}

/// Returns system-installed Chromium candidates only. No bundled runtime or downloader.
pub fn system_chromium() -> Option<PathBuf> {
    if let Some(value) = std::env::var_os("YSU_AUTH_CHROMIUM_PATH") {
        let path = PathBuf::from(value);
        return path.is_absolute().then_some(path).filter(|p| p.is_file());
    }
    let names = if cfg!(target_os = "windows") {
        vec!["chrome.exe", "msedge.exe", "chromium.exe"]
    } else {
        vec![
            "chromium",
            "chromium-browser",
            "google-chrome",
            "google-chrome-stable",
            "microsoft-edge",
        ]
    };
    if let Some(path) = std::env::var_os("PATH") {
        for directory in std::env::split_paths(&path) {
            for name in &names {
                let candidate = directory.join(name);
                if candidate.is_file() {
                    return candidate.canonicalize().ok();
                }
            }
        }
    }
    let mut candidates = vec![
        PathBuf::from("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        PathBuf::from("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
        PathBuf::from("/Applications/Chromium.app/Contents/MacOS/Chromium"),
    ];
    for variable in ["PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"] {
        if let Some(root) = std::env::var_os(variable) {
            let root = PathBuf::from(root);
            candidates.push(root.join("Google/Chrome/Application/chrome.exe"));
            candidates.push(root.join("Microsoft/Edge/Application/msedge.exe"));
            candidates.push(root.join("Chromium/Application/chrome.exe"));
        }
    }
    candidates.into_iter().find(|p| p.is_file())
}

impl Browser {
    pub async fn start(http: Transport, op: &Operation) -> Result<Self, AuthError> {
        op.remaining()?;
        let executable = system_chromium().ok_or_else(|| {
            AuthError::interaction(
                "浏览器后端需要系统 Chromium、Chrome 或 Edge，请安装或显式设置浏览器路径",
            )
        })?;
        let profile = tempfile::Builder::new()
            .prefix("ysu-auth-chromium-")
            .tempdir()
            .map_err(|_| AuthError::query("创建隔离浏览器目录失败"))?;
        let mut command = Command::new(executable);
        command.args([
            // Private pipes instead of a debugging port: no other local process can attach.
            "--headless=new", "--remote-debugging-pipe",
            "--no-first-run", "--no-default-browser-check", "--disable-background-networking",
            "--disable-component-update", "--disable-default-apps", "--disable-extensions",
            "--disable-sync", "--disable-domain-reliability", "--disable-breakpad", "--disable-dev-shm-usage",
            "--disable-features=MediaRouter,OptimizationHints,AutofillServerCommunication,CertificateTransparencyComponentUpdater",
            // Fetch is fulfilled by Rust; any unintercepted browser traffic gets no network route.
            "--proxy-server=http://127.0.0.1:9", "--proxy-bypass-list=<-loopback>", "--disable-quic",
        ]).arg(format!("--user-data-dir={}", profile.path().display())).arg("about:blank");
        let failed = |_| AuthError::query("启动系统 Chromium 失败，请检查安装与执行权限");
        #[cfg(not(windows))]
        let (child, pipe) = {
            // Chromium reads commands from fd 3 and writes replies to fd 4.
            let (browser_input, commands) = std::io::pipe().map_err(failed)?;
            let (replies, browser_output) = std::io::pipe().map_err(failed)?;
            let browser_input = OwnedFd::from(browser_input);
            let browser_output = OwnedFd::from(browser_output);
            let (read, write) = (browser_input.as_raw_fd(), browser_output.as_raw_fd());
            command.process_group(0);
            unsafe {
                command.pre_exec(move || {
                    // Copy above 3/4 first so neither source is overwritten by the other dup2.
                    let read = libc::fcntl(read, libc::F_DUPFD_CLOEXEC, 10);
                    let write = libc::fcntl(write, libc::F_DUPFD_CLOEXEC, 10);
                    if read < 0 || write < 0 || libc::dup2(read, 3) < 0 || libc::dup2(write, 4) < 0
                    {
                        return Err(std::io::Error::last_os_error());
                    }
                    Ok(())
                });
            }
            let child = command
                .stdin(Stdio::null())
                .stdout(Stdio::null())
                .stderr(Stdio::null())
                .spawn()
                .map_err(failed)?;
            // Only the child may hold its ends, so its exit is seen as EOF.
            drop((browser_input, browser_output));
            let pipe = Pipe::new(
                File::from(OwnedFd::from(replies)),
                File::from(OwnedFd::from(commands)),
                CDP_MESSAGE_LIMIT,
            );
            (child, pipe)
        };
        #[cfg(windows)]
        let (child, pipe) = {
            use std::os::windows::io::AsRawHandle;
            let (browser_input, commands) = crate::browser_process::pipe().map_err(failed)?;
            let (replies, browser_output) = crate::browser_process::pipe().map_err(failed)?;
            let handles = [
                browser_input.as_raw_handle(),
                browser_output.as_raw_handle(),
            ];
            command.arg(format!(
                "--remote-debugging-io-pipes={},{}",
                handles[0] as usize, handles[1] as usize
            ));
            let child = Child::spawn(
                Path::new(command.get_program()),
                &command.get_args().collect::<Vec<_>>(),
                &handles,
            )
            .map_err(failed)?;
            drop((browser_input, browser_output));
            let pipe = Pipe::new(File::from(replies), File::from(commands), CDP_MESSAGE_LIMIT);
            (child, pipe)
        };
        let process = Process {
            child: Some(child),
            profile: Some(profile),
        };
        let pipe = pipe.map_err(|_| AuthError::query("连接 Chromium 调试管道失败"))?;
        let mut this = Self {
            pipe,
            _process: process,
            last: http.base.clone(),
            http,
            session: String::new(),
            main_frame: String::new(),
            next_id: 1,
            contexts: BTreeSet::new(),
            initialization: BTreeMap::new(),
            initializing_children: BTreeMap::new(),
            redirects: 0,
            requests: 0,
            sid: None,
        };
        let target = this
            .rpc(
                "Target.createTarget",
                json!({"url":"about:blank"}),
                None,
                op,
            )
            .await?;
        let target = target["targetId"]
            .as_str()
            .ok_or_else(|| AuthError::query("Chromium 未创建隔离页面"))?;
        let attached = this
            .rpc(
                "Target.attachToTarget",
                json!({"targetId":target,"flatten":true}),
                None,
                op,
            )
            .await?;
        this.session = attached["sessionId"]
            .as_str()
            .ok_or_else(|| AuthError::query("Chromium 页面连接失败"))?
            .to_owned();
        for (method, params) in [
            ("Page.enable", json!({})),
            ("Runtime.enable", json!({})),
            ("Network.enable", json!({})),
            ("Network.setBypassServiceWorker", json!({"bypass":true})),
            (
                "Fetch.enable",
                json!({"patterns":[{"urlPattern":"*","requestStage":"Request"}]}),
            ),
            (
                "Target.setAutoAttach",
                json!({"autoAttach":true,"waitForDebuggerOnStart":true,"flatten":true}),
            ),
        ] {
            this.call(method, params, op).await?;
        }
        let tree = this.call("Page.getFrameTree", json!({}), op).await?;
        this.main_frame = tree["frameTree"]["frame"]["id"]
            .as_str()
            .ok_or_else(|| AuthError::query("Chromium 主页面标识缺失"))?
            .to_owned();
        Ok(this)
    }
    async fn send(
        &mut self,
        method: &str,
        params: Value,
        session: Option<&str>,
        op: &Operation,
    ) -> Result<u64, AuthError> {
        let id = self.next_id;
        self.next_id += 1;
        let mut v = json!({"id":id,"method":method,"params":params});
        if let Some(session) = session {
            v["sessionId"] = Value::String(session.into());
        }
        op.remaining()?;
        if !self.pipe.send(v.to_string().into_bytes()) {
            return Err(AuthError::query("Chromium 调试连接中断"));
        }
        Ok(id)
    }
    async fn receive(&mut self, op: &Operation) -> Result<Value, AuthError> {
        let message = op
            .run(self.pipe.recv())
            .await?
            .ok_or_else(|| AuthError::query("Chromium 调试连接已关闭"))?;
        serde_json::from_slice(&message).map_err(|_| AuthError::query("Chromium 调试响应格式异常"))
    }
    async fn rpc(
        &mut self,
        method: &str,
        params: Value,
        session: Option<&str>,
        op: &Operation,
    ) -> Result<Value, AuthError> {
        let id = self.send(method, params, session, op).await?;
        loop {
            let v = self.receive(op).await?;
            if v["id"].as_u64() == Some(id) {
                if v.get("error").is_some() {
                    return Err(AuthError::query("Chromium 调试操作失败"));
                }
                return Ok(v["result"].clone());
            }
            if v["id"].as_u64().is_some() {
                self.acknowledge(&v, op).await?;
            } else {
                self.event(v, op).await?;
            }
        }
    }
    async fn call(
        &mut self,
        method: &str,
        params: Value,
        op: &Operation,
    ) -> Result<Value, AuthError> {
        let session = self.session.clone();
        self.rpc(method, params, Some(&session), op).await
    }
    async fn acknowledge(&mut self, response: &Value, op: &Operation) -> Result<(), AuthError> {
        if response.get("error").is_some() {
            return Err(AuthError::query("Chromium 网络或子页面初始化失败"));
        }
        if let Some(child) = response["id"]
            .as_u64()
            .and_then(|id| self.initialization.remove(&id))
        {
            if let Some(remaining) = self.initializing_children.get_mut(&child) {
                *remaining -= 1;
                if *remaining == 0 {
                    self.initializing_children.remove(&child);
                    self.send(
                        "Runtime.runIfWaitingForDebugger",
                        json!({}),
                        Some(&child),
                        op,
                    )
                    .await?;
                }
            }
        }
        Ok(())
    }

    async fn event(&mut self, event: Value, op: &Operation) -> Result<(), AuthError> {
        let params = &event["params"];
        let session = event["sessionId"]
            .as_str()
            .unwrap_or(&self.session)
            .to_owned();
        match event["method"].as_str().unwrap_or("") {
            "Fetch.requestPaused" => self.fulfill(params, &session, op).await?,
            "Runtime.executionContextCreated" => {
                let c = &params["context"];
                if c["origin"].as_str()
                    == Some(self.http.cas.origin().ascii_serialization().as_str())
                    && c["auxData"]["isDefault"] == true
                {
                    if let Some(id) = c["id"].as_i64() {
                        self.contexts.insert((session.clone(), id));
                    }
                }
            }
            "Runtime.executionContextDestroyed" => {
                if let Some(id) = params["executionContextId"].as_i64() {
                    self.contexts.remove(&(session.clone(), id));
                }
            }
            "Runtime.executionContextsCleared" => self.contexts.retain(|(s, _)| s != &session),
            "Page.frameNavigated" => {
                if session == self.session
                    && params["frame"]["id"].as_str() == Some(self.main_frame.as_str())
                {
                    if let Some(url) = params["frame"]["url"]
                        .as_str()
                        .and_then(|s| Url::parse(s).ok())
                    {
                        if matches!(url.scheme(), "https" | "http") {
                            self.last = url;
                        }
                    }
                }
            }
            "Target.detachedFromTarget" => {
                if let Some(child) = params["sessionId"].as_str() {
                    self.contexts.retain(|(session, _)| session != child);
                    self.initializing_children.remove(child);
                    self.initialization.retain(|_, session| session != child);
                }
            }
            "Target.attachedToTarget" => {
                if let Some(child) = params["sessionId"].as_str() {
                    if self.initializing_children.len() >= 64 {
                        return Err(AuthError::query("Chromium 子页面超过数量限制"));
                    }
                    self.initializing_children.insert(child.to_owned(), 5);
                    // Every setup ACK must succeed before the target is allowed to execute.
                    for (method, settings) in [
                        (
                            "Fetch.enable",
                            json!({"patterns":[{"urlPattern":"*","requestStage":"Request"}]}),
                        ),
                        ("Runtime.enable", json!({})),
                        ("Network.enable", json!({})),
                        ("Network.setBypassServiceWorker", json!({"bypass":true})),
                        (
                            "Target.setAutoAttach",
                            json!({"autoAttach":true,"waitForDebuggerOnStart":true,"flatten":true}),
                        ),
                    ] {
                        let id = self.send(method, settings, Some(child), op).await?;
                        self.initialization.insert(id, child.to_owned());
                    }
                }
            }
            _ => {}
        }
        Ok(())
    }
    async fn fulfill(
        &mut self,
        params: &Value,
        session: &str,
        op: &Operation,
    ) -> Result<(), AuthError> {
        let id = params["requestId"]
            .as_str()
            .ok_or_else(|| AuthError::query("Chromium 请求标识异常"))?;
        let request = &params["request"];
        let url = request["url"].as_str().and_then(|v| Url::parse(v).ok());
        let Some(url) = url else {
            return Err(AuthError::query("Chromium 请求地址异常"));
        };
        let top_document = params["resourceType"] == "Document"
            && params["frameId"].as_str() == Some(self.main_frame.as_str());
        let captive =
            url.origin() != self.http.base.origin() && url.origin() != self.http.cas.origin();
        if self.http.allowed(&url).is_err() || (captive && !top_document) {
            self.send(
                "Fetch.failRequest",
                json!({"requestId":id,"errorReason":"BlockedByClient"}),
                Some(session),
                op,
            )
            .await?;
            if params["resourceType"] == "Document" {
                return Err(AuthError::query("浏览器导航超出认证地址"));
            }
            return Ok(());
        }
        self.requests += 1;
        if self.requests > 256 {
            return Err(AuthError::query("浏览器请求超过次数限制"));
        }
        if top_document && url.origin() == self.http.base.origin() {
            if let Some(sid) = query(&url, "sessionId").or_else(|| query(&url, "flowSessionId")) {
                self.sid = Some(sid);
            }
        }
        let method = Method::from_bytes(request["method"].as_str().unwrap_or("GET").as_bytes())
            .map_err(|_| AuthError::query("浏览器请求方法异常"))?;
        let mut headers = self.http.api_headers(&url, None);
        headers.remove("isportal");
        headers.remove("x-requested-with");
        if let Some(raw) = request["headers"].as_object() {
            for (name, value) in raw {
                if matches!(
                    name.to_ascii_lowercase().as_str(),
                    "content-type" | "accept" | "accept-language"
                ) {
                    if let (Ok(name), Some(value)) =
                        (HeaderName::from_bytes(name.as_bytes()), value.as_str())
                    {
                        if let Ok(value) = HeaderValue::from_str(value) {
                            headers.insert(name, value);
                        }
                    }
                }
            }
        }
        let body = request["postData"].as_str().map(|s| s.as_bytes().to_vec());
        if request["hasPostData"] == true && body.is_none() {
            return Err(AuthError::query("浏览器请求体缺失，暂不提交认证"));
        }
        if captive && (body.is_some() || !matches!(method, Method::GET | Method::HEAD)) {
            return Err(AuthError::query(
                "浏览器 captive 页面仅接受无认证内容的导航",
            ));
        }
        let has_body = body.is_some();
        let cas_post = method == Method::POST
            && url.origin() == self.http.cas.origin()
            && url.path().ends_with("/authserver/login");
        let r = self
            .http
            .once(method, url.clone(), headers, body, op)
            .await?;
        if matches!(r.status, 301 | 302 | 303 | 307 | 308) {
            self.redirects += 1;
            if self.redirects > REDIRECT_LIMIT {
                return Err(AuthError::query("浏览器重定向超过次数限制"));
            }
            if let Some(location) = r.headers.get("location").and_then(|v| v.to_str().ok()) {
                let next = url
                    .join(location)
                    .map_err(|_| AuthError::query("浏览器重定向地址异常"))?;
                self.http.allowed(&next)?;
                if has_body && next.origin() != url.origin() && matches!(r.status, 307 | 308) {
                    return Err(AuthError::query("浏览器认证内容跨站重复提交已停止"));
                }
                if cas_post && matches!(r.status, 307 | 308) {
                    return Err(AuthError::interaction(
                        "统一认证要求重复提交，请人工处理后重试",
                    ));
                }
            } else {
                return Err(AuthError::query("浏览器重定向缺少地址"));
            }
        }
        if cas_post && !matches!(r.status, 301 | 302 | 303) {
            if matches!(r.status, 429 | 500..=599) {
                return Err(AuthError::query("统一认证服务暂时不可用，请稍后重试"));
            }
            return Err(AuthError::interaction(
                "统一认证未确认登录，请检查账号密码、验证码或风控状态",
            ));
        }
        if params["resourceType"] == "Document" && !matches!(r.status, 301 | 302 | 303 | 307 | 308)
        {
            r.ensure_success()?;
        }
        let mut response_headers = Vec::new();
        for (name, value) in &r.headers {
            // reqwest already decoded gzip/brotli/deflate; CDP receives the decoded bytes.
            if matches!(
                name.as_str(),
                "content-encoding" | "transfer-encoding" | "content-length"
            ) {
                continue;
            }
            if let Ok(value) = value.to_str() {
                response_headers.push(json!({"name":name.as_str(),"value":value}));
            }
        }
        response_headers.push(json!({"name":"Content-Length","value":r.body.len().to_string()}));
        self.send("Fetch.fulfillRequest", json!({"requestId":id,"responseCode":r.status,"responseHeaders":response_headers,"body":STANDARD.encode(r.body)}), Some(session), op).await?;
        Ok(())
    }
    async fn evaluate(
        &mut self,
        expression: &str,
        context: Option<(String, i64)>,
        op: &Operation,
    ) -> Result<Value, AuthError> {
        let mut params = json!({"expression":expression,"returnByValue":true,"awaitPromise":false});
        let session = if let Some((session, context)) = context {
            params["contextId"] = json!(context);
            session
        } else {
            self.session.clone()
        };
        let result = self
            .rpc("Runtime.evaluate", params, Some(&session), op)
            .await?;
        if result.get("exceptionDetails").is_some() {
            return Err(AuthError::interaction(
                "浏览器页面交互失败，请检查门户或风控状态",
            ));
        }
        Ok(result["result"]["value"].clone())
    }
    async fn navigate(&mut self, url: Url, op: &Operation) -> Result<(), AuthError> {
        self.http.allowed(&url)?;
        self.redirects = 0;
        let result = self
            .call("Page.navigate", json!({"url":url.as_str()}), op)
            .await?;
        if result.get("errorText").is_some() {
            return Err(AuthError::query("Chromium 页面导航失败"));
        }
        self.ready(op).await
    }
    async fn ready(&mut self, op: &Operation) -> Result<(), AuthError> {
        loop {
            let state = self.evaluate("document.readyState", None, op).await?;
            if matches!(state.as_str(), Some("interactive" | "complete")) {
                return Ok(());
            }
            op.pause().await?;
        }
    }
    pub async fn portal(&mut self, op: &Operation) -> Result<(String, Url), AuthError> {
        for path in ["", "eportal/index.jsp", "eportal/redirect.jsp"] {
            self.navigate(self.http.endpoint(path)?, op).await?;
            // Let startup scripts execute; every pending HTTP request is still intercepted.
            let settle = Operation::new(
                (Instant::now() + std::time::Duration::from_millis(500)).min(op.deadline),
            );
            while Instant::now() < settle.deadline {
                let short = Operation::new(
                    (Instant::now() + std::time::Duration::from_millis(50)).min(settle.deadline),
                );
                match self.receive(&short).await {
                    Ok(v) if v.get("id").is_none() => self.event(v, op).await?,
                    Ok(v) => self.acknowledge(&v, op).await?,
                    Err(e) if e.message == AuthError::timeout().message => {}
                    Err(e) => return Err(e),
                }
            }
            let href = self.evaluate("location.href", None, op).await?;
            if let Some(url) = href.as_str().and_then(|s| Url::parse(s).ok()) {
                self.last = url;
            }
            if let Some(sid) = self
                .sid
                .clone()
                .or_else(|| query(&self.last, "sessionId"))
                .or_else(|| query(&self.last, "flowSessionId"))
            {
                return Ok((sid, self.last.clone()));
            }
        }
        Err(AuthError::query("浏览器门户未返回有效会话"))
    }
    pub async fn cas_login(
        &mut self,
        url: Url,
        config: &Config,
        op: &Operation,
    ) -> Result<(), AuthError> {
        self.navigate(url, op).await?;
        let state = self.evaluate(r#"({href:location.href,blocked:/IP被冻结|风险验证|访问频繁|noSupport/.test(document.title+' '+document.body.innerText.slice(0,4096)),captcha:!!Array.from(document.querySelectorAll('#captchaDiv, input[name=captcha], input[name=otp], input[name=smscode]')).find(e=>e.getClientRects().length&&getComputedStyle(e).visibility!=='hidden')})"#, None, op).await?;
        if state["blocked"] == true {
            return Err(AuthError::interaction("统一认证触发风控，请人工处理后重试"));
        }
        let page = state["href"]
            .as_str()
            .and_then(|s| Url::parse(s).ok())
            .ok_or_else(|| AuthError::query("浏览器页面地址异常"))?;
        if captcha_required(
            &self.http,
            &page,
            &config.username,
            state["captcha"] == true,
            op,
        )
        .await?
        {
            return Err(AuthError::interaction(
                "统一认证需要验证码，请人工处理后重试",
            ));
        }
        let credentials = json!({"username":config.username,"password":config.password,"origin":self.http.cas.origin().ascii_serialization()});
        let expression = format!(
            r#"(()=>{{
            const c={credentials};
            if(location.origin!==c.origin)return 'other';
            const visible=e=>e.getClientRects().length&&getComputedStyle(e).visibility!=='hidden';
            const candidates=Array.from(document.forms).map(f=>({{f,
                u:f.querySelector('input#username,input[name=username],input[name=userName],input[autocomplete=username]'),
                p:f.querySelector('input#password,input[name=password],input[type=password]')}}));
            const choice=candidates.find(x=>x.u&&x.p&&visible(x.u)&&visible(x.p));
            if(!choice)return 'missing';
            const {{f,u,p}}=choice;
            if(new URL(f.action||location.href,location.href).origin!==c.origin)return 'bad-action';
            for(const [e,v] of [[u,c.username],[p,c.password]]){{
                Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(e,v);
                e.dispatchEvent(new Event('input',{{bubbles:true}}));
                e.dispatchEvent(new Event('change',{{bubbles:true}}));
            }}
            const b=f.querySelector('#login_submit,button[type=submit],input[type=submit]')||Array.from(f.querySelectorAll('button')).find(e=>/登录/.test(e.innerText));
            setTimeout(()=>{{if(b)b.click();else f.requestSubmit();}},0);
            return 'submitted';
        }})()"#
        );
        let mut contexts: Vec<Option<(String, i64)>> = vec![None];
        contexts.extend(self.contexts.iter().cloned().map(Some));
        let mut submitted = false;
        for context in contexts {
            let frame_state = self.evaluate(r#"({blocked:/IP被冻结|访问被拒绝|安全验证|风险验证|访问频繁|noSupport/.test(document.title+' '+document.body.innerText.slice(0,4096)),captcha:!!Array.from(document.querySelectorAll('#captchaDiv, input[name=captcha], input[name=otp], input[name=smscode]')).find(e=>e.getClientRects().length&&getComputedStyle(e).visibility!=='hidden')})"#, context.clone(), op).await?;
            if frame_state["blocked"] == true || frame_state["captcha"] == true {
                return Err(AuthError::interaction(
                    "统一认证需要验证码或触发风控，请人工处理后重试",
                ));
            }
            match self.evaluate(&expression, context, op).await {
                Ok(v) if v == "submitted" => {
                    submitted = true;
                    break;
                }
                Ok(v) if v == "bad-action" => {
                    return Err(AuthError::query("浏览器认证表单指向了其他站点"))
                }
                Ok(_) => {}
                Err(e) => return Err(e),
            }
        }
        if !submitted {
            return Err(AuthError::interaction(
                "浏览器未找到登录表单，请检查门户或风控状态",
            ));
        }
        // RPC pumping executes intercepted form requests and the complete CAS ticket redirect.
        loop {
            let href = self.evaluate("location.href", None, op).await?;
            if let Some(url) = href.as_str().and_then(|s| Url::parse(s).ok()) {
                if url.origin() == self.http.base.origin() {
                    self.last = url;
                    self.ready(op).await?;
                    return Ok(());
                }
            }
            op.pause().await?;
        }
    }
}

#[cfg(test)]
mod lifecycle_tests {
    use super::*;

    async fn started() -> Browser {
        let config = Config {
            base: "http://127.0.0.1:1".into(),
            cas_host: "http://127.0.0.1:1".into(),
            ..Config::default()
        };
        let http = Transport::new(&config, true).unwrap();
        // A cold Chromium start on shared CI runners can exceed 10s.
        let op = Operation::new(Instant::now() + std::time::Duration::from_secs(30));
        Browser::start(http, &op).await.unwrap()
    }

    async fn cleaned(pid: u32, profile: &Path) {
        tokio::time::timeout(std::time::Duration::from_secs(3), async {
            loop {
                let mut gone = !profile.exists();
                #[cfg(target_os = "linux")]
                {
                    gone &= !Path::new(&format!("/proc/{pid}")).exists();
                }
                if gone {
                    return;
                }
                tokio::time::sleep(std::time::Duration::from_millis(10)).await;
            }
        })
        .await
        .unwrap_or_else(|_| panic!("owned browser {pid} cleanup timed out"));
    }

    #[tokio::test]
    #[ignore = "requires host-installed Chromium; no external network"]
    async fn dropping_browser_reaps_own_process_and_removes_own_profile() {
        let browser = started().await;
        let pid = browser._process.id();
        let profile = browser._process.profile_path().to_owned();
        assert!(profile.is_dir());
        // Chromium writes this file only when it listens on a debugging port.
        assert!(!profile.join("DevToolsActivePort").exists());
        drop(browser);
        cleaned(pid, &profile).await;
    }

    #[tokio::test]
    #[ignore = "requires host-installed Chromium; no external network"]
    async fn cancelled_browser_future_reaps_process_and_removes_profile() {
        let browser = started().await;
        let pid = browser._process.id();
        let profile = browser._process.profile_path().to_owned();
        let owned = async move {
            let _owned = browser;
            std::future::pending::<()>().await;
        };
        assert!(
            tokio::time::timeout(std::time::Duration::from_millis(20), owned)
                .await
                .is_err()
        );
        cleaned(pid, &profile).await;
    }

    #[tokio::test]
    #[ignore = "requires host-installed Chromium; no external network"]
    async fn closed_cdp_pipe_reaps_process_and_removes_profile() {
        let mut browser = started().await;
        let pid = browser._process.id();
        let profile = browser._process.profile_path().to_owned();
        let op = Operation::new(Instant::now() + std::time::Duration::from_secs(3));
        browser.pipe.close();
        assert!(browser.receive(&op).await.is_err());
        drop(browser);
        cleaned(pid, &profile).await;
    }
}

#[cfg(all(test, unix))]
#[path = "cdp_tests.rs"]
mod cdp_tests;
