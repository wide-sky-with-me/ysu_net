//! Decision: .agents/notes/proposals/desktop/2026-10-14-rust-desktop.md
use fs2::FileExt;
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};
use std::{
    fs::{self, File, OpenOptions},
    io::Write,
    path::{Path, PathBuf},
    sync::Arc,
    time::{Duration, Instant},
};
use tempfile::{NamedTempFile, TempDir};
use ysu_auth::Config;

const CONFIG_LIMIT: u64 = 64 * 1024;
const FIELDS: &[&str] = &[
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
pub const CONFIG_ERROR: &str = "配置格式无效，请检查认证设置或配置文件";
pub const SAVE_ERROR: &str = "设置保存失败，请检查目录权限或稍后重试";
pub const EXTERNAL: &str = "后台服务正在管理此配置，请先执行 ysu stop";

pub fn valid_accent(value: &str) -> bool {
    matches!(
        value,
        "teal" | "blue" | "indigo" | "violet" | "rose" | "amber"
    )
}

fn default_accent() -> String {
    "teal".into()
}

#[derive(Clone, Serialize, Deserialize)]
pub struct Prefs {
    pub theme: String,
    #[serde(default = "default_accent")]
    pub accent: String,
    pub close_to_tray: bool,
    pub auto_reconnect: bool,
}

impl Default for Prefs {
    fn default() -> Self {
        Self {
            theme: "system".into(),
            accent: default_accent(),
            close_to_tray: true,
            auto_reconnect: false,
        }
    }
}

pub struct Store {
    pub path: PathBuf,
    pub demo: bool,
    _temporary: Option<TempDir>,
}

pub struct RunGuard {
    _file: File,
}

fn private_directory(path: &Path) -> Result<(), String> {
    let mut builder = fs::DirBuilder::new();
    builder.recursive(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::DirBuilderExt;
        builder.mode(0o700);
    }
    builder.create(path).map_err(|_| SAVE_ERROR.to_owned())
}

pub(crate) fn lock_file(path: &Path, wait: bool) -> Result<File, String> {
    private_directory(path.parent().ok_or(SAVE_ERROR)?)?;
    let mut options = OpenOptions::new();
    options.create(true).read(true).append(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    let file = options.open(path).map_err(|_| SAVE_ERROR.to_owned())?;
    let deadline = Instant::now() + Duration::from_secs(2);
    loop {
        match FileExt::try_lock_exclusive(&file) {
            Ok(()) => return Ok(file),
            Err(error) if error.kind() == std::io::ErrorKind::WouldBlock => {
                if !wait {
                    return Err(EXTERNAL.into());
                }
                if Instant::now() >= deadline {
                    return Err("其他进程正在保存设置，请稍后重试".into());
                }
                std::thread::sleep(Duration::from_millis(20));
            }
            Err(_) => return Err(SAVE_ERROR.into()),
        }
    }
}

pub(crate) fn write_json(path: &Path, value: &impl Serialize) -> Result<(), String> {
    let mut bytes = serde_json::to_vec_pretty(value).map_err(|_| SAVE_ERROR.to_owned())?;
    bytes.push(b'\n');
    if bytes.len() as u64 > CONFIG_LIMIT {
        return Err(CONFIG_ERROR.into());
    }
    let parent = path.parent().ok_or(SAVE_ERROR)?;
    private_directory(parent)?;
    let mut temporary = NamedTempFile::new_in(parent).map_err(|_| SAVE_ERROR.to_owned())?;
    temporary
        .write_all(&bytes)
        .map_err(|_| SAVE_ERROR.to_owned())?;
    temporary
        .as_file_mut()
        .sync_all()
        .map_err(|_| SAVE_ERROR.to_owned())?;
    temporary.persist(path).map_err(|_| SAVE_ERROR.to_owned())?;
    Ok(())
}

pub(crate) fn read_json(path: &Path) -> Result<Option<Value>, String> {
    let file = match File::open(path) {
        Ok(file) => file,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        Err(_) => return Err(CONFIG_ERROR.into()),
    };
    if file.metadata().map_err(|_| CONFIG_ERROR.to_owned())?.len() > CONFIG_LIMIT {
        return Err(CONFIG_ERROR.into());
    }
    use std::io::Read;
    let mut bytes = Vec::new();
    file.take(CONFIG_LIMIT + 1)
        .read_to_end(&mut bytes)
        .map_err(|_| CONFIG_ERROR.to_owned())?;
    if bytes.len() as u64 > CONFIG_LIMIT {
        return Err(CONFIG_ERROR.into());
    }
    serde_json::from_slice(&bytes)
        .map(Some)
        .map_err(|_| CONFIG_ERROR.into())
}

pub fn default_config_path() -> Result<PathBuf, String> {
    #[cfg(target_os = "windows")]
    let directory = std::env::var_os("APPDATA")
        .filter(|value| !value.is_empty())
        .map(PathBuf::from)
        .or_else(|| {
            std::env::var_os("USERPROFILE").map(|home| PathBuf::from(home).join("AppData/Roaming"))
        });
    #[cfg(not(target_os = "windows"))]
    let directory = unix_config_home(
        std::env::var_os("XDG_CONFIG_HOME"),
        std::env::var_os("HOME"),
    );
    directory
        .map(|path| path.join("ysu-net/config.json"))
        .ok_or_else(|| "未找到当前用户的配置目录".into())
}

// XDG: an empty or relative value is invalid and must fall back to the default.
#[cfg(not(target_os = "windows"))]
fn unix_config_home(
    xdg: Option<std::ffi::OsString>,
    home: Option<std::ffi::OsString>,
) -> Option<PathBuf> {
    xdg.map(PathBuf::from)
        .filter(|path| path.is_absolute())
        .or_else(|| home.map(|home| PathBuf::from(home).join(".config")))
}

impl Store {
    pub fn open(path: Option<String>, demo: bool) -> Result<Arc<Self>, String> {
        if demo {
            let directory = tempfile::Builder::new()
                .prefix("ysu-rust-demo-")
                .tempdir()
                .map_err(|_| SAVE_ERROR.to_owned())?;
            let store = Arc::new(Self {
                path: directory.path().join("config.json"),
                demo: true,
                _temporary: Some(directory),
            });
            let mut config = Config::default();
            config.username = "20260001".into();
            config.password = "demo-only-password".into();
            write_json(&store.path, &config)?;
            return Ok(store);
        }
        let path = match path {
            Some(path) => PathBuf::from(path),
            None => default_config_path()?,
        };
        let path = if path.is_absolute() {
            path
        } else {
            std::env::current_dir()
                .map_err(|_| CONFIG_ERROR.to_owned())?
                .join(path)
        };
        Ok(Arc::new(Self {
            path,
            demo: false,
            _temporary: None,
        }))
    }

    pub fn load_config(&self, with_environment: bool) -> Result<Config, String> {
        let mut data = match read_json(&self.path)? {
            Some(Value::Object(data)) if data.keys().all(|key| FIELDS.contains(&key.as_str())) => {
                data
            }
            Some(_) => return Err(CONFIG_ERROR.into()),
            None => Map::new(),
        };
        if with_environment && !self.demo {
            for (key, variable) in [
                ("username", "YSU_USER"),
                ("password", "YSU_PASS"),
                ("service", "YSU_SERVICE"),
            ] {
                if let Some(value) = std::env::var_os(variable) {
                    data.insert(
                        key.into(),
                        Value::String(value.to_string_lossy().into_owned()),
                    );
                }
            }
        }
        let config: Config =
            serde_json::from_value(Value::Object(data)).map_err(|_| CONFIG_ERROR.to_owned())?;
        config.validate().map_err(|_| CONFIG_ERROR.to_owned())?;
        Ok(config)
    }

    pub fn update_config(&self, mut changes: Map<String, Value>) -> Result<Config, String> {
        if changes.is_empty() || !changes.keys().all(|key| FIELDS.contains(&key.as_str())) {
            return Err(CONFIG_ERROR.into());
        }
        if changes
            .get("password")
            .is_some_and(|value| value.as_str() == Some(""))
        {
            changes.remove("password");
        }
        let lock_path = self.path.with_file_name(format!(
            "{}.write.lock",
            self.path.file_name().ok_or(CONFIG_ERROR)?.to_string_lossy()
        ));
        let _lock = lock_file(&lock_path, true)?;
        let mut data =
            serde_json::to_value(self.load_config(false)?).map_err(|_| CONFIG_ERROR.to_owned())?;
        data.as_object_mut().ok_or(CONFIG_ERROR)?.extend(changes);
        let candidate: Config =
            serde_json::from_value(data).map_err(|_| CONFIG_ERROR.to_owned())?;
        candidate.validate().map_err(|_| CONFIG_ERROR.to_owned())?;
        write_json(&self.path, &candidate)?;
        self.load_config(true)
    }

    fn prefs_path(&self) -> PathBuf {
        self.path.with_file_name("gui.json")
    }

    pub fn load_prefs(&self) -> Prefs {
        let mut prefs = Prefs::default();
        if let Ok(Some(Value::Object(data))) = read_json(&self.prefs_path()) {
            if let Some(value) = data
                .get("theme")
                .and_then(Value::as_str)
                .filter(|v| ["system", "light", "dark"].contains(v))
            {
                prefs.theme = value.into();
            }
            // Missing, malformed and future accent values fall back without rewriting the file.
            if let Some(value) = data
                .get("accent")
                .and_then(Value::as_str)
                .filter(|v| valid_accent(v))
            {
                prefs.accent = value.into();
            }
            if let Some(value) = data.get("close_to_tray").and_then(Value::as_bool) {
                prefs.close_to_tray = value;
            }
            if let Some(value) = data.get("auto_reconnect").and_then(Value::as_bool) {
                prefs.auto_reconnect = value;
            }
        }
        prefs
    }

    pub fn update_prefs(&self, changes: Map<String, Value>) -> Result<Prefs, String> {
        if changes.is_empty()
            || !changes.keys().all(|key| {
                ["theme", "accent", "close_to_tray", "auto_reconnect"].contains(&key.as_str())
            })
        {
            return Err("偏好参数无效".into());
        }
        if changes
            .get("accent")
            .is_some_and(|value| !value.as_str().is_some_and(valid_accent))
        {
            return Err("主题色参数无效".into());
        }
        let path = self.prefs_path();
        let _lock = lock_file(&path.with_file_name("gui.json.write.lock"), true)?;
        let mut data =
            serde_json::to_value(self.load_prefs()).map_err(|_| SAVE_ERROR.to_owned())?;
        data.as_object_mut().ok_or(SAVE_ERROR)?.extend(changes);
        let prefs: Prefs = serde_json::from_value(data).map_err(|_| "偏好参数无效".to_owned())?;
        if !["system", "light", "dark"].contains(&prefs.theme.as_str()) {
            return Err("外观参数无效".into());
        }
        write_json(&path, &prefs)?;
        Ok(prefs)
    }

    pub fn acquire_run(&self) -> Result<RunGuard, String> {
        Ok(RunGuard {
            _file: lock_file(&self.path.with_extension("lock"), false)?,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn changes(value: Value) -> Map<String, Value> {
        value.as_object().unwrap().clone()
    }

    #[test]
    fn demo_ignores_explicit_configuration_and_has_private_credentials() {
        let directory = tempfile::tempdir().unwrap();
        let real = directory.path().join("real.json");
        fs::write(&real, "not-json-private-fixture").unwrap();
        let store = Store::open(Some(real.to_string_lossy().into_owned()), true).unwrap();
        assert_ne!(store.path, real);
        assert_eq!(store.load_config(true).unwrap().username, "20260001");
        assert_eq!(
            fs::read_to_string(real).unwrap(),
            "not-json-private-fixture"
        );
    }

    #[test]
    fn empty_password_preserves_existing_and_updates_merge_latest_fields() {
        let store = Store::open(None, true).unwrap();
        store
            .update_config(changes(
                json!({"username": "fixture-a", "password": "kept-secret"}),
            ))
            .unwrap();
        store
            .update_config(changes(json!({"service": "中国移动", "password": ""})))
            .unwrap();
        let config = store.load_config(false).unwrap();
        assert_eq!(config.username, "fixture-a");
        assert_eq!(config.password, "kept-secret");
        assert_eq!(config.service, "中国移动");
    }

    #[test]
    fn running_and_configuration_write_locks_are_independent() {
        let store = Store::open(None, true).unwrap();
        let first = store.acquire_run().unwrap();
        assert!(store.acquire_run().is_err());
        store
            .update_config(changes(json!({"service": "中国移动"})))
            .unwrap();
        drop(first);
        assert!(store.acquire_run().is_ok());
    }

    #[test]
    fn preferences_filter_bad_fields_and_reject_invalid_updates() {
        let store = Store::open(None, true).unwrap();
        write_json(
            &store.prefs_path(),
            &json!({"theme":"invalid","close_to_tray":false,"auto_reconnect":"yes"}),
        )
        .unwrap();
        let prefs = store.load_prefs();
        assert_eq!(prefs.theme, "system");
        assert!(!prefs.close_to_tray);
        assert!(!prefs.auto_reconnect);
        assert!(store
            .update_prefs(changes(json!({"theme":"invalid"})))
            .is_err());
        assert!(store.update_prefs(changes(json!({"theme":"dark"}))).is_ok());
    }

    #[test]
    fn accent_preferences_round_trip_all_allowed_values_without_touching_authentication() {
        let store = Store::open(None, true).unwrap();
        let config_before = fs::read(&store.path).unwrap();
        store
            .update_prefs(changes(
                json!({"theme":"dark","close_to_tray":false,"auto_reconnect":true}),
            ))
            .unwrap();
        let _running = store.acquire_run().unwrap();
        let reopened = Store::open(Some(store.path.to_string_lossy().into_owned()), false).unwrap();
        for accent in ["teal", "blue", "indigo", "violet", "rose", "amber"] {
            let saved = store
                .update_prefs(changes(json!({"accent":accent})))
                .unwrap();
            assert_eq!(saved.accent, accent);
            let reloaded = reopened.load_prefs();
            assert_eq!(reloaded.accent, accent);
            assert_eq!(reloaded.theme, "dark");
            assert!(!reloaded.close_to_tray);
            assert!(reloaded.auto_reconnect);
            assert_eq!(
                read_json(&store.prefs_path()).unwrap().unwrap()["accent"],
                accent
            );
        }
        assert_eq!(fs::read(&store.path).unwrap(), config_before);
    }

    #[test]
    fn legacy_preferences_default_accent_and_keep_existing_fields() {
        let store = Store::open(None, true).unwrap();
        assert_eq!(store.load_prefs().accent, "teal");
        let legacy = json!({"theme":"light","close_to_tray":false,"auto_reconnect":true});
        write_json(&store.prefs_path(), &legacy).unwrap();
        let before = fs::read(store.prefs_path()).unwrap();
        let prefs = store.load_prefs();
        assert_eq!(prefs.accent, "teal");
        assert_eq!(prefs.theme, "light");
        assert!(!prefs.close_to_tray);
        assert!(prefs.auto_reconnect);
        assert_eq!(fs::read(store.prefs_path()).unwrap(), before);
        assert_eq!(
            serde_json::from_value::<Prefs>(legacy).unwrap().accent,
            "teal"
        );
        store
            .update_prefs(changes(json!({"close_to_tray":true})))
            .unwrap();
        assert_eq!(store.load_prefs().accent, "teal");
    }

    #[test]
    fn malformed_and_future_accent_values_fall_back_without_rewriting_valid_preferences() {
        let store = Store::open(None, true).unwrap();
        for accent in [
            json!("future-accent"),
            json!("TEAL"),
            json!(" teal"),
            json!(null),
            json!(false),
            json!(42),
            json!([]),
            json!({}),
        ] {
            write_json(
                &store.prefs_path(),
                &json!({
                    "accent":accent, "theme":"dark", "close_to_tray":false, "auto_reconnect":true
                }),
            )
            .unwrap();
            let before = fs::read(store.prefs_path()).unwrap();
            let prefs = store.load_prefs();
            assert_eq!(prefs.accent, "teal");
            assert_eq!(prefs.theme, "dark");
            assert!(!prefs.close_to_tray);
            assert!(prefs.auto_reconnect);
            assert_eq!(fs::read(store.prefs_path()).unwrap(), before);
        }
        for bytes in [b"not-json".as_slice(), b"[]", b"null"] {
            fs::write(store.prefs_path(), bytes).unwrap();
            assert_eq!(store.load_prefs().accent, "teal");
            assert_eq!(fs::read(store.prefs_path()).unwrap(), bytes);
        }
    }

    #[test]
    fn invalid_accent_updates_never_create_or_overwrite_preferences() {
        let store = Store::open(None, true).unwrap();
        let invalid = [
            json!("future-accent"),
            json!(""),
            json!("TEAL"),
            json!("teal "),
            json!(null),
            json!(true),
            json!(3),
            json!([]),
            json!({}),
        ];
        for accent in &invalid {
            assert!(store
                .update_prefs(changes(json!({"accent":accent})))
                .is_err());
            assert!(!store.prefs_path().exists());
            assert!(!store
                .prefs_path()
                .with_file_name("gui.json.write.lock")
                .exists());
        }
        store
            .update_prefs(changes(json!({"accent":"violet","theme":"dark"})))
            .unwrap();
        let before = fs::read(store.prefs_path()).unwrap();
        for accent in invalid {
            assert!(store
                .update_prefs(changes(json!({"accent":accent,"theme":"light"})))
                .is_err());
            assert_eq!(fs::read(store.prefs_path()).unwrap(), before);
            assert_eq!(store.load_prefs().accent, "violet");
        }
    }

    #[test]
    fn invalid_unknown_and_oversized_configuration_never_overwrites() {
        let store = Store::open(None, true).unwrap();
        assert!(store.update_config(changes(json!({"extra":true}))).is_err());
        assert!(store
            .update_config(changes(json!({"check_interval":0})))
            .is_err());
        let before = fs::read(&store.path).unwrap();
        assert!(store
            .update_config(changes(json!({"verify_tls":"no"})))
            .is_err());
        assert_eq!(before, fs::read(&store.path).unwrap());
        fs::write(&store.path, vec![b' '; CONFIG_LIMIT as usize + 1]).unwrap();
        assert!(store.load_config(false).is_err());
    }

    #[test]
    fn oversized_serialization_keeps_the_previous_file() {
        let store = Store::open(None, true).unwrap();
        let before = fs::read(&store.path).unwrap();
        assert!(write_json(
            &store.path,
            &json!({"fixture":"x".repeat(CONFIG_LIMIT as usize)})
        )
        .is_err());
        assert_eq!(before, fs::read(&store.path).unwrap());
        assert!(store.load_config(false).is_ok());
    }

    #[test]
    fn relative_configuration_is_resolved_without_creating_files() {
        let store = Store::open(Some("relative-fixture/config.json".into()), false).unwrap();
        assert!(store.path.is_absolute());
        assert_eq!(
            store.path,
            std::env::current_dir()
                .unwrap()
                .join("relative-fixture/config.json")
        );
    }

    #[cfg(unix)]
    #[test]
    fn empty_or_relative_xdg_config_home_falls_back_to_home() {
        let home = Some("/fixture-home".into());
        for xdg in ["", "relative/config"] {
            assert_eq!(
                unix_config_home(Some(xdg.into()), home.clone()),
                Some(PathBuf::from("/fixture-home/.config"))
            );
        }
        assert_eq!(
            unix_config_home(Some("/fixture-xdg".into()), home),
            Some(PathBuf::from("/fixture-xdg"))
        );
        assert_eq!(unix_config_home(None, None), None);
    }

    #[cfg(unix)]
    #[test]
    fn writes_keep_owner_only_permissions() {
        use std::os::unix::fs::PermissionsExt;
        let store = Store::open(None, true).unwrap();
        assert_eq!(
            fs::metadata(&store.path).unwrap().permissions().mode() & 0o777,
            0o600
        );
    }
}
