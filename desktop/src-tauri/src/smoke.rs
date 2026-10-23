use crate::{bridge::CoreBridge, quit};
use serde_json::{json, Value};
use std::{
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc,
    },
    time::Duration,
};
use tauri::Manager;

#[derive(Default)]
pub struct SmokeState {
    rendered: AtomicBool,
    #[cfg(target_os = "linux")]
    tray_fixture: std::sync::Mutex<Option<zbus::blocking::Connection>>,
}

#[tauri::command]
pub fn smoke_rendered(app: tauri::AppHandle, rendered: bool) {
    if app.state::<Arc<CoreBridge>>().smoke {
        app.state::<SmokeState>()
            .rendered
            .store(rendered, Ordering::Release);
    }
}

async fn wait_for(
    bridge: &CoreBridge,
    predicate: impl Fn(&Value) -> bool,
) -> Result<Value, String> {
    for _ in 0..200 {
        let snapshot = bridge.snapshot();
        if predicate(&snapshot) {
            return Ok(snapshot);
        }
        tokio::time::sleep(Duration::from_millis(50)).await;
    }
    Err("离线原生自检等待状态超时".to_owned())
}

async fn verify_accent_preferences(bridge: &CoreBridge) -> Result<Value, String> {
    let original = bridge.snapshot()["prefs"].clone();
    let checked = async {
        let saved = bridge
            .request("save_prefs", json!({"accent":"rose"}))
            .await?;
        let persisted = bridge.persisted_prefs_for_smoke().await?;
        if saved["prefs"]["accent"] != "rose" || saved["prefs"] != persisted {
            return Err("主题色保存与磁盘重读不一致".to_owned());
        }
        if bridge
            .request("save_prefs", json!({"accent":"future-accent"}))
            .await
            .is_ok()
            || bridge.persisted_prefs_for_smoke().await? != persisted
            || bridge.snapshot()["prefs"] != persisted
        {
            return Err("非法主题色改变了偏好".into());
        }
        Ok(())
    }
    .await;
    // Restore the original preference even if a check failed, before other smoke flows run.
    let restored = bridge
        .request("save_prefs", json!({"accent":original["accent"]}))
        .await?;
    if restored["prefs"] != original || bridge.persisted_prefs_for_smoke().await? != original {
        return Err("主题色原偏好恢复失败".into());
    }
    checked?;
    Ok(json!({"saved":true,"disk_reloaded":true,"invalid_unchanged":true,"restored":true}))
}

async fn verify(app: &tauri::AppHandle) -> Result<Value, String> {
    let bridge = app.state::<Arc<CoreBridge>>().inner().clone();
    wait_for(&bridge, |snapshot| snapshot["sequence"].is_number()).await?;
    let accent_preferences = verify_accent_preferences(&bridge).await?;
    bridge
        .request("save_config", json!({"password":"20260001"}))
        .await?;
    bridge.request("action", json!({"name": "login"})).await?;
    wait_for(&bridge, |snapshot| {
        snapshot["status"]["online"] == true && snapshot["busy"] == false
    })
    .await?;
    bridge
        .request("action", json!({"name": "switch", "value": "中国移动"}))
        .await?;
    wait_for(&bridge, |snapshot| {
        snapshot["status"]["service"] == "中国移动" && snapshot["busy"] == false
    })
    .await?;
    bridge.request("action", json!({"name": "info"})).await?;
    wait_for(&bridge, |snapshot| {
        snapshot["info"]["online"] == true && snapshot["busy"] == false
    })
    .await?;
    let saved = bridge.request("save_account", json!({"label":"备用账号", "username":"native-fixture-b", "password":"native-fixture-b", "service":"中国移动", "backend":"api", "enabled":true})).await?;
    let id = saved["accounts"]["items"]
        .as_array()
        .and_then(|items| {
            items
                .iter()
                .find(|item| item["username"] == "native-fixture-b")
        })
        .and_then(|item| item["id"].as_str())
        .ok_or("原生账号簿未返回备用账号")?
        .to_owned();
    bridge.request("save_account", json!({"id":id,"label":"备用账号 B", "username":"native-fixture-b", "password":"", "service":"中国移动", "backend":"api", "enabled":true})).await?;
    bridge
        .request("action", json!({"name":"switch_account","value":id}))
        .await?;
    let selected = wait_for(&bridge, |snapshot| {
        snapshot["status"]["user"] == "native-fixture-b"
            && snapshot["config"]["username"] == "native-fixture-b"
            && snapshot["busy"] == false
    })
    .await?;
    if selected["config"].get("password").is_some()
        || selected["accounts"]["items"]
            .as_array()
            .is_none_or(|items| items.iter().any(|item| item.get("password").is_some()))
    {
        return Err("公开账号快照包含密码字段".into());
    }
    if bridge
        .request("delete_account", json!({"id":id}))
        .await
        .is_ok()
    {
        return Err("当前账号删除保护缺失".into());
    }
    let temporary = bridge.request("save_account", json!({"label":"可删除样例", "username":"native-fixture-c", "password":"native-only-secret-c", "service":"校园网", "backend":"api", "enabled":true})).await?;
    let temporary_id = temporary["accounts"]["items"]
        .as_array()
        .and_then(|items| {
            items
                .iter()
                .find(|item| item["username"] == "native-fixture-c")
        })
        .and_then(|item| item["id"].as_str())
        .ok_or("原生账号簿新增失败")?
        .to_owned();
    bridge
        .request("delete_account", json!({"id":temporary_id}))
        .await?;
    bridge.request("rotation", json!({"enabled":true})).await?;
    wait_for(&bridge, |snapshot| {
        snapshot["auto"]["state"] == "on"
            && snapshot["accounts"]["auto_switch"] == true
            && snapshot["accounts"]["quota"]["state"] == "available"
            && snapshot["busy"] == false
    })
    .await?;
    bridge.request("rotation", json!({"enabled":false})).await?;
    if bridge.snapshot()["accounts"]["auto_switch"] != false {
        return Err("自动换号关闭意图未生效".into());
    }
    bridge.request("rotation", json!({"enabled":true})).await?;
    println!("{}", json!({"phase": "visible", "mode": "demo"}));
    tokio::time::sleep(Duration::from_secs(2)).await;
    let window = app.get_webview_window("main").ok_or("原生窗口未创建")?;
    for _ in 0..80 {
        window.eval("window.__TAURI_INTERNALS__.invoke('smoke_rendered',{rendered:!!document.querySelector('main') && document.body.textContent.includes('中国移动') && document.body.textContent.includes('已连接') && document.body.textContent.includes('native-fixture-b')})")
            .map_err(|_| "执行原生界面自检失败")?;
        tokio::time::sleep(Duration::from_millis(100)).await;
        if app.state::<SmokeState>().rendered.load(Ordering::Acquire) {
            break;
        }
    }
    if !app.state::<SmokeState>().rendered.load(Ordering::Acquire) {
        return Err("原生 WebView 未渲染后台状态".to_owned());
    }
    let tray_initial = wait_for_tray(app, |menu| {
        menu["auto"] == true
            && menu["status"]
                .as_str()
                .is_some_and(|text| text.starts_with("已连接 · "))
            && menu["rotation"] == true
            && menu["identity"]
                .as_str()
                .is_some_and(|text| text.contains("native-fixture-b"))
    })
    .await?;
    if tray_initial["root_items"][0] != "open"
        || tray_initial["header_enabled"] != true
        || tray_initial["header"] != "打开燕大校园网"
        || tray_initial["detail_items"] != json!(["address", "activity"])
        || tray_initial["root_items"].as_array().is_none_or(|items| {
            items
                .iter()
                .any(|item| item == "address" || item == "activity")
        })
    {
        return Err("原生托盘菜单分组或打开窗口入口不正确".to_owned());
    }
    #[cfg(target_os = "linux")]
    if std::env::var("YSU_DESKTOP_SMOKE_TRAY_CAPTURE")
        .ok()
        .as_deref()
        == Some("1")
    {
        let handle = app.clone();
        app.run_on_main_thread(move || {
            if let Err(error) = crate::tray::popup_for_smoke(&handle) {
                eprintln!("原生菜单截图展示失败：{error}");
            }
        })
        .map_err(|_| "调度原生菜单展示失败")?;
        println!("{}", json!({"phase":"tray", "mode":"demo"}));
        tokio::time::sleep(Duration::from_secs(2)).await;
    }
    window.minimize().map_err(|_| "最小化调用失败")?;
    restore_window(app).await?;
    window.close().map_err(|_| "原生窗口关闭请求失败")?;
    wait_window(app, false).await?;
    tokio::time::sleep(Duration::from_secs(2)).await;
    if app.get_webview_window("main").is_some() || !bridge.running.load(Ordering::Acquire) {
        return Err("窗口和后台核心生命周期未分离".to_owned());
    }
    let background = bridge.request("snapshot", json!({})).await?;
    if background["status"]["online"] != true || background["auto"]["state"] != "on" {
        return Err("窗口销毁后后台状态未保持".to_owned());
    }
    println!("{}", json!({"phase": "background", "mode": "demo"}));
    tokio::time::sleep(Duration::from_secs(2)).await;
    crate::tray::dispatch(app, "auto");
    wait_for(&bridge, |s| {
        s["auto"]["state"] == "off" && s["accounts"]["auto_switch"] == false
    })
    .await?;
    wait_for_tray(app, |menu| {
        menu["auto"] == false && menu["rotation"] == false
    })
    .await?;
    crate::tray::dispatch(app, "connection");
    wait_for(&bridge, |s| {
        s["status"]["online"] == false && s["busy"] == false
    })
    .await?;
    let tray_offline = wait_for_tray(app, |menu| {
        menu["status"]
            .as_str()
            .is_some_and(|s| s.contains("未连接"))
            && menu["connection_enabled"] == true
    })
    .await?;
    crate::tray::dispatch(app, "connection");
    wait_for(&bridge, |s| {
        s["status"]["online"] == true && s["busy"] == false
    })
    .await?;
    crate::tray::dispatch(app, "refresh");
    wait_for(&bridge, |s| {
        s["info"]["online"] == true && s["busy"] == false
    })
    .await?;
    crate::tray::dispatch(app, "auto");
    wait_for(&bridge, |s| {
        s["auto"]["state"] == "on" && s["busy"] == false
    })
    .await?;
    crate::tray::dispatch(app, "rotation");
    wait_for(&bridge, |s| {
        s["accounts"]["auto_switch"] == true && s["busy"] == false
    })
    .await?;
    wait_for_tray(app, |menu| menu["auto"] == true && menu["rotation"] == true).await?;
    restore_window(app).await?;
    app.state::<SmokeState>()
        .rendered
        .store(false, Ordering::Release);
    for _ in 0..80 {
        let window = app.get_webview_window("main").ok_or("重建后的窗口缺失")?;
        window.eval("window.__TAURI_INTERNALS__.invoke('smoke_rendered',{rendered:!!document.querySelector('main') && document.body.textContent.includes('中国移动') && document.body.textContent.includes('已连接') && document.body.textContent.includes('native-fixture-b')})")
            .map_err(|_| "读取重建后的界面失败")?;
        tokio::time::sleep(Duration::from_millis(100)).await;
        if app.state::<SmokeState>().rendered.load(Ordering::Acquire) {
            break;
        }
    }
    if !app.state::<SmokeState>().rendered.load(Ordering::Acquire) {
        return Err("重建窗口未恢复后台快照".to_owned());
    }
    let mut host_loss_restored = false;
    #[cfg(target_os = "linux")]
    {
        let owned = app
            .state::<SmokeState>()
            .tray_fixture
            .lock()
            .unwrap()
            .is_some();
        if owned {
            app.get_webview_window("main")
                .ok_or("宿主丢失测试窗口缺失")?
                .close()
                .map_err(|_| "宿主测试关闭失败")?;
            wait_window(app, false).await?;
            app.state::<SmokeState>()
                .tray_fixture
                .lock()
                .unwrap()
                .take();
            wait_window(app, true).await?;
            if bridge.tray_available.load(Ordering::Acquire) {
                return Err("宿主丢失后能力标记未更新".into());
            }
            host_loss_restored = true;
        }
    }
    bridge.request("action", json!({"name": "logout"})).await?;
    wait_for(&bridge, |snapshot| {
        snapshot["status"]["online"] == false
            && snapshot["busy"] == false
            && snapshot["auto"]["state"] == "off"
            && snapshot["accounts"]["auto_switch"] == false
    })
    .await?;
    Ok(
        json!({"ok": true, "mode": "demo", "core_ipc": true, "rendered": true, "login": true, "switch": true, "account": true, "account_management":true, "account_switch":true, "rotation_control":true, "quota_reporting":true, "password_redacted":true, "auto_reconnect": true, "window_destroyed": true, "background_alive": true, "window_recreated": true, "logout": true,
            "accent_preferences":accent_preferences, "native_close_requested":true, "minimize_restore_api":true, "tray_native_menu_readback":true, "tray_actions_while_closed":true, "tray_initial":tray_initial, "tray_offline":tray_offline, "tray_host_loss_restored":host_loss_restored}),
    )
}

pub fn start(app: &tauri::AppHandle) {
    let app = app.clone();
    tauri::async_runtime::spawn(async move {
        let result = tokio::time::timeout(Duration::from_secs(60), verify(&app)).await;
        let (report, code) = match result {
            Ok(Ok(report)) => (report, 0),
            Ok(Err(error)) => (json!({"ok": false, "mode": "demo", "error": error}), 1),
            Err(_) => (
                json!({"ok": false, "mode": "demo", "error": "原生自检超时"}),
                1,
            ),
        };
        println!("{report}");
        if let Ok(path) = std::env::var("YSU_DESKTOP_SMOKE_REPORT") {
            if std::fs::write(path, format!("{report}\n")).is_err() {
                eprintln!("保存原生自检结果失败");
            }
        }
        let _ = quit(&app, code);
    });
}

async fn wait_window(app: &tauri::AppHandle, exists: bool) -> Result<(), String> {
    for _ in 0..260 {
        if app.get_webview_window("main").is_some() == exists {
            return Ok(());
        }
        tokio::time::sleep(Duration::from_millis(50)).await;
    }
    Err("窗口生命周期等待超时".into())
}

async fn restore_window(app: &tauri::AppHandle) -> Result<(), String> {
    let handle = app.clone();
    app.run_on_main_thread(move || crate::tray::dispatch(&handle, "open"))
        .map_err(|_| "调度恢复窗口失败")?;
    wait_window(app, true).await
}

async fn wait_for_tray(
    app: &tauri::AppHandle,
    predicate: impl Fn(&Value) -> bool,
) -> Result<Value, String> {
    for _ in 0..200 {
        let menu = crate::tray::inspect(app).map_err(|_| "读取原生托盘菜单失败")?;
        if predicate(&menu) && menu["quit_enabled"] == true {
            return Ok(menu);
        }
        tokio::time::sleep(Duration::from_millis(50)).await;
    }
    Err("原生托盘菜单状态等待超时".into())
}

pub fn prepare_tray_fixture(app: &tauri::AppHandle) -> Result<(), String> {
    #[cfg(target_os = "linux")]
    if !crate::tray_host_available() {
        let connection = (|| -> zbus::Result<_> {
            zbus::blocking::connection::Builder::session()?
                .name("org.kde.StatusNotifierWatcher")?
                .serve_at("/StatusNotifierWatcher", SmokeWatcher::default())?
                .build()
        })()
        .map_err(|_| "创建隔离托盘宿主样本失败")?;
        *app.state::<SmokeState>().tray_fixture.lock().unwrap() = Some(connection);
    }
    #[cfg(not(target_os = "linux"))]
    let _ = app;
    Ok(())
}

// A controlled D-Bus watcher, not a real desktop panel or hover implementation.
#[cfg(target_os = "linux")]
#[derive(Default)]
struct SmokeWatcher {
    items: std::sync::Mutex<Vec<String>>,
}

#[cfg(target_os = "linux")]
#[zbus::interface(name = "org.kde.StatusNotifierWatcher")]
impl SmokeWatcher {
    fn register_status_notifier_item(&self, service: &str) {
        self.items.lock().unwrap().push(service.into());
    }
    fn register_status_notifier_host(&self, _service: &str) {}
    #[zbus(property)]
    fn registered_status_notifier_items(&self) -> Vec<String> {
        self.items.lock().unwrap().clone()
    }
    #[zbus(property)]
    fn is_status_notifier_host_registered(&self) -> bool {
        true
    }
    #[zbus(property)]
    fn protocol_version(&self) -> i32 {
        0
    }
}
