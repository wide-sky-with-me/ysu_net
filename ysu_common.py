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


def check_action(status, payload, action):
    if status != 200 or not isinstance(payload, dict):
        raise OperationFailed(f"{action} 请求失败（HTTP {status}）")
    # Some portal versions wrap the result inside data; others return it at the top.
    for item in (payload, payload.get("data")):
        if isinstance(item, dict) and item.get("result") in ("fail", "failed", "failure", "error"):
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
