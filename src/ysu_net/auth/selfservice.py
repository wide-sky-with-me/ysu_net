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
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests

from .common import QueryError

SELF_PATH = "/self/index"

DEVICES = "/sam/api/userself/devices"
PACKAGE_OVERVIEW = "/sam/api/userself/package/overview"
PACKAGE_FLOW = "/sam/api/userself/package/flow"
REMEMBER_CURRENT = "/sam/api/userself/rememberService/current"
KICK_OFFLINE = "/sam/api/userself/devices/kick-offline/batch"
KICK_VERIFY_SECONDS = 12.0
KICK_VERIFY_INTERVAL = 3.0

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


def parse_devices(payload) -> dict:
    """Split online/offline devices into display rows; never invent values."""
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        raise QueryError("自助服务设备响应结构异常")
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
            # 核验用的原始标识，渲染时不显示
            row["_uuid"] = _text(item.get("onlineUserUuid"))
            row["_unified"] = item.get("unifiedAuthentication") is True
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


def save_session(session: requests.Session, base: str, username: str) -> None:
    """Persist the cookie jar for this origin+account; best effort."""
    data = {"version": 1, "base": base.rstrip("/"), "username": username,
            "saved_at": int(time.time()), "cookies": _jar(session)}
    try:
        path = cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(path.parent, 0o700)
        tmp = path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
        os.replace(tmp, path)
    except OSError:
        pass   # a cache miss only costs one extra login


def _portal_session() -> requests.Session:
    from .api import _new_portal_session

    return _new_portal_session()


def load_session(base: str, username: str, ttl: int = SESSION_TTL):
    """Return a session restored from cache, or None when unusable."""
    try:
        path = cache_path()
        if not path.is_file() or path.stat().st_size > _CACHE_MAX_BYTES:
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("version") != 1:
        return None
    if data.get("base") != base.rstrip("/") or data.get("username") != username:
        return None
    saved_at = data.get("saved_at")
    if not isinstance(saved_at, int) or time.time() - saved_at > ttl:
        return None
    cookies = data.get("cookies")
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
    return session


def clear_session() -> None:
    try:
        cache_path().unlink()
    except OSError:
        pass


def _still_authorised(session: requests.Session, base: str, timeout: int = 15) -> bool:
    """One lightweight GET decides whether the cached jar still works."""
    try:
        r = session.get(self_service_url(base), timeout=timeout, allow_redirects=True)
    except requests.RequestException:
        return False
    return r.status_code == 200 and _is_self_url(r.url)


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
            clear_session()   # stale: drop it so the next run does not retry it

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
# Writes.  The portal's device page is a control console; kick-offline is the
# only state-changing endpoint this module touches.
#
# Contract, read from /self/assets/myDevices-*.js (2026-11-09):
#   kick-offline/batch  {onlineUserUuids: [...], kickUnifiedAuthOffline: bool}
# The SPA derives `kickUnifiedAuthOffline` as `!au || tu`, where `au` becomes
# true when the target is the current device that logged in through unified
# auth.  So kicking yourself keeps your SSO session (you can log back in),
# while kicking another device also ends that device's SSO session.
# ---------------------------------------------------------------------------

class KickVerifyError(QueryError):
    """The write returned OK but the device is still online."""


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
    """Re-read the device list until the targets are gone or the budget runs out.

    The portal updates the online list asynchronously: an immediate re-read can
    still show the device the write has just removed, so a single check reports
    a false failure.
    """
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
