#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]
mod accounts;
mod bridge;
mod debug_recording;
mod project;
mod runtime;
mod smoke;
mod startup;
mod storage;
mod tray;
mod tray_model;
mod updater;

use bridge::CoreBridge;
use serde_json::{json, Value};
use std::sync::{atomic::Ordering, Arc, Mutex};
use tauri::{Manager, RunEvent, WebviewUrl, WebviewWindowBuilder, WindowEvent};
use tauri_plugin_autostart::ManagerExt;
use tray::{install as make_tray, update as update_tray};
#[cfg(test)]
use tray_model::auto_control_available;

#[derive(Default)]
struct WindowGeometry {
    size: Option<tauri::PhysicalSize<u32>>,
    position: Option<tauri::PhysicalPosition<i32>>,
}

#[derive(Default)]
struct Options {
    config: Option<String>,
    demo: bool,
    minimized: bool,
    autostart: bool,
    smoke: bool,
}

fn options() -> Result<Options, String> {
    let mut result = Options::default();
    let mut args = std::env::args().skip(1);
    while let Some(arg) = args.next() {
        match arg.as_str() {
            "--demo" => result.demo = true,
            "--smoke" => {
                result.smoke = true;
                result.demo = true;
            }
            "--minimized" => result.minimized = true,
            "--autostart" => result.autostart = true,
            "--config" => result.config = Some(args.next().ok_or("--config 需要文件路径")?),
            "--help" | "-h" => {
                println!("YSU Net 桌面客户端\n--demo 离线模拟\n--smoke 离线原生自检\n--minimized 强制以托盘方式启动\n--autostart 按偏好自启\n--config PATH 使用指定配置");
                std::process::exit(0);
            }
            _ if arg.starts_with("--config=") => result.config = Some(arg[9..].to_owned()),
            _ => return Err("未知启动参数，请运行 --help".to_owned()),
        }
    }
    if result.config.is_none() && !result.smoke {
        result.config = std::env::var("YSU_DESKTOP_CONFIG").ok();
    }
    result.demo |= std::env::var("YSU_DESKTOP_DEMO").as_deref() == Ok("1");
    if let Some(path) = &mut result.config {
        let absolute = std::env::current_dir()
            .map_err(|_| "读取启动目录失败")?
            .join(&*path);
        *path = absolute.to_string_lossy().into_owned();
    }
    // A smoke check must never inherit an operator's real account file.
    if result.smoke {
        result.config = None;
    }
    Ok(result)
}

fn ensure_window(app: &tauri::AppHandle) -> tauri::Result<()> {
    if let Some(window) = app.get_webview_window("main") {
        window.unminimize()?;
        window.show()?;
        window.set_focus()?;
        return Ok(());
    }
    let bridge = app.state::<Arc<CoreBridge>>();
    let title = if bridge.demo {
        "YSU Net · 模拟模式"
    } else {
        "YSU Net"
    };
    let theme = match bridge.snapshot()["prefs"]["theme"].as_str() {
        Some("dark") => Some(tauri::Theme::Dark),
        Some("light") => Some(tauri::Theme::Light),
        _ => None,
    };
    let window = WebviewWindowBuilder::new(app, "main", WebviewUrl::App("index.html".into()))
        .title(title)
        .inner_size(1000.0, 720.0)
        .min_inner_size(700.0, 560.0)
        .center()
        .theme(theme)
        .build()?;
    let geometry_state = app.state::<Mutex<WindowGeometry>>();
    let geometry = geometry_state.lock().unwrap();
    if let Some(size) = geometry.size {
        let _ = window.set_size(size);
    }
    if let Some(position) = geometry.position {
        let visible = window.available_monitors()?.iter().any(|monitor| {
            let origin = monitor.position();
            let size = monitor.size();
            position.x >= origin.x
                && position.y >= origin.y
                && position.x < origin.x + size.width as i32
                && position.y < origin.y + size.height as i32
        });
        if visible {
            let _ = window.set_position(position);
        }
    }
    window.set_focus()?;
    Ok(())
}

fn quit(app: &tauri::AppHandle, code: i32) -> Result<(), String> {
    let bridge = app.state::<Arc<CoreBridge>>().inner().clone();
    if !bridge.try_begin_quit()? {
        return Ok(());
    }
    let app = app.clone();
    tauri::async_runtime::spawn(async move {
        bridge.shutdown().await;
        app.exit(code);
    });
    Ok(())
}

#[tauri::command]
async fn core_request(
    command: String,
    args: Option<Value>,
    bridge: tauri::State<'_, Arc<CoreBridge>>,
) -> Result<Value, String> {
    let args = args.unwrap_or_else(|| json!({}));
    if !bridge::valid_request(&command, &args) {
        return Err("请求参数无效".to_owned());
    }
    if bridge.quitting.load(Ordering::Acquire) {
        return Err("客户端正在退出".to_owned());
    }
    bridge.request(&command, args).await
}

#[tauri::command]
fn get_desktop_settings(
    app: tauri::AppHandle,
    bridge: tauri::State<'_, Arc<CoreBridge>>,
) -> Result<Value, String> {
    let enabled = if bridge.demo {
        false
    } else {
        startup::read_enabled(&*app.autolaunch())?
    };
    Ok(
        json!({"autostart": enabled, "tray_available": bridge.tray_available.load(Ordering::Acquire),
        "tray_tooltip": !cfg!(target_os = "linux"),
        "version": app.package_info().version.to_string(), "demo": bridge.demo}),
    )
}

#[tauri::command]
async fn set_autostart(
    app: tauri::AppHandle,
    enabled: bool,
    bridge: tauri::State<'_, Arc<CoreBridge>>,
    changes: tauri::State<'_, startup::StartupChanges>,
) -> Result<(), String> {
    let _change = changes.gate.lock().await;
    startup::set_enabled(
        &*app.autolaunch(),
        enabled,
        bridge.demo,
        bridge.update_busy(),
    )
}

#[tauri::command]
async fn set_startup_mode(
    app: tauri::AppHandle,
    minimized: bool,
    bridge: tauri::State<'_, Arc<CoreBridge>>,
    changes: tauri::State<'_, startup::StartupChanges>,
) -> Result<Value, String> {
    let _change = changes.gate.lock().await;
    startup::set_mode(
        &*app.autolaunch(),
        minimized,
        bridge.demo,
        bridge.update_busy(),
        |minimized| async move {
            // Recheck after registration refresh and before any preference I/O.
            startup::mutation_allowed(bridge.demo, bridge.update_busy())?;
            bridge
                .request("save_prefs", json!({"autostart_minimized":minimized}))
                .await
        },
    )
    .await
}

#[tauri::command]
fn quit_app(app: tauri::AppHandle) -> Result<(), String> {
    quit(&app, 0)
}

fn tray_host_available() -> bool {
    #[cfg(target_os = "linux")]
    {
        let Ok(connection) = zbus::blocking::Connection::session() else {
            return false;
        };
        let Ok(proxy) = zbus::blocking::Proxy::new(
            &connection,
            "org.freedesktop.DBus",
            "/org/freedesktop/DBus",
            "org.freedesktop.DBus",
        ) else {
            return false;
        };
        proxy
            .call::<_, _, bool>("NameHasOwner", &("org.kde.StatusNotifierWatcher",))
            .unwrap_or(false)
    }
    #[cfg(not(target_os = "linux"))]
    {
        true
    }
}

fn main() {
    let options = match options() {
        Ok(options) => options,
        Err(message) => {
            eprintln!("{message}");
            std::process::exit(2);
        }
    };
    let bridge = CoreBridge::new(options.demo, options.smoke);
    let autostart_args = startup::registration_args(options.config.as_deref());
    let app = tauri::Builder::default()
        .manage(updater::normalized_restart_env(
            options.config.as_deref(),
            options.minimized,
            options.demo,
            options.smoke,
        ))
        .plugin(tauri_plugin_single_instance::init(|app, args, _| {
            if startup::LaunchOrigin::from_args(&args).show_on_reopen() {
                let _ = ensure_window(app);
            }
        }))
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(
            tauri_plugin_autostart::Builder::new()
                .args(autostart_args)
                .build(),
        )
        .manage(updater::UpdateManager::new(
            env!("CARGO_PKG_VERSION").into(),
            bridge.demo,
        ))
        .manage(startup::StartupChanges::default())
        .manage(bridge.clone())
        .manage(Mutex::new(WindowGeometry::default()))
        .manage(smoke::SmokeState::default())
        .invoke_handler(tauri::generate_handler![
            core_request,
            get_desktop_settings,
            set_autostart,
            set_startup_mode,
            quit_app,
            project::project_open_link,
            smoke::smoke_rendered,
            updater::updater_status,
            updater::updater_open_releases,
            updater::updater_check,
            updater::updater_install,
            updater::updater_resume,
            updater::updater_restart
        ])
        .setup(move |app| {
            let handle = app.handle();
            if options.smoke {
                smoke::prepare_tray_fixture(handle).map_err(std::io::Error::other)?;
            }
            bridge
                .start(handle, options.config)
                .map_err(std::io::Error::other)?;
            if let Err(error) = make_tray(handle) {
                eprintln!("创建系统托盘失败，关闭窗口将退出：{error}");
                bridge.tray_available.store(false, Ordering::Release);
            }
            let origin = startup::LaunchOrigin {
                autostart: options.autostart,
                minimized: options.minimized,
                smoke: options.smoke,
            };
            if origin.show_on_launch(
                bridge.snapshot()["prefs"]["autostart_minimized"]
                    .as_bool()
                    .unwrap_or(true),
                bridge.tray_available.load(Ordering::Acquire),
                tray_host_available(),
            ) {
                ensure_window(handle)?;
            }
            if options.smoke {
                smoke::start(handle);
            }
            Ok(())
        })
        .on_window_event(|window, event| {
            if let WindowEvent::CloseRequested { api, .. } = event {
                let app = window.app_handle();
                let bridge = app.state::<Arc<CoreBridge>>();
                if bridge.quitting.load(Ordering::Acquire) {
                    return;
                }
                api.prevent_close();
                let keep = bridge.close_to_tray.load(Ordering::Acquire)
                    && bridge.tray_available.load(Ordering::Acquire)
                    && tray_host_available();
                if keep {
                    let geometry_state = app.state::<Mutex<WindowGeometry>>();
                    let mut geometry = geometry_state.lock().unwrap();
                    geometry.size = window.inner_size().ok();
                    geometry.position = window.outer_position().ok();
                    drop(geometry);
                    // Destroy the WebView; the core and tray have independent lifetimes.
                    let _ = window.destroy();
                } else {
                    let _ = quit(app, 0);
                }
            }
        })
        .build(tauri::generate_context!())
        .expect("启动桌面客户端失败");
    app.run(|app, event| match event {
        RunEvent::ExitRequested { api, code, .. } => {
            let bridge = app.state::<Arc<CoreBridge>>();
            if !bridge.quitting.load(Ordering::Acquire) {
                api.prevent_exit();
                let background = code.is_none()
                    && (bridge.smoke
                        || (bridge.close_to_tray.load(Ordering::Acquire)
                            && bridge.tray_available.load(Ordering::Acquire)));
                if !background {
                    let _ = quit(app, code.unwrap_or(0));
                }
            }
        }
        RunEvent::Exit => app.state::<Arc<CoreBridge>>().force_stop(),
        #[cfg(target_os = "macos")]
        RunEvent::Reopen { .. } => {
            let _ = ensure_window(app);
        }
        _ => {}
    });
}
