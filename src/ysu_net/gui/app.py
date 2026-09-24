"""Desktop entry point: ``ysu-gui`` / ``python -m ysu_net.gui`` / the frozen executable."""
import argparse
import sys
from pathlib import Path

from ysu_net.manager.backend import AUTH_WORKER_FLAG

SERVER_NAME = "ysu-net-gui"


def _parse(argv):
    ap = argparse.ArgumentParser(prog="ysu-gui", description="燕山大学校园网 · 图形界面")
    ap.add_argument("--minimized", action="store_true", help="启动后仅显示托盘图标")
    ap.add_argument("--config", type=Path, help="指定配置文件")
    ap.add_argument("--smoke", action="store_true", help=argparse.SUPPRESS)
    return ap.parse_args(argv)


def _already_running(app_name):
    """Forward activation to a running instance; return True if one answered."""
    from PySide6.QtNetwork import QLocalSocket
    socket = QLocalSocket()
    socket.connectToServer(app_name)
    if socket.waitForConnected(300):
        socket.write(b"show")
        socket.waitForBytesWritten(300)
        socket.disconnectFromServer()
        return True
    return False


def _serve(app_name, window):
    from PySide6.QtNetwork import QLocalServer
    QLocalServer.removeServer(app_name)  # Clears a stale socket after a crash on Unix.
    server = QLocalServer(window)
    server.newConnection.connect(lambda: (server.nextPendingConnection(), window.show_window()))
    server.listen(app_name)
    return server


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == [AUTH_WORKER_FLAG]:
        # Frozen bundles re-enter here to run an authentication child process.
        from ysu_net.auth.worker import run
        return run(argv[1:])

    args = _parse(argv)
    try:
        from PySide6.QtGui import QFont
        from PySide6.QtWidgets import QApplication
    except ImportError:
        print("缺少图形界面依赖，请运行：uv sync --extra gui", file=sys.stderr)
        return 2

    from ysu_net.manager.config import config_path
    from . import prefs as prefs_mod
    from .theme import font_families

    if sys.platform == "win32":
        try:  # Group the taskbar button under our icon instead of python.exe.
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("YSU.Net.Client")
        except (AttributeError, OSError):
            pass

    app = QApplication(sys.argv[:1])
    app.setApplicationName("YSU Net")
    app.setOrganizationName("ysu-net")
    app.setDesktopFileName("ysu-net")
    app.setStyle("Fusion")
    app.setQuitOnLastWindowClosed(False)
    font = QFont()
    font.setFamilies(font_families())
    font.setPointSizeF(10)
    app.setFont(font)

    config_file = (args.config or config_path()).expanduser().absolute()
    # One instance per user; a second launch just brings the existing window forward.
    server_name = f"{SERVER_NAME}-{Path.home().name}"
    if not args.smoke and _already_running(server_name):
        return 0

    from .window import MainWindow
    if args.smoke:
        # Packaging check: build and render every page, then exit without any network access.
        from PySide6.QtCore import QTimer
        window = MainWindow(config_file, prefs_mod.Prefs(), offline=True)
        for index in range(window.stack.count()):
            window._navigate(index)
            app.processEvents()
        QTimer.singleShot(500, window.quit)
        app.exec()
        print(f"[OK] GUI smoke test · Qt platform {app.platformName()}")
        return 0
    window = MainWindow(config_file, prefs_mod.load_prefs(prefs_mod.prefs_path(config_file)),
                        start_hidden=args.minimized)
    window.server = _serve(server_name, window)
    return app.exec()
