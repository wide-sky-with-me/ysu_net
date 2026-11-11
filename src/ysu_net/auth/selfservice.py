"""Access to the auth1 self-service portal (/self) and device offline control.

The portal is a separate OAuth2 client (``custom-self``) that shares the same
CAS identity as the eportal chain but keeps its own local session.  Login is
delegated back to ``cer.ysu.edu.cn`` through ``/cas-sso/clientredirect``, which
lands on the *classic* CAS form this project already drives — the only new
input is the ``service`` value.

Snapshot queries are read-only; explicit device actions only touch the allowlisted
kick-offline endpoint.  Verified against the live portal on 2026-11-09:
plain cookies are enough — no Bearer token, no request-body encryption.

Decision: .agents/notes/proposals/desktop/2026-11-09-self-service-protocol.md
"""
from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

import requests

from .common import QueryError

SELF_PATH = "/self/index"

DEVICES = "/sam/api/userself/devices"
DEFAULT_SERVICES = "/sam/api/userself/devices/defaultServicesList"
PACKAGE_OVERVIEW = "/sam/api/userself/package/overview"
PACKAGE_FLOW = "/sam/api/userself/package/flow"
REMEMBER_CURRENT = "/sam/api/userself/rememberService/current"
KICK_OFFLINE = "/sam/api/userself/devices/kick-offline/batch"
NOSENSE_REGISTER = "/sam/api/userself/nosense/register"
NOSENSE_UNBIND = "/sam/api/userself/nosense/unbind/batch"
DEVICE_MODIFY = "/sam/api/userself/devices/modify"
DEFAULT_SERVICE_PACKAGE = "00_DEFAULT_IN_PACKAGE"
NOSENSE_RENEW_THRESHOLD = 86400
KICK_VERIFY_SECONDS = 12.0
KICK_VERIFY_INTERVAL = 3.0

_DEFAULT_SERVICE_UUIDS = {
    "套餐默认服务": DEFAULT_SERVICE_PACKAGE,
    "校园网": DEFAULT_SERVICE_PACKAGE,
    "默认": DEFAULT_SERVICE_PACKAGE,
    "中国移动": "8a8b808256b247030156b282869a008f",
    "中国电信": "8a8b808256b247030156b2831c150095",
    "中国联通": "8a8b808256b247030156b2813f020087",
}
_UUID_TO_DEFAULT_SERVICE = {
    DEFAULT_SERVICE_PACKAGE: "套餐默认服务",
    "8a8b808256b247030156b282869a008f": "中国移动",
    "8a8b808256b247030156b2831c150095": "中国电信",
    "8a8b808256b247030156b2813f020087": "中国联通",
}
_BEIJING_TZ = timezone(timedelta(hours=8))
_MAC_HEX_RE = re.compile(r"^[0-9A-F]{12}$")
_MAC_DASH_RE = re.compile(r"^(?:[0-9A-F]{2}-){5}[0-9A-F]{2}$")

_DEVICE_FIELDS = (
    ("deviceName", "设备名称"),
    ("deviceType", "类型"),
    ("userMac", "MAC"),
    ("userIpv4", "IP"),
    ("onlineDuration", "在线时长"),
    ("authType", "接入方式"),
)
_MAX_TEXT = 4096
_MAX_DEVICES = 64


def normalize_mac(value: str | None) -> str | None:
    """Normalize a MAC address to uppercase XX-XX-XX-XX-XX-XX, or None if invalid."""
    if not isinstance(value, str):
        return None
    raw = value.strip().upper().replace(":", "-")
    if "." in raw:
        parts = raw.split(".")
        if len(parts) == 3 and all(len(p) == 4 for p in parts):
            raw = "".join(parts)
    if _MAC_HEX_RE.fullmatch(raw):
        raw = "-".join(raw[i:i + 2] for i in range(0, 12, 2))
    if not _MAC_DASH_RE.fullmatch(raw):
        return None
    if raw in ("00-00-00-00-00-00", "FF-FF-FF-FF-FF-FF"):
        return None
    return raw


def require_mac(value: str | None) -> str:
    mac = normalize_mac(value)
    if not mac:
        raise QueryError("MAC 地址格式无效，应为 XX-XX-XX-XX-XX-XX")
    return mac


def format_epoch_ms(value) -> str:
    """Format epoch milliseconds in UTC+8 (matching portal timestamps)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        return ""
    try:
        return datetime.fromtimestamp(value / 1000.0, tz=_BEIJING_TZ).strftime("%Y-%m-%d %H:%M:%S")
    except (OverflowError, OSError, ValueError):
        return ""


def parse_default_services(payload) -> list[dict]:
    if isinstance(payload, dict) and "data" in payload and payload["data"] is None:
        return []
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        raise QueryError("自助服务缺省服务列表响应结构异常")
    items = []
    for item in data[:16]:
        if not isinstance(item, dict):
            continue
        label, value = _text(item.get("label")), _text(item.get("value"))
        if label and value:
            items.append({"label": label, "value": value})
    return items


def resolve_default_service(name: str | None, services: list[dict] | None = None) -> tuple[str, str]:
    """Resolve user service label/alias to (canonical_label, uuid)."""
    wanted = (name or "").strip()
    if wanted in ("校园网", "默认"):
        wanted = "套餐默认服务"
    for item in services or ():
        if item.get("label") == wanted and item.get("value"):
            return item["label"], item["value"]
        if item.get("value") == wanted and item.get("label"):
            return item["label"], item["value"]
    if wanted in _DEFAULT_SERVICE_UUIDS:
        uuid = _DEFAULT_SERVICE_UUIDS[wanted]
        return _UUID_TO_DEFAULT_SERVICE.get(uuid, wanted), uuid
    if wanted in _UUID_TO_DEFAULT_SERVICE:
        return _UUID_TO_DEFAULT_SERVICE[wanted], wanted
    raise QueryError("缺省服务无效，可选：套餐默认服务（或校园网）、中国移动、中国联通、中国电信")


def self_service_url(base: str) -> str:
    return f"{base.rstrip('/')}{SELF_PATH}"


def callback_url(base: str) -> str:
    return f"{base.rstrip('/')}/login/oauth2/code/custom-self"


def _is_self_url(url: str) -> bool:
    path = urlparse(url or "").path
    return (path == "/self" or path.startswith("/self/")) and "/cas-sso/" not in path


def seed_service(seed_url: str, base: str) -> str:
    """Use the OAuth2 callbackAuthorize service from /self/index when same-origin."""
    fallback = callback_url(base)
    raw = (parse_qs(urlparse(seed_url or "").query).get("service") or [None])[0]
    if not raw or len(raw) > 1024:
        return fallback
    parsed, expected = urlparse(raw), urlparse(base)
    if (parsed.scheme, parsed.netloc) != (expected.scheme, expected.netloc):
        return fallback
    if parsed.username or parsed.password:
        return fallback
    return raw


def _seed_self(session: requests.Session, base: str, timeout: int = 25) -> tuple[bool, str]:
    """Visit /self/index first to initialise OAuth2 SavedRequest and callbackAuthorize."""
    r = session.get(self_service_url(base), timeout=timeout, allow_redirects=True)
    if r.status_code == 200 and _is_self_url(r.url):
        return True, callback_url(base)
    return False, seed_service(r.url, base)


def _text(value) -> str:
    if value is None or isinstance(value, (bool, dict, list)):
        return ""
    out = " ".join(str(value).split())
    return out[:_MAX_TEXT]


def parse_devices(payload, services: list[dict] | None = None) -> dict:
    """Split online/offline devices into display rows; never invent values."""
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        raise QueryError("自助服务设备响应结构异常")
    uuid_map = dict(_UUID_TO_DEFAULT_SERVICE)
    for item in services or ():
        if isinstance(item, dict) and item.get("value") and item.get("label"):
            uuid_map[item["value"]] = item["label"]
    rows = []
    for group in ("onlineDevices", "offlineDevices"):
        items = data.get(group)
        if not isinstance(items, list):
            continue
        for item in items[:_MAX_DEVICES]:
            if not isinstance(item, dict):
                continue
            row = {label: _text(item.get(key)) for key, label in _DEVICE_FIELDS}
            row["在线"] = "是" if group == "onlineDevices" else "否"
            row["本机"] = "是" if item.get("currentDevice") is True else "否"
            bind_nosense = item.get("bindNoSense") is True
            create_ms = item.get("noSenseCreateTime")
            if isinstance(create_ms, bool) or not isinstance(create_ms, int):
                create_ms = None
            end_ms = item.get("noSenseEndTime")
            if isinstance(end_ms, bool) or not isinstance(end_ms, int):
                end_ms = None
            service_uuid = _text(item.get("defaultServiceOperaporsConfigUuid"))
            terminal_type = item.get("terminalType")
            if isinstance(terminal_type, bool) or not isinstance(terminal_type, int):
                terminal_type = 1
            row["无感"] = "是" if bind_nosense else "否"
            row["无感到期"] = format_epoch_ms(end_ms) if bind_nosense else ""
            row["缺省服务"] = uuid_map.get(service_uuid, service_uuid) if service_uuid else ""
            # 核验用的原始标识，渲染时不显示
            row["_uuid"] = _text(item.get("onlineUserUuid"))
            row["_unified"] = item.get("unifiedAuthentication") is True
            row["_nosense_uuid"] = _text(item.get("noSenseUuid"))
            row["_nosense_create_ms"] = create_ms
            row["_nosense_end_ms"] = end_ms
            row["_service_uuid"] = service_uuid
            row["_terminal_type"] = terminal_type
            row["_location"] = _text(item.get("location"))
            rows.append(row)
    return {"online": sum(1 for r in rows if r["在线"] == "是"),
            "total": len(rows), "rows": rows}


def parse_flow(payload) -> dict:
    """Remaining traffic as the portal states it; no unit conversion."""
    if isinstance(payload, dict) and "data" in payload and payload["data"] is None:
        return {"items": []}
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        raise QueryError("自助服务流量响应结构异常")
    items = []
    for group in data.get("availableFreeItems") or []:
        if not isinstance(group, dict):
            continue
        for charge in group.get("chargeItems") or []:
            if not isinstance(charge, dict):
                continue
            items.append({
                "name": _text(charge.get("name")),
                "total": _text(charge.get("totalFreeValueDesc")),
                "left": _text(charge.get("leftFreeValueDesc")),
                "percent": charge.get("usingPercentages"),
            })
    return {"items": items}


def parse_package(payload) -> dict:
    if isinstance(payload, dict) and "data" in payload and payload["data"] is None:
        return {
            "package": "",
            "rule": "",
            "period": "",
            "used": "",
            "percent": None,
            "balance": "",
        }
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        raise QueryError("自助服务套餐响应结构异常")
    policy = data.get("policyInfo") or {}
    period = data.get("periodInfo") or {}
    used = data.get("usedInfo") or {}
    return {
        "package": _text(policy.get("packageName")),
        "rule": _text(policy.get("periodAndTimeOrFlowDetail")),
        "period": _text(period.get("dateRangeDesc")),
        "used": _text(used.get("usedFreeDesc")),
        "percent": used.get("flowUsingPercentages"),
        "balance": _text((data.get("accountInfo") or {}).get("currentFee")),
    }


def parse_remember(payload) -> dict:
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        return {"remembered": None, "service": "", "expires": ""}
    return {"remembered": data.get("remembered"),
            "service": _text(data.get("service")),
            "expires": _text(data.get("expirationDate"))}


def fetch(session: requests.Session, base: str, path: str, body: dict | None = None,
          timeout: int = 25) -> dict:
    """POST a JSON body (default empty); the portal authorises by cookie alone."""
    r = session.post(f"{base.rstrip('/')}{path}", json={} if body is None else body,
                     timeout=timeout,
                     headers={"Accept": "application/json", "clientType": "self",
                              "Referer": self_service_url(base)})
    if r.status_code != 200:
        raise QueryError(f"自助服务接口未返回 200（HTTP {r.status_code}）")
    try:
        payload = r.json()
    except ValueError as exc:
        raise QueryError("自助服务接口返回的不是 JSON") from exc
    if not isinstance(payload, dict) or payload.get("code") != 200:
        raise QueryError("自助服务接口业务结果未确认")
    return payload


def landed_in_self(session: requests.Session, base: str, timeout: int = 25) -> bool:
    """True when the session reaches /self/index instead of bouncing to CAS."""
    r = session.get(self_service_url(base), timeout=timeout, allow_redirects=True)
    return r.status_code == 200 and _is_self_url(r.url)


# Cache the cookie jar so repeated calls do not re-run a password login.
# The file holds live session cookies, so it is created 0600 next to the other
# ysu-net cache data and never written to logs or error output.
SESSION_TTL = 1800
_CACHE_NAME = "self-session.json"
_CACHE_MAX_BYTES = 64 * 1024


def cache_path() -> Path:
    root = os.environ.get("XDG_CACHE_HOME", "")
    base = Path(root) if root and Path(root).is_absolute() else Path.home() / ".cache"
    return base / "ysu-net" / _CACHE_NAME


def _jar(session: requests.Session) -> list[dict]:
    return [{"name": c.name, "value": c.value, "domain": c.domain,
             "path": c.path, "secure": bool(c.secure)}
            for c in session.cookies]


def _session_cache_key(base: str, username: str) -> str:
    return f"{base.rstrip('/')}|{username}"


def _read_session_store(path: Path) -> dict | None:
    try:
        if not path.is_file() or path.stat().st_size > _CACHE_MAX_BYTES:
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("version") != 1:
        return None
    return data


def _extract_sessions(data: dict | None, now: int) -> dict[str, dict]:
    if not isinstance(data, dict):
        return {}
    out: dict[str, dict] = {}
    raw_sessions = data.get("sessions")
    if isinstance(raw_sessions, dict):
        for k, item in raw_sessions.items():
            if (isinstance(k, str) and isinstance(item, dict)
                    and isinstance(item.get("base"), str)
                    and isinstance(item.get("username"), str)
                    and isinstance(item.get("saved_at"), int)
                    and now - item["saved_at"] <= SESSION_TTL
                    and isinstance(item.get("cookies"), list) and item["cookies"]):
                out[k] = item
    if (isinstance(data.get("base"), str) and isinstance(data.get("username"), str)
            and isinstance(data.get("saved_at"), int)
            and now - data["saved_at"] <= SESSION_TTL
            and isinstance(data.get("cookies"), list) and data["cookies"]):
        top_key = _session_cache_key(data["base"], data["username"])
        out.setdefault(top_key, {
            "base": data["base"],
            "username": data["username"],
            "saved_at": data["saved_at"],
            "cookies": data["cookies"],
        })
    return out


def _write_session_store(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(data, handle)
    os.replace(tmp, path)


def save_session(session: requests.Session, base: str, username: str) -> None:
    """Persist the cookie jar for this origin+account; best effort."""
    now = int(time.time())
    norm_base = base.rstrip("/")
    entry = {"base": norm_base, "username": username,
             "saved_at": now, "cookies": _jar(session)}
    session._ysu_self_saved_at = now  # noqa: SLF001 - internal marker
    try:
        path = cache_path()
        sessions = _extract_sessions(_read_session_store(path), now)
        sessions[_session_cache_key(norm_base, username)] = entry
        if len(sessions) > 32:
            oldest = sorted(sessions.items(), key=lambda kv: kv[1].get("saved_at", 0))
            for k, _ in oldest[:len(sessions) - 32]:
                sessions.pop(k, None)
        data = {"version": 1, **entry, "sessions": sessions}
        _write_session_store(path, data)
    except OSError:
        pass   # a cache miss only costs one extra login


def _portal_session() -> requests.Session:
    from .api import _new_portal_session

    return _new_portal_session()


def load_session(base: str, username: str, ttl: int = SESSION_TTL):
    """Return a session restored from cache, or None when unusable."""
    path = cache_path()
    data = _read_session_store(path)
    if data is None:
        return None
    norm_base = base.rstrip("/")
    key = _session_cache_key(norm_base, username)
    entry = None
    raw_sessions = data.get("sessions")
    if isinstance(raw_sessions, dict) and isinstance(raw_sessions.get(key), dict):
        entry = raw_sessions[key]
    elif data.get("base") == norm_base and data.get("username") == username:
        entry = data
    if not isinstance(entry, dict):
        return None
    if entry.get("base") != norm_base or entry.get("username") != username:
        return None
    saved_at = entry.get("saved_at")
    if not isinstance(saved_at, int) or time.time() - saved_at > ttl:
        return None
    cookies = entry.get("cookies")
    if not isinstance(cookies, list) or not cookies:
        return None
    # Rebuild with the same headers a fresh login would use; a bare
    # requests.Session() advertises python-requests and loses Accept-Language.
    session = _portal_session()
    for item in cookies:
        if not isinstance(item, dict):
            continue
        name, value = item.get("name"), item.get("value")
        if isinstance(name, str) and isinstance(value, str):
            session.cookies.set(name, value, domain=item.get("domain"),
                                path=item.get("path"))
    session._ysu_self_saved_at = saved_at  # noqa: SLF001 - internal marker
    return session


def clear_session(base: str | None = None, username: str | None = None) -> None:
    try:
        path = cache_path()
        if not base or not username:
            path.unlink()
            return
        now = int(time.time())
        sessions = _extract_sessions(_read_session_store(path), now)
        sessions.pop(_session_cache_key(base.rstrip("/"), username), None)
        if not sessions:
            path.unlink()
            return
        latest = max(sessions.values(), key=lambda item: item.get("saved_at", 0))
        _write_session_store(path, {"version": 1, **latest, "sessions": sessions})
    except OSError:
        pass


def _still_authorised(session: requests.Session, base: str, timeout: int = 15) -> bool:
    """One lightweight GET decides whether the cached jar still works.

    When /self's local SESSION cookie has expired (~30 min) but the unified-auth
    CASTGC cookie is still valid, following /cas-sso/clientredirect re-mints
    SESSION without submitting a password login.
    """
    try:
        r = session.get(self_service_url(base), timeout=timeout, allow_redirects=True)
        if r.status_code == 200 and _is_self_url(r.url):
            return True
        if r.status_code == 200 and any(c.name == "CASTGC" for c in session.cookies):
            svc = seed_service(r.url, base)
            redirect = (f"{base.rstrip('/')}/cas-sso/clientredirect"
                        f"?client_name=sidadapter&service={quote(svc, safe='')}&accept-language=zh-CN")
            r2 = session.get(redirect, timeout=timeout, allow_redirects=True)
            if r2.status_code == 200 and _is_self_url(r2.url):
                return True
    except requests.RequestException:
        return False
    return False


def open_session(base: str, cas_host: str, username: str, password: str,
                 debug: bool = False, fresh: bool = False,
                 ttl: int = SESSION_TTL) -> requests.Session:
    """Return an authorised /self session, reusing a cached one when possible.

    Unified auth issues a long-lived ``CASTGC``; caching the cookie jar means a
    second ``ysu self`` inside the TTL performs no password login at all.  That
    matters because repeated full logins are what trips the portal's IP freeze.

    ``fresh=True`` ignores the cache and always logs in again.
    """
    from .api import _new_portal_session, cas_login

    if not fresh:
        cached = load_session(base, username, ttl=ttl)
        if cached is not None:
            if _still_authorised(cached, base):
                cached._ysu_self_cached = True     # noqa: SLF001 - internal marker
                return cached
            clear_session(base, username)   # stale: drop only this account's entry

    session = _new_portal_session()
    try:
        already_in, service = _seed_self(session, base)
        if not already_in:
            cas_login(session, username, password, debug=debug, service=service)
    except Exception as exc:  # re-raise with a stable prefix, keep the reason
        raise QueryError(f"自助服务登录失败：{exc}") from exc
    if not landed_in_self(session, base):
        raise QueryError("自助服务登录后仍未进入自助服务页")
    session._ysu_self_cached = False      # noqa: SLF001 - internal marker
    save_session(session, base, username)
    return session


def session_state(session: requests.Session) -> dict:
    """Where the session came from, for the rendered output."""
    cached = getattr(session, "_ysu_self_cached", None)
    left = None
    if cached:
        saved_at = getattr(session, "_ysu_self_saved_at", None)
        if isinstance(saved_at, int):
            left = max(0, SESSION_TTL - (int(time.time()) - saved_at))
        else:
            try:
                data = json.loads(cache_path().read_text(encoding="utf-8"))
                left = max(0, SESSION_TTL - (int(time.time()) - int(data["saved_at"])))
            except (OSError, ValueError, KeyError, TypeError):
                left = None
    return {"cached": cached is True, "expires_in": left}


def snapshot(base: str, cas_host: str, username: str, password: str,
             debug: bool = False, fresh: bool = False) -> dict:
    """Read-only snapshot: devices, package, remaining flow, remembered service."""
    session = open_session(base, cas_host, username, password, debug=debug, fresh=fresh)
    try:
        return {
            "session": session_state(session),
            "devices": parse_devices(fetch(session, base, DEVICES)),
            "package": parse_package(fetch(session, base, PACKAGE_OVERVIEW)),
            "flow": parse_flow(fetch(session, base, PACKAGE_FLOW)),
            "remember": parse_remember(fetch(session, base, REMEMBER_CURRENT)),
        }
    except Exception:
        clear_session()
        raise


def format_snapshot(snap: dict) -> str:
    """Human-readable block for the CLI; portal wording only, no derived values."""
    lines = ["自助服务（门户原文）"]
    state = snap.get("session") or {}
    if state.get("cached"):
        left = state.get("expires_in")
        extra = f"，缓存剩余 {left // 60} 分钟" if isinstance(left, int) else ""
        lines.append(f"会话：复用已登录状态（未重新登录{extra}）")
    elif state.get("cached") is False:
        lines.append("会话：本次新登录")
    dev = snap.get("devices") or {}
    lines.append(f"在线设备：{dev.get('online', 0)} 台 / 共 {dev.get('total', 0)} 条")
    for index, row in enumerate(dev.get("rows") or [], 1):
        bits = [f"{k}={row[k]}" for k in ("类型", "MAC", "IP", "在线时长", "接入方式")
                if row.get(k)]
        if row.get("无感") == "是":
            bits.append("无感=已开启")
            if row.get("无感到期"):
                bits.append(f"无感到期={row['无感到期']}")
            if row.get("缺省服务"):
                bits.append(f"缺省服务={row['缺省服务']}")
        tags = []
        if row.get("在线") == "是":
            tags.append("在线")
        if row.get("本机") == "是":
            tags.append("本机")
        head = f"  {index}. {row.get('设备名称') or '未命名'}"
        if tags:
            head += f"（{'，'.join(tags)}）"
        lines.append(head + ("  " + " ".join(bits) if bits else ""))
    if not dev.get("rows"):
        lines.append("  （门户未返回任何设备）")

    pkg = snap.get("package") or {}
    if pkg.get("package"):
        lines.append(f"套餐：{pkg['package']}" + (f"（{pkg['rule']}）" if pkg.get("rule") else ""))
    if pkg.get("period"):
        lines.append(f"计费周期：{pkg['period']}")
    if pkg.get("used"):
        lines.append(f"已用：{pkg['used']}")
    if pkg.get("balance"):
        lines.append(f"余额：{pkg['balance']}")

    flow = snap.get("flow") or {}
    for item in flow.get("items") or []:
        pct = item.get("percent")
        name = f"（{item['name']}）" if item.get("name") else ""
        suffix = f"（已用 {pct}%）" if isinstance(pct, (int, float)) else ""
        lines.append(f"剩余流量：{item.get('left') or '门户未提供'} / {item.get('total') or '—'}{name}{suffix}")
    if not flow.get("items"):
        lines.append("剩余流量：门户未提供（不代表 0 或不限量）")

    rem = snap.get("remember") or {}
    if rem.get("remembered") is True:
        lines.append(f"记住的上网选择：{rem.get('service') or '已开启'}"
                     + (f"（到期 {rem['expires']}）" if rem.get("expires") else ""))
    elif rem.get("remembered") is False:
        lines.append("记住的上网选择：未开启")
    return "\n".join(lines)


def cmd_self(username: str, password: str, base: str, cas_host: str,
             raw: bool, debug: bool, fresh: bool = False) -> str:
    snap = snapshot(base, cas_host, username, password, debug=debug, fresh=fresh)
    if raw:
        import json
        return json.dumps(snap, ensure_ascii=False, indent=2)
    return format_snapshot(snap)


# ---------------------------------------------------------------------------
# Writes.  The portal's device page is a control console; only allowlisted
# kick-offline, seamless-auth (nosense), and device default-service endpoints
# are touched.
#
# Contract, read from /self/assets/myDevices-*.js:
#   kick-offline/batch  {onlineUserUuids: [...], kickUnifiedAuthOffline: bool}
#   nosense/register    {userMac: "XX-XX-XX-XX-XX-XX", expireTime: 7, expireUnit: "day"}
#   nosense/unbind/batch {noSenseUuids: [...]}
#   devices/modify      {userMac, name, location, defaultServiceOperaporsConfigUuid, terminalType}
# ---------------------------------------------------------------------------

class KickVerifyError(QueryError):
    """The write returned OK but the device is still online."""


class NoSenseVerifyError(QueryError):
    """The seamless-auth or default-service write returned OK but was not confirmed."""


def kick_offline(session: requests.Session, base: str, uuids, *,
                 kick_unified: bool) -> dict:
    if not uuids:
        raise QueryError("没有指定要下线的设备")
    return fetch(session, base, KICK_OFFLINE,
                 {"onlineUserUuids": list(uuids),
                  "kickUnifiedAuthOffline": bool(kick_unified)})


def kick_unified_flag(row) -> bool:
    """Mirror the portal's own rule for whether to end the SSO session too."""
    return not (row.get("_unified") is True and row.get("本机") == "是")


def select_devices(rows, selector: str) -> list:
    """Resolve `all` or a 1-based index against the last rendered list."""
    if selector.strip().lower() in ("all", "全部"):
        picked = [r for r in rows if r.get("在线") == "是" and r.get("_uuid")]
        if not picked:
            raise QueryError("没有可下线的在线设备")
        return picked
    try:
        index = int(selector)
    except (TypeError, ValueError):
        raise QueryError("设备编号无法识别") from None
    if index < 1 or index > len(rows):
        raise QueryError("设备编号超出范围")
    row = rows[index - 1]
    if row.get("在线") != "是":
        raise QueryError("该设备当前不在线")
    if not row.get("_uuid"):
        raise QueryError("该设备缺少门户标识")
    return [row]


def kick(base: str, cas_host: str, username: str, password: str, selector: str,
         debug: bool = False, fresh: bool = False) -> dict:
    """Kick one device (by 1-based index) or `all`, then verify by re-reading."""
    session = open_session(base, cas_host, username, password, debug=debug, fresh=fresh)
    try:
        before = parse_devices(fetch(session, base, DEVICES))
        targets = select_devices(before["rows"], selector)

        kicked = []
        for row in targets:
            flag = kick_unified_flag(row)
            kick_offline(session, base, [row["_uuid"]], kick_unified=flag)
            kicked.append({"uuid": row["_uuid"], "type": row.get("类型", ""),
                           "current": row.get("本机") == "是",
                           "unified_offline": flag})

        after, still = _await_offline(session, base, [k["uuid"] for k in kicked])
        if still:
            raise KickVerifyError(
                f"下线请求已提交，但仍有 {len(still)} 台设备显示在线"
            )
        return {"kicked": kicked, "online_before": before["online"],
                "online_after": after["online"], "rows": after["rows"]}
    except Exception:
        clear_session()
        raise


def _await_offline(session: requests.Session, base: str, uuids,
                   wait: float = KICK_VERIFY_SECONDS,
                   interval: float = KICK_VERIFY_INTERVAL):
    """Re-read the device list until the targets are gone or the budget runs out."""
    deadline = time.monotonic() + wait
    while True:
        after = parse_devices(fetch(session, base, DEVICES))
        remaining = {r.get("_uuid") for r in after["rows"] if r.get("在线") == "是"}
        still = [u for u in uuids if u in remaining]
        if not still or time.monotonic() >= deadline:
            return after, still
        time.sleep(interval)


def format_kick(result: dict) -> str:
    """Report what was asked to go offline and what the portal says now."""
    lines = []
    for item in result.get("kicked") or []:
        kind = item.get("type") or "设备"
        who = "本机" if item.get("current") else "其他设备"
        tail = "（统一认证一并登出）" if item.get("unified_offline") else "（保留统一认证登录）"
        lines.append(f"已下线：{kind}（{who}）{tail}")
    lines.append(f"在线设备：{result.get('online_before')} → {result.get('online_after')} 台")
    rows = result.get("rows") or []
    for index, row in enumerate(rows, 1):
        if row.get("在线") == "是":
            lines.append(f"  {index}. {row.get('类型') or '未命名'}"
                         f"（{'本机' if row.get('本机') == '是' else '其他设备'}）"
                         f" {row.get('IP') or ''} {row.get('在线时长') or ''}".rstrip())
    if not any(r.get("在线") == "是" for r in rows):
        lines.append("当前没有在线设备。")
    return "\n".join(lines)


def select_nosense_target(rows: list[dict], selector: str | None = "current") -> tuple[str, dict | None]:
    """Resolve `current`, a 1-based device index, or an explicit MAC address."""
    wanted = (selector or "current").strip()
    if not wanted or wanted.lower() in ("current", "本机"):
        row = next((r for r in rows if r.get("本机") == "是"), None)
        if row is None:
            row = next((r for r in rows if r.get("无感") == "是"), None)
        if row is None:
            raise QueryError("未找到本机或已绑定无感的设备，请指定设备编号或 MAC 地址")
        return require_mac(row.get("MAC")), row
    if wanted.isdigit() and len(wanted) <= 4:
        index = int(wanted)
        if index < 1 or index > len(rows):
            raise QueryError("设备编号超出范围")
        row = rows[index - 1]
        return require_mac(row.get("MAC")), row
    mac = normalize_mac(wanted)
    if mac:
        row = next((r for r in rows if normalize_mac(r.get("MAC")) == mac), None)
        return mac, row
    raise QueryError("设备编号或 MAC 地址无法识别")


def select_nosense_unbind_targets(rows: list[dict], selector: str | None = "all") -> list[dict]:
    """Resolve devices to unbind from seamless auth."""
    wanted = (selector or "all").strip()
    if not wanted or wanted.lower() in ("all", "全部"):
        picked = [r for r in rows if r.get("无感") == "是" and r.get("_nosense_uuid")]
        if not picked:
            raise QueryError("当前没有已开启无感认证的设备")
        return picked
    if wanted.lower() in ("current", "本机"):
        row = next((r for r in rows if r.get("本机") == "是"), None)
        if row is None or row.get("无感") != "是" or not row.get("_nosense_uuid"):
            raise QueryError("本机当前未开启无感认证")
        return [row]
    if wanted.isdigit() and len(wanted) <= 4:
        index = int(wanted)
        if index < 1 or index > len(rows):
            raise QueryError("设备编号超出范围")
        row = rows[index - 1]
        if row.get("无感") != "是" or not row.get("_nosense_uuid"):
            raise QueryError("该设备未开启无感认证")
        return [row]
    mac = normalize_mac(wanted)
    if mac:
        row = next((r for r in rows if normalize_mac(r.get("MAC")) == mac), None)
        if row is None or row.get("无感") != "是" or not row.get("_nosense_uuid"):
            raise QueryError("该设备未开启无感认证")
        return [row]
    raise QueryError("设备编号或 MAC 地址无法识别")


def _enable_nosense_session(session: requests.Session, base: str, before: dict,
                            selector: str | None = "current",
                            service: str | None = None,
                            wait: float = KICK_VERIFY_SECONDS,
                            interval: float = KICK_VERIFY_INTERVAL) -> dict:
    rows = before.get("rows") or []
    mac, target_row = select_nosense_target(rows, selector)
    if service and service.strip():
        desired_label, desired_uuid = resolve_default_service(service)
    elif target_row and target_row.get("_service_uuid"):
        desired_uuid = target_row["_service_uuid"]
        desired_label = target_row.get("缺省服务") or _UUID_TO_DEFAULT_SERVICE.get(desired_uuid, "套餐默认服务")
    else:
        desired_label, desired_uuid = "套餐默认服务", DEFAULT_SERVICE_PACKAGE

    bound_uuids = [r["_nosense_uuid"] for r in rows
                   if r.get("无感") == "是" and r.get("_nosense_uuid")]
    if bound_uuids:
        fetch(session, base, NOSENSE_UNBIND, {"noSenseUuids": bound_uuids})

    fetch(session, base, NOSENSE_REGISTER,
          {"userMac": mac, "expireTime": 7, "expireUnit": "day"})

    if desired_uuid != DEFAULT_SERVICE_PACKAGE:
        fetch(session, base, DEVICE_MODIFY, {
            "userMac": mac,
            "name": (target_row.get("设备名称") if target_row else "") or "我的设备",
            "location": (target_row.get("_location") if target_row else "") or "",
            "defaultServiceOperaporsConfigUuid": desired_uuid,
            "terminalType": target_row.get("_terminal_type", 1) if target_row else 1,
        })

    deadline = time.monotonic() + wait
    verified_row = None
    after = before
    while True:
        after = parse_devices(fetch(session, base, DEVICES))
        candidate = next((r for r in after["rows"] if normalize_mac(r.get("MAC")) == mac), None)
        if candidate and candidate.get("无感") == "是":
            if desired_uuid == DEFAULT_SERVICE_PACKAGE or candidate.get("_service_uuid") == desired_uuid:
                verified_row = candidate
                break
        if time.monotonic() >= deadline:
            break
        time.sleep(interval)

    if verified_row is None:
        raise NoSenseVerifyError(f"无感认证请求已提交，但设备 {mac} 状态未确认生效")

    return {
        "action": "nosense",
        "mac": mac,
        "bind_no_sense": True,
        "expires": verified_row.get("无感到期") or "",
        "service": verified_row.get("缺省服务") or desired_label,
        "renewed": bool(bound_uuids),
        "rows": after["rows"],
    }


def enable_nosense(base: str, cas_host: str, username: str, password: str,
                   selector: str | None = "current", *,
                   service: str | None = None,
                   debug: bool = False, fresh: bool = False) -> dict:
    """Enable or renew seamless authentication for a device (replacing any existing binding)."""
    session = open_session(base, cas_host, username, password, debug=debug, fresh=fresh)
    try:
        before = parse_devices(fetch(session, base, DEVICES))
        return _enable_nosense_session(session, base, before, selector=selector, service=service)
    except Exception:
        clear_session()
        raise


def disable_nosense(base: str, cas_host: str, username: str, password: str,
                    selector: str | None = "all", *,
                    debug: bool = False, fresh: bool = False) -> dict:
    """Disable seamless authentication and verify the binding is removed."""
    session = open_session(base, cas_host, username, password, debug=debug, fresh=fresh)
    try:
        before = parse_devices(fetch(session, base, DEVICES))
        targets = select_nosense_unbind_targets(before["rows"], selector)
        uuids = [r["_nosense_uuid"] for r in targets]
        macs = [normalize_mac(r.get("MAC")) or r.get("MAC", "") for r in targets]
        fetch(session, base, NOSENSE_UNBIND, {"noSenseUuids": uuids})

        deadline = time.monotonic() + KICK_VERIFY_SECONDS
        while True:
            after = parse_devices(fetch(session, base, DEVICES))
            still = [r for r in after["rows"]
                     if r.get("无感") == "是"
                     and (r.get("_nosense_uuid") in uuids
                          or (normalize_mac(r.get("MAC")) or r.get("MAC", "")) in macs)]
            if not still or time.monotonic() >= deadline:
                break
            time.sleep(KICK_VERIFY_INTERVAL)
        if still:
            raise NoSenseVerifyError("关闭无感认证请求已提交，但门户仍显示已开启")
        return {"action": "unbind", "unbound": macs, "rows": after["rows"]}
    except Exception:
        clear_session()
        raise


def modify_device_service(base: str, cas_host: str, username: str, password: str,
                          selector: str | None = "current",
                          service: str = "套餐默认服务", *,
                          debug: bool = False, fresh: bool = False) -> dict:
    """Modify the default carrier service of a seamless-bound device and verify."""
    desired_label, desired_uuid = resolve_default_service(service)
    session = open_session(base, cas_host, username, password, debug=debug, fresh=fresh)
    try:
        before = parse_devices(fetch(session, base, DEVICES))
        mac, target_row = select_nosense_target(before["rows"], selector)
        if target_row is None or target_row.get("无感") != "是":
            raise QueryError("请先为该设备开启无感认证，再设置缺省服务")
        fetch(session, base, DEVICE_MODIFY, {
            "userMac": mac,
            "name": target_row.get("设备名称") or "我的设备",
            "location": target_row.get("_location") or "",
            "defaultServiceOperaporsConfigUuid": desired_uuid,
            "terminalType": target_row.get("_terminal_type", 1),
        })

        deadline = time.monotonic() + KICK_VERIFY_SECONDS
        verified_row = None
        after = before
        while True:
            after = parse_devices(fetch(session, base, DEVICES))
            candidate = next((r for r in after["rows"] if normalize_mac(r.get("MAC")) == mac), None)
            if candidate and candidate.get("_service_uuid") == desired_uuid:
                verified_row = candidate
                break
            if time.monotonic() >= deadline:
                break
            time.sleep(KICK_VERIFY_INTERVAL)
        if verified_row is None:
            raise NoSenseVerifyError("缺省服务修改已提交，但门户未确认生效")
        return {
            "action": "service",
            "mac": mac,
            "service": verified_row.get("缺省服务") or desired_label,
            "expires": verified_row.get("无感到期") or "",
            "rows": after["rows"],
        }
    except Exception:
        clear_session()
        raise


def renew_nosense(base: str, cas_host: str, username: str, password: str,
                  selector: str | None = "current", *,
                  service: str | None = None,
                  force: bool = False,
                  threshold: int = NOSENSE_RENEW_THRESHOLD,
                  debug: bool = False, fresh: bool = False) -> dict:
    """Check seamless auth validity and renew when unbound, expiring within threshold, or forced."""
    session = open_session(base, cas_host, username, password, debug=debug, fresh=fresh)
    try:
        before = parse_devices(fetch(session, base, DEVICES))
        mac, target_row = select_nosense_target(before["rows"], selector)
        now_ms = int(time.time() * 1000)
        end_ms = target_row.get("_nosense_end_ms") if target_row else None
        bound = bool(target_row and target_row.get("无感") == "是")
        remaining = max(0, int((end_ms - now_ms) // 1000)) if (bound and isinstance(end_ms, int)) else 0
        desired_uuid = resolve_default_service(service)[1] if (service and service.strip()) else ""
        service_mismatch = bool(desired_uuid and target_row and target_row.get("_service_uuid") != desired_uuid)

        if not force and bound and isinstance(end_ms, int) and remaining > threshold and not service_mismatch:
            return {
                "action": "renew",
                "renewed": False,
                "mac": mac,
                "bind_no_sense": True,
                "expires": target_row.get("无感到期") or "",
                "remaining_seconds": remaining,
                "service": target_row.get("缺省服务") or "套餐默认服务",
                "rows": before["rows"],
            }

        enabled = _enable_nosense_session(session, base, before, selector=mac, service=service)
        row = next((r for r in enabled["rows"] if normalize_mac(r.get("MAC")) == mac), None)
        new_end_ms = row.get("_nosense_end_ms") if row else None
        new_remaining = max(0, int((new_end_ms - int(time.time() * 1000)) // 1000)) if isinstance(new_end_ms, int) else 0
        return {
            "action": "renew",
            "renewed": True,
            "mac": mac,
            "bind_no_sense": True,
            "expires": enabled["expires"],
            "remaining_seconds": new_remaining,
            "service": enabled["service"],
            "rows": enabled["rows"],
        }
    except Exception:
        clear_session()
        raise


def format_nosense(result: dict) -> str:
    """Format seamless auth / default service / renewal result for CLI."""
    action = result.get("action")
    if action == "unbind":
        macs = "、".join(result.get("unbound") or []) or "无"
        return f"已关闭无感认证：{macs}"
    if action == "service":
        return (f"已更新无感缺省服务：{result.get('mac')} → {result.get('service')}"
                + (f"（到期 {result['expires']}）" if result.get("expires") else ""))
    if action == "renew" and not result.get("renewed"):
        hours = (result.get("remaining_seconds") or 0) // 3600
        return (f"无感认证仍在有效期内，无需续约：{result.get('mac')}"
                f"（到期 {result.get('expires') or '—'}，剩余约 {hours} 小时，"
                f"缺省服务：{result.get('service') or '套餐默认服务'}）")
    verb = "已续约无感认证" if result.get("renewed") else "已开启无感认证"
    return (f"{verb}：{result.get('mac')}"
            f"（到期 {result.get('expires') or '—'}，"
            f"缺省服务：{result.get('service') or '套餐默认服务'}）")
