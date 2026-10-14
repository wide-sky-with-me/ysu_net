#!/usr/bin/env python3
"""
燕山大学校园网登录（auth1.ysu.edu.cn）

命令：
  login  : 必要时走统一认证(cer.ysu.edu.cn)登录，然后 serviceLogin + userOnline 上线
  info   : 查询在线状态 + 账户信息（在线时展示：用户/IP/SSID/运营商/在线设备/流量等）
  logout : 调用真实下线接口 /eportal/network/offline 下线（失败再尝试 UI 点击“下线”）

账号密码：
  - 环境变量：YSU_USER / YSU_PASS
  - 命令行：-u/--user  -p/--password（login 必填；info/logout 不需要）

示例：
  export YSU_USER="******"
  export YSU_PASS="******"

  python -m ysu_net.auth.browser login --service 校园网 --debug
  python -m ysu_net.auth.browser info --debug
  python -m ysu_net.auth.browser info --raw
  python -m ysu_net.auth.browser logout --debug
"""

from __future__ import annotations

import argparse
import getpass
import json

import re
from urllib.parse import parse_qsl, quote
import os
import sys
import time
from dataclasses import dataclass
from typing import Any, Optional
from urllib.parse import parse_qs, urlparse

from ysu_net.auth.account import (
    format_account_info as format_info,
    summarize_account_payload,
)
from ysu_net.auth.common import (
    InteractionRequired,
    OperationFailed,
    QueryError,
    check_action,
    managed_resources,
    online_state,
    require_online_service,
    track_resource,
)

from playwright.sync_api import sync_playwright


@dataclass(frozen=True)
class Urls:
    base: str
    cas_host: str

    @property
    def route_root(self) -> str:
        return f"{self.base}/"

    @property
    def api_get_online(self) -> str:
        return f"{self.base}/eportal/adaptor/getOnlineUserInfo"

    @property
    def api_get_node(self) -> str:
        return f"{self.base}/eportal/workFlow/getCurrentNode"

    @property
    def api_service_login(self) -> str:
        return f"{self.base}/eportal/network/serviceLogin"

    @property
    def api_user_online(self) -> str:
        return f"{self.base}/eportal/network/userOnline"

    @property
    def api_get_account_info(self) -> str:
        return f"{self.base}/eportal/operator/getAccountInfo"

    @property
    def api_offline(self) -> str:
        return f"{self.base}/eportal/network/offline"

    def with_overrides(self, base: str | None, cas_host: str | None) -> "Urls":
        b = (base or self.base).rstrip("/")
        c = (cas_host or self.cas_host).rstrip("/")
        return Urls(base=b, cas_host=c)


URLS = Urls(
    base=os.getenv("YSU_BASE", "https://auth1.ysu.edu.cn").strip().rstrip("/"),
    cas_host=os.getenv("YSU_CAS_HOST", "https://cer.ysu.edu.cn").strip().rstrip("/"),
)

VERSION_TAG = os.getenv("YSU_VERSION", "this is a git-commit").strip()

VERIFY_TLS = os.getenv("YSU_VERIFY_TLS", "1").strip().lower() in ("1", "true", "yes")
SAVE_DEBUG_FILES = os.getenv("YSU_SAVE_DEBUG_FILES", "0").strip().lower() in (
    "1",
    "true",
    "yes",
)
PORTAL_USER_AGENT = os.getenv("YSU_PORTAL_UA", "").strip() or None

NAV_TIMEOUT = 60_000
REQ_TIMEOUT = 30_000
ACTION_TIMEOUT = 15_000


def _mask_kv_form(post_data: str) -> str:
    """
    把 password/captcha 等敏感字段打码，保留结构用于复刻对比。
    """
    if not post_data:
        return post_data
    try:
        kv = parse_qsl(post_data, keep_blank_values=True)
        masked = []
        for k, v in kv:
            lk = k.lower()
            if lk in ("password", "captcha", "pwd", "pass", "smscode", "otp"):
                masked.append((k, "<redacted>"))
            elif lk in ("username", "user", "userid"):
                # 可选：用户名也稍微打码
                if len(v) > 4:
                    masked.append((k, v[:2] + "****" + v[-2:]))
                else:
                    masked.append((k, v))
            else:
                masked.append((k, v))
        return "&".join([f"{k}={v}" for k, v in masked])
    except Exception:
        # 兜底：正则打码
        s = re.sub(r"(password=)[^&]*", r"\1<redacted>", post_data, flags=re.I)
        s = re.sub(r"(captcha=)[^&]*", r"\1<redacted>", s, flags=re.I)
        return s


def dump_cookies(ctx, label: str, debug: bool) -> None:
    """
    打印并保存 context cookies（只看 cer/auth1 域）。
    """
    if not debug:
        return
    try:
        cookies = ctx.cookies()
    except Exception as e:
        print(f"[COOKIE] dump failed: {e}")
        return

    base_host = urlparse(URLS.base).netloc
    cas_host = urlparse(URLS.cas_host).netloc
    focus = []
    for c in cookies:
        dom = c.get("domain") or ""
        if (base_host and base_host in dom) or (cas_host and cas_host in dom):
            focus.append(
                {
                    "domain": dom,
                    "path": c.get("path"),
                    "name": c.get("name"),
                    "value": c.get("value"),
                    "httpOnly": c.get("httpOnly"),
                    "secure": c.get("secure"),
                    "sameSite": c.get("sameSite"),
                    "expires": c.get("expires"),
                }
            )

    print(f"[COOKIE] {label} count={len(focus)}")
    for c in focus:
        # value 也可能敏感，这里只打印前 12 个字符
        v = c["value"] or ""
        v_show = (v[:12] + "..." + v[-6:]) if len(v) > 24 else v
        print(
            f"  - {c['domain']} {c['name']}={v_show} path={c['path']} samesite={c['sameSite']} httpOnly={c['httpOnly']}"
        )

    if SAVE_DEBUG_FILES:
        try:
            with open(f"cookies_{label}.json", "w", encoding="utf-8") as f:
                json.dump(focus, f, ensure_ascii=False, indent=2)
            print(f"[DEBUG] saved cookies_{label}.json")
        except Exception:
            pass


def now_ms() -> int:
    return int(time.time() * 1000)


def dprint(debug: bool, *args: Any) -> None:
    if debug:
        print(*args)


_SERVICE_LIST: tuple[str, ...] = ("校园网", "中国移动", "中国联通", "中国电信")
_SERVICE_ALIASES: dict[str, str] = {
    "校园网": "校园网",
    "campus": "校园网",
    "campusnet": "校园网",
    "ysu": "校园网",
    "1": "校园网",
    "中国移动": "中国移动",
    "移动": "中国移动",
    "cmcc": "中国移动",
    "2": "中国移动",
    "中国联通": "中国联通",
    "联通": "中国联通",
    "cucc": "中国联通",
    "unicom": "中国联通",
    "3": "中国联通",
    "中国电信": "中国电信",
    "电信": "中国电信",
    "ctcc": "中国电信",
    "telecom": "中国电信",
    "4": "中国电信",
}


def normalize_service(service: str | None) -> str | None:
    if service is None:
        return None
    s = str(service).strip()
    if not s:
        return None
    key = s.lower().replace(" ", "")
    return (
        _SERVICE_ALIASES.get(key)
        or _SERVICE_ALIASES.get(s)
        or _SERVICE_ALIASES.get(s.strip())
    )


def _prompt_service(default_service: str | None = None) -> str:
    d = normalize_service(default_service) or "校园网"
    while True:
        print("可选服务：")
        for i, name in enumerate(_SERVICE_LIST, start=1):
            mark = " *" if name == d else ""
            print(f"  {i}. {name}{mark}")
        inp = input(f"选择服务（回车默认 {d}）: ").strip()
        if not inp:
            return d
        picked = normalize_service(inp)
        if picked:
            return picked
        print("无效输入，请输入 1-4 或服务名（校园网/中国移动/中国联通/中国电信）。")


def extract_q(url: str, key: str) -> Optional[str]:
    try:
        qs = parse_qs(urlparse(url).query)
        v = qs.get(key)
        if v:
            return v[0]
    except Exception:
        pass
    return None


def safe_goto(page, url: str, debug: bool, timeout: int = NAV_TIMEOUT) -> None:
    """允许被重定向打断的 goto（auth1 -> cer 场景常见）"""
    try:
        dprint(debug, f"[NAV] goto {url}")
        page.goto(url, wait_until="domcontentloaded", timeout=timeout)
    except Exception as e:
        msg = str(e)
        # Playwright 在连续重定向/并发导航下经常抛这个；对我们不致命
        if "interrupted by another navigation" in msg or "Navigation to" in msg:
            dprint(debug, f"[NAV] interrupted (ok): {msg.splitlines()[0]}")
        else:
            raise


def api_post_json(ctx_request, url: str, payload: dict, debug: bool) -> tuple[int, Any]:
    body = json.dumps(payload, ensure_ascii=False)
    dprint(debug, f"[API] POST {url} keys={list(payload.keys())}")
    resp = ctx_request.post(
        url,
        data=body,
        headers={
            "Content-Type": "application/json;charset=UTF-8",
            "Accept": "application/json, text/plain, */*",
        },
        timeout=REQ_TIMEOUT,
    )
    try:
        return resp.status, resp.json()
    except Exception:
        return resp.status, resp.text()


def api_get_json(ctx_request, url: str, debug: bool) -> tuple[int, Any]:
    dprint(debug, f"[API] GET  {url}")
    resp = ctx_request.get(url, timeout=REQ_TIMEOUT)
    try:
        return resp.status, resp.json()
    except Exception:
        return resp.status, resp.text()


def get_current_node(ctx_request, session_id: str, debug: bool) -> Optional[str]:
    st, data = api_post_json(
        ctx_request,
        URLS.api_get_node,
        {"sessionId": session_id, "flowKey": "portal_auth"},
        debug=debug,
    )
    if st != 200 or not isinstance(data, dict):
        return None
    return (data.get("data") or {}).get("currentNodePath")


def get_online_info(ctx_request, session_id: str, debug: bool) -> Optional[dict]:
    url = (
        f"{URLS.api_get_online}"
        f"?sessionId={session_id}&t={now_ms()}&version={quote(VERSION_TAG, safe='')}"
    )
    st, data = api_get_json(ctx_request, url, debug=debug)
    if st != 200 or not isinstance(data, dict):
        raise QueryError(f"在线状态查询失败（HTTP {st}）")
    online_state(data)
    return data


def get_account_info(ctx_request, session_id: str, debug: bool) -> tuple[int, Any]:
    return api_post_json(
        ctx_request, URLS.api_get_account_info, {"sessionId": session_id}, debug=debug
    )


def is_online(online_info) -> bool:
    return online_state(online_info)


def online_fields(online_info: dict) -> dict:
    pu = ((online_info.get("data") or {}).get("portalOnlineUserInfo")) or {}
    out = {}
    for k in [
        "result",
        "message",
        "userName",
        "userId",
        "userIp",
        "ssid",
        "realServiceName",
        "service",
        "userIndex",
    ]:
        if k in pu and pu.get(k) not in (None, "", []):
            out[k] = pu.get(k)
    return out


@dataclass
class Session:
    session_id: str


class SessionSniffer:
    """
    从命中请求的 URL/query 里提取 sessionId/flowSessionId
    + 额外抓 CAS 登录关键请求/响应（用于复刻 requests）
    """

    def __init__(self, debug: bool):
        self.debug = debug
        self.session_id: Optional[str] = None
        self.flow_session_id: Optional[str] = None

    def _is_offline_url(self, url: str) -> bool:
        return "/eportal/network/offline" in url

    def _is_onlineinfo_url(self, url: str) -> bool:
        return "/eportal/adaptor/getOnlineUserInfo" in url

    def _is_cas_login_url(self, url: str) -> bool:
        return (URLS.cas_host.rstrip("/") + "/authserver/login") in url

    def _is_auth1_cas_sso(self, url: str) -> bool:
        return (URLS.base.rstrip("/") + "/cas-sso") in url

    def on_request(self, req) -> None:
        url = req.url

        sid = extract_q(url, "sessionId")
        fsid = extract_q(url, "flowSessionId")
        if sid:
            self.session_id = sid
        if fsid:
            self.flow_session_id = fsid

        if not self.debug:
            return

        m = req.method.upper()

        if self._is_offline_url(url):
            print(f"[TRACE][REQ][OFFLINE] {m} {url}")
            try:
                h = req.headers
                # 建议全部打印（量不大）
                print(f"[TRACE][REQ][OFFLINE] headers={h}")
            except Exception as e:
                print(f"[TRACE][REQ][OFFLINE] headers read failed: {e}")

            if m == "POST":
                try:
                    pd = req.post_data or ""
                    print(f"[TRACE][REQ][OFFLINE] postData={pd}")
                    if SAVE_DEBUG_FILES:
                        with open("offline_postdata.txt", "w", encoding="utf-8") as f:
                            f.write(pd)
                        print("[DEBUG] saved offline_postdata.txt")
                except Exception as e:
                    print(f"[TRACE][REQ][OFFLINE] postData read failed: {e}")

            return

        # （可选）你也可以顺便把 getOnlineUserInfo 抓一下，看它请求头/cookie差异
        if self._is_onlineinfo_url(url):
            print(f"[TRACE][REQ][ONLINE] {m} {url}")
            try:
                print(f"[TRACE][REQ][ONLINE] headers={req.headers}")
            except Exception:
                pass
            return

        if self._is_cas_login_url(url) or self._is_auth1_cas_sso(url):
            print(f"[TRACE][REQ] {m} {url}")
            try:
                h = req.headers
                # 只打印关键信息，避免太吵
                keep = [
                    "user-agent",
                    "referer",
                    "origin",
                    "content-type",
                    "accept",
                    "sec-fetch-site",
                    "sec-fetch-mode",
                    "sec-fetch-dest",
                ]
                hk = {k: v for k, v in h.items() if k.lower() in keep}
                print(f"[TRACE][REQ] headers={hk}")
            except Exception:
                pass

            if m == "POST":
                try:
                    pd = req.post_data or ""
                    print(f"[TRACE][REQ] postData={_mask_kv_form(pd)[:2000]}")
                    if SAVE_DEBUG_FILES:
                        with open("cas_postdata.txt", "w", encoding="utf-8") as f:
                            f.write(_mask_kv_form(pd))
                        print("[DEBUG] saved cas_postdata.txt")
                except Exception as e:
                    print(f"[TRACE][REQ] postData read failed: {e}")

        # 原来的 capture 也保留（可选）
        # print(f"[CAPTURE] {m} {url}")

    def on_response(self, resp) -> None:
        if not self.debug:
            return
        try:
            url = resp.url
            st = resp.status

            if self._is_offline_url(url):
                print(f"[TRACE][RESP][OFFLINE] {st} {url}")
                try:
                    h = resp.headers
                    print(f"[TRACE][RESP][OFFLINE] headers={h}")
                except Exception:
                    pass
                # 读 body（有些响应可能无法读或不是 json，try 一下）
                try:
                    txt = resp.text()
                    print(f"[TRACE][RESP][OFFLINE] body={txt[:2000]}")
                    if SAVE_DEBUG_FILES:
                        with open("offline_resp.txt", "w", encoding="utf-8") as f:
                            f.write(txt)
                        print("[DEBUG] saved offline_resp.txt")
                except Exception as e:
                    print(f"[TRACE][RESP][OFFLINE] body read failed: {e}")
                return

            # 可选：抓 onlineinfo 响应
            if self._is_onlineinfo_url(url):
                print(f"[TRACE][RESP][ONLINE] {st} {url}")
                return

            if self._is_cas_login_url(url) or self._is_auth1_cas_sso(url):
                print(f"[TRACE][RESP] {st} {url}")
                try:
                    h = resp.headers
                    loc = h.get("location") or h.get("Location")
                    if loc:
                        print(f"[TRACE][RESP] Location: {loc}")
                    # Set-Cookie 通常不会直接给你完整，但有时能看到
                    sc = h.get("set-cookie") or h.get("Set-Cookie")
                    if sc:
                        print(f"[TRACE][RESP] Set-Cookie: {sc[:300]}")
                except Exception:
                    pass
        except Exception:
            pass


def obtain_session_id(page, sniffer: SessionSniffer) -> Optional[str]:
    return (
        sniffer.session_id
        or sniffer.flow_session_id
        or extract_q(page.url, "sessionId")
        or extract_q(page.url, "flowSessionId")
    )


def _playwright():
    """sync_playwright() with a Node.js runtime selected for desktop bundles."""
    from .node_runtime import configure

    if not configure():
        raise RuntimeError(
            "浏览器认证组件未安装：请在图形界面“设置 → 认证方式”中下载，或改用 API 认证"
        )
    return sync_playwright()


def _launch_chromium(p, *, headless: bool, debug: bool):
    """Prefer an explicit YSU_BROWSER_PATH, then Playwright's Chromium, then Edge/Chrome."""
    from .system_browser import ENV, find_system_browser

    if os.getenv(ENV, "").strip():
        found = find_system_browser()
        if not found:
            raise RuntimeError(f"{ENV} 指向的浏览器不存在")
        dprint(debug, f"[BROWSER] {found[0]}: {found[1]}")
        return p.chromium.launch(headless=headless, executable_path=str(found[1]))
    try:
        return p.chromium.launch(headless=headless)
    except Exception as exc:
        # Only a missing download falls back; other launch failures stay visible.
        found = find_system_browser() if "Executable doesn't exist" in str(exc) else None
        if not found:
            if "Executable doesn't exist" in str(exc):
                raise RuntimeError(
                    "未找到可用浏览器：请安装 Microsoft Edge 或 Google Chrome，"
                    "或运行 playwright install chromium"
                ) from None
            raise
        dprint(debug, f"[BROWSER] 使用系统浏览器 {found[0]}: {found[1]}")
        return p.chromium.launch(headless=headless, executable_path=str(found[1]))


def open_portal_and_get_session(debug: bool, headed: bool):
    """
    打开 portal，拿到 sessionId，并返回 (Session, (playwright, browser), context, page)
    """
    p = _playwright().start()
    track_resource(p.stop)
    browser = _launch_chromium(p, headless=(not headed), debug=debug)
    track_resource(browser.close)
    ctx_kwargs: dict[str, Any] = {"ignore_https_errors": (not VERIFY_TLS)}
    if PORTAL_USER_AGENT:
        ctx_kwargs["user_agent"] = PORTAL_USER_AGENT
    ctx = browser.new_context(**ctx_kwargs)
    track_resource(ctx.close)
    page = ctx.new_page()

    sniffer = SessionSniffer(debug=debug)
    page.on("request", sniffer.on_request)
    page.on("response", sniffer.on_response)
    safe_goto(page, URLS.route_root, debug=debug, timeout=NAV_TIMEOUT)
    page.wait_for_timeout(800)

    sid = obtain_session_id(page, sniffer)
    if not sid:
        raise RuntimeError("无法获取 sessionId（建议加 --debug 查看请求链路）。")

    dprint(debug, f"[INFO] sessionId={sid}")
    return Session(session_id=sid), (p, browser), ctx, page


def _detect_cas_block_reason(page) -> Optional[str]:
    try:
        t = page.title() or ""
        if "IP被冻结" in t:
            return "IP被冻结"
    except Exception:
        pass

    try:
        if page.locator("text=IP被冻结").count() > 0:
            return "IP被冻结"
    except Exception:
        pass

    try:
        url = page.url or ""
        if "noSupport" in url:
            return "浏览器不受支持"
    except Exception:
        pass

    return None


def _first_locator_in_any_frame(page, selector: str):
    try:
        loc = page.locator(selector)
        if loc.count() > 0:
            return loc.first
    except Exception:
        pass

    try:
        frames = page.frames
    except Exception:
        frames = []

    for fr in frames:
        try:
            if fr == page.main_frame:
                continue
        except Exception:
            pass
        try:
            loc2 = fr.locator(selector)
            if loc2.count() > 0:
                return loc2.first
        except Exception:
            continue

    return page.locator(selector).first


def ui_cas_login(page, user: str, pwd: str, debug: bool) -> None:
    # ✅ 日志验证过的 tab 文案：账号
    try:
        tab = page.get_by_text("账号", exact=False).first
        if tab.is_visible(timeout=1000):
            tab.click(timeout=ACTION_TIMEOUT)
            dprint(debug, "[UI] tab '账号'")
    except Exception:
        pass

    page.wait_for_timeout(300)

    block_reason = _detect_cas_block_reason(page)
    if block_reason == "IP被冻结":
        if debug and SAVE_DEBUG_FILES:
            try:
                html = page.content()
                with open("cas_blocked.html", "w", encoding="utf-8") as f:
                    f.write(html)
                page.screenshot(path="cas_blocked.png", full_page=True)
                print("[DEBUG] saved cas_blocked.html / cas_blocked.png")
            except Exception:
                pass
        raise InteractionRequired(
            "CAS 页面提示“IP被冻结”，导致找不到登录输入框。请稍后再试，或换网络/联系管理员解除。"
        )

    username_sel = "input#username, input[name='username'], input[name='userName'], input[autocomplete='username']"
    password_sel = "input#password, input[name='password'], input[type='password'], input[autocomplete='current-password']"
    submit_sel = "#login_submit, button#login_submit, input#login_submit, button:has-text('登录'), input[type='submit']"

    try:
        _first_locator_in_any_frame(page, username_sel).fill(
            user, timeout=ACTION_TIMEOUT
        )
        _first_locator_in_any_frame(page, password_sel).fill(
            pwd, timeout=ACTION_TIMEOUT
        )
        _first_locator_in_any_frame(page, submit_sel).click(timeout=ACTION_TIMEOUT)
    except Exception as e:
        if debug and SAVE_DEBUG_FILES:
            try:
                html = page.content()
                with open("cas_ui_fail.html", "w", encoding="utf-8") as f:
                    f.write(html)
                page.screenshot(path="cas_ui_fail.png", full_page=True)
                print("[DEBUG] saved cas_ui_fail.html / cas_ui_fail.png")
            except Exception:
                pass
        raise RuntimeError(f"CAS UI 自动填写失败：{e}")

    dprint(debug, "[UI] submitted CAS login")
    try:
        page.wait_for_load_state("domcontentloaded", timeout=30_000)
    except Exception:
        pass


@managed_resources
def cmd_login(
    service: str, user: str, pwd: str, debug: bool, max_wait: int, headed: bool
) -> None:
    svc = normalize_service(service)
    if not svc:
        raise RuntimeError(
            "service 无效：校园网/中国移动/中国联通/中国电信 或 1-4/移动/联通/电信"
        )
    session, (p, browser), ctx, page = open_portal_and_get_session(
        debug=debug, headed=headed
    )
    sid = session.session_id

    # 已在线直接返回
    online = get_online_info(ctx.request, sid, debug=debug)
    if online and is_online(online):
        require_online_service(online, svc)
        print("[OK] already online")
        # 在线的话也尽量带上 account
        _, acc = get_account_info(ctx.request, sid, debug=debug)
        print(format_info(online, acc))
        return

    node = get_current_node(ctx.request, sid, debug=debug)
    dprint(debug, f"[INFO] node={node} url={page.url}")

    # 需要 CAS 则 UI 登录
    if ((URLS.cas_host.rstrip("/") + "/authserver/login") in page.url) or (
        node == "authenticate"
    ):
        dump_cookies(ctx, "before_cas_login", debug=debug)
        dprint(debug, "[STEP] CAS login (UI)")
        ui_cas_login(page, user, pwd, debug=debug)
        # 等待 CAS -> auth1 的跳转链稳定下来
        try:
            page.wait_for_load_state("domcontentloaded", timeout=30_000)
        except Exception:
            pass
        page.wait_for_timeout(1200)
        dump_cookies(ctx, "after_cas_login", debug=debug)

    # serviceSelection -> 上线
    node = get_current_node(ctx.request, sid, debug=debug)
    dprint(debug, f"[INFO] after CAS node={node}")
    if node == "authenticate":
        raise InteractionRequired("统一认证后仍要求登录，请检查账号密码、验证码或风控状态")

    if node == "serviceSelection":
        st, response = api_post_json(
            ctx.request,
            URLS.api_service_login,
            {"sessionId": sid, "service": svc},
            debug=debug,
        )
        check_action(st, response, "选择服务")
        st, response = api_post_json(
            ctx.request, URLS.api_user_online, {"sessionId": sid}, debug=debug
        )
        check_action(st, response, "上线")

    # 等待 online
    deadline = time.monotonic() + max_wait
    last = None
    while time.monotonic() < deadline:
        last = get_online_info(ctx.request, sid, debug=debug)
        if last and is_online(last):
            require_online_service(last, svc)
            print("[OK] 已在线")
            _, acc = get_account_info(ctx.request, sid, debug=debug)
            print(format_info(last, acc))
            break
        time.sleep(2)
    else:
        raise OperationFailed("登录超时，未确认在线")


@managed_resources
def cmd_info(debug: bool, raw: bool, headed: bool) -> None:
    session, (p, browser), ctx, _page = open_portal_and_get_session(
        debug=debug, headed=headed
    )
    sid = session.session_id

    online = get_online_info(ctx.request, sid, debug=debug)

    acc = None
    st_acc = None
    if online and is_online(online):
        st_acc, acc = get_account_info(ctx.request, sid, debug=debug)

    if raw:
        out = {"online": online, "account_http_status": st_acc, "account": acc}
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print(format_info(online, acc))


@managed_resources
def cmd_status(debug: bool, raw: bool, headed: bool) -> bool:
    session, (p, browser), ctx, _page = open_portal_and_get_session(
        debug=debug, headed=headed
    )
    sid = session.session_id
    online = get_online_info(ctx.request, sid, debug=debug)
    ok = bool(online and is_online(online))
    if raw:
        out = {"online": online, "is_online": ok}
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print("online" if ok else "offline")
    return ok


@managed_resources
def cmd_logout(debug: bool, max_wait: int, headed: bool) -> None:
    session, (p, browser), ctx, page = open_portal_and_get_session(
        debug=debug, headed=headed
    )
    sid = session.session_id

    online = get_online_info(ctx.request, sid, debug=debug)
    if not (online and is_online(online)):
        print("[OK] 当前已离线")
        print(format_info(online, None))
        return

    # ✅ 优先走真实 API 下线
    dump_cookies(ctx, "before_offline", debug=debug)
    st, data = api_post_json(
        ctx.request, URLS.api_offline, {"sessionId": sid}, debug=debug
    )
    dprint(debug, f"[INFO] offline api status={st} resp_type={type(data).__name__}")
    dump_cookies(ctx, "after_offline", debug=debug)

    # 轮询直到离线
    deadline = time.monotonic() + max_wait
    last = None
    while time.monotonic() < deadline:
        last = get_online_info(ctx.request, sid, debug=debug)
        if last and (not is_online(last)):
            print("[OK] 已下线")
            print(format_info(last, None))
            return
        time.sleep(2)

    # API 不生效/慢：兜底尝试 UI 点击“下线”
    print("[WARN] API 下线未在限定时间内生效，尝试 UI 点击“下线”兜底。")
    try:
        finish_url = f"{URLS.base}/portal/entry/pc/finish;flowParams=undefined;from="
        safe_goto(page, finish_url, debug=debug, timeout=NAV_TIMEOUT)
        page.wait_for_timeout(800)

        page.get_by_text("下线", exact=False).first.click(timeout=ACTION_TIMEOUT)
        page.wait_for_timeout(300)
        page.get_by_text("确定", exact=False).first.click(timeout=ACTION_TIMEOUT)

        deadline = time.monotonic() + max_wait
        while time.monotonic() < deadline:
            last = get_online_info(ctx.request, sid, debug=debug)
            if last and (not is_online(last)):
                print("[OK] 已下线（UI 兜底成功）")
                print(format_info(last, None))
                break
            time.sleep(2)
        else:
            raise OperationFailed("下线超时，仍显示在线")
    except Exception as e:
        raise OperationFailed("UI 下线失败") from e


class YsuNetBrowserClient:
    def __init__(
        self,
        *,
        base: str | None = None,
        cas_host: str | None = None,
        version_tag: str | None = None,
        verify_tls: bool | None = None,
        save_debug_files: bool | None = None,
        portal_user_agent: str | None = None,
    ):
        self.urls = URLS.with_overrides(base, cas_host)
        self.version_tag = version_tag
        self.verify_tls = verify_tls
        self.save_debug_files = save_debug_files
        self.portal_user_agent = portal_user_agent

    def _apply(self) -> None:
        global URLS, VERSION_TAG, VERIFY_TLS, SAVE_DEBUG_FILES, PORTAL_USER_AGENT
        URLS = self.urls
        if self.version_tag is not None:
            VERSION_TAG = str(self.version_tag)
        if self.verify_tls is not None:
            VERIFY_TLS = bool(self.verify_tls)
        if self.save_debug_files is not None:
            SAVE_DEBUG_FILES = bool(self.save_debug_files)
        if self.portal_user_agent is not None:
            PORTAL_USER_AGENT = str(self.portal_user_agent)

    def login(
        self,
        *,
        service: str,
        user: str,
        password: str,
        debug: bool,
        max_wait: int,
        headed: bool,
    ) -> None:
        self._apply()
        cmd_login(
            service=service,
            user=user,
            pwd=password,
            debug=debug,
            max_wait=max_wait,
            headed=headed,
        )

    def info(self, *, debug: bool, raw: bool, headed: bool) -> None:
        self._apply()
        cmd_info(debug=debug, raw=raw, headed=headed)

    def logout(self, *, debug: bool, max_wait: int, headed: bool) -> None:
        self._apply()
        cmd_logout(debug=debug, max_wait=max_wait, headed=headed)


def build_parser() -> argparse.ArgumentParser:
    class NiceFormatter(
        argparse.RawTextHelpFormatter, argparse.ArgumentDefaultsHelpFormatter
    ):
        pass

    # 通用参数放在子命令后（例如：info --debug）
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "-u",
        "--user",
        default=os.getenv("YSU_USER", "").strip(),
        help="账号（默认读 YSU_USER）",
    )
    common.add_argument(
        "-p",
        "--password",
        default=os.getenv("YSU_PASS", ""),
        help="密码（默认读 YSU_PASS）",
    )
    common.add_argument("--debug", action="store_true", help="输出更多日志")
    common.add_argument(
        "--save-debug-files",
        dest="save_debug_files",
        action="store_true",
        default=None,
        help="允许保存调试文件到当前目录（默认关闭）",
    )
    common.add_argument(
        "--no-save-debug-files",
        dest="save_debug_files",
        action="store_false",
        default=None,
        help="禁止保存调试文件到当前目录",
    )
    common.add_argument(
        "--raw", action="store_true", help="输出完整 JSON（仅 info 有意义）"
    )
    common.add_argument(
        "--headed", action="store_true", help="有头模式（调试用；默认无头）"
    )
    common.add_argument(
        "--base",
        default=None,
        help="portal 根地址（默认读 YSU_BASE）",
    )
    common.add_argument(
        "--cas-host",
        default=None,
        help="CAS 根地址（默认读 YSU_CAS_HOST）",
    )
    common.add_argument(
        "--verify-tls",
        dest="verify_tls",
        action="store_true",
        default=None,
        help="启用 TLS 证书校验（默认开启）",
    )
    common.add_argument(
        "--no-verify-tls",
        dest="verify_tls",
        action="store_false",
        default=None,
        help="关闭 TLS 证书校验",
    )
    common.add_argument(
        "--ua",
        default=None,
        help="自定义浏览器 User-Agent（默认读 YSU_PORTAL_UA）",
    )
    common.add_argument(
        "--version-tag",
        default=None,
        help="version 查询参数（默认读 YSU_VERSION）",
    )
    common.add_argument(
        "--interactive",
        action="store_true",
        help="缺少账号/密码时使用交互输入（仅 login 需要）",
    )

    ap = argparse.ArgumentParser(
        prog="python -m ysu_net.auth.browser",
        formatter_class=NiceFormatter,
        description="燕山大学校园网登录脚本（auth1.ysu.edu.cn）——Playwright 无头浏览器版",
        epilog=(
            "Examples:\n"
            "  # 1) 登录上线\n"
            "  export YSU_USER='******'\n"
            "  export YSU_PASS='******'\n"
            "  python -m ysu_net.auth.browser login --service 校园网\n"
            "  python -m ysu_net.auth.browser login --service 校园网 --debug\n"
            "\n"
            "  # 2) 查询信息（离线提示/在线输出账户信息）\n"
            "  python -m ysu_net.auth.browser info\n"
            "  python -m ysu_net.auth.browser info --debug\n"
            "  python -m ysu_net.auth.browser info --raw\n"
            "\n"
            "  # 3) 下线\n"
            "  python -m ysu_net.auth.browser logout\n"
            "  python -m ysu_net.auth.browser logout --debug\n"
            "\n"
            "Tips:\n"
            "  - 通用参数 --debug/--raw/--headed 放在子命令后。\n"
            "    例如：python -m ysu_net.auth.browser info --debug\n"
        ),
    )

    sub = ap.add_subparsers(
        dest="cmd", required=True, metavar="{login,info,logout,status,shell}"
    )

    p_login = sub.add_parser(
        "login",
        parents=[common],
        help="登录并上线",
        formatter_class=NiceFormatter,
        epilog=(
            "Examples:\n"
            "  python -m ysu_net.auth.browser login --service 校园网\n"
            "  python -m ysu_net.auth.browser login --service 校园网 --debug\n"
            "  python -m ysu_net.auth.browser login --service 校园网 --headed --debug\n"
        ),
    )
    p_login.add_argument(
        "--service",
        default="校园网",
        help="服务名(校园网/中国移动/中国联通/中国电信)，也支持 1-4/移动/联通/电信/cmcc/cucc/ctcc",
    )
    p_login.add_argument("--max-wait", type=int, default=60, help="最多等待在线(秒)")

    sub.add_parser(
        "info",
        parents=[common],
        help="查看在线状态 + 账户信息",
        formatter_class=NiceFormatter,
        epilog=(
            "Examples:\n"
            "  python -m ysu_net.auth.browser info\n"
            "  python -m ysu_net.auth.browser info --debug\n"
            "  python -m ysu_net.auth.browser info --raw\n"
        ),
    )

    sub.add_parser(
        "status",
        parents=[common],
        help="仅判断是否在线（在线返回码 0，离线返回码 1）",
        formatter_class=NiceFormatter,
    )

    p_logout = sub.add_parser(
        "logout",
        parents=[common],
        help="下线",
        formatter_class=NiceFormatter,
        epilog=(
            "Examples:\n  python -m ysu_net.auth.browser logout\n  python -m ysu_net.auth.browser logout --debug\n"
        ),
    )
    p_logout.add_argument("--max-wait", type=int, default=30)

    sub.add_parser(
        "shell",
        parents=[common],
        help="交互式模式（login/info/logout/exit）",
        formatter_class=NiceFormatter,
    )

    return ap


def _apply_runtime_config(args: argparse.Namespace) -> None:
    global URLS, VERSION_TAG, VERIFY_TLS, SAVE_DEBUG_FILES, PORTAL_USER_AGENT
    URLS = URLS.with_overrides(
        getattr(args, "base", None), getattr(args, "cas_host", None)
    )

    if getattr(args, "version_tag", None):
        VERSION_TAG = str(args.version_tag)
    if getattr(args, "verify_tls", None) is not None:
        VERIFY_TLS = bool(args.verify_tls)
    if getattr(args, "save_debug_files", None) is not None:
        SAVE_DEBUG_FILES = bool(args.save_debug_files)
    if getattr(args, "ua", None):
        PORTAL_USER_AGENT = str(args.ua)


def _prompt_user_pass(user: str, password: str) -> tuple[str, str]:
    u = (user or "").strip()
    p = password or ""
    if not u:
        u = input("账号: ").strip()
    if not p:
        p = getpass.getpass("密码: ")
    return u, p


def _run_shell(args: argparse.Namespace) -> None:
    debug = bool(args.debug)
    headed = bool(args.headed)
    current_service = normalize_service(getattr(args, "service", None)) or "校园网"
    while True:
        try:
            cmdline = input("ysu-net(browser)> ").strip()
        except EOFError:
            print()
            return
        if not cmdline:
            continue
        if cmdline in ("exit", "quit", "q"):
            return
        if cmdline in ("help", "?"):
            print("commands: login, info, logout, status, service, exit")
            print("examples:")
            print("  login")
            print("  login 2")
            print("  service 中国移动")
            print("  logout")
            print("  info")
            print("  status")
            continue

        parts = cmdline.split()
        subcmd = parts[0].lower()
        if subcmd == "service":
            if len(parts) > 1:
                picked = normalize_service(parts[1])
                if picked:
                    current_service = picked
                    print(f"service={current_service}")
                else:
                    print("无效服务：校园网/中国移动/中国联通/中国电信 或 1-4")
            else:
                current_service = _prompt_service(current_service)
                print(f"service={current_service}")
            continue
        if subcmd == "login":
            if len(parts) > 1:
                picked = normalize_service(parts[1])
                if not picked:
                    print("无效服务：校园网/中国移动/中国联通/中国电信 或 1-4")
                    continue
                service = picked
            else:
                current_service = _prompt_service(current_service)
                service = current_service
            u, p = _prompt_user_pass(args.user, args.password)
            cmd_login(
                service=service,
                user=u,
                pwd=p,
                debug=debug,
                max_wait=60,
                headed=headed,
            )
            continue
        if subcmd == "info":
            cmd_info(debug=debug, raw=bool(args.raw), headed=headed)
            continue
        if subcmd == "status":
            cmd_status(debug=debug, raw=bool(args.raw), headed=headed)
            continue
        if subcmd == "logout":
            cmd_logout(debug=debug, max_wait=30, headed=headed)
            continue

        print("unknown command, type 'help'")


def main() -> None:
    ap = build_parser()
    args = ap.parse_args()

    debug = bool(args.debug)
    headed = bool(args.headed)
    _apply_runtime_config(args)

    if args.cmd == "login":
        if args.interactive:
            args.user, args.password = _prompt_user_pass(args.user, args.password)
            args.service = _prompt_service(getattr(args, "service", None))
        if not args.user or not args.password:
            ap.error(
                "login 需要账号密码：用 -u/-p 或环境变量 YSU_USER/YSU_PASS，或加 --interactive"
            )
        svc = normalize_service(getattr(args, "service", None))
        if not svc:
            ap.error(
                "service 无效：校园网/中国移动/中国联通/中国电信 或 1-4/移动/联通/电信"
            )
        cmd_login(
            service=svc,
            user=args.user,
            pwd=args.password,
            debug=debug,
            max_wait=int(args.max_wait),
            headed=headed,
        )
    elif args.cmd == "info":
        cmd_info(debug=debug, raw=bool(args.raw), headed=headed)
    elif args.cmd == "status":
        ok = cmd_status(debug=debug, raw=bool(args.raw), headed=headed)
        sys.exit(0 if ok else 1)
    elif args.cmd == "logout":
        cmd_logout(debug=debug, max_wait=int(args.max_wait), headed=headed)
    elif args.cmd == "shell":
        _run_shell(args)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[EXIT] cancelled", file=sys.stderr)
        sys.exit(130)
    except Exception as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(getattr(e, "exit_code", 2))


def self_check() -> int:
    """Launch the browser that login would use and render a local page; no network."""
    with _playwright() as p:
        browser = _launch_chromium(p, headless=True, debug=True)
        try:
            page = browser.new_page()
            page.set_content("<title>ysu-net 浏览器自检</title>")
            print(f"[OK] {page.title()} · Chromium {browser.version}")
        finally:
            browser.close()
    return 0
