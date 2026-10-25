//! Offline policy/cache/malicious-input tests. These are authored for cloud CI;
//! no local execution or product/installer testing is implied by their presence.
//! Mock signatures below test ordering only, NOT SDK cryptography. The public
//! reconstruct_sdk_fixture seam awaits the Lead's real double-signed fixture.
use super::*;
use serde_json::json;
use std::{
    collections::VecDeque,
    sync::{Arc, Mutex},
};

type Trace = Arc<Mutex<Vec<&'static str>>>;

fn integer(value: i64) -> [u8; 8] {
    let raw = if value < 0 {
        value.unsigned_abs() | (1u64 << 63)
    } else {
        value as u64
    };
    raw.to_le_bytes()
}
fn bz(bytes: &[u8]) -> Vec<u8> {
    let mut encoder = bzip2::read::BzEncoder::new(bytes, bzip2::Compression::default());
    let mut result = Vec::new();
    encoder.read_to_end(&mut result).unwrap();
    result
}
fn patch_raw(controls: &[u8], delta: &[u8], extra: &[u8], target: u64) -> Vec<u8> {
    let control = bz(controls);
    let delta = bz(delta);
    let extra = bz(extra);
    let mut result = b"BSDIFF40".to_vec();
    result.extend(integer(control.len() as i64));
    result.extend(integer(delta.len() as i64));
    result.extend(integer(target as i64));
    result.extend(control);
    result.extend(delta);
    result.extend(extra);
    result
}
fn patch(tuples: &[[i64; 3]], delta: &[u8], extra: &[u8], target: u64) -> Vec<u8> {
    let controls: Vec<u8> = tuples
        .iter()
        .flat_map(|t| t.iter().flat_map(|v| integer(*v)))
        .collect();
    patch_raw(&controls, delta, extra, target)
}
fn fixture() -> (Release, Descriptor, Vec<u8>, Vec<u8>, Vec<u8>) {
    let base = vec![b'A'; 8192];
    let mut target = base.clone();
    target[234] = b'B';
    target[8123] = b'C';
    let delta: Vec<u8> = target
        .iter()
        .zip(&base)
        .map(|(new, old)| new.wrapping_sub(*old))
        .collect();
    let patch = patch(&[[8192, 0, 0]], &delta, &[], target.len() as u64);
    let full_url = format!("{ASSET_PREFIX}v0.3.0/setup.exe");
    let d = Descriptor {
        format: "bsdiff40".into(),
        base_version: "0.2.1".into(),
        base_sha256: digest(&base),
        base_size: base.len() as u64,
        target_version: "0.3.0".into(),
        target_sha256: digest(&target),
        target_size: target.len() as u64,
        full_url: full_url.clone(),
        full_signature: "mock-full-signature".into(),
        url: format!("{ASSET_PREFIX}v0.3.0/setup.patch"),
        signature: "mock-patch-signature".into(),
        sha256: digest(&patch),
        size: patch.len() as u64,
    };
    let raw_d = descriptor_json(&d);
    let release = Release {
        current: "0.2.1".into(),
        version: "0.3.0".into(),
        target: "windows".into(),
        url: full_url.parse().unwrap(),
        signature: d.full_signature.clone(),
        raw: json!({"version":"0.3.0", "platforms": {
            (WINDOWS.key): {"url":full_url, "signature":d.full_signature}
        }, "deltas": {(WINDOWS.key): [raw_d]}}),
    };
    (release, d, base, target, patch)
}
fn descriptor_json(d: &Descriptor) -> Value {
    json!({
        "format":d.format, "base_version":d.base_version, "base_sha256":d.base_sha256,
        "base_size":d.base_size, "target_version":d.target_version,
        "target_sha256":d.target_sha256, "target_size":d.target_size,
        "full_url":d.full_url, "full_signature":d.full_signature,
        "url":d.url, "signature":d.signature, "sha256":d.sha256, "size":d.size,
    })
}
fn root() -> (tempfile::TempDir, PathBuf) {
    let directory = tempfile::tempdir().unwrap();
    // macOS temp paths can themselves use /var -> /private/var. Production rejects
    // symlink parents; normalize this trusted, newly created fixture root first.
    let path = directory
        .path()
        .canonicalize()
        .unwrap()
        .join("update-packages-v1");
    (directory, path)
}

#[derive(Default)]
struct RecordedProgress {
    transfers: Mutex<Vec<(&'static str, bool)>>,
    bytes: Mutex<u64>,
    phases: Mutex<Vec<UpdatePhase>>,
}
impl Progress for RecordedProgress {
    fn phase(&self, phase: UpdatePhase) {
        self.phases.lock().unwrap().push(phase);
    }
    fn chunk(&self, length: usize, _: Option<u64>) {
        *self.bytes.lock().unwrap() += length as u64;
    }
    fn transfer(&self, mode: DownloadMode, fallback: bool) {
        let mode = match mode {
            DownloadMode::Full => "full",
            DownloadMode::Delta => "delta",
            DownloadMode::Cached => "cached",
        };
        *self.bytes.lock().unwrap() = 0;
        self.transfers.lock().unwrap().push((mode, fallback));
    }
}
struct FakeNetwork {
    replies: Mutex<VecDeque<Result<Vec<u8>, UpdateError>>>,
    calls: Mutex<Vec<(String, u64)>>,
}
impl FakeNetwork {
    fn new(replies: Vec<Result<Vec<u8>, UpdateError>>) -> Self {
        Self {
            replies: Mutex::new(replies.into()),
            calls: Mutex::new(vec![]),
        }
    }
}
impl Network for FakeNetwork {
    async fn fetch(
        &self,
        url: &reqwest::Url,
        limit: u64,
        progress: &impl Progress,
    ) -> Result<Vec<u8>, UpdateError> {
        self.calls
            .lock()
            .unwrap()
            .push((url.path().to_owned(), limit));
        let reply = self
            .replies
            .lock()
            .unwrap()
            .pop_front()
            .expect("unexpected extra network attempt")?;
        let mut bytes = Vec::new();
        for chunk in reply.chunks(4096) {
            append_bounded(&mut bytes, chunk, limit as usize)
                .map_err(|_| UpdateError::DownloadFailed)?;
            progress.chunk(chunk.len(), None);
        }
        Ok(bytes)
    }
}
#[derive(Clone)]
struct FakeVerifier {
    target: Vec<u8>,
    patch: Vec<u8>,
    reject_patch: bool,
    reject_full: bool,
    trace: Trace,
}
impl FakeVerifier {
    fn new(target: &[u8], patch: &[u8]) -> Self {
        Self {
            target: target.into(),
            patch: patch.into(),
            reject_patch: false,
            reject_full: false,
            trace: Arc::new(Mutex::new(vec![])),
        }
    }
}
impl Verifier for FakeVerifier {
    fn full(&self, bytes: &[u8]) -> Result<(), UpdateError> {
        self.trace.lock().unwrap().push("verify-full");
        if self.reject_full || bytes != self.target {
            Err(UpdateError::Signature)
        } else {
            Ok(())
        }
    }
    fn patch(&self, bytes: &[u8], signature: &str) -> Result<(), UpdateError> {
        self.trace.lock().unwrap().push("verify-patch");
        if self.reject_patch || bytes != self.patch || signature != "mock-patch-signature" {
            Err(UpdateError::Signature)
        } else {
            Ok(())
        }
    }
}

#[test]
fn feed_status_mapping_and_actual_byte_limits_are_fixed() {
    assert_eq!(feed_status(200), Ok(true));
    assert_eq!(feed_status(204), Ok(false));
    assert_eq!(feed_status(404), Err(UpdateError::FeedNotReady));
    for status in [201, 206, 301, 401, 403, 429, 500] {
        assert_eq!(feed_status(status), Err(UpdateError::CheckFailed));
    }
    let mut bytes = vec![];
    append_bounded(&mut bytes, &[0; 8], 8).unwrap();
    assert!(append_bounded(&mut bytes, &[1], 8).is_err());
    assert_eq!(bytes.len(), 8); // Last chunk is not appended past the cap.
    assert!(append_bounded(&mut bytes, &[1], usize::MAX).is_ok());
}

#[test]
fn initial_and_redirect_url_policies_do_not_accept_credentials_or_other_hosts() {
    let good = format!("{ASSET_PREFIX}v0.3.0/setup.exe");
    assert!(asset_url(&good).is_some());
    for bad in [
        good.replace("https:", "http:"),
        good.replace("github.com/", "github.com.evil/"),
        good.replace("ysu_net/", "elsewhere/"),
        format!("{good}?token=redacted"),
        format!("{good}#fragment"),
        good.replace("https://", "https://user:password@"),
        good.replace("setup.exe", "nested/file.exe"),
        good.replace("setup.exe", "%2fsetup.exe"),
        good.replace("github.com/", "github.com:8443/"),
    ] {
        assert!(
            asset_url(&bad).is_none(),
            "must reject non-canonical release asset"
        );
    }
    for host in [
        "github.com",
        "release-assets.githubusercontent.com",
        "objects.githubusercontent.com",
        "github-releases.githubusercontent.com",
    ] {
        assert!(transport_url(
            &format!("https://{host}/asset?cdn-token=opaque")
                .parse()
                .unwrap()
        ));
        assert!(!transport_url(
            &format!("http://{host}/asset").parse().unwrap()
        ));
    }
    assert!(!transport_url(
        &"https://example.org/asset".parse().unwrap()
    ));
    assert!(!transport_url(
        &"https://user@github.com/asset".parse().unwrap()
    ));
}

#[test]
fn sdk_target_precedence_and_architecture_are_reproduced_not_guessed_from_os() {
    let (mut release, d, _, _, _) = fixture();
    assert_eq!(descriptors(&release, WINDOWS).len(), 1);
    assert!(descriptors(&release, MAC_X64).is_empty());
    assert!(descriptors(&release, MAC_ARM64).is_empty());
    release.raw["platforms"][WINDOWS.bare] = json!({"url":release.url, "signature":"other"});
    release.raw["deltas"][WINDOWS.bare] = json!([descriptor_json(&d)]);
    assert_eq!(descriptors(&release, WINDOWS).len(), 1); // Installer key wins.
    release.raw["platforms"][WINDOWS.key]["signature"] = json!("mismatch");
    assert!(descriptors(&release, WINDOWS).is_empty()); // Do not bypass it via bare key.
    release.raw["platforms"]
        .as_object_mut()
        .unwrap()
        .remove(WINDOWS.key);
    release.raw["platforms"][WINDOWS.bare]["signature"] = json!(release.signature);
    assert_eq!(descriptors(&release, WINDOWS).len(), 1);
    release.target = WINDOWS.key.into(); // A custom SDK target is not the runtime OS.
    assert!(descriptors(&release, WINDOWS).is_empty());
}

#[test]
fn descriptor_malformed_unknown_oversize_and_non_newer_metadata_are_ignored() {
    let (release, d, _, _, _) = fixture();
    for (field, value) in [
        ("format", json!("unknown")),
        ("base_version", json!("0.1.0")),
        ("target_version", json!("0.4.0")),
        ("base_sha256", json!("A".repeat(64))),
        ("target_sha256", json!("a".repeat(63))),
        ("sha256", json!("g".repeat(64))),
        ("size", json!(PATCH_LIMIT + 1)),
        ("target_size", json!(FULL_LIMIT + 1)),
        ("base_size", json!(-1)),
        ("target_size", json!(0)),
        ("full_signature", json!("not-selected")),
        ("signature", json!("x".repeat(SIGNATURE_LIMIT + 1))),
        ("full_url", json!(format!("{ASSET_PREFIX}v0.3.0/other.exe"))),
        ("url", json!("https://example.org/p.patch")),
        ("unknown", json!(true)),
    ] {
        let mut changed = release.clone();
        changed.raw["deltas"][WINDOWS.key][0][field] = value;
        assert!(
            descriptors(&changed, WINDOWS).is_empty(),
            "accepted invalid {field}"
        );
    }
    let mut changed = release.clone();
    changed.raw["deltas"][WINDOWS.key] = json!([
        descriptor_json(&d),
        descriptor_json(&d),
        descriptor_json(&d),
        descriptor_json(&d)
    ]);
    assert!(descriptors(&changed, WINDOWS).is_empty());
    changed = release.clone();
    changed.raw["deltas"][WINDOWS.key][0]["target_size"] = json!(100);
    changed.raw["deltas"][WINDOWS.key][0]["size"] = json!(80);
    assert!(descriptors(&changed, WINDOWS).is_empty()); // Strictly less than 80%.
    changed.raw["deltas"][WINDOWS.key][0]["size"] = json!(79);
    assert_eq!(descriptors(&changed, WINDOWS).len(), 1);
    changed.current = changed.version.clone();
    assert!(descriptors(&changed, WINDOWS).is_empty());
}

#[test]
fn qbsdiff_really_reconstructs_a_bsdiff40_fixture_after_bounded_preflight() {
    let (_, _, base, target, patch) = fixture();
    assert_eq!(
        checked_apply(&base, &patch, target.len() as u64).unwrap(),
        target
    );
    let copy = self::patch(&[[0, 3, 0]], &[], b"abc", 3);
    assert_eq!(checked_apply(&[], &copy, 3).unwrap(), b"abc");
}

#[test]
fn headers_reject_magic_negative_zero_negative_lengths_overflow_and_truncation() {
    let (_, _, base, _, valid) = fixture();
    for index in [8usize, 16, 24] {
        for raw in [
            integer(-1),
            (1u64 << 63).to_le_bytes(),
            i64::MAX.to_le_bytes(),
        ] {
            let mut bad = valid.clone();
            bad[index..index + 8].copy_from_slice(&raw);
            assert!(checked_apply(&base, &bad, 8192).is_err());
        }
    }
    let mut bad = valid.clone();
    bad[8..16].copy_from_slice(&i64::MAX.to_le_bytes());
    bad[16..24].copy_from_slice(&i64::MAX.to_le_bytes());
    assert!(sections(&bad, 8192).is_err()); // 32 + MAX + MAX would overflow u64.
    bad = valid.clone();
    bad[0] = b'x';
    assert!(checked_apply(&base, &bad, 8192).is_err());
    for length in [0usize, 7, 31, valid.len() - 1] {
        assert!(checked_apply(&base, &valid[..length], 8192).is_err());
    }
    assert!(checked_apply(&base, &valid, 8191).is_err());
    assert!(checked_apply(&base, &valid, FULL_LIMIT + 1).is_err());
}

#[test]
fn malicious_control_counts_zero_progress_source_reads_and_seeks_are_bounded() {
    let mut zeros = vec![[0, 0, 0]; ZERO_PROGRESS_LIMIT + 1];
    zeros.push([0, 1, 0]);
    assert!(checked_apply(&[], &patch(&zeros, &[], b"x", 1), 1).is_err());
    let many: Vec<_> = (0..=CONTROL_LIMIT).map(|_| [0, 1, 0]).collect();
    assert!(checked_apply(
        &[],
        &patch(&many, &[], &vec![0; many.len()], many.len() as u64),
        many.len() as u64
    )
    .is_err());
    for tuples in [
        vec![[-1, 1, 0]],
        vec![[0, -1, 0]],
        vec![[2, 0, 0]],
        vec![[0, 1, -1]],
        vec![[0, 1, i64::MAX]],
        vec![[1, 0, 1], [1, 0, 0]],
    ] {
        assert!(checked_apply(b"x", &patch(&tuples, b"xx", b"x", 1), 1).is_err());
    }
    assert!(checked_apply(b"x", &patch_raw(&[0; 23], &[], b"x", 1), 1).is_err());
}

#[test]
fn short_extra_or_delta_output_and_unused_or_concatenated_bytes_are_rejected() {
    for (tuples, delta, extra) in [
        (vec![[0, 2, 0]], vec![], b"x".to_vec()),
        (vec![[0, 1, 0]], vec![], b"xx".to_vec()),
        (vec![[1, 0, 0]], vec![], vec![]),
        (vec![[1, 0, 0]], vec![0, 0], vec![]),
        (vec![[0, 0, 0]], vec![], vec![]),
        (vec![[0, 2, 0]], vec![], b"xx".to_vec()),
    ] {
        assert!(checked_apply(b"x", &patch(&tuples, &delta, &extra, 1), 1).is_err());
    }
    let mut trailing = patch(&[[0, 1, 0]], &[], b"x", 1);
    trailing.extend(bz(b"ignored second member"));
    assert!(checked_apply(&[], &trailing, 1).is_err());
    let mut writer = BudgetWriter {
        bytes: vec![],
        limit: 1,
        deadline: Instant::now() + Duration::from_secs(1),
    };
    assert!(writer.write_all(b"xx").is_err());
    assert!(writer.bytes.is_empty());
    assert!(preflight(
        0,
        &patch(&[[0, 1, 0]], &[], b"x", 1),
        1,
        Instant::now() - Duration::from_secs(1)
    )
    .is_err());
}

#[test]
fn patch_signature_precedes_any_decoder_and_final_signature_is_still_required() {
    let (_, d, base, target, patch) = fixture();
    let mut verifier = FakeVerifier::new(&target, &patch);
    verifier.reject_patch = true;
    let result = reconstruct_with(&base, &patch, &d, &verifier, |_, _, _| {
        panic!("unverified patch must never reach a decoder")
    });
    assert_eq!(result, Err(UpdateError::Signature));
    assert_eq!(*verifier.trace.lock().unwrap(), ["verify-patch"]);
    verifier.reject_patch = false;
    verifier.reject_full = true;
    assert_eq!(
        reconstruct_with(&base, &patch, &d, &verifier, checked_apply),
        Err(UpdateError::Signature)
    );
    let mut wrong = d.clone();
    wrong.target_sha256 = "0".repeat(64);
    assert_eq!(
        reconstruct_with(&base, &patch, &wrong, &verifier, checked_apply),
        Err(UpdateError::DownloadFailed)
    );
    assert!(
        reconstruct_with(b"wrong base", &patch, &d, &verifier, |_, _, _| panic!(
            "wrong base must not decode"
        ))
        .is_err()
    );
}

#[tokio::test]
async fn first_launch_fetches_only_the_full_target_and_caches_after_verification() {
    let (release, _, _, target, patch) = fixture();
    let (_directory, root) = root();
    let network = FakeNetwork::new(vec![Ok(target.clone())]);
    let verifier = FakeVerifier::new(&target, &patch);
    let progress = RecordedProgress::default();
    let result = download_inner(
        release,
        Some(WINDOWS),
        Some(root.clone()),
        &progress,
        &network,
        verifier,
    )
    .await
    .unwrap();
    assert_eq!(result, target);
    assert_eq!(network.calls.lock().unwrap().len(), 1);
    assert_eq!(network.calls.lock().unwrap()[0].1, FULL_LIMIT);
    assert_eq!(*progress.transfers.lock().unwrap(), [("full", false)]);
    let cache = Cache::open(root).unwrap();
    assert_eq!(
        cache
            .entries()
            .unwrap()
            .iter()
            .filter(|e| own_package(&e.name))
            .count(),
        1
    );
}

#[tokio::test]
async fn precise_cached_base_enables_a_real_delta_without_any_full_fetch() {
    let (release, _, base, target, patch) = fixture();
    let (_directory, root) = root();
    Cache::open(root.clone())
        .unwrap()
        .store(WINDOWS, "0.2.1", &base)
        .unwrap();
    let network = FakeNetwork::new(vec![Ok(patch.clone())]);
    let progress = RecordedProgress::default();
    let verifier = FakeVerifier::new(&target, &patch);
    let trace = verifier.trace.clone();
    assert_eq!(
        download_inner(
            release,
            Some(WINDOWS),
            Some(root.clone()),
            &progress,
            &network,
            verifier
        )
        .await
        .unwrap(),
        target
    );
    assert_eq!(*trace.lock().unwrap(), ["verify-patch", "verify-full"]);
    assert_eq!(network.calls.lock().unwrap().len(), 1);
    assert_eq!(network.calls.lock().unwrap()[0].1, PATCH_LIMIT);
    assert_eq!(*progress.transfers.lock().unwrap(), [("delta", false)]);
    assert!(progress
        .phases
        .lock()
        .unwrap()
        .contains(&UpdatePhase::Reconstructing));
    assert_eq!(Cache::open(root).unwrap().entries().unwrap().len(), 2);
}

#[tokio::test]
async fn patch_failure_falls_back_once_resets_progress_and_ignores_delta_target_hash() {
    let (mut release, _, base, target, patch) = fixture();
    release.raw["deltas"][WINDOWS.key][0]["target_sha256"] = json!("0".repeat(64));
    for full in [Ok(target.clone()), Err(UpdateError::DownloadFailed)] {
        let (_directory, root) = root();
        Cache::open(root.clone())
            .unwrap()
            .store(WINDOWS, "0.2.1", &base)
            .unwrap();
        let success = full.is_ok();
        let network = FakeNetwork::new(vec![Ok(patch.clone()), full]);
        let progress = RecordedProgress::default();
        let result = download_inner(
            release.clone(),
            Some(WINDOWS),
            Some(root),
            &progress,
            &network,
            FakeVerifier::new(&target, &patch),
        )
        .await;
        assert_eq!(result.is_ok(), success);
        assert_eq!(network.calls.lock().unwrap().len(), 2);
        assert_eq!(
            *progress.transfers.lock().unwrap(),
            [("delta", false), ("full", true)]
        );
        assert_eq!(
            *progress.bytes.lock().unwrap(),
            if success { target.len() as u64 } else { 0 }
        );
    }
}

#[tokio::test]
async fn cache_failures_and_malformed_descriptors_cannot_block_signed_full_downloads() {
    let (mut release, _, _, target, patch) = fixture();
    release.raw["deltas"] = json!({"unknown": "invalid"});
    let (_directory, root) = root();
    fs::create_dir(&root).unwrap();
    fs::write(root.join("not-ours.txt"), b"preserve unknown file").unwrap();
    let network = FakeNetwork::new(vec![Ok(target.clone())]);
    assert_eq!(
        download_inner(
            release,
            Some(WINDOWS),
            Some(root.clone()),
            &RecordedProgress::default(),
            &network,
            FakeVerifier::new(&target, &patch)
        )
        .await
        .unwrap(),
        target
    );
    assert_eq!(
        fs::read(root.join("not-ours.txt")).unwrap(),
        b"preserve unknown file"
    );
}

#[tokio::test]
async fn unverified_full_bytes_never_enter_the_cache() {
    let (release, _, _, target, patch) = fixture();
    let (_directory, root) = root();
    let mut verifier = FakeVerifier::new(&target, &patch);
    verifier.reject_full = true;
    assert_eq!(
        download_inner(
            release,
            Some(WINDOWS),
            Some(root.clone()),
            &RecordedProgress::default(),
            &FakeNetwork::new(vec![Ok(target)]),
            verifier
        )
        .await,
        Err(UpdateError::Signature)
    );
    assert!(Cache::open(root).unwrap().entries().unwrap().is_empty());
}

#[test]
fn cache_lock_exact_base_architecture_and_same_opened_object_are_required() {
    let (_, d, base, _, _) = fixture();
    let (_directory, root) = root();
    let mut cache = Cache::open(root.clone()).unwrap();
    assert!(Cache::open(root.clone()).is_err());
    cache.store(WINDOWS, "0.2.1", &base).unwrap();
    assert_eq!(cache.base(WINDOWS, &d).unwrap(), base);
    assert!(cache.base(MAC_ARM64, &d).is_err());
    assert!(cache.base(MAC_X64, &d).is_err());
    let name = cache_name(WINDOWS, "0.2.1", &d.base_sha256).unwrap();
    fs::write(root.join(name), b"corrupt cache").unwrap();
    assert!(cache.base(WINDOWS, &d).is_err());
}

#[test]
fn atomic_write_failure_keeps_the_existing_base_and_never_publishes_target() {
    let (_, d, base, target, _) = fixture();
    let (_directory, root) = root();
    let mut cache = Cache::open(root.clone()).unwrap();
    cache.store(WINDOWS, "0.2.1", &base).unwrap();
    cache
        .store(WINDOWS, "0.2.2", b"newer but unused package")
        .unwrap();
    assert_eq!(cache.entries().unwrap().len(), 2);
    assert_eq!(cache.base(WINDOWS, &d).unwrap(), base); // Pin the precise base before pruning.
    let target_name = cache_name(WINDOWS, "0.3.0", &digest(&target)).unwrap();
    assert!(cache
        .store_with(WINDOWS, "0.3.0", &target, |file, bytes| {
            file.write_all(&bytes[..13])?;
            Err(io::Error::other("injected atomic write failure"))
        })
        .is_err());
    assert_eq!(cache.base(WINDOWS, &d).unwrap(), base);
    assert!(!root.join(target_name).exists());
    assert!(!cache.entries().unwrap().iter().any(|e| own_temp(&e.name)));
}

#[test]
fn cache_maintenance_keeps_two_packages_cleans_only_owned_fragments_and_never_clobbers() {
    let (_directory, root) = root();
    let mut cache = Cache::open(root.clone()).unwrap();
    for version in ["0.1.0", "0.2.0", "0.3.0"] {
        cache.store(WINDOWS, version, version.as_bytes()).unwrap();
    }
    let entries = cache.entries().unwrap();
    assert!(entries.len() <= 2);
    assert!(entries.iter().all(|e| e.size <= FULL_LIMIT));
    assert!(entries.iter().map(|e| e.size).sum::<u64>() <= FULL_LIMIT * 2);
    let own = format!("{TEMP_PREFIX}{}", "a".repeat(32));
    fs::write(root.join(&own), b"crash fragment").unwrap();
    cache.maintain(2).unwrap();
    assert!(!root.join(&own).exists());
    let directory_name = cache_name(WINDOWS, "0.4.0", &digest(b"x")).unwrap();
    fs::create_dir(root.join(&directory_name)).unwrap();
    assert!(cache.maintain(2).is_err());
    assert!(root.join(&directory_name).is_dir());
}

#[cfg(unix)]
#[test]
fn cache_rejects_symlink_roots_parents_packages_and_locks_without_following_them() {
    use std::os::unix::fs::symlink;
    let (directory, root) = root();
    let outside = directory.path().canonicalize().unwrap().join("outside");
    fs::create_dir(&outside).unwrap();
    symlink(&outside, &root).unwrap();
    assert!(Cache::open(root.clone()).is_err());
    // Use distinct fixture roots; no cleanup outside tempfile's own lifetime.
    let (_other, other_root) = self::root();
    fs::create_dir(&other_root).unwrap();
    let secret = outside.join("not-a-real-secret.txt");
    fs::write(&secret, b"fixture-only").unwrap();
    let name = cache_name(WINDOWS, "0.2.1", &digest(b"fixture-only")).unwrap();
    symlink(&secret, other_root.join(name)).unwrap();
    assert!(Cache::open(other_root).is_err());
    assert_eq!(fs::read(secret).unwrap(), b"fixture-only");
    let (_third, third_root) = self::root();
    fs::create_dir(&third_root).unwrap();
    symlink(&outside, third_root.join(CACHE_LOCK)).unwrap();
    assert!(Cache::open(third_root).is_err());
    let (_fourth, fourth_root) = self::root();
    let link_parent = fourth_root.parent().unwrap().join("linked-parent");
    symlink(&outside, &link_parent).unwrap();
    assert!(Cache::open(link_parent.join("update-packages-v1")).is_err());
}

#[cfg(unix)]
#[test]
fn commit_rejects_a_temp_name_replaced_after_the_verified_handle_was_opened() {
    let (_directory, root) = root();
    let cache = Cache::open(root.clone()).unwrap();
    let temp = format!("{TEMP_PREFIX}{}", "b".repeat(32));
    let mut verified = cache.dir.file(&temp, FileMode::New).unwrap();
    verified.write_all(b"verified fixture bytes").unwrap();
    verified.sync_all().unwrap();
    let parked = root.join("parked-public-fixture");
    fs::rename(root.join(&temp), &parked).unwrap();
    fs::write(root.join(&temp), b"replaced fixture bytes").unwrap();
    let target = cache_name(WINDOWS, "0.3.0", &digest(b"verified fixture bytes")).unwrap();
    assert!(cache.dir.commit(&temp, &target, &verified).is_err());
    assert!(!root.join(target).exists());
    assert_eq!(fs::read(parked).unwrap(), b"verified fixture bytes");
}

#[cfg(unix)]
#[test]
fn commit_rejects_a_temp_name_replaced_with_a_symlink() {
    use std::os::unix::fs::symlink;
    let (_directory, root) = root();
    let cache = Cache::open(root.clone()).unwrap();
    let temp = format!("{TEMP_PREFIX}{}", "c".repeat(32));
    let mut verified = cache.dir.file(&temp, FileMode::New).unwrap();
    verified.write_all(b"verified fixture bytes").unwrap();
    verified.sync_all().unwrap();
    let parked = root.join("parked-verified-fixture");
    fs::rename(root.join(&temp), &parked).unwrap();
    let outside = root.parent().unwrap().join("outside-public-fixture");
    fs::write(&outside, b"unrelated fixture bytes").unwrap();
    symlink(&outside, root.join(&temp)).unwrap();
    let target = cache_name(WINDOWS, "0.3.0", &digest(b"verified fixture bytes")).unwrap();
    assert!(cache.dir.commit(&temp, &target, &verified).is_err());
    assert!(fs::symlink_metadata(root.join(target)).is_err());
    assert_eq!(fs::read(parked).unwrap(), b"verified fixture bytes");
    assert_eq!(fs::read(outside).unwrap(), b"unrelated fixture bytes");
}

#[test]
fn commit_never_clobbers_an_existing_target_on_any_supported_platform() {
    let (_directory, root) = root();
    let cache = Cache::open(root.clone()).unwrap();
    let temp = format!("{TEMP_PREFIX}{}", "d".repeat(32));
    let bytes = b"verified new public fixture";
    let mut verified = cache.dir.file(&temp, FileMode::New).unwrap();
    verified.write_all(bytes).unwrap();
    verified.sync_all().unwrap();
    let target = cache_name(WINDOWS, "0.3.0", &digest(bytes)).unwrap();
    fs::write(root.join(&target), b"existing public fixture").unwrap();
    assert!(cache.dir.commit(&temp, &target, &verified).is_err());
    assert_eq!(
        fs::read(root.join(target)).unwrap(),
        b"existing public fixture"
    );
    assert_eq!(fs::read(root.join(temp)).unwrap(), bytes);
}

#[cfg(unix)]
#[test]
fn cache_operations_stay_anchored_when_parent_path_is_replaced() {
    let (_, d, base, _, _) = fixture();
    let (_directory, root) = root();
    let mut cache = Cache::open(root.clone()).unwrap();
    cache.store(WINDOWS, "0.2.1", &base).unwrap();
    let moved = root.with_file_name("renamed-cache");
    fs::rename(&root, &moved).unwrap();
    fs::create_dir(&root).unwrap();
    fs::write(root.join("unknown.txt"), b"must not touch replacement").unwrap();
    assert_eq!(cache.base(WINDOWS, &d).unwrap(), base);
    cache.maintain(1).unwrap();
    assert_eq!(
        fs::read(root.join("unknown.txt")).unwrap(),
        b"must not touch replacement"
    );
}

#[cfg(windows)]
#[test]
fn windows_cache_refuses_parent_rename_and_never_deletes_an_open_package() {
    let (_, d, base, _, _) = fixture();
    let (_directory, root) = root();
    let mut cache = Cache::open(root.clone()).unwrap();
    cache.store(WINDOWS, "0.2.1", &base).unwrap();
    assert!(fs::rename(&root, root.with_file_name("cannot-move-live-cache")).is_err());
    let name = cache_name(WINDOWS, "0.2.1", &d.base_sha256).unwrap();
    let in_use = cache.dir.file(&name, FileMode::Read).unwrap();
    assert!(cache.remove(&name).is_err());
    drop(in_use);
    cache.remove(&name).unwrap();
}

#[test]
fn both_macos_architectures_bind_the_selected_app_archive_and_exact_delta_key() {
    for p in [MAC_X64, MAC_ARM64] {
        let (mut release, mut d, _, _, _) = fixture();
        d.full_url = format!("{ASSET_PREFIX}v0.3.0/ysu-net.app.tar.gz");
        release.target = p.os.into();
        release.url = d.full_url.parse().unwrap();
        release.raw = json!({"version":release.version, "platforms": {
            (p.key): {"url":release.url, "signature":release.signature}
        }, "deltas": {(p.key): [descriptor_json(&d)]}});
        assert_eq!(descriptors(&release, p).len(), 1);
        let other = if p == MAC_X64 { MAC_ARM64 } else { MAC_X64 };
        assert!(descriptors(&release, other).is_empty());
        release.raw["deltas"][p.key][0]["full_signature"] = json!("different signature");
        assert!(descriptors(&release, p).is_empty());
    }
}

#[tokio::test]
async fn patch_network_and_signature_failures_each_have_one_full_attempt_only() {
    let (release, _, base, target, patch) = fixture();
    for bad_network in [true, false] {
        let (_directory, root) = root();
        Cache::open(root.clone())
            .unwrap()
            .store(WINDOWS, "0.2.1", &base)
            .unwrap();
        let reply = if bad_network {
            Err(UpdateError::DownloadFailed)
        } else {
            Ok(patch.clone())
        };
        let network = FakeNetwork::new(vec![reply, Ok(target.clone())]);
        let progress = RecordedProgress::default();
        let mut verifier = FakeVerifier::new(&target, &patch);
        verifier.reject_patch = !bad_network;
        assert_eq!(
            download_inner(
                release.clone(),
                Some(WINDOWS),
                Some(root),
                &progress,
                &network,
                verifier
            )
            .await
            .unwrap(),
            target
        );
        assert_eq!(network.calls.lock().unwrap().len(), 2);
        assert_eq!(
            *progress.transfers.lock().unwrap(),
            [("delta", false), ("full", true)]
        );
    }
}

#[cfg(windows)]
#[test]
fn windows_reparse_point_cache_roots_and_packages_are_not_followed() {
    use std::os::windows::fs::{symlink_dir, symlink_file};
    let (directory, root) = root();
    let outside = directory.path().canonicalize().unwrap().join("outside");
    fs::create_dir(&outside).unwrap();
    // Cloud runner must provide symlink privilege; lack of it is not a false pass.
    symlink_dir(&outside, &root).expect("cloud symlink fixture requires symlink privilege");
    assert!(Cache::open(root).is_err());
    let (_other, other_root) = self::root();
    fs::create_dir(&other_root).unwrap();
    let payload = outside.join("fixture.txt");
    fs::write(&payload, b"fixture").unwrap();
    let name = cache_name(WINDOWS, "0.2.1", &digest(b"fixture")).unwrap();
    symlink_file(&payload, other_root.join(name))
        .expect("cloud symlink fixture requires symlink privilege");
    assert!(Cache::open(other_root).is_err());
    assert_eq!(fs::read(payload).unwrap(), b"fixture");
}
