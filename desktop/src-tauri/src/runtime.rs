//! In-process desktop state. Authentication is serialized independently of settings and snapshots.
//! Decision: .agents/notes/proposals/desktop/2026-10-14-rust-desktop.md
use crate::storage::{valid_accent, Prefs, RunGuard, Store, CONFIG_ERROR, EXTERNAL};
#[path = "account_runtime.rs"]
mod account_runtime;
use account_runtime::{account_state, Rotation};
use chrono::{SecondsFormat, Utc};
use rand::Rng;
use serde_json::{json, Map, Value};
use std::{
    collections::VecDeque,
    sync::{
        atomic::{AtomicBool, AtomicU64, Ordering},
        Arc, Mutex,
    },
    time::Duration,
};
use tokio::{
    sync::{mpsc, watch, Mutex as AsyncMutex},
    time::Instant,
};
use ysu_auth::{
    AuthClient, AuthDiagnostic, AuthError, Config, DiagnosticOperation, DiagnosticReason,
    DiagnosticStage, Status, SERVICES,
};

const MAX_REQUEST: usize = 32 * 1024;
const QUEUE_SIZE: usize = 64;
const STOPPED: &str = "后台运行器已停止";
const CONFIG_FIELDS: &[&str] = &[
    "username",
    "password",
    "service",
    "backend",
    "base",
    "cas_host",
    "verify_tls",
    "check_interval",
    "retry_interval",
    "max_retry_interval",
    "operation_timeout",
];
type Sink = Arc<dyn Fn(Value) + Send + Sync>;

#[derive(Clone, Debug)]
pub(crate) enum Action {
    Status,
    Info,
    Login,
    Logout,
    Switch(String),
    SwitchAccount(String),
    SetService(String),
}

impl Action {
    fn name(&self) -> &'static str {
        match self {
            Self::Status => "status",
            Self::Info => "info",
            Self::Login => "login",
            Self::Logout => "logout",
            Self::Switch(_) => "switch_service",
            Self::SwitchAccount(_) => "switch_account",
            Self::SetService(_) => "set_service",
        }
    }
}

pub fn valid_request(command: &str, args: &Value) -> bool {
    let Some(object) = args.as_object() else {
        return false;
    };
    if !serde_json::to_vec(args).is_ok_and(|v| v.len() <= MAX_REQUEST) {
        return false;
    }
    match command {
        "snapshot" | "diagnostics" => object.is_empty(),
        "browser_install" => {
            object.keys().all(|k| k == "cancel")
                && object.get("cancel").is_none_or(Value::is_boolean)
        }
        "action" => {
            if object.keys().any(|k| k != "name" && k != "value") {
                return false;
            }
            match object.get("name").and_then(Value::as_str) {
                Some("status" | "info" | "login" | "logout") => !object.contains_key("value"),
                Some("switch" | "set_service") => object
                    .get("value")
                    .and_then(Value::as_str)
                    .is_some_and(|v| SERVICES.contains(&v)),
                Some("switch_account") => object
                    .get("value")
                    .and_then(Value::as_str)
                    .is_some_and(crate::accounts::valid_id),
                Some("set_auto") => object.get("value").is_some_and(Value::is_boolean),
                _ => false,
            }
        }
        "save_account" => {
            object.keys().all(|k| {
                [
                    "id", "label", "username", "password", "service", "backend", "enabled",
                ]
                .contains(&k.as_str())
            }) && object
                .get("id")
                .is_none_or(|v| v.as_str().is_some_and(crate::accounts::valid_id))
                && ["label", "password"]
                    .iter()
                    .all(|k| object.get(*k).is_none_or(Value::is_string))
                && object.get("username").is_some_and(Value::is_string)
                && object
                    .get("service")
                    .and_then(Value::as_str)
                    .is_some_and(|v| SERVICES.contains(&v))
                && object
                    .get("backend")
                    .and_then(Value::as_str)
                    .is_some_and(|v| ["api", "browser"].contains(&v))
                && object.get("enabled").is_some_and(Value::is_boolean)
        }
        "delete_account" => {
            object.len() == 1
                && object
                    .get("id")
                    .and_then(Value::as_str)
                    .is_some_and(crate::accounts::valid_id)
        }
        "rotation" => object.len() == 1 && object.get("enabled").is_some_and(Value::is_boolean),
        "save_config" => {
            !object.is_empty()
                && object.iter().all(|(k, v)| {
                    CONFIG_FIELDS.contains(&k.as_str())
                        && match k.as_str() {
                            "verify_tls" => v.is_boolean(),
                            "check_interval" | "retry_interval" | "max_retry_interval"
                            | "operation_timeout" => {
                                v.as_u64().is_some_and(|v| (1..=86400).contains(&v))
                            }
                            "service" => v.as_str().is_some_and(|v| SERVICES.contains(&v)),
                            "backend" => {
                                v.as_str().is_some_and(|v| ["api", "browser"].contains(&v))
                            }
                            _ => v.is_string(),
                        }
                })
        }
        "save_prefs" => {
            !object.is_empty()
                && object.iter().all(|(k, v)| match k.as_str() {
                    "theme" => v
                        .as_str()
                        .is_some_and(|v| ["system", "light", "dark"].contains(&v)),
                    "accent" => v.as_str().is_some_and(valid_accent),
                    "close_to_tray" | "autostart_minimized" => v.is_boolean(),
                    _ => false,
                })
        }
        _ => false,
    }
}

fn public_error(code: i32) -> &'static str {
    match code {
        4 => "认证已暂停：请检查凭据或完成交互，修改配置或手动登录后恢复",
        3 => "操作未确认成功或在线账号不一致，请查询当前实际状态",
        _ => "查询未确认连接状态，请检查配置或稍后重试",
    }
}

fn local_auth_error(
    code: i32,
    operation: DiagnosticOperation,
    stage: DiagnosticStage,
    reason: DiagnosticReason,
) -> AuthError {
    let mut error = AuthError::new(code, "");
    error.diagnostic = AuthDiagnostic {
        operation,
        stage,
        reason,
    };
    error
}

fn diagnostic_detail(action: &str, phase: DiagnosticStage, error: &AuthError) -> String {
    // Serialize only closed enums. AuthError.message may contain server text or credentials.
    let diagnostic = serde_json::to_value(error.diagnostic()).expect("fixed diagnostic enums");
    let phase = serde_json::to_value(phase).expect("fixed diagnostic phase");
    format!(
        "action={action} phase={} code={} operation={} stage={} reason={}",
        phase.as_str().unwrap_or("unknown"),
        error.code,
        diagnostic["operation"].as_str().unwrap_or("unknown"),
        diagnostic["stage"].as_str().unwrap_or("unknown"),
        diagnostic["reason"].as_str().unwrap_or("unknown"),
    )
}

struct State {
    sequence: u64,
    config: Config,
    prefs: Prefs,
    status: Value,
    auto: Value,
    accounts: Value,
    rotation_intent: Option<bool>,
    busy: bool,
    busy_message: String,
    info: Value,
    info_error: String,
    logs: VecDeque<Value>,
    environment: Value,
    secrets: Vec<String>,
}

impl State {
    fn remember(&mut self, password: &str) {
        if !password.is_empty() && !self.secrets.iter().any(|v| v == password) {
            self.secrets.push(password.into());
            self.secrets.sort_by_key(|v| std::cmp::Reverse(v.len()));
        }
    }

    fn text(&self, input: &str) -> String {
        let mut text = input.to_owned();
        for secret in &self.secrets {
            text = text.replace(secret, "[redacted]");
        }
        text.chars()
            .filter(|c| !c.is_control() || *c == '\n' || *c == '\t')
            .take(2048)
            .collect()
    }

    fn scrub(&self, value: &mut Value) {
        match value {
            Value::String(text) => *text = self.text(text),
            Value::Array(values) => values.iter_mut().for_each(|v| self.scrub(v)),
            Value::Object(values) => values.values_mut().for_each(|v| self.scrub(v)),
            _ => {}
        }
    }

    fn snapshot(&self) -> Value {
        let mut config = serde_json::to_value(&self.config).expect("serializable config");
        config.as_object_mut().unwrap().remove("password");
        config["password_set"] = (!self.config.password.is_empty()).into();
        let mut value = json!({
            "sequence": self.sequence, "config": config, "prefs": self.prefs,
            "status": self.status, "auto": self.auto, "busy": self.busy,
            "busy_message": self.text(&self.busy_message), "info": self.info,
            "info_error": self.text(&self.info_error), "logs": self.logs,
            "environment": self.environment, "accounts": self.accounts,
        });
        // Public identities must round-trip even when they happen to equal a password.
        for key in ["base", "cas_host"] {
            self.scrub(&mut value["config"][key]);
        }
        if let Some(status) = value["status"].as_object_mut() {
            for key in ["user", "ip", "message"] {
                let known_identity = key == "user"
                    && status.get(key).and_then(Value::as_str).is_some_and(|user| {
                        user == self.config.username
                            || self.accounts["items"].as_array().is_some_and(|items| {
                                items.iter().any(|item| item["username"] == user)
                            })
                    });
                if !known_identity {
                    if let Some(text) = status.get_mut(key) {
                        self.scrub(text);
                    }
                }
            }
        }
        if let Some(items) = value["accounts"]["items"].as_array_mut() {
            for item in items {
                self.scrub(&mut item["label"]);
            }
        }
        self.scrub(&mut value["accounts"]["message"]);
        self.scrub(&mut value["accounts"]["quota"]["message"]);
        self.scrub(&mut value["info"]);
        self.scrub(&mut value["auto"]["message"]);
        if let Some(logs) = value["logs"].as_array_mut() {
            for log in logs {
                self.scrub(&mut log["message"]);
            }
        }
        value
    }

    fn log(&mut self, level: &str, message: &str) {
        self.logs.push_back(
            json!({"timestamp": Utc::now().to_rfc3339_opts(SecondsFormat::Millis, true),
            "level": level, "message": self.text(message)}),
        );
        while self.logs.len() > 2000 {
            self.logs.pop_front();
        }
    }
}

#[derive(Default)]
struct AuthGate {
    active: bool,
    updating: bool,
}

struct AuthWork {
    gate: Arc<Mutex<AuthGate>>,
}

impl Drop for AuthWork {
    fn drop(&mut self) {
        self.gate.lock().unwrap().active = false;
    }
}

pub struct Runtime {
    store: Arc<Store>,
    state: Mutex<State>,
    publication: Mutex<()>,
    auth_gate: Arc<Mutex<AuthGate>>,
    sink: Sink,
    backend: Backend,
    sender: mpsc::Sender<Action>,
    stop: watch::Sender<bool>,
    control: watch::Sender<u64>,
    desired: AtomicBool,
    revision: AtomicU64,
    auto_version: AtomicU64,
    rotation_version: AtomicU64,
    rotation_enabled: AtomicBool,
    settings: AsyncMutex<()>,
    task: Mutex<Option<tauri::async_runtime::JoinHandle<()>>>,
    stopped: AtomicBool,
}

impl Runtime {
    pub(crate) fn new(
        store: Arc<Store>,
        sink: Sink,
    ) -> Result<(Arc<Self>, mpsc::Receiver<Action>), String> {
        let config = store.load_config(true)?;
        let prefs = store.load_prefs();
        let (accounts, passwords) = account_state(&store, &config);
        let rotation_enabled = accounts["auto_switch"].as_bool().unwrap_or(false);
        let backend = if store.demo {
            Backend::Demo(Arc::new(Mutex::new(Demo::default())))
        } else {
            Backend::Native
        };
        let (sender, receiver) = mpsc::channel(QUEUE_SIZE);
        let (stop, _) = watch::channel(false);
        let (control, _) = watch::channel(0);
        let desired = prefs.auto_reconnect;
        let mut state = State {
            sequence: 1,
            config,
            prefs,
            status: Value::Null,
            auto: json!({"state":"off", "message":"自动重连已关闭"}),
            busy: false,
            busy_message: String::new(),
            info: Value::Null,
            info_error: String::new(),
            accounts,
            rotation_intent: None,
            logs: VecDeque::new(),
            environment: environment(store.demo),
            secrets: Vec::new(),
        };
        state.remember(&state.config.password.clone());
        for password in passwords {
            state.remember(&password);
        }
        let runtime = Arc::new(Self {
            store,
            state: Mutex::new(state),
            publication: Mutex::new(()),
            auth_gate: Arc::new(Mutex::new(AuthGate::default())),
            sink,
            backend,
            sender,
            stop,
            control,
            desired: AtomicBool::new(desired),
            revision: AtomicU64::new(0),
            auto_version: AtomicU64::new(0),
            rotation_version: AtomicU64::new(0),
            rotation_enabled: AtomicBool::new(rotation_enabled),
            settings: AsyncMutex::new(()),
            task: Mutex::new(None),
            stopped: AtomicBool::new(false),
        });
        Ok((runtime, receiver))
    }

    fn begin_auth(&self) -> Result<AuthWork, String> {
        let mut gate = self.auth_gate.lock().unwrap();
        if gate.updating || self.stopped.load(Ordering::Acquire) || *self.stop.borrow() {
            return Err(STOPPED.into());
        }
        if gate.active {
            return Err("已有认证任务正在执行".into());
        }
        gate.active = true;
        Ok(AuthWork {
            gate: self.auth_gate.clone(),
        })
    }

    pub(crate) fn pause_for_update(&self) -> Result<(), String> {
        // This is the same short gate used before authentication config reads and network work.
        let mut gate = self.auth_gate.lock().unwrap();
        if gate.updating || self.stopped.load(Ordering::Acquire) || *self.stop.borrow() {
            return Err(STOPPED.into());
        }
        if gate.active || self.state.lock().unwrap().busy {
            return Err("认证任务进行中，请完成后再安装更新".into());
        }
        gate.updating = true;
        self.stop.send_replace(true);
        Ok(())
    }

    /// Called only on a newly created runtime before launch; does not publish an event.
    pub(crate) fn set_sequence_floor(&self, floor: u64) {
        let mut state = self.state.lock().unwrap();
        state.sequence = state.sequence.max(floor);
    }

    pub(crate) fn launch(self: &Arc<Self>, receiver: mpsc::Receiver<Action>) {
        (self.sink)(self.snapshot());
        let runtime = self.clone();
        *self.task.lock().unwrap() = Some(tauri::async_runtime::spawn(async move {
            Worker::new(runtime.clone(), receiver).run().await;
            runtime.stopped.store(true, Ordering::Release);
        }));
    }

    pub(crate) async fn persisted_prefs_for_smoke(&self) -> Result<Value, String> {
        let store = self.store.clone();
        self.blocking(move || {
            serde_json::to_value(store.load_prefs()).map_err(|_| CONFIG_ERROR.to_owned())
        })
        .await
    }

    pub fn snapshot(&self) -> Value {
        self.state.lock().unwrap().snapshot()
    }

    pub fn report_error(&self, message: &str) {
        self.update(|state| state.log("error", message));
    }

    fn update(&self, change: impl FnOnce(&mut State)) {
        let _publication = self.publication.lock().unwrap();
        if self.stopped.load(Ordering::Acquire) {
            return;
        }
        let value = {
            let mut state = self.state.lock().unwrap();
            if self.stopped.load(Ordering::Acquire) {
                return;
            }
            change(&mut state);
            // All account-data producers, including verified quota reads, clear obsolete read errors.
            if !state.info.is_null() {
                state.info_error.clear();
            }
            state.sequence += 1;
            state.snapshot()
        };
        // Tauri menu setters wait on the UI thread, which may read this snapshot.
        (self.sink)(value);
    }

    fn wake(&self) {
        let revision = self.revision.fetch_add(1, Ordering::AcqRel) + 1;
        self.control.send_replace(revision);
    }

    async fn blocking<T: Send + 'static>(
        &self,
        f: impl FnOnce() -> Result<T, String> + Send + 'static,
    ) -> Result<T, String> {
        let mut stop = self.stop.subscribe();
        if *stop.borrow() {
            return Err(STOPPED.into());
        }
        tokio::select! {
            biased;
            _ = stop.changed() => Err(STOPPED.into()),
            result = tokio::time::timeout(Duration::from_secs(4), tokio::task::spawn_blocking(f)) =>
                result.map_err(|_| "本地设置操作超时".to_owned())?
                    .map_err(|_| "本地设置操作失败".to_owned())?,
        }
    }

    async fn setting_guard(&self) -> Result<tokio::sync::MutexGuard<'_, ()>, String> {
        let mut stop = self.stop.subscribe();
        if *stop.borrow() {
            return Err(STOPPED.into());
        }
        tokio::select! {
            biased;
            _ = stop.changed() => Err(STOPPED.into()),
            result = tokio::time::timeout(Duration::from_secs(4), self.settings.lock()) =>
                result.map_err(|_| "设置请求较多，请稍后重试".to_owned()),
        }
    }

    async fn config(&self) -> Result<Config, String> {
        let _settings = self.setting_guard().await?;
        let store = self.store.clone();
        let (config, accounts, passwords) = self
            .blocking(move || {
                let config = store.load_config(true)?;
                let (accounts, passwords) = account_state(&store, &config);
                Ok((config, accounts, passwords))
            })
            .await?;
        self.update(|state| {
            self.apply_accounts(state, config.clone(), accounts, passwords);
        });
        Ok(config)
    }

    async fn save_config(&self, changes: Map<String, Value>) -> Result<Value, String> {
        let _settings = self.setting_guard().await?;
        if let Some(password) = changes.get("password").and_then(Value::as_str) {
            self.update(|state| state.remember(password));
        }
        let store = self.store.clone();
        let (config, accounts, passwords) = self
            .blocking(move || {
                let config = store.update_config(changes)?;
                let (accounts, passwords) = account_state(&store, &config);
                Ok((config, accounts, passwords))
            })
            .await?;
        self.update(|state| {
            self.apply_accounts(state, config, accounts, passwords);
            state.log("success", "配置已保存");
        });
        self.wake();
        Ok(self.snapshot())
    }

    async fn set_desired(&self, enabled: bool) -> Result<(), String> {
        let mut version = 0;
        self.update(|state| {
            version = self.auto_version.fetch_add(1, Ordering::AcqRel) + 1;
            // Disabling is immediate; enabling starts only after its intent is durable.
            if !enabled {
                self.desired.store(false, Ordering::Release);
                state.prefs.auto_reconnect = false;
                self.rotation_enabled.store(false, Ordering::Release);
                self.rotation_version.fetch_add(1, Ordering::AcqRel);
                state.rotation_intent = Some(false);
                state.accounts["auto_switch"] = false.into();
                state.accounts["message"] = "流量自动换号已关闭".into();
                state.auto = json!({"state":"off", "message":"自动重连已关闭"});
            }
        });
        self.wake();
        let _settings = self.setting_guard().await?;
        if self.auto_version.load(Ordering::Acquire) != version {
            return Ok(());
        }
        let store = self.store.clone();
        let prefs = self
            .blocking(move || {
                let prefs = store.update_prefs(
                    json!({"auto_reconnect":enabled})
                        .as_object()
                        .unwrap()
                        .clone(),
                )?;
                if !enabled {
                    store.save_rotation(false)?;
                }
                Ok(prefs)
            })
            .await?;
        self.update(|state| {
            if self.auto_version.load(Ordering::Acquire) == version {
                self.desired.store(enabled, Ordering::Release);
                state.prefs = prefs;
                if !enabled {
                    state.rotation_intent = None;
                }
            }
            state.prefs.auto_reconnect = self.desired.load(Ordering::Acquire);
        });
        self.wake();
        Ok(())
    }

    pub async fn request(&self, command: &str, args: Value) -> Result<Value, String> {
        if !valid_request(command, &args) {
            return Err("请求参数无效".into());
        }
        if self.stopped.load(Ordering::Acquire) || *self.stop.borrow() {
            return Err(STOPPED.into());
        }
        match command {
            "snapshot" => Ok(self.snapshot()),
            "diagnostics" | "browser_install" => {
                let demo = self.store.demo;
                let environment = self.blocking(move || Ok(environment(demo))).await?;
                self.update(|state| state.environment = environment);
                Ok(self.snapshot())
            }
            "save_account" | "delete_account" => self.change_accounts(command, args).await,
            "rotation" => self.set_rotation(args["enabled"].as_bool().unwrap()).await,
            "save_config" => self.save_config(args.as_object().unwrap().clone()).await,
            "save_prefs" => {
                let _settings = self.setting_guard().await?;
                let store = self.store.clone();
                let prefs = self
                    .blocking(move || store.update_prefs(args.as_object().unwrap().clone()))
                    .await?;
                self.update(|state| {
                    state.prefs = prefs;
                    state.prefs.auto_reconnect = self.desired.load(Ordering::Acquire);
                });
                Ok(self.snapshot())
            }
            "action" => {
                let mut intent_error = None;
                let action = match args["name"].as_str().unwrap() {
                    "set_auto" => {
                        self.set_desired(args["value"].as_bool().unwrap()).await?;
                        return Ok(self.snapshot());
                    }
                    "status" => Action::Status,
                    "info" => Action::Info,
                    "login" => Action::Login,
                    "logout" => {
                        // Stop auto first; a failed preference write must not discard the requested logout.
                        if let Err(error) = self.set_desired(false).await {
                            self.update(|state| state.log("error", "自动重连关闭意图保存失败"));
                            intent_error = Some(error);
                        }
                        Action::Logout
                    }
                    "switch_account" => {
                        Action::SwitchAccount(args["value"].as_str().unwrap().into())
                    }
                    "switch" => Action::Switch(args["value"].as_str().unwrap().into()),
                    "set_service" => Action::SetService(args["value"].as_str().unwrap().into()),
                    _ => unreachable!(),
                };
                self.sender.try_send(action).map_err(|error| match error {
                    mpsc::error::TrySendError::Full(_) => "后台任务队列已满，请稍后重试".to_owned(),
                    mpsc::error::TrySendError::Closed(_) => STOPPED.to_owned(),
                })?;
                if let Some(error) = intent_error {
                    Err(error)
                } else {
                    Ok(self.snapshot())
                }
            }
            _ => unreachable!(),
        }
    }

    pub fn force_stop(&self) {
        self.stop.send_replace(true);
        self.stopped.store(true, Ordering::Release);
        if let Some(task) = self.task.lock().unwrap().take() {
            task.abort();
        }
    }

    pub async fn shutdown(&self) {
        self.stop.send_replace(true);
        let task = self.task.lock().unwrap().take();
        if let Some(mut task) = task {
            if tokio::time::timeout(Duration::from_secs(3), &mut task)
                .await
                .is_err()
            {
                task.abort();
                let _ = tokio::time::timeout(Duration::from_secs(1), task).await;
            }
        }
        self.stopped.store(true, Ordering::Release);
    }
}

fn environment(demo: bool) -> Value {
    json!({"version":env!("CARGO_PKG_VERSION"), "rust":option_env!("YSU_RUST_VERSION").unwrap_or("unknown"),
        "runtime":"rust", "platform":std::env::consts::OS, "browser_available":demo || ysu_auth::browser_path().is_some(),
        "browser_component_available":true})
}

#[derive(Default)]
struct Reconnect {
    failures: u32,
    blocked: Option<String>,
}
impl Reconnect {
    fn identity(config: &Config) -> String {
        serde_json::to_string(&(
            &config.username,
            &config.password,
            &config.service,
            &config.backend,
        ))
        .expect("serializable credential identity")
    }
    fn paused(&mut self, config: &Config) -> bool {
        if self
            .blocked
            .as_ref()
            .is_some_and(|v| *v != Self::identity(config))
        {
            self.blocked = None;
            self.failures = 0;
        }
        self.blocked.is_some()
    }
    fn delay(&mut self, config: &Config, jitter: f64) -> f64 {
        self.failures = (self.failures + 1).min(20);
        let base = config
            .retry_interval
            .saturating_mul(1u64 << (self.failures - 1))
            .min(config.max_retry_interval) as f64;
        (base * (1.0 + jitter.clamp(0.0, 0.1))).min(config.max_retry_interval as f64)
    }
}

struct Worker {
    runtime: Arc<Runtime>,
    receiver: mpsc::Receiver<Action>,
    stop: watch::Receiver<bool>,
    control: watch::Receiver<u64>,
    guard: Option<RunGuard>,
    next_check: Instant,
    reconnect: Reconnect,
    rotation: Rotation,
    action: &'static str,
    phase: DiagnosticStage,
}

impl Worker {
    fn new(runtime: Arc<Runtime>, receiver: mpsc::Receiver<Action>) -> Self {
        Self {
            stop: runtime.stop.subscribe(),
            control: runtime.control.subscribe(),
            runtime,
            receiver,
            guard: None,
            next_check: Instant::now(),
            reconnect: Reconnect::default(),
            rotation: Rotation::default(),
            action: "status",
            phase: DiagnosticStage::Unknown,
        }
    }

    async fn acquire(&self) -> Result<RunGuard, String> {
        let store = self.runtime.store.clone();
        self.runtime.blocking(move || store.acquire_run()).await
    }

    async fn run(mut self) {
        if *self.stop.borrow() {
            return;
        }
        let runtime = self.runtime.clone();
        let mut stop = self.stop.clone();
        tokio::select! {
            biased;
            _ = stop.changed() => return,
            result = self.execute(Action::Status) => {
                if result.is_err() && !*stop.borrow() { runtime.update(|state| state.log("error", CONFIG_ERROR)); }
            }
        }
        runtime.update(|state| {
            state.busy = false;
            state.busy_message.clear();
        });
        loop {
            if *self.stop.borrow() {
                break;
            }
            if !self.runtime.desired.load(Ordering::Acquire) {
                self.guard.take();
            } else if self.guard.is_none() && Instant::now() >= self.next_check {
                match self.acquire().await {
                    Ok(guard) => {
                        self.guard = Some(guard);
                        self.runtime.update(|state| {
                            if self.runtime.desired.load(Ordering::Acquire) {
                                state.auto =
                                    json!({"state":"on", "message":"自动重连已开启，正在检查"});
                            }
                        });
                        if !self.runtime.desired.load(Ordering::Acquire) {
                            self.guard.take();
                        }
                    }
                    Err(_) => {
                        self.runtime.update(|state| {
                            if self.runtime.desired.load(Ordering::Acquire) {
                                state.auto = json!({"state":"external", "message":EXTERNAL});
                            }
                        });
                        self.next_check = Instant::now() + Duration::from_secs(15);
                    }
                }
            }
            let automatic = self.runtime.desired.load(Ordering::Acquire);
            tokio::select! {
                biased;
                _ = self.stop.changed() => break,
                _ = self.control.changed() => { self.next_check = Instant::now(); self.rotation.clear_zero(); },
                action = self.receiver.recv() => {
                    let Some(action) = action else { break; };
                    let runtime = self.runtime.clone();
                    let mut stop = self.stop.clone();
                    tokio::select! {
                        biased;
                        _ = stop.changed() => break,
                        result = self.execute(action) => {
                            if let Err(error) = result { runtime.update(|state| state.log("error", &error)); }
                        },
                    }
                    runtime.update(|state| { state.busy = false; state.busy_message.clear(); });
                }
                _ = tokio::time::sleep_until(self.next_check), if automatic => {
                    let runtime = self.runtime.clone();
                    let mut stop = self.stop.clone();
                    let mut control = self.control.clone();
                    let rotation_was_enabled = runtime.rotation_enabled.load(Ordering::Acquire);
                    let auto_version = runtime.auto_version.load(Ordering::Acquire);
                    let rotation_version = runtime.rotation_version.load(Ordering::Acquire);
                    tokio::select! {
                        biased;
                        _ = stop.changed() => break,
                        _ = async {
                            loop {
                                // Coalesced off/on notifications still invalidate the old operation.
                                if !runtime.desired.load(Ordering::Acquire) || runtime.auto_version.load(Ordering::Acquire) != auto_version || (rotation_was_enabled && (!runtime.rotation_enabled.load(Ordering::Acquire) || runtime.rotation_version.load(Ordering::Acquire) != rotation_version)) { break; }
                                if control.changed().await.is_err() { break; }
                            }
                        } => {
                            self.guard.take();
                            self.runtime.update(|state| {
                                state.status = json!({"online":null, "service":null, "user":"", "ip":"", "message":"自动认证已取消，请查询实际状态"});
                                state.info = Value::Null;
                            });
                        },
                        _ = self.tick() => {},
                    }
                    runtime.update(|state| { state.busy = false; state.busy_message.clear(); });
                    if !runtime.desired.load(Ordering::Acquire) { self.guard.take(); }
                }
            }
        }
        self.receiver.close();
        self.guard.take();
    }

    fn busy(&self, message: &str) {
        self.runtime.update(|state| {
            state.busy = true;
            state.busy_message = message.into();
        });
    }
    fn error_message(&self, error: &AuthError) -> String {
        format!(
            "{} [{}]",
            public_error(error.code),
            diagnostic_detail(self.action, self.phase, error)
        )
    }

    fn error(&self, error: &AuthError) {
        let message = self.error_message(error);
        self.runtime.update(|state| state.log("error", &message));
    }

    fn local_error(
        &self,
        code: i32,
        stage: DiagnosticStage,
        reason: DiagnosticReason,
    ) -> AuthError {
        let operation = match self.action {
            "status" => DiagnosticOperation::Status,
            "info" => DiagnosticOperation::Info,
            "login" => DiagnosticOperation::Login,
            "logout" => DiagnosticOperation::Logout,
            "switch_service" => DiagnosticOperation::SwitchService,
            _ => DiagnosticOperation::Unknown,
        };
        local_auth_error(code, operation, stage, reason)
    }

    fn config_failed(&self, account_only: bool) {
        let error = self.local_error(2, DiagnosticStage::Config, DiagnosticReason::ConfigInvalid);
        let message = format!(
            "{CONFIG_ERROR} [{}]",
            diagnostic_detail(self.action, DiagnosticStage::Config, &error)
        );
        self.runtime.update(|state| {
            state.info = Value::Null;
            if account_only {
                state.info_error = message.clone();
            }
            if !account_only {
                state.status =
                    json!({"online":null, "service":null, "user":"", "ip":"", "message":message});
            }
            state.log("error", &message);
        });
    }

    async fn status(&self, config: &Config) -> Result<Status, AuthError> {
        let result = self.runtime.backend.status(config).await;
        self.runtime.update(|state| match &result {
            Ok(status) => {
                state.status = serde_json::to_value(status).unwrap();
                state.status["message"] = if status.online {
                    "校园网已连接"
                } else {
                    "校园网未连接"
                }
                .into();
                if !status.online {
                    state.info = json!({"online":false, "fields":[], "items":[]});
                } else if state.info["online"] == false {
                    // A previous offline account response is no longer current after an online query.
                    state.info = Value::Null;
                }
            }
            Err(error) => {
                let message = self.error_message(error);
                state.status =
                    json!({"online":null, "service":null, "user":"", "ip":"", "message":message});
                state.info = Value::Null;
                state.log("error", &message);
            }
        });
        result
    }

    fn operation_timed_out(&self, account_only: bool) {
        let error = self.local_error(2, self.phase, DiagnosticReason::Deadline);
        let message = format!(
            "操作超过时限，请重新查询实际状态 [{}]",
            diagnostic_detail(self.action, self.phase, &error)
        );
        self.runtime.update(|state| {
            state.info = Value::Null;
            if account_only {
                state.info_error = format!(
                    "账户信息和连接状态刷新超时，请稍后重试 [{}]",
                    diagnostic_detail(self.action, self.phase, &error)
                );
            }
            // Info now includes an independent status query; a whole-operation timeout leaves it unconfirmed.
            state.status =
                json!({"online":null, "service":null, "user":"", "ip":"", "message":message});
            state.log("error", &message);
        });
    }

    async fn execute(&mut self, action: Action) -> Result<(), String> {
        let _work = self.runtime.begin_auth()?;
        self.action = action.name();
        self.phase = DiagnosticStage::Queue;
        let account_only = matches!(action, Action::Info);
        let config = match self.runtime.config().await {
            Ok(config) => config,
            Err(_) => {
                self.config_failed(account_only);
                return Ok(());
            }
        };
        if matches!(action, Action::SetService(_)) {
            return self.execute_inner(action).await;
        }
        let budget = Duration::from_secs(config.operation_timeout);
        match tokio::time::timeout(budget, self.execute_inner(action)).await {
            Ok(result) => result,
            Err(_) => {
                self.operation_timed_out(account_only);
                Ok(())
            }
        }
    }

    async fn execute_inner(&mut self, action: Action) -> Result<(), String> {
        let config = match self.runtime.config().await {
            Ok(config) => config,
            Err(_) => {
                self.config_failed(matches!(action, Action::Info));
                return Ok(());
            }
        };
        match action {
            Action::SwitchAccount(id) => {
                self.switch_account(&id, false).await?;
            }
            Action::SetService(target) => {
                self.runtime
                    .save_config(json!({"service":target}).as_object().unwrap().clone())
                    .await?;
            }
            Action::Status => {
                self.phase = DiagnosticStage::OnlineState;
                self.busy("正在查询连接状态");
                let _ = self.status(&config).await;
            }
            Action::Info => {
                self.phase = DiagnosticStage::AccountInfo;
                self.busy("正在读取账户信息");
                let result = self.runtime.backend.info(&config).await;
                let info = result.as_ref().ok().and_then(normalize_info);
                let info_error = match &result {
                    Err(error) => Some(format!(
                        "账户信息获取失败，请稍后重试 [{}]",
                        diagnostic_detail(self.action, self.phase, error)
                    )),
                    Ok(_) if info.is_none() => Some(format!(
                        "账户信息格式未确认，请稍后重试 [{}]",
                        diagnostic_detail(
                            self.action,
                            self.phase,
                            &self.local_error(
                                2,
                                DiagnosticStage::AccountInfo,
                                DiagnosticReason::ResponseInvalid,
                            )
                        )
                    )),
                    _ => None,
                };
                if let Some(message) = &info_error {
                    self.runtime.update(|state| state.log("error", message));
                }
                self.phase = DiagnosticStage::Verification;
                self.busy("正在复查连接状态");
                let observed = self.status(&config).await;
                self.runtime.update(|state| {
                    if observed.as_ref().is_ok_and(|status| !status.online) {
                        // Only the independent status observation can confirm an offline connection.
                        state.info = json!({"online":false, "fields":[], "items":[]});
                    } else if observed.is_err() {
                        state.info = Value::Null;
                        state.info_error = info_error.clone().unwrap_or_else(|| {
                            format!(
                                "账户信息连接状态复查失败，请稍后重试 [{}]",
                                diagnostic_detail(
                                    self.action,
                                    self.phase,
                                    observed.as_ref().unwrap_err()
                                ),
                            )
                        });
                    } else if let Some(message) = &info_error {
                        state.info = Value::Null;
                        state.info_error = message.clone();
                    } else if info.as_ref().is_some_and(|info| info["online"] == true) {
                        state.info = info.clone().unwrap();
                    } else {
                        state.info = Value::Null;
                        let error = self.local_error(
                            2,
                            DiagnosticStage::Verification,
                            DiagnosticReason::StateUnrecognized,
                        );
                        state.info_error = format!(
                            "账户信息与连接状态不一致，请重新读取 [{}]",
                            diagnostic_detail(self.action, self.phase, &error)
                        );
                        state.log("error", &state.info_error.clone());
                    }
                });
            }
            Action::Login | Action::Logout | Action::Switch(_) => {
                if matches!(action, Action::Login) {
                    self.reconnect = Reconnect::default();
                }
                let _temporary = if self.guard.is_none() {
                    match self.acquire().await {
                        Ok(guard) => {
                            self.runtime.update(|state| {
                                if !self.runtime.desired.load(Ordering::Acquire) {
                                    state.auto = json!({"state":"off", "message":"自动重连已关闭"});
                                }
                            });
                            Some(guard)
                        }
                        Err(_) => {
                            self.runtime.update(|state| {
                                state.auto = json!({"state":"external", "message":EXTERNAL});
                                state.log("error", EXTERNAL);
                            });
                            return Ok(());
                        }
                    }
                } else {
                    None
                };
                self.busy(match action {
                    Action::Login => "正在登录并确认连接",
                    Action::Logout => "正在下线并确认结果",
                    _ => "正在切换并确认实际服务",
                });
                let config = match self.runtime.config().await {
                    Ok(config) => config,
                    Err(_) => {
                        self.config_failed(false);
                        return Ok(());
                    }
                };
                self.phase = match action {
                    Action::Logout => DiagnosticStage::OfflineSubmit,
                    Action::Switch(_) => DiagnosticStage::ServiceSelect,
                    _ => DiagnosticStage::UserOnline,
                };
                let result = self.runtime.backend.mutate(&config, &action).await;
                if let Err(error) = &result {
                    self.error(error);
                }
                if result.as_ref().is_err_and(|error| error.code == 4) {
                    self.reconnect.blocked = Some(Reconnect::identity(&config));
                }
                let latest = match self.runtime.config().await {
                    Ok(config) => config,
                    Err(_) => {
                        self.config_failed(false);
                        self.next_check = Instant::now() + Duration::from_secs(30);
                        return Ok(());
                    }
                };
                self.phase = DiagnosticStage::Verification;
                let observed = self.status(&latest).await;
                let confirmed = match (&action, &observed) {
                    (Action::Login, Ok(status)) => {
                        status.online
                            && status.user == config.username
                            && status.service.as_deref() == Some(&config.service)
                    }
                    (Action::Logout, Ok(status)) => !status.online,
                    (Action::Switch(target), Ok(status)) => {
                        status.online
                            && status.user == config.username
                            && status.service.as_deref() == Some(target)
                    }
                    _ => false,
                };
                if result.is_ok() && confirmed {
                    if let Action::Switch(target) = &action {
                        self.runtime
                            .save_config(json!({"service":target}).as_object().unwrap().clone())
                            .await?;
                    }
                    self.runtime.update(|state| {
                        state.log(
                            "success",
                            match action {
                                Action::Logout => "已独立确认下线",
                                Action::Switch(_) => "已独立确认切换服务",
                                _ => "已独立确认登录",
                            },
                        )
                    });
                } else {
                    if result.is_ok() && observed.is_ok() {
                        self.error(&self.local_error(
                            3,
                            DiagnosticStage::Verification,
                            DiagnosticReason::IdentityMismatch,
                        ));
                    }
                }
                self.next_check = Instant::now() + Duration::from_secs(config.check_interval);
            }
        }
        Ok(())
    }

    async fn tick(&mut self) {
        let Ok(_work) = self.runtime.begin_auth() else {
            return;
        };
        self.action = "auto";
        self.phase = DiagnosticStage::Config;
        let config = match self.runtime.config().await {
            Ok(config) => config,
            Err(_) => {
                self.config_failed(false);
                self.schedule(30.0, "配置不可用，等待修复，未发起登录");
                return;
            }
        };
        let budget = Duration::from_secs(config.operation_timeout);
        if tokio::time::timeout(budget, self.tick_inner())
            .await
            .is_err()
        {
            self.operation_timed_out(false);
            let delay = self
                .reconnect
                .delay(&config, rand::thread_rng().gen_range(0.0..=0.1));
            self.schedule(delay, "操作超过时限，等待重新查询状态");
        }
    }

    async fn tick_inner(&mut self) {
        let config = match self.runtime.config().await {
            Ok(config) => config,
            Err(_) => {
                self.config_failed(false);
                self.schedule(30.0, "配置不可用，等待修复，未发起登录");
                return;
            }
        };
        self.phase = DiagnosticStage::OnlineState;
        self.busy("自动重连：正在检查连接");
        let observed = self.status(&config).await;
        let latest = match self.runtime.config().await {
            Ok(config) => config,
            Err(_) => {
                self.config_failed(false);
                self.schedule(30.0, CONFIG_ERROR);
                return;
            }
        };
        if serde_json::to_value(&latest).ok() != serde_json::to_value(&config).ok() {
            self.schedule(0.0, "配置已更新，重新确认连接状态");
            return;
        }
        let paused = self.reconnect.paused(&config);
        if !observed.as_ref().is_ok_and(|status| {
            status.online
                && status.user == config.username
                && status.service.as_deref() == Some(&config.service)
        }) {
            self.rotation.clear_zero();
        }
        let (delay, message) = match observed {
            Ok(status) if status.online => {
                self.reconnect.failures = 0;
                if !paused && self.guard.is_some() && self.rotate_if_needed(&config, &status).await
                {
                    self.schedule(
                        config.check_interval as f64,
                        "本轮账号检查结束，稍后重新查询",
                    );
                    return;
                }
                (
                    config.check_interval as f64,
                    if paused {
                        "在线；认证暂停保持，修改配置或手动登录后恢复"
                    } else {
                        "已确认在线"
                    },
                )
            }
            Ok(_) if self.guard.is_none() => (config.check_interval as f64, EXTERNAL),
            Ok(_) if paused => (config.check_interval as f64, public_error(4)),
            Ok(_) => {
                if !self.runtime.desired.load(Ordering::Acquire) {
                    return;
                }
                self.phase = DiagnosticStage::UserOnline;
                let result = self.runtime.backend.mutate(&config, &Action::Login).await;
                if let Err(error) = &result {
                    self.error(error);
                }
                if result.as_ref().is_err_and(|error| error.code == 4) {
                    self.reconnect.blocked = Some(Reconnect::identity(&config));
                }
                let latest = match self.runtime.config().await {
                    Ok(config) => config,
                    Err(_) => {
                        self.config_failed(false);
                        self.schedule(30.0, CONFIG_ERROR);
                        return;
                    }
                };
                self.phase = DiagnosticStage::Verification;
                let verified = self.status(&latest).await;
                if result.is_ok()
                    && verified.as_ref().is_ok_and(|v| {
                        v.online
                            && v.user == config.username
                            && v.service.as_deref() == Some(&config.service)
                    })
                {
                    self.reconnect.failures = 0;
                    (config.check_interval as f64, "重连已独立确认成功")
                } else if result.as_ref().is_err_and(|v| v.code == 4) {
                    self.reconnect.blocked = Some(Reconnect::identity(&config));
                    (config.check_interval as f64, public_error(4))
                } else {
                    (
                        self.reconnect
                            .delay(&config, rand::thread_rng().gen_range(0.0..=0.1)),
                        public_error(3),
                    )
                }
            }
            Err(_) => (
                self.reconnect
                    .delay(&config, rand::thread_rng().gen_range(0.0..=0.1)),
                public_error(2),
            ),
        };
        self.schedule(delay, message);
    }

    fn schedule(&mut self, delay: f64, message: &str) {
        self.next_check = Instant::now() + Duration::from_secs_f64(delay);
        self.runtime.update(|state| {
            if self.runtime.desired.load(Ordering::Acquire) {
                state.auto = json!({"state":if self.guard.is_some() { "on" } else { "external" }, "message":message, "delay":delay.ceil()});
            }
        });
    }
}

fn normalize_info(value: &Value) -> Option<Value> {
    let online = value.get("online")?.as_bool()?;
    let mut result = json!({"online":online, "fields":[], "items":[]});
    for key in ["fields", "items"] {
        let pairs = value
            .get(key)?
            .as_array()?
            .iter()
            .take(100)
            .filter_map(|pair| {
                let pair = pair.as_array()?;
                if pair.len() != 2 {
                    return None;
                }
                Some(json!([pair[0].as_str()?, pair[1].as_str()?]))
            })
            .collect::<Vec<_>>();
        result[key] = pairs.into();
    }
    Some(result)
}

enum Backend {
    Native,
    Demo(Arc<Mutex<Demo>>),
}
#[derive(Default)]
struct Demo {
    online: bool,
    service: Option<String>,
    user: String,
    #[cfg(test)]
    quota: Option<Value>,
    #[cfg(test)]
    login_failures: std::collections::HashMap<String, i32>,
    #[cfg(test)]
    logouts: u32,
    #[cfg(test)]
    status_error: Option<i32>,
    #[cfg(test)]
    status_diagnostic: Option<AuthDiagnostic>,
    #[cfg(test)]
    status_delay: Duration,
    #[cfg(test)]
    status_calls: u32,
    #[cfg(test)]
    operation_error: Option<i32>,
    #[cfg(test)]
    info_error: bool,
    #[cfg(test)]
    info_delay: Duration,
    #[cfg(test)]
    info_online: Option<bool>,
    #[cfg(test)]
    info_calls: u32,
    #[cfg(test)]
    delay: Duration,
    #[cfg(test)]
    logins: u32,
    #[cfg(test)]
    in_flight: u32,
    #[cfg(test)]
    cancelled: u32,
}
impl Demo {
    fn status(&self) -> Status {
        Status {
            online: self.online,
            service: self.service.clone(),
            user: self.user.clone(),
            ip: if self.online { "192.0.2.10" } else { "" }.into(),
            message: if self.online { "在线" } else { "离线" }.into(),
        }
    }
}
#[cfg(test)]
struct DemoFlight {
    demo: Arc<Mutex<Demo>>,
    completed: bool,
}
#[cfg(test)]
impl Drop for DemoFlight {
    fn drop(&mut self) {
        let mut demo = self.demo.lock().unwrap();
        demo.in_flight -= 1;
        if !self.completed {
            demo.cancelled += 1;
        }
    }
}
impl Backend {
    async fn status(&self, config: &Config) -> Result<Status, AuthError> {
        match self {
            Self::Native => AuthClient::new(config.clone())?.status().await,
            Self::Demo(demo) => {
                #[cfg(test)]
                {
                    let delay = {
                        let mut state = demo.lock().unwrap();
                        state.status_calls += 1;
                        state.status_delay
                    };
                    tokio::time::sleep(delay).await;
                }
                #[cfg(test)]
                {
                    let failure = {
                        let state = demo.lock().unwrap();
                        state
                            .status_error
                            .map(|code| (code, state.status_diagnostic))
                    };
                    if let Some((code, diagnostic)) = failure {
                        let mut error = AuthError::new(code, "fixture query https://fixture-user:fixture-secret@portal.invalid/?token=fixture-token");
                        if let Some(diagnostic) = diagnostic {
                            error.diagnostic = diagnostic;
                        }
                        return Err(error);
                    }
                }
                Ok(demo.lock().unwrap().status())
            }
        }
    }
    async fn info(&self, config: &Config) -> Result<Value, AuthError> {
        match self {
            Self::Native => AuthClient::new(config.clone())?.info().await,
            Self::Demo(demo) => {
                #[cfg(test)]
                {
                    let delay = {
                        let mut state = demo.lock().unwrap();
                        state.info_calls += 1;
                        state.info_delay
                    };
                    tokio::time::sleep(delay).await;
                }
                let demo = demo.lock().unwrap();
                #[cfg(test)]
                if demo.info_error {
                    return Err(AuthError::new(2,
                        "fixture account https://fixture-user:fixture-secret@portal.invalid/?token=fixture-token",
                    ));
                }
                #[cfg(test)]
                let online = demo.info_online.unwrap_or(demo.online);
                #[cfg(not(test))]
                let online = demo.online;
                Ok(
                    json!({"online":online, "fields":if online { vec![["账号", demo.user.as_str()]] } else { vec![] },
                    "items":if online { vec![["剩余流量", "12.5 GB"]] } else { vec![] }}),
                )
            }
        }
    }
    async fn mutate(&self, config: &Config, action: &Action) -> Result<Status, AuthError> {
        match self {
            Self::Native => {
                let client = AuthClient::new(config.clone())?;
                match action {
                    Action::Login => client.login().await,
                    Action::Logout => client.logout().await,
                    Action::Switch(target) => client.switch_service(target).await,
                    _ => unreachable!(),
                }
            }
            Self::Demo(demo) => {
                #[cfg(test)]
                let mut flight = {
                    let mut state = demo.lock().unwrap();
                    state.in_flight += 1;
                    if matches!(action, Action::Login) {
                        state.logins += 1;
                    }
                    DemoFlight {
                        demo: demo.clone(),
                        completed: false,
                    }
                };
                #[cfg(test)]
                {
                    let delay = demo.lock().unwrap().delay;
                    tokio::time::sleep(delay).await;
                    flight.completed = true;
                }
                let mut demo = demo.lock().unwrap();
                #[cfg(test)]
                if matches!(action, Action::Login) {
                    #[cfg(test)]
                    if let Some(code) = demo.login_failures.get(&config.username) {
                        return Err(AuthError::new(*code, "fixture candidate login failure"));
                    }
                }
                #[cfg(test)]
                if let Some(code) = demo.operation_error {
                    return Err(AuthError::new(code, "fixture mutation"));
                }
                if config.username.is_empty() || config.password.is_empty() {
                    return Err(AuthError::new(4, "fixture credentials"));
                }
                match action {
                    Action::Logout => {
                        #[cfg(test)]
                        {
                            demo.logouts += 1;
                        }
                        demo.online = false;
                        demo.service = None;
                        demo.user.clear();
                    }
                    Action::Login | Action::Switch(_) => {
                        demo.online = true;
                        demo.user = config.username.clone();
                        demo.service = Some(match action {
                            Action::Switch(target) => target.clone(),
                            _ => config.service.clone(),
                        });
                    }
                    _ => unreachable!(),
                }
                Ok(demo.status())
            }
        }
    }
}

#[cfg(test)]
#[path = "runtime_tests.rs"]
mod tests;

#[cfg(test)]
#[path = "runtime_review_tests.rs"]
mod review_tests;
