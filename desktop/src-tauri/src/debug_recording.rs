//! Session-scoped, bounded JSONL recording. Only ysu-auth's typed events are accepted.
//! Decision: .agents/notes/implemented/desktop/2026-10-28-opt-in-auth-recording.md
use chrono::{SecondsFormat, Utc};
use fs2::FileExt;
use serde::Serialize;
use serde_json::{json, Value};
use std::{fs::{self, File}, io::Write, path::{Path, PathBuf}, sync::{Arc, Mutex}, time::Instant};
use ysu_auth::{Trace, TraceRecord};

const LIMIT: u64 = 8 * 1024 * 1024;
const RESERVE: u64 = 1024;
const FILES: usize = 5;
struct Maintenance(File);
impl Drop for Maintenance { fn drop(&mut self) { let _ = FileExt::unlock(&self.0); } }

const ERROR: &str = "调试记录无法写入，请检查目录权限或磁盘空间";

#[derive(Clone, Copy, Serialize)]
#[serde(rename_all = "snake_case")]
enum StopReason { User, Shutdown, SizeLimit }
#[derive(Serialize)]
#[serde(rename_all = "snake_case")]
enum TaskAction { Status, Info, Login, Logout, Switch, SwitchAccount, Auto, Observe, Other }
#[derive(Serialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
enum Event {
    Started { version: &'static str, platform: &'static str, architecture: &'static str, source_commit: Option<&'static str> },
    Authentication { record: TraceRecord },
    Stopped { reason: StopReason },
    Task { action: TaskAction, phase: ysu_auth::DiagnosticStage, code: Option<i32>, diagnostic: Option<ysu_auth::AuthDiagnostic> },
}

struct Writer {
    file: File,
    lock: File,
    name: String,
    bytes: u64,
    sequence: u64,
    started: Instant,
    state: &'static str,
}
impl Writer {
    fn line(&mut self, event: &Event) -> std::io::Result<()> {
        let mut data = serde_json::to_vec(&json!({"schema":1, "sequence":self.sequence + 1,
            "timestamp":Utc::now().to_rfc3339_opts(SecondsFormat::Millis, true),
            "elapsed_ms":self.started.elapsed().as_millis().min(u64::MAX as u128) as u64,
            "data": event}))?;
        data.push(b'\n');
        if self.bytes + data.len() as u64 > LIMIT {
            return Err(std::io::Error::other("trace size limit"));
        }
        self.file.write_all(&data)?;
        self.file.flush()?;
        self.bytes += data.len() as u64;
        self.sequence += 1;
        Ok(())
    }
    fn record(&mut self, record: TraceRecord) {
        self.event(Event::Authentication { record });
    }
    fn event(&mut self, event: Event) {
        if self.state != "recording" { return; }
        // Keep enough space for a terminal marker. Events contain only bounded enums/numbers.
        if self.bytes + 4096 > LIMIT - RESERVE { self.stop(StopReason::SizeLimit); return; }
        if self.line(&event).is_err() { self.state = "error"; }
    }
    fn stop(&mut self, reason: StopReason) {
        if self.state != "recording" { return; }
        self.state = if self.line(&Event::Stopped { reason }).and_then(|_| self.file.sync_data()).is_ok() {
            if matches!(reason, StopReason::SizeLimit) { "limit" } else { "stopped" }
        } else { "error" };
    }
}
impl Drop for Writer {
    fn drop(&mut self) { self.stop(StopReason::Shutdown); let _ = FileExt::unlock(&self.lock); }
}

pub(crate) struct Recording {
    directory: PathBuf,
    current: Mutex<Option<(Arc<Mutex<Writer>>, Trace)>>,
}
impl Recording {
    pub(crate) fn new(config: &Path) -> Self {
        Self { directory: config.with_extension("diagnostics"), current: Mutex::new(None) }
    }
    pub(crate) fn trace(&self) -> Trace {
        self.current.lock().unwrap().as_ref().filter(|(writer, _)| writer.lock().unwrap().state == "recording").map(|(_, trace)| trace.clone()).unwrap_or_default()
    }
    pub(crate) fn status(&self) -> Value {
        let current = self.current.lock().unwrap();
        let (state, name, bytes, records) = if let Some((writer, _)) = current.as_ref() {
            let writer = writer.lock().unwrap();
            (writer.state, Some(writer.name.clone()), writer.bytes, writer.sequence)
        } else { ("off", None, 0, 0) };
        json!({"state":state,"file":name,"bytes":bytes,"records":records,
            "directory_available":plain_directory(&self.directory),"limit_bytes":LIMIT})
    }
    pub(crate) fn directory(&self) -> Result<&Path, String> {
        if !plain_directory(&self.directory) { return Err("尚无可打开的调试记录目录".into()); }
        Ok(&self.directory)
    }
    pub(crate) fn start(&self) -> Result<Value, String> {
        let mut current = self.current.lock().unwrap();
        if let Some((writer, _)) = current.as_ref() {
            if writer.lock().unwrap().state == "recording" { return Err("调试记录已经开启".into()); }
        }
        let mut builder = fs::DirBuilder::new();
        builder.recursive(true);
        #[cfg(unix)] { use std::os::unix::fs::DirBuilderExt; builder.mode(0o700); }
        builder.create(&self.directory).map_err(|_| ERROR)?;
        if !plain_directory(&self.directory) { return Err(ERROR.into()); }
        let _maintenance = Maintenance(crate::storage::lock_file(&self.directory.join(".maintenance.lock"), false)?);
        prune(&self.directory).map_err(|_| ERROR)?;
        let named = tempfile::Builder::new().prefix("auth-trace-").suffix(".jsonl")
            .tempfile_in(&self.directory).map_err(|_| ERROR)?;
        let (file, path) = named.keep().map_err(|_| ERROR)?;
        let lock = crate::storage::lock_file(&path.with_extension("lock"), false)?;
        let mut writer = Writer { file, lock, name: path.file_name().ok_or(ERROR)?.to_string_lossy().into_owned(),
            bytes: 0, sequence: 0, started: Instant::now(), state: "recording" };
        writer.line(&Event::Started { version: env!("CARGO_PKG_VERSION"), platform: std::env::consts::OS,
            architecture: std::env::consts::ARCH, source_commit: option_env!("GITHUB_SHA").filter(|v| v.len() == 40 && v.bytes().all(|b| b.is_ascii_hexdigit())) }).map_err(|_| ERROR)?;
        writer.file.sync_data().map_err(|_| ERROR)?;
        let writer = Arc::new(Mutex::new(writer));
        let sink = writer.clone();
        let trace = Trace::new(move |record| { sink.lock().unwrap().record(record); });
        *current = Some((writer, trace));
        drop(current);
        Ok(self.status())
    }
    pub(crate) fn stop(&self) -> Value { self.close(StopReason::User); self.status() }
    pub(crate) fn task(&self, action: &str, phase: ysu_auth::DiagnosticStage, error: Option<&ysu_auth::AuthError>) {
        let action = match action {
            "status" => TaskAction::Status, "info" => TaskAction::Info,
            "login" => TaskAction::Login, "logout" => TaskAction::Logout,
            "switch_service" => TaskAction::Switch, "switch_account" => TaskAction::SwitchAccount,
            "auto" => TaskAction::Auto, "observe" => TaskAction::Observe, _ => TaskAction::Other,
        };
        if let Some((writer, _)) = self.current.lock().unwrap().as_ref() {
            writer.lock().unwrap().event(Event::Task { action, phase,
                code: error.map(|e| e.code), diagnostic: error.map(ysu_auth::AuthError::diagnostic) });
        }
    }
    pub(crate) fn shutdown(&self) { self.close(StopReason::Shutdown); }
    fn close(&self, reason: StopReason) {
        if let Some((writer, _)) = self.current.lock().unwrap().as_ref() { writer.lock().unwrap().stop(reason); }
    }
}

fn plain_directory(path: &Path) -> bool {
    fs::symlink_metadata(path).is_ok_and(|meta| meta.is_dir() && !reparse(&meta))
}
fn reparse(meta: &fs::Metadata) -> bool {
    if meta.file_type().is_symlink() { return true; }
    #[cfg(windows)] { use std::os::windows::fs::MetadataExt; if meta.file_attributes() & 0x400 != 0 { return true; } }
    false
}
fn owned_name(name: &str) -> bool {
    name.strip_prefix("auth-trace-").and_then(|n| n.strip_suffix(".jsonl"))
        .is_some_and(|n| (6..=32).contains(&n.len()) && n.bytes().all(|b| b.is_ascii_alphanumeric()))
}
fn prune(directory: &Path) -> std::io::Result<()> {
    let mut files = Vec::new();
    for entry in fs::read_dir(directory)? {
        let entry = entry?;
        if !owned_name(&entry.file_name().to_string_lossy()) { continue; }
        let meta = fs::symlink_metadata(entry.path())?;
        if !meta.is_file() || reparse(&meta) { continue; }
        files.push((meta.modified()?, entry.path()));
    }
    files.sort_by_key(|(time, _)| *time);
    let mut count = files.len();
    for (_, path) in files {
        if count < FILES { break; }
        let marker = path.with_extension("lock");
        let file = match crate::storage::lock_file(&marker, false) { Ok(file) => file, Err(_) => continue };
        // Lock a sidecar: locking JSONL itself would prevent Windows readers opening a live trace.
        let result = fs::remove_file(&path);
        let _ = FileExt::unlock(&file);
        result?;
        drop(file);
        fs::remove_file(marker)?;
        count -= 1;
    }
    if count >= FILES { return Err(std::io::Error::other("trace retention busy")); }
    Ok(())
}

#[cfg(test)]
#[path = "debug_recording_tests.rs"]
mod tests;
