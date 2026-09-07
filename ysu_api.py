#!/usr/bin/env python3
"""
燕山大学校园网登录（auth1.ysu.edu.cn）——纯 requests 版（无浏览器）

命令：
  login  : 登录上线（必要时走统一认证 cer.ysu.edu.cn）
  info   : 查看在线状态 + 账户信息
  logout : 调用 /eportal/network/offline 下线

依赖：
  pip install requests
  pip install pycryptodome  # 仅 login 需要
"""

from __future__ import annotations

import argparse
import base64
import getpass
import html as _html
import json
import os
import random
import re
import sys
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urljoin, urlparse

from ysu_common import (
    InteractionRequired,
    OperationFailed,
    QueryError,
    check_action,
    managed_resources,
    online_state,
    track_resource,
)

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


@dataclass(frozen=True)
class Urls:
    base: str
    cas_host: str

    @property
    def route_root(self) -> str:
        return f"{self.base}/"

    @property
    def entry_index(self) -> str:
        return f"{self.base}/eportal/index.jsp"

    @property
    def entry_redirect(self) -> str:
        return f"{self.base}/eportal/redirect.jsp"

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

    @property
    def sam_enable_info(self) -> str:
        return f"{self.base}/sam/api/protected/guest/enableConfig/info"

    @property
    def cas_check_need_captcha(self) -> str:
        return f"{self.cas_host}/authserver/checkNeedCaptcha.htl"

    @property
    def cas_get_captcha(self) -> str:
        return f"{self.cas_host}/authserver/getCaptcha.htl"

    def with_overrides(self, base: str | None, cas_host: str | None) -> "Urls":
        b = (base or self.base).rstrip("/")
        c = (cas_host or self.cas_host).rstrip("/")
        return Urls(base=b, cas_host=c)


URLS = Urls(
    base=os.getenv("YSU_BASE", "https://auth1.ysu.edu.cn").strip().rstrip("/"),
    cas_host=os.getenv("YSU_CAS_HOST", "https://cer.ysu.edu.cn").strip().rstrip("/"),
)

PORTAL_USER_AGENT = os.getenv(
    "YSU_PORTAL_UA",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) HeadlessChrome/145.0.7632.6 Safari/537.36",
).strip()

VERSION_TAG = os.getenv("YSU_VERSION", "this is a git-commit").strip()

VERIFY_TLS = os.getenv("YSU_VERIFY_TLS", "1").strip().lower() in ("1", "true", "yes")
SAVE_DEBUG_FILES = os.getenv("YSU_SAVE_DEBUG_FILES", "0").strip().lower() in (
    "1",
    "true",
    "yes",
)

REQ_TIMEOUT = int(os.getenv("YSU_TIMEOUT", "25").strip() or "25")

# CAS 侧加密需要用到的字符表
_AES_CHARS = "ABCDEFGHJKMNPQRSTWXYZabcdefhijkmnprstwxyz2345678"


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


def extract_q(url: str, key: str) -> str | None:
    try:
        qs = parse_qs(urlparse(url).query)
        v = qs.get(key)
        if v:
            return v[0]
    except Exception:
        pass
    return None


def _save_debug_text(debug: bool, name: str, content: str) -> None:
    if not (debug and SAVE_DEBUG_FILES):
        return
    try:
        with open(name, "w", encoding="utf-8", errors="ignore") as f:
            f.write(content or "")
        print(f"[DEBUG] saved {name}")
    except Exception:
        pass


def _random_string(n: int) -> str:
    return "".join(random.choice(_AES_CHARS) for _ in range(n))


def _pkcs7_pad(data: bytes, block: int = 16) -> bytes:
    pad = block - (len(data) % block)
    return data + bytes([pad]) * pad


def cas_encrypt_password(plain_pwd: str, salt: str) -> str:
    """
    CAS 登录页前端用 JS 对密码做 AES-CBC(PKCS7) 加密，这里用 pycryptodome 复刻。

    加密逻辑（与 encrypt.js 对齐）：
      Base64(AES_CBC_PKCS7(randomString(64)+password, key=salt, iv=randomString(16)))
    """
    try:
        from Crypto.Cipher import AES  # pycryptodome
    except Exception as e:
        raise RuntimeError("缺少依赖 pycryptodome：请 pip install pycryptodome") from e

    key = salt.strip().encode("utf-8")
    iv = _random_string(16).encode("utf-8")
    msg = (_random_string(64) + plain_pwd).encode("utf-8")
    msg = _pkcs7_pad(msg, 16)

    cipher = AES.new(key, AES.MODE_CBC, iv=iv)
    ct = cipher.encrypt(msg)
    return base64.b64encode(ct).decode("utf-8")


def _build_browser_headers(referer: str) -> dict[str, str]:
    return {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-User": "?1",
        "Referer": referer,
    }


def _extract_login_form(html: str) -> str:
    """
    只截取最像登录表单的 <form>...</form>，避免页面里存在多个 form 时解析错 input。
    """
    html = html or ""
    forms = re.findall(r"(<form\b.*?</form>)", html, flags=re.I | re.S)
    if not forms:
        return html

    def score(f: str) -> int:
        s = 0
        if re.search(r'name=["\']username["\']', f, flags=re.I):
            s += 3
        if re.search(r'name=["\']password["\']', f, flags=re.I):
            s += 3
        if re.search(r'name=["\']execution["\']', f, flags=re.I):
            s += 2
        if re.search(r"pwdEncryptSalt", f, flags=re.I):
            s += 1
        return s

    return max(forms, key=score)


def _parse_form_fields(form_html: str) -> dict[str, str]:
    """
    解析 form 内所有 input 的 name/value（不限制 type=hidden）
    """
    out: dict[str, str] = {}
    form_html = form_html or ""

    for m in re.finditer(r"<input\b[^>]*>", form_html, flags=re.I):
        tag = m.group(0)
        name_m = re.search(r'\bname=["\']([^"\']+)["\']', tag, flags=re.I)
        if not name_m:
            continue
        name = name_m.group(1)

        val_m = re.search(r'\bvalue=["\']([^"\']*)["\']', tag, flags=re.I)
        if val_m:
            out[name] = val_m.group(1)
        else:
            # 无 value 的 checkbox/radio：只有 checked 才会提交；这里不强行加
            t_m = re.search(r'\btype=["\']([^"\']+)["\']', tag, flags=re.I)
            t = t_m.group(1).lower() if t_m else ""
            if t in ("checkbox", "radio"):
                continue
            out[name] = ""

    return out


def _extract_pwd_salt(html: str) -> str | None:
    m = re.search(
        r'id=["\']pwdEncryptSalt["\'][^>]*value=["\']([^"\']+)["\']',
        html or "",
        flags=re.I,
    )
    return m.group(1) if m else None


def _extract_form_action(form_html: str, base_url: str) -> str:
    m = re.search(
        r"<form\b[^>]*action=['\"]([^'\"]+)['\"]", form_html or "", flags=re.I
    )
    if not m:
        return base_url
    return urljoin(base_url, m.group(1))


def _cookie_xsrf(sess: requests.Session) -> str | None:
    for k in ("XSRF-TOKEN", "XSRF_TOKEN", "CSRF-TOKEN", "CSRF_TOKEN"):
        v = sess.cookies.get(k)
        if v:
            return v
    return None


def _page_says_captcha_visible(html: str) -> bool:
    html = html or ""

    # 1) 优先看 captchaDiv 的 class / style 是否显式隐藏
    m = re.search(r'id=["\']captchaDiv["\'][^>]*>', html, flags=re.I)
    if not m:
        # 没有 captchaDiv，通常表示页面结构变了；不要武断认为需要验证码
        return False

    tag = m.group(0)

    cls_m = re.search(r'class=["\']([^"\']+)["\']', tag, flags=re.I)
    cls = cls_m.group(1).lower() if cls_m else ""
    if any(x in cls for x in ("hide", "hidden")):
        return False

    style_m = re.search(r'style=["\']([^"\']+)["\']', tag, flags=re.I)
    style = style_m.group(1).lower() if style_m else ""
    if "display:none" in style.replace(" ", ""):
        return False

    # 走到这里：captchaDiv 存在且未标记隐藏 => 认为需要验证码
    return True


def _check_need_captcha(
    sess: requests.Session, username: str, debug: bool, referer: str | None = None
) -> bool | None:
    url = f"{URLS.cas_check_need_captcha}?username={username}&_={now_ms()}"
    headers = {
        "Accept": "application/json, text/plain, */*",
        "X-Requested-With": "XMLHttpRequest",
    }
    if referer:
        headers["Referer"] = referer

    r = sess.get(url, timeout=REQ_TIMEOUT, allow_redirects=True, headers=headers)

    try:
        data = r.json()
    except Exception:
        dprint(
            debug, f"[CAS] checkNeedCaptcha non-json: {r.status_code} {r.text[:200]}"
        )
        return None

    def to_bool(x) -> bool | None:
        if isinstance(x, bool):
            return x
        if isinstance(x, str):
            s = x.strip().lower()
            if s in ("true", "1", "yes"):
                return True
            if s in ("false", "0", "no"):
                return False
        return None

    # 直接是 bool / "true"/"false"
    b = to_bool(data)
    if b is not None:
        return b

    if isinstance(data, dict):
        for k in ("isNeed", "needCaptcha", "isNeedCaptcha", "data", "result"):
            if k in data:
                b = to_bool(data.get(k))
                if b is not None:
                    return b

    return None


def _probe_captcha_image(sess: requests.Session, debug: bool) -> tuple[bytes, str]:
    ts = now_ms()
    url = f"{URLS.cas_get_captcha}?ts={ts}"
    r = sess.get(url, timeout=REQ_TIMEOUT, allow_redirects=True)
    ctype = (r.headers.get("Content-Type") or "").lower()
    dprint(
        debug,
        f"[CAS] captcha {url} -> {r.status_code} {ctype} bytes={len(r.content or b'')}",
    )
    if (
        r.status_code == 200
        and ctype.startswith("image/")
        and len(r.content or b"") > 800
    ):
        return r.content, url
    raise RuntimeError("验证码图片获取失败（getCaptcha.htl 未返回有效图片）")


def _extract_cas_error_msg(html: str) -> str | None:
    html = html or ""
    patterns = [
        r'id="msg"[^>]*>\s*([^<]+)\s*<',
        r'id="error"[^>]*>\s*([^<]+)\s*<',
        r'id="formError"[^>]*>\s*([^<]+)\s*<',
        r'class="[^"]*errors[^"]*"[^>]*>\s*([^<]+)\s*<',
    ]
    for pat in patterns:
        m = re.search(pat, html, flags=re.I)
        if m:
            return m.group(1).strip()
    return None


def _get_cas_login_url_via_clientredirect(sess: requests.Session, debug: bool) -> str:
    """
    通过 auth1 的 /cas-sso/clientredirect 获取真正 CAS 登录页 URL（带 service=...delegatedclientid=...）。
    """
    service = f"{URLS.base}/portal/entry/pc/authenticate;flowParams=undefined;from="
    params = {
        "client_name": "sidadapter",
        "accept-language": "zh-CN",
        "service": service,
    }
    url = f"{URLS.base}/cas-sso/clientredirect"

    dprint(debug, f"[CAS] GET {url} params={params}")
    r = sess.get(url, params=params, timeout=REQ_TIMEOUT, allow_redirects=False)
    cas_login_prefix = URLS.cas_host.rstrip("/") + "/authserver/login"

    for hop in range(12):
        if r.is_redirect or r.is_permanent_redirect:
            loc = r.headers.get("Location") or r.headers.get("location")
            if not loc:
                break
            nxt = urljoin(r.url, loc)
            dprint(debug, f"[CAS] redirect[{hop}] -> {nxt}")
            if cas_login_prefix in nxt:
                return nxt
            r = sess.get(nxt, timeout=REQ_TIMEOUT, allow_redirects=False)
            continue

        if cas_login_prefix in (r.url or ""):
            return r.url
        break

    raise RuntimeError("无法通过 /cas-sso/clientredirect 获取 CAS 登录 URL")


def cas_login(
    sess: requests.Session, username: str, password: str, debug: bool
) -> None:
    """
    完整 CAS 登录流程：
      clientredirect -> GET login page -> (optional captcha) -> POST -> 跟随重定向回 auth1
    """
    login_url = _get_cas_login_url_via_clientredirect(sess, debug=debug)

    dprint(debug, f"[CAS] GET {login_url}")
    r = sess.get(
        login_url,
        timeout=REQ_TIMEOUT,
        allow_redirects=True,
        headers=_build_browser_headers(referer=login_url),
    )
    html = (r.content or b"").decode("utf-8", errors="replace")
    _save_debug_text(debug, "cas_login.html", html)

    form_html = _extract_login_form(html)
    fields = _parse_form_fields(form_html)

    salt = _extract_pwd_salt(html)
    if not salt:
        raise RuntimeError(
            "CAS 登录页未找到 pwdEncryptSalt（可能页面结构变化或被风控返回假页）"
        )

    # captcha 判定：优先信接口，其次用 DOM 结构兜底
    need_cap_api = _check_need_captcha(sess, username, debug=debug, referer=r.url)
    need_cap_dom = _page_says_captcha_visible(html)
    need_cap = need_cap_api if (need_cap_api is not None) else need_cap_dom
    dprint(
        debug, f"[CAS] needCaptcha(api/dom)={need_cap_api}/{need_cap_dom} -> {need_cap}"
    )

    if need_cap:
        if not sys.stdin.isatty():
            raise InteractionRequired("需要验证码，请在终端手动登录后再启动自动重连")
        img, img_url = _probe_captcha_image(sess, debug=debug)
        cap_path = os.path.abspath("captcha.png")
        with open(cap_path, "wb") as f:
            f.write(img)
        print(f"[CAPTCHA] 已下载验证码图片：{cap_path}")
        dprint(debug, f"[CAPTCHA] from: {img_url}")
        cap = input("[CAPTCHA] 请输入验证码：").strip()
        fields["captcha"] = cap
    else:
        if "captcha" in fields and not fields["captcha"]:
            fields.pop("captcha", None)

    enc_pwd = cas_encrypt_password(password, salt)

    # 覆写必要字段
    fields["username"] = username
    fields["password"] = enc_pwd
    fields.setdefault("_eventId", "submit")
    fields.setdefault("cllt", "userNameLogin")
    fields.setdefault("dllt", "generalLogin")
    fields.setdefault("lt", fields.get("lt", ""))

    # 目标 POST URL：form action + 补回 service query（避免部分 action 丢 query 导致失败）
    action_url = _extract_form_action(form_html, r.url)
    post_url = action_url
    if ("service=" not in post_url) and ("service=" in r.url):
        if "?" in post_url:
            post_url = post_url + "&" + r.url.split("?", 1)[1]
        else:
            post_url = post_url + "?" + r.url.split("?", 1)[1]

    # CSRF：如果有 XSRF cookie，加 header
    xsrf = _cookie_xsrf(sess)
    headers = _build_browser_headers(referer=r.url)
    headers.update(
        {"Origin": URLS.cas_host, "Content-Type": "application/x-www-form-urlencoded"}
    )
    if xsrf:
        headers["X-XSRF-TOKEN"] = unquote(xsrf)

    if debug:
        print(f"[CAS] salt_len={len(salt)} enc_pwd_len={len(enc_pwd)}")
        print(f"[CAS] POST {post_url}")

    # POST 不自动跟随：用是否重定向判断登录是否成功
    r2 = sess.post(
        post_url,
        data=fields,
        timeout=REQ_TIMEOUT,
        allow_redirects=False,
        headers=headers,
    )

    loc = r2.headers.get("Location") or r2.headers.get("location")
    if debug:
        print(f"[CAS] POST status={r2.status_code} loc={loc}")

    if r2.status_code not in (301, 302, 303, 307, 308) or not loc:
        if r2.status_code == 429 or r2.status_code >= 500:
            raise QueryError(f"CAS 服务暂时不可用（HTTP {r2.status_code}），稍后重试")
        body = (r2.content or b"").decode("utf-8", errors="replace")
        _save_debug_text(debug, "cas_after_post.html", body)
        msg = _extract_cas_error_msg(body)
        raise InteractionRequired(
            f"CAS 登录失败：POST 未重定向。HTTP={r2.status_code} "
            + (f"提示：{msg}" if msg else "请检查账号、密码或风控状态")
        )

    # 手动跟随重定向回 auth1
    nxt = urljoin(r2.url, loc)
    for i in range(16):
        rr = sess.get(
            nxt,
            timeout=REQ_TIMEOUT,
            allow_redirects=False,
            headers={"Referer": r2.url, "Accept": "*/*"},
        )
        loc2 = rr.headers.get("Location") or rr.headers.get("location")
        if debug:
            print(f"[CAS] hop[{i}] {rr.status_code} url={nxt} loc={loc2}")
        if rr.status_code in (301, 302, 303, 307, 308) and loc2:
            nxt = urljoin(rr.url, loc2)
            continue
        break

    dprint(debug, "[CAS] login ok")


@dataclass
class PortalContext:
    sess: requests.Session
    session_id: str
    last_url: str


def _extract_sid_from_chain(urls: list[str]) -> str | None:
    for u in reversed(urls):
        sid = extract_q(u, "sessionId") or extract_q(u, "flowSessionId")
        if sid:
            return sid
    return None


def _extract_next_url_from_124(html: str, base_url: str) -> str | None:
    if not html:
        return None
    html = _html.unescape(html)
    base_host = urlparse(base_url).netloc
    patterns = [
        r'(https?://[^/]+/portal/portal-main\?[^"\'>\s]*sessionId=[^"\'>\s]+)',
        r'(https?://[^/]+/eportal/index\.jsp\?[^"\'>\s]+)',
        r'<meta[^>]+http-equiv=["\']refresh["\'][^>]+content=["\'][^"\']*url=([^"\'>\s]+)["\']',
        r'location\.(?:href|replace)\s*=\s*"([^"]+)"',
        r'window\.location(?:\.href|\.replace)?\s*=\s*"([^"]+)"',
    ]
    for pat in patterns:
        m = re.search(pat, html, flags=re.I)
        if not m:
            continue
        u = m.group(1).strip()
        if any(x in u for x in ("%2F", "%3A", "%3F", "%3D")):
            try:
                u2 = unquote(u)
                if base_host and (base_host in u2):
                    u = u2
            except Exception:
                pass
        if u.startswith("//"):
            return "https:" + u
        if u.startswith("/"):
            return urljoin(base_url, u)
        if u.startswith("http"):
            return u
        return urljoin(base_url, u)
    return None


def _new_portal_session() -> requests.Session:
    sess = requests.Session()
    track_resource(sess.close)
    sess.verify = VERIFY_TLS
    sess.headers.update(
        {
            "User-Agent": PORTAL_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "sec-ch-ua": '"Not:A-Brand";v="99", "HeadlessChrome";v="145", "Chromium";v="145"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Linux"',
        }
    )
    return sess


def open_portal_get_session(debug: bool) -> PortalContext:
    sess = _new_portal_session()
    candidates = [URLS.entry_index, URLS.entry_redirect, URLS.route_root]
    last_url = None

    for entry in candidates:
        dprint(debug, f"[NAV] GET {entry}")
        r = sess.get(entry, timeout=REQ_TIMEOUT, allow_redirects=True)
        chain = [h.url for h in r.history] + [r.url]
        last_url = r.url

        if debug:
            dprint(debug, "[DEBUG] redirect chain:")
            for u in chain:
                dprint(debug, "  ", u)

        sid = _extract_sid_from_chain(chain)
        if sid:
            dprint(debug, f"[INFO] sessionId={sid}")
            return PortalContext(sess=sess, session_id=sid, last_url=r.url)

        if "124.124.124.124" in (r.url or ""):
            dprint(debug, "[INFO] hit 124 captive page, parsing next hop...")
            _save_debug_text(debug, "124.html", r.text or "")
            nxt = _extract_next_url_from_124(r.text or "", base_url=URLS.base)
            dprint(debug, f"[INFO] parsed next url: {nxt}")
            if not nxt:
                continue

            r2 = sess.get(nxt, timeout=REQ_TIMEOUT, allow_redirects=True)
            chain2 = [h.url for h in r2.history] + [r2.url]
            last_url = r2.url

            if debug:
                dprint(debug, "[DEBUG] redirect chain (after 124):")
                for u in chain2:
                    dprint(debug, "  ", u)

            sid2 = _extract_sid_from_chain(chain2)
            if sid2:
                dprint(debug, f"[INFO] sessionId={sid2}")
                return PortalContext(sess=sess, session_id=sid2, last_url=r2.url)

    raise RuntimeError(f"无法获取 sessionId。最终URL={last_url}")


def _terminal_load_url_from_portal_main(portal_main_url: str, online_info: dict) -> str:
    qs = parse_qs(urlparse(portal_main_url).query)

    def q1(k: str) -> str:
        v = qs.get(k)
        return (v[0] if v else "") or ""

    session_id = q1("sessionId")
    user_ip = q1("userIp")
    ssid = q1("ssid")
    nas_ip = q1("nasIp")
    custom_page_id = q1("customPageId")
    redirect_url = q1("redirectUrl")
    sam_redirect_url = q1("samPortalRedirectUrl")
    clear_identity = q1("clearIdentitySelect") or "true"
    guest_flow = q1("guestFlow") or "false"

    inner = (
        "/entry?"
        f"sessionId={quote(session_id, safe='')}"
        f"&userIp={quote(user_ip, safe='')}"
        f"&ssid={quote(ssid, safe='')}"
        f"&nasIp={quote(nas_ip, safe='')}"
        f"&customPageId={quote(custom_page_id, safe='')}"
        f"&redirectUrl={quote(redirect_url, safe='')}"
        f"&samPortalRedirectUrl={quote(sam_redirect_url, safe='')}"
        f"&clearIdentitySelect={quote(clear_identity, safe='')}"
        f"&guestFlow={quote(guest_flow, safe='')}"
    )

    pu = ((online_info.get("data") or {}).get("portalOnlineUserInfo")) or {}
    oi = {"result": pu.get("result"), "userIndex": pu.get("userIndex")}
    rq = {
        "sessionId": session_id,
        "userIp": user_ip,
        "ssid": ssid,
        "nasIp": nas_ip,
        "customPageId": custom_page_id,
        "redirectUrl": redirect_url,
        "samPortalRedirectUrl": sam_redirect_url,
        "clearIdentitySelect": clear_identity,
        "guestFlow": guest_flow,
    }

    return (
        f"{URLS.base}/portal/entry/pc/terminalLoad"
        f"?url={quote(inner, safe='')}"
        f"&onlineInfo={quote(json.dumps(oi, ensure_ascii=False), safe='')}"
        f"&routrQueryParams={quote(json.dumps(rq, ensure_ascii=False), safe='')}"
    )


def _seed_sam_cookie(sess: requests.Session, debug: bool, referer: str) -> None:
    url = f"{URLS.sam_enable_info}?{now_ms()}&version={quote(VERSION_TAG, safe='')}"
    try:
        r = sess.get(
            url,
            timeout=REQ_TIMEOUT,
            allow_redirects=True,
            headers=_portal_api_headers(sess, referer),
        )
        dprint(debug, f"[PRE] sam enableConfig status={r.status_code} url={r.url}")
    except Exception as e:
        dprint(debug, f"[WARN] sam enableConfig failed: {e}")


def api_post_json(
    sess: requests.Session,
    url: str,
    payload: dict,
    debug: bool,
    referer: str | None = None,
    extra_headers: dict[str, str] | None = None,
) -> tuple[int, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    dprint(debug, f"[API] POST {url} keys={list(payload.keys())}")
    headers = {
        **_portal_api_headers(sess, referer),
        "Content-Type": "application/json;charset=UTF-8",
    }
    if extra_headers:
        headers.update(extra_headers)
    r = sess.post(
        url,
        data=body,
        headers=headers,
        timeout=REQ_TIMEOUT,
        allow_redirects=True,
    )
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, r.text


def api_get_json(
    sess: requests.Session, url: str, debug: bool, referer: str | None = None
) -> tuple[int, Any]:
    dprint(debug, f"[API] GET  {url}")
    r = sess.get(
        url,
        headers=_portal_api_headers(sess, referer),
        timeout=REQ_TIMEOUT,
        allow_redirects=True,
    )
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, r.text


def get_current_node(
    sess: requests.Session, session_id: str, debug: bool
) -> str | None:
    st, data = api_post_json(
        sess,
        URLS.api_get_node,
        {"sessionId": session_id, "flowKey": "portal_auth"},
        debug=debug,
    )
    if st != 200 or not isinstance(data, dict):
        return None
    return (data.get("data") or {}).get("currentNodePath")


def get_online_info(
    sess: requests.Session, session_id: str, debug: bool, referer: str | None = None
) -> dict | None:
    url = (
        f"{URLS.api_get_online}"
        f"?sessionId={session_id}&t={now_ms()}&version={quote(VERSION_TAG, safe='')}"
    )
    st, data = api_get_json(sess, url, debug=debug, referer=referer)
    if st != 200 or not isinstance(data, dict):
        raise QueryError(f"在线状态查询失败（HTTP {st}）")
    online_state(data)
    return data


def get_account_info(
    sess: requests.Session, session_id: str, debug: bool
) -> tuple[int, Any]:
    return api_post_json(
        sess, URLS.api_get_account_info, {"sessionId": session_id}, debug=debug
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


def summarize_account_payload(payload: Any) -> dict:
    if not isinstance(payload, dict):
        return {}
    lvl1 = payload.get("data") or {}
    if not isinstance(lvl1, dict):
        return {}

    if isinstance(lvl1.get("accountInfo"), list) or lvl1.get("accountInfo") is None:
        inner = lvl1
    else:
        lvl2 = lvl1.get("data") or {}
        inner = lvl2 if isinstance(lvl2, dict) else {}

    items_raw = inner.get("accountInfo")
    items_map: dict[str, dict] = {}
    if isinstance(items_raw, list):
        for it in items_raw:
            if not isinstance(it, dict):
                continue
            title = it.get("title")
            if not title:
                continue
            items_map[str(title)] = {
                "content": it.get("content"),
                "link": it.get("link"),
            }

    return {
        "name": inner.get("name"),
        "service": inner.get("service"),
        "items_map": items_map,
    }


def format_info(online_info: dict | None, account_payload: Any) -> str:
    if not online_info or not isinstance(online_info, dict):
        return "No status (empty)"

    f = online_fields(online_info)
    if f.get("result") != "success":
        msg = f.get("message")
        return f"离线：{msg or 'dx.failed.user.offline'}\n提示：请先运行 `python ysu_api.py login` 登录上网。"

    acc = (
        summarize_account_payload(account_payload)
        if account_payload is not None
        else {}
    )
    items_map = acc.get("items_map") if isinstance(acc, dict) else {}

    display_name = (
        (acc.get("name") if isinstance(acc, dict) else None) or f.get("userName") or ""
    )
    account_id = f.get("userId") or f.get("userName") or ""

    lines: list[str] = []
    lines.append("在线：success")
    if display_name:
        lines.append(f"用户: {display_name}")
    if account_id:
        lines.append(f"账号: {account_id}")
    if f.get("userIp"):
        lines.append(f"IP: {f['userIp']}")
    if f.get("ssid"):
        lines.append(f"SSID: {f['ssid']}")

    svc = (
        (acc.get("service") if isinstance(acc, dict) else None)
        or f.get("realServiceName")
        or f.get("service")
    )
    if svc:
        lines.append(f"服务: {svc}")
    if f.get("userIndex"):
        lines.append(f"userIndex: {f['userIndex']}")

    wanted_keys = ["在线设备", "剩余流量", "套餐&余额"]
    shown = []
    if isinstance(items_map, dict):
        for k in wanted_keys:
            v = (
                items_map.get(k, {}).get("content")
                if isinstance(items_map.get(k), dict)
                else None
            )
            if v:
                shown.append((k, v))

    if shown:
        lines.append("账户信息:")
        for k, v in shown:
            lines.append(f"  - {k}: {v}")
    else:
        lines.append("账户信息: (无可展示项)")

    return "\n".join(lines)


@managed_resources
def cmd_login(service: str, user: str, pwd: str, debug: bool, max_wait: int) -> None:
    svc = normalize_service(service)
    if not svc:
        raise RuntimeError(
            "service 无效：校园网/中国移动/中国联通/中国电信 或 1-4/移动/联通/电信"
        )
    ctx = open_portal_get_session(debug=debug)
    sess = ctx.sess
    sid = ctx.session_id

    online = get_online_info(sess, sid, debug=debug)
    if online and is_online(online):
        print("[OK] already online")
        _, acc = get_account_info(sess, sid, debug=debug)
        print(format_info(online, acc))
        return

    node = get_current_node(sess, sid, debug=debug)
    dprint(debug, f"[INFO] node={node} last_url={ctx.last_url}")

    if node == "authenticate":
        # 部分情况下直接 CAS 登录会话不完整；先访问一次 cas-sso/login 预热 auth1 侧会话
        custom_page_id = extract_q(ctx.last_url, "customPageId") or ""
        seed = f"{URLS.base}/cas-sso/login?flowSessionId={sid}"
        if custom_page_id:
            seed += f"&customPageId={custom_page_id}"
        seed += f"&preview=false&appType=normal&language=zh-CN&timer={now_ms()}"
        dprint(debug, f"[SSO] GET {seed}")
        rr = sess.get(seed, timeout=REQ_TIMEOUT, allow_redirects=True)
        dprint(debug, f"[SSO] seed final_url={rr.url} status={rr.status_code}")

        dprint(debug, "[STEP] CAS login (requests)")
        cas_login(sess, username=user, password=pwd, debug=debug)

        node = get_current_node(sess, sid, debug=debug)
        dprint(debug, f"[INFO] after CAS node={node}")
        if node == "authenticate":
            raise InteractionRequired("统一认证后仍要求登录，请检查账号密码、验证码或风控状态")

    if node == "serviceSelection":
        st, response = api_post_json(
            sess,
            URLS.api_service_login,
            {"sessionId": sid, "service": svc},
            debug=debug,
        )
        check_action(st, response, "选择服务")
        st, response = api_post_json(
            sess, URLS.api_user_online, {"sessionId": sid}, debug=debug
        )
        check_action(st, response, "上线")

    deadline = time.monotonic() + max_wait
    last = None
    while time.monotonic() < deadline:
        last = get_online_info(sess, sid, debug=debug)
        if last and is_online(last):
            print("[OK] 已在线")
            _, acc = get_account_info(sess, sid, debug=debug)
            print(format_info(last, acc))
            return
        time.sleep(2)

    raise OperationFailed("登录超时，未确认在线")


@managed_resources
def cmd_info(debug: bool, raw: bool) -> None:
    ctx = open_portal_get_session(debug=debug)
    sess, sid = ctx.sess, ctx.session_id

    online = get_online_info(sess, sid, debug=debug)
    acc = None
    st_acc = None
    if online and is_online(online):
        st_acc, acc = get_account_info(sess, sid, debug=debug)

    if raw:
        out = {"online": online, "account_http_status": st_acc, "account": acc}
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print(format_info(online, acc))


@managed_resources
def cmd_status(debug: bool, raw: bool) -> bool:
    ctx = open_portal_get_session(debug=debug)
    sess, sid = ctx.sess, ctx.session_id
    online = get_online_info(sess, sid, debug=debug)
    ok = bool(online and is_online(online))
    if raw:
        out = {"online": online, "is_online": ok}
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print("online" if ok else "offline")
    return ok


def dump_requests_cookies(sess: requests.Session, label: str, debug: bool) -> None:
    if not debug:
        return
    print(f"[COOKIE][{label}]")
    base_host = urlparse(URLS.base).netloc
    cas_host = urlparse(URLS.cas_host).netloc
    for c in sess.cookies:
        dom = c.domain or ""
        if (base_host and base_host in dom) or (cas_host and cas_host in dom):
            v = c.value or ""
            v_show = (v[:12] + "..." + v[-6:]) if len(v) > 24 else v
            print(f"  - {c.domain} {c.name}={v_show} path={c.path}")


def _portal_api_headers(
    sess: requests.Session, referer: str | None = None
) -> dict[str, str]:
    h = {
        "Accept": "application/json, text/plain, */*",
        "X-Requested-With": "XMLHttpRequest",
        "isportal": "true",
        "Origin": URLS.base,
    }
    if referer:
        h["Referer"] = referer

    # 如果站点用了 XSRF cookie，则加 header（可选但建议）
    xsrf = _cookie_xsrf(sess)
    if xsrf:
        h["X-XSRF-TOKEN"] = unquote(xsrf)
    return h


def _find_cookie_value(
    sess: requests.Session, name: str, *, domain_contains: str, path: str
) -> str | None:
    for c in sess.cookies:
        if (c.name or "") != name:
            continue
        dom = c.domain or ""
        if domain_contains not in dom:
            continue
        if (c.path or "") != path:
            continue
        v = c.value or ""
        if v:
            return v
    return None


def _prepare_logout_context(
    sess: requests.Session, portal_main_url: str, online_info: dict, debug: bool
) -> str:
    """
    纯 requests 版 logout 的关键：复刻浏览器在下线前的页面访问顺序。

    这一步的目的不是拿 HTML，而是触发站点侧加载流程，补齐 /sam 域的会话 cookie。
    """
    try:
        tl = _terminal_load_url_from_portal_main(portal_main_url, online_info)
        dprint(debug, f"[PRE] GET terminalLoad: {tl}")
        r_tl = sess.get(
            tl,
            timeout=REQ_TIMEOUT,
            allow_redirects=True,
            headers={
                "User-Agent": sess.headers.get("User-Agent", ""),
                "Accept": "text/html,application/xhtml+xml,*/*",
                "Referer": portal_main_url,
            },
        )
        dprint(debug, f"[PRE] terminalLoad final_url={r_tl.url}")
    except Exception as e:
        dprint(debug, f"[WARN] terminalLoad preflight failed: {e}")

    finish_url = f"{URLS.base}/portal/entry/pc/finish;flowParams=undefined;from="
    dprint(debug, f"[PRE] GET finish page: {finish_url}")
    r_finish = sess.get(
        finish_url,
        timeout=REQ_TIMEOUT,
        allow_redirects=True,
        headers={
            "User-Agent": sess.headers.get("User-Agent", ""),
            "Accept": "text/html,application/xhtml+xml,*/*",
            "Referer": portal_main_url,
        },
    )
    finish_final = r_finish.url
    dprint(debug, f"[PRE] finish final_url={finish_final}")
    dump_requests_cookies(sess, "after_finish", debug=debug)

    _seed_sam_cookie(sess, debug=debug, referer=finish_final)
    dump_requests_cookies(sess, "after_sam_seed", debug=debug)

    return finish_final


def _post_offline(sess: requests.Session, session_id: str, referer: str, debug: bool):
    """
    下线接口返回 code=200 并不总是意味着真正下线成功。
    实测需要让 offline 请求“携带 /sam 域的 JSESSIONID”（模拟浏览器行为）才能稳定生效。
    """
    _seed_sam_cookie(sess, debug=debug, referer=referer)
    sam_jsessionid = _find_cookie_value(
        sess, "JSESSIONID", domain_contains=urlparse(URLS.base).netloc, path="/sam"
    )
    offline_cookie = f"JSESSIONID={sam_jsessionid}" if sam_jsessionid else None
    dprint(debug, f"[PRE] offline cookie override={bool(offline_cookie)}")

    return api_post_json(
        sess,
        URLS.api_offline,
        {"sessionId": session_id},
        debug=debug,
        referer=referer,
        extra_headers=({"Cookie": offline_cookie} if offline_cookie else None),
    )


def _wait_until_offline(
    sess: requests.Session,
    session_id: str,
    debug: bool,
    deadline_ts: float,
    *,
    referer: str,
) -> dict | None:
    last = None
    while time.monotonic() < deadline_ts:
        last = get_online_info(sess, session_id, debug=debug, referer=referer)
        if last and (not is_online(last)):
            return last
        time.sleep(2)
    return last


@managed_resources
def cmd_logout(debug: bool, max_wait: int, user: str, pwd: str) -> None:
    ctx = open_portal_get_session(debug=debug)
    sess, sid = ctx.sess, ctx.session_id

    online = get_online_info(sess, sid, debug=debug)
    if not (online and is_online(online)):
        print("[OK] 当前已离线")
        print(format_info(online, None))
        return

    dump_requests_cookies(sess, "logout_start", debug=debug)

    finish_final = _prepare_logout_context(
        sess, portal_main_url=ctx.last_url, online_info=online, debug=debug
    )

    _ = get_online_info(sess, sid, debug=debug, referer=finish_final)

    st, data = _post_offline(sess, sid, referer=finish_final, debug=debug)
    dprint(debug, f"[INFO] offline api status={st} resp={data}")
    dump_requests_cookies(sess, "after_offline", debug=debug)

    deadline = time.monotonic() + max_wait
    last = _wait_until_offline(
        sess,
        sid,
        debug=debug,
        deadline_ts=min(deadline, time.monotonic() + 6),
        referer=finish_final,
    )
    if last and (not is_online(last)):
        print("[OK] 已下线")
        print(format_info(last, None))
        return

    last = _wait_until_offline(
        sess, sid, debug=debug, deadline_ts=deadline, referer=finish_final
    )
    if last and (not is_online(last)):
        print("[OK] 已下线")
        print(format_info(last, None))
        return

    if user and pwd:
        node = get_current_node(sess, sid, debug=debug)
        dprint(debug, f"[INFO] before retry node={node}")
        if node == "authenticate":
            dprint(debug, "[STEP] CAS login (requests) for logout retry")
            cas_login(sess, username=user, password=pwd, debug=debug)

        online2 = get_online_info(sess, sid, debug=debug)
        if online2 and is_online(online2):
            finish_final2 = _prepare_logout_context(
                sess, portal_main_url=ctx.last_url, online_info=online2, debug=debug
            )
            st2, data2 = _post_offline(sess, sid, referer=finish_final2, debug=debug)
            dprint(debug, f"[INFO] offline retry status={st2} resp={data2}")

            last = _wait_until_offline(
                sess,
                sid,
                debug=debug,
                deadline_ts=time.monotonic() + max_wait,
                referer=finish_final2,
            )
            if last and (not is_online(last)):
                print("[OK] 已下线")
                print(format_info(last, None))
                return

    raise OperationFailed("下线超时，仍显示在线")


class YsuNetApiClient:
    def __init__(
        self,
        *,
        base: str | None = None,
        cas_host: str | None = None,
        timeout: int | None = None,
        verify_tls: bool | None = None,
        portal_user_agent: str | None = None,
        version_tag: str | None = None,
        save_debug_files: bool | None = None,
    ):
        self.urls = URLS.with_overrides(base, cas_host)
        self.timeout = timeout
        self.verify_tls = verify_tls
        self.portal_user_agent = portal_user_agent
        self.version_tag = version_tag
        self.save_debug_files = save_debug_files

    def _apply(self) -> None:
        global \
            URLS, \
            REQ_TIMEOUT, \
            VERIFY_TLS, \
            PORTAL_USER_AGENT, \
            VERSION_TAG, \
            SAVE_DEBUG_FILES
        URLS = self.urls
        if self.timeout is not None:
            REQ_TIMEOUT = int(self.timeout)
        if self.verify_tls is not None:
            VERIFY_TLS = bool(self.verify_tls)
        if self.portal_user_agent is not None:
            PORTAL_USER_AGENT = str(self.portal_user_agent)
        if self.version_tag is not None:
            VERSION_TAG = str(self.version_tag)
        if self.save_debug_files is not None:
            SAVE_DEBUG_FILES = bool(self.save_debug_files)

    def login(
        self, *, service: str, user: str, password: str, debug: bool, max_wait: int
    ) -> None:
        self._apply()
        cmd_login(
            service=service, user=user, pwd=password, debug=debug, max_wait=max_wait
        )

    def info(self, *, debug: bool, raw: bool) -> None:
        self._apply()
        cmd_info(debug=debug, raw=raw)

    def logout(
        self, *, debug: bool, max_wait: int, user: str = "", password: str = ""
    ) -> None:
        self._apply()
        cmd_logout(debug=debug, max_wait=max_wait, user=user, pwd=password)


# ====== CLI ======
def build_parser() -> argparse.ArgumentParser:
    class NiceFormatter(
        argparse.RawTextHelpFormatter, argparse.ArgumentDefaultsHelpFormatter
    ):
        pass

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
        "--timeout",
        type=int,
        default=None,
        help="请求超时秒数（默认读 YSU_TIMEOUT）",
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
        help="自定义 User-Agent（默认读 YSU_PORTAL_UA）",
    )
    common.add_argument(
        "--version-tag",
        default=None,
        help="version 查询参数（默认读 YSU_VERSION）",
    )
    common.add_argument(
        "--interactive",
        action="store_true",
        help="缺少账号/密码时使用交互输入",
    )
    common.add_argument(
        "--raw", action="store_true", help="输出完整 JSON（仅 info 有意义）"
    )

    ap = argparse.ArgumentParser(
        prog="ysu_api.py",
        formatter_class=NiceFormatter,
        description="燕山大学校园网登录脚本（auth1.ysu.edu.cn）——纯 requests 版",
    )
    sub = ap.add_subparsers(
        dest="cmd", required=True, metavar="{login,info,logout,status,shell}"
    )

    p_login = sub.add_parser(
        "login", parents=[common], help="登录并上线", formatter_class=NiceFormatter
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
    )

    sub.add_parser(
        "status",
        parents=[common],
        help="仅判断是否在线（在线返回码 0，离线返回码 1）",
        formatter_class=NiceFormatter,
    )

    p_logout = sub.add_parser(
        "logout", parents=[common], help="下线", formatter_class=NiceFormatter
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
    global \
        URLS, \
        REQ_TIMEOUT, \
        VERIFY_TLS, \
        PORTAL_USER_AGENT, \
        VERSION_TAG, \
        SAVE_DEBUG_FILES
    URLS = URLS.with_overrides(
        getattr(args, "base", None), getattr(args, "cas_host", None)
    )

    if getattr(args, "timeout", None) is not None:
        REQ_TIMEOUT = int(args.timeout)
    if getattr(args, "verify_tls", None) is not None:
        VERIFY_TLS = bool(args.verify_tls)
    if getattr(args, "ua", None):
        PORTAL_USER_AGENT = str(args.ua)
    if getattr(args, "version_tag", None):
        VERSION_TAG = str(args.version_tag)
    if getattr(args, "save_debug_files", None) is not None:
        SAVE_DEBUG_FILES = bool(args.save_debug_files)


def _prompt_user_pass(user: str, password: str) -> tuple[str, str]:
    u = user.strip()
    p = password
    if not u:
        u = input("账号: ").strip()
    if not p:
        p = getpass.getpass("密码: ")
    return u, p


def _run_shell(args: argparse.Namespace) -> None:
    debug = bool(args.debug)
    current_service = normalize_service(getattr(args, "service", None)) or "校园网"
    while True:
        try:
            cmdline = input("ysu-net> ").strip()
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
            cmd_login(service=service, user=u, pwd=p, debug=debug, max_wait=60)
            continue
        if subcmd == "info":
            cmd_info(debug=debug, raw=bool(args.raw))
            continue
        if subcmd == "status":
            cmd_status(debug=debug, raw=bool(args.raw))
            continue
        if subcmd == "logout":
            u = args.user
            p = args.password
            cmd_logout(debug=debug, max_wait=30, user=u, pwd=p)
            continue

        print("unknown command, type 'help'")


def main() -> None:
    ap = build_parser()
    args = ap.parse_args()
    debug = bool(args.debug)
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
        )
    elif args.cmd == "info":
        cmd_info(debug=debug, raw=bool(args.raw))
    elif args.cmd == "status":
        ok = cmd_status(debug=debug, raw=bool(args.raw))
        sys.exit(0 if ok else 1)
    elif args.cmd == "logout":
        if args.interactive and (not args.user or not args.password):
            args.user, args.password = _prompt_user_pass(args.user, args.password)
        cmd_logout(
            debug=debug,
            max_wait=int(args.max_wait),
            user=args.user,
            pwd=args.password,
        )
    elif args.cmd == "shell":
        if args.interactive and (not args.user or not args.password):
            args.user, args.password = _prompt_user_pass(args.user, args.password)
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
