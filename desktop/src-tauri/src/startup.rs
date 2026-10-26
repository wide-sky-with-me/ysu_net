//! Startup policy only; OS registration stays in the existing autostart plugin.
use serde_json::Value;
use std::future::Future;

pub const READ_ERROR: &str = "读取系统自启设置失败";
pub const WRITE_ERROR: &str = "更新系统自启设置失败，请检查安装位置及当前用户权限";
pub const VERIFY_ERROR: &str = "系统自启状态与请求不一致，请重试";
const DEMO_ERROR: &str = "模拟模式不修改系统自启配置";
const BUSY_ERROR: &str = "后台忙碌或正在更新，请稍后修改自启";

// Serialize native toggles and mode changes, including preference persistence.
#[derive(Default)]
pub struct StartupChanges {
    pub gate: tokio::sync::Mutex<()>,
}

#[derive(Clone, Copy, Default)]
pub struct LaunchOrigin {
    pub autostart: bool,
    pub minimized: bool,
    pub smoke: bool,
}

impl LaunchOrigin {
    pub fn from_args(args: &[String]) -> Self {
        let mut origin = Self::default();
        let mut args = args.iter();
        while let Some(arg) = args.next() {
            match arg.as_str() {
                "--autostart" => origin.autostart = true,
                "--minimized" => origin.minimized = true,
                "--smoke" => origin.smoke = true,
                // A profile path is data, even if it happens to resemble a flag.
                "--config" => {
                    args.next();
                }
                _ => {}
            }
        }
        origin
    }

    pub fn show_on_launch(self, minimized_pref: bool, tray_icon: bool, tray_host: bool) -> bool {
        self.smoke
            || !tray_icon
            || !tray_host
            || !(self.minimized || (self.autostart && minimized_pref))
    }

    pub fn show_on_reopen(self) -> bool {
        // A repeated automatic/background invocation must never steal focus,
        // even when its initial-launch preference would show a window.
        self.smoke || (!self.autostart && !self.minimized)
    }
}

pub fn registration_args(config: Option<&str>) -> Vec<String> {
    let mut args = vec!["--autostart".to_owned()];
    if let Some(path) = config {
        args.extend(["--config".to_owned(), path.to_owned()]);
    }
    args
}

pub trait Registration {
    type Error;
    fn is_enabled(&self) -> Result<bool, Self::Error>;
    fn enable(&self) -> Result<(), Self::Error>;
    fn disable(&self) -> Result<(), Self::Error>;
}

impl Registration for tauri_plugin_autostart::AutoLaunchManager {
    type Error = tauri_plugin_autostart::Error;

    fn is_enabled(&self) -> Result<bool, Self::Error> {
        self.is_enabled()
    }

    fn enable(&self) -> Result<(), Self::Error> {
        self.enable()
    }

    fn disable(&self) -> Result<(), Self::Error> {
        self.disable()
    }
}

pub fn mutation_allowed(demo: bool, busy: bool) -> Result<(), String> {
    if demo {
        return Err(DEMO_ERROR.into());
    }
    if busy {
        return Err(BUSY_ERROR.into());
    }
    Ok(())
}

pub fn read_enabled(manager: &impl Registration) -> Result<bool, String> {
    manager.is_enabled().map_err(|_| READ_ERROR.to_owned())
}

pub fn set_enabled(
    manager: &impl Registration,
    enabled: bool,
    demo: bool,
    busy: bool,
) -> Result<(), String> {
    mutation_allowed(demo, busy)?;
    let result = if enabled {
        manager.enable()
    } else {
        manager.disable()
    };
    result.map_err(|_| WRITE_ERROR.to_owned())?;
    if read_enabled(manager)? != enabled {
        return Err(VERIFY_ERROR.into());
    }
    Ok(())
}

pub async fn set_mode<F, Fut>(
    manager: &impl Registration,
    minimized: bool,
    demo: bool,
    busy: bool,
    persist: F,
) -> Result<Value, String>
where
    F: FnOnce(bool) -> Fut,
    Fut: Future<Output = Result<Value, String>>,
{
    mutation_allowed(demo, busy)?;
    if read_enabled(manager)? {
        // Pinned tauri-plugin-autostart 2.7.0 delegates enable() directly to
        // auto-launch 0.6.0: Windows set_string, Linux XDG truncate(true), and
        // macOS's default LaunchAgent File::create all replace existing args.
        // Source: https://docs.rs/crate/auto-launch/0.6.0/source/src/
        // Refresh legacy --minimized BEFORE saving the new preference. If the
        // save fails, --autostart still follows the unchanged old preference.
        set_enabled(manager, true, demo, busy)?;
    }
    // An OS-disabled entry is never enabled by changing the launch mode.
    persist(minimized).await
}

#[cfg(test)]
#[path = "startup_tests.rs"]
mod tests;
