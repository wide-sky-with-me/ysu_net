//! Passive observations share the authentication worker, but never its reconnect policy.
//! Decision: .agents/notes/implemented/desktop/2026-10-27-passive-state-observation.md
use super::*;

const OBSERVE_INTERVAL: Duration = Duration::from_secs(30);
const OBSERVE_BUDGET: Duration = Duration::from_secs(2);
const OBSERVE_BACKOFF_MAX: u64 = 300;
const OBSERVE_LOG_INTERVAL: Duration = Duration::from_secs(60);

#[derive(Clone, PartialEq, Eq)]
pub(super) struct StatusIdentity {
    user: String,
    service: Option<String>,
    ip: String,
}

impl StatusIdentity {
    fn from_status(status: &Status) -> Self {
        Self {
            user: status.user.clone(),
            service: status.service.clone(),
            ip: status.ip.clone(),
        }
    }

    fn from_value(status: &Value) -> Option<Self> {
        (status["online"] == true).then(|| Self {
            user: status["user"].as_str().unwrap_or_default().into(),
            service: status["service"].as_str().map(str::to_owned),
            ip: status["ip"].as_str().unwrap_or_default().into(),
        })
    }
}

pub(super) struct Observation {
    next_periodic: Instant,
    request_after: Instant,
    requested: bool,
    failures: u32,
    last_error_log: Option<Instant>,
    #[cfg(test)]
    gate_deferrals: Arc<AtomicU64>,
}

impl Observation {
    pub(super) fn new(now: Instant) -> Self {
        Self {
            next_periodic: now + OBSERVE_INTERVAL,
            request_after: now,
            requested: false,
            failures: 0,
            last_error_log: None,
            #[cfg(test)]
            gate_deferrals: Arc::new(AtomicU64::new(0)),
        }
    }

    pub(super) fn request(&mut self) {
        self.requested = true;
    }

    pub(super) fn sample_started(&mut self) {
        self.requested = false;
    }

    fn admission_deferred(&mut self, now: Instant) {
        // An occupied gate must not leave a past-due timer spinning. Keep any pending
        // advisory request, without changing business state or reconnect's deadline.
        let retry = now + OBSERVE_BUDGET;
        self.next_periodic = self.next_periodic.max(retry);
        self.request_after = self.request_after.max(retry);
        #[cfg(test)]
        self.gate_deferrals.fetch_add(1, Ordering::AcqRel);
    }

    pub(super) fn deadline(&self, automatic: bool, next_auto: Instant) -> Instant {
        let due = if self.requested {
            self.next_periodic.min(self.request_after)
        } else {
            self.next_periodic
        };
        // Reuse a near-due automatic sample; never advance or reset reconnect's deadline.
        if automatic && next_auto <= due + OBSERVE_BUDGET {
            due.max(next_auto + OBSERVE_BUDGET)
        } else {
            due
        }
    }

    fn sampled(&mut self, now: Instant, success: bool) {
        if success {
            self.failures = 0;
            self.next_periodic = now + OBSERVE_INTERVAL;
            self.request_after = now + OBSERVE_BUDGET;
        } else {
            self.failures = self.failures.saturating_add(1).min(4);
            let seconds = (30u64 << self.failures).min(OBSERVE_BACKOFF_MAX);
            self.next_periodic = now + Duration::from_secs(seconds);
            // Advisory focus/network events may recover sooner than background backoff,
            // but failed requests are still limited to the healthy observation cadence.
            // This does not clear failures or advance automatic authentication/rotation.
            self.request_after = now + OBSERVE_INTERVAL;
        }
    }

    fn log_error(&mut self, now: Instant) -> bool {
        if self
            .last_error_log
            .is_some_and(|last| now.duration_since(last) < OBSERVE_LOG_INTERVAL)
        {
            return false;
        }
        self.last_error_log = Some(now);
        true
    }
}

impl State {
    fn accept_observed_status(&mut self, status: &Status) {
        if status.online {
            let identity = StatusIdentity::from_status(status);
            let previous =
                StatusIdentity::from_value(&self.status).or_else(|| self.observed_identity.clone());
            if previous
                .as_ref()
                .is_some_and(|previous| previous != &identity)
            {
                self.info = Value::Null;
                self.info_error.clear();
            } else if self.info["online"] == false {
                self.info = Value::Null;
            }
            // Retain the last confirmed identity through an unknown result so an old read
            // error survives same-identity recovery, but not a different account/service/IP.
            self.observed_identity = Some(identity);
        } else {
            self.info = json!({"online":false, "fields":[], "items":[]});
            self.info_error.clear();
        }
        self.status = serde_json::to_value(status).expect("serializable status");
        self.status["message"] = if status.online {
            "校园网已连接"
        } else {
            "校园网未连接"
        }
        .into();
    }
}

impl Worker {
    pub(super) fn publish_status(&self, result: &Result<Status, AuthError>, passive: bool) {
        let now = Instant::now();
        let log_error = {
            let mut observation = self.observation.lock().unwrap();
            observation.sampled(now, result.is_ok());
            result.is_err() && (!passive || observation.log_error(now))
        };
        self.runtime.update(|state| match result {
            Ok(status) => state.accept_observed_status(status),
            Err(error) => {
                let message = self.error_message(error);
                state.status =
                    json!({"online":null, "service":null, "user":"", "ip":"", "message":message});
                state.info = Value::Null;
                if log_error {
                    state.log("error", &message);
                }
            }
        });
    }

    pub(super) async fn observe(&mut self) {
        let Ok(_work) = self.runtime.begin_auth() else {
            self.observation
                .lock()
                .unwrap()
                .admission_deferred(Instant::now());
            return;
        };
        self.observation.lock().unwrap().sample_started();
        self.action = "observe";
        self.phase = DiagnosticStage::OnlineState;
        self.runtime.recording.task(self.action, self.phase, None);
        // Cached config avoids settings IO/migration and cannot change the saved identity.
        // Passive reads always use the public API, even when authentication uses a browser:
        // the browser status path starts Chromium and cannot fit this silent read budget.
        let mut config = self.runtime.state.lock().unwrap().config.clone();
        config.backend = "api".into();
        let budget = OBSERVE_BUDGET.min(Duration::from_secs(config.operation_timeout));
        let mut stop = self.stop.clone();
        let result = tokio::select! {
            biased;
            _ = stop.changed() => return,
            result = tokio::time::timeout(budget, self.runtime.backend.status(&config)) => {
                result.unwrap_or_else(|_| Err(local_auth_error(
                    2,
                    DiagnosticOperation::Status,
                    DiagnosticStage::OnlineState,
                    DiagnosticReason::Deadline,
                )))
            }
        };
        self.publish_status(&result, true);
    }
}

#[cfg(test)]
#[path = "runtime_observer_tests.rs"]
mod tests;
