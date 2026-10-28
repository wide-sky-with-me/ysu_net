//! Decision: .agents/notes/proposals/accounts/2026-10-14-account-rotation.md
//! Decision: .agents/notes/implemented/accounts/2026-10-28-account-switch-validation.md
use super::*;
use crate::accounts::{identity, AccountBook, AccountPlan};
use std::collections::HashMap;

pub(super) fn account_state(store: &Store, config: &Config) -> (Value, Vec<String>) {
    match store.load_accounts(config) {
        Ok(book) => (
            book.public(config, store.environment_override()),
            book.passwords().map(str::to_owned).collect(),
        ),
        Err(error) => {
            let mut public = AccountBook::default().public(config, store.environment_override());
            public["error"] = error.into();
            public["message"] = "账号簿待修复，自动换号已暂停".into();
            (public, Vec::new())
        }
    }
}

fn unknown_quota(message: &str) -> Value {
    json!({"state":"unknown","message":message})
}

impl Runtime {
    pub(super) fn apply_accounts(
        &self,
        state: &mut State,
        config: Config,
        mut accounts: Value,
        passwords: Vec<String>,
    ) {
        state.remember(&config.password);
        for password in passwords {
            state.remember(&password);
        }
        if identity(&state.config) == identity(&config) {
            accounts["quota"] = state.accounts["quota"].clone();
            if accounts["auto_switch"] == state.accounts["auto_switch"] {
                accounts["message"] = state.accounts["message"].clone();
            }
        } else {
            state.info = Value::Null;
        }
        if let Some(intent) = state.rotation_intent {
            accounts["auto_switch"] = intent.into();
        }
        let enabled = accounts["auto_switch"].as_bool().unwrap_or(false)
            && accounts["error"] == ""
            && accounts["environment_override"] == false;
        self.rotation_enabled.store(enabled, Ordering::Release);
        if !enabled {
            accounts["message"] = if accounts["environment_override"] == true {
                "临时环境凭据覆盖期间暂停自动换号"
            } else {
                "流量自动换号已关闭"
            }
            .into();
        }
        state.config = config;
        state.accounts = accounts;
    }

    pub(super) async fn change_accounts(
        &self,
        command: &str,
        args: Value,
    ) -> Result<Value, String> {
        if let Some(password) = args.get("password").and_then(Value::as_str) {
            self.update(|state| state.remember(password));
        }
        let result = {
            let _settings = self.setting_guard().await?;
            let store = self.store.clone();
            let deleting = command == "delete_account";
            self.blocking(move || {
                if deleting {
                    store.delete_account(args["id"].as_str().unwrap())
                } else {
                    store.save_account(args)
                }
            })
            .await
        };
        // A partial metadata failure must still reflect the authoritative active config.
        self.config().await?;
        result?;
        self.update(|state| state.log("success", "账号簿已保存"));
        self.wake();
        Ok(self.snapshot())
    }

    pub(super) async fn set_rotation(&self, enabled: bool) -> Result<Value, String> {
        let mut version = 0;
        self.update(|state| {
            version = self.rotation_version.fetch_add(1, Ordering::AcqRel) + 1;
            if !enabled {
                self.rotation_enabled.store(false, Ordering::Release);
                state.rotation_intent = Some(false);
                state.accounts["auto_switch"] = false.into();
                state.accounts["message"] = "流量自动换号已关闭".into();
            }
        });
        self.wake();
        {
            let _settings = self.setting_guard().await?;
            if self.rotation_version.load(Ordering::Acquire) != version {
                return Ok(self.snapshot());
            }
            let store = self.store.clone();
            self.blocking(move || store.save_rotation(enabled)).await?;
            self.update(|state| {
                if self.rotation_version.load(Ordering::Acquire) == version {
                    state.rotation_intent = None;
                }
            });
        }
        self.config().await?;
        if enabled && self.rotation_version.load(Ordering::Acquire) == version {
            self.set_desired(true).await?;
        }
        self.wake();
        Ok(self.snapshot())
    }
}

pub(super) struct Rotation {
    next_check: Instant,
    zero: Option<(String, Instant)>,
    cooling: HashMap<String, (String, Instant)>,
}
impl Default for Rotation {
    fn default() -> Self {
        Self {
            next_check: Instant::now(),
            zero: None,
            cooling: HashMap::new(),
        }
    }
}
impl Rotation {
    pub(super) fn clear_zero(&mut self) {
        self.zero = None;
    }
    fn cool(&mut self, config: &Config) {
        self.cooling.insert(
            config.username.clone(),
            (identity(config), Instant::now() + Duration::from_secs(900)),
        );
    }
    fn eligible(&self, config: &Config) -> bool {
        self.cooling
            .get(&config.username)
            .is_none_or(|(previous, until)| {
                *previous != identity(config) || Instant::now() >= *until
            })
    }
}

impl Worker {
    async fn plan_current(&self, plan: &AccountPlan) -> Result<(), String> {
        let store = self.runtime.store.clone();
        let plan = plan.clone();
        self.runtime
            .blocking(move || store.account_plan_current(&plan))
            .await
    }

    async fn source_current(&self, plan: &AccountPlan) -> bool {
        // Recovery must preserve newer source and candidate intentions.
        self.plan_current(plan).await.is_ok()
    }

    async fn restore_account(&self, plan: &AccountPlan, original: &Status) -> bool {
        if !original.online || !self.source_current(plan).await {
            return false;
        }
        let Ok(current) = self.status(&plan.source).await else {
            return false;
        };
        if current.online && current.user == original.user && current.service == original.service {
            return true;
        }
        if current.online {
            if current.user != plan.target.username {
                return false;
            }
            if self
                .runtime
                .backend
                .mutate(&plan.target, &Action::Logout)
                .await
                .is_err()
            {
                return false;
            }
            if !self
                .status(&plan.target)
                .await
                .is_ok_and(|status| !status.online)
            {
                return false;
            }
        }
        if !self.source_current(plan).await {
            return false;
        }
        let mut restore = plan.source.clone();
        let Some(service) = original.service.as_ref() else {
            return false;
        };
        restore.service = service.clone();
        if self
            .runtime
            .backend
            .mutate(&restore, &Action::Login)
            .await
            .is_err()
        {
            return false;
        }
        self.status(&restore).await.is_ok_and(|status| {
            status.online && status.user == original.user && status.service == original.service
        })
    }

    pub(super) async fn switch_account(
        &mut self,
        id: &str,
        automatic: bool,
    ) -> Result<bool, String> {
        self.switch_account_bound(id, automatic, None).await
    }

    async fn switch_account_bound(
        &mut self,
        id: &str,
        automatic: bool,
        expected: Option<Config>,
    ) -> Result<bool, String> {
        let _temporary = if self.guard.is_none() {
            Some(self.acquire().await.map_err(|error| {
                self.runtime.update(|state| {
                    state.auto = json!({"state":"external","message":EXTERNAL});
                });
                error
            })?)
        } else {
            None
        };
        self.busy("正在切换账号并核验实际连接");
        let store = self.runtime.store.clone();
        let id = id.to_owned();
        let plan = self
            .runtime
            .blocking(move || store.prepare_account_for(&id, expected.as_ref()))
            .await?;
        self.runtime.update(|state| {
            state.remember(&plan.source.password);
            state.remember(&plan.target.password);
            state.info = Value::Null;
        });
        if !automatic {
            self.rotation.cooling.remove(&plan.target.username);
            self.rotation.zero = None;
        }
        self.phase = DiagnosticStage::OnlineState;
        let original = self
            .status(&plan.source)
            .await
            .map_err(|_| "连接状态未知，未切换账号".to_owned())?;
        if original.online && (original.user != plan.source.username || original.service.is_none())
        {
            return Err("当前在线账号与活动配置不一致，未下线或切换".into());
        }
        self.plan_current(&plan).await?;
        let result: Result<(), String> = async {
            if !(original.online
                && original.user == plan.target.username
                && original.service.as_deref() == Some(&plan.target.service))
            {
                if original.online {
                    let mut leaving = plan.source.clone();
                    leaving.service = original.service.clone().unwrap();
                    self.phase = DiagnosticStage::OfflineSubmit;
                    let result = self.runtime.backend.mutate(&leaving, &Action::Logout).await;
                    if let Err(error) = &result {
                        self.error(error);
                    }
                    self.phase = DiagnosticStage::Verification;
                    let observed = self.status(&leaving).await;
                    if result.is_err() || !observed.is_ok_and(|status| !status.online) {
                        return Err("原账号下线未确认，已停止切换".into());
                    }
                }
                self.plan_current(&plan).await?;
                if automatic
                    && (!self.runtime.desired.load(Ordering::Acquire)
                        || !self.runtime.rotation_enabled.load(Ordering::Acquire))
                {
                    return Err("自动换号已停止，请重新查询实际状态".into());
                }
                self.phase = DiagnosticStage::OnlineState;
                let before = self
                    .status(&plan.target)
                    .await
                    .map_err(|_| "登录前连接状态未知".to_owned())?;
                if before.online {
                    return Err("切换期间连接发生变化，已停止登录".into());
                }
                self.phase = DiagnosticStage::UserOnline;
                let result = self
                    .runtime
                    .backend
                    .mutate(&plan.target, &Action::Login)
                    .await;
                if let Err(error) = &result {
                    self.error(error);
                }
                self.phase = DiagnosticStage::Verification;
                let verified = self.status(&plan.target).await;
                if result.is_err()
                    || !verified.is_ok_and(|status| {
                        status.online
                            && status.user == plan.target.username
                            && status.service.as_deref() == Some(&plan.target.service)
                    })
                {
                    return Err("目标账号连接未独立确认".into());
                }
            }
            self.phase = DiagnosticStage::Config;
            let store = self.runtime.store.clone();
            let plan = plan.clone();
            self.runtime
                .blocking(move || store.commit_account(&plan))
                .await?;
            self.runtime.config().await?;
            Ok(())
        }
        .await;
        if let Err(error) = result {
            self.rotation.cool(&plan.target);
            self.phase = DiagnosticStage::Recovery;
            if self.restore_account(&plan, &original).await {
                self.runtime
                    .update(|state| state.log("info", "账号切换失败，已独立确认恢复原连接"));
            } else {
                self.runtime
                    .update(|state| state.log("error", "账号切换未确认，请核对当前实际连接"));
            }
            return Err(error);
        }
        self.reconnect = Reconnect::default();
        self.rotation.zero = None;
        self.runtime.update(|state| {
            state.info = Value::Null;
            state.accounts["quota"] = unknown_quota("账号已切换，等待查询新的剩余流量");
            state.accounts["message"] = "已独立确认切换账号".into();
            state.log("success", "已独立确认账号及运营商，活动配置已保存");
        });
        Ok(true)
    }

    pub(super) async fn rotate_if_needed(&mut self, config: &Config, status: &Status) -> bool {
        if !self.runtime.rotation_enabled.load(Ordering::Acquire)
            || !self.runtime.desired.load(Ordering::Acquire)
            || Instant::now() < self.rotation.next_check
        {
            return false;
        }
        self.rotation.next_check =
            Instant::now() + Duration::from_secs(config.check_interval.max(60));
        if !status.online
            || status.user != config.username
            || status.service.as_deref() != Some(&config.service)
        {
            self.rotation.zero = None;
            self.runtime.update(|state| {
                state.accounts["quota"] = unknown_quota("账号或服务不一致，未发起流量换号");
            });
            return false;
        }
        let result = self.runtime.backend.verified_info(config).await;
        let latest = self.runtime.config().await;
        let info = match result {
            Ok(info) if latest.is_ok_and(|latest| identity(&latest) == identity(config)) => info,
            _ => {
                self.rotation.zero = None;
                self.runtime.update(|state| {
                    state.info = Value::Null;
                    state.accounts["quota"] = unknown_quota("流量查询或身份核验失败，保留当前账号");
                });
                let _ = self.status(config).await;
                return false;
            }
        };
        let quota = info
            .get("quota")
            .filter(|quota| {
                quota.get("state").and_then(Value::as_str).is_some_and(|s| {
                    ["unknown", "available", "zero_reported", "unlimited"].contains(&s)
                }) && quota.get("message").is_some_and(Value::is_string)
            })
            .cloned()
            .unwrap_or_else(|| unknown_quota("门户未提供可识别的剩余流量"));
        self.runtime.update(|state| {
            state.info = normalize_info(&info).unwrap_or(Value::Null);
            state.accounts["quota"] = quota.clone();
        });
        if quota["state"] != "zero_reported" {
            self.rotation.zero = None;
            if quota["state"] == "available" || quota["state"] == "unlimited" {
                self.rotation.cooling.remove(&config.username);
            }
            return false;
        }
        let key = format!(
            "{}:{}:{}",
            self.runtime.rotation_version.load(Ordering::Acquire),
            self.runtime.auto_version.load(Ordering::Acquire),
            identity(config)
        );
        let confirmed = self.rotation.zero.as_ref().is_some_and(|(previous, when)| {
            *previous == key
                && when.elapsed() >= Duration::from_secs(60)
                && when.elapsed()
                    <= Duration::from_secs(config.check_interval.saturating_mul(2).max(120))
        });
        if !confirmed {
            self.rotation.zero = Some((key, Instant::now()));
            self.runtime.update(|state| {
                state.accounts["message"] = "门户报告零剩余流量，等待下一次独立确认".into();
            });
            return false;
        }
        let store = self.runtime.store.clone();
        let config_copy = config.clone();
        let Ok(book) = self
            .runtime
            .blocking(move || store.load_accounts(&config_copy))
            .await
        else {
            self.rotation.zero = None;
            return false;
        };
        let position = book
            .accounts
            .iter()
            .position(|account| account.username == config.username)
            .unwrap_or(book.accounts.len().saturating_sub(1));
        let target = (1..=book.accounts.len())
            .filter_map(|offset| book.accounts.get((position + offset) % book.accounts.len()))
            .find(|account| {
                account.enabled
                    && !account.password.is_empty()
                    && account.username != config.username
                    && self.rotation.eligible(&account.config(config))
            })
            .cloned();
        let Some(target) = target else {
            self.runtime.update(|state| {
                state.accounts["message"] = "备用账号均已停用或处于冷却，等待后续检查".into();
            });
            return false;
        };
        if !self.runtime.rotation_enabled.load(Ordering::Acquire)
            || !self.runtime.desired.load(Ordering::Acquire)
        {
            return false;
        }
        self.rotation.cool(config);
        self.runtime.update(|state| {
            state.accounts["message"] = "连续两次报告零剩余流量，正在切换备用账号".into();
        });
        if let Err(error) = self
            .switch_account_bound(&target.id, true, Some(config.clone()))
            .await
        {
            self.rotation.cool(&target.config(config));
            self.runtime.update(|state| {
                state.accounts["message"] = "备用账号切换未确认，已进入冷却".into();
                state.log("error", &error);
            });
        }
        true
    }
}

impl Backend {
    pub(super) async fn verified_info(&self, config: &Config) -> Result<Value, AuthError> {
        match self {
            Self::Native(recording) => {
                AuthClient::new(config.clone())?
                    .with_trace(recording.trace())
                    .verified_info()
                    .await
            }
            Self::Demo(_) => {
                let before = self.status(config).await?;
                let info = self.info(config).await?.info;
                let after = self.status(config).await?;
                if !before.online
                    || before.user != config.username
                    || before.service.as_deref() != Some(&config.service)
                    || before.user != after.user
                    || before.service != after.service
                    || !after.online
                {
                    return Err(AuthError::new(2, "fixture account identity changed"));
                }
                let mut info = info;
                #[cfg(test)]
                if let Self::Demo(demo) = self {
                    if let Some(quota) = demo.lock().unwrap().quota.clone() {
                        info["quota"] = quota;
                    }
                }
                if info.get("quota").is_none() {
                    info["quota"] =
                        json!({"state":"available","message":"门户报告剩余流量 12.5 GB"});
                }
                Ok(info)
            }
        }
    }
}

#[cfg(test)]
#[path = "account_runtime_tests.rs"]
mod tests;
