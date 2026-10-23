//! User-initiated signed updates. No network work runs during setup or status reads.
//! The bundled updater public key is the trust root; IPC never accepts a key or URL.
use crate::bridge::CoreBridge;
use serde::Serialize;
use std::{
    future::Future,
    sync::{Arc, Mutex},
    time::Duration,
};
use tauri::{AppHandle, Emitter, State};
use tauri_plugin_updater::{Update, UpdaterExt};

pub const RELEASES_URL: &str = "https://github.com/wide-sky-with-me/ysu_net/releases/latest";
const FEED_URL: &str =
    "https://github.com/wide-sky-with-me/ysu_net/releases/latest/download/latest.json";
const ASSET_PREFIX: &str = "https://github.com/wide-sky-with-me/ysu_net/releases/download/";
const CHECK_TIMEOUT: Duration = Duration::from_secs(30);
const DOWNLOAD_TIMEOUT: Duration = Duration::from_secs(300);

/// Keep the effective Options across NSIS/LaunchServices restarts, whose working
/// directory and inherited environment need not match the original launcher.
/// `config` is the absolute path already resolved by startup's Options parser.
/// No account credentials or arbitrary raw arguments are added to the command line.
pub fn normalized_restart_env(
    config: Option<&str>,
    minimized: bool,
    demo: bool,
    smoke: bool,
) -> tauri::Env {
    let mut environment = tauri::Env::default();
    environment.args_os.truncate(1);
    if let Some(path) = config {
        environment.args_os.extend(["--config".into(), path.into()]);
    }
    for (flag, enabled) in [
        ("--minimized", minimized),
        ("--demo", demo),
        ("--smoke", smoke),
    ] {
        if enabled {
            environment.args_os.push(flag.into());
        }
    }
    environment
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum UpdatePhase {
    Idle,
    Disabled,
    Manual,
    Checking,
    UpToDate,
    Available,
    Downloading,
    Verifying,
    Quiescing,
    Installing,
    RestartRequired,
    RecoveryRequired,
    Error,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum UpdateError {
    Disabled,
    ManualOnly,
    Busy,
    CoreBusy,
    Configuration,
    FeedNotReady,
    CheckFailed,
    InvalidFeed,
    TargetMissing,
    UntrustedAsset,
    NoCandidate,
    StaleCandidate,
    DownloadFailed,
    Signature,
    CoreStopFailed,
    InstallFailed,
    ApplicationRestoreFailed,
    RecoveryFailed,
    InvalidState,
    OpenFailed,
}

// Never serialize or log the plugin's Display/Debug: reqwest errors can contain
// redirect URLs, query strings and signed download tokens.
fn public_error(error: &tauri_plugin_updater::Error, stage: UpdatePhase) -> UpdateError {
    use tauri_plugin_updater::Error as E;
    match error {
        E::Minisign(_)
        | E::Base64(_)
        | E::SignatureUtf8(_)
        | E::SignedVersionMismatch { .. }
        | E::MissingSignedVersion => UpdateError::Signature,
        E::TargetNotFound(_) | E::TargetsNotFound(_) | E::UnsupportedArch | E::UnsupportedOs => {
            UpdateError::TargetMissing
        }
        E::ReleaseNotFound => UpdateError::FeedNotReady,
        E::Serialization(_) | E::Semver(_) => UpdateError::InvalidFeed,
        E::EmptyEndpoints | E::InsecureTransportProtocol | E::UrlParse(_) => {
            UpdateError::Configuration
        }
        E::PreviousAppNotRestored(_) => UpdateError::ApplicationRestoreFailed,
        _ => match stage {
            UpdatePhase::Checking => UpdateError::CheckFailed,
            UpdatePhase::Downloading | UpdatePhase::Verifying => UpdateError::DownloadFailed,
            _ => UpdateError::InstallFailed,
        },
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct UpdateRelease {
    pub version: String,
    pub notes: String,
}

#[derive(Clone, Debug, Serialize)]
pub struct UpdateSnapshot {
    pub sequence: u64,
    pub phase: UpdatePhase,
    pub current_version: String,
    pub release: Option<UpdateRelease>,
    pub downloaded: u64,
    pub total: Option<u64>,
    pub error: Option<UpdateError>,
    pub releases_url: &'static str,
}

struct Session {
    snapshot: UpdateSnapshot,
    pending: Option<Update>,
}

// Dependency injection keeps native IPC tests from launching a user's browser.
// Only open_releases() supplies a URL, never an IPC argument or feed value.
type ReleasePageOpener = Box<dyn Fn(&'static str) -> Result<(), ()> + Send + Sync>;

pub struct UpdateManager {
    session: Mutex<Session>,
    operation: tokio::sync::Mutex<()>,
    release_opener: ReleasePageOpener,
    demo: bool,
    automatic: bool,
}

impl UpdateManager {
    pub fn new(version: String, demo: bool) -> Self {
        // The shipped Linux product is a deb, not an AppImage updater product.
        Self::with_support(version, demo, cfg!(any(windows, target_os = "macos")))
    }

    fn with_support(version: String, demo: bool, automatic: bool) -> Self {
        Self {
            session: Mutex::new(Session {
                snapshot: UpdateSnapshot {
                    sequence: 0,
                    phase: if demo {
                        UpdatePhase::Disabled
                    } else if automatic {
                        UpdatePhase::Idle
                    } else {
                        UpdatePhase::Manual
                    },
                    current_version: version,
                    release: None,
                    downloaded: 0,
                    total: None,
                    error: None,
                    releases_url: RELEASES_URL,
                },
                pending: None,
            }),
            operation: tokio::sync::Mutex::new(()),
            // Use the official Rust API directly: no guest opener commands,
            // permissions, automatic link interception, or JS dependency.
            release_opener: Box::new(|url| {
                tauri_plugin_opener::open_url(url, None::<&str>).map_err(|_| ())
            }),
            demo,
            automatic,
        }
    }

    fn open_releases(&self) -> Result<(), UpdateError> {
        if self.demo {
            return Err(UpdateError::Disabled);
        }
        // Linux deb intentionally permits manual download even though check/install
        // are unsupported. Do not gate this on permitted().
        (self.release_opener)(RELEASES_URL).map_err(|_| UpdateError::OpenFailed)
    }

    fn permitted(&self) -> Result<(), UpdateError> {
        if self.demo {
            Err(UpdateError::Disabled)
        } else if !self.automatic {
            Err(UpdateError::ManualOnly)
        } else {
            Ok(())
        }
    }

    fn snapshot(&self) -> UpdateSnapshot {
        self.session.lock().unwrap().snapshot.clone()
    }

    fn change(&self, app: &AppHandle, change: impl FnOnce(&mut Session)) -> UpdateSnapshot {
        let snapshot = {
            let mut session = self.session.lock().unwrap();
            change(&mut session);
            session.snapshot.sequence = session.snapshot.sequence.saturating_add(1);
            session.snapshot.clone()
        };
        let _ = app.emit("updater-event", &snapshot);
        snapshot
    }

    fn fail(&self, app: &AppHandle, error: UpdateError, recovery: bool) -> UpdateSnapshot {
        self.change(app, |session| {
            session.snapshot.phase = if recovery {
                UpdatePhase::RecoveryRequired
            } else {
                UpdatePhase::Error
            };
            session.snapshot.error = Some(error);
        })
    }
}

// Only initial GitHub Release asset URLs are accepted. GitHub's official HTTPS
// CDN redirects are handled by the plugin; their raw addresses never enter IPC.
fn trusted_asset_url(url: &tauri::Url, signature: &str) -> bool {
    url.scheme() == "https"
        && url.host_str() == Some("github.com")
        && url.port().is_none()
        && url.username().is_empty()
        && url.password().is_none()
        && url.query().is_none()
        && url.fragment().is_none()
        && url.as_str().starts_with(ASSET_PREFIX)
        && url.path_segments().is_some_and(|parts| parts.count() == 6)
        && !signature.trim().is_empty()
}

trait Progress: Sync {
    fn phase(&self, phase: UpdatePhase);
    fn chunk(&self, length: usize, total: Option<u64>);
}

trait Artifact: Sync {
    fn download(
        &self,
        progress: &impl Progress,
    ) -> impl Future<Output = Result<Vec<u8>, UpdateError>> + Send;
    fn install(&self, bytes: Vec<u8>) -> impl Future<Output = Result<(), UpdateError>> + Send;
}

impl Artifact for Update {
    async fn download(&self, progress: &impl Progress) -> Result<Vec<u8>, UpdateError> {
        // on_download_finish happens before signature verification, not after it.
        // Only a successful download() return means verified bytes.
        tokio::time::timeout(
            DOWNLOAD_TIMEOUT,
            Update::download(
                self,
                |length, total| progress.chunk(length, total),
                || progress.phase(UpdatePhase::Verifying),
            ),
        )
        .await
        .map_err(|_| UpdateError::DownloadFailed)?
        .map_err(|error| public_error(&error, UpdatePhase::Downloading))
    }

    async fn install(&self, bytes: Vec<u8>) -> Result<(), UpdateError> {
        let update = self.clone();
        tauri::async_runtime::spawn_blocking(move || update.install(bytes))
            .await
            .map_err(|_| UpdateError::InstallFailed)?
            .map_err(|error| public_error(&error, UpdatePhase::Installing))
    }
}

trait CoreGate: Sync {
    fn busy(&self) -> bool;
    fn pause(&self) -> impl Future<Output = Result<(), UpdateError>> + Send;
    fn resume(&self) -> impl Future<Output = Result<(), UpdateError>> + Send;
    fn finish(&self);
}

impl CoreGate for Arc<CoreBridge> {
    fn busy(&self) -> bool {
        self.update_busy()
    }
    async fn pause(&self) -> Result<(), UpdateError> {
        self.pause_for_update()
            .await
            .map_err(|_| UpdateError::CoreStopFailed)
    }
    async fn resume(&self) -> Result<(), UpdateError> {
        self.resume_after_update_failure()
            .await
            .map_err(|_| UpdateError::RecoveryFailed)
    }
    fn finish(&self) {
        self.finish_update_installation();
    }
}

struct NativeProgress<'a> {
    manager: &'a UpdateManager,
    app: &'a AppHandle,
}
impl Progress for NativeProgress<'_> {
    fn phase(&self, phase: UpdatePhase) {
        self.manager
            .change(self.app, |session| session.snapshot.phase = phase);
    }
    fn chunk(&self, length: usize, total: Option<u64>) {
        self.manager.change(self.app, |session| {
            session.snapshot.downloaded = session.snapshot.downloaded.saturating_add(length as u64);
            session.snapshot.total = total.filter(|total| *total > 0);
        });
    }
}

#[derive(Debug)]
struct InstallFailure {
    error: UpdateError,
    recovery: bool,
}

async fn apply_update(
    artifact: &impl Artifact,
    core: &impl CoreGate,
    progress: &impl Progress,
) -> Result<(), InstallFailure> {
    let before_pause = |error| InstallFailure {
        error,
        recovery: false,
    };
    if core.busy() {
        return Err(before_pause(UpdateError::CoreBusy));
    }
    progress.phase(UpdatePhase::Downloading);
    let bytes = artifact.download(progress).await.map_err(before_pause)?;
    // Authentication may have started during download. pause() must also check
    // atomically with request admission, not merely trust this observation.
    if core.busy() {
        return Err(before_pause(UpdateError::CoreBusy));
    }
    progress.phase(UpdatePhase::Quiescing);
    core.pause().await.map_err(before_pause)?;
    progress.phase(UpdatePhase::Installing);
    let result = match artifact.install(bytes).await {
        // Windows exits inside install(). macOS returns with the old core still
        // stopped; finish only releases the ordinary-quit critical section.
        Ok(()) => Ok(()),
        Err(UpdateError::ApplicationRestoreFailed) => Err(InstallFailure {
            error: UpdateError::ApplicationRestoreFailed,
            recovery: true,
        }),
        Err(error) => {
            if core.resume().await.is_err() {
                Err(InstallFailure {
                    error: UpdateError::RecoveryFailed,
                    recovery: true,
                })
            } else {
                Err(before_pause(error))
            }
        }
    };
    // Keep quit blocked until both the blocking installer and any core recovery
    // have reached a terminal result. Never release from on_before_exit: Windows
    // invokes that callback before even launching the installer.
    core.finish();
    if result.is_ok() {
        progress.phase(UpdatePhase::RestartRequired);
    }
    result
}

#[tauri::command]
pub fn updater_open_releases(manager: State<'_, UpdateManager>) -> Result<(), UpdateError> {
    manager.open_releases()
}

#[tauri::command]
pub fn updater_status(manager: State<'_, UpdateManager>) -> UpdateSnapshot {
    manager.snapshot()
}

#[tauri::command]
pub async fn updater_check(
    app: AppHandle,
    manager: State<'_, UpdateManager>,
) -> Result<UpdateSnapshot, UpdateError> {
    manager.permitted()?;
    let _operation = manager
        .operation
        .try_lock()
        .map_err(|_| UpdateError::Busy)?;
    if matches!(
        manager.snapshot().phase,
        UpdatePhase::RestartRequired | UpdatePhase::RecoveryRequired
    ) {
        return Err(UpdateError::InvalidState);
    }
    manager.change(&app, |session| {
        session.pending = None;
        session.snapshot.phase = UpdatePhase::Checking;
        session.snapshot.release = None;
        session.snapshot.error = None;
        session.snapshot.downloaded = 0;
        session.snapshot.total = None;
    });
    let checked = async {
        let public_key = app
            .config()
            .plugins
            .0
            .get("updater")
            .and_then(|config| config.get("pubkey"))
            .and_then(|value| value.as_str())
            .filter(|key| !key.trim().is_empty())
            .ok_or(UpdateError::Configuration)?;
        let updater = app
            .updater_builder()
            .pubkey(public_key)
            .endpoints(vec![FEED_URL
                .parse()
                .map_err(|_| UpdateError::Configuration)?])
            .map_err(|_| UpdateError::Configuration)?
            .clear_headers()
            .timeout(CHECK_TIMEOUT)
            .build()
            .map_err(|_| UpdateError::Configuration)?;
        let candidate = tokio::time::timeout(CHECK_TIMEOUT, updater.check())
            .await
            .map_err(|_| UpdateError::CheckFailed)?
            .map_err(|error| public_error(&error, UpdatePhase::Checking))?;
        if candidate
            .as_ref()
            .is_some_and(|update| !trusted_asset_url(&update.download_url, &update.signature))
        {
            return Err(UpdateError::UntrustedAsset);
        }
        Ok(candidate)
    }
    .await;
    match checked {
        Ok(candidate) => Ok(manager.change(&app, |session| {
            session.snapshot.phase = if candidate.is_some() {
                UpdatePhase::Available
            } else {
                UpdatePhase::UpToDate
            };
            session.snapshot.release = candidate.as_ref().map(|update| UpdateRelease {
                version: update.version.clone(),
                notes: update
                    .body
                    .as_deref()
                    .unwrap_or("")
                    .chars()
                    .take(16_384)
                    .collect(),
            });
            session.pending = candidate.map(|mut update| {
                update.timeout = Some(DOWNLOAD_TIMEOUT);
                update
            });
        })),
        Err(error) => {
            manager.fail(&app, error, false);
            Err(error)
        }
    }
}

#[tauri::command]
pub async fn updater_install(
    app: AppHandle,
    version: String,
    bridge: State<'_, Arc<CoreBridge>>,
    manager: State<'_, UpdateManager>,
) -> Result<UpdateSnapshot, UpdateError> {
    manager.permitted()?;
    if bridge.demo {
        return Err(UpdateError::Disabled);
    }
    let _operation = manager
        .operation
        .try_lock()
        .map_err(|_| UpdateError::Busy)?;
    if matches!(
        manager.snapshot().phase,
        UpdatePhase::RestartRequired | UpdatePhase::RecoveryRequired
    ) {
        return Err(UpdateError::InvalidState);
    }
    let candidate = manager
        .session
        .lock()
        .unwrap()
        .pending
        .clone()
        .ok_or(UpdateError::NoCandidate)?;
    if candidate.version != version {
        return Err(UpdateError::StaleCandidate);
    }
    manager.change(&app, |session| {
        session.snapshot.error = None;
        session.snapshot.downloaded = 0;
        session.snapshot.total = None;
    });
    let progress = NativeProgress {
        manager: &manager,
        app: &app,
    };
    match apply_update(&candidate, bridge.inner(), &progress).await {
        Ok(()) => Ok(manager.change(&app, |session| session.pending = None)),
        Err(failure) => {
            manager.fail(&app, failure.error, failure.recovery);
            Err(failure.error)
        }
    }
}

#[tauri::command]
pub async fn updater_resume(
    app: AppHandle,
    bridge: State<'_, Arc<CoreBridge>>,
    manager: State<'_, UpdateManager>,
) -> Result<UpdateSnapshot, UpdateError> {
    manager.permitted()?;
    let _operation = manager
        .operation
        .try_lock()
        .map_err(|_| UpdateError::Busy)?;
    let snapshot = manager.snapshot();
    if snapshot.phase != UpdatePhase::RecoveryRequired
        || snapshot.error != Some(UpdateError::RecoveryFailed)
    {
        return Err(UpdateError::InvalidState);
    }
    match bridge.resume_after_update_failure().await {
        Ok(()) => Ok(manager.change(&app, |session| {
            session.snapshot.phase = UpdatePhase::Error;
            session.snapshot.error = Some(UpdateError::InstallFailed);
        })),
        Err(_) => {
            manager.fail(&app, UpdateError::RecoveryFailed, true);
            Err(UpdateError::RecoveryFailed)
        }
    }
}

#[tauri::command]
pub fn updater_restart(
    app: AppHandle,
    manager: State<'_, UpdateManager>,
) -> Result<(), UpdateError> {
    manager.permitted()?;
    if manager.snapshot().phase != UpdatePhase::RestartRequired {
        return Err(UpdateError::InvalidState);
    }
    app.restart();
}

#[cfg(test)]
#[path = "updater_tests.rs"]
mod tests;
