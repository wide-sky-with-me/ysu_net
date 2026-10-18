"""Verified account transitions and conservative portal-zero rotation.

Decision: .agents/notes/proposals/accounts/2026-10-14-account-rotation.md
"""
from dataclasses import dataclass, replace
import json
from pathlib import Path
import time

from ysu_net.auth.common import QueryError, online_service, online_state
from .accounts import (CREDENTIAL_FIELDS, candidate_signature, commit_switch,
                       environment_override, load_accounts, prepare_switch,
                       source_signature, unchanged_switch)
from .backend import run_backend
from .config import load_config


@dataclass(frozen=True)
class AccountSwitchResult:
    code: int
    message: str
    previous: str | None = None
    restored: bool = False
    committed: bool = False


class _Failure(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class _Budget:
    def __init__(self, config, runner, clock, stop_event=None, timeout=None):
        self.runner = runner
        self.clock = clock
        self.stop_event = stop_event
        self.deadline = clock() + min(config.operation_timeout,
                                     config.operation_timeout if timeout is None else max(0, timeout))

    def check(self):
        if self.stop_event is not None and self.stop_event.is_set():
            raise _Failure(130, "操作已取消，连接状态未确认")
        remaining = self.deadline - self.clock()
        if remaining <= 0:
            raise _Failure(2, "共同操作预算已用尽，连接状态未确认")
        return remaining

    def run(self, config, action, **kwargs):
        remaining = self.check()
        bounded = replace(config, operation_timeout=remaining)
        result = self.runner(bounded, action, **kwargs)
        self.check()
        if result.code == 130:
            raise _Failure(130, "操作已取消，连接状态未确认")
        return result


def _bound_online(payload):
    online = online_state(payload)
    if not online:
        return None
    service = online_service(payload)
    info = payload["data"]["portalOnlineUserInfo"]
    if any(key in info and info[key] != service for key in ("realServiceName", "service")):
        raise QueryError("unknown or conflicting raw service")
    owner = info["userId"] if "userId" in info else info.get("userName")
    if not isinstance(owner, str) or not owner:
        raise QueryError("missing authoritative identity")
    return {owner}, service


def _observe(config, budget):
    result = budget.run(config, "status", raw=True)
    if result.code not in (0, 1):
        raise _Failure(2, "在线状态查询失败，连接状态未确认")
    try:
        data = json.loads(result.output)
        payload = data["online"]
        observed = _bound_online(payload)
        online = observed is not None
        if data.get("is_online") is not online or online != (result.code == 0):
            raise QueryError("inconsistent status")
        return observed
    except (ValueError, KeyError, TypeError, AttributeError, QueryError):
        raise _Failure(2, "状态响应缺失或矛盾，账号和服务未确认") from None


def _expected(config, budget):
    observed = _observe(config, budget)
    if observed is not None and config.username not in observed[0]:
        raise _Failure(3, "在线账号与当前配置不一致，保留现有连接")
    return observed[1] if observed else None


def _action(config, action, budget):
    result = budget.run(config, action)
    if result.code:
        stage = "目标账号登录" if action == "login" else "现有连接下线"
        raise _Failure(result.code, f"{stage}失败：{result.message}")


def _unchanged(path, source, target, budget):
    budget.check()
    if environment_override() or not unchanged_switch(path, source, target):
        raise _Failure(3, "源配置或候选已被修改，保留新意图并停止切换")


def _restore(path, source, target, previous, budget):
    """One attempt, never act on unknown/external identities or newer intent."""
    original = replace(source, service=previous)
    try:
        _unchanged(path, source, target, budget)
        observed = _observe(original, budget)
        if observed is not None:
            names, service = observed
            if source.username in names and service == previous:
                return True
            if source.username not in names and target["username"] not in names:
                return False
            _unchanged(path, source, target, budget)
            active = original if source.username in names else replace(source, **{
                key: target[key] for key in CREDENTIAL_FIELDS})
            _action(active, "logout", budget)
            if _observe(original, budget) is not None:
                return False
        _unchanged(path, source, target, budget)
        _action(original, "login", budget)
        return _expected(original, budget) == previous
    except (_Failure, OSError, ValueError):
        return False


def switch_account(path, id, *, runner=None, clock=time.monotonic, stop_event=None,
                   timeout=None, environ=None, expected_source=None):
    """Caller owns the lifecycle lock; network work never holds the write lock."""
    if environment_override(environ):
        return AccountSwitchResult(2, "环境变量覆盖存在，账号切换已停用")
    path = Path(path)
    if runner is None:
        runner = lambda config, action, **kwargs: run_backend(
            config, action, stop_event=stop_event, **kwargs)
    try:
        initial = load_config(path, environ={})
        budget = _Budget(initial, runner, clock, stop_event, timeout)
        source, target = prepare_switch(path, id, timeout=budget.check(), stop_event=stop_event,
                                        expected_source=expected_source)
        budget.check()
    except (_Failure, OSError, ValueError) as exc:
        if isinstance(exc, _Failure):
            return AccountSwitchResult(exc.code, str(exc))
        return AccountSwitchResult(2, "账号或活动配置不可用，未发起切换")
    previous, changed = None, False
    desired = replace(source, **{key: target[key] for key in CREDENTIAL_FIELDS})
    try:
        previous = _expected(source, budget)
        _unchanged(path, source, target, budget)
        if source.username == desired.username and previous == desired.service:
            commit_switch(path, source, target, timeout=budget.check(), stop_event=stop_event)
            budget.check()
            return AccountSwitchResult(0, "已独立确认当前账号及服务，无需切换", previous,
                                       committed=True)
        if previous is not None:
            changed = True
            _action(source, "logout", budget)
            if _observe(source, budget) is not None:
                raise _Failure(3, "下线后仍在线，停止切换")
        _unchanged(path, source, target, budget)
        _action(desired, "login", budget)
        if _expected(desired, budget) != desired.service:
            raise _Failure(3, "目标账号或服务核验不一致")
        _unchanged(path, source, target, budget)
        commit_switch(path, source, target, timeout=budget.check(), stop_event=stop_event)
        budget.check()
        return AccountSwitchResult(0, "已独立核验目标账号和服务并保存活动配置", previous,
                                   committed=True)
    except (_Failure, OSError, ValueError) as exc:
        restored = changed and _restore(path, source, target, previous, budget)
        code = exc.code if isinstance(exc, _Failure) else 2
        message = str(exc) if isinstance(exc, _Failure) else "本地配置提交失败，切换未确认"
        if changed:
            message += "；已独立确认恢复原连接" if restored else "；原连接恢复未确认"
        return AccountSwitchResult(code, message, previous, restored)
    except KeyboardInterrupt:
        # Cancellation consumes the same budget; it never yields a success ack.
        if changed and (stop_event is None or not stop_event.is_set()):
            _restore(path, source, target, previous, budget)
        return AccountSwitchResult(130, "操作已取消，切换未确认", previous)


def _cooldown_key(entry):
    # Synthetic current receives a real id on departure; its cooldown survives.
    return tuple(entry[key] for key in CREDENTIAL_FIELDS + ("enabled",))


def _classify(raw):
    # The shared auth classifier is supplied by the quota implementation. An
    # absent module is unknown, never a surrogate exhaustion heuristic.
    try:
        from ysu_net.auth.quota import classify_quota
    except ImportError:
        return {"state": "unknown", "message": "流量分类器尚未可用"}
    return classify_quota(raw)


class AccountRotation:
    MIN_INTERVAL = 60
    COOLDOWN = 900

    def __init__(self, path, *, runner=run_backend, clock=time.monotonic,
                 classifier=None, switcher=None, stop_event=None):
        self.path = Path(path)
        self.runner = runner
        self.clock = clock
        self.classifier = classifier or _classify
        self.switcher = switcher or switch_account
        self.stop_event = stop_event
        self.next_check = 0.0
        self.zero_key = None
        self.zero_time = None
        self.cooldowns = {}
        self.disabled = False
        self.quota = {"state": "unknown", "message": "尚未取得有效流量报告"}
        self.quota_key = None

    def reset(self, *, manual=False):
        self.zero_key = None
        self.zero_time = None
        self.next_check = 0.0
        self.quota = {"state": "unknown", "message": "尚未取得有效流量报告"}
        self.quota_key = None
        if manual:
            self.cooldowns.clear()

    def disable(self):
        # Set before persistence so a disk error never re-enables this owner.
        self.disabled = True
        self.reset()

    def enable(self):
        self.disabled = False
        self.reset()

    def _unknown(self, message):
        self.zero_key = self.zero_time = None
        self.quota = {"state": "unknown", "message": message}
        self.quota_key = None
        return message

    def public_quota(self):
        try:
            latest = load_config(self.path, environ={})
            if self.quota_key == source_signature(latest) and not environment_override():
                return dict(self.quota)
        except (OSError, ValueError):
            pass
        return {"state": "unknown", "message": "当前账号尚未取得有效流量报告"}

    def step(self, *, auto_reconnect=True):
        now = self.clock()
        if self.disabled or not auto_reconnect:
            self.reset()
            return ""
        try:
            config = load_config(self.path, environ={})
            book = load_accounts(self.path, config=config)
            if not book["auto_switch"] or environment_override():
                self.reset()
                return ""
            if now < self.next_check:
                return ""
            self.next_check = now + self.MIN_INTERVAL
            valid = [entry for entry in book["accounts"]
                     if entry["enabled"] and entry["username"] and entry["password"]]
            if len(valid) < 2:
                return self._unknown("有效启用账号不足，等待配置修复")
            budget = _Budget(config, self.runner, self.clock, self.stop_event)
            before = _expected(config, budget)
            if before != config.service:
                return self._unknown("当前账号或服务尚未绑定，暂停流量轮换")
            result = budget.run(config, "info", raw=True)
            if result.code != 0:
                return self._unknown("账户查询失败，未判定流量耗尽")
            try:
                info = json.loads(result.output)
                if type(info.get("account_http_status")) is not int or info["account_http_status"] != 200:
                    raise ValueError("account HTTP query failed")
                raw = info["account"]
                embedded = info["online"]
                observed = _bound_online(embedded)
                if observed is None or observed[1] != before or config.username not in observed[0]:
                    raise QueryError("unbound account query")
                classified = self.classifier(raw)
                if (not isinstance(classified, dict)
                        or classified.get("state") not in ("unknown", "available", "zero_reported", "unlimited")
                        or not isinstance(classified.get("message"), str)):
                    raise ValueError("invalid quota classifier")
            except (ValueError, KeyError, TypeError, AttributeError, QueryError):
                return self._unknown("账户响应无有效身份绑定，暂停流量轮换")
            after = _expected(config, budget)
            latest = load_config(self.path, environ={})
            latest_book = load_accounts(self.path, config=latest)
            if (after != before or source_signature(config) != source_signature(latest)
                    or not latest_book["auto_switch"] or environment_override()):
                return self._unknown("查询期间账号、服务或轮换意图变化，暂停流量轮换")
            # Recheck list membership/credentials after the independent queries.
            current = next(entry for entry in latest_book["accounts"]
                           if entry["username"] == latest.username)
            key = source_signature(config)
            self.quota = {"state": classified["state"], "message": classified["message"]}
            self.quota_key = key
            if classified["state"] != "zero_reported":
                self.zero_key = self.zero_time = None
                return classified["message"]
            observed_at = self.clock()
            if self.zero_key != key or self.zero_time is None:
                self.zero_key, self.zero_time = key, observed_at
                self.cooldowns[_cooldown_key(current)] = observed_at + self.COOLDOWN
                return "门户首次报告零剩余流量，等待独立复查"
            if observed_at - self.zero_time > max(config.check_interval * 2, self.MIN_INTERVAL * 2):
                self.zero_key, self.zero_time = key, observed_at
                return "旧零值报告已过期，等待独立复查"
            if observed_at - self.zero_time < self.MIN_INTERVAL:
                return "等待零剩余流量独立复查"
            self.cooldowns[_cooldown_key(current)] = observed_at + self.COOLDOWN
            entries = latest_book["accounts"]
            index = entries.index(current)
            ordered = entries[index + 1:] + entries[:index]
            target = next((entry for entry in ordered
                           if entry["enabled"] and entry["password"]
                           and self.cooldowns.get(_cooldown_key(entry), 0) <= observed_at), None)
            if target is None:
                return "所有候选均不可用或处于冷却，等待后续检查"
            remaining = budget.check()
            self.zero_key = self.zero_time = None
            outcome = self.switcher(self.path, target["id"], runner=self.runner,
                                    clock=self.clock, stop_event=self.stop_event, timeout=remaining,
                                    expected_source=config)
            if outcome.code != 0:
                self.cooldowns[_cooldown_key(target)] = self.clock() + self.COOLDOWN
            else:
                # No source quota is ever shown as belonging to the new identity.
                self.quota = {"state": "unknown", "message": "已切换，等待新账号流量报告"}
                self.quota_key = None
            self.next_check = self.clock() + self.MIN_INTERVAL
            return outcome.message
        except (_Failure, OSError, ValueError, StopIteration):
            return self._unknown("流量检查未确认，等待后续检查")


class AccountController:
    """Serial control handler run by the daemon that owns the configuration."""

    def __init__(self, path, *, runner=run_backend, stop_event=None):
        self.path = Path(path)
        self.runner = runner
        self.stop_event = stop_event
        self.auto_reconnect = True
        self.rotation = AccountRotation(path, runner=runner, stop_event=stop_event)

    def snapshot(self, *, message=""):
        from .accounts import public_accounts
        view = public_accounts(self.path, quota=self.rotation.public_quota(), message=message)
        if self.rotation.disabled:
            view["auto_switch"] = False
        return view

    def handle(self, action, payload, expires_at):
        from .accounts import set_rotation
        remaining = expires_at - time.time()
        if remaining <= 0:
            return {"code": 2, "message": "控制请求已过期，操作未确认"}
        if action == "switch_account":
            self.rotation.reset(manual=True)
            outcome = switch_account(self.path, payload["id"], runner=self.runner,
                                     stop_event=self.stop_event, timeout=remaining)
            return {"code": outcome.code, "message": outcome.message,
                    "restored": outcome.restored, "committed": outcome.committed}
        if action == "rotation":
            enabled = payload["enabled"]
            if not enabled:
                self.rotation.disable()
            set_rotation(self.path, enabled, auto_reconnect=self.auto_reconnect)
            if enabled:
                self.rotation.enable()
            return {"code": 0, "message": "自动轮换已开启" if enabled else "自动轮换已关闭"}
        return {"code": 2, "message": "控制操作未识别，操作未确认"}
