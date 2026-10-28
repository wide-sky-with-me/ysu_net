//! Opt-in, typed tracing. Raw URLs, messages, headers and payloads never enter events.
//! Decision: .agents/notes/implemented/desktop/2026-10-28-opt-in-auth-recording.md
use crate::{AuthDiagnostic, AuthError, DiagnosticOperation, DiagnosticStage, NavigationDiagnostic};
use serde::Serialize;
use std::{error::Error, future::Future, sync::{Arc, atomic::{AtomicU64, Ordering}}, time::Instant};

#[derive(Clone, Copy, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum TraceOutcome { Success, Failed, Cancelled }

#[derive(Clone, Copy, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum NetworkPhase { Send, ReadBody }

#[derive(Clone, Copy, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum NetworkClass { Timeout, Connect, Decode, Body, Request, Other }

#[derive(Clone, Copy, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum IoClass { Refused, Reset, Aborted, NotConnected, TimedOut, UnexpectedEof, Other }

#[derive(Clone, Copy, Serialize)]
pub struct NetworkFailure {
    phase: NetworkPhase,
    class: NetworkClass,
    io_class: Option<IoClass>,
    os_code: Option<i32>,
}
impl NetworkFailure {
    fn capture(error: &reqwest::Error, phase: NetworkPhase) -> Self {
        let class = if error.is_timeout() { NetworkClass::Timeout }
            else if error.is_connect() { NetworkClass::Connect }
            else if error.is_decode() { NetworkClass::Decode }
            else if error.is_body() { NetworkClass::Body }
            else if error.is_request() { NetworkClass::Request }
            else { NetworkClass::Other };
        let mut cause: Option<&(dyn Error + 'static)> = Some(error);
        let mut io = None;
        // Bound traversal even if a third-party error implementation has a cyclic source.
        for _ in 0..16 {
            let Some(current) = cause else { break };
            if let Some(value) = current.downcast_ref::<std::io::Error>() { io = Some(value); break; }
            cause = current.source();
        }
        let io_class = io.map(|value| match value.kind() {
            std::io::ErrorKind::ConnectionRefused => IoClass::Refused,
            std::io::ErrorKind::ConnectionReset => IoClass::Reset,
            std::io::ErrorKind::ConnectionAborted => IoClass::Aborted,
            std::io::ErrorKind::NotConnected => IoClass::NotConnected,
            std::io::ErrorKind::TimedOut => IoClass::TimedOut,
            std::io::ErrorKind::UnexpectedEof => IoClass::UnexpectedEof,
            _ => IoClass::Other,
        });
        Self { phase, class, io_class, os_code: io.and_then(std::io::Error::raw_os_error) }
    }
}

#[derive(Serialize)]
#[serde(tag = "event", rename_all = "snake_case")]
pub enum TraceEvent {
    OperationStarted { browser: bool, verify_tls: bool, timeout_secs: u64 },
    OperationFinished { outcome: TraceOutcome, code: Option<i32>, diagnostic: Option<AuthDiagnostic> },
    Stage { stage: DiagnosticStage },
    OnlineState { online: bool, service_known: bool },
    RequestStarted { request: u64, endpoint: NavigationDiagnostic, post: bool },
    ResponseHeaders { request: u64, status: u16 },
    RequestFinished { request: u64, outcome: TraceOutcome, bytes: usize, failure: Option<NetworkFailure> },
    Navigation { navigation: NavigationDiagnostic },
    BrowserDocument { endpoint: NavigationDiagnostic, status: Option<u16>, failed: bool },
}

#[derive(Serialize)]
pub struct TraceRecord {
    pub operation_id: u64,
    pub operation: DiagnosticOperation,
    pub elapsed_ms: u64,
    #[serde(flatten)]
    pub event: TraceEvent,
}

type Sink = Arc<dyn Fn(TraceRecord) + Send + Sync>;
#[derive(Clone, Default)]
pub struct Trace {
    sink: Option<Sink>,
    ids: Arc<AtomicU64>,
}

tokio::task_local! { static CURRENT: Context; }

impl Trace {
    pub fn new(sink: impl Fn(TraceRecord) + Send + Sync + 'static) -> Self {
        Self { sink: Some(Arc::new(sink)), ids: Arc::new(AtomicU64::new(0)) }
    }
    pub(crate) async fn run<T>(&self, operation: DiagnosticOperation, browser: bool, verify_tls: bool,
        timeout_secs: u64, future: impl Future<Output = Result<T, AuthError>>) -> Result<T, AuthError> {
        let Some(sink) = &self.sink else { return future.await };
        let context = Context(Some(Arc::new(Inner { sink: sink.clone(), operation,
            id: self.ids.fetch_add(1, Ordering::Relaxed) + 1, start: Instant::now(), requests: AtomicU64::new(0) })));
        context.emit(TraceEvent::OperationStarted { browser, verify_tls, timeout_secs });
        let mut guard = OperationGuard { context: context.clone(), finished: false };
        let result = CURRENT.scope(context, future).await;
        guard.context.emit(TraceEvent::OperationFinished {
            outcome: if result.is_ok() { TraceOutcome::Success } else { TraceOutcome::Failed },
            code: result.as_ref().err().map(|e| e.code),
            diagnostic: result.as_ref().err().map(AuthError::diagnostic),
        });
        guard.finished = true;
        result
    }
}

struct Inner { sink: Sink, operation: DiagnosticOperation, id: u64, start: Instant, requests: AtomicU64 }
#[derive(Clone, Default)]
pub(crate) struct Context(Option<Arc<Inner>>);
impl Context {
    pub(crate) fn current() -> Self { CURRENT.try_with(Clone::clone).unwrap_or_default() }
    pub(crate) fn emit(&self, event: TraceEvent) {
        if let Some(inner) = &self.0 {
            (inner.sink)(TraceRecord { operation_id: inner.id, operation: inner.operation,
                elapsed_ms: inner.start.elapsed().as_millis().min(u64::MAX as u128) as u64, event });
        }
    }
    pub(crate) fn stage(&self, stage: DiagnosticStage) { self.emit(TraceEvent::Stage { stage }); }
    pub(crate) fn request(&self, endpoint: NavigationDiagnostic, post: bool) -> RequestGuard {
        let id = self.0.as_ref().map(|i| i.requests.fetch_add(1, Ordering::Relaxed) + 1).unwrap_or(0);
        self.emit(TraceEvent::RequestStarted { request: id, endpoint, post });
        RequestGuard { context: self.clone(), id, bytes: 0, failure: None, finished: false }
    }
}
struct OperationGuard { context: Context, finished: bool }
impl Drop for OperationGuard {
    fn drop(&mut self) {
        if !self.finished { self.context.emit(TraceEvent::OperationFinished {
            outcome: TraceOutcome::Cancelled, code: None, diagnostic: None }); }
    }
}
pub(crate) struct RequestGuard {
    context: Context, id: u64, pub(crate) bytes: usize, failure: Option<NetworkFailure>, finished: bool,
}
impl RequestGuard {
    pub(crate) fn network<T>(&mut self, result: Result<Result<T, reqwest::Error>, AuthError>, phase: NetworkPhase) -> Result<T, AuthError> {
        match result {
            Ok(Ok(value)) => Ok(value),
            Ok(Err(error)) => {
                self.failure = Some(NetworkFailure::capture(&error, phase));
                Err(crate::transport::network_error(error))
            }
            Err(error) => {
                self.failure = Some(NetworkFailure { phase, class: NetworkClass::Timeout, io_class: None, os_code: None });
                Err(error)
            }
        }
    }
    pub(crate) fn headers(&self, status: u16) { self.context.emit(TraceEvent::ResponseHeaders { request: self.id, status }); }
    pub(crate) fn finish<T>(&mut self, result: &Result<T, AuthError>) {
        self.context.emit(TraceEvent::RequestFinished { request: self.id,
            outcome: if result.is_ok() { TraceOutcome::Success } else { TraceOutcome::Failed },
            bytes: self.bytes, failure: self.failure });
        self.finished = true;
    }
}
impl Drop for RequestGuard {
    fn drop(&mut self) {
        if !self.finished { self.context.emit(TraceEvent::RequestFinished { request: self.id,
            outcome: TraceOutcome::Cancelled, bytes: self.bytes, failure: self.failure }); }
    }
}

#[cfg(test)]
#[path = "trace_tests.rs"]
mod tests;
