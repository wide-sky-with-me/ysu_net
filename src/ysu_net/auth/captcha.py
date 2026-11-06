"""验证码识别：把「人工输入」换成可插拔的自动识别，保留人工兜底。

设计约束：
- 不把识别结果当成凭据，同一张图只提交一次；失败由调用方决定是否换图重试。
- 后端按可用性排序，缺依赖就跳过，最后回落到人工输入或 InteractionRequired。
- 后端之间不共享 Cookie、不读取账号密码；远端后端只发送图片字节。
"""

from __future__ import annotations

import base64
import io
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass

ENV_BACKEND = "YSU_CAPTCHA_SOLVER"
ENV_REMOTE = "YSU_CAPTCHA_REMOTE_URL"
REMOTE_TIMEOUT = 10
DEFAULT_LEN = 4


@dataclass(frozen=True)
class Solution:
    text: str
    backend: str


def _normalize(text: str) -> str | None:
    cleaned = "".join(ch for ch in (text or "").strip() if ch.isalnum())
    return cleaned or None


def _usable(text: str | None, expected_len: int = DEFAULT_LEN) -> str | None:
    value = _normalize(text)
    if value is None or len(value) != expected_len:
        return None
    return value


def _preprocess(image: bytes) -> bytes | None:
    """灰度、放大、二值化；缺 Pillow 时返回 None，由调用方跳过该后端。"""
    try:
        from PIL import Image, ImageFilter
    except Exception:
        return None
    try:
        with Image.open(io.BytesIO(image)) as im:
            im = im.convert("L").resize((im.width * 4, im.height * 4), Image.LANCZOS)
            im = im.filter(ImageFilter.MedianFilter(3))
            im = im.point(lambda v: 0 if v < 140 else 255)
            out = io.BytesIO()
            im.save(out, format="PNG")
            return out.getvalue()
    except Exception:
        return None


_OCR_CACHE = {"engine": None, "failed": False}


def solve_ddddocr(image: bytes) -> str | None:
    """ddddocr（MIT）的 CRNN 模型，对 4~6 位扭曲字符验证码开箱可用。"""
    if _OCR_CACHE["failed"]:
        return None
    if _OCR_CACHE["engine"] is None:
        try:
            import ddddocr
        except Exception:
            _OCR_CACHE["failed"] = True
            return None
        try:
            _OCR_CACHE["engine"] = ddddocr.DdddOcr(show_ad=False)
        except Exception:
            _OCR_CACHE["failed"] = True
            return None
    try:
        return _usable(_OCR_CACHE["engine"].classification(image))
    except Exception:
        return None


def solve_tesseract(image: bytes) -> str | None:
    exe = shutil.which("tesseract")
    if not exe:
        return None
    prepared = _preprocess(image) or image
    try:
        run = subprocess.run(
            [exe, "stdin", "stdout", "--psm", "8",
             "-c", "tessedit_char_whitelist=0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"],
            input=prepared,
            capture_output=True,
            timeout=15,
            check=False,
        )
    except Exception:
        return None
    return _usable(run.stdout.decode("utf-8", "ignore")) if run.returncode == 0 else None


def solve_remote(image: bytes, url: str) -> str | None:
    if not url:
        return None
    try:
        import requests
    except Exception:
        return None
    payload = {
        "image": base64.b64encode(image).decode("ascii"),
        "encoding": "base64",
    }
    try:
        r = requests.post(url, json=payload, timeout=REMOTE_TIMEOUT)
    except Exception:
        return None
    if r.status_code != 200:
        return None
    try:
        data = r.json()
    except Exception:
        return None
    text = data.get("text") if isinstance(data, dict) else None
    return _usable(text if isinstance(text, str) else None)


def solve_manual(image: bytes) -> str | None:
    if not sys.stdin.isatty():
        return None
    try:
        return _usable(input("[CAPTCHA] 请输入验证码："))
    except (EOFError, KeyboardInterrupt):
        return None


def available() -> bool:
    """是否存在不需要终端的识别后端；不存在时调用方按原规则立即要求人工介入。"""
    choice = (os.environ.get(ENV_BACKEND) or "auto").strip().lower()
    remote_url = (os.environ.get(ENV_REMOTE) or "").strip()
    if choice in ("remote", "auto") and remote_url:
        return True
    if choice in ("tesseract", "auto") and shutil.which("tesseract"):
        return True
    if choice in ("ddddocr", "auto"):
        try:
            import ddddocr  # noqa: F401
        except Exception:
            return False
        return True
    return False


def solve(image: bytes, *, expected_len: int = DEFAULT_LEN) -> Solution | None:
    """按可用性依次尝试后端；返回 None 表示没有后端给出可用结果。"""
    choice = (os.environ.get(ENV_BACKEND) or "auto").strip().lower()
    remote_url = (os.environ.get(ENV_REMOTE) or "").strip()
    order = {
        "auto": ("remote", "ddddocr", "tesseract", "manual"),
        "remote": ("remote",),
        "ddddocr": ("ddddocr",),
        "tesseract": ("tesseract",),
        "manual": ("manual",),
    }.get(choice, ("remote", "ddddocr", "tesseract", "manual"))
    for backend in order:
        text = None
        if backend == "remote":
            text = _usable(solve_remote(image, remote_url), expected_len)
        elif backend == "ddddocr":
            text = _usable(solve_ddddocr(image), expected_len)
        elif backend == "tesseract":
            text = _usable(solve_tesseract(image), expected_len)
        elif backend == "manual":
            text = _usable(solve_manual(image), expected_len)
        if text:
            return Solution(text=text, backend=backend)
    return None
