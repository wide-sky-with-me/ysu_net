"""Build the desktop bundle for the current platform.

    uv sync --locked --extra gui --group build
    uv run python packaging/build.py            # PyInstaller bundle + archive
    uv run python packaging/build.py --installer  # also: Windows setup.exe / Ubuntu .deb

Outputs land in ``dist/``. Cross-compiling is not supported: build Windows
packages on Windows and Ubuntu packages on Ubuntu (CI does both).
"""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[1]
PACKAGING = ROOT / "packaging"
DIST = ROOT / "dist"
BUILD = ROOT / "build" / "pyinstaller"
NAME = "ysu-net"


def version():
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]


def render_icons():
    """Rasterize the SVG app icon to PNG (Linux) and ICO (Windows)."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QGuiApplication
    app = QGuiApplication.instance() or QGuiApplication([])
    from ysu_net.gui import icons
    BUILD.mkdir(parents=True, exist_ok=True)
    png = BUILD / f"{NAME}.png"
    icons.render(icons.app_svg(), 256, 1.0).save(str(png))
    ico = BUILD / f"{NAME}.ico"
    # Qt's ICO writer stores one size per file; build a multi-size ICO by hand.
    sizes = (16, 24, 32, 48, 64, 128, 256)
    images = []
    for size in sizes:
        from PySide6.QtCore import QBuffer, QIODevice
        buffer = QBuffer()
        buffer.open(QIODevice.WriteOnly)
        icons.render(icons.app_svg(), size, 1.0).save(buffer, "PNG")
        images.append(bytes(buffer.data()))
    header = bytearray(b"\0\0\1\0" + len(sizes).to_bytes(2, "little"))
    offset = 6 + 16 * len(sizes)
    for size, data in zip(sizes, images):
        dim = 0 if size == 256 else size
        header += bytes([dim, dim, 0, 0]) + (1).to_bytes(2, "little") + (32).to_bytes(2, "little")
        header += len(data).to_bytes(4, "little") + offset.to_bytes(4, "little")
        offset += len(data)
    ico.write_bytes(bytes(header) + b"".join(images))
    del app
    return png, ico


def pyinstaller(icon):
    command = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed",
        "--name", NAME, "--icon", str(icon),
        "--distpath", str(DIST), "--workpath", str(BUILD / "work"), "--specpath", str(BUILD),
        "--paths", str(ROOT / "src"),
        # Authentication runs as a child of the same executable (see auth/worker.py).
        "--hidden-import", "ysu_net.auth.api",
        "--hidden-import", "ysu_net.auth.browser",
        # Playwright's driver ships inside the package; browsers do not. At run time the
        # browser backend uses the installed Edge / Chrome (see auth/system_browser.py).
        "--collect-all", "playwright",
        "--exclude-module", "tkinter",
        str(PACKAGING / "launcher.py"),
    ]
    if os.name != "nt":
        command.insert(-1, "--strip")
    subprocess.run(command, check=True, cwd=ROOT)
    return DIST / NAME


def smoke_test(bundle):
    exe = bundle / (f"{NAME}.exe" if os.name == "nt" else NAME)
    result = subprocess.run([str(exe), "--ysu-auth", "api", "--help"], capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=60)
    if result.returncode != 0 or "校园网" not in result.stdout:  # also checks UTF-8 output
        raise SystemExit(f"打包后的认证入口不可用：\n{result.stdout}\n{result.stderr}")
    print("[OK] bundle smoke test")
    if os.environ.get("YSU_BROWSER_CHECK") == "1":
        # Needs Edge / Chrome on the build machine; CI runners have both.
        check = subprocess.run([str(exe), "--ysu-auth", "browser-check"], capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=180)
        print(check.stdout, check.stderr)
        if check.returncode != 0:
            raise SystemExit("打包后的浏览器认证无法启动系统浏览器")


def windows_packages(bundle, ico, installer):
    archive = shutil.make_archive(str(DIST / f"YSU-Net-{version()}-windows-portable"), "zip", bundle.parent, bundle.name)
    print("[OK]", archive)
    if not installer:
        return
    shutil.copy(ico, DIST / f"{NAME}.ico")
    iscc = shutil.which("iscc") or r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
    subprocess.run([iscc, f"/DAppVersion={version()}", f"/DSourceDir={bundle}", f"/O{DIST}",
                    str(PACKAGING / "ysu-net.iss")], check=True)


def linux_packages(bundle, png, installer):
    archive = shutil.make_archive(str(DIST / f"YSU-Net-{version()}-linux-x86_64"), "gztar", bundle.parent, bundle.name)
    print("[OK]", archive)
    if not installer:
        return
    from ysu_net.gui.prefs import desktop_entry
    root = BUILD / "deb"
    shutil.rmtree(root, ignore_errors=True)
    shutil.copytree(bundle, root / "opt" / NAME)
    (root / "usr/bin").mkdir(parents=True)
    (root / "usr/bin/ysu-gui").symlink_to(f"/opt/{NAME}/{NAME}")
    apps = root / "usr/share/applications"
    apps.mkdir(parents=True)
    (apps / f"{NAME}.desktop").write_text(desktop_entry([f"/opt/{NAME}/{NAME}"]), encoding="utf-8")
    icon_dir = root / "usr/share/icons/hicolor/256x256/apps"
    icon_dir.mkdir(parents=True)
    shutil.copy(png, icon_dir / f"{NAME}.png")
    size = sum(f.stat().st_size for f in root.rglob("*") if f.is_file() and not f.is_symlink()) // 1024
    (root / "DEBIAN").mkdir()
    (root / "DEBIAN/control").write_text(
        f"Package: {NAME}\nVersion: {version()}\nSection: net\nPriority: optional\nArchitecture: amd64\n"
        f"Installed-Size: {size}\nMaintainer: ysu-net <noreply@users.noreply.github.com>\n"
        "Depends: libegl1, libfontconfig1, libxkbcommon-x11-0, libxcb-cursor0, libxcb-icccm4, "
        "libxcb-image0, libxcb-keysyms1, libxcb-render-util0, libxcb-shape0, libxcb-util1, libdbus-1-3\n"
        "Description: YSU campus network client\n 燕山大学校园网登录、运营商切换与自动重连的图形界面客户端。\n",
        encoding="utf-8")
    for path in root.rglob("*"):
        if not path.is_symlink():
            path.chmod(0o755 if path.is_dir() or os.access(path, os.X_OK) else 0o644)
    deb = DIST / f"{NAME}_{version()}_amd64.deb"
    subprocess.run(["dpkg-deb", "--root-owner-group", "--build", str(root), str(deb)], check=True)
    print("[OK]", deb)


def main():
    # Windows consoles (cp1252 on CI) cannot print the Chinese self-check output.
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="构建图形界面安装包")
    ap.add_argument("--installer", action="store_true", help="额外生成 Windows 安装程序或 Ubuntu .deb")
    args = ap.parse_args()
    png, ico = render_icons()
    bundle = pyinstaller(ico if os.name == "nt" else png)
    smoke_test(bundle)
    if os.name == "nt":
        windows_packages(bundle, ico, args.installer)
    else:
        linux_packages(bundle, png, args.installer)


if __name__ == "__main__":
    main()
