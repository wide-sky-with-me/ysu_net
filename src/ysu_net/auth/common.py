"""Shared protocol errors and resource ownership for both authentication engines."""
from contextlib import ExitStack
from contextvars import ContextVar
from functools import wraps


class QueryError(RuntimeError):
    exit_code = 2


class OperationFailed(RuntimeError):
    exit_code = 3


class InteractionRequired(RuntimeError):
    exit_code = 4


def online_state(payload):
    """Only a recognized offline response permits automatic authentication."""
    try:
        info = payload["data"]["portalOnlineUserInfo"]
        if info.get("result") == "success":
            return True
        if info.get("message") == "dx.failed.user.offline":
            return False
    except (KeyError, TypeError, AttributeError):
        pass
    raise QueryError("无法确认在线状态：响应结构异常或服务端返回了未知错误")


def online_service(payload):
    """Require a unique, recognized service instead of equating online with success."""
    if not online_state(payload):
        return None
    info = payload["data"]["portalOnlineUserInfo"]
    services = {"校园网", "中国移动", "中国联通", "中国电信"}
    names = {value for key in ("realServiceName", "service")
             if isinstance(value := info.get(key), str) and value in services}
    if len(names) != 1:
        raise QueryError("在线响应未返回唯一可识别的服务，暂不切换连接")
    return names.pop()


def require_online_service(payload, expected):
    actual = online_service(payload)
    if actual != expected:
        raise OperationFailed(
            f"在线服务与请求不一致（当前：{actual or '离线'}；目标：{expected}），"
            f"请使用 ysu switch {expected} 显式切换"
        )
    return actual


def check_action(status, payload, action):
    if status != 200 or not isinstance(payload, dict):
        raise OperationFailed(f"{action} 请求失败（HTTP {status}）")
    # HTTP 200 alone is not success: the live portal can return online=false.
    for item in (payload, payload.get("data")):
        if not isinstance(item, dict):
            continue
        message = item.get("message")
        explicit_failure = isinstance(message, str) and (
            "认证失败" in message or "同时在线用户数量上限" in message
        )
        failed = (item.get("result") in ("fail", "failed", "failure", "error")
                  or (item.get("online") is False and explicit_failure))
        if failed:
            if isinstance(message, str) and "同时在线用户数量上限" in message:
                raise InteractionRequired("运营商同时在线数量已达上限，请先在其他终端正常下线后重试")
            if isinstance(message, str) and any(term in message for term in
                                               ("账号密码错误", "用户名或密码错误", "验证码")):
                raise InteractionRequired("运营商认证需要人工处理，请检查账号绑定、密码或验证码")
            raise OperationFailed(f"{action} 被服务器拒绝")


_resources = ContextVar("ysu_resources", default=None)


def track_resource(close):
    stack = _resources.get()
    if stack is not None:
        stack.callback(close)


def managed_resources(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with ExitStack() as stack:
            token = _resources.set(stack)
            try:
                return function(*args, **kwargs)
            finally:
                _resources.reset(token)
    return wrapped
