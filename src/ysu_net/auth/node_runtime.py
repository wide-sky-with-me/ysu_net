"""Node.js runtime lookup for the Playwright driver.

Playwright's Python package runs ``driver/package/cli.js`` with Node.js. The
browser backend uses, in order: ``PLAYWRIGHT_NODEJS_PATH``, Playwright's bundled
binary, a runtime downloaded by earlier desktop releases, or a compatible system
``node``.
"""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import platform

VERSION = "v24.18.1"  # The release Playwright 1.62 ships and tests against.
MIN_MAJOR = 20        # playwright-core's package.json: "engines": {"node": ">=20"}
ENV = "PLAYWRIGHT_NODEJS_PATH"


def _exe_name():
    return "node.exe" if sys.platform == "win32" else "node"


def runtime_dir():
    from ysu_net.manager.config import config_dir
    suffix = "-arm64" if platform.machine().lower() in ("arm64", "aarch64") else ""
    return config_dir() / "runtime" / f"node-{VERSION}{suffix}"


def downloaded_node():
    return runtime_dir() / _exe_name()


def bundled_node():
    try:
        import playwright
    except ImportError:
        return None
    return Path(playwright.__file__).parent / "driver" / _exe_name()


def _system_node():
    found = shutil.which("node")
    if not found:
        return None
    try:
        out = subprocess.run([found, "--version"], capture_output=True, text=True, timeout=10,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
        major = int(out.strip().lstrip("v").split(".")[0])
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None
    return Path(found) if major >= MIN_MAJOR else None


def find_node():
    """Return a usable Node.js executable for the Playwright driver, or None."""
    override = os.environ.get(ENV, "").strip()
    if override:
        return Path(override) if Path(override).is_file() else None
    for candidate in (bundled_node(), downloaded_node()):
        if candidate and candidate.is_file():
            return candidate
    return _system_node()


def configure():
    """Point Playwright at a Node.js runtime; returns False when none is available."""
    node = find_node()
    if node is None:
        return False
    bundled = bundled_node()
    if not (bundled and node == bundled):
        os.environ[ENV] = str(node)
    return True
