//! Decision: .agents/notes/proposals/accounts/2026-10-14-account-rotation.md
use crate::storage::{lock_file, read_json, write_json, Store};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::{collections::HashSet, fs::File};
use ysu_auth::Config;

const INVALID: &str = "账号簿格式无效，请检查账号设置";
const CONFLICT: &str = "账号或认证配置已变更，请重新查询后切换";
const LIMIT: usize = 32;

#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct Account {
    pub id: String,
    pub label: String,
    pub username: String,
    pub password: String,
    pub service: String,
    pub backend: String,
    pub enabled: bool,
}

impl Account {
    pub fn config(&self, base: &Config) -> Config {
        let mut config = base.clone();
        config.username = self.username.clone();
        config.password = self.password.clone();
        config.service = self.service.clone();
        config.backend = self.backend.clone();
        config
    }

    fn from_config(config: &Config) -> Self {
        Self {
            id: format!("{:032x}", rand::random::<u128>()),
            label: String::new(),
            username: config.username.clone(),
            password: config.password.clone(),
            service: config.service.clone(),
            backend: config.backend.clone(),
            enabled: true,
        }
    }

    fn validate(&self) -> Result<(), String> {
        if !saved_id(&self.id)
            || self.label.chars().count() > 80
            || self.label.chars().any(char::is_control)
            || self.username.trim().is_empty()
            || self.password.is_empty()
        {
            return Err(INVALID.into());
        }
        self.config(&Config::default())
            .validate()
            .map_err(|_| INVALID.to_owned())
    }
}

#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct AccountBook {
    pub version: u32,
    pub auto_switch: bool,
    pub accounts: Vec<Account>,
}

impl Default for AccountBook {
    fn default() -> Self {
        Self {
            version: 1,
            auto_switch: false,
            accounts: Vec::new(),
        }
    }
}

pub(crate) fn saved_id(id: &str) -> bool {
    id.len() == 32
        && id
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}

pub(crate) fn valid_id(id: &str) -> bool {
    id == "current" || saved_id(id)
}

pub(crate) fn identity(config: &Config) -> String {
    serde_json::to_string(&(
        &config.username,
        &config.password,
        &config.service,
        &config.backend,
        &config.base,
        &config.cas_host,
        config.verify_tls,
    ))
    .expect("serializable identity")
}

impl AccountBook {
    fn validate(&self) -> Result<(), String> {
        let mut ids = HashSet::new();
        let mut users = HashSet::new();
        if self.version != 1 || self.accounts.len() > LIMIT {
            return Err(INVALID.into());
        }
        for account in &self.accounts {
            account.validate()?;
            if !ids.insert(&account.id) || !users.insert(&account.username) {
                return Err(INVALID.into());
            }
        }
        if serde_json::to_vec_pretty(self)
            .map_err(|_| INVALID.to_owned())?
            .len()
            + 1
            > 64 * 1024
        {
            return Err("账号簿超过大小限制，请减少账号或字段长度".into());
        }
        Ok(())
    }

    fn overlay(&mut self, config: &Config) {
        if let Some(account) = self
            .accounts
            .iter_mut()
            .find(|a| a.username == config.username)
        {
            account.password = config.password.clone();
            account.service = config.service.clone();
            account.backend = config.backend.clone();
        }
    }

    fn remember_current(&mut self, config: &Config) -> Result<(), String> {
        if config.username.is_empty() || config.password.is_empty() {
            return Ok(());
        }
        self.overlay(config);
        if !self.accounts.iter().any(|a| a.username == config.username) {
            if self.accounts.len() >= LIMIT {
                return Err("账号簿已满，请先删除未使用的账号".into());
            }
            self.accounts.push(Account::from_config(config));
        }
        self.validate()
    }

    pub fn public(&self, config: &Config, environment_override: bool) -> Value {
        let mut accounts = self.accounts.clone();
        if !config.username.is_empty()
            && !config.password.is_empty()
            && !accounts.iter().any(|a| a.username == config.username)
        {
            let mut current = Account::from_config(config);
            current.id = "current".into();
            accounts.push(current);
        }
        let items: Vec<Value> = accounts.iter().map(|account| json!({
            "id":account.id, "label":account.label, "username":account.username,
            "service":account.service, "backend":account.backend, "enabled":account.enabled,
            "password_set":!account.password.is_empty(), "current":account.username == config.username,
        })).collect();
        json!({"items":items,"auto_switch":self.auto_switch,"environment_override":environment_override,
            "error":"", "quota":{"state":"unknown","message":"尚未读取当前账号的剩余流量"},
            "message":if self.auto_switch { "随自动重连检查剩余流量" } else { "流量自动换号已关闭" }})
    }

    pub fn passwords(&self) -> impl Iterator<Item = &str> {
        self.accounts.iter().map(|a| a.password.as_str())
    }
}

#[derive(Clone)]
pub(crate) struct AccountPlan {
    pub source: Config,
    pub target: Config,
    pub target_id: String,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct AccountChanges {
    id: Option<String>,
    #[serde(default)]
    label: String,
    username: String,
    #[serde(default)]
    password: String,
    service: String,
    backend: String,
    enabled: bool,
}

impl Store {
    pub fn environment_override(&self) -> bool {
        !self.demo
            && ["YSU_USER", "YSU_PASS", "YSU_SERVICE"]
                .iter()
                .any(|name| std::env::var_os(name).is_some())
    }

    fn accounts_lock(&self) -> Result<File, String> {
        let filename = self.path.file_name().ok_or(INVALID)?.to_string_lossy();
        lock_file(
            &self.path.with_file_name(format!("{filename}.write.lock")),
            true,
        )
    }

    pub fn load_accounts(&self, config: &Config) -> Result<AccountBook, String> {
        let mut book = match read_json(&self.path.with_extension("accounts.json"))? {
            None => AccountBook::default(),
            Some(value) => {
                serde_json::from_value::<AccountBook>(value).map_err(|_| INVALID.to_owned())?
            }
        };
        book.validate()?;
        book.overlay(config);
        if let Some(active) = book
            .accounts
            .iter()
            .find(|account| account.username == config.username)
        {
            active
                .validate()
                .map_err(|_| "活动账号凭据不完整，请先完善当前配置".to_owned())?;
        }
        Ok(book)
    }

    pub fn save_account(&self, value: Value) -> Result<(), String> {
        let changes: AccountChanges =
            serde_json::from_value(value).map_err(|_| INVALID.to_owned())?;
        let _lock = self.accounts_lock()?;
        let config = self.load_config(false)?;
        let mut book = self.load_accounts(&config)?;
        let previous = match changes.id.as_deref() {
            Some("current") if changes.username == config.username => book
                .accounts
                .iter()
                .find(|a| a.username == config.username)
                .cloned()
                .or_else(|| Some(Account::from_config(&config))),
            Some(id) => Some(
                book.accounts
                    .iter()
                    .find(|a| a.id == id)
                    .cloned()
                    .ok_or(CONFLICT)?,
            ),
            None => None,
        };
        if previous
            .as_ref()
            .is_some_and(|a| a.username != changes.username)
        {
            return Err("已保存账号的用户名保持不变，请新增另一个账号".into());
        }
        if book.accounts.iter().any(|a| {
            a.username == changes.username && previous.as_ref().is_none_or(|p| p.id != a.id)
        }) {
            return Err("此账号已保存，请编辑已有条目".into());
        }
        let active = changes.username == config.username;
        let account = Account {
            id: previous
                .as_ref()
                .map(|a| a.id.clone())
                .unwrap_or_else(|| format!("{:032x}", rand::random::<u128>())),
            label: changes.label.trim().into(),
            username: changes.username,
            password: if changes.password.is_empty() {
                previous
                    .as_ref()
                    .map(|a| a.password.clone())
                    .or_else(|| active.then(|| config.password.clone()))
                    .unwrap_or_default()
            } else {
                changes.password
            },
            service: changes.service,
            backend: changes.backend,
            enabled: changes.enabled,
        };
        account.validate()?;
        if let Some(index) = book.accounts.iter().position(|a| a.id == account.id) {
            book.accounts[index] = account.clone();
        } else {
            book.accounts.push(account.clone());
        }
        book.validate()?;
        // The active config is authoritative even if the following metadata write fails.
        if active {
            write_json(&self.path, &account.config(&config))?;
        }
        write_json(&self.path.with_extension("accounts.json"), &book)
    }

    pub fn delete_account(&self, id: &str) -> Result<(), String> {
        let _lock = self.accounts_lock()?;
        let config = self.load_config(false)?;
        let mut book = self.load_accounts(&config)?;
        let account = book.accounts.iter().find(|a| a.id == id).ok_or(CONFLICT)?;
        if account.username == config.username {
            return Err("请先切换到其他账号，再删除当前账号".into());
        }
        book.accounts.retain(|a| a.id != id);
        write_json(&self.path.with_extension("accounts.json"), &book)
    }

    pub fn save_rotation(&self, enabled: bool) -> Result<(), String> {
        let _lock = self.accounts_lock()?;
        let config = self.load_config(false)?;
        let mut book = self.load_accounts(&config)?;
        if enabled {
            if self.environment_override() {
                return Err("临时环境凭据覆盖期间暂停账号切换，请清除 YSU_* 覆盖后重试".into());
            }
            book.remember_current(&config)?;
            if config.username.is_empty()
                || config.password.is_empty()
                || book.accounts.iter().filter(|a| a.enabled).count() < 2
            {
                return Err("请先保存当前账号和至少一个启用的备用账号".into());
            }
        }
        book.auto_switch = enabled;
        write_json(&self.path.with_extension("accounts.json"), &book)
    }

    #[cfg(test)]
    pub fn prepare_account(&self, id: &str) -> Result<AccountPlan, String> {
        self.prepare_account_for(id, None)
    }

    pub fn prepare_account_for(
        &self,
        id: &str,
        expected: Option<&Config>,
    ) -> Result<AccountPlan, String> {
        if self.environment_override() {
            return Err("临时环境凭据覆盖期间暂停账号切换，请清除 YSU_* 覆盖后重试".into());
        }
        let _lock = self.accounts_lock()?;
        let source = self.load_config(false)?;
        if expected.is_some_and(|expected| identity(expected) != identity(&source)) {
            return Err("流量证据对应的活动账号已变化，本轮换号已停止".into());
        }
        let mut book = self.load_accounts(&source)?;
        book.remember_current(&source)?;
        let account = book
            .accounts
            .iter()
            .find(|a| {
                if id == "current" {
                    a.username == source.username
                } else {
                    a.id == id
                }
            })
            .filter(|a| a.enabled)
            .ok_or("目标账号已删除或停用")?;
        let plan = AccountPlan {
            source: source.clone(),
            target: account.config(&source),
            target_id: account.id.clone(),
        };
        write_json(&self.path.with_extension("accounts.json"), &book)?;
        Ok(plan)
    }

    pub fn account_plan_current(&self, plan: &AccountPlan) -> Result<(), String> {
        if self.environment_override() {
            return Err(CONFLICT.into());
        }
        let config = self.load_config(false)?;
        if identity(&config) != identity(&plan.source) {
            return Err(CONFLICT.into());
        }
        let book = self.load_accounts(&config)?;
        let account = book
            .accounts
            .iter()
            .find(|a| a.id == plan.target_id && a.enabled)
            .ok_or(CONFLICT)?;
        if identity(&account.config(&config)) != identity(&plan.target) {
            return Err(CONFLICT.into());
        }
        Ok(())
    }

    pub fn commit_account(&self, plan: &AccountPlan) -> Result<Config, String> {
        let _lock = self.accounts_lock()?;
        self.account_plan_current(plan)?;
        let latest = self.load_config(false)?;
        let mut selected = latest;
        selected.username = plan.target.username.clone();
        selected.password = plan.target.password.clone();
        selected.service = plan.target.service.clone();
        selected.backend = plan.target.backend.clone();
        selected.validate().map_err(|_| INVALID.to_owned())?;
        write_json(&self.path, &selected)?;
        Ok(selected)
    }
}

#[cfg(test)]
#[path = "accounts_tests.rs"]
mod tests;
