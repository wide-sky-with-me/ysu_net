from dataclasses import replace
from datetime import datetime
import json
import logging
from pathlib import Path
import random
import signal
import threading
import time
from types import SimpleNamespace

from .accounts import load_accounts
from .account_switching import AccountController
from .backend import run_backend
from .config import (
    clear_protection,
    credential_identity_hash,
    load_config,
    load_nosense,
    load_protection,
    load_schedule,
    night_pause_until,
    save_protection,
)
from .control import ControlServer
from .locking import exclusive_config


class NoSenseRenewer:
    CHECK_INTERVAL = 21600
    RETRY_INTERVAL = 1800

    def __init__(self, path, *, runner=run_backend, clock=time.monotonic):
        self.path = Path(path)
        self.runner = runner
        self.clock = clock
        self.next_check = 0.0
        self.blocked_credentials = None
        self.last_config = None
        self.next_check_by_user = {}
        self.blocked_by_user = {}
        self.last_config_by_user = {}

    def _targets(self, config, nosense):
        targets = []
        accounts_map = nosense.get("accounts") or {}
        used_macs = set()
        if config.username and config.password:
            rule = accounts_map.get(config.username)
            if isinstance(rule, dict):
                if rule.get("auto_renew"):
                    mac = rule.get("target_mac") or "current"
                    targets.append((config, mac, rule.get("service") or None))
                    used_macs.add(mac)
            elif nosense.get("auto_renew"):
                mac = nosense.get("target_mac") or "current"
                targets.append((config, mac, nosense.get("service") or None))
                used_macs.add(mac)
        if any(isinstance(v, dict) and v.get("auto_renew")
               for k, v in accounts_map.items() if k != config.username):
            try:
                book = load_accounts(self.path, config=config)
            except (OSError, ValueError):
                book = {"accounts": []}
            for entry in book.get("accounts", []):
                uname = entry.get("username", "")
                if (not entry.get("enabled") or not uname or not entry.get("password")
                        or uname == config.username):
                    continue
                rule = accounts_map.get(uname)
                if not isinstance(rule, dict) or not rule.get("auto_renew"):
                    continue
                mac = rule.get("target_mac") or ""
                if not mac or mac in used_macs:
                    continue
                used_macs.add(mac)
                acct_cfg = replace(
                    config,
                    username=uname,
                    password=entry["password"],
                    service=entry.get("service") or config.service,
                    backend=entry.get("backend") or config.backend,
                )
                targets.append((acct_cfg, mac, rule.get("service") or entry.get("service") or None))
        return targets

    def _step_one(self, acct_cfg, target_mac, service):
        uname = acct_cfg.username
        credentials = (uname, acct_cfg.password, acct_cfg.base, acct_cfg.cas_host)
        if self.blocked_by_user.get(uname) == credentials:
            return f"无感自动续约已暂停（{uname}）：账号认证需人工处理"
        state_key = (credentials, target_mac, service or "")
        now = self.clock()
        if self.last_config_by_user.get(uname) == state_key and now < self.next_check_by_user.get(uname, 0.0):
            return ""
        args = SimpleNamespace(
            action="renew",
            target=target_mac,
            service=service,
            yes=False,
            fresh=False,
        )
        result = self.runner(acct_cfg, "self", raw=True, args=args)
        self.last_config_by_user[uname] = state_key
        if result.code == 0:
            self.blocked_by_user.pop(uname, None)
            self.next_check_by_user[uname] = self.clock() + self.CHECK_INTERVAL
            try:
                payload = json.loads(result.output)
            except (ValueError, TypeError):
                return "无感认证已检查"
            expires = payload.get("expires", "") if isinstance(payload, dict) else ""
            if isinstance(payload, dict) and payload.get("renewed"):
                return f"无感认证已自动续约（到期 {expires}）" if expires else "无感认证已自动续约"
            return f"无感认证有效（到期 {expires}）" if expires else "无感认证有效"
        if result.code == 4:
            self.blocked_by_user[uname] = credentials
            self.next_check_by_user[uname] = self.clock() + self.CHECK_INTERVAL
            return "无感自动续约暂停：" + result.message
        self.next_check_by_user[uname] = self.clock() + self.RETRY_INTERVAL
        return "无感续约待重试：" + result.message

    def step(self, config):
        try:
            nosense = load_nosense(self.path)
        except (OSError, ValueError):
            return ""
        targets = self._targets(config, nosense)
        active_users = {cfg.username for cfg, _, _ in targets}
        for d in (self.next_check_by_user, self.last_config_by_user, self.blocked_by_user):
            for k in list(d):
                if k not in active_users:
                    d.pop(k, None)
        if not targets:
            self.next_check = 0.0
            self.last_config = None
            return ""
        messages = []
        for acct_cfg, target_mac, service in targets:
            msg = self._step_one(acct_cfg, target_mac, service)
            if acct_cfg.username == config.username:
                self.next_check = self.next_check_by_user.get(config.username, 0.0)
                self.last_config = self.last_config_by_user.get(config.username)
                self.blocked_credentials = self.blocked_by_user.get(config.username)
            if msg:
                messages.append(msg)
        return "；".join(messages)


class Reconnector:
    MAX_LOGIN_FAILURES = 3

    def __init__(self, runner=run_backend, jitter=random.uniform, *, path=None, now_fn=None, fallback_fn=None):
        self.runner = runner
        self.jitter = jitter
        self.path = Path(path) if path is not None else None
        self.now_fn = now_fn or (lambda: datetime.now().astimezone())
        self.fallback_fn = fallback_fn
        self.failures = 0
        self.login_failures = 0
        self.login_credentials = None
        self.blocked_credentials = None
        self.blocked_by_code4 = False
        self._was_paused = False
        self._hydrated = False

    def _sync_from_disk(self, config, credentials):
        if self.path is None or self._hydrated:
            return False
        self._hydrated = True
        persisted = load_protection(self.path)
        if persisted.get("corrupted"):
            return True
        if persisted["identity"] == credential_identity_hash(config):
            self.login_credentials = credentials
            self.login_failures = persisted["login_failures"]
            if persisted["blocked"]:
                self.blocked_credentials = credentials
                self.blocked_by_code4 = persisted.get("code4", False)
        return False

    def _persist(self, config, *, blocked, code4):
        if self.path is None:
            return
        try:
            save_protection(
                self.path,
                identity=credential_identity_hash(config),
                login_failures=self.login_failures,
                blocked=blocked,
                code4=code4,
            )
        except OSError:
            pass

    def _active_night_pause(self):
        if self.path is None:
            return None, None
        try:
            sched = load_schedule(self.path)
        except ValueError:
            return None, None
        now = self.now_fn()
        return now, night_pause_until(now, sched)

    def step(self, config):
        credentials = (config.username, config.password, config.service, config.backend)
        now, pause_until = self._active_night_pause()
        if pause_until is not None:
            self._was_paused = True
            wait = min(config.max_retry_interval, max(1.0, (pause_until - now).total_seconds()))
            return wait, f"夜间停网保护中（{pause_until:%H:%M} 恢复自动重连）"

        if self.path is not None:
            persisted = load_protection(self.path)
            if persisted.get("corrupted"):
                self.runner(config, "status")
                return config.max_retry_interval, "认证保护状态异常，已暂停自动提交；执行 ysu login 恢复"
            self._sync_from_disk(config, credentials)

        if self._was_paused:
            self._was_paused = False
            self.failures = 0
            self.login_failures = 0
            if not self.blocked_by_code4:
                self.blocked_credentials = None
                self._persist(config, blocked=False, code4=False)

        result = self.runner(config, "status")
        if result.code == 0:
            self.failures = 0
            self.login_failures = 0
            self.login_credentials = None
            self.blocked_credentials = None
            self.blocked_by_code4 = False
            if self.path is not None:
                clear_protection(self.path)
            return config.check_interval, "在线"
        if result.code == 1:
            if self.blocked_credentials == credentials:
                return config.max_retry_interval, "认证已暂停：修改配置或手动登录后恢复"
            if self.login_credentials != credentials:
                self.login_credentials = credentials
                self.login_failures = 0
                self.blocked_by_code4 = False
            prev_failures = self.login_failures
            self.login_failures = prev_failures + 1
            self._persist(
                config,
                blocked=self.login_failures >= self.MAX_LOGIN_FAILURES,
                code4=False,
            )
            result = self.runner(config, "login")
            if result.code == 0:
                self.failures = 0
                self.login_failures = 0
                self.blocked_credentials = None
                self.blocked_by_code4 = False
                if self.path is not None:
                    clear_protection(self.path)
                return config.check_interval, "重连成功"
            now_after, pause_after = self._active_night_pause()
            if pause_after is not None and result.code != 4:
                self._was_paused = True
                self.login_failures = prev_failures
                self._persist(config, blocked=False, code4=False)
                wait = min(config.max_retry_interval, max(1.0, (pause_after - now_after).total_seconds()))
                return wait, f"夜间停网保护中（{pause_after:%H:%M} 恢复自动重连）"
            if result.code == 4 and result.reason == "session_limit" and self.fallback_fn is not None:
                switched_msg = self.fallback_fn(config)
                if switched_msg:
                    self.failures = 0
                    self.login_failures = 0
                    self.login_credentials = None
                    self.blocked_credentials = None
                    self.blocked_by_code4 = False
                    if self.path is not None:
                        clear_protection(self.path)
                    return config.check_interval, switched_msg
            if result.code == 4 or self.login_failures >= self.MAX_LOGIN_FAILURES:
                self.blocked_credentials = credentials
                self.blocked_by_code4 = (result.code == 4)
                self._persist(config, blocked=True, code4=self.blocked_by_code4)
                message = result.message if result.code == 4 else (
                    f"{result.message}；连续重连失败已达 {self.MAX_LOGIN_FAILURES} 次，自动重连已暂停，请检查账号或网络后手动登录"
                )
                return config.max_retry_interval, message
        # Query failures never trigger login; both queries and transient login failures back off.
        self.failures = min(self.failures + 1, 20)
        delay = min(config.max_retry_interval, config.retry_interval * 2 ** (self.failures - 1))
        delay = min(config.max_retry_interval, delay + self.jitter(0, delay * 0.1))
        return delay, result.message


def run_daemon(config_file, *, once=False):
    config_file = Path(config_file)
    load_config(config_file)  # Validate before creating runtime files.
    with exclusive_config(config_file):
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
        stop = threading.Event()
        previous = {}
        for sig in (signal.SIGTERM, signal.SIGINT):
            previous[sig] = signal.signal(sig, lambda *_: stop.set())
        runner = lambda config, action, **kwargs: run_backend(config, action, stop_event=stop, **kwargs)
        accounts = AccountController(config_file, runner=runner, stop_event=stop)
        worker = Reconnector(
            runner=runner,
            path=config_file,
            fallback_fn=accounts.rotation.fallback_on_limit,
        )
        nosense = NoSenseRenewer(config_file, runner=runner)
        control = ControlServer(config_file, accounts.handle)
        last_message = None
        next_check = 0.0
        try:
            control.start()
            while not stop.is_set():
                control.consume()
                now = time.monotonic()
                if now < next_check:
                    stop.wait(min(0.25, next_check - now))
                    continue
                try:
                    current = load_config(config_file)
                    delay, message = worker.step(current)
                    if not worker._was_paused:
                        rotation_message = accounts.rotation.step()
                        if rotation_message:
                            message += "；" + rotation_message
                        nosense_message = nosense.step(current)
                        if nosense_message:
                            message += "；" + nosense_message
                except (ValueError, OSError):
                    delay, message = 30, "配置不可用，等待修复（未发起登录）"
                if message != last_message:
                    logging.info("%s；下次检查 %.0f 秒后", message, delay)
                    last_message = message
                if once:
                    return 0
                next_check = time.monotonic() + delay
        finally:
            control.close()
            for sig, handler in previous.items():
                signal.signal(sig, handler)
    return 0
