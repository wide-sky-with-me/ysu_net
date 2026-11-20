"""Shared protocol errors and resource ownership for both authentication engines."""
from contextlib import ExitStack
from contextvars import ContextVar
from functools import wraps
import re

from .quota import successful_envelope


class QueryError(RuntimeError):
    exit_code = 2


class OperationFailed(RuntimeError):
    exit_code = 3


class InteractionRequired(RuntimeError):
    exit_code = 4


class DeviceLimitError(InteractionRequired):
    """Explicit concurrent-session or authentication-device limit."""


_ANSI_ESCAPE = re.compile(
    r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\))|\x9b[0-?]*[ -/]*[@-~]"
)
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f-\x9f]")
_MAC_BLOCK_RE = re.compile(
    r"(?:mac(?:address|地址)?|物理地址|设备|终端|device)"
    r"(?:[:：（(]?(?:[0-9a-f]{12}|(?:[0-9a-f]{2}[:-]){5}[0-9a-f]{2})[）)]?)?"
    r"[:：=_-]?(?:已经被列入|已被列入|被列入|已经被|已经|已被|被|已|处于|列入|加入|is|was|hasbeen)?[:：=_-]?"
    r"(?:冻结|封禁|锁定|黑名单|禁止认证|禁止登录|不允许认证|受限|限制认证|"
    r"frozen|blocked|banned|blacklisted|locked|restricted|denied)"
    r"|(?:blocked|frozen|blacklisted|banned)(?:mac(?:address)?|device)"
)


def sanitize_text(value: str, limit: int = 500) -> str:
    clean = _ANSI_ESCAPE.sub("", str(value or ""))
    clean = _CONTROL_CHARS.sub(" ", clean)
    return " ".join(clean.split())[:limit]


def _normalize_auth_text(value: str) -> str:
    chars = []
    for ch in str(value or ""):
        code = ord(ch)
        if 0xFF01 <= code <= 0xFF5E:
            chars.append(chr(code - 0xFEE0))
        elif code == 0x3000:
            chars.append(" ")
        else:
            chars.append(ch)
    return re.sub(r"\s+", "", "".join(chars).casefold())


def captcha_needed(payload) -> bool | None:
    """Parse CAS preflight variants; an affirmative flag wins over a conflicting flag."""
    if isinstance(payload, dict):
        flags = [captcha_needed(payload[key]) for key in
                 ("isNeed", "needCaptcha", "isNeedCaptcha", "data", "result") if key in payload]
        return True if True in flags else False if False in flags else None
    if isinstance(payload, (str, bool, int)):
        value = str(payload).strip().casefold()
        if value in ("true", "1", "yes"):
            return True
        if value in ("false", "0", "no"):
            return False
    return None


def _is_device_limit(compact: str) -> bool:
    if any(marker in compact for marker in (
        "同时在线用户数量上限", "并发用户数量上限", "并发数上限",
        "认证设备数量", "认证设备数", "认证终端数量", "认证终端数",
        "设备数量上限", "设备数上限", "在线设备数量上限", "在线设备数上限",
        "终端数量上限", "终端数上限", "达到设备上限", "设备已达上限", "设备达到上限",
        "最大认证设备", "authenticationdevicelimit", "maximumauthenticationdevices",
        "devicecountlimit", "maximumnumberofdevices", "devicelimit",
    )):
        return True
    has_device = any(w in compact for w in ("设备", "终端", "device", "terminal"))
    has_limit = any(w in compact for w in ("上限", "最大", "限制", "超过", "已满", "limit", "maximum", "max", "exceed"))
    has_auth = any(w in compact for w in ("认证", "登录", "在线", "数量", "设备数", "terminal", "authentication", "login", "count"))
    return has_device and has_limit and has_auth


def _is_terminal_auth_rejection(compact: str) -> bool:
    if "maccollision" in compact or "mac冲突" in compact or "mac地址冲突" in compact:
        return True
    if _MAC_BLOCK_RE.search(compact):
        return True
    return any(term in compact for term in (
        "认证过于频繁", "认证太频繁", "登录过于频繁", "操作过于频繁", "请求过于频繁", "认证频率过高",
        "toomanyauthenticationattempts", "toomanyloginattempts", "toomanyrequests",
        "ratelimitexceeded", "authenticationtoofrequent",
        "账号密码错误", "用户名或密码", "用户名错误", "用户或密码", "账号或密码", "帐号或密码",
        "账户或密码", "密码错误", "密码不正确", "口令错误", "凭据无效", "invalidcredentials",
        "wrongpassword", "验证码", "captcha", "verificationcode", "风控", "ip被冻结", "冻结", "锁定", "欠费", "停机",
        "余额不足", "未绑定", "无绑定", "绑定关系", "用户不存在", "账号不存在", "黑名单",
    ))


def flow_node(payload):
    """A failed workflow envelope never grants permission to change a connection."""
    inner = payload.get("data") if isinstance(payload, dict) else None
    if not successful_envelope(payload) or not successful_envelope(inner):
        raise QueryError("门户流程节点业务结果未确认，暂不修改连接")
    node = inner.get("currentNodePath")
    if not isinstance(node, str) or not node:
        raise QueryError("门户流程节点未知，暂不修改连接")
    return node


def online_state(payload):
    """Only a recognized offline response permits automatic authentication."""
    try:
        info = payload["data"]["portalOnlineUserInfo"]
        if not successful_envelope(payload) or not successful_envelope(payload["data"]):
            raise QueryError("在线状态的外层业务结果未确认")
        if info.get("result") == "success":
            if not successful_envelope(info):
                raise QueryError("在线状态的内层业务结果矛盾")
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
    values = [info[key] for key in ("realServiceName", "service") if key in info]
    # Portal variants send JSON null when the raw label is absent, not unknown.
    raw_service = info.get("realServiceName")
    if raw_service is not None and (not isinstance(raw_service, str) or raw_service not in services):
        raise QueryError("在线原始服务名称未知，暂不切换连接")
    names = {value for value in values if isinstance(value, str) and value in services}
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


_AUTH_MESSAGE_KEYS = (
    "message", "authMessage", "errorMessage", "errorMsg",
    "reason", "description", "errorCode", "authCode", "errCode",
)


def check_action(status, payload, action):
    if status == 429:
        raise InteractionRequired("认证请求过于频繁，请稍后重试")
    if not isinstance(payload, dict):
        raise OperationFailed(f"{action} 请求失败（HTTP {status}）")
    # HTTP 200 alone is not success: the live portal can return online=false,
    # and the status flag may live on the outer envelope while error detail lives in data.
    items = [item for item in (payload, payload.get("data")) if isinstance(item, dict)]
    if any(captcha_needed(item[key]) is True for item in items
           for key in ("needCaptcha", "isNeedCaptcha") if key in item):
        raise InteractionRequired("运营商认证需要验证码，请在校园网门户人工处理")
    compacts = [
        _normalize_auth_text(sanitize_text(str(item[key])))
        for item in items
        for key in _AUTH_MESSAGE_KEYS
        if item.get(key) is not None and not isinstance(item.get(key), (dict, list, tuple, set, bool))
        and str(item[key]).strip()
    ]
    if any(any(term in c for term in ("请输入验证码", "需要验证码", "验证码错误", "验证码不正确",
                                       "captcharequired", "captcha_required", "invalidcaptcha"))
           for c in compacts):
        raise InteractionRequired("运营商认证需要验证码，请在校园网门户人工处理")
    explicit_failure = any(
        "认证失败" in c or _is_device_limit(c) or _is_terminal_auth_rejection(c)
        for c in compacts
    )
    failed = status != 200 or any(
        item.get("result") in ("fail", "failed", "failure", "error")
        or ("authResult" in item and item["authResult"] != "success")
        or item.get("success") is False
        or (type(item.get("code")) is int and item["code"] not in (0, 200))
        or (item.get("online") is False and explicit_failure)
        for item in items
    )
    if failed:
        if any(_is_device_limit(c) for c in compacts):
            raise DeviceLimitError("运营商同时在线数量已达上限，请先在其他终端正常下线后重试")
        if any(_is_terminal_auth_rejection(c) for c in compacts):
            raise InteractionRequired("运营商认证需要人工处理，请检查账号绑定、密码或验证码")
        if status != 200:
            raise OperationFailed(f"{action} 请求失败（HTTP {status}）")
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
