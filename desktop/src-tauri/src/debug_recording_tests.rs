use super::*;
use ysu_auth::{DiagnosticOperation, DiagnosticStage, TraceEvent};

fn event() -> TraceRecord {
    TraceRecord { operation_id: 1, operation: DiagnosticOperation::Status, elapsed_ms: 1,
        event: TraceEvent::Stage { stage: DiagnosticStage::PortalNavigation } }
}
fn active_writer(recording: &Recording) -> Arc<Mutex<Writer>> {
    recording.current.lock().unwrap().as_ref().unwrap().0.clone()
}

#[test]
fn files_are_opt_in_flushed_and_survive_stopping_and_new_sessions() {
    let directory = tempfile::tempdir().unwrap();
    let recording = Recording::new(&directory.path().join("config.json"));
    assert_eq!(recording.status()["state"], "off");
    assert!(!recording.directory.exists());
    recording.start().unwrap();
    let old = active_writer(&recording);
    old.lock().unwrap().record(event());
    let path = recording.directory.join(old.lock().unwrap().name.clone());
    let live = fs::read_to_string(&path).unwrap();
    assert_eq!(live.lines().count(), 2);
    assert_eq!(serde_json::from_str::<Value>(live.lines().last().unwrap()).unwrap()["data"]["record"]["event"], "stage");
    assert!(recording.start().is_err());
    recording.stop();
    let stopped = fs::read(&path).unwrap();
    recording.start().unwrap();
    old.lock().unwrap().record(event());
    assert_eq!(fs::read(&path).unwrap(), stopped);
    assert_ne!(recording.status()["file"], path.file_name().unwrap().to_string_lossy().as_ref());
    recording.shutdown();
    assert_eq!(recording.status()["state"], "stopped");
    assert_eq!(fs::read_dir(&recording.directory).unwrap().filter_map(Result::ok).filter(|e| owned_name(&e.file_name().to_string_lossy())).count(), 2);
    #[cfg(unix)] {
        use std::os::unix::fs::PermissionsExt;
        assert_eq!(fs::metadata(&path).unwrap().permissions().mode() & 0o777, 0o600);
        assert_eq!(fs::metadata(&recording.directory).unwrap().permissions().mode() & 0o777, 0o700);
    }
}

#[test]
fn retention_preserves_unrelated_files_and_keeps_five_sessions() {
    let directory = tempfile::tempdir().unwrap();
    let recording = Recording::new(&directory.path().join("config.json"));
    recording.start().unwrap(); recording.stop();
    let unrelated = recording.directory.join("notes.txt"); fs::write(&unrelated, b"keep").unwrap();
    for _ in 0..7 { recording.start().unwrap(); recording.stop(); }
    assert_eq!(fs::read(&unrelated).unwrap(), b"keep");
    assert_eq!(fs::read_dir(&recording.directory).unwrap().filter_map(Result::ok).filter(|e| owned_name(&e.file_name().to_string_lossy())).count(), 5);
}

#[test]
fn full_and_unwritable_files_stop_recording_without_affecting_authentication() {
    let directory = tempfile::tempdir().unwrap();
    let recording = Recording::new(&directory.path().join("config.json"));
    recording.start().unwrap();
    let handle = active_writer(&recording);
    let mut writer = handle.lock().unwrap();
    let path = recording.directory.join(&writer.name);
    let padding = LIMIT - RESERVE - writer.bytes;
    writer.file.write_all(&vec![b'\n'; padding as usize]).unwrap(); writer.bytes += padding;
    writer.record(event());
    assert_eq!(writer.state, "limit");
    assert!(fs::metadata(&path).unwrap().len() <= LIMIT);
    assert!(fs::read_to_string(&path).unwrap().lines().last().unwrap().contains("size_limit"));
    drop(writer);
    recording.start().unwrap();
    let handle = active_writer(&recording);
    let mut current = handle.lock().unwrap();
    let path = recording.directory.join(&current.name);
    current.file = File::open(path).unwrap();
    current.record(event());
    assert_eq!(current.state, "error");
}

#[cfg(unix)]
#[test]
fn linked_recording_directories_are_rejected() {
    let directory = tempfile::tempdir().unwrap();
    let outside = tempfile::tempdir().unwrap();
    let recording = Recording::new(&directory.path().join("config.json"));
    std::os::unix::fs::symlink(outside.path(), &recording.directory).unwrap();
    assert!(recording.start().is_err());
    assert_eq!(fs::read_dir(outside.path()).unwrap().count(), 0);
}
