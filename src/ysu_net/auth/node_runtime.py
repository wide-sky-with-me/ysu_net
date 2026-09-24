"""Node.js runtime for the Playwright driver, downloaded on demand by desktop bundles.

Playwright's Python package runs ``driver/package/cli.js`` with a bundled Node.js
(~100 MB). Desktop bundles ship the small JS package but not Node itself; the
browser backend then uses, in order: ``PLAYWRIGHT_NODEJS_PATH``, the bundled
binary, a previously downloaded runtime, or a compatible system ``node``.
Downloads are pinned to one release and verified against a built-in SHA-256.
"""
import hashlib
import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile

VERSION = "v24.18.1"  # The release Playwright 1.62 ships and tests against.
MIN_MAJOR = 20        # playwright-core's package.json: "engines": {"node": ">=20"}
ARCHIVES = {
    # Official SHASUMS256.txt for each archive; mirrors are safe because of this check.
    "win32": (f"node-{VERSION}-win-x64.zip",
              "ec56b84a7551893ab2324ebdfdc4ab974a63b4781162600b68a1293cc3e53765", 37177316),
    "linux": (f"node-{VERSION}-linux-x64.tar.xz",
              "d6c664df3f3f61458e8c277585571328522d705166723a7c7823a9253a4d15a0", 31525884),
}
MIRRORS = ("https://npmmirror.com/mirrors/node", "https://nodejs.org/dist")
ENV = "PLAYWRIGHT_NODEJS_PATH"


def _exe_name():
    return "node.exe" if sys.platform == "win32" else "node"


def runtime_dir():
    from ysu_net.manager.config import config_dir
    return config_dir() / "runtime" / f"node-{VERSION}"


def downloaded_node():
    return runtime_dir() / _exe_name()


def bundled_node():
    try:
        import playwright
    except ImportError:
        return None
    return Path(playwright.__file__).parent / "driver" / _exe_name()


def _system_node():
    # YSU_NODE_SYSTEM=0 forces the downloaded runtime (used by packaging checks).
    if os.environ.get("YSU_NODE_SYSTEM") == "0":
        return None
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


def supported():
    return sys.platform in ARCHIVES


def download_size():
    return ARCHIVES[sys.platform][2] if supported() else 0


def _fetch(url, expected_size, progress, cancel):
    import requests
    data = io.BytesIO()
    with requests.get(url, stream=True, timeout=(10, 60)) as response:
        response.raise_for_status()
        for chunk in response.iter_content(256 * 1024):
            if cancel is not None and cancel.is_set():
                raise InterruptedError("下载已取消")
            data.write(chunk)
            if data.tell() > expected_size * 2:
                raise ValueError("下载内容大小异常")
            if progress:
                progress(data.tell(), expected_size)
    return data.getvalue()


def _extract(archive, name):
    member_suffix = "/" + _exe_name() if name.endswith(".zip") else "/bin/node"
    if name.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
            member = next(m for m in bundle.namelist() if m.endswith(member_suffix) and m.count("/") == 1)
            return bundle.read(member)
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:xz") as bundle:
        member = next(m for m in bundle.getmembers() if m.name.endswith(member_suffix) and m.isfile())
        return bundle.extractfile(member).read()


def install(progress=None, cancel=None, mirrors=MIRRORS):
    """Download, verify and install the pinned Node.js runtime; returns its path."""
    if not supported():
        raise RuntimeError("当前平台不支持自动下载浏览器认证组件")
    name, digest, size = ARCHIVES[sys.platform]
    errors = []
    for base in mirrors:
        try:
            archive = _fetch(f"{base}/{VERSION}/{name}", size, progress, cancel)
        except InterruptedError:
            raise
        except Exception as exc:  # noqa: BLE001 - try the next mirror
            errors.append(type(exc).__name__)
            continue
        if hashlib.sha256(archive).hexdigest() != digest:
            errors.append("校验失败")
            continue
        binary = _extract(archive, name)
        target = downloaded_node()
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(dir=target.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(binary)
            os.chmod(temporary, 0o755)
            os.replace(temporary, target)
        finally:
            Path(temporary).unlink(missing_ok=True)
        return target
    raise RuntimeError("浏览器认证组件下载失败（" + "、".join(errors) + "），请检查网络后重试")


def remove():
    shutil.rmtree(runtime_dir(), ignore_errors=True)
