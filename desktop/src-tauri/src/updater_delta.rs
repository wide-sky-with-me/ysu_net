//! Bounded transport and opt-in BSDIFF40 reconstruction. Called only after the
//! parent's user/admission gates; this module never installs or touches app files.
//! Cache hashes are lookup hints, not a trust root: every returned payload has
//! passed the original SDK verifier, including its signed-version policy.
use super::{DownloadMode, Progress, UpdateError, UpdatePhase};
use bzip2::read::BzDecoder;
use fs2::FileExt;
use serde::Deserialize;
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::{
    ffi::OsString,
    fs::{File, Metadata},
    future::Future,
    io::{self, Read, Write},
    path::{Component, Path, PathBuf},
    time::{Duration, Instant, SystemTime},
};
#[cfg(any(windows, test))]
use std::fs;
#[cfg(windows)]
use windows_sys::Win32::{
    Foundation::{GENERIC_READ, GENERIC_WRITE},
    Storage::FileSystem::{
        DELETE, FILE_ATTRIBUTE_REPARSE_POINT, FILE_FLAG_BACKUP_SEMANTICS,
        FILE_FLAG_OPEN_REPARSE_POINT, FILE_READ_ATTRIBUTES, FILE_SHARE_READ,
        FILE_SHARE_WRITE, FILE_TRAVERSE,
    },
};
use tauri_plugin_updater::Update;

const FEED_LIMIT: usize = 1024 * 1024;
const FULL_LIMIT: u64 = 64 * 1024 * 1024;
const PATCH_LIMIT: u64 = 32 * 1024 * 1024;
const REQUEST_TIMEOUT: Duration = Duration::from_secs(300);
const CHECK_TIMEOUT: Duration = Duration::from_secs(30);
const CONTROL_LIMIT: usize = 100_000;
const ZERO_PROGRESS_LIMIT: usize = 1024;
const SIGNATURE_LIMIT: usize = 16 * 1024;
const URL_LIMIT: usize = 4096;
const CACHE_LOCK: &str = ".update-packages-v1.lock";
const TEMP_PREFIX: &str = ".update-tmp-";
const ASSET_PREFIX: &str =
    "https://github.com/wide-sky-with-me/ysu_net/releases/download/";

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
struct Platform {
    key: &'static str,
    bare: &'static str,
    os: &'static str,
    suffix: &'static str,
}
const WINDOWS: Platform = Platform {
    key: "windows-x86_64-nsis", bare: "windows-x86_64", os: "windows", suffix: ".exe",
};
const MAC_X64: Platform = Platform {
    key: "darwin-x86_64-app", bare: "darwin-x86_64", os: "darwin", suffix: ".app.tar.gz",
};
const MAC_ARM64: Platform = Platform {
    key: "darwin-aarch64-app", bare: "darwin-aarch64", os: "darwin", suffix: ".app.tar.gz",
};

fn platform() -> Option<Platform> {
    // Deliberately independent of Update.target, which normally contains only OS.
    if cfg!(all(target_os = "windows", target_arch = "x86_64")) {
        Some(WINDOWS)
    } else if cfg!(all(target_os = "macos", target_arch = "x86_64")) {
        Some(MAC_X64)
    } else if cfg!(all(target_os = "macos", target_arch = "aarch64")) {
        Some(MAC_ARM64)
    } else {
        None
    }
}

fn transport_url(url: &reqwest::Url) -> bool {
    url.as_str().len() <= 16 * 1024
        && url.scheme() == "https"
        && url.port().is_none()
        && url.username().is_empty()
        && url.password().is_none()
        && url.fragment().is_none()
        && matches!(url.host_str(), Some("github.com" | "release-assets.githubusercontent.com"
            | "objects.githubusercontent.com" | "github-releases.githubusercontent.com"))
}

fn asset_url(raw: &str) -> Option<reqwest::Url> {
    if raw.len() > URL_LIMIT || !raw.starts_with(ASSET_PREFIX) { return None; }
    let url = reqwest::Url::parse(raw).ok()?;
    if !transport_url(&url) || url.query().is_some() || url.as_str() != raw { return None; }
    let parts: Vec<_> = url.path_segments()?.collect();
    if parts.len() != 6 || parts[0..4] != ["wide-sky-with-me", "ysu_net", "releases", "download"] {
        return None;
    }
    if !parts[4..].iter().all(|part| !part.is_empty() && part.len() <= 255
        && *part != "." && *part != ".."
        && part.bytes().all(|b| b.is_ascii_alphanumeric() || b"._+-".contains(&b))) {
        return None;
    }
    Some(url)
}

fn client(timeout: Duration) -> Result<reqwest::Client, ()> {
    reqwest::Client::builder()
        .https_only(true)
        .no_gzip().no_brotli().no_deflate().no_zstd()
        .user_agent("ysu-net-updater")
        // Keep configured system proxies; no application credentials/SDK headers are added.
        .referer(false)
        .timeout(timeout)
        .redirect(reqwest::redirect::Policy::custom(|attempt| {
            // previous includes the initial request; this permits exactly five hops.
            if attempt.previous().len() > 5 || !transport_url(attempt.url()) {
                attempt.error("update redirect rejected")
            } else {
                attempt.follow()
            }
        }))
        .build().map_err(|_| ())
}

fn append_bounded(buffer: &mut Vec<u8>, bytes: &[u8], limit: usize) -> Result<(), ()> {
    if buffer.len().checked_add(bytes.len()).filter(|n| *n <= limit).is_none() {
        return Err(());
    }
    buffer.try_reserve(bytes.len()).map_err(|_| ())?;
    buffer.extend_from_slice(bytes);
    Ok(())
}

enum BodyError { Network, Limit }

async fn body_bounded(
    mut response: reqwest::Response,
    limit: usize,
    mut chunk: impl FnMut(usize, Option<u64>),
) -> Result<Vec<u8>, BodyError> {
    let total = response.content_length();
    if total.is_some_and(|n| n > limit as u64) { return Err(BodyError::Limit); }
    let mut bytes = Vec::new();
    while let Some(part) = response.chunk().await.map_err(|_| BodyError::Network)? {
        append_bounded(&mut bytes, &part, limit).map_err(|_| BodyError::Limit)?;
        chunk(part.len(), total);
    }
    Ok(bytes)
}

fn feed_status(status: u16) -> Result<bool, UpdateError> {
    match status {
        200 => Ok(true),
        204 => Ok(false),
        404 => Err(UpdateError::FeedNotReady),
        _ => Err(UpdateError::CheckFailed),
    }
}

pub(super) async fn fetch_feed() -> Result<Option<Value>, UpdateError> {
    tokio::time::timeout(CHECK_TIMEOUT, async {
        let url = reqwest::Url::parse(super::FEED_URL).map_err(|_| UpdateError::Configuration)?;
        if !transport_url(&url) { return Err(UpdateError::Configuration); }
        let response = client(CHECK_TIMEOUT).map_err(|_| UpdateError::Configuration)?
            .get(url).header(reqwest::header::ACCEPT, "application/json")
            .send().await.map_err(|_| UpdateError::CheckFailed)?;
        if !feed_status(response.status().as_u16())? { return Ok(None); }
        let bytes = body_bounded(response, FEED_LIMIT, |_, _| {}).await
            .map_err(|error| match error {
                BodyError::Network => UpdateError::CheckFailed,
                BodyError::Limit => UpdateError::InvalidFeed,
            })?;
        serde_json::from_slice(&bytes).map(Some).map_err(|_| UpdateError::InvalidFeed)
    }).await.map_err(|_| UpdateError::CheckFailed)?
}

#[derive(Clone)]
struct Release {
    current: String,
    version: String,
    target: String,
    url: reqwest::Url,
    signature: String,
    raw: Value,
}
impl From<&Update> for Release {
    fn from(update: &Update) -> Self {
        Self {
            current: update.current_version.clone(), version: update.version.clone(),
            target: update.target.clone(), url: update.download_url.clone(),
            signature: update.signature.clone(), raw: update.raw_json.clone(),
        }
    }
}

#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct Descriptor {
    format: String,
    base_version: String,
    base_sha256: String,
    base_size: u64,
    target_version: String,
    target_sha256: String,
    target_size: u64,
    full_url: String,
    full_signature: String,
    url: String,
    signature: String,
    sha256: String,
    size: u64,
}

fn valid_hash(value: &str) -> bool {
    value.len() == 64 && value.bytes().all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}
fn parsed_version(value: &str) -> Option<semver::Version> {
    if value.len() > 128 { return None; }
    let version = semver::Version::parse(value).ok()?;
    (version.to_string() == value).then_some(version)
}
fn valid_signature(value: &str) -> bool {
    !value.trim().is_empty() && value.len() <= SIGNATURE_LIMIT
}
fn digest(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}
fn exact_bytes(bytes: &[u8], size: u64, hash: &str) -> bool {
    bytes.len() as u64 == size && digest(bytes) == hash
}

fn descriptors(release: &Release, p: Platform) -> Vec<Descriptor> {
    let Some(current) = parsed_version(&release.current) else { return vec![]; };
    let Some(target) = parsed_version(&release.version) else { return vec![]; };
    if release.target != p.os || !current.cmp_precedence(&target).is_lt()
        || !release.url.path().ends_with(p.suffix) { return vec![]; }
    let Some(platforms) = release.raw.get("platforms").and_then(Value::as_object) else {
        return vec![]; // Dynamic manifests cannot establish the complete architecture key.
    };
    // Match the official SDK 2.14.0's installer-specific entry before its bare entry.
    let key = if platforms.contains_key(p.key) { p.key } else { p.bare };
    let Some(original) = platforms.get(key) else { return vec![]; };
    if original.get("url").and_then(Value::as_str) != Some(release.url.as_str())
        || original.get("signature").and_then(Value::as_str) != Some(release.signature.as_str()) {
        return vec![];
    }
    let Some(entries) = release.raw.get("deltas").and_then(|v| v.get(key)).and_then(Value::as_array)
        else { return vec![]; };
    if entries.len() > 3 { return vec![]; }
    let mut result: Vec<_> = entries.iter().filter_map(|value| {
        let d: Descriptor = serde_json::from_value(value.clone()).ok()?;
        if d.format != "bsdiff40" || d.base_version != release.current
            || d.target_version != release.version
            || parsed_version(&d.base_version).as_ref() != Some(&current)
            || parsed_version(&d.target_version).as_ref() != Some(&target)
            || ![&d.base_sha256, &d.target_sha256, &d.sha256].into_iter().all(|s| valid_hash(s))
            || !valid_signature(&d.signature) || !valid_signature(&d.full_signature)
            || d.full_url != release.url.as_str() || d.full_signature != release.signature
            || asset_url(&d.full_url).is_none() || asset_url(&d.url).is_none()
            || d.base_size == 0 || d.base_size > FULL_LIMIT
            || d.target_size == 0 || d.target_size > FULL_LIMIT
            || d.size == 0 || d.size > PATCH_LIMIT
            || d.size.checked_mul(5)? >= d.target_size.checked_mul(4)? {
            return None;
        }
        Some(d)
    }).collect();
    result.sort_by_key(|d| d.size);
    result
}

trait Network: Sync {
    fn fetch(&self, url: &reqwest::Url, limit: u64, progress: &impl Progress)
        -> impl Future<Output = Result<Vec<u8>, UpdateError>> + Send;
}
struct HttpNetwork;
impl Network for HttpNetwork {
    async fn fetch(&self, url: &reqwest::Url, limit: u64, progress: &impl Progress)
        -> Result<Vec<u8>, UpdateError> {
        if !transport_url(url) { return Err(UpdateError::UntrustedAsset); }
        tokio::time::timeout(REQUEST_TIMEOUT, async {
            let response = client(REQUEST_TIMEOUT).map_err(|_| UpdateError::DownloadFailed)?
                .get(url.clone()).header(reqwest::header::ACCEPT, "application/octet-stream")
                .send().await.map_err(|_| UpdateError::DownloadFailed)?;
            if response.status() != reqwest::StatusCode::OK { return Err(UpdateError::DownloadFailed); }
            body_bounded(response, limit as usize, |length, total| progress.chunk(length, total))
                .await.map_err(|_| UpdateError::DownloadFailed)
        }).await.map_err(|_| UpdateError::DownloadFailed)?
    }
}

trait Verifier: Clone + Send + Sync + 'static {
    fn full(&self, bytes: &[u8]) -> Result<(), UpdateError>;
    fn patch(&self, bytes: &[u8], signature: &str) -> Result<(), UpdateError>;
}
#[derive(Clone)]
struct SdkVerifier(Update);
impl Verifier for SdkVerifier {
    fn full(&self, bytes: &[u8]) -> Result<(), UpdateError> {
        self.0.verify(bytes).map_err(|_| UpdateError::Signature)
    }
    fn patch(&self, bytes: &[u8], signature: &str) -> Result<(), UpdateError> {
        // Preserve the original public key, signed target version and SDK policy.
        let mut signed_patch = self.0.clone();
        signed_patch.signature = signature.to_owned();
        signed_patch.verify(bytes).map_err(|_| UpdateError::Signature)
    }
}

pub(super) async fn download(
    update: &Update,
    cache_root: Option<PathBuf>,
    progress: &impl Progress,
) -> Result<Vec<u8>, UpdateError> {
    download_inner(Release::from(update), platform(), cache_root, progress,
        &HttpNetwork, SdkVerifier(update.clone())).await
}

async fn download_inner(
    release: Release,
    p: Option<Platform>,
    root: Option<PathBuf>,
    progress: &impl Progress,
    network: &impl Network,
    verifier: impl Verifier,
) -> Result<Vec<u8>, UpdateError> {
    if asset_url(release.url.as_str()).is_none() || !valid_signature(&release.signature) {
        return Err(UpdateError::UntrustedAsset);
    }
    // This function is reached only by the parent's explicitly confirmed install.
    // Failure to open/lock/maintain a cache disables caching, never installation.
    let mut cache = match (root, p) {
        (Some(root), Some(_)) => Cache::open(root).ok(),
        _ => None,
    };
    let mut selected = None;
    if let (Some(cache), Some(p)) = (cache.as_mut(), p) {
        for d in descriptors(&release, p) {
            // First launch has no exact base: do not fetch an old full package.
            if let Ok(base) = cache.base(p, &d) { selected = Some((d, base)); break; }
        }
    }
    let fallback = selected.is_some();
    if let Some((d, base)) = selected {
        progress.transfer(DownloadMode::Delta, false);
        progress.phase(UpdatePhase::Downloading);
        let attempt = async {
            let url = asset_url(&d.url).ok_or(UpdateError::DownloadFailed)?;
            let patch = network.fetch(&url, PATCH_LIMIT, progress).await?;
            progress.phase(UpdatePhase::Verifying);
            let verifier = verifier.clone();
            // Authentication and preflight happen in this worker before *any*
            // bzip decoding. All stages see the same owned, immutable patch Vec.
            progress.phase(UpdatePhase::Reconstructing);
            tauri::async_runtime::spawn_blocking(move || {
                reconstruct_with(&base, &patch, &d, &verifier, checked_apply)
            }).await.map_err(|_| UpdateError::DownloadFailed)?
        }.await;
        if let Ok(bytes) = attempt {
            progress.phase(UpdatePhase::Verifying);
            if let (Some(cache), Some(p)) = (cache.as_mut(), p) {
                let _ = cache.store(p, &release.version, &bytes);
            }
            return Ok(bytes);
        }
    }
    // Exactly one full attempt, with its own hard limit and official signature.
    // Never require a delta's unauthenticated target SHA/size on this fallback.
    progress.transfer(DownloadMode::Full, fallback);
    progress.phase(UpdatePhase::Downloading);
    let bytes = network.fetch(&release.url, FULL_LIMIT, progress).await?;
    if bytes.len() as u64 > FULL_LIMIT { return Err(UpdateError::DownloadFailed); }
    progress.phase(UpdatePhase::Verifying);
    verifier.full(&bytes)?;
    if let (Some(cache), Some(p)) = (cache.as_mut(), p) {
        let _ = cache.store(p, &release.version, &bytes);
    }
    Ok(bytes)
}

// This seam is also used by offline tests and the Lead's cloud-generated SDK
// double-signature fixture. Injected decoders cannot run before patch verification.
#[cfg(test)]
pub(super) fn reconstruct_sdk_fixture(
    update: &Update, base: &[u8], patch: &[u8], metadata: Value,
) -> Result<Vec<u8>, UpdateError> {
    let d: Descriptor = serde_json::from_value(metadata).map_err(|_| UpdateError::InvalidFeed)?;
    if d.target_version != update.version || d.base_version != update.current_version
        || d.full_url != update.download_url.as_str() || d.full_signature != update.signature {
        return Err(UpdateError::InvalidFeed);
    }
    reconstruct_with(base, patch, &d, &SdkVerifier(update.clone()), checked_apply)
}

fn reconstruct_with(
    base: &[u8], patch: &[u8], d: &Descriptor, verifier: &impl Verifier,
    decode: impl FnOnce(&[u8], &[u8], u64) -> io::Result<Vec<u8>>,
) -> Result<Vec<u8>, UpdateError> {
    if patch.len() as u64 > PATCH_LIMIT || !exact_bytes(base, d.base_size, &d.base_sha256)
        || !exact_bytes(patch, d.size, &d.sha256) { return Err(UpdateError::DownloadFailed); }
    verifier.patch(patch, &d.signature)?;
    let bytes = decode(base, patch, d.target_size).map_err(|_| UpdateError::DownloadFailed)?;
    if !exact_bytes(&bytes, d.target_size, &d.target_sha256) {
        return Err(UpdateError::DownloadFailed);
    }
    verifier.full(&bytes)?;
    Ok(bytes)
}

fn invalid() -> io::Error { io::Error::new(io::ErrorKind::InvalidData, "invalid update data") }
fn deadline_check(deadline: Instant) -> io::Result<()> {
    if Instant::now() > deadline { return Err(io::Error::new(io::ErrorKind::TimedOut, "update budget")); }
    Ok(())
}

// BSDIFF uses sign/magnitude. Reject negative zero too: qbsdiff 1.4.4 decodes its
// special bit pattern as i64::MIN, unlike the usual BSDIFF interpretation.
fn signed_int(bytes: &[u8]) -> io::Result<i64> {
    let raw = u64::from_le_bytes(bytes.try_into().map_err(|_| invalid())?);
    let magnitude = raw & (i64::MAX as u64);
    if raw >> 63 == 0 { Ok(magnitude as i64) }
    else if magnitude == 0 { Err(invalid()) }
    else { Ok(-(magnitude as i64)) }
}
fn positive_int(bytes: &[u8]) -> io::Result<u64> {
    u64::try_from(signed_int(bytes)?).map_err(|_| invalid())
}

struct PatchSections<'a> { controls: &'a [u8], delta: &'a [u8], extra: &'a [u8] }
fn sections(patch: &[u8], expected: u64) -> io::Result<PatchSections<'_>> {
    if patch.len() < 32 || patch.len() as u64 > PATCH_LIMIT || &patch[..8] != b"BSDIFF40"
        || expected == 0 || expected > FULL_LIMIT { return Err(invalid()); }
    let control = positive_int(&patch[8..16])?;
    let delta = positive_int(&patch[16..24])?;
    let target = positive_int(&patch[24..32])?;
    if target != expected { return Err(invalid()); }
    let middle = 32u64.checked_add(control).ok_or_else(invalid)?;
    let end = middle.checked_add(delta).ok_or_else(invalid)?;
    if end > patch.len() as u64 { return Err(invalid()); }
    Ok(PatchSections {
        controls: &patch[32..middle as usize], delta: &patch[middle as usize..end as usize],
        extra: &patch[end as usize..],
    })
}

struct BudgetReader<R> { inner: R, deadline: Instant }
impl<R: Read> Read for BudgetReader<R> {
    fn read(&mut self, out: &mut [u8]) -> io::Result<usize> {
        deadline_check(self.deadline)?;
        // Cooperative deadline only, not a hard process CPU timeout.
        let count = out.len().min(16 * 1024);
        self.inner.read(&mut out[..count])
    }
}
fn decoder(bytes: &[u8], deadline: Instant) -> BzDecoder<BudgetReader<&[u8]>> {
    BzDecoder::new(BudgetReader { inner: bytes, deadline })
}
fn exact_stream(bytes: &[u8], expected: u64, deadline: Instant) -> io::Result<()> {
    let mut reader = decoder(bytes, deadline);
    let mut total = 0u64;
    let mut buffer = [0u8; 16 * 1024];
    loop {
        deadline_check(deadline)?;
        let n = reader.read(&mut buffer)?;
        if n == 0 { break; }
        total = total.checked_add(n as u64).ok_or_else(invalid)?;
        if total > expected || total > FULL_LIMIT { return Err(invalid()); }
    }
    if total != expected || reader.total_in() != bytes.len() as u64 { return Err(invalid()); }
    Ok(())
}

fn preflight(base_len: u64, patch: &[u8], expected: u64, deadline: Instant) -> io::Result<()> {
    let s = sections(patch, expected)?; // Checked before constructing Bspatch or any decoder.
    let mut controls = decoder(s.controls, deadline);
    let (mut records, mut zeros, mut output, mut source, mut add_total, mut copy_total) =
        (0usize, 0usize, 0u64, 0u64, 0u64, 0u64);
    loop {
        deadline_check(deadline)?;
        let mut tuple = [0u8; 24];
        let first = controls.read(&mut tuple[..1])?;
        if first == 0 { break; }
        records = records.checked_add(1).ok_or_else(invalid)?;
        if records > CONTROL_LIMIT { return Err(invalid()); }
        controls.read_exact(&mut tuple[1..])?;
        let add = positive_int(&tuple[..8])?;
        let copy = positive_int(&tuple[8..16])?;
        let seek = signed_int(&tuple[16..])?;
        let progress = add.checked_add(copy).ok_or_else(invalid)?;
        if progress == 0 { zeros += 1; } else { zeros = 0; }
        if zeros > ZERO_PROGRESS_LIMIT { return Err(invalid()); }
        output = output.checked_add(progress).ok_or_else(invalid)?;
        if output > expected || output > FULL_LIMIT { return Err(invalid()); }
        // qbsdiff reads source exactly (not BSDIFF's optional zero extension).
        source = source.checked_add(add).ok_or_else(invalid)?;
        if source > base_len { return Err(invalid()); }
        source = source.checked_add_signed(seek).ok_or_else(invalid)?;
        if source > base_len { return Err(invalid()); }
        add_total = add_total.checked_add(add).ok_or_else(invalid)?;
        copy_total = copy_total.checked_add(copy).ok_or_else(invalid)?;
    }
    if output != expected || controls.total_in() != s.controls.len() as u64
        || controls.total_out() > (CONTROL_LIMIT * 24) as u64 { return Err(invalid()); }
    exact_stream(s.delta, add_total, deadline)?;
    exact_stream(s.extra, copy_total, deadline)
}

struct BudgetWriter { bytes: Vec<u8>, limit: usize, deadline: Instant }
impl Write for BudgetWriter {
    fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
        deadline_check(self.deadline)?;
        append_bounded(&mut self.bytes, bytes, self.limit).map_err(|_| invalid())?;
        Ok(bytes.len())
    }
    fn flush(&mut self) -> io::Result<()> { deadline_check(self.deadline) }
}
fn checked_apply(base: &[u8], patch: &[u8], expected: u64) -> io::Result<Vec<u8>> {
    let deadline = Instant::now() + REQUEST_TIMEOUT;
    preflight(base.len() as u64, patch, expected, deadline)?;
    // No mutable alias of patch exists between preflight and qbsdiff parsing.
    let patcher = qbsdiff::Bspatch::new(patch)?;
    if patcher.hint_target_size() != expected { return Err(invalid()); }
    let mut output = BudgetWriter { bytes: Vec::new(), limit: expected as usize, deadline };
    let written = patcher.apply(base, &mut output)?;
    if written != expected || output.bytes.len() as u64 != expected { return Err(invalid()); }
    Ok(output.bytes)
}

// A cache owns an exclusive global lock for the whole download, including base
// reads and maintenance. Unix operations are anchored to an O_NOFOLLOW dirfd;
// Windows retains no-delete-share handles on the entire parent chain.
struct Cache { dir: CacheDir, _lock: File, protected_base: Option<String> }
struct Entry { name: String, size: u64, modified: SystemTime }

fn cache_name(p: Platform, version: &str, hash: &str) -> Option<String> {
    parsed_version(version)?;
    if !valid_hash(hash) { return None; }
    Some(format!("pkg-{}__{}__{}.bin", p.key, version, hash))
}
fn own_package(name: &str) -> bool {
    [WINDOWS, MAC_X64, MAC_ARM64].into_iter().any(|p| {
        let Some(rest) = name.strip_prefix(&format!("pkg-{}__", p.key)) else { return false; };
        let Some((version, hash)) = rest.strip_suffix(".bin").and_then(|r| r.split_once("__"))
            else { return false; };
        cache_name(p, version, hash).as_deref() == Some(name)
    })
}
fn own_temp(name: &str) -> bool {
    name.strip_prefix(TEMP_PREFIX).is_some_and(|s| s.len() == 32
        && s.bytes().all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b)))
}
fn regular(metadata: &Metadata) -> bool {
    if !metadata.is_file() { return false; }
    #[cfg(unix)] {
        use std::os::unix::fs::MetadataExt;
        if metadata.uid() != rustix::process::geteuid().as_raw() { return false; }
    }
    #[cfg(windows)] {
        use std::os::windows::fs::MetadataExt;
        if metadata.file_attributes() & FILE_ATTRIBUTE_REPARSE_POINT != 0 { return false; }
    }
    true
}
impl Cache {
    fn open(root: PathBuf) -> io::Result<Self> {
        if root.file_name().and_then(|n| n.to_str()) != Some("update-packages-v1") {
            return Err(invalid());
        }
        let dir = CacheDir::open(&root)?;
        let lock = dir.file(CACHE_LOCK, FileMode::Lock)?;
        if !regular(&lock.metadata()?) { return Err(invalid()); }
        lock.try_lock_exclusive()?;
        let mut cache = Self { dir, _lock: lock, protected_base: None };
        cache.maintain(2)?;
        Ok(cache)
    }
    fn entries(&self) -> io::Result<Vec<Entry>> {
        let mut entries = Vec::new();
        let names = self.dir.names()?;
        // Bound maintenance even if a user populates this private directory.
        if names.len() > 128 { return Err(invalid()); }
        for name in names {
            let name = name.to_str().ok_or_else(invalid)?;
            if name == CACHE_LOCK { continue; }
            if !own_package(name) && !own_temp(name) { return Err(invalid()); }
            let file = self.dir.file(name, FileMode::Read)?;
            let metadata = file.metadata()?;
            if !regular(&metadata) { return Err(invalid()); }
            entries.push(Entry { name: name.into(), size: metadata.len(),
                modified: metadata.modified().unwrap_or(SystemTime::UNIX_EPOCH) });
        }
        Ok(entries)
    }
    fn remove(&self, name: &str) -> io::Result<()> {
        if !own_temp(name) && !own_package(name) { return Err(invalid()); }
        self.dir.remove(name)
    }
    fn maintain(&mut self, keep: usize) -> io::Result<()> {
        let mut entries = self.entries()?;
        for e in &entries { if own_temp(&e.name) { self.remove(&e.name)?; } }
        entries.retain(|e| own_package(&e.name));
        // Keep the exact base already used by this operation, even if an older
        // mtime would otherwise evict it before a failed target write.
        let protected = self.protected_base.as_deref();
        entries.sort_by(|a, b| (protected == Some(b.name.as_str()))
            .cmp(&(protected == Some(a.name.as_str())))
            .then_with(|| b.modified.cmp(&a.modified)).then_with(|| a.name.cmp(&b.name)));
        let mut count = 0;
        for e in entries {
            if e.size > FULL_LIMIT || count >= keep { self.remove(&e.name)?; }
            else { count += 1; }
        }
        Ok(())
    }
    fn base(&mut self, p: Platform, d: &Descriptor) -> io::Result<Vec<u8>> {
        let name = cache_name(p, &d.base_version, &d.base_sha256).ok_or_else(invalid)?;
        let mut file = self.dir.file(&name, FileMode::Read)?;
        let metadata = file.metadata()?;
        if !regular(&metadata) || metadata.len() != d.base_size || metadata.len() > FULL_LIMIT {
            return Err(invalid());
        }
        file.try_lock_exclusive()?;
        // Read, hash, and use this one opened object, never reopen by pathname.
        let mut bytes = Vec::new();
        let mut buffer = [0u8; 16 * 1024];
        loop {
            let n = file.read(&mut buffer)?;
            if n == 0 { break; }
            append_bounded(&mut bytes, &buffer[..n], d.base_size as usize).map_err(|_| invalid())?;
        }
        if !exact_bytes(&bytes, d.base_size, &d.base_sha256) { return Err(invalid()); }
        self.protected_base = Some(name);
        Ok(bytes)
    }
    // Call only with bytes already authenticated by the original SDK verifier.
    fn store(&mut self, p: Platform, version: &str, bytes: &[u8]) -> io::Result<()> {
        self.store_with(p, version, bytes, |file, bytes| {
            file.write_all(bytes)?;
            file.flush()?;
            file.sync_all()
        })
    }
    fn store_with(&mut self, p: Platform, version: &str, bytes: &[u8],
        write: impl FnOnce(&mut File, &[u8]) -> io::Result<()>) -> io::Result<()> {
        if bytes.len() as u64 > FULL_LIMIT { return Err(invalid()); }
        let name = cache_name(p, version, &digest(bytes)).ok_or_else(invalid)?;
        // At most one 64 MiB package remains before creating the temporary file:
        // peak <=128 MiB (stricter than 192 MiB), committed packages <=2.
        self.maintain(1)?;
        let temp = format!("{TEMP_PREFIX}{:032x}", rand::random::<u128>());
        let mut file = self.dir.file(&temp, FileMode::New)?;
        let result = (|| {
            write(&mut file, bytes)?;
            if file.metadata()?.len() != bytes.len() as u64 { return Err(invalid()); }
            self.dir.commit(&temp, &name, &file)?;
            self.dir.sync()
        })();
        drop(file);
        // Only this exact create_new name, under the still-held global lock.
        // Unlink the temporary hard link before syncing the directory again.
        let cleanup = self.dir.remove(&temp);
        if cleanup.is_ok() { let _ = self.dir.sync(); }
        result
    }
}

#[derive(Clone, Copy)]
enum FileMode { Read, Lock, New }

#[cfg(unix)]
struct CacheDir { root: File }
#[cfg(unix)]
impl CacheDir {
    fn open(path: &Path) -> io::Result<Self> {
        use rustix::{fs::{mkdirat, openat, Mode, OFlags}, io::Errno};
        use std::os::unix::fs::MetadataExt;
        if !path.is_absolute() { return Err(invalid()); }
        let mut dir = File::open("/")?;
        for component in path.components() {
            let Component::Normal(name) = component else {
                if matches!(component, Component::RootDir) { continue; }
                return Err(invalid());
            };
            let flags = OFlags::RDONLY | OFlags::CLOEXEC | OFlags::DIRECTORY | OFlags::NOFOLLOW;
            let fd = match openat(&dir, name, flags, Mode::empty()) {
                Ok(fd) => fd,
                Err(Errno::NOENT) => {
                    match mkdirat(&dir, name, Mode::RWXU) {
                        Ok(()) | Err(Errno::EXIST) => (),
                        Err(error) => return Err(error.into()),
                    }
                    openat(&dir, name, flags, Mode::empty())?
                }
                Err(error) => return Err(error.into()),
            };
            dir = File::from(fd);
        }
        let metadata = dir.metadata()?;
        if metadata.uid() != rustix::process::geteuid().as_raw() || metadata.mode() & 0o022 != 0 {
            return Err(invalid());
        }
        Ok(Self { root: dir })
    }
    fn file(&self, name: &str, mode: FileMode) -> io::Result<File> {
        use rustix::fs::{openat, Mode, OFlags};
        if name.contains('/') || name == "." || name == ".." { return Err(invalid()); }
        let mode = match mode {
            FileMode::Read => OFlags::RDONLY,
            FileMode::Lock => OFlags::RDWR | OFlags::CREATE,
            FileMode::New => OFlags::RDWR | OFlags::CREATE | OFlags::EXCL,
        };
        let fd = openat(&self.root, name,
            mode | OFlags::NOFOLLOW | OFlags::CLOEXEC | OFlags::NONBLOCK,
            Mode::RUSR | Mode::WUSR)?;
        let file = File::from(fd);
        if !regular(&file.metadata()?) { return Err(invalid()); }
        Ok(file)
    }
    fn names(&self) -> io::Result<Vec<OsString>> {
        use std::os::unix::ffi::OsStrExt;
        // read_from opens an independent "." file description; unlike dup, it
        // does not share our directory offset. rustix owns enumeration/errno/close.
        let mut directory = rustix::fs::Dir::read_from(&self.root)?;
        let mut names = Vec::new();
        while let Some(entry) = directory.read() {
            let entry = entry?;
            let name = entry.file_name().to_bytes();
            if name != b"." && name != b".." {
                names.push(std::ffi::OsStr::from_bytes(name).to_os_string());
                if names.len() > 128 { return Err(invalid()); }
            }
        }
        Ok(names)
    }
    fn remove(&self, name: &str) -> io::Result<()> {
        if !own_temp(name) && !own_package(name) { return Err(invalid()); }
        let file = self.file(name, FileMode::Read)?;
        if !regular(&file.metadata()?) { return Err(invalid()); }
        file.try_lock_exclusive()?;
        rustix::fs::unlinkat(&self.root, name, rustix::fs::AtFlags::empty())?;
        Ok(())
    }
    fn commit(&self, temp: &str, target: &str, file: &File) -> io::Result<()> {
        use rustix::fs::{linkat, unlinkat, AtFlags};
        use std::os::unix::fs::MetadataExt;
        if !own_temp(temp) || !own_package(target) { return Err(invalid()); }
        let expected = file.metadata()?;
        // linkat atomically adds a name without clobbering an existing target.
        // The temporary name is removed by the caller after this identity check.
        linkat(&self.root, temp, &self.root, target, AtFlags::empty())?;
        // A same-UID process can ignore our advisory lock and replace a name.
        // Require the published object to be the original still-open inode at
        // this check; this does not promise immunity to later same-UID writes.
        let matches = self.file(target, FileMode::Read)
            .and_then(|published| published.metadata())
            .is_ok_and(|actual| actual.dev() == expected.dev() && actual.ino() == expected.ino());
        if !matches {
            let _ = unlinkat(&self.root, target, AtFlags::empty());
            return Err(invalid());
        }
        Ok(())
    }
    fn sync(&self) -> io::Result<()> { self.root.sync_all() }
}

#[cfg(windows)]
struct CacheDir { root: PathBuf, _parents: Vec<File> }
#[cfg(windows)]
impl CacheDir {
    fn open(path: &Path) -> io::Result<Self> {
        use std::os::windows::fs::{MetadataExt, OpenOptionsExt};
        if !path.is_absolute() { return Err(invalid()); }
        let mut current = PathBuf::new();
        let mut parents = Vec::new();
        for component in path.components() {
            match component {
                Component::Prefix(_) | Component::RootDir => { current.push(component.as_os_str()); continue; }
                Component::Normal(_) => current.push(component.as_os_str()),
                _ => return Err(invalid()),
            }
            match fs::create_dir(&current) {
                Ok(()) => (),
                Err(e) if e.kind() == io::ErrorKind::AlreadyExists => (),
                Err(e) => return Err(e),
            }
            let file = fs::OpenOptions::new().read(true)
                .share_mode(FILE_SHARE_READ | FILE_SHARE_WRITE)
                // Restrict directory access to avoid the rename target's relative
                // FILE_WRITE_DATA | SYNCHRONIZE open conflicting with this handle.
                .access_mode(FILE_READ_ATTRIBUTES | FILE_TRAVERSE)
                .custom_flags(FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT)
                .open(&current)?;
            let metadata = file.metadata()?;
            if !metadata.is_dir() || metadata.file_attributes() & FILE_ATTRIBUTE_REPARSE_POINT != 0 {
                return Err(invalid());
            }
            parents.push(file); // No FILE_SHARE_DELETE: ancestors cannot be replaced.
        }
        if parents.is_empty() { return Err(invalid()); }
        Ok(Self { root: path.into(), _parents: parents })
    }
    fn file(&self, name: &str, mode: FileMode) -> io::Result<File> {
        use std::os::windows::fs::OpenOptionsExt;
        if name.contains(['/', '\\', ':']) || name == "." || name == ".." { return Err(invalid()); }
        let mut options = fs::OpenOptions::new();
        options.read(true).custom_flags(FILE_FLAG_OPEN_REPARSE_POINT);
        match mode {
            FileMode::Read => { options.share_mode(FILE_SHARE_READ); }
            FileMode::Lock => { options.write(true).create(true).share_mode(FILE_SHARE_READ | FILE_SHARE_WRITE); }
            FileMode::New => {
                options.write(true).create_new(true).share_mode(FILE_SHARE_READ)
                    .access_mode(GENERIC_READ | GENERIC_WRITE | DELETE);
            }
        }
        let file = options.open(self.root.join(name))?;
        if !regular(&file.metadata()?) { return Err(invalid()); }
        Ok(file)
    }
    fn names(&self) -> io::Result<Vec<OsString>> {
        let mut names = Vec::new();
        for entry in fs::read_dir(&self.root)? {
            names.push(entry?.file_name());
            if names.len() > 128 { return Err(invalid()); }
        }
        Ok(names)
    }
    fn remove(&self, name: &str) -> io::Result<()> {
        use std::os::windows::{fs::OpenOptionsExt, io::AsRawHandle};
        use windows_sys::Win32::Storage::FileSystem::{
            SetFileInformationByHandle, FileDispositionInfo, FILE_DISPOSITION_INFO,
        };
        if !own_temp(name) && !own_package(name) { return Err(invalid()); }
        // DELETE access fails while any cooperating reader has omitted
        // FILE_SHARE_DELETE. Delete by the checked opened handle, not by path.
        let file = fs::OpenOptions::new().read(true)
            .access_mode(GENERIC_READ | DELETE).share_mode(FILE_SHARE_READ)
            .custom_flags(FILE_FLAG_OPEN_REPARSE_POINT).open(self.root.join(name))?;
        if !regular(&file.metadata()?) { return Err(invalid()); }
        file.try_lock_exclusive()?;
        let delete = FILE_DISPOSITION_INFO { DeleteFile: true };
        // SAFETY: the synchronous std File remains open for the call. `delete`
        // is the official initialized structure, with its exact type/byte size,
        // and its immutable storage remains valid until the API returns.
        let result = unsafe {
            SetFileInformationByHandle(file.as_raw_handle(), FileDispositionInfo,
                (&delete as *const FILE_DISPOSITION_INFO).cast(),
                std::mem::size_of::<FILE_DISPOSITION_INFO>() as u32)
        };
        if result == 0 { return Err(io::Error::last_os_error()); }
        Ok(())
    }
    fn commit(&self, temp: &str, target: &str, file: &File) -> io::Result<()> {
        use std::os::windows::io::AsRawHandle;
        use windows_sys::{
            Wdk::Storage::FileSystem::{NtSetInformationFile, FileRenameInformation, FILE_RENAME_INFORMATION},
            Win32::{Foundation::RtlNtStatusToDosError, System::IO::IO_STATUS_BLOCK},
        };
        if !own_temp(temp) || !own_package(target) { return Err(invalid()); }
        let name: Vec<u16> = target.encode_utf16().collect();
        let name_bytes = name.len().checked_mul(std::mem::size_of::<u16>()).ok_or_else(invalid)?;
        let filename_length = u32::try_from(name_bytes).map_err(|_| invalid())?;
        let offset = std::mem::offset_of!(FILE_RENAME_INFORMATION, FileName);
        // Include the official header plus the UTF-16 tail and a zero terminator;
        // the recorded FileNameLength excludes that terminator, as required.
        let size = std::mem::size_of::<FILE_RENAME_INFORMATION>()
            .checked_add(name_bytes).and_then(|n| n.checked_add(std::mem::size_of::<u16>()))
            .ok_or_else(invalid)?;
        let information_length = u32::try_from(size).map_err(|_| invalid())?;
        const _: () = assert!(std::mem::align_of::<usize>() >= std::mem::align_of::<FILE_RENAME_INFORMATION>());
        let mut storage = vec![0usize; size.div_ceil(std::mem::size_of::<usize>())];
        let info = storage.as_mut_ptr().cast::<FILE_RENAME_INFORMATION>();
        let root = self._parents.last().ok_or_else(invalid)?.as_raw_handle();
        // SAFETY: usize storage is zero-initialized, statically aligned for the
        // official header and large enough for its checked UTF-16 tail. Every
        // field uses the generated ABI; copied name data is disjoint and fits
        // offset + name_bytes, with zero storage left for the terminator.
        unsafe {
            (*info).Anonymous.Flags = 0; // ReplaceIfExists = FALSE: no-clobber.
            (*info).RootDirectory = root;
            (*info).FileNameLength = filename_length;
            std::ptr::copy_nonoverlapping(name.as_ptr(),
                storage.as_mut_ptr().cast::<u8>().add(offset).cast::<u16>(), name.len());
        }
        let mut io_status = IO_STATUS_BLOCK::default();
        // SAFETY: both handles and all input/output buffers remain alive for this
        // call. FileMode::New uses a synchronous, non-OVERLAPPED std File, so NT
        // completes the request before returning; io_status never outlives its
        // stack storage. Native FileRenameInformation preserves RootDirectory
        // unlike Win32's relative-name rewriting on some Windows versions.
        let status = unsafe {
            NtSetInformationFile(file.as_raw_handle(), &mut io_status,
                storage.as_ptr().cast(), information_length, FileRenameInformation)
        };
        if status < 0 {
            // SAFETY: the generated system binding accepts this returned NTSTATUS
            // by value and does not borrow any of the caller's storage.
            let code = unsafe { RtlNtStatusToDosError(status) };
            return Err(io::Error::from_raw_os_error(code as i32));
        }
        Ok(())
    }
    fn sync(&self) -> io::Result<()> {
        // File::sync_all already persisted the payload. Directory FlushFileBuffers
        // is not portable on Windows and failure must not prevent installation.
        Ok(())
    }
}

#[cfg(not(any(unix, windows)))]
struct CacheDir;
#[cfg(not(any(unix, windows)))]
impl CacheDir {
    fn open(_: &Path) -> io::Result<Self> { Err(invalid()) }
    fn file(&self, _: &str, _: FileMode) -> io::Result<File> { Err(invalid()) }
    fn names(&self) -> io::Result<Vec<OsString>> { Err(invalid()) }
    fn remove(&self, _: &str) -> io::Result<()> { Err(invalid()) }
    fn commit(&self, _: &str, _: &str, _: &File) -> io::Result<()> { Err(invalid()) }
    fn sync(&self) -> io::Result<()> { Err(invalid()) }
}

#[cfg(test)]
#[path = "updater_delta_tests.rs"]
mod tests;
