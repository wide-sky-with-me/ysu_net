//! Opt-in captcha model management for the settings page.
//! Decision: .agents/notes/implemented/desktop/2026-11-07-captcha-recognition.md
use crate::bridge::CoreBridge;
use serde::Serialize;
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc,
};
use tauri::State;

static DOWNLOADING: AtomicBool = AtomicBool::new(false);

#[derive(Clone, Debug, Serialize)]
pub struct CaptchaSnapshot {
    pub ready: bool,
    pub path: Option<String>,
    pub bytes: u64,
    pub url: &'static str,
    pub sha256: &'static str,
}

fn snapshot() -> CaptchaSnapshot {
    let status = ysu_auth::model_status();
    CaptchaSnapshot {
        ready: status.ready,
        path: status.path.map(|path| path.to_string_lossy().into_owned()),
        bytes: status.bytes,
        url: ysu_auth::MODEL_URL,
        sha256: ysu_auth::MODEL_SHA256,
    }
}

#[tauri::command]
pub fn captcha_status() -> CaptchaSnapshot {
    snapshot()
}

#[tauri::command]
pub async fn captcha_download(
    bridge: State<'_, Arc<CoreBridge>>,
) -> Result<CaptchaSnapshot, String> {
    if bridge.demo {
        return Err("离线模拟不下载验证码模型".into());
    }
    if bridge.quitting.load(Ordering::Acquire) {
        return Err("客户端正在退出".into());
    }
    if DOWNLOADING.swap(true, Ordering::AcqRel) {
        return Err("验证码模型正在下载".into());
    }
    let result = ysu_auth::download().await;
    DOWNLOADING.store(false, Ordering::Release);
    match result {
        Ok(_) => Ok(snapshot()),
        Err(error) => {
            // The auth library already returns fixed classifications; keep them.
            bridge.report_error("验证码模型下载失败");
            Err(format!("{error}"))
        }
    }
}
