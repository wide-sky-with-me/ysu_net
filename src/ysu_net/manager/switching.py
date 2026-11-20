"""Explicit, verified service transitions with a bounded rollback attempt."""
from dataclasses import dataclass, replace
import json
from pathlib import Path

from ysu_net.auth.common import InteractionRequired, QueryError, online_service, online_state
from .backend import run_backend
from .config import SERVICES, config_path, pause_unattended, unattended_paused


@dataclass(frozen=True)
class SwitchResult:
    code: int
    message: str
    previous: str | None = None
    restored: bool = False


class SwitchFailure(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def check_interaction(path, result):
    """A backend challenge is terminal, even if persisting the pause fails."""
    if result.code == 4:
        try:
            pause_unattended(path)
        except OSError as exc:
            raise InteractionRequired(f"{result.message}；自动操作已停止，暂停状态未保存") from exc
        raise InteractionRequired(f"{result.message}；自动操作已暂停")
    return result


def _snapshot(config, runner):
    result = runner(config, "status", raw=True)
    if result.code not in (0, 1):
        raise SwitchFailure(result.code, "在线状态查询失败，未确认连接状态")
    try:
        payload = json.loads(result.output)
        online = online_state(payload["online"])
        if online != (result.code == 0) or payload.get("is_online") is not online:
            raise QueryError("inconsistent status")
        if not online:
            return None
        service = online_service(payload["online"])
        info = payload["online"]["data"]["portalOnlineUserInfo"]
        if config.username not in (info.get("userName"), info.get("userId")):
            raise SwitchFailure(3, "在线账号与当前配置不一致，保留现有连接")
        return service
    except (ValueError, KeyError, TypeError, QueryError):
        raise SwitchFailure(2, "状态响应缺失或矛盾，未确认实际在线服务") from None


def _action(config, action, runner):
    result = runner(config, action)
    if result.code:
        stage = "目标服务登录" if action == "login" else "原连接下线"
        raise SwitchFailure(result.code, f"{stage}失败：{result.message}")


def _restore(config, previous, runner):
    """Never disconnect another account or act on an unknown status."""
    original = replace(config, service=previous)
    try:
        current = _snapshot(original, runner)
        if current == previous:
            return True
        if current is not None:
            _action(original, "logout", runner)
            if _snapshot(original, runner) is not None:
                return False
        _action(original, "login", runner)
        return _snapshot(original, runner) == previous
    except (SwitchFailure, OSError, ValueError):
        return False


def switch_service(config, target, *, path=None, runner=None):
    path = config_path() if path is None else Path(path)
    backend = runner or run_backend

    def run(config, action, **kwargs):
        return check_interaction(path, backend(config, action, **kwargs))

    def recover(config, action, **kwargs):
        if unattended_paused(path):
            raise SwitchFailure(4, "自动操作已暂停，未恢复原连接")
        return run(config, action, **kwargs)

    if target not in SERVICES:
        return SwitchResult(2, "目标服务无效")
    if not config.username or not config.password:
        return SwitchResult(2, "切换前请配置账号密码")
    previous = None
    changed = False
    try:
        previous = _snapshot(config, run)
        if previous == target:
            return SwitchResult(0, f"已确认当前连接为{target}，无需切换", previous)
        desired = replace(config, service=target)
        if previous is not None:
            changed = True
            _action(config, "logout", run)
            if _snapshot(config, run) is not None:
                raise SwitchFailure(3, "下线后仍在线，停止切换")
        _action(desired, "login", run)
        if _snapshot(desired, run) != target:
            raise SwitchFailure(3, "登录后实际在线服务与目标不一致")
        return SwitchResult(0, f"已独立确认切换到{target}", previous)
    except InteractionRequired as stop:
        return SwitchResult(4, str(stop), previous)
    except BaseException as exc:
        try:
            restored = changed and _restore(config, previous, recover)
        except InteractionRequired as stop:
            return SwitchResult(4, str(stop), previous)
        if not isinstance(exc, (SwitchFailure, OSError, ValueError)):
            raise
        code = exc.code if isinstance(exc, SwitchFailure) else 2
        reason = str(exc) if isinstance(exc, SwitchFailure) else "本地操作失败"
        if changed:
            reason += f"；已恢复{previous}" if restored else "；原连接恢复未确认，请查询状态"
        return SwitchResult(code, reason, previous, restored)
