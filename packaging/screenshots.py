"""Render every page with a fake backend (no network) for visual review.

    uv run python packaging/screenshots.py [output-dir]

Uses a throwaway config directory; never touches the real configuration.
"""
import json
import os
from pathlib import Path
import sys
import tempfile
import time

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "dist/screenshots").absolute()
TMP = Path(tempfile.mkdtemp())
os.environ["XDG_CONFIG_HOME"] = os.environ["APPDATA"] = str(TMP)

from ysu_net.manager.backend import Result  # noqa: E402
from ysu_net.manager.config import Config, save_config  # noqa: E402

ONLINE = {"data": {"portalOnlineUserInfo": {
    "result": "success", "userName": "2023000001", "userId": "2023000001", "userIp": "10.12.34.56",
    "ssid": "YSU-WLAN", "service": "中国移动", "realServiceName": "中国移动"}}}
ACCOUNT = {"data": {"name": "示例用户", "service": "中国移动", "accountInfo": [
    {"title": "剩余流量", "content": "38.62 GB"}, {"title": "套餐&余额", "content": "¥ 25.80"},
    {"title": "本月已用", "content": "21.4 GB"}, {"title": "到期时间", "content": "2026-12-31"}]}}


def fake_backend(config, action, raw=False, stop_event=None, **_):
    time.sleep(0.1)
    if action == "status":
        return Result(0, json.dumps({"online": ONLINE, "is_online": True}))
    if action == "info":
        return Result(0, json.dumps({"online": ONLINE, "account": ACCOUNT}))
    return Result(0)


def main():
    import faulthandler
    # A hang must fail loudly (with every thread's stack) rather than stall CI.
    faulthandler.dump_traceback_later(120, exit=True)
    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication, QScrollArea
    from ysu_net.gui import engine, prefs, theme
    from ysu_net.gui.widgets import Confirm
    from ysu_net.gui.window import MainWindow

    engine.Engine.__init__.__defaults__ = (fake_backend,)
    OUT.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    app.setStyle("Fusion")
    font = QFont()
    font.setFamilies(theme.font_families())
    font.setPointSizeF(10)
    app.setFont(font)
    config = TMP / "ysu-net/config.json"
    save_config(config, Config(username="2023000001", password="x", service="中国移动"))
    windows = []

    def shoot(mode):
        window = MainWindow(config, prefs.Prefs(theme=mode, auto_reconnect=True), start_hidden=False)
        window.resize(980, 660)
        windows.append(window)

        def snap(index, name, scroll=0):
            window._navigate(index)
            window.stack.widget(index).findChild(QScrollArea).verticalScrollBar().setValue(scroll)
            QTimer.singleShot(300, lambda: window.grab().save(str(OUT / f"{mode}-{name}.png")))

        def dialog():
            box = Confirm(window, "切换到中国联通", "将从“中国移动”切换到“中国联通”。切换会先下线再登录，"
                          "期间网络短暂中断；若新服务登录失败，会尝试恢复原连接。", "立即切换")
            box.show()
            app.processEvents()
            box.grab().save(str(OUT / f"{mode}-dialog.png"))
            box.close()

        plan = [(1500, lambda: snap(0, "overview")), (1600, lambda: window._navigate(1)),
                (2600, lambda: snap(1, "account")), (3200, lambda: snap(2, "settings")),
                (3800, lambda: snap(2, "settings-lower", 600)), (4400, lambda: snap(3, "logs")),
                (5000, dialog)]
        for delay, step in plan:
            QTimer.singleShot(delay, step)

    shoot("light")

    def next_theme():
        # Both windows share one profile; release the first one's reconnect lock.
        windows[0].engine.shutdown()
        shoot("dark")
    QTimer.singleShot(5600, next_theme)
    QTimer.singleShot(11500, app.quit)
    app.exec()
    for window in windows:
        window.quitting = True
        window.engine.shutdown()
    print(f"[OK] screenshots in {OUT}")


if __name__ == "__main__":
    main()
