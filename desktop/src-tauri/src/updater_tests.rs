//! Offline lifecycle tests: artifact/gate mocks never download or run an installer.
//! Lifecycle mocks exercise admission/recovery; official verifier tests use a fixed signed text fixture.
use super::*;
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};

type Trace = Arc<Mutex<Vec<&'static str>>>;
const FIXTURE_BYTES: &[u8] = b"offline updater artifact fixture; never executable";

struct MockArtifact {
    trace: Trace,
    download_error: Option<UpdateError>,
    install_error: Option<UpdateError>,
    critical: Arc<AtomicBool>,
}
impl Artifact for MockArtifact {
    async fn download(&self, progress: &impl Progress) -> Result<Vec<u8>, UpdateError> {
        self.trace.lock().unwrap().push("download");
        progress.chunk(12, Some(FIXTURE_BYTES.len() as u64));
        progress.chunk(FIXTURE_BYTES.len() - 12, Some(FIXTURE_BYTES.len() as u64));
        progress.phase(UpdatePhase::Verifying);
        self.trace.lock().unwrap().push("verify");
        if let Some(error) = self.download_error {
            return Err(error);
        }
        Ok(FIXTURE_BYTES.to_vec())
    }
    async fn install(&self, bytes: Vec<u8>) -> Result<(), UpdateError> {
        assert_eq!(bytes, FIXTURE_BYTES);
        assert!(
            self.critical.load(Ordering::Acquire),
            "ordinary quit must remain blocked throughout installation"
        );
        self.trace.lock().unwrap().push("install");
        self.install_error.map_or(Ok(()), Err)
    }
}

struct MockCore {
    trace: Trace,
    busy_calls: AtomicUsize,
    busy_at: usize,
    pause_error: Option<UpdateError>,
    resume_error: Option<UpdateError>,
    critical: Arc<AtomicBool>,
}
impl CoreGate for MockCore {
    fn busy(&self) -> bool {
        self.busy_calls.fetch_add(1, Ordering::AcqRel) >= self.busy_at
    }
    async fn pause(&self) -> Result<(), UpdateError> {
        self.trace.lock().unwrap().push("pause");
        if let Some(error) = self.pause_error {
            return Err(error);
        }
        assert!(!self.critical.swap(true, Ordering::AcqRel));
        Ok(())
    }
    async fn resume(&self) -> Result<(), UpdateError> {
        assert!(
            self.critical.load(Ordering::Acquire),
            "ordinary quit must remain blocked throughout recovery"
        );
        self.trace.lock().unwrap().push("resume");
        self.resume_error.map_or(Ok(()), Err)
    }
    fn finish(&self) {
        assert!(
            self.critical.swap(false, Ordering::AcqRel),
            "finish must run exactly once after successful pause"
        );
        self.trace.lock().unwrap().push("finish");
    }
}

#[derive(Default)]
struct MockProgress {
    phases: Mutex<Vec<UpdatePhase>>,
    bytes: Mutex<u64>,
}
impl Progress for MockProgress {
    fn phase(&self, phase: UpdatePhase) {
        self.phases.lock().unwrap().push(phase);
    }
    fn chunk(&self, length: usize, _: Option<u64>) {
        *self.bytes.lock().unwrap() += length as u64;
    }
}

fn fixture() -> (MockArtifact, MockCore, MockProgress, Trace) {
    let trace = Arc::new(Mutex::new(Vec::new()));
    let critical = Arc::new(AtomicBool::new(false));
    (
        MockArtifact {
            trace: trace.clone(),
            download_error: None,
            install_error: None,
            critical: critical.clone(),
        },
        MockCore {
            trace: trace.clone(),
            busy_calls: AtomicUsize::new(0),
            busy_at: usize::MAX,
            pause_error: None,
            resume_error: None,
            critical,
        },
        MockProgress::default(),
        trace,
    )
}

#[test]
fn demo_and_deb_are_blocked_before_network_or_installer() {
    let demo = UpdateManager::with_support("0.2.0".into(), true, true);
    assert_eq!(demo.permitted(), Err(UpdateError::Disabled));
    assert_eq!(demo.snapshot().phase, UpdatePhase::Disabled);
    let linux_deb = UpdateManager::with_support("0.2.0".into(), false, false);
    assert_eq!(linux_deb.permitted(), Err(UpdateError::ManualOnly));
    assert_eq!(linux_deb.snapshot().phase, UpdatePhase::Manual);
    assert!(linux_deb.snapshot().release.is_none());
    let native = UpdateManager::with_support("0.2.0".into(), false, true);
    assert_eq!(native.permitted(), Ok(()));
    assert_eq!(native.snapshot().phase, UpdatePhase::Idle);
    assert_eq!(native.snapshot().sequence, 0);
}

#[test]
fn only_public_github_assets_from_this_repository_are_accepted() {
    let valid = format!("{ASSET_PREFIX}v0.3.0/ysu-net-setup.exe");
    assert!(trusted_asset_url(
        &valid.parse().unwrap(),
        "fixture-signature"
    ));
    for value in [
        valid.replace("https:", "http:"),
        valid.replace("github.com/", "github.com.evil.test/"),
        valid.replace("ysu_net/", "other_repo/"),
        valid.replace("releases/download/", "releases/latest/download/"),
        format!("{valid}?token=fixture-private"),
        format!("{valid}#fixture"),
        valid.replace("https://", "https://fixture-token@"),
        format!("{ASSET_PREFIX}v0.3.0/extra/file.exe"),
    ] {
        assert!(!trusted_asset_url(
            &value.parse().unwrap(),
            "fixture-signature"
        ));
    }
    assert!(!trusted_asset_url(&valid.parse().unwrap(), " \n"));
}

#[test]
fn raw_plugin_messages_and_paths_never_enter_public_errors() {
    let secret = "https://fixture.invalid/download?token=fixture-secret";
    for stage in [
        UpdatePhase::Checking,
        UpdatePhase::Downloading,
        UpdatePhase::Installing,
    ] {
        let error = public_error(&tauri_plugin_updater::Error::Network(secret.into()), stage);
        let public = serde_json::to_string(&error).unwrap();
        assert!(!public.contains("https"));
        assert!(!public.contains("fixture-secret"));
    }
    assert_eq!(
        public_error(
            &tauri_plugin_updater::Error::ReleaseNotFound,
            UpdatePhase::Checking
        ),
        UpdateError::FeedNotReady
    );
    assert_eq!(
        public_error(
            &tauri_plugin_updater::Error::SignatureUtf8(secret.into()),
            UpdatePhase::Downloading
        ),
        UpdateError::Signature
    );
    assert_eq!(
        public_error(
            &tauri_plugin_updater::Error::SignedVersionMismatch {
                signed: secret.into(),
                announced: secret.into()
            },
            UpdatePhase::Downloading
        ),
        UpdateError::Signature
    );
    assert_eq!(
        public_error(
            &tauri_plugin_updater::Error::MissingSignedVersion,
            UpdatePhase::Downloading
        ),
        UpdateError::Signature
    );
    assert_eq!(
        public_error(
            &tauri_plugin_updater::Error::PreviousAppNotRestored(secret.into()),
            UpdatePhase::Installing
        ),
        UpdateError::ApplicationRestoreFailed
    );
}

#[tokio::test]
async fn verified_bytes_precede_core_shutdown_and_installation() {
    let (artifact, core, progress, trace) = fixture();
    apply_update(&artifact, &core, &progress).await.unwrap();
    assert_eq!(
        *trace.lock().unwrap(),
        ["download", "verify", "pause", "install", "finish"]
    );
    assert_eq!(
        *progress.phases.lock().unwrap(),
        [
            UpdatePhase::Downloading,
            UpdatePhase::Verifying,
            UpdatePhase::Quiescing,
            UpdatePhase::Installing,
            UpdatePhase::RestartRequired
        ]
    );
    assert_eq!(*progress.bytes.lock().unwrap(), FIXTURE_BYTES.len() as u64);
    // Successful installation does not restart the old core.
    assert!(!trace.lock().unwrap().contains(&"resume"));
}

#[tokio::test]
async fn initial_authentication_busy_prevents_even_download() {
    let (artifact, mut core, progress, trace) = fixture();
    core.busy_at = 0;
    let failure = apply_update(&artifact, &core, &progress).await.unwrap_err();
    assert_eq!(failure.error, UpdateError::CoreBusy);
    assert!(!failure.recovery);
    assert!(trace.lock().unwrap().is_empty());
}

#[tokio::test]
async fn authentication_started_during_download_prevents_shutdown_and_install() {
    let (artifact, mut core, progress, trace) = fixture();
    core.busy_at = 1;
    let failure = apply_update(&artifact, &core, &progress).await.unwrap_err();
    assert_eq!(failure.error, UpdateError::CoreBusy);
    assert_eq!(*trace.lock().unwrap(), ["download", "verify"]);
}

#[tokio::test]
async fn signature_or_network_failure_never_stops_the_core() {
    for error in [UpdateError::Signature, UpdateError::DownloadFailed] {
        let (mut artifact, core, progress, trace) = fixture();
        artifact.download_error = Some(error);
        let failure = apply_update(&artifact, &core, &progress).await.unwrap_err();
        assert_eq!(failure.error, error);
        assert!(!failure.recovery);
        assert_eq!(*trace.lock().unwrap(), ["download", "verify"]);
        assert!(!progress
            .phases
            .lock()
            .unwrap()
            .contains(&UpdatePhase::Installing));
    }
}

#[tokio::test]
async fn atomic_pause_admission_failure_prevents_installation() {
    let (artifact, mut core, progress, trace) = fixture();
    core.pause_error = Some(UpdateError::CoreStopFailed);
    let failure = apply_update(&artifact, &core, &progress).await.unwrap_err();
    assert_eq!(failure.error, UpdateError::CoreStopFailed);
    assert!(!failure.recovery);
    assert_eq!(*trace.lock().unwrap(), ["download", "verify", "pause"]);
}

#[tokio::test]
async fn installation_failure_resumes_core_once_without_retrying_install() {
    let (mut artifact, core, progress, trace) = fixture();
    artifact.install_error = Some(UpdateError::InstallFailed);
    let failure = apply_update(&artifact, &core, &progress).await.unwrap_err();
    assert_eq!(failure.error, UpdateError::InstallFailed);
    assert!(!failure.recovery);
    assert_eq!(
        *trace.lock().unwrap(),
        ["download", "verify", "pause", "install", "resume", "finish"]
    );
}

#[tokio::test]
async fn failed_recovery_remains_stopped_until_explicit_recovery() {
    let (mut artifact, mut core, progress, trace) = fixture();
    artifact.install_error = Some(UpdateError::InstallFailed);
    core.resume_error = Some(UpdateError::RecoveryFailed);
    let failure = apply_update(&artifact, &core, &progress).await.unwrap_err();
    assert_eq!(failure.error, UpdateError::RecoveryFailed);
    assert!(failure.recovery);
    assert_eq!(
        *trace.lock().unwrap(),
        ["download", "verify", "pause", "install", "resume", "finish"]
    );
}

#[tokio::test]
async fn failed_application_rollback_requires_manual_repair_not_core_resume() {
    let (mut artifact, core, progress, trace) = fixture();
    artifact.install_error = Some(UpdateError::ApplicationRestoreFailed);
    let failure = apply_update(&artifact, &core, &progress).await.unwrap_err();
    assert_eq!(failure.error, UpdateError::ApplicationRestoreFailed);
    assert!(failure.recovery);
    assert_eq!(
        *trace.lock().unwrap(),
        ["download", "verify", "pause", "install", "finish"]
    );
}

#[tokio::test]
async fn operation_lock_rejects_parallel_checks_and_installs_instead_of_queueing() {
    let manager = UpdateManager::with_support("0.2.0".into(), false, true);
    let first = manager.operation.try_lock().unwrap();
    assert!(manager.operation.try_lock().is_err());
    drop(first);
    assert!(manager.operation.try_lock().is_ok());
}

// Public fixtures from an independent one-use test key, not the release key.
// The private fixture key was destroyed; these bytes are text, not an installer.
const SIGNED_BYTES: &[u8] = b"offline updater artifact fixture; never executable\n";
const FIXTURE_PUBKEY: &str = "dW50cnVzdGVkIGNvbW1lbnQ6IG1pbmlzaWduIHB1YmxpYyBrZXk6IEVENDVFQzhGNkJFOTJEOUEKUldTYUxlbHJqK3hGN1lVUUFYdDlKMGdodDR0dnBFeVBPVlFEL2lTcUV5WmVhY0s3dm1Zd2dieVUK";
const FIXTURE_SIGNATURE: &str = "dW50cnVzdGVkIGNvbW1lbnQ6IHNpZ25hdHVyZSBmcm9tIHRhdXJpIHNlY3JldCBrZXkKUlVTYUxlbHJqK3hGN2FTMVowZXV3ZFFCY1dMN1JoaTZybTBhS0pwSnloSmRwQktVREZkblZhaFp2REF0cGNEMmJ4Y21sN3Q5YWI0YzJvNi9idHpoTFRSa3hxQWVZUDFoTGdZPQp0cnVzdGVkIGNvbW1lbnQ6IHRpbWVzdGFtcDoxNzkyNjY4NjQxCWZpbGU6YXJ0aWZhY3QudHh0CXZlcnNpb246OTk5LjAuMAp0WWM2ejFya0M3cENPdlR5WG1KTkFvbEZYM0N1QjJramQ0UU9VVTM2U3AvR0ZaelQzUUR3RlMxb3JTeGpEaGRIZWMyYkxNdmg4bHhMVlR5Ry9FcWFEUT09Cg==";

async fn checked_fixture(version: &str, signature: &str) -> Update {
    use tauri::test::{mock_builder, mock_context, noop_assets};
    let mut context = mock_context(noop_assets());
    context.config_mut().plugins.0.insert(
        "updater".into(),
        serde_json::json!({ "pubkey": FIXTURE_PUBKEY, "requireSignedVersion": true }),
    );
    let app = mock_builder()
        .plugin(tauri_plugin_updater::Builder::new().build())
        .build(context)
        .unwrap();
    let updater = app
        .updater_builder()
        .endpoints(vec![FEED_URL.parse().unwrap()])
        .unwrap()
        .executable_path("fixture-path/app")
        .configure_client(|_| panic!("signature fixture must not make any network request"))
        .build()
        .unwrap();
    // Official restore_update reconstructs Update from fixed metadata and forces
    // signed-version verification, without fetching even a local manifest.
    updater
        .restore_update(serde_json::json!({
            "version": version,
            "url": format!("{ASSET_PREFIX}v999.0.0/fixture.txt"),
            "signature": signature,
        }))
        .unwrap()
        .expect("fixture version must be newer than mock app")
}

struct SignedFixtureArtifact {
    update: Update,
    bytes: Vec<u8>,
    trace: Trace,
}
impl Artifact for SignedFixtureArtifact {
    async fn download(&self, progress: &impl Progress) -> Result<Vec<u8>, UpdateError> {
        self.trace.lock().unwrap().push("verify");
        progress.phase(UpdatePhase::Verifying);
        self.update
            .verify(&self.bytes)
            .map_err(|error| public_error(&error, UpdatePhase::Verifying))?;
        Ok(self.bytes.clone())
    }
    async fn install(&self, _: Vec<u8>) -> Result<(), UpdateError> {
        // This deliberately does not call Update::install or execute fixture bytes.
        self.trace.lock().unwrap().push("mock-install");
        Ok(())
    }
}

#[tokio::test]
async fn official_verifier_accepts_independent_signed_text_fixture() {
    let update = checked_fixture("999.0.0", FIXTURE_SIGNATURE).await;
    update.verify(SIGNED_BYTES).unwrap();
    let (_, core, progress, trace) = fixture();
    let artifact = SignedFixtureArtifact {
        update,
        bytes: SIGNED_BYTES.to_vec(),
        trace: trace.clone(),
    };
    apply_update(&artifact, &core, &progress).await.unwrap();
    assert_eq!(
        *trace.lock().unwrap(),
        ["verify", "pause", "mock-install", "finish"]
    );
}

#[tokio::test]
async fn official_verifier_rejects_tampered_payload_before_core_pause() {
    let update = checked_fixture("999.0.0", FIXTURE_SIGNATURE).await;
    let (_, core, progress, trace) = fixture();
    let artifact = SignedFixtureArtifact {
        update,
        bytes: b"modified artifact".to_vec(),
        trace: trace.clone(),
    };
    let failure = apply_update(&artifact, &core, &progress).await.unwrap_err();
    assert_eq!(failure.error, UpdateError::Signature);
    assert_eq!(*trace.lock().unwrap(), ["verify"]);
}

#[tokio::test]
async fn official_verifier_rejects_announced_version_mismatch_before_core_pause() {
    let update = checked_fixture("999.0.1", FIXTURE_SIGNATURE).await;
    assert!(matches!(
        update.verify(SIGNED_BYTES),
        Err(tauri_plugin_updater::Error::SignedVersionMismatch { .. })
    ));
    let (_, core, progress, trace) = fixture();
    let artifact = SignedFixtureArtifact {
        update,
        bytes: SIGNED_BYTES.to_vec(),
        trace: trace.clone(),
    };
    let failure = apply_update(&artifact, &core, &progress).await.unwrap_err();
    assert_eq!(failure.error, UpdateError::Signature);
    assert_eq!(*trace.lock().unwrap(), ["verify"]);
}

#[tokio::test]
async fn official_verifier_rejects_bad_signature_before_core_pause() {
    let update = checked_fixture("999.0.0", "fixture-broken-signature").await;
    let (_, core, progress, trace) = fixture();
    let artifact = SignedFixtureArtifact {
        update,
        bytes: SIGNED_BYTES.to_vec(),
        trace: trace.clone(),
    };
    let failure = apply_update(&artifact, &core, &progress).await.unwrap_err();
    assert_eq!(failure.error, UpdateError::Signature);
    assert_eq!(*trace.lock().unwrap(), ["verify"]);
}

#[tokio::test]
async fn every_paused_terminal_path_finishes_after_install_and_recovery_once() {
    for (install_error, resume_error) in [
        (None, None),
        (Some(UpdateError::InstallFailed), None),
        (
            Some(UpdateError::InstallFailed),
            Some(UpdateError::RecoveryFailed),
        ),
        (Some(UpdateError::ApplicationRestoreFailed), None),
    ] {
        let (mut artifact, mut core, progress, trace) = fixture();
        artifact.install_error = install_error;
        core.resume_error = resume_error;
        let _ = apply_update(&artifact, &core, &progress).await;
        // Mock install/resume assert ordinary quit is blocked while they run.
        // Only the terminal finish releases it; updating/auth admission is separate.
        assert!(!core.critical.load(Ordering::Acquire));
        let trace = trace.lock().unwrap();
        assert_eq!(trace.last(), Some(&"finish"));
        assert_eq!(trace.iter().filter(|item| **item == "finish").count(), 1);
    }
}

#[tokio::test]
async fn restart_required_is_published_only_after_ordinary_quit_is_unblocked() {
    struct RestartProgress(Arc<AtomicBool>);
    impl Progress for RestartProgress {
        fn phase(&self, phase: UpdatePhase) {
            if phase == UpdatePhase::RestartRequired {
                assert!(!self.0.load(Ordering::Acquire));
            }
        }
        fn chunk(&self, _: usize, _: Option<u64>) {}
    }
    let (artifact, core, _, _) = fixture();
    apply_update(&artifact, &core, &RestartProgress(core.critical.clone()))
        .await
        .unwrap();
}

#[test]
fn normalized_restart_without_options_keeps_only_original_executable() {
    let original = tauri::Env::default();
    let normalized = normalized_restart_env(None, false, false, false);
    assert_eq!(normalized.args_os, original.args_os[..1]);
    #[cfg(target_os = "linux")]
    {
        assert_eq!(normalized.appimage, original.appimage);
        assert_eq!(normalized.appdir, original.appdir);
    }
}

#[test]
fn resolved_relative_and_environment_config_options_keep_absolute_path_and_flags() {
    use std::ffi::OsString;
    // Startup Options resolves both --config relative paths and the environment
    // fallback before calling this helper. No process-global env/cwd is mutated.
    for name in [
        "relative option/config with spaces.toml",
        "environment option/配置.toml",
    ] {
        let resolved = std::env::current_dir().unwrap().join(name);
        assert!(resolved.is_absolute());
        let normalized = normalized_restart_env(resolved.to_str(), true, true, true);
        assert_eq!(
            normalized.args_os[1..],
            [
                OsString::from("--config"),
                resolved.into_os_string(),
                OsString::from("--minimized"),
                OsString::from("--demo"),
                OsString::from("--smoke"),
            ]
        );
        assert_eq!(normalized.args_os.len(), 6);
    }
}

#[test]
fn premanaged_normalized_environment_survives_tauri_default_environment_setup() {
    use tauri::{
        test::{mock_builder, mock_context, noop_assets},
        Manager,
    };
    let path = std::env::current_dir()
        .unwrap()
        .join("restart fixture/config.toml");
    let environment = normalized_restart_env(path.to_str(), true, false, false);
    let expected = environment.args_os.clone();
    let app = mock_builder()
        .manage(environment)
        .build(mock_context(noop_assets()))
        .unwrap();
    assert_eq!(app.env().args_os, expected);
}

// Exercise the actual argument-free Tauri handler; only the OS boundary is replaced.
fn release_page_ipc(
    manager: UpdateManager,
    payload: serde_json::Value,
) -> Result<(), serde_json::Value> {
    use tauri::test::{get_ipc_response, mock_builder, mock_context, noop_assets, INVOKE_KEY};
    use tauri::Manager;

    let before = serde_json::to_value(manager.snapshot()).unwrap();
    let app = mock_builder()
        .manage(manager)
        .invoke_handler(tauri::generate_handler![
            crate::updater::updater_open_releases
        ])
        .build(mock_context(noop_assets()))
        .unwrap();
    let webview = tauri::WebviewWindowBuilder::new(&app, "main", Default::default())
        .build()
        .unwrap();
    let response = get_ipc_response(
        &webview,
        tauri::webview::InvokeRequest {
            cmd: "updater_open_releases".into(),
            callback: tauri::ipc::CallbackFn(0),
            error: tauri::ipc::CallbackFn(1),
            url: if cfg!(windows) {
                "http://tauri.localhost"
            } else {
                "tauri://localhost"
            }
            .parse()
            .unwrap(),
            body: tauri::ipc::InvokeBody::Json(payload),
            headers: Default::default(),
            invoke_key: INVOKE_KEY.into(),
        },
    )
    .map(|body| body.deserialize::<()>().unwrap());
    assert_eq!(
        serde_json::to_value(app.state::<UpdateManager>().snapshot()).unwrap(),
        before,
        "opening the release page must not check, download, or mutate updater state"
    );
    response
}

#[test]
fn native_releases_ipc_opens_only_fixed_url_including_manual_deb_mode() {
    for automatic in [false, true] {
        let calls = Arc::new(Mutex::new(Vec::new()));
        let captured = calls.clone();
        let mut manager = UpdateManager::with_support("0.2.1".into(), false, automatic);
        manager.release_opener = Box::new(move |url| {
            captured.lock().unwrap().push(url);
            Ok(())
        });
        // Extra JSON fields must never become an OS URL or an application override.
        release_page_ipc(
            manager,
            serde_json::json!({"url":"https://outside.invalid/", "with":"fixture-command"}),
        )
        .unwrap();
        assert_eq!(*calls.lock().unwrap(), [RELEASES_URL]);
    }
}

#[test]
fn demo_releases_ipc_never_reaches_the_system_opener() {
    for automatic in [false, true] {
        let mut manager = UpdateManager::with_support("0.2.1".into(), true, automatic);
        manager.release_opener = Box::new(|_| panic!("demo must not launch a browser"));
        assert_eq!(
            release_page_ipc(manager, serde_json::json!({})),
            Err(serde_json::json!("disabled"))
        );
    }
}

#[test]
fn native_releases_ipc_returns_only_a_fixed_public_open_error() {
    let mut manager = UpdateManager::with_support("0.2.1".into(), false, false);
    manager.release_opener = Box::new(|_| Err(()));
    assert_eq!(
        release_page_ipc(manager, serde_json::json!({})),
        Err(serde_json::json!("open_failed"))
    );
}

#[cfg(target_os = "linux")]
#[test]
fn official_release_opener_dispatches_to_isolated_linux_handler_without_network() {
    use std::os::unix::fs::PermissionsExt;
    const CAPTURE: &str = "YSU_TEST_RELEASE_OPENER_CAPTURE";
    // Only the isolated child reaches the real official opener. Its PATH contains
    // one recording script, not a browser; its environment has no user credentials.
    if std::env::var_os(CAPTURE).is_some() {
        release_page_ipc(
            UpdateManager::with_support("0.2.1".into(), false, false),
            serde_json::json!({}),
        )
        .unwrap();
        return;
    }
    let directory = tempfile::tempdir().unwrap();
    let capture = directory.path().join("arguments.txt");
    let handler = directory.path().join("xdg-open");
    std::fs::write(
        &handler,
        "#!/bin/sh\nprintf '%s\\n' \"$#\" \"$1\" > \"$YSU_TEST_RELEASE_OPENER_CAPTURE\"\n",
    )
    .unwrap();
    std::fs::set_permissions(&handler, std::fs::Permissions::from_mode(0o700)).unwrap();
    let result = std::process::Command::new(std::env::current_exe().unwrap())
        .args([
            "--exact",
            "updater::tests::official_release_opener_dispatches_to_isolated_linux_handler_without_network",
            "--nocapture",
        ])
        .env_clear()
        .env("PATH", directory.path())
        .env("HOME", directory.path())
        .env(CAPTURE, &capture)
        .output()
        .unwrap();
    assert!(
        result.status.success(),
        "isolated native opener probe failed: {}",
        String::from_utf8_lossy(&result.stderr)
    );
    let expected = format!("1\n{RELEASES_URL}\n");
    // The maintained OS launcher is detached; await only this recording fixture.
    let deadline = std::time::Instant::now() + Duration::from_secs(2);
    while std::fs::read_to_string(&capture).ok().as_deref() != Some(&expected)
        && std::time::Instant::now() < deadline
    {
        std::thread::sleep(Duration::from_millis(10));
    }
    assert_eq!(std::fs::read_to_string(&capture).unwrap(), expected);
}
