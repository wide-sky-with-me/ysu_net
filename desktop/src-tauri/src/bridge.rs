//! Native Tauri facade; the runtime has no window or subprocess lifetime dependency.
//! Decision: .agents/notes/implemented/desktop/2026-10-22-diagnostics-and-update-lifecycle.md
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
    lifecycle: tokio::sync::Mutex<()>,
    quit_gate: Mutex<()>,
    installing: AtomicBool,
    updating: AtomicBool,
    startup: Mutex<Option<(AppHandle, Option<String>)>>,
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
            lifecycle: tokio::sync::Mutex::new(()),
            quit_gate: Mutex::new(()),
            installing: AtomicBool::new(false),
            updating: AtomicBool::new(false),
            startup: Mutex::new(None),
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
        let startup_config = config.clone();
        let store = Store::open(config, self.demo)?;
        let floor = self
            .runtime
            .lock()
            .unwrap()
            .as_ref()
            .and_then(|runtime| runtime.snapshot()["sequence"].as_u64())
            .unwrap_or(0)
            .saturating_add(1);
        *self.startup.lock().unwrap() = Some((app.clone(), startup_config));
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
        runtime.set_sequence_floor(floor);
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
        // Snapshot reads remain available while the authentication worker is paused.
        if command == "snapshot" {
            return Ok(self.snapshot());
        }
        let _lifecycle = self.lifecycle.lock().await;
        if self.quitting.load(Ordering::Acquire) {
            return Err("客户端正在退出".into());
        }
        if self.updating.load(Ordering::Acquire) {
            return Err("软件更新期间暂停认证操作".into());
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
        let _lifecycle = self.lifecycle.lock().await;
        let runtime = self.runtime.lock().unwrap().clone();
        if let Some(runtime) = runtime {
            runtime.shutdown().await;
        }
        self.running.store(false, Ordering::Release);
    }

    pub fn update_busy(&self) -> bool {
        self.updating.load(Ordering::Acquire)
            || self.quitting.load(Ordering::Acquire)
            || !self.running.load(Ordering::Acquire)
            || self.snapshot()["busy"].as_bool().unwrap_or(true)
    }

    pub async fn pause_for_update(&self) -> Result<(), String> {
        let _lifecycle = self.lifecycle.lock().await;
        let runtime = self
            .runtime
            .lock()
            .unwrap()
            .clone()
            .ok_or("后台运行器尚未启动")?;
        {
            let _quit = self.quit_gate.lock().unwrap();
            if self.demo
                || self.quitting.load(Ordering::Acquire)
                || self.updating.load(Ordering::Acquire)
            {
                return Err("当前状态不允许安装更新".into());
            }
            // Quit admission and installation admission must be one atomic decision.
            runtime.pause_for_update()?;
            self.updating.store(true, Ordering::Release);
            self.installing.store(true, Ordering::Release);
        }
        runtime.shutdown().await;
        self.running.store(false, Ordering::Release);
        Ok(())
    }

    pub(crate) fn try_begin_quit(&self) -> Result<bool, String> {
        let _quit = self.quit_gate.lock().unwrap();
        if self.installing.load(Ordering::Acquire) {
            return Err("正在安装软件更新，完成后可退出".into());
        }
        Ok(!self.quitting.swap(true, Ordering::AcqRel))
    }

    pub(crate) fn finish_update_installation(&self) {
        let _quit = self.quit_gate.lock().unwrap();
        self.installing.store(false, Ordering::Release);
    }

    fn begin_update_recovery(&self) -> Result<(), String> {
        let _quit = self.quit_gate.lock().unwrap();
        if !self.updating.load(Ordering::Acquire) || self.quitting.load(Ordering::Acquire) {
            return Err("当前状态不允许恢复认证后台".into());
        }
        // Keep normal quit out of synchronous runtime reconstruction without
        // holding this mutex across disk access, publication or UI callbacks.
        self.installing.store(true, Ordering::Release);
        Ok(())
    }

    pub async fn resume_after_update_failure(self: &Arc<Self>) -> Result<(), String> {
        let _lifecycle = self.lifecycle.lock().await;
        self.begin_update_recovery()?;
        let result = (|| {
            let (app, config) = self
                .startup
                .lock()
                .unwrap()
                .clone()
                .ok_or("启动上下文不可用")?;
            // start seeds the new stream above the stopped runtime's last sequence.
            self.start(&app, config)?;
            self.updating.store(false, Ordering::Release);
            Ok(())
        })();
        self.finish_update_installation();
        result
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
        self.startup.lock().unwrap().take();
        if let Some(runtime) = self.runtime.lock().unwrap().take() {
            runtime.force_stop();
        }
        self.running.store(false, Ordering::Release);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn installing_blocks_normal_quit_without_marking_quitting() {
        let bridge = CoreBridge::new(false, false);
        bridge.installing.store(true, Ordering::Release);
        assert!(bridge.try_begin_quit().is_err());
        assert!(!bridge.quitting.load(Ordering::Acquire));
        bridge.finish_update_installation();
        assert_eq!(bridge.try_begin_quit().unwrap(), true);
        assert_eq!(bridge.try_begin_quit().unwrap(), false);
    }

    #[test]
    fn recovery_admission_blocks_quit_without_reopening_authentication() {
        let bridge = CoreBridge::new(false, false);
        bridge.updating.store(true, Ordering::Release);
        bridge.begin_update_recovery().unwrap();
        assert!(bridge.try_begin_quit().is_err());
        assert!(!bridge.quitting.load(Ordering::Acquire));
        bridge.finish_update_installation();
        assert!(bridge.updating.load(Ordering::Acquire));
        assert!(bridge.try_begin_quit().unwrap());
        assert!(bridge.begin_update_recovery().is_err());
    }

    #[tokio::test]
    async fn failed_reconstruction_keeps_authentication_locked_but_allows_quit() {
        let bridge = CoreBridge::new(false, false);
        bridge.updating.store(true, Ordering::Release);
        assert!(bridge.resume_after_update_failure().await.is_err());
        assert!(bridge.updating.load(Ordering::Acquire));
        assert!(!bridge.installing.load(Ordering::Acquire));
        assert_eq!(
            bridge
                .request("snapshot", serde_json::json!({}))
                .await
                .unwrap(),
            Value::Null
        );
        assert!(bridge
            .request("action", serde_json::json!({"name":"status"}))
            .await
            .is_err());
        assert!(bridge.try_begin_quit().unwrap());
    }
}
