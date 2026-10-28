//! Headless live validation of the desktop's actual AuthClient, not a second protocol.
//! Decision: .agents/notes/implemented/desktop/2026-10-28-headless-auth-probe.md
use serde::Serialize;
use std::{io::{self, IsTerminal, Read}, time::Duration};
use ysu_auth::{AuthClient, AuthDiagnostic, AuthError, Config, Status};
use zeroize::Zeroizing;

const INPUT_LIMIT: u64 = 64 * 1024;

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
enum Action { Status, Login, Logout }

impl Action {
    fn parse(arguments: &[String]) -> Option<Self> {
        if arguments.len() != 1 { return None; }
        match arguments[0].as_str() {
            "status" => Some(Self::Status),
            "login" => Some(Self::Login),
            "logout" => Some(Self::Logout),
            _ => None,
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
enum Outcome {
    InvalidInput, Observed, Verified, ExpectedOffline, ExpectedOnline,
    IdentityMismatch, ServiceMismatch, PostconditionFailed, AuthError, Deadline,
}

#[derive(Clone, Copy, Serialize)]
#[serde(rename_all = "snake_case")]
enum Phase { Input, Before, Action, After }

#[derive(Debug, Serialize)]
struct Proof {
    online: bool,
    service: &'static str,
    owner_matches_config: bool,
    service_matches_config: bool,
}

impl Proof {
    fn from_status(status: &Status, config: &Config) -> Self {
        Self {
            online: status.online,
            service: match status.service.as_deref() {
                Some("校园网") => "campus",
                Some("中国移动") => "mobile",
                Some("中国联通") => "unicom",
                Some("中国电信") => "telecom",
                None => "absent",
                _ => "unknown",
            },
            owner_matches_config: status.online && !config.username.is_empty()
                && status.user == config.username,
            service_matches_config: status.online && status.service.as_deref() == Some(&config.service),
        }
    }
}

#[derive(Serialize)]
struct Report {
    schema: u8,
    action: Option<Action>,
    phase: Phase,
    outcome: Outcome,
    code: i32,
    before: Option<Proof>,
    after: Option<Proof>,
    diagnostic: Option<AuthDiagnostic>,
}

impl Report {
    fn new(action: Option<Action>) -> Self {
        Self { schema: 1, action, phase: Phase::Input, outcome: Outcome::InvalidInput, code: 2,
            before: None, after: None, diagnostic: None }
    }
    fn fail(&mut self, error: AuthError) {
        self.code = error.code;
        self.outcome = Outcome::AuthError;
        // Error.message may be free form in future callers; only fixed categories leave here.
        self.diagnostic = Some(error.diagnostic());
    }
}

fn decode(input: &[u8], action: Action) -> Option<Config> {
    if input.len() as u64 > INPUT_LIMIT { return None; }
    let config: Config = serde_json::from_slice(input).ok()?;
    config.validate().ok()?;
    if !config.verify_tls || (action != Action::Status
        && (config.username.is_empty() || config.password.is_empty())) {
        return None;
    }
    Some(config)
}

fn precondition(action: Action, before: &Proof) -> Option<Outcome> {
    match action {
        Action::Login if before.online => Some(Outcome::ExpectedOffline),
        Action::Logout if !before.online => Some(Outcome::ExpectedOnline),
        Action::Logout if !before.owner_matches_config => Some(Outcome::IdentityMismatch),
        Action::Logout if !before.service_matches_config => Some(Outcome::ServiceMismatch),
        _ => None,
    }
}

fn verified(action: Action, after: &Proof) -> bool {
    match action {
        Action::Login => after.online && after.owner_matches_config && after.service_matches_config,
        Action::Logout => !after.online,
        Action::Status => true,
    }
}

async fn execute(client: &AuthClient, config: &Config, action: Action, report: &mut Report) {
    report.phase = Phase::Before;
    let before = match client.status().await {
        Ok(status) => Proof::from_status(&status, config),
        Err(error) => { report.fail(error); return; }
    };
    let blocked = precondition(action, &before);
    let online = before.online;
    report.before = Some(before);
    if let Some(reason) = blocked {
        report.outcome = reason;
        report.code = 3;
        return;
    }
    if action == Action::Status {
        report.outcome = Outcome::Observed;
        report.code = if online { 0 } else { 1 };
        return;
    }
    report.phase = Phase::Action;
    let changed = match action {
        Action::Login => client.login().await,
        Action::Logout => client.logout().await,
        Action::Status => unreachable!(),
    };
    if let Err(error) = changed { report.fail(error); return; }
    // Every public status() creates a fresh Transport/Jar. A successful action
    // alone is insufficient evidence of the resulting connection state.
    report.phase = Phase::After;
    let after = match client.status().await {
        Ok(status) => Proof::from_status(&status, config),
        Err(error) => { report.fail(error); return; }
    };
    let passed = verified(action, &after);
    report.after = Some(after);
    report.outcome = if passed { Outcome::Verified } else { Outcome::PostconditionFailed };
    report.code = if passed { 0 } else { 3 };
}

#[tokio::main(flavor = "current_thread")]
async fn main() {
    let action = Action::parse(&std::env::args().skip(1).collect::<Vec<_>>());
    let mut report = Report::new(action);
    if let Some(action) = action.filter(|_| !io::stdin().is_terminal()) {
        let mut input = Zeroizing::new(Vec::new());
        if io::stdin().lock().take(INPUT_LIMIT + 1).read_to_end(&mut input).is_ok() {
            if let Some(config) = decode(&input, action) {
                let budget = Duration::from_secs(config.operation_timeout);
                match AuthClient::new(config.clone()) {
                    Ok(client) => {
                        if tokio::time::timeout(budget, execute(&client, &config, action, &mut report)).await.is_err() {
                            report.code = 2;
                            report.outcome = Outcome::Deadline;
                        }
                    }
                    Err(error) => report.fail(error),
                }
            }
        }
    }
    println!("{}", serde_json::to_string(&report).expect("only fixed JSON fields"));
    std::process::exit(report.code);
}

#[cfg(test)]
#[path = "support/auth_probe_tests.rs"]
mod tests;
