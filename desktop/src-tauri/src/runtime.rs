//! In-process desktop state. Authentication is serialized independently of settings and snapshots.
//! Decision: .agents/notes/proposals/desktop/2026-10-14-rust-desktop.md
use crate::storage::{
    valid_accent, valid_nosense_service, NoSenseConfig, Prefs, RunGuard, Store, CONFIG_ERROR,
    EXTERNAL,
};
#[path = "account_runtime.rs"]
mod account_runtime;
use account_runtime::{account_state, Rotation};
#[path = "runtime_observer.rs"]
mod runtime_observer;
use chrono::{SecondsFormat, Utc};
use rand::Rng;
use runtime_observer::{Observation, StatusIdentity};
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
    DiagnosticStage, InfoObservation, SelfDevice, SelfKick, SelfNoSense, SelfPackage, SelfRemember,
    SelfSnapshot, Status, SERVICES,
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
    SelfService,
    SelfKick(String),
    SelfNoSenseEnable {
        target: String,
        service: Option<String>,
    },
    SelfNoSenseDisable(String),
    SelfDeviceService {
        target: String,
        service: String,
    },
    SelfNoSenseRenew {
        target: String,
        service: Option<String>,
        force: bool,
    },
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
            Self::SelfService => "self_service",
            Self::SelfKick(_) => "self_kick",
            Self::SelfNoSenseEnable { .. } => "self_nosense_enable",
            Self::SelfNoSenseDisable(_) => "self_nosense_disable",
            Self::SelfDeviceService { .. } => "self_device_service",
            Self::SelfNoSenseRenew { .. } => "self_nosense_renew",
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
        "snapshot" | "diagnostics" | "observe" | "debug_status" | "debug_start" | "debug_stop"
        | "debug_open" => object.is_empty(),
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
                Some("self_service") => object.get("value").is_none_or(|v| {
                    v.as_str()
                        .is_some_and(|s| s.trim().len() <= 256 && !s.chars().any(char::is_control))
                }),
                Some("self_kick" | "self_nosense_disable") => object
                    .get("value")
                    .and_then(Value::as_str)
                    .is_some_and(|v| !v.trim().is_empty() && v.len() <= 32),
                Some("self_nosense_enable" | "self_nosense_renew") => object
                    .get("value")
                    .and_then(Value::as_str)
                    .is_some_and(|v| {
                        let (target, service) = v.split_once('|').unwrap_or((v, ""));
                        !target.trim().is_empty()
                            && target.len() <= 32
                            && valid_nosense_service(service)
                    }),
                Some("self_device_service") => object
                    .get("value")
                    .and_then(Value::as_str)
                    .is_some_and(|v| {
                        v.split_once('|').is_some_and(|(target, service)| {
                            !target.trim().is_empty()
                                && target.len() <= 32
                                && !service.trim().is_empty()
                                && valid_nosense_service(service)
                        })
                    }),
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
        "nosense" => {
            !object.is_empty()
                && object.iter().all(|(k, v)| match k.as_str() {
                    "auto_renew" | "remove" => v.is_boolean(),
                    "account" => v
                        .as_str()
                        .is_some_and(|s| s.trim().len() <= 256 && !s.chars().any(char::is_control)),
                    "target_mac" => v.as_str().is_some_and(|s| {
                        let t = s.trim();
                        t.is_empty()
                            || t.eq_ignore_ascii_case("current")
                            || ysu_auth::normalize_mac(t).is_some()
                    }),
                    "service" => v.as_str().is_some_and(valid_nosense_service),
                    _ => false,
                })
        }
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
                    "close_to_tray"
                    | "autostart_minimized"
                    | "auto_check_update"
                    | "auto_install_update" => v.is_boolean(),
                    "ignored_update_version" => v
                        .as_str()
                        .is_some_and(crate::storage::valid_ignored_version),
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
        navigation: None,
    };
    error
}

fn diagnostic_detail(action: &str, phase: DiagnosticStage, error: &AuthError) -> String {
    // Serialize only closed enums. AuthError.message may contain server text or credentials.
    let diagnostic = serde_json::to_value(error.diagnostic()).expect("fixed diagnostic enums");
    let phase = serde_json::to_value(phase).expect("fixed diagnostic phase");
    let mut detail = format!(
        "action={action} phase={} code={} operation={} stage={} reason={}",
        phase.as_str().unwrap_or("unknown"),
        error.code,
        diagnostic["operation"].as_str().unwrap_or("unknown"),
        diagnostic["stage"].as_str().unwrap_or("unknown"),
        diagnostic["reason"].as_str().unwrap_or("unknown"),
    );
    if let Some(navigation) = error.diagnostic().navigation {
        detail.push(' ');
        detail.push_str(&navigation.detail());
    }
    detail
}

struct LogEntry {
    timestamp: String,
    level: &'static str,
    message: String,
}

struct State {
    sequence: u64,
    config: Config,
    prefs: Prefs,
    status: Value,
    observed_identity: Option<StatusIdentity>,
    auto: Value,
    accounts: Value,
    rotation_intent: Option<bool>,
    busy: bool,
    busy_message: String,
    info: Value,
    self_service: Value,
    self_account: String,
    self_error: String,
    self_notice: String,
    nosense: Value,
    info_error: String,
    logs: VecDeque<LogEntry>,
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

    fn is_known_identity(&self, user: &str) -> bool {
        if user.is_empty() {
            return false;
        }
        if user == self.config.username {
            return true;
        }
        let Some(items) = self.accounts["items"].as_array() else {
            return false;
        };
        items.iter().any(|item| item["username"] == user)
    }

    fn public_identity(&self, user: &str) -> String {
        if self.is_known_identity(user) {
            user.to_owned()
        } else {
            self.text(user)
        }
    }

    fn snapshot(&self) -> Value {
        let mut config = serde_json::to_value(&self.config).expect("serializable config");
        config.as_object_mut().unwrap().remove("password");
        config["password_set"] = (!self.config.password.is_empty()).into();
        let logs: Vec<Value> = self
            .logs
            .iter()
            .map(|entry| {
                json!({
                    "timestamp": entry.timestamp,
                    "level": entry.level,
                    "message": self.text(&entry.message),
                })
            })
            .collect();
        let mut value = json!({
            "sequence": self.sequence, "config": config, "prefs": self.prefs,
            "status": self.status, "auto": self.auto, "busy": self.busy,
            "busy_message": self.text(&self.busy_message), "info": self.info,
            "info_error": self.text(&self.info_error), "logs": logs,
            "self_service": self.self_service,
            "self_account": self.public_identity(&self.self_account),
            "self_error": self.text(&self.self_error),
            "self_notice": self.text(&self.self_notice),
            "nosense": self.nosense,
            "environment": self.environment, "accounts": self.accounts,
        });
        // Public identities must round-trip even when they happen to equal a password.
        for key in ["base", "cas_host"] {
            self.scrub(&mut value["config"][key]);
        }
        if let Some(status) = value["status"].as_object_mut() {
            for key in ["user", "ip", "message"] {
                let user = status.get(key).and_then(Value::as_str);
                if key == "user" && user.is_some_and(|name| self.is_known_identity(name)) {
                    continue;
                }
                if let Some(text) = status.get_mut(key) {
                    self.scrub(text);
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
        if let Some(self_service) = value["self_service"].as_object_mut() {
            for (key, field) in self_service.iter_mut() {
                let user = field.as_str();
                if key == "account" && user.is_some_and(|name| self.is_known_identity(name)) {
                    continue;
                }
                self.scrub(field);
            }
        } else {
            self.scrub(&mut value["self_service"]);
        }
        self.scrub(&mut value["self_error"]);
        self.scrub(&mut value["self_notice"]);
        self.scrub(&mut value["nosense"]["message"]);
        self.scrub(&mut value["auto"]["message"]);
        value
    }

    fn log(&mut self, level: &str, message: &str) {
        let level = match level {
            "success" => "success",
            "error" => "error",
            _ => "info",
        };
        self.logs.push_back(LogEntry {
            timestamp: Utc::now().to_rfc3339_opts(SecondsFormat::Millis, true),
            level,
            message: self.text(message),
        });
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
    recording: Arc<crate::debug_recording::Recording>,
    sender: mpsc::Sender<Action>,
    stop: watch::Sender<bool>,
    control: watch::Sender<u64>,
    observations: watch::Sender<u64>,
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
        let nosense_cfg = store.load_nosense();
        let (accounts, passwords) = account_state(&store, &config);
        let rotation_enabled = accounts["auto_switch"].as_bool().unwrap_or(false);
        let recording = Arc::new(crate::debug_recording::Recording::new(&store.path));
        let backend = if store.demo {
            Backend::Demo(Arc::new(Mutex::new(Demo::default())))
        } else {
            Backend::Native(recording.clone())
        };
        let (sender, receiver) = mpsc::channel(QUEUE_SIZE);
        let (stop, _) = watch::channel(false);
        let (control, _) = watch::channel(0);
        let (observations, _) = watch::channel(0);
        let desired = prefs.auto_reconnect;
        let nosense = nosense_value(
            &nosense_cfg,
            if nosense_cfg.auto_renew {
                "无感自动续约已开启"
            } else {
                "无感自动续约已关闭"
            },
        );
        let mut state = State {
            sequence: 1,
            config,
            prefs,
            status: Value::Null,
            observed_identity: None,
            auto: json!({"state":"off", "message":"自动重连已关闭"}),
            busy: false,
            busy_message: String::new(),
            info: Value::Null,
            self_service: Value::Null,
            self_account: String::new(),
            self_error: String::new(),
            self_notice: String::new(),
            nosense,
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
            recording,
            sender,
            stop,
            control,
            observations,
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
            "debug_status" => Ok(self.recording.status()),
            "debug_start" | "debug_stop" => {
                if self.store.demo {
                    return Err("演示模式不写入调试文件".into());
                }
                if command == "debug_start" {
                    self.recording.start()
                } else {
                    Ok(self.recording.stop())
                }
            }
            "observe" => {
                // A watch revision coalesces bursts without consuming manual action queue slots.
                self.observations
                    .send_modify(|revision| *revision = revision.wrapping_add(1));
                Ok(self.snapshot())
            }
            "diagnostics" | "browser_install" => {
                let demo = self.store.demo;
                let environment = self.blocking(move || Ok(environment(demo))).await?;
                self.update(|state| state.environment = environment);
                Ok(self.snapshot())
            }
            "save_account" | "delete_account" => self.change_accounts(command, args).await,
            "rotation" => self.set_rotation(args["enabled"].as_bool().unwrap()).await,
            "nosense" => {
                let _settings = self.setting_guard().await?;
                let store = self.store.clone();
                let has_account = args.get("account").and_then(Value::as_str).is_some();
                let acct = args
                    .get("account")
                    .and_then(Value::as_str)
                    .map(str::trim)
                    .filter(|s| !s.is_empty() && !s.eq_ignore_ascii_case("current"))
                    .map(str::to_string);
                let removed = args.get("remove").and_then(Value::as_bool).unwrap_or(false);
                let updated = self
                    .blocking(move || store.update_nosense(args.as_object().unwrap().clone()))
                    .await?;
                let msg = if let Some(user) = &acct {
                    if removed {
                        format!("已移除账号 {user} 的无感续约设置")
                    } else if updated.accounts.get(user).is_some_and(|a| a.auto_renew) {
                        format!("账号 {user} 的无感自动续约已开启")
                    } else {
                        format!("账号 {user} 的无感自动续约已关闭")
                    }
                } else if updated.auto_renew {
                    "无感自动续约已开启".to_string()
                } else {
                    "无感自动续约已关闭".to_string()
                };
                self.update(|state| {
                    if has_account {
                        state.self_account = acct.unwrap_or_default();
                    }
                    state.nosense = nosense_value(&updated, &msg);
                    state.log("success", &msg);
                });
                self.wake();
                Ok(self.snapshot())
            }
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
                    "self_service" => {
                        if let Some(acct) = args.get("value").and_then(Value::as_str) {
                            let trimmed = acct.trim();
                            self.state.lock().unwrap().self_account =
                                if trimmed.eq_ignore_ascii_case("current") {
                                    String::new()
                                } else {
                                    trimmed.to_string()
                                };
                        }
                        Action::SelfService
                    }
                    "self_kick" => Action::SelfKick(args["value"].as_str().unwrap().into()),
                    "self_nosense_enable" => {
                        let raw = args["value"].as_str().unwrap();
                        let (target, service) = match raw.split_once('|') {
                            Some((t, s)) => (
                                t.trim().to_string(),
                                Some(s.trim().to_string()).filter(|v| !v.is_empty()),
                            ),
                            None => (raw.trim().to_string(), None),
                        };
                        Action::SelfNoSenseEnable { target, service }
                    }
                    "self_nosense_disable" => {
                        Action::SelfNoSenseDisable(args["value"].as_str().unwrap().trim().into())
                    }
                    "self_device_service" => {
                        let raw = args["value"].as_str().unwrap();
                        let (target, service) = raw.split_once('|').unwrap();
                        Action::SelfDeviceService {
                            target: target.trim().into(),
                            service: service.trim().into(),
                        }
                    }
                    "self_nosense_renew" => {
                        let raw = args["value"].as_str().unwrap();
                        let (target, service) = match raw.split_once('|') {
                            Some((t, s)) => (
                                t.trim().to_string(),
                                Some(s.trim().to_string()).filter(|v| !v.is_empty()),
                            ),
                            None => (raw.trim().to_string(), None),
                        };
                        Action::SelfNoSenseRenew {
                            target,
                            service,
                            force: true,
                        }
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

    pub(crate) fn debug_directory(&self) -> Result<&std::path::Path, String> {
        if self.store.demo {
            return Err("演示模式没有调试文件".into());
        }
        self.recording.directory()
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
        self.recording.shutdown();
        self.stopped.store(true, Ordering::Release);
    }
}

fn nosense_value(config: &NoSenseConfig, message: &str) -> Value {
    json!({
        "auto_renew": config.auto_renew,
        "target_mac": config.target_mac,
        "service": config.service,
        "accounts": config.accounts,
        "message": message,
    })
}

fn environment(demo: bool) -> Value {
    json!({"version":env!("CARGO_PKG_VERSION"), "rust":option_env!("YSU_RUST_VERSION").unwrap_or("unknown"),
        "runtime":"rust", "platform":std::env::consts::OS, "browser_available":demo || ysu_auth::browser_path().is_some(),
        "browser_component_available":true})
}

const MAX_LOGIN_FAILURES: u32 = 3;

#[derive(Default)]
struct Reconnect {
    failures: u32,
    login_failures: u32,
    login_identity: Option<String>,
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
        let current = Self::identity(config);
        if self.blocked.as_ref().is_some_and(|v| *v != current) {
            self.blocked = None;
            self.failures = 0;
            self.login_failures = 0;
            self.login_identity = None;
        }
        if self.login_identity.as_ref().is_some_and(|v| *v != current) {
            self.login_failures = 0;
            self.login_identity = None;
        }
        self.blocked.is_some()
    }
    fn record_login_failure(&mut self, config: &Config, code: i32) -> bool {
        let current = Self::identity(config);
        if self.login_identity.as_ref() != Some(&current) {
            self.login_identity = Some(current.clone());
            self.login_failures = 0;
        }
        self.login_failures = self.login_failures.saturating_add(1);
        if code == 4 || self.login_failures >= MAX_LOGIN_FAILURES {
            self.blocked = Some(current);
            true
        } else {
            false
        }
    }
    fn clear_login_failures(&mut self) {
        self.failures = 0;
        self.login_failures = 0;
        self.login_identity = None;
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
    observations: watch::Receiver<u64>,
    observation: Mutex<Observation>,
    guard: Option<RunGuard>,
    next_check: Instant,
    reconnect: Reconnect,
    rotation: Rotation,
    nosense_schedule: std::collections::HashMap<String, (String, Instant)>,
    action: &'static str,
    phase: DiagnosticStage,
}

impl Worker {
    fn new(runtime: Arc<Runtime>, receiver: mpsc::Receiver<Action>) -> Self {
        let observations = runtime.observations.subscribe();
        let mut observation = Observation::new(Instant::now());
        if *observations.borrow() != 0 {
            observation.request();
        }
        Self {
            stop: runtime.stop.subscribe(),
            control: runtime.control.subscribe(),
            observations,
            observation: Mutex::new(observation),
            runtime,
            receiver,
            guard: None,
            next_check: Instant::now(),
            reconnect: Reconnect::default(),
            rotation: Rotation::default(),
            nosense_schedule: std::collections::HashMap::new(),
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
        self.run_loop().await;
    }

    async fn run_loop(&mut self) {
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
            if self.observations.has_changed().unwrap_or(false) {
                self.observations.borrow_and_update();
                self.observation.lock().unwrap().request();
            }
            let automatic = self.runtime.desired.load(Ordering::Acquire);
            let observe_at = self
                .observation
                .lock()
                .unwrap()
                .deadline(automatic, self.next_check);
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
                _ = tokio::time::sleep_until(observe_at) => self.observe().await,
                _ = self.observations.changed() => self.observation.lock().unwrap().request(),
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
        self.runtime
            .recording
            .task(self.action, self.phase, Some(error));
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
            "self_service"
            | "self_nosense_enable"
            | "self_nosense_disable"
            | "self_device_service"
            | "self_nosense_renew" => DiagnosticOperation::SelfService,
            "self_kick" => DiagnosticOperation::SelfKick,
            _ => DiagnosticOperation::Unknown,
        };
        local_auth_error(code, operation, stage, reason)
    }

    fn is_self_action(&self) -> bool {
        matches!(
            self.action,
            "self_service"
                | "self_kick"
                | "self_nosense_enable"
                | "self_nosense_disable"
                | "self_device_service"
                | "self_nosense_renew"
        )
    }

    fn config_failed(&self, account_only: bool) {
        let error = self.local_error(2, DiagnosticStage::Config, DiagnosticReason::ConfigInvalid);
        self.runtime
            .recording
            .task(self.action, DiagnosticStage::Config, Some(&error));
        let message = format!(
            "{CONFIG_ERROR} [{}]",
            diagnostic_detail(self.action, DiagnosticStage::Config, &error)
        );
        let self_only = self.is_self_action();
        self.runtime.update(|state| {
            state.log("error", &message);
            if self_only {
                state.self_service = Value::Null;
                state.self_error = message.clone();
                return;
            }
            state.info = Value::Null;
            if account_only {
                state.info_error = message.clone();
            }
            if !account_only {
                state.status =
                    json!({"online":null, "service":null, "user":"", "ip":"", "message":message});
            }
        });
    }

    async fn status(&self, config: &Config) -> Result<Status, AuthError> {
        // A query starting after an admitted trigger satisfies it; watch revisions that arrive
        // during the query remain unread and request one follow-up after the busy operation.
        self.observation.lock().unwrap().sample_started();
        let result = self.runtime.backend.status(config).await;
        self.publish_status(&result, false);
        result
    }

    fn operation_timed_out(&self, account_only: bool) {
        let error = self.local_error(2, self.phase, DiagnosticReason::Deadline);
        self.runtime
            .recording
            .task(self.action, self.phase, Some(&error));
        let message = format!(
            "操作超过时限，请重新查询实际状态 [{}]",
            diagnostic_detail(self.action, self.phase, &error)
        );
        let self_only = self.is_self_action();
        self.runtime.update(|state| {
            if self_only {
                let message = format!(
                    "自助服务操作超过时限，请稍后重试 [{}]",
                    diagnostic_detail(self.action, self.phase, &error)
                );
                state.log("error", &message);
                state.self_service = Value::Null;
                state.self_error = message;
                return;
            }
            state.log("error", &message);
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
        });
    }

    async fn execute(&mut self, action: Action) -> Result<(), String> {
        let _work = self.runtime.begin_auth()?;
        self.action = action.name();
        self.phase = DiagnosticStage::Queue;
        self.runtime.recording.task(self.action, self.phase, None);
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

    async fn self_config(&self, config: &Config) -> Config {
        let target = self.runtime.state.lock().unwrap().self_account.clone();
        if target.is_empty() || target == config.username {
            return config.clone();
        }
        let store = self.runtime.store.clone();
        let cfg_copy = config.clone();
        if let Ok(Ok(book)) = self
            .runtime
            .blocking(move || Ok(store.load_accounts(&cfg_copy)))
            .await
        {
            if let Some(account) = book
                .accounts
                .into_iter()
                .find(|a| a.username == target && !a.password.is_empty())
            {
                return account.config(config);
            }
        }
        config.clone()
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
            Action::SelfService => {
                self.phase = DiagnosticStage::AccountInfo;
                self.busy("正在读取自助服务");
                let self_cfg = self.self_config(&config).await;
                let result = self.runtime.backend.self_service(&self_cfg).await;
                if let Err(error) = &result {
                    self.runtime
                        .recording
                        .task(self.action, self.phase, Some(error));
                }
                let resolved_account = if self_cfg.username == config.username {
                    String::new()
                } else {
                    self_cfg.username.clone()
                };
                self.runtime.update(|state| {
                    if !state.self_account.is_empty() && state.self_account != self_cfg.username {
                        state.self_account = resolved_account.clone();
                    }
                    match result {
                        Ok(snapshot) => {
                            state.self_service = snapshot;
                            state.self_error.clear();
                            state.self_notice.clear();
                            state.log("info", "自助服务读取完成");
                        }
                        Err(error) => {
                            let prefix = if error.code == 4 {
                                "自助服务认证未通过，请检查账号密码或稍后重试"
                            } else {
                                "自助服务读取失败，请稍后重试"
                            };
                            let message = format!(
                                "{prefix} [{}]",
                                diagnostic_detail(self.action, self.phase, &error)
                            );
                            state.self_service = Value::Null;
                            state.self_error = message.clone();
                            state.log("error", &message);
                        }
                    }
                });
            }
            Action::SelfKick(selector) => {
                self.phase = DiagnosticStage::UserOnline;
                self.busy("正在下线设备");
                let self_cfg = self.self_config(&config).await;
                let result = self.runtime.backend.self_kick(&self_cfg, &selector).await;
                match result {
                    Ok(kick) => {
                        let notice = format!(
                            "已下线 {} 台设备：在线 {} → {} 台",
                            kick["kicked"].as_array().map_or(0, |v| v.len()),
                            kick["onlineBefore"].as_u64().unwrap_or(0),
                            kick["onlineAfter"].as_u64().unwrap_or(0),
                        );
                        // Re-read the full snapshot so the list and its 1-based
                        // indices always match what the next kick will resolve.
                        let refreshed = self.runtime.backend.self_service(&self_cfg).await;
                        if let Err(error) = &refreshed {
                            self.runtime
                                .recording
                                .task(self.action, self.phase, Some(error));
                        }
                        self.runtime.update(|state| {
                            state.self_notice = notice.clone();
                            state.log("success", &notice);
                            match refreshed {
                                Ok(snapshot) => {
                                    state.self_service = snapshot;
                                    state.self_error.clear();
                                }
                                Err(error) => {
                                    let message = format!(
                                        "下线已提交，但重新读取失败 [{}]",
                                        diagnostic_detail(self.action, self.phase, &error)
                                    );
                                    state.self_service = Value::Null;
                                    state.self_error = message.clone();
                                    state.log("error", &message);
                                }
                            }
                        });
                    }
                    Err(error) => {
                        self.runtime
                            .recording
                            .task(self.action, self.phase, Some(&error));
                        let message = format!(
                            "下线未完成 [{}]",
                            diagnostic_detail(self.action, self.phase, &error)
                        );
                        self.runtime.update(|state| {
                            state.self_error = message.clone();
                            state.log("error", &message);
                        });
                    }
                }
            }
            Action::SelfNoSenseEnable { .. }
            | Action::SelfNoSenseDisable(_)
            | Action::SelfDeviceService { .. }
            | Action::SelfNoSenseRenew { .. } => {
                self.phase = DiagnosticStage::UserOnline;
                let self_cfg = self.self_config(&config).await;
                let (busy_text, fail_prefix, result) = match &action {
                    Action::SelfNoSenseEnable { target, service } => (
                        "正在开启无感认证并核验结果",
                        "开启无感认证未完成",
                        self.runtime
                            .backend
                            .self_nosense_enable(&self_cfg, target, service.as_deref())
                            .await,
                    ),
                    Action::SelfNoSenseDisable(target) => (
                        "正在关闭无感认证并核验结果",
                        "关闭无感认证未完成",
                        self.runtime
                            .backend
                            .self_nosense_disable(&self_cfg, target)
                            .await,
                    ),
                    Action::SelfDeviceService { target, service } => (
                        "正在修改设备缺省服务并核验结果",
                        "修改缺省服务未完成",
                        self.runtime
                            .backend
                            .self_device_service(&self_cfg, target, service)
                            .await,
                    ),
                    Action::SelfNoSenseRenew {
                        target,
                        service,
                        force,
                    } => (
                        "正在检查并续约无感认证",
                        "续约无感认证未完成",
                        self.runtime
                            .backend
                            .self_nosense_renew(&self_cfg, target, service.as_deref(), *force)
                            .await,
                    ),
                    _ => unreachable!(),
                };
                self.busy(busy_text);
                match result {
                    Ok(outcome) => {
                        let notice = match outcome["action"].as_str().unwrap_or("") {
                            "unbind" => format!(
                                "已关闭无感认证：{}",
                                outcome["mac"].as_str().unwrap_or("已选设备")
                            ),
                            "service" => format!(
                                "已更新无感缺省服务：{} → {}",
                                outcome["mac"].as_str().unwrap_or(""),
                                outcome["service"].as_str().unwrap_or("套餐默认服务")
                            ),
                            "renew" => {
                                if outcome["renewed"].as_bool().unwrap_or(false) {
                                    format!(
                                        "已续约无感认证：{}（到期 {}）",
                                        outcome["mac"].as_str().unwrap_or(""),
                                        outcome["expires"].as_str().unwrap_or("—")
                                    )
                                } else {
                                    format!(
                                        "无感认证仍在有效期内：{}（到期 {}）",
                                        outcome["mac"].as_str().unwrap_or(""),
                                        outcome["expires"].as_str().unwrap_or("—")
                                    )
                                }
                            }
                            _ => format!(
                                "已开启无感认证：{}（到期 {}，缺省服务 {}）",
                                outcome["mac"].as_str().unwrap_or(""),
                                outcome["expires"].as_str().unwrap_or("—"),
                                outcome["service"].as_str().unwrap_or("套餐默认服务")
                            ),
                        };
                        let refreshed = self.runtime.backend.self_service(&self_cfg).await;
                        if let Err(error) = &refreshed {
                            self.runtime
                                .recording
                                .task(self.action, self.phase, Some(error));
                        }
                        self.runtime.update(|state| {
                            state.self_notice = notice.clone();
                            state.log("success", &notice);
                            match refreshed {
                                Ok(snapshot) => {
                                    state.self_service = snapshot;
                                    state.self_error.clear();
                                }
                                Err(error) => {
                                    let message = format!(
                                        "变更已提交，但重新读取失败 [{}]",
                                        diagnostic_detail(self.action, self.phase, &error)
                                    );
                                    state.self_service = Value::Null;
                                    state.self_error = message.clone();
                                    state.log("error", &message);
                                }
                            }
                        });
                    }
                    Err(error) => {
                        self.runtime
                            .recording
                            .task(self.action, self.phase, Some(&error));
                        let message = format!(
                            "{fail_prefix} [{}]",
                            diagnostic_detail(self.action, self.phase, &error)
                        );
                        self.runtime.update(|state| {
                            state.self_error = message.clone();
                            state.log("error", &message);
                        });
                    }
                }
            }
            Action::Info => {
                self.phase = DiagnosticStage::AccountInfo;
                self.busy("正在读取账户信息");
                let result = self.runtime.backend.info(&config).await;
                let info = result
                    .as_ref()
                    .ok()
                    .and_then(|observation| normalize_info(&observation.info));
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
                // status() may have invalidated cached info after an external identity change.
                // Do not republish this read's older payload under that newer actual identity.
                let matches_observed = result.as_ref().is_ok_and(|source| {
                    observed
                        .as_ref()
                        .is_ok_and(|status| source.matches_status(status))
                });
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
                    } else if info.as_ref().is_some_and(|info| info["online"] == true)
                        && matches_observed
                    {
                        state.info = info.clone().unwrap();
                    } else {
                        state.info = Value::Null;
                        let (reason, message) =
                            if info.as_ref().is_some_and(|info| info["online"] == true) {
                                (
                                    DiagnosticReason::IdentityMismatch,
                                    "账户信息读取期间实际身份已变化，请重新读取",
                                )
                            } else {
                                (
                                    DiagnosticReason::StateUnrecognized,
                                    "账户信息与连接状态不一致，请重新读取",
                                )
                            };
                        let error = self.local_error(2, DiagnosticStage::Verification, reason);
                        state.info_error = format!(
                            "{message} [{}]",
                            diagnostic_detail(self.action, self.phase, &error)
                        );
                        state.log("error", &state.info_error.clone());
                    }
                });
            }
            Action::Login | Action::Logout | Action::Switch(_) => {
                if matches!(action, Action::Login) {
                    self.reconnect = Reconnect::default();
                    self.nosense_schedule.clear();
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
                        if matches!(action, Action::Logout) {
                            state.info = Value::Null;
                            state.info_error.clear();
                            state.self_service = Value::Null;
                            state.self_error.clear();
                            state.self_notice.clear();
                        }
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
                    if matches!(action, Action::Login) {
                        let code = result.as_ref().err().map_or(3, |v| v.code);
                        if !self.reconnect.record_login_failure(&config, code) {
                            let delay = self
                                .reconnect
                                .delay(&config, rand::thread_rng().gen_range(0.0..=0.1));
                            self.next_check = Instant::now() + Duration::from_secs_f64(delay);
                            return Ok(());
                        }
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
        self.runtime.recording.task(self.action, self.phase, None);
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
                self.reconnect.clear_login_failures();
                if !paused && self.guard.is_some() && self.rotate_if_needed(&config, &status).await
                {
                    self.schedule(
                        config.check_interval as f64,
                        "本轮账号检查结束，稍后重新查询",
                    );
                    return;
                }
                if !paused && self.guard.is_some() {
                    self.renew_nosense_if_needed(&config).await;
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
                    self.reconnect.clear_login_failures();
                    (config.check_interval as f64, "重连已独立确认成功")
                } else {
                    let code = result.as_ref().err().map_or(3, |v| v.code);
                    if self.reconnect.record_login_failure(&config, code) {
                        (
                            config.check_interval as f64,
                            if code == 4 {
                                public_error(4)
                            } else {
                                "连续重连失败已达上限，自动重连已暂停，请检查账号或网络后手动登录"
                            },
                        )
                    } else {
                        (
                            self.reconnect
                                .delay(&config, rand::thread_rng().gen_range(0.0..=0.1)),
                            public_error(3),
                        )
                    }
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

    pub(super) async fn renew_nosense_if_needed(&mut self, config: &Config) {
        let store = self.runtime.store.clone();
        let cfg_copy = config.clone();
        let Ok((nosense, book)) = self
            .runtime
            .blocking(move || Ok((store.load_nosense(), store.load_accounts(&cfg_copy))))
            .await
        else {
            return;
        };
        let mut targets: Vec<(Config, String, Option<String>)> = Vec::new();
        let mut used_macs = std::collections::HashSet::new();
        if !config.username.is_empty() && !config.password.is_empty() {
            if let Some(rule) = nosense.accounts.get(&config.username) {
                if rule.auto_renew {
                    let mac = if rule.target_mac.is_empty() {
                        "current".to_string()
                    } else {
                        rule.target_mac.clone()
                    };
                    let svc = (!rule.service.is_empty()).then(|| rule.service.clone());
                    used_macs.insert(mac.clone());
                    targets.push((config.clone(), mac, svc));
                }
            } else if nosense.auto_renew {
                let mac = if nosense.target_mac.is_empty() {
                    "current".to_string()
                } else {
                    nosense.target_mac.clone()
                };
                let svc = (!nosense.service.is_empty()).then(|| nosense.service.clone());
                used_macs.insert(mac.clone());
                targets.push((config.clone(), mac, svc));
            }
        }
        if let Ok(book) = book {
            for account in book.accounts {
                if !account.enabled
                    || account.username.is_empty()
                    || account.password.is_empty()
                    || account.username == config.username
                {
                    continue;
                }
                let Some(rule) = nosense.accounts.get(&account.username) else {
                    continue;
                };
                if !rule.auto_renew
                    || rule.target_mac.is_empty()
                    || used_macs.contains(&rule.target_mac)
                {
                    continue;
                }
                used_macs.insert(rule.target_mac.clone());
                let svc = if rule.service.is_empty() {
                    Some(account.service.clone())
                } else {
                    Some(rule.service.clone())
                };
                targets.push((account.config(config), rule.target_mac.clone(), svc));
            }
        }
        let active_users: std::collections::HashSet<&str> = targets
            .iter()
            .map(|(c, _, _)| c.username.as_str())
            .collect();
        self.nosense_schedule
            .retain(|k, _| active_users.contains(k.as_str()));
        if targets.is_empty() {
            return;
        }
        let mut messages = Vec::new();
        let mut any_renewed = false;
        let mut any_failed = false;
        for (acct_cfg, target_mac, service) in targets {
            let key = format!(
                "{}|{}|{}",
                Reconnect::identity(&acct_cfg),
                target_mac,
                service.as_deref().unwrap_or("")
            );
            if self
                .nosense_schedule
                .get(&acct_cfg.username)
                .is_some_and(|(k, next)| k == &key && Instant::now() < *next)
            {
                continue;
            }
            match self
                .runtime
                .backend
                .self_nosense_renew(&acct_cfg, &target_mac, service.as_deref(), false)
                .await
            {
                Ok(outcome) => {
                    self.nosense_schedule.insert(
                        acct_cfg.username.clone(),
                        (key, Instant::now() + Duration::from_secs(21_600)),
                    );
                    let expires = outcome["expires"].as_str().unwrap_or("");
                    let renewed = outcome["renewed"].as_bool().unwrap_or(false);
                    any_renewed |= renewed;
                    let msg = if renewed {
                        if expires.is_empty() {
                            "无感认证已自动续约".to_string()
                        } else {
                            format!("无感认证已自动续约（到期 {expires}）")
                        }
                    } else if expires.is_empty() {
                        "无感认证有效".to_string()
                    } else {
                        format!("无感认证有效（到期 {expires}）")
                    };
                    messages.push(msg);
                }
                Err(error) => {
                    any_failed = true;
                    let backoff = if error.code == 4 { 86_400 * 365 } else { 1_800 };
                    self.nosense_schedule.insert(
                        acct_cfg.username.clone(),
                        (key, Instant::now() + Duration::from_secs(backoff)),
                    );
                    let msg = if error.code == 4 {
                        "无感自动续约已暂停（认证未通过，请修改配置后重试）"
                    } else {
                        "无感自动续约待重试"
                    };
                    messages.push(msg.to_string());
                }
            }
        }
        if !messages.is_empty() {
            let joined = messages.join("；");
            self.runtime.update(|state| {
                state.nosense = nosense_value(&nosense, &joined);
                if any_renewed {
                    state.log("success", &joined);
                } else if any_failed {
                    state.log("error", &joined);
                }
            });
        }
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
    Native(Arc<crate::debug_recording::Recording>),
    Demo(Arc<Mutex<Demo>>),
}
#[cfg(test)]
#[derive(Clone, Debug, PartialEq, Eq)]
enum AccountEvent {
    Status {
        requested: String,
        online: bool,
        owner: String,
        service: Option<String>,
    },
    Mutation {
        action: &'static str,
        requested: String,
        service: String,
    },
}
#[derive(Default)]
struct Demo {
    online: bool,
    service: Option<String>,
    user: String,
    nosense_mac: Option<String>,
    nosense_service: String,
    nosense_expires: String,
    nosense_by_user: std::collections::HashMap<String, (String, String, String)>,
    #[cfg(test)]
    ip: Option<String>,
    #[cfg(test)]
    quota: Option<Value>,
    #[cfg(test)]
    login_failures: std::collections::HashMap<String, i32>,
    #[cfg(test)]
    login_diagnostics: std::collections::HashMap<String, AuthDiagnostic>,
    #[cfg(test)]
    account_events: Vec<AccountEvent>,
    #[cfg(test)]
    status_gate_at: Option<(u32, Arc<tokio::sync::Notify>)>,
    #[cfg(test)]
    status_failure_at: Option<(u32, i32)>,
    #[cfg(test)]
    logouts: u32,
    #[cfg(test)]
    status_error: Option<i32>,
    #[cfg(test)]
    status_diagnostic: Option<AuthDiagnostic>,
    #[cfg(test)]
    status_delay: Duration,
    #[cfg(test)]
    status_gate: Option<Arc<tokio::sync::Notify>>,
    #[cfg(test)]
    mutation_gate: Option<Arc<tokio::sync::Notify>>,
    #[cfg(test)]
    status_calls: u32,
    #[cfg(test)]
    status_backends: Vec<String>,
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
    self_error: Option<i32>,
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
        #[cfg(test)]
        let ip = self
            .ip
            .clone()
            .unwrap_or_else(|| if self.online { "192.0.2.10" } else { "" }.into());
        #[cfg(not(test))]
        let ip = if self.online { "192.0.2.10" } else { "" }.into();
        Status {
            online: self.online,
            service: self.service.clone(),
            user: self.user.clone(),
            ip,
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
            Self::Native(recording) => {
                AuthClient::new(config.clone())?
                    .with_trace(recording.trace())
                    .status()
                    .await
            }
            Self::Demo(demo) => {
                #[cfg(test)]
                let call = {
                    let (delay, gate, call) = {
                        let mut state = demo.lock().unwrap();
                        state.status_calls += 1;
                        state.status_backends.push(config.backend.clone());
                        let gate = state
                            .status_gate_at
                            .as_ref()
                            .filter(|(at, _)| *at == state.status_calls)
                            .map(|(_, gate)| gate.clone())
                            .or_else(|| state.status_gate.clone());
                        (state.status_delay, gate, state.status_calls)
                    };
                    if let Some(gate) = gate {
                        gate.notified().await;
                    }
                    tokio::time::sleep(delay).await;
                    call
                };
                #[cfg(test)]
                {
                    let failure = {
                        let state = demo.lock().unwrap();
                        state
                            .status_failure_at
                            .filter(|(at, _)| *at == call)
                            .map(|(_, code)| code)
                            .or(state.status_error)
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
                let status = demo.lock().unwrap().status();
                #[cfg(test)]
                demo.lock()
                    .unwrap()
                    .account_events
                    .push(AccountEvent::Status {
                        requested: config.username.clone(),
                        online: status.online,
                        owner: status.user.clone(),
                        service: status.service.clone(),
                    });
                Ok(status)
            }
        }
    }
    async fn info(&self, config: &Config) -> Result<InfoObservation, AuthError> {
        match self {
            Self::Native(recording) => {
                AuthClient::new(config.clone())?
                    .with_trace(recording.trace())
                    .info_observation()
                    .await
            }
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
                // Capture the actual source identity with the payload, without a second
                // backend status call, config-owner inference or display-field parsing.
                Ok(InfoObservation {
                    status: demo.status(),
                    info: json!({"online":online, "fields":if online { vec![["账号", demo.user.as_str()]] } else { vec![] },
                        "items":if online { vec![["剩余流量", "12.5 GB"]] } else { vec![] }}),
                })
            }
        }
    }
    /// Read the self-service portal as JSON so the UI needs one shape.
    async fn self_service(&self, config: &Config) -> Result<Value, AuthError> {
        match self {
            Self::Native(recording) => {
                let client = AuthClient::new(config.clone())?.with_trace(recording.trace());
                let snapshot: SelfSnapshot = client.self_snapshot().await?;
                Ok(serde_json::to_value(snapshot).unwrap_or(Value::Null))
            }
            Self::Demo(demo) => {
                config.require_credentials()?;
                let demo = demo.lock().unwrap();
                #[cfg(test)]
                if let Some(code) = demo.self_error {
                    let mut error = AuthError::new(
                        code,
                        "fixture self https://fixture-user:fixture-secret@portal.invalid/?token=fixture-token",
                    );
                    error.diagnostic = AuthDiagnostic {
                        operation: DiagnosticOperation::SelfService,
                        stage: DiagnosticStage::CasCallback,
                        reason: DiagnosticReason::RedirectBlocked,
                        navigation: None,
                    };
                    return Err(error);
                }
                let online = demo.online;
                let bound = demo.nosense_mac.as_deref() == Some("02-00-00-00-00-01");
                let snapshot = SelfSnapshot {
                    account: config.username.clone(),
                    local_mac: Some("02-00-00-00-00-01".into()),
                    devices: if online {
                        vec![SelfDevice {
                            device_name: "我的设备".into(),
                            device_type: "电脑".into(),
                            user_mac: "02-00-00-00-00-01".into(),
                            user_ipv4: Some("10.0.0.1".into()),
                            online_duration: "0时12分".into(),
                            auth_type: "无线标准Portal接入".into(),
                            current_device: true,
                            unified_authentication: true,
                            online_user_uuid: "fixture-device-1".into(),
                            online: true,
                            bind_no_sense: bound,
                            no_sense_expires: if bound {
                                demo.nosense_expires.clone()
                            } else {
                                String::new()
                            },
                            default_service: if bound {
                                if demo.nosense_service.is_empty() {
                                    "套餐默认服务".into()
                                } else {
                                    demo.nosense_service.clone()
                                }
                            } else {
                                String::new()
                            },
                            ..SelfDevice::default()
                        }]
                    } else {
                        Vec::new()
                    },
                    online: usize::from(online),
                    package: SelfPackage {
                        package: "硕士研究生60G".into(),
                        rule: "0.00—60.00GB内免费".into(),
                        period: "2026-11-01 至 2026-11-30".into(),
                        used: "国内下行流量:10 GB 46.53 MB /60 GB 0.00 MB".into(),
                        percent: Some(16.74),
                        balance: "0.00".into(),
                    },
                    flow: vec![ysu_auth::SelfFlow {
                        name: "国内下行流量".into(),
                        total: "60 GB 0.00 MB".into(),
                        left: "49 GB 977.47 MB".into(),
                        percent: Some(16.7),
                    }],
                    remember: SelfRemember {
                        remembered: Some(false),
                        service: String::new(),
                        expires: String::new(),
                    },
                };
                Ok(serde_json::to_value(snapshot).unwrap_or(Value::Null))
            }
        }
    }

    /// Take one device offline and return the verified result.
    async fn self_kick(&self, config: &Config, selector: &str) -> Result<Value, AuthError> {
        match self {
            Self::Native(recording) => {
                let client = AuthClient::new(config.clone())?.with_trace(recording.trace());
                let kick: SelfKick = client.self_kick(selector).await?;
                Ok(serde_json::to_value(kick).unwrap_or(Value::Null))
            }
            Self::Demo(demo) => {
                config.require_credentials()?;
                let mut demo = demo.lock().unwrap();
                if !demo.online {
                    return Err(AuthError::new(2, "设备编号超出范围"));
                }
                demo.online = false;
                let kick = SelfKick {
                    kicked: vec!["fixture-device-1".into()],
                    online_before: 1,
                    online_after: 0,
                    devices: Vec::new(),
                };
                Ok(serde_json::to_value(kick).unwrap_or(Value::Null))
            }
        }
    }

    async fn self_nosense_enable(
        &self,
        config: &Config,
        selector: &str,
        service: Option<&str>,
    ) -> Result<Value, AuthError> {
        match self {
            Self::Native(recording) => {
                let client = AuthClient::new(config.clone())?.with_trace(recording.trace());
                let out: SelfNoSense = client.self_nosense_enable(selector, service).await?;
                Ok(serde_json::to_value(out).unwrap_or(Value::Null))
            }
            Self::Demo(demo) => {
                config.require_credentials()?;
                let mut demo = demo.lock().unwrap();
                let mac = if selector.trim().is_empty()
                    || selector.eq_ignore_ascii_case("current")
                    || selector == "1"
                {
                    "02-00-00-00-00-01".to_string()
                } else {
                    ysu_auth::normalize_mac(selector)
                        .ok_or_else(|| AuthError::new(2, "MAC 地址格式无效"))?
                };
                let svc = match service.map(str::trim).filter(|s| !s.is_empty()) {
                    Some("校园网" | "套餐默认服务") => "套餐默认服务".to_string(),
                    Some(other) => other.to_string(),
                    None if !demo.nosense_service.is_empty() => demo.nosense_service.clone(),
                    None => "套餐默认服务".to_string(),
                };
                let renewed = demo.nosense_mac.is_some();
                demo.nosense_mac = Some(mac.clone());
                demo.nosense_service = svc.clone();
                let exp = "2026-11-17 22:00:00".to_string();
                demo.nosense_expires = exp.clone();
                demo.nosense_by_user.insert(
                    config.username.clone(),
                    (mac.clone(), svc.clone(), exp.clone()),
                );
                let out = SelfNoSense {
                    action: "nosense".into(),
                    mac,
                    bind_no_sense: true,
                    expires: exp,
                    service: svc,
                    renewed,
                    unbound: Vec::new(),
                    devices: Vec::new(),
                };
                Ok(serde_json::to_value(out).unwrap_or(Value::Null))
            }
        }
    }

    async fn self_nosense_disable(
        &self,
        config: &Config,
        selector: &str,
    ) -> Result<Value, AuthError> {
        match self {
            Self::Native(recording) => {
                let client = AuthClient::new(config.clone())?.with_trace(recording.trace());
                let out: SelfNoSense = client.self_nosense_disable(selector).await?;
                Ok(serde_json::to_value(out).unwrap_or(Value::Null))
            }
            Self::Demo(demo) => {
                config.require_credentials()?;
                let mut demo = demo.lock().unwrap();
                let removed_user = demo
                    .nosense_by_user
                    .remove(&config.username)
                    .map(|(m, _, _)| m);
                let Some(mac) = demo.nosense_mac.take().or(removed_user) else {
                    return Err(AuthError::new(2, "当前没有已开启无感认证的设备"));
                };
                demo.nosense_service.clear();
                demo.nosense_expires.clear();
                let out = SelfNoSense {
                    action: "unbind".into(),
                    mac: mac.clone(),
                    bind_no_sense: false,
                    expires: String::new(),
                    service: String::new(),
                    renewed: false,
                    unbound: vec![mac],
                    devices: Vec::new(),
                };
                Ok(serde_json::to_value(out).unwrap_or(Value::Null))
            }
        }
    }

    async fn self_device_service(
        &self,
        config: &Config,
        selector: &str,
        service: &str,
    ) -> Result<Value, AuthError> {
        match self {
            Self::Native(recording) => {
                let client = AuthClient::new(config.clone())?.with_trace(recording.trace());
                let out: SelfNoSense = client.self_device_service(selector, service).await?;
                Ok(serde_json::to_value(out).unwrap_or(Value::Null))
            }
            Self::Demo(demo) => {
                config.require_credentials()?;
                let mut demo = demo.lock().unwrap();
                let Some(mac) = demo.nosense_mac.clone() else {
                    return Err(AuthError::new(2, "请先为该设备开启无感认证"));
                };
                let svc = if service.trim() == "校园网" {
                    "套餐默认服务".to_string()
                } else {
                    service.trim().to_string()
                };
                demo.nosense_service = svc.clone();
                let exp = demo.nosense_expires.clone();
                demo.nosense_by_user.insert(
                    config.username.clone(),
                    (mac.clone(), svc.clone(), exp.clone()),
                );
                let out = SelfNoSense {
                    action: "service".into(),
                    mac,
                    bind_no_sense: true,
                    expires: demo.nosense_expires.clone(),
                    service: svc,
                    renewed: false,
                    unbound: Vec::new(),
                    devices: Vec::new(),
                };
                Ok(serde_json::to_value(out).unwrap_or(Value::Null))
            }
        }
    }

    async fn self_nosense_renew(
        &self,
        config: &Config,
        selector: &str,
        service: Option<&str>,
        force: bool,
    ) -> Result<Value, AuthError> {
        match self {
            Self::Native(recording) => {
                let client = AuthClient::new(config.clone())?.with_trace(recording.trace());
                let out: SelfNoSense = client.self_nosense_renew(selector, service, force).await?;
                Ok(serde_json::to_value(out).unwrap_or(Value::Null))
            }
            Self::Demo(demo) => {
                let mut out = self.self_nosense_enable(config, selector, service).await?;
                out["action"] = "renew".into();
                out["renewed"] = true.into();
                let _ = demo;
                Ok(out)
            }
        }
    }

    async fn mutate(&self, config: &Config, action: &Action) -> Result<Status, AuthError> {
        match self {
            Self::Native(recording) => {
                let client = AuthClient::new(config.clone())?.with_trace(recording.trace());
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
                    state.account_events.push(AccountEvent::Mutation {
                        action: match action {
                            Action::Login => "login",
                            Action::Logout => "logout",
                            Action::Switch(_) => "switch_service",
                            _ => unreachable!(),
                        },
                        requested: config.username.clone(),
                        service: config.service.clone(),
                    });
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
                    let (delay, gate) = {
                        let state = demo.lock().unwrap();
                        (state.delay, state.mutation_gate.clone())
                    };
                    if let Some(gate) = gate {
                        gate.notified().await;
                    }
                    tokio::time::sleep(delay).await;
                    flight.completed = true;
                }
                let mut demo = demo.lock().unwrap();
                #[cfg(test)]
                if matches!(action, Action::Login) {
                    #[cfg(test)]
                    if let Some(code) = demo.login_failures.get(&config.username) {
                        let mut error = AuthError::new(*code, "fixture candidate login failure");
                        if let Some(diagnostic) = demo.login_diagnostics.get(&config.username) {
                            error.diagnostic = *diagnostic;
                        }
                        return Err(error);
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

#[cfg(test)]
mod navigation_diagnostic_formatter_tests {
    use super::*;

    #[test]
    fn absent_navigation_keeps_exact_legacy_log_format() {
        let error = local_auth_error(
            2,
            DiagnosticOperation::Status,
            DiagnosticStage::PortalNavigation,
            DiagnosticReason::RedirectBlocked,
        );
        assert!(error.diagnostic().navigation.is_none());
        assert_eq!(
            diagnostic_detail("status", DiagnosticStage::OnlineState, &error),
            concat!(
                "action=status phase=online_state code=2 operation=status ",
                "stage=portal_navigation reason=redirect_blocked"
            )
        );
    }

    #[test]
    fn optional_navigation_appends_only_fixed_tokens_not_raw_error_material() {
        let mut error = local_auth_error(
            3,
            DiagnosticOperation::SwitchService,
            DiagnosticStage::CasNavigation,
            DiagnosticReason::RedirectBlocked,
        );
        error.message = concat!(
            "fixture-user fixture-password https://192.0.2.71/private-path",
            "?sessionId=fixture-session&ticket=fixture-ticket"
        )
        .into();
        let plain = diagnostic_detail("switch_service", DiagnosticStage::Verification, &error);
        let navigation = ysu_auth::NavigationDiagnostic::default();
        error.diagnostic.navigation = Some(navigation);
        let detail = diagnostic_detail("switch_service", DiagnosticStage::Verification, &error);
        assert_eq!(detail, format!("{plain} {}", navigation.detail()));
        assert_eq!(error.code, 3);
        assert_eq!(
            error.diagnostic().operation,
            DiagnosticOperation::SwitchService
        );
        assert_eq!(error.diagnostic().stage, DiagnosticStage::CasNavigation);
        assert_eq!(error.diagnostic().reason, DiagnosticReason::RedirectBlocked);
        for private in [
            "fixture-user",
            "fixture-password",
            "192.0.2.71",
            "private-path",
            "fixture-session",
            "fixture-ticket",
            "sessionId",
            "ticket=",
            "https://",
        ] {
            assert!(!detail.contains(private));
        }
        assert!(detail.contains("nav_kind=http_location"));
        assert!(detail.contains("nav_source_scheme=other"));
        assert!(detail.contains("nav_target_userinfo=false"));
    }
}
