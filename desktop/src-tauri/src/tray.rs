//! Native tray adapter. No menu setter runs under a runtime/publication/cache lock.
//! Decision: .agents/notes/implemented/desktop/2026-10-15-tray-control.md
use crate::{
    bridge::CoreBridge,
    tray_model::{badged_icon, TrayView, Updates},
};
use serde_json::Value;
use std::sync::{atomic::Ordering, Arc, Mutex};
use tauri::{
    image::Image,
    menu::{CheckMenuItem, Menu, MenuItem, PredefinedMenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    Manager,
};

pub struct TrayState {
    status: MenuItem<tauri::Wry>,
    identity: MenuItem<tauri::Wry>,
    address: MenuItem<tauri::Wry>,
    quota: MenuItem<tauri::Wry>,
    activity: MenuItem<tauri::Wry>,
    connection: MenuItem<tauri::Wry>,
    refresh: MenuItem<tauri::Wry>,
    auto: CheckMenuItem<tauri::Wry>,
    rotation: CheckMenuItem<tauri::Wry>,
    menu: Menu<tauri::Wry>,
    quit: MenuItem<tauri::Wry>,
    updates: Mutex<Updates>,
}

fn menu_text(value: &str) -> String {
    // Ampersands are menu mnemonics on Windows, not part of user identities.
    if cfg!(target_os = "windows") {
        value.replace('&', "&&")
    } else {
        value.to_owned()
    }
}

pub fn install(app: &tauri::AppHandle) -> tauri::Result<()> {
    let status = MenuItem::with_id(app, "status", "YSU Net · 正在读取状态", false, None::<&str>)?;
    let identity = MenuItem::with_id(app, "identity", "账号：待确认", false, None::<&str>)?;
    let address = MenuItem::with_id(app, "address", "IP：待确认", false, None::<&str>)?;
    let quota = MenuItem::with_id(app, "quota", "剩余流量：待核验", false, None::<&str>)?;
    let activity = MenuItem::with_id(app, "activity", "等待后台状态", false, None::<&str>)?;
    let open = MenuItem::with_id(app, "open", "打开主窗口", true, None::<&str>)?;
    let connection = MenuItem::with_id(app, "connection", "查询连接状态", false, None::<&str>)?;
    let refresh = MenuItem::with_id(app, "refresh", "刷新连接与账户", false, None::<&str>)?;
    let auto = CheckMenuItem::with_id(app, "auto", "自动重连", false, false, None::<&str>)?;
    let rotation = CheckMenuItem::with_id(
        app,
        "rotation",
        "流量耗尽自动换号",
        false,
        false,
        None::<&str>,
    )?;
    let exit = MenuItem::with_id(app, "quit", "退出应用", true, None::<&str>)?;
    let divider = PredefinedMenuItem::separator(app)?;
    let controls_divider = PredefinedMenuItem::separator(app)?;
    let exit_divider = PredefinedMenuItem::separator(app)?;
    let menu = Menu::with_items(
        app,
        &[
            &status,
            &identity,
            &address,
            &quota,
            &activity,
            &divider,
            &open,
            &connection,
            &refresh,
            &controls_divider,
            &auto,
            &rotation,
            &exit_divider,
            &exit,
        ],
    )?;
    let mut builder = TrayIconBuilder::with_id("network")
        .menu(&menu)
        .tooltip("YSU Net · 正在读取状态")
        .show_menu_on_left_click(false)
        .on_menu_event(|app, event| {
            dispatch(app, event.id.as_ref());
        })
        .on_tray_icon_event(|tray, event| {
            if matches!(
                event,
                TrayIconEvent::Click {
                    button: MouseButton::Left,
                    button_state: MouseButtonState::Up,
                    ..
                }
            ) {
                dispatch(tray.app_handle(), "open");
            }
        });
    if let Some(icon) = app.default_window_icon() {
        builder = builder.icon(icon.clone());
    }
    builder.build(app)?;
    app.manage(TrayState {
        status,
        identity,
        address,
        quota,
        activity,
        connection,
        refresh,
        auto,
        rotation,
        menu,
        quit: exit,
        updates: Mutex::new(Updates::default()),
    });
    let bridge = app.state::<Arc<CoreBridge>>();
    bridge
        .tray_available
        .store(crate::tray_host_available(), Ordering::Release);
    // Runtime startup publishes before the native menu exists.
    update(app, &bridge.snapshot());
    monitor_host(app);
    Ok(())
}

pub fn dispatch(app: &tauri::AppHandle, id: &str) {
    if id == "quit" {
        crate::quit(app, 0);
        return;
    }
    if id == "open" {
        if crate::ensure_window(app).is_err() {
            report_error(app, "恢复主窗口失败，请从应用入口重新打开");
        }
        return;
    }
    if !matches!(id, "connection" | "refresh" | "auto" | "rotation") {
        return;
    }
    let bridge = app.state::<Arc<CoreBridge>>().inner().clone();
    let snapshot = bridge.snapshot();
    let view = TrayView::from_snapshot(
        &snapshot,
        bridge.running.load(Ordering::Acquire),
        bridge.quitting.load(Ordering::Acquire),
    );
    let Some((command, args)) = view.request(id) else {
        enqueue(app, &snapshot, true);
        return;
    };
    let app = app.clone();
    let refresh = id == "refresh";
    tauri::async_runtime::spawn(async move {
        let result = bridge.request(command, args).await;
        let result = if result.is_ok() && refresh {
            bridge
                .request("action", serde_json::json!({"name":"info"}))
                .await
        } else {
            result
        };
        if let Err(error) = result {
            bridge.report_error(&format!("托盘操作失败：{error}"));
        }
        // Checkable native menus may toggle before the request is accepted.
        // Force them back to the authoritative state, including on write failure.
        enqueue(&app, &bridge.snapshot(), true);
    });
}

fn report_error(app: &tauri::AppHandle, message: &'static str) {
    let bridge = app.state::<Arc<CoreBridge>>().inner().clone();
    tauri::async_runtime::spawn(async move {
        bridge.report_error(message);
    });
}

pub fn update(app: &tauri::AppHandle, snapshot: &Value) {
    enqueue(app, snapshot, false);
}

fn enqueue(app: &tauri::AppHandle, snapshot: &Value, force: bool) {
    let Some(state) = app.try_state::<TrayState>() else {
        return;
    };
    let bridge = app.state::<Arc<CoreBridge>>();
    let view = TrayView::from_snapshot(
        snapshot,
        bridge.running.load(Ordering::Acquire),
        bridge.quitting.load(Ordering::Acquire),
    );
    let schedule = state.updates.lock().unwrap().enqueue(
        snapshot["sequence"].as_u64().unwrap_or(0),
        view,
        force,
    );
    if !schedule {
        return;
    }
    let handle = app.clone();
    if app.run_on_main_thread(move || drain(&handle)).is_err() {
        state.updates.lock().unwrap().scheduling_failed();
        eprintln!("调度原生托盘更新失败；下次快照将重试");
    }
}

fn drain(app: &tauri::AppHandle) {
    let state = app.state::<TrayState>();
    let next = state.updates.lock().unwrap().take();
    let Some((view, force)) = next else {
        return;
    };
    let previous = state.updates.lock().unwrap().applied.clone();
    if !force && previous.as_ref() == Some(&view) {
        return;
    }
    // Native setters hold no locks. A newer publication schedules another UI turn.
    match apply(app, &state, &view, previous.as_ref()) {
        Ok(()) => state.updates.lock().unwrap().applied = Some(view),
        Err(error) => eprintln!("更新原生托盘失败（下次快照重试）：{error}"),
    }
}

fn apply(
    app: &tauri::AppHandle,
    state: &TrayState,
    view: &TrayView,
    previous: Option<&TrayView>,
) -> tauri::Result<()> {
    state.status.set_text(menu_text(&view.status))?;
    state.identity.set_text(menu_text(&view.identity))?;
    state.address.set_text(menu_text(&view.address))?;
    state.quota.set_text(menu_text(&view.quota))?;
    state
        .activity
        .set_text(menu_text(&format!("最近：{}", view.activity)))?;
    state.connection.set_text(&view.connection_label)?;
    state.connection.set_enabled(view.connection_enabled)?;
    state.refresh.set_enabled(view.refresh_enabled)?;
    state.auto.set_checked(view.auto_checked)?;
    state.auto.set_enabled(view.auto_enabled)?;
    state.rotation.set_checked(view.rotation_checked)?;
    state.rotation.set_enabled(view.rotation_enabled)?;
    if let Some(icon) = app.tray_by_id("network") {
        // Linux has no native tray tooltip API; its menu carries the same facts.
        #[cfg(not(target_os = "linux"))]
        icon.set_tooltip(Some(&view.tooltip))?;
        if previous.is_none_or(|previous| previous.indicator != view.indicator) {
            if let Some(base) = app.default_window_icon() {
                icon.set_icon(Some(Image::new_owned(
                    badged_icon(base.rgba(), base.width(), base.height(), view.indicator),
                    base.width(),
                    base.height(),
                )))?;
            }
        }
    }
    Ok(())
}

pub fn inspect(app: &tauri::AppHandle) -> tauri::Result<Value> {
    let state = app.state::<TrayState>();
    let view = state.updates.lock().unwrap().applied.clone();
    Ok(serde_json::json!({
        "status": state.status.text()?, "identity": state.identity.text()?,
        "address": state.address.text()?, "quota": state.quota.text()?,
        "connection": state.connection.text()?, "connection_enabled":state.connection.is_enabled()?,
        "refresh_enabled":state.refresh.is_enabled()?, "auto":state.auto.is_checked()?,
        "auto_enabled":state.auto.is_enabled()?, "rotation":state.rotation.is_checked()?,
        "rotation_enabled":state.rotation.is_enabled()?,
        "quit_enabled": state.quit.is_enabled()?,
        "tooltip":view.map(|view|view.tooltip), "tooltip_supported":!cfg!(target_os="linux")
    }))
}

fn monitor_host(app: &tauri::AppHandle) {
    #[cfg(target_os = "linux")]
    {
        let app = app.clone();
        tauri::async_runtime::spawn(async move {
            loop {
                tokio::time::sleep(std::time::Duration::from_secs(10)).await;
                let bridge = app.state::<Arc<CoreBridge>>();
                if bridge.quitting.load(Ordering::Acquire)
                    || !bridge.running.load(Ordering::Acquire)
                {
                    return;
                }
                let available = tauri::async_runtime::spawn_blocking(crate::tray_host_available)
                    .await
                    .unwrap_or(false);
                let previous = bridge.tray_available.swap(available, Ordering::AcqRel);
                if previous && !available && !bridge.quitting.load(Ordering::Acquire) {
                    let handle = app.clone();
                    if app
                        .run_on_main_thread(move || {
                            dispatch(&handle, "open");
                        })
                        .is_err()
                    {
                        eprintln!("托盘宿主已退出，恢复主窗口调度失败");
                    }
                }
            }
        });
    }
    #[cfg(not(target_os = "linux"))]
    let _ = app;
}

#[cfg(target_os = "linux")]
pub fn popup_for_smoke(app: &tauri::AppHandle) -> Result<(), String> {
    use tauri::menu::ContextMenu;
    let window = app.get_webview_window("main").ok_or("原生菜单窗口缺失")?;
    app.state::<TrayState>()
        .menu
        .popup_at(
            window.as_ref().window(),
            tauri::LogicalPosition::new(500.0, 45.0),
        )
        .map_err(|error| error.to_string())
}
