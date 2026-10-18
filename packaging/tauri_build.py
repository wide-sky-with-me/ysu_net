"""Compatibility build entry; the desktop uses only the Node/Rust build pipeline.

Prefer `npm --prefix desktop run native:build`. Python is not a desktop build or
runtime dependency; this wrapper remains for callers of the old helper path.
"""
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    if "--api-only" in sys.argv[1:]:
        raise SystemExit("原生 Rust 构建已移除 Python 浏览器驱动选项；请省略 --api-only")
    node = shutil.which("node")
    if node is None:
        raise SystemExit("构建需要 Node.js；请使用 npm --prefix desktop run native:build")
    environment = os.environ.copy()
    local = ROOT / "build/tauri-toolchain"
    if shutil.which("cargo") is None and (local / "cargo/bin/cargo").is_file():
        environment["CARGO_HOME"] = str(local / "cargo")
        environment["RUSTUP_HOME"] = str(local / "rustup")
        environment["PATH"] = str(local / "cargo/bin") + os.pathsep + environment.get("PATH", "")
    return subprocess.run([node, str(ROOT / "desktop/scripts/desktop.mjs"), *sys.argv[1:]],
                          cwd=ROOT, env=environment, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
