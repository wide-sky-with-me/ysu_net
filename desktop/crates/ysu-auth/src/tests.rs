use super::*;
use crate::{
    crypto::encrypt_with_material,
    protocol::{LoginForm, Snapshot},
    transport::{Operation, Transport, RESPONSE_LIMIT},
};
use aes::cipher::{block_padding::Pkcs7, BlockDecryptMut, KeyIvInit};
use base64::{engine::general_purpose::STANDARD, Engine};
use reqwest::{header::HeaderMap, Method};
use serde_json::{json, Value};
use std::{
    collections::BTreeMap,
    io::{Read, Write},
    net::{TcpListener, TcpStream},
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc, Mutex as StdMutex,
    },
    thread,
    time::Duration,
};
use url::Url;

#[derive(Clone)]
struct Request {
    method: String,
    path: String,
    headers: BTreeMap<String, String>,
    body: Vec<u8>,
}
struct Response {
    status: u16,
    body: Vec<u8>,
    headers: Vec<(String, String)>,
    delay: Duration,
}
impl Response {
    fn json(v: Value) -> Self {
        Self::body(200, v.to_string().into_bytes(), "application/json")
    }
    fn body(status: u16, body: Vec<u8>, kind: &str) -> Self {
        Self {
            status,
            body,
            headers: vec![("Content-Type".into(), kind.into())],
            delay: Duration::ZERO,
        }
    }
    fn html(s: &str) -> Self {
        Self::body(200, s.as_bytes().to_vec(), "text/html;charset=utf-8")
    }
    fn redirect(url: &str) -> Self {
        let mut r = Self::html("");
        r.status = 302;
        r.headers.push(("Location".into(), url.into()));
        r
    }
    fn cookie(mut self, s: &str) -> Self {
        self.headers.push(("Set-Cookie".into(), s.into()));
        self
    }
}
struct Server {
    address: String,
    stopped: Arc<AtomicBool>,
    thread: Option<thread::JoinHandle<()>>,
}
impl Server {
    fn new(handler: Arc<dyn Fn(Request) -> Response + Send + Sync>) -> Self {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap().to_string();
        let stopped = Arc::new(AtomicBool::new(false));
        let stop = stopped.clone();
        let thread = thread::spawn(move || {
            let mut workers = Vec::new();
            while let Ok((mut socket, _)) = listener.accept() {
                if stop.load(Ordering::SeqCst) {
                    break;
                }
                let handler = handler.clone();
                workers.push(thread::spawn(move || {
                    let _ = socket.set_read_timeout(Some(Duration::from_secs(5)));
                    // A client may reject a body without reading it while the test thread blocks
                    // in Drop; small socket buffers (macOS) would otherwise stall this write forever.
                    let _ = socket.set_write_timeout(Some(Duration::from_secs(5)));
                    let mut bytes = Vec::new();
                    let mut buf = [0u8; 4096];
                    let end = loop {
                        let n = socket.read(&mut buf).unwrap_or(0);
                        if n == 0 {
                            return;
                        }
                        bytes.extend_from_slice(&buf[..n]);
                        if let Some(i) = bytes.windows(4).position(|v| v == b"\r\n\r\n") {
                            break i + 4;
                        }
                        if bytes.len() > 64 * 1024 {
                            return;
                        }
                    };
                    let head = String::from_utf8_lossy(&bytes[..end]);
                    let mut lines = head.lines();
                    let line = lines.next().unwrap_or("");
                    let mut words = line.split_whitespace();
                    let method = words.next().unwrap_or("").to_owned();
                    let path = words.next().unwrap_or("/").to_owned();
                    let headers: BTreeMap<_, _> = lines
                        .filter_map(|s| s.split_once(':'))
                        .map(|(k, v)| (k.to_ascii_lowercase(), v.trim().to_owned()))
                        .collect();
                    let length = headers
                        .get("content-length")
                        .and_then(|s| s.parse::<usize>().ok())
                        .unwrap_or(0);
                    if length > RESPONSE_LIMIT {
                        return;
                    }
                    while bytes.len() < end + length {
                        let n = socket.read(&mut buf).unwrap_or(0);
                        if n == 0 {
                            return;
                        }
                        bytes.extend_from_slice(&buf[..n]);
                    }
                    let request = Request {
                        method,
                        path,
                        headers,
                        body: bytes[end..end + length].to_vec(),
                    };
                    let response = handler(request);
                    thread::sleep(response.delay);
                    let chunked = response.headers.iter().any(|(k, v)| {
                        k.eq_ignore_ascii_case("Transfer-Encoding") && v == "chunked"
                    });
                    let mut out = format!(
                        "HTTP/1.1 {} fixture\r\nConnection: close\r\n",
                        response.status
                    );
                    if !chunked {
                        out.push_str(&format!("Content-Length: {}\r\n", response.body.len()));
                    }
                    for (k, v) in response.headers {
                        out.push_str(&format!("{k}: {v}\r\n"));
                    }
                    out.push_str("\r\n");
                    let _ = socket.write_all(out.as_bytes());
                    if chunked {
                        for chunk in response.body.chunks(4096) {
                            if write!(socket, "{:x}\r\n", chunk.len()).is_err() {
                                break;
                            }
                            if socket.write_all(chunk).is_err() {
                                break;
                            }
                            if socket.write_all(b"\r\n").is_err() {
                                break;
                            }
                        }
                        let _ = socket.write_all(b"0\r\n\r\n");
                    } else {
                        let _ = socket.write_all(&response.body);
                    }
                }));
            }
            for worker in workers {
                let _ = worker.join();
            }
        });
        Self {
            address,
            stopped,
            thread: Some(thread),
        }
    }
    fn url(&self) -> String {
        format!("http://{}", self.address)
    }
}
impl Drop for Server {
    fn drop(&mut self) {
        self.stopped.store(true, Ordering::SeqCst);
        let _ = TcpStream::connect(&self.address);
        if let Some(t) = self.thread.take() {
            t.join().unwrap();
        }
    }
}

struct State {
    base: String,
    cas: String,
    online: Option<String>,
    owner: String,
    null_raw_service: bool,
    selected: String,
    cas_required: bool,
    authenticated: bool,
    captcha: bool,
    dom_captcha: bool,
    risk: bool,
    cas_reject: u16,
    state_http: u16,
    state_override: Option<Value>,
    node_override: Option<Value>,
    state_failure_at: Option<usize>,
    offline_ack_only: bool,
    rejected_service: Option<String>,
    failure_owner: bool,
    failure_unknown: bool,
    wrong_service: Option<String>,
    oversized: bool,
    meta: bool,
    requests: Vec<Request>,
    navigation_hops: usize,
    navigation_loop: bool,
    race_at: Option<(usize, String, String)>,
    poison_sid: bool,
}
impl Default for State {
    fn default() -> Self {
        Self {
            base: String::new(),
            cas: String::new(),
            online: None,
            owner: "fixture-user".into(),
            null_raw_service: false,
            selected: "校园网".into(),
            cas_required: false,
            authenticated: false,
            captcha: false,
            dom_captcha: false,
            risk: false,
            cas_reject: 0,
            state_http: 200,
            state_override: None,
            node_override: None,
            state_failure_at: None,
            offline_ack_only: false,
            rejected_service: None,
            failure_owner: false,
            failure_unknown: false,
            wrong_service: None,
            oversized: false,
            meta: false,
            requests: Vec::new(),
            navigation_hops: 0,
            navigation_loop: false,
            race_at: None,
            poison_sid: false,
        }
    }
}
struct Fixture {
    _portal: Server,
    _cas: Server,
    state: Arc<StdMutex<State>>,
    config: Config,
}
impl Fixture {
    fn new() -> Self {
        let state = Arc::new(StdMutex::new(State::default()));
        let handler_state = state.clone();
        let handler = Arc::new(move |r: Request| respond(&mut handler_state.lock().unwrap(), r));
        let portal = Server::new(handler.clone());
        let cas = Server::new(handler);
        {
            let mut s = state.lock().unwrap();
            s.base = portal.url();
            s.cas = cas.url();
        }
        let config = Config {
            username: "fixture-user".into(),
            password: " p@ss 密码 ".into(),
            base: portal.url(),
            cas_host: cas.url(),
            operation_timeout: 3,
            ..Config::default()
        };
        Self {
            _portal: portal,
            _cas: cas,
            state,
            config,
        }
    }
    fn client(&self) -> AuthClient {
        AuthClient::new_local_fixture(self.config.clone()).unwrap()
    }
    fn mutate(&self, f: impl FnOnce(&mut State)) {
        f(&mut self.state.lock().unwrap());
    }
    fn count(&self, path: &str) -> usize {
        self.state
            .lock()
            .unwrap()
            .requests
            .iter()
            .filter(|r| r.path.starts_with(path))
            .count()
    }
    fn selections(&self) -> Vec<String> {
        self.state
            .lock()
            .unwrap()
            .requests
            .iter()
            .filter(|r| r.path.starts_with("/eportal/network/serviceLogin"))
            .map(|r| {
                serde_json::from_slice::<Value>(&r.body).unwrap()["service"]
                    .as_str()
                    .unwrap()
                    .to_owned()
            })
            .collect()
    }
}
fn status_value(s: &State) -> Value {
    match &s.online {
        Some(service) => {
            if s.null_raw_service {
                return json!({"data":{"portalOnlineUserInfo":{"result":"success",
                    "realServiceName":null,"service":service,"userId":s.owner}}});
            }
            json!({"data":{"portalOnlineUserInfo":{"result":"success","realServiceName":service,"service":"opaque-id","userId":s.owner,"userName":"Fixture Name","userIp":"192.0.2.1","ssid":"fixture-wifi","userIndex":"private-session"}}})
        }
        None => {
            json!({"data":{"portalOnlineUserInfo":{"result":"fail","message":"dx.failed.user.offline"}}})
        }
    }
}
const FORM: &str = r#"<html><head><title>CAS fixture</title></head><body>
<form><input name=password value=irrelevant></form>
<form id=login action='/authserver/login' method=post>
<input id=username name=username><input id=password name=password type=password>
<input name=execution value='exec&amp;token'><input id=pwdEncryptSalt value='0123456789abcdef'>
<input name=disabled value=bad disabled><input type=checkbox name=unchecked value=bad>
<input type=checkbox name=checked checked value=good><input name=captcha value='' type=hidden>
<button id=login_submit type=submit>登录</button></form><div id=captchaDiv style='display:none'></div>
<script>document.querySelector('#login').addEventListener('submit',async e=>{e.preventDefault();const f=e.target;const enc=new TextEncoder();const k=await crypto.subtle.importKey('raw',enc.encode('0123456789abcdef'),{name:'AES-CBC'},false,['encrypt']);const v=enc.encode('A'.repeat(64)+f.password.value);const result=await crypto.subtle.encrypt({name:'AES-CBC',iv:enc.encode('abcdefghijklmnop')},k,v);f.password.value=btoa(String.fromCharCode(...new Uint8Array(result)));f.action='/authserver/login'+location.search;HTMLFormElement.prototype.submit.call(f);});</script>
</body></html>"#;
fn respond(s: &mut State, r: Request) -> Response {
    s.requests.push(r.clone());
    let url = Url::parse(&format!("http://fixture{}", r.path)).unwrap();
    let path = url.path();
    match path {
        "/eportal/index.jsp" | "/eportal/redirect.jsp" => {
            if s.navigation_hops > 0 || s.navigation_loop {
                return Response::html("<script>location.assign('/nav/0');</script>");
            }
            let next = format!("{}/portal/portal-main?sessionId=fixture-session&userIp=192.0.2.1&ssid=fixture-wifi",s.base);
            if s.meta {
                Response::html(&format!("<meta http-equiv=refresh content='0;url={next}'>"))
            } else {
                Response::redirect(&next)
                    .cookie("JSESSIONID=portal-cookie; Path=/; HttpOnly")
                    .cookie("XSRF-TOKEN=p%2Bq%20r; Path=/")
            }
        }
        _ if path.starts_with("/nav/") => {
            let hop = path.trim_start_matches("/nav/").parse::<usize>().unwrap();
            if hop < s.navigation_hops || s.navigation_loop {
                Response::html(&format!(
                    "<meta http-equiv=refresh content='0;url=/nav/{}'>",
                    hop + 1
                ))
            } else {
                Response::redirect(&format!(
                    "{}/portal/portal-main?sessionId=fixture-session",
                    s.base
                ))
            }
        }
        "/" => Response::html(&format!(
            "<script>location.href='{}/eportal/index.jsp';</script>",
            s.base
        )),
        "/portal/portal-main" => {
            if s.poison_sid {
                Response::html(
                    "<html><body>portal<img src='/fixture-asset?sessionId=decoy'></body></html>",
                )
            } else {
                Response::html("<html><body>fixture portal</body></html>")
            }
        }
        "/fixture-asset" => Response::body(200, b"fixture".to_vec(), "image/png"),
        "/eportal/adaptor/getOnlineUserInfo" => {
            if let Some((at, service, owner)) = s.race_at.clone() {
                let count = s
                    .requests
                    .iter()
                    .filter(|r| r.path.starts_with("/eportal/adaptor/getOnlineUserInfo"))
                    .count();
                if count == at {
                    s.online = Some(service);
                    s.owner = owner;
                }
            }
            if s.oversized {
                return Response::body(200, vec![b'x'; RESPONSE_LIMIT + 1], "application/json");
            }
            let mut payload = s.state_override.clone().unwrap_or_else(|| status_value(s));
            let checks = s
                .requests
                .iter()
                .filter(|request| {
                    request
                        .path
                        .starts_with("/eportal/adaptor/getOnlineUserInfo")
                })
                .count();
            if s.state_failure_at == Some(checks) {
                payload["result"] = "fail".into();
            }
            let mut out = Response::json(payload);
            out.status = s.state_http;
            out
        }
        "/eportal/workFlow/getCurrentNode" => Response::json(s.node_override.clone().unwrap_or_else(||
            json!({"data":{"currentNodePath":if s.cas_required&&!s.authenticated {"authenticate"} else {"serviceSelection"}}})
        )),
        "/cas-sso/login" => Response::html("seed"),
        "/cas-sso/clientredirect" => Response::redirect(&format!(
            "{}/authserver/login?service={}",
            s.cas,
            url::form_urlencoded::byte_serialize(
                format!("{}/cas-ticket-return", s.base).as_bytes()
            )
            .collect::<String>()
        )),
        "/authserver/checkNeedCaptcha.htl" => Response::json(json!({"isNeed":s.captcha})),
        "/authserver/login" if r.method == "GET" => {
            let body = if s.risk {
                "<title>IP被冻结</title>".into()
            } else if s.dom_captcha {
                FORM.replace("display:none", "display:block")
            } else {
                FORM.into()
            };
            Response::html(&body)
                .cookie("JSESSIONID=cas-cookie; Path=/authserver; HttpOnly")
                .cookie("XSRF-TOKEN=a%2Bb%20c; Path=/authserver")
        }
        "/authserver/login" if r.method == "POST" => {
            if s.cas_reject != 0 {
                return Response::body(
                    s.cas_reject,
                    b"<span id=msg>private-response</span>".to_vec(),
                    "text/html",
                );
            }
            let form: BTreeMap<_, _> = url::form_urlencoded::parse(&r.body)
                .map(|(k, v)| (k.into_owned(), v.into_owned()))
                .collect();
            let encrypted = form.get("password").and_then(|s| STANDARD.decode(s).ok());
            // CBC's unknown IV only affects block 1; decrypt the tail to verify the full password.
            let valid_password = encrypted
                .and_then(|ct| {
                    cbc::Decryptor::<aes::Aes128>::new_from_slices(b"0123456789abcdef", &[0; 16])
                        .ok()
                        .and_then(|cipher| cipher.decrypt_padded_vec_mut::<Pkcs7>(&ct).ok())
                })
                .is_some_and(|plain| plain.get(64..) == Some(" p@ss 密码 ".as_bytes()));
            let valid = form.get("username").is_some_and(|u| u == "fixture-user")
                && form.get("execution").is_some_and(|v| v == "exec&token")
                && !form.contains_key("disabled")
                && !form.contains_key("unchecked")
                && form.get("checked").is_some_and(|v| v == "good")
                && r.headers
                    .get("cookie")
                    .is_some_and(|c| c.contains("JSESSIONID=cas-cookie"))
                && r.headers.get("x-xsrf-token").is_some_and(|v| v == "a+b c")
                && url.query_pairs().any(|(k, _)| k == "service")
                && valid_password;
            if !valid {
                eprintln!("CAS fixture checks: user={} execution={} disabled={} unchecked={} checked={} cookie={} xsrf={} service={} password={}",
                    form.get("username").is_some_and(|u| u == "fixture-user"),
                    form.get("execution").is_some_and(|v| v == "exec&token"),
                    !form.contains_key("disabled"), !form.contains_key("unchecked"),
                    form.get("checked").is_some_and(|v| v == "good"),
                    r.headers.get("cookie").is_some_and(|c| c.contains("JSESSIONID=cas-cookie")),
                    r.headers.get("x-xsrf-token").is_some_and(|v| v == "a+b c"),
                    url.query_pairs().any(|(k, _)| k == "service"), valid_password);
                return Response::body(400, b"fixture validation failed".to_vec(), "text/html");
            }
            s.authenticated = true;
            Response::redirect(&format!(
                "{}/cas-ticket-return?ticket=private-ticket",
                s.base
            ))
        }
        "/cas-ticket-return" => {
            Response::html("ticket returned").cookie("JSESSIONID=portal-cookie; Path=/; HttpOnly")
        }
        "/eportal/network/serviceLogin" => {
            let v: Value = serde_json::from_slice(&r.body).unwrap();
            let target = v["service"].as_str().unwrap();
            if s.rejected_service.as_deref() == Some(target) {
                if s.failure_owner {
                    s.online = Some(target.into());
                    s.owner = "other-account".into();
                }
                if s.failure_unknown {
                    s.state_override = Some(
                        json!({"data":{"portalOnlineUserInfo":{"result":"fail","message":"unknown-error"}}}),
                    );
                }
                return Response::json(
                    json!({"code":200,"data":{"online":false,"message":"portal认证失败：账号已达到同时在线用户数量上限 private-account"}}),
                );
            }
            s.selected = target.into();
            Response::json(json!({"result":"success"}))
        }
        "/eportal/network/userOnline" => {
            s.online = Some(
                s.wrong_service
                    .clone()
                    .unwrap_or_else(|| s.selected.clone()),
            );
            Response::json(json!({"result":"success"}))
        }
        "/portal/entry/pc/terminalLoad" => Response::html("terminal loaded"),
        "/portal/entry/pc/finish;flowParams=undefined;from=" => Response::html("finish loaded"),
        "/sam/api/protected/guest/enableConfig/info" => {
            Response::json(json!({"code":200})).cookie("JSESSIONID=sam-cookie; Path=/sam; HttpOnly")
        }
        "/eportal/network/offline" => {
            if r.headers.get("cookie").map(String::as_str) != Some("JSESSIONID=sam-cookie") {
                return Response::body(401, b"cookie missing".to_vec(), "text/plain");
            }
            if !s.offline_ack_only {
                s.online = None;
            }
            Response::json(json!({"code":200}))
        }
        "/eportal/operator/getAccountInfo" => Response::json(
            json!({"data":{"data":{"name":"Fixture Person","accountInfo":[{"title":"剩余流量","content":"1024 MB","link":"https://example.invalid/?token=private"},{"title":"套餐&余额","content":0},{"title":"在线设备","content":"1 台"}]}}}),
        ),
        _ => Response::body(404, Vec::new(), "text/plain"),
    }
}

#[test]
fn config_defaults_and_validation() {
    let default: Config = serde_json::from_value(json!({})).unwrap();
    default.validate().unwrap();
    assert_eq!(default.check_interval, 15);
    assert!(serde_json::from_value::<Config>(json!({"operation_timeout":-1})).is_err());
    assert!(serde_json::from_value::<Config>(json!({"password":"x","unknown":true})).is_err());
    for base in [
        "http://127.0.0.1:80",
        "https://user:private@example.invalid",
        "https://example.invalid/?token=private",
    ] {
        assert!(Config {
            base: base.into(),
            ..default.clone()
        }
        .validate()
        .is_err());
    }
    assert!(Config {
        max_retry_interval: 1,
        ..default.clone()
    }
    .validate()
    .is_err());
    let secret = Config {
        username: "private-user".into(),
        password: "private-password".into(),
        ..default
    };
    assert!(!format!("{secret:?}").contains("private"));
}
#[test]
fn aes_cas_matches_independent_openssl_vector() {
    let encrypted = encrypt_with_material(
        " p@ss 密码 ",
        b"0123456789abcdef",
        &[b'A'; 64],
        b"abcdefghijklmnop",
    )
    .unwrap();
    assert_eq!(encrypted,"DMGz6tROv6ESSVXiQAgIOmBrwrpXnhA50MFnZCf+mSfJz9oXR8JkzjrZCml6P4c2dz8RH71xU1Sb9RHSPLzDXYhzef8jUXeXxIRoYsYRxQ0=");
}
#[test]
fn aes_pkcs7_and_key_lengths() {
    for (key_len, password) in [(16, ""), (24, "0123456789abcdef"), (32, "unicode 密码")] {
        let key = vec![b'K'; key_len];
        let ct = STANDARD
            .decode(encrypt_with_material(password, &key, &[b'A'; 64], &[b'I'; 16]).unwrap())
            .unwrap();
        assert_eq!(ct.len(), (64 + password.len()) / 16 * 16 + 16);
        let pt = match key_len {
            16 => cbc::Decryptor::<aes::Aes128>::new_from_slices(&key, &[b'I'; 16])
                .unwrap()
                .decrypt_padded_vec_mut::<Pkcs7>(&ct)
                .unwrap(),
            24 => cbc::Decryptor::<aes::Aes192>::new_from_slices(&key, &[b'I'; 16])
                .unwrap()
                .decrypt_padded_vec_mut::<Pkcs7>(&ct)
                .unwrap(),
            _ => cbc::Decryptor::<aes::Aes256>::new_from_slices(&key, &[b'I'; 16])
                .unwrap()
                .decrypt_padded_vec_mut::<Pkcs7>(&ct)
                .unwrap(),
        };
        assert_eq!(&pt[64..], password.as_bytes());
    }
    assert!(encrypt_with_material("x", b"bad", &[b'A'; 64], &[b'I'; 16]).is_err());
}
#[tokio::test]
async fn status_without_credentials_and_known_offline() {
    let mut f = Fixture::new();
    f.config.username.clear();
    f.config.password.clear();
    assert!(!f.client().status().await.unwrap().online);
    f.mutate(|s| s.online = Some("中国联通".into()));
    assert_eq!(
        f.client().status().await.unwrap().service.as_deref(),
        Some("中国联通")
    );
    assert_eq!(f.count("/authserver/login"), 0);
}
#[tokio::test]
async fn unknown_state_never_authenticates() {
    for state in [
        json!({}),
        json!({"data":null}),
        json!({"data":{"portalOnlineUserInfo":{"result":"fail","message":"session expired"}}}),
    ] {
        let f = Fixture::new();
        f.mutate(|s| s.state_override = Some(state));
        assert_eq!(f.client().login().await.unwrap_err().code, QUERY_ERROR);
        assert_eq!(f.count("/eportal/network/serviceLogin"), 0);
    }
}
#[tokio::test]
async fn unauthorized_and_server_failure_are_distinct() {
    for (status, code) in [
        (401, INTERACTION_ERROR),
        (403, INTERACTION_ERROR),
        (429, QUERY_ERROR),
        (503, QUERY_ERROR),
    ] {
        let f = Fixture::new();
        f.mutate(|s| s.state_http = status);
        let error = f.client().status().await.unwrap_err();
        assert_eq!(error.code, code);
        assert!(!error.message.contains("fixture-session"));
    }
}
#[tokio::test]
async fn full_api_cas_login_cookies_xsrf_encryption_and_independent_verification() {
    let f = Fixture::new();
    f.mutate(|s| s.cas_required = true);
    let result = f.client().login().await.unwrap();
    assert!(result.online);
    assert_eq!(result.service.as_deref(), Some("校园网"));
    assert_eq!(f.count("/authserver/login"), 2);
    assert!(f.count("/eportal/adaptor/getOnlineUserInfo") >= 3);
    assert_eq!(f.selections(), vec!["校园网"]);
}
#[tokio::test]
async fn portal_meta_refresh_is_followed() {
    let f = Fixture::new();
    f.mutate(|s| s.meta = true);
    assert!(!f.client().status().await.unwrap().online);
    assert_eq!(f.count("/portal/portal-main"), 1);
}
#[tokio::test]
async fn cas_captcha_and_risk_never_submit() {
    for kind in 0..3 {
        let f = Fixture::new();
        f.mutate(|s| {
            s.cas_required = true;
            s.captcha = kind == 0;
            s.dom_captcha = kind == 1;
            s.risk = kind == 2;
        });
        let e = f.client().login().await.unwrap_err();
        assert_eq!(e.code, INTERACTION_ERROR);
        let posts = f
            .state
            .lock()
            .unwrap()
            .requests
            .iter()
            .filter(|r| r.method == "POST" && r.path.starts_with("/authserver/login"))
            .count();
        assert_eq!(posts, 0);
    }
}
#[tokio::test]
async fn cas_rejection_is_redacted_and_retryable_http_is_query_error() {
    for (http, code) in [(200, INTERACTION_ERROR), (503, QUERY_ERROR)] {
        let f = Fixture::new();
        f.mutate(|s| {
            s.cas_required = true;
            s.cas_reject = http;
        });
        let e = f.client().login().await.unwrap_err();
        assert_eq!(e.code, code);
        assert!(!e.message.contains("private-response"));
        assert!(!e.message.contains("密码 "));
        assert_eq!(f.selections().len(), 0);
    }
}
#[tokio::test]
async fn login_verifies_actual_service_and_account() {
    let f = Fixture::new();
    f.mutate(|s| s.wrong_service = Some("中国移动".into()));
    assert_eq!(f.client().login().await.unwrap_err().code, OPERATION_ERROR);
    let f = Fixture::new();
    f.mutate(|s| s.owner = "other-account".into());
    assert_eq!(f.client().login().await.unwrap_err().code, OPERATION_ERROR);
}
#[tokio::test]
async fn already_online_other_account_preserved_in_all_mutations() {
    for action in 0..3 {
        let f = Fixture::new();
        f.mutate(|s| {
            s.online = Some("校园网".into());
            s.owner = "other-account".into();
        });
        let client = f.client();
        let result = match action {
            0 => client.login().await,
            1 => client.logout().await,
            _ => client.switch_service("中国移动").await,
        };
        assert_eq!(result.unwrap_err().code, OPERATION_ERROR);
        assert_eq!(f.count("/eportal/network/"), 0);
    }
}
#[tokio::test]
async fn same_service_switch_and_missing_credentials_are_non_destructive() {
    let mut f = Fixture::new();
    f.mutate(|s| s.online = Some("中国移动".into()));
    assert!(f.client().switch_service("中国移动").await.unwrap().online);
    assert_eq!(f.count("/eportal/network/"), 0);
    f.config.password.clear();
    let before = f.state.lock().unwrap().requests.len();
    assert_eq!(
        f.client().logout().await.unwrap_err().code,
        INTERACTION_ERROR
    );
    assert_eq!(
        f.client().login().await.unwrap_err().code,
        INTERACTION_ERROR
    );
    assert_eq!(
        f.client()
            .switch_service("中国移动")
            .await
            .unwrap_err()
            .code,
        INTERACTION_ERROR
    );
    assert_eq!(f.state.lock().unwrap().requests.len(), before);
}
#[tokio::test]
async fn node_business_failure_never_submits_service_actions() {
    let fixture: Value =
        serde_json::from_str(include_str!("../../../../tests/fixtures/flow-node.json")).unwrap();
    for case in fixture["cases"].as_array().unwrap() {
        let f = Fixture::new();
        f.mutate(|state| state.node_override = Some(case["payload"].clone()));
        if case["valid"] == true {
            assert!(f.client().login().await.unwrap().online);
        } else {
            let error = f.client().login().await.unwrap_err();
            assert_eq!(error.code, QUERY_ERROR, "{}", case["id"]);
            assert_eq!(f.count("/eportal/network/"), 0, "{}", case["id"]);
            assert_eq!(f.count("/cas-sso/"), 0, "{}", case["id"]);
        }
    }
}

#[tokio::test]
async fn outer_business_failure_during_each_logout_preflight_never_posts_offline() {
    for at in [1, 2] {
        let f = Fixture::new();
        f.mutate(|state| {
            state.online = Some("校园网".into());
            state.state_failure_at = Some(at);
        });
        assert_eq!(f.client().logout().await.unwrap_err().code, QUERY_ERROR);
        assert_eq!(f.count("/eportal/network/offline"), 0);
        assert_eq!(f.state.lock().unwrap().online.as_deref(), Some("校园网"));
    }
}
#[tokio::test]
async fn conflicting_outer_or_inner_envelopes_do_not_become_online() {
    for layer in 0..3 {
        for (key, value) in [
            ("result", json!("fail")),
            ("code", json!(500)),
            ("success", json!(false)),
        ] {
            let f = Fixture::new();
            f.mutate(|state| {
                state.online = Some("校园网".into());
                let mut payload = status_value(state);
                let target = match layer {
                    0 => &mut payload,
                    1 => &mut payload["data"],
                    _ => &mut payload["data"]["portalOnlineUserInfo"],
                };
                target[key] = value;
                state.state_override = Some(payload);
            });
            assert_eq!(f.client().status().await.unwrap_err().code, QUERY_ERROR);
            assert_eq!(f.client().logout().await.unwrap_err().code, QUERY_ERROR);
            assert_eq!(f.count("/eportal/network/offline"), 0);
        }
    }
}
#[tokio::test]
async fn logout_uses_sam_cookie_and_independently_confirms() {
    let f = Fixture::new();
    f.mutate(|s| s.online = Some("校园网".into()));
    assert!(!f.client().logout().await.unwrap().online);
    let s = f.state.lock().unwrap();
    let offline = s
        .requests
        .iter()
        .position(|r| r.path.starts_with("/eportal/network/offline"))
        .unwrap();
    assert!(s.requests[offline + 1..]
        .iter()
        .any(|r| r.path.starts_with("/eportal/adaptor/getOnlineUserInfo")));
    assert!(s.requests[..offline]
        .iter()
        .any(|r| r.path.starts_with("/sam/api/")));
}
#[tokio::test]
async fn logout_ack_alone_is_not_success() {
    let mut f = Fixture::new();
    f.config.operation_timeout = 1;
    f.mutate(|s| {
        s.online = Some("校园网".into());
        s.offline_ack_only = true;
    });
    assert_eq!(f.client().logout().await.unwrap_err().code, OPERATION_ERROR);
    assert_eq!(f.count("/eportal/network/offline"), 1);
}
#[tokio::test]
async fn switch_independently_verifies_and_does_not_change_config() {
    let f = Fixture::new();
    f.mutate(|s| s.online = Some("校园网".into()));
    let status = f.client().switch_service("中国移动").await.unwrap();
    assert_eq!(status.service.as_deref(), Some("中国移动"));
    assert_eq!(f.config.service, "校园网");
    assert_eq!(f.count("/eportal/network/offline"), 1);
}
#[tokio::test]
async fn failed_switch_restores_actual_previous_service_once() {
    let f = Fixture::new();
    f.mutate(|s| {
        s.online = Some("中国联通".into());
        s.rejected_service = Some("中国移动".into());
    });
    let error = f.client().switch_service("中国移动").await.unwrap_err();
    assert_eq!(error.code, INTERACTION_ERROR);
    assert!(error.message.contains("已独立确认恢复"));
    assert!(!error.message.contains("private-account"));
    assert_eq!(f.selections(), vec!["中国移动", "中国联通"]);
    assert_eq!(f.state.lock().unwrap().online.as_deref(), Some("中国联通"));
}
#[tokio::test]
async fn failed_switch_unknown_or_other_account_stops_recovery() {
    for other in [true, false] {
        let f = Fixture::new();
        f.mutate(|s| {
            s.online = Some("校园网".into());
            s.rejected_service = Some("中国移动".into());
            s.failure_owner = other;
            s.failure_unknown = !other;
        });
        let error = f.client().switch_service("中国移动").await.unwrap_err();
        assert!(error.message.contains("恢复未确认"));
        assert_eq!(f.selections(), vec!["中国移动"]);
        assert_eq!(f.count("/eportal/network/offline"), 1);
    }
}
#[tokio::test]
async fn info_preserves_zero_and_portal_units_without_session_links() {
    let f = Fixture::new();
    f.mutate(|s| s.online = Some("校园网".into()));
    let summary = f.client().info().await.unwrap();
    assert_eq!(summary["items"][0], json!(["剩余流量", "1024 MB"]));
    assert_eq!(summary["items"][1], json!(["套餐与余额", "0"]));
    let output = summary.to_string();
    assert!(!output.contains("private"));
    assert!(!output.contains("link"));
}
#[test]
fn account_empty_html_control_and_nested_boundaries() {
    let online = json!({"data":{"portalOnlineUserInfo":{"result":"success","service":"校园网","userId":"u"}}});
    for value in [
        Value::Null,
        json!(""),
        json!(" "),
        json!({}),
        json!([]),
        json!(false),
    ] {
        let account = json!({"data":{"accountInfo":null,"data":{"accountInfo":[{"title":"余额","content":value}]}}});
        assert_eq!(presentation::summary(&online, &account)["items"], json!([]));
    }
    let content = json!(
        "<b>12</b>&nbsp;GB<script>hidden</script>\u{1b}[31m\u{1b}]8;;https://private.invalid\u{7}"
    );
    assert_eq!(presentation::text(&content), "12 GB");
    assert_eq!(presentation::text(&json!(0)), "0");
    assert_eq!(presentation::text(&json!("12\nGB")), "12 GB");
}
#[tokio::test]
async fn null_raw_service_login_and_switch_verify_the_actual_service() {
    let f = Fixture::new();
    f.mutate(|state| state.null_raw_service = true);
    let client = f.client();
    assert_eq!(
        client.login().await.unwrap().service.as_deref(),
        Some("校园网")
    );
    assert_eq!(
        client.login().await.unwrap().service.as_deref(),
        Some("校园网")
    );
    assert_eq!(f.selections(), vec!["校园网"]);
    assert_eq!(
        client
            .switch_service("中国移动")
            .await
            .unwrap()
            .service
            .as_deref(),
        Some("中国移动")
    );
    assert_eq!(f.count("/eportal/network/offline"), 1);
    assert_eq!(f.selections(), vec!["校园网", "中国移动"]);
}

#[tokio::test]
async fn null_raw_service_failed_switch_verifies_original_service_recovery() {
    let f = Fixture::new();
    f.mutate(|state| {
        state.null_raw_service = true;
        state.online = Some("校园网".into());
        state.rejected_service = Some("中国移动".into());
    });
    let error = f.client().switch_service("中国移动").await.unwrap_err();
    assert_eq!(error.code, INTERACTION_ERROR);
    assert!(error.message.contains("已独立确认恢复原服务"));
    assert_eq!(
        f.client().status().await.unwrap().service.as_deref(),
        Some("校园网")
    );
    assert_eq!(f.count("/eportal/network/offline"), 1);
}

#[tokio::test]
async fn shared_unknown_service_fields_never_authenticate_or_switch() {
    for case in crate::service_tests::cases()
        .into_iter()
        .filter(|case| case.expected.is_none())
    {
        for switching in [false, true] {
            let f = Fixture::new();
            f.mutate(|state| state.state_override = Some(case.online("fixture-user")));
            let client = f.client();
            let result = if switching {
                client.switch_service("中国移动").await
            } else {
                client.login().await
            };
            assert_eq!(result.unwrap_err().code, QUERY_ERROR, "{}", case.id);
            assert_eq!(f.count("/eportal/network/"), 0, "{}", case.id);
        }
    }
}

#[test]
fn recognized_service_and_authoritative_account_boundaries() {
    for info in [
        json!({"result":"success"}),
        json!({"result":"success","service":"unknown"}),
        json!({"result":"success","service":"校园网","realServiceName":"中国移动"}),
    ] {
        assert_eq!(
            Snapshot::parse(json!({"data":{"portalOnlineUserInfo":info}}))
                .err()
                .unwrap()
                .code,
            QUERY_ERROR
        );
    }
    let snapshot=Snapshot::parse(json!({"data":{"portalOnlineUserInfo":{"result":"success","service":"校园网","userName":"fixture-user","userId":"other"}}})).unwrap();
    assert!(snapshot.require_owner("fixture-user").is_err());
}
#[tokio::test]
async fn response_limit_rejects_oversized_body() {
    let f = Fixture::new();
    f.mutate(|s| s.oversized = true);
    assert_eq!(f.client().status().await.unwrap_err().code, QUERY_ERROR);
}
#[tokio::test]
async fn redirects_loop_cross_origin_and_body_preservation_are_bounded() {
    let server = Server::new(Arc::new(|r| {
        match Url::parse(&format!("http://fixture{}", r.path))
            .unwrap()
            .path()
        {
            "/loop" => Response::redirect("/loop"),
            "/foreign" => Response::redirect("http://127.0.0.1:1/collect"),
            "/flow" => Response::redirect("/final?flowSessionId=only-history"),
            _ => Response::html("done"),
        }
    }));
    let config = Config {
        base: server.url(),
        cas_host: server.url(),
        ..Config::default()
    };
    let http = Transport::new(&config, true).unwrap();
    let op = Operation::new(Instant::now() + Duration::from_secs(3));
    assert!(http
        .get(http.endpoint("loop").unwrap(), &op)
        .await
        .unwrap_err_for_test()
        .message
        .contains("重定向"));
    assert!(http
        .get(http.endpoint("foreign").unwrap(), &op)
        .await
        .is_err());
    let r = http.get(http.endpoint("flow").unwrap(), &op).await.unwrap();
    assert_eq!(r.chain.len(), 2);
    assert_eq!(
        protocol::query(&r.url, "flowSessionId").as_deref(),
        Some("only-history")
    );
}
// Avoid Debug on any HTTP response/session even in failing assertions.
trait ErrorForTest<T> {
    fn unwrap_err_for_test(self) -> AuthError;
}
impl<T> ErrorForTest<T> for Result<T, AuthError> {
    fn unwrap_err_for_test(self) -> AuthError {
        match self {
            Err(e) => e,
            Ok(_) => panic!("expected fixed error"),
        }
    }
}
#[tokio::test]
async fn deadline_covers_http_and_lock_queue() {
    let server = Server::new(Arc::new(|_| {
        let mut r = Response::html("delayed");
        r.delay = Duration::from_millis(300);
        r
    }));
    let config = Config {
        base: server.url(),
        cas_host: server.url(),
        ..Config::default()
    };
    let http = Transport::new(&config, true).unwrap();
    let op = Operation::new(Instant::now() + Duration::from_millis(50));
    assert!(http.get(http.endpoint("slow").unwrap(), &op).await.is_err());
    let mut f = Fixture::new();
    f.config.operation_timeout = 1;
    let client = f.client();
    let _lock = client.lock.lock().await;
    assert_eq!(
        client.status().await.unwrap_err().message,
        AuthError::timeout().message
    );
    assert_eq!(f.state.lock().unwrap().requests.len(), 0);
}
#[tokio::test]
async fn form_action_host_and_successful_controls_are_verified() {
    let f = Fixture::new();
    let http = Transport::new(&f.config, true).unwrap();
    let page = http
        .cas_endpoint("authserver/login?service=fixture")
        .unwrap();
    let form = LoginForm::parse(FORM, &page, &http).unwrap();
    assert_eq!(
        form.fields.get("execution").map(String::as_str),
        Some("exec&token")
    );
    assert!(!form.fields.contains_key("disabled"));
    assert!(!form.fields.contains_key("unchecked"));
    assert!(form.fields.contains_key("checked"));
    let malicious = FORM.replace(
        "action='/authserver/login'",
        "action='https://outside.invalid/login'",
    );
    assert!(LoginForm::parse(&malicious, &page, &http).is_err());
}

#[tokio::test]
#[ignore = "requires host-installed Chromium; runs against loopback fixtures only"]
async fn chromium_cdp_full_cas_login_and_logout_fixture() {
    assert!(
        browser::system_chromium().is_some(),
        "host Chromium prerequisite"
    );
    let mut f = Fixture::new();
    f.config.backend = "browser".into();
    f.config.operation_timeout = 20;
    f.mutate(|s| s.cas_required = true);
    let client = f.client();
    let status = client.login().await.unwrap();
    assert!(status.online);
    assert_eq!(status.service.as_deref(), Some("校园网"));
    assert!(!client.logout().await.unwrap().online);
}
#[tokio::test]
#[ignore = "requires host-installed Chromium; runs against loopback fixtures only"]
async fn chromium_cdp_captcha_and_no_fallback_fixture() {
    let mut f = Fixture::new();
    f.config.backend = "browser".into();
    f.config.operation_timeout = 20;
    f.mutate(|s| {
        s.cas_required = true;
        s.captcha = true;
    });
    assert_eq!(
        f.client().login().await.unwrap_err().code,
        INTERACTION_ERROR
    );
    assert_eq!(f.selections().len(), 0);
}

#[path = "diagnostic_tests.rs"]
mod diagnostics;
#[path = "regression_tests.rs"]
mod regression;
