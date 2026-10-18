//! Native Tauri facade; the runtime has no window or subprocess lifetime dependency.
use crate::{runtime::Runtime, storage::Store};
use serde_json::Value;
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc, Mutex,
};
use tauri::{AppHandle, Emitter, Manager};

pub use crate::runtime::valid_request;

pub struct CoreBridge {
    runtime: Mutex<Option<Arc<Runtime>>>,
    pub running: AtomicBool,
    pub quitting: AtomicBool,
    pub close_to_tray: AtomicBool,
    pub tray_available: AtomicBool,
    pub demo: bool,
    pub smoke: bool,
}

impl CoreBridge {
    pub fn new(demo: bool, smoke: bool) -> Arc<Self> {
        Arc::new(Self {
            runtime: Mutex::new(None),
            running: AtomicBool::new(false),
            quitting: AtomicBool::new(false),
            close_to_tray: AtomicBool::new(true),
            tray_available: AtomicBool::new(false),
            demo: demo || smoke,
            smoke,
        })
    }

    pub fn start(self: &Arc<Self>, app: &AppHandle, config: Option<String>) -> Result<(), String> {
        if self.running.load(Ordering::Acquire) {
            return Ok(());
        }
        let store = Store::open(config, self.demo)?;
        let weak = Arc::downgrade(self);
        let app = app.clone();
        let (runtime, receiver) = Runtime::new(
            store,
            Arc::new(move |value| {
                if let Some(bridge) = weak.upgrade() {
                    bridge.accept_snapshot(&app, &value);
                    let _ = app.emit(
                        "core-event",
                        serde_json::json!({"kind":"event", "name":"snapshot", "payload":value}),
                    );
                }
            }),
        )?;
        *self.runtime.lock().unwrap() = Some(runtime.clone());
        self.running.store(true, Ordering::Release);
        runtime.launch(receiver);
        Ok(())
    }

    fn accept_snapshot(&self, app: &AppHandle, value: &Value) {
        self.close_to_tray.store(
            value["prefs"]["close_to_tray"].as_bool().unwrap_or(false),
            Ordering::Release,
        );
        crate::update_tray(app, value);
        if let Some(window) = app.get_webview_window("main") {
            let theme = match value["prefs"]["theme"].as_str() {
                Some("dark") => Some(tauri::Theme::Dark),
                Some("light") => Some(tauri::Theme::Light),
                _ => None,
            };
            let _ = window.set_theme(theme);
        }
    }

    pub fn snapshot(&self) -> Value {
        let runtime = self.runtime.lock().unwrap().clone();
        runtime
            .map(|runtime| runtime.snapshot())
            .unwrap_or(Value::Null)
    }

    pub async fn request(&self, command: &str, args: Value) -> Result<Value, String> {
        if !valid_request(command, &args) {
            return Err("请求参数无效".into());
        }
        if self.quitting.load(Ordering::Acquire) {
            return Err("客户端正在退出".into());
        }
        let runtime = self
            .runtime
            .lock()
            .unwrap()
            .clone()
            .ok_or("后台运行器尚未启动")?;
        runtime.request(command, args).await
    }

    pub fn report_error(&self, message: &str) {
        let runtime = self.runtime.lock().unwrap().clone();
        if let Some(runtime) = runtime {
            runtime.report_error(message);
        }
    }

    pub async fn shutdown(&self) {
        let runtime = self.runtime.lock().unwrap().clone();
        if let Some(runtime) = runtime {
            runtime.shutdown().await;
        }
        self.running.store(false, Ordering::Release);
    }

    pub(crate) async fn persisted_prefs_for_smoke(&self) -> Result<Value, String> {
        if !self.smoke {
            return Err("偏好自检仅用于原生 smoke".into());
        }
        let runtime = self
            .runtime
            .lock()
            .unwrap()
            .clone()
            .ok_or("后台运行器尚未启动")?;
        runtime.persisted_prefs_for_smoke().await
    }

    pub fn force_stop(&self) {
        if let Some(runtime) = self.runtime.lock().unwrap().take() {
            runtime.force_stop();
        }
        self.running.store(false, Ordering::Release);
    }
}
