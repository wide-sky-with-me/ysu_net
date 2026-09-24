"""Locate an installed Chromium-family browser for the Playwright backend.

Playwright drives any Chromium build through ``executable_path``; using Edge or
Chrome that is already installed avoids a separate ~150 MB Chromium download.
Firefox is not usable here: Playwright needs its own patched Firefox build.
"""
import os
from pathlib import Path
import shutil
import sys

ENV = "YSU_BROWSER_PATH"


def _windows_candidates():
    roots = [os.environ.get(k) for k in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA")]
    names = (
        ("Microsoft Edge", r"Microsoft\Edge\Application\msedge.exe"),
        ("Google Chrome", r"Google\Chrome\Application\chrome.exe"),
        ("Chromium", r"Chromium\Application\chrome.exe"),
    )
    for label, relative in names:
        for root in roots:
            if root:
                yield label, Path(root) / relative


def _posix_candidates():
    # Snap packages (Ubuntu's chromium) run confined and cannot read Playwright's
    # temporary profile directory, so only regular .deb / distro installs qualify.
    for label, command in (
        ("Google Chrome", "google-chrome-stable"), ("Google Chrome", "google-chrome"),
        ("Microsoft Edge", "microsoft-edge-stable"), ("Microsoft Edge", "microsoft-edge"),
        ("Chromium", "chromium"), ("Chromium", "chromium-browser"),
        ("Brave", "brave-browser"),
    ):
        found = shutil.which(command)
        if found and not Path(found).resolve().as_posix().startswith("/snap/"):
            yield label, Path(found)


def find_system_browser():
    """Return (label, path) of a usable browser, or None."""
    override = os.environ.get(ENV, "").strip()
    if override:
        path = Path(override)
        return ("自定义浏览器", path) if path.is_file() else None
    candidates = _windows_candidates() if sys.platform == "win32" else _posix_candidates()
    for label, path in candidates:
        if path.is_file():
            return label, path
    return None
