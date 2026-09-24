import importlib.util
import json
import os
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from helpers import OFFLINE, ONLINE, OfflineTestCase
from ysu_net.auth import worker
from ysu_net.auth.account import account_summary
from ysu_net.gui import prefs
from ysu_net.gui.engine import EXTERNAL_DAEMON, Engine, parse_status
from ysu_net.manager import backend
from ysu_net.manager.backend import Result
from ysu_net.manager.config import Config, load_config, save_config
from ysu_net.manager.locking import exclusive_config


def status(payload, code=None):
    online = payload is ONLINE
    return Result(0 if online else 1 if code is None else code,
                  json.dumps({"online": payload, "is_online": online}))


class ParseStatusTests(unittest.TestCase):
    def test_online_offline_and_failure(self):
        online = parse_status(status(ONLINE))
        self.assertEqual((online.online, online.service, online.user), (True, "校园网", "mock-user"))
        self.assertIs(parse_status(status(OFFLINE)).online, False)
        failed = parse_status(Result(2, reason="dns"))
        self.assertIsNone(failed.online)
        self.assertIn("DNS", failed.message)

    def test_malformed_output_is_unknown(self):
        self.assertIsNone(parse_status(Result(0, "not json")).online)


class EngineTests(OfflineTestCase):
    def setUp(self):
        super().setUp()
        self.path = self.tmp / "config.json"
        save_config(self.path, Config(username="user", password="secret"))
        self.events = []
        self.calls = []
        self.responses = {}
        self.engine = Engine(self.path, lambda kind, payload: self.events.append((kind, payload)),
                             runner=self.runner)

    def runner(self, config, action, raw=False, stop_event=None):
        self.calls.append((action, raw, config.service))
        response = self.responses.get(action, Result(0))
        return response.pop(0) if isinstance(response, list) else response

    def kinds(self, kind):
        return [payload for k, payload in self.events if k == kind]

    def test_login_reports_and_refreshes_status(self):
        self.responses["status"] = status(ONLINE)
        self.engine._do_login()
        self.assertEqual([c[0] for c in self.calls], ["login", "status"])
        self.assertTrue(self.kinds("result")[0]["ok"])
        self.assertTrue(self.kinds("status")[-1].online)

    def test_login_without_credentials_does_not_spawn(self):
        save_config(self.path, Config())
        with self.assertRaisesRegex(ValueError, "账号"):
            self.engine._do_login()
        self.assertEqual(self.calls, [])

    def test_manual_login_refused_while_external_daemon_holds_lock(self):
        with exclusive_config(self.path):
            with self.assertRaisesRegex(RuntimeError, "ysu stop"):
                self.engine._do_login()
        self.assertNotIn("login", [c[0] for c in self.calls])

    def test_auto_reports_external_daemon(self):
        with exclusive_config(self.path):
            self.engine._do_set_auto(True)
        self.assertFalse(self.engine.auto)
        self.assertEqual(self.kinds("auto")[-1], {"state": "external", "message": EXTERNAL_DAEMON})

    def test_auto_tick_reconnects_and_logout_disables_it(self):
        self.responses["status"] = [status(OFFLINE), status(OFFLINE), status(OFFLINE)]
        self.engine._do_set_auto(True)
        self.assertTrue(self.engine.auto)
        self.engine._do_tick()
        self.assertEqual([c[0] for c in self.calls], ["status", "login"])
        self.assertEqual(self.kinds("auto")[-1]["message"], "重连成功")
        self.engine._do_logout()
        self.assertFalse(self.engine.auto)
        self.assertEqual(self.kinds("auto")[-1]["state"], "off")
        # The lock is released, so a fresh holder can take it.
        with exclusive_config(self.path):
            pass

    def test_status_checks_always_request_raw_json(self):
        self.responses["status"] = status(ONLINE)
        self.engine._run(Config(), "status", raw=True)
        self.assertEqual(self.calls, [("status", True, "校园网")])

    def test_switch_updates_configured_service_after_verification(self):
        moved = dict(ONLINE, data={"portalOnlineUserInfo": dict(
            ONLINE["data"]["portalOnlineUserInfo"], service="中国移动", userName="user")})
        user_online = {"data": {"portalOnlineUserInfo": dict(ONLINE["data"]["portalOnlineUserInfo"], userName="user")}}
        self.responses["status"] = [
            Result(0, json.dumps({"online": user_online, "is_online": True})),
            status(OFFLINE),
            Result(0, json.dumps({"online": moved, "is_online": True})),
            Result(0, json.dumps({"online": moved, "is_online": True})),
        ]
        self.engine._do_switch("中国移动")
        self.assertTrue(self.kinds("result")[-1]["ok"])
        self.assertEqual(load_config(self.path, environ={}).service, "中国移动")

    def test_info_summary(self):
        account = {"data": {"name": "张三", "accountInfo": [{"title": "剩余流量", "content": "<b>5 GB</b>"}]}}
        self.responses["info"] = Result(0, json.dumps({"online": ONLINE, "account": account}))
        self.engine._do_info()
        summary = self.kinds("info")[-1]
        self.assertEqual(summary["items"], [("剩余流量", "5 GB")])
        self.assertIn(("用户", "张三"), summary["fields"])

    def test_thread_loop_serializes_tasks_and_stops(self):
        self.responses["status"] = status(ONLINE)
        self.engine.start()
        self.engine.submit("status")
        self.engine.shutdown()
        self.assertFalse(self.engine.thread.is_alive())
        self.assertIn(("status", True, "校园网"), self.calls)


class AccountSummaryTests(unittest.TestCase):
    def test_offline_and_unknown(self):
        self.assertEqual(account_summary(OFFLINE, None), {"online": False, "fields": [], "items": []})
        self.assertIsNone(account_summary({"bad": 1}, None))


class PrefsTests(OfflineTestCase):
    def test_invalid_file_falls_back_to_defaults(self):
        path = self.tmp / "gui.json"
        path.write_text('{"theme": "neon", "close_to_tray": "yes", "extra": 1}')
        loaded = prefs.load_prefs(path)
        self.assertEqual(loaded, prefs.Prefs())
        prefs.save_prefs(path, prefs.Prefs(theme="dark", auto_reconnect=True))
        self.assertEqual(prefs.load_prefs(path), prefs.Prefs(theme="dark", auto_reconnect=True))

    def test_desktop_exec_quotes_paths(self):
        entry = prefs.desktop_entry(["/opt/my app/ysu-net", "--minimized"])
        self.assertIn('Exec="/opt/my app/ysu-net" --minimized', entry)
        self.assertIn('"a\\$b"', prefs.desktop_entry(["a$b"]))

    @unittest.skipIf(os.name == "nt", "XDG autostart is Linux-only")
    def test_linux_autostart_roundtrip(self):
        with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.tmp)}):
            prefs.set_autostart(True)
            self.assertTrue(prefs.autostart_enabled())
            text = (self.tmp / "autostart/ysu-net.desktop").read_text()
            self.assertIn("--minimized", text)
            self.assertIn("X-GNOME-Autostart-enabled=true", text)
            prefs.set_autostart(False)
            self.assertFalse(prefs.autostart_enabled())


class FrozenBundleTests(OfflineTestCase):
    def test_frozen_bundle_reenters_its_executable(self):
        with patch.object(backend, "FROZEN", True):
            self.assertEqual(backend.auth_command("api"), [sys.executable, "--ysu-auth", "api"])
        self.assertEqual(backend.auth_command("api"), [sys.executable, "-m", "ysu_net.auth.api"])

    def test_worker_rejects_unknown_backend_and_propagates_exit_code(self):
        self.assertEqual(worker.run(["evil"]), 2)
        with patch.object(sys, "argv", ["x"]):
            self.assertEqual(worker.run(["api", "--help"]), 0)

    def test_windows_config_directory(self):
        from ysu_net.manager import config
        fake_os = SimpleNamespace(name="nt", environ={"APPDATA": "C:/Users/u/AppData/Roaming"})
        with patch.object(config, "os", fake_os):
            self.assertEqual(config.config_path().as_posix(), "C:/Users/u/AppData/Roaming/ysu-net/config.json")


@unittest.skipUnless(importlib.util.find_spec("PySide6"), "PySide6 未安装")
class WindowSmokeTests(OfflineTestCase):
    def test_window_builds_offscreen_without_network(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        from ysu_net.gui import window
        app = QApplication.instance() or QApplication([])
        path = self.tmp / "config.json"
        save_config(path, Config(username="user", password="secret"))
        with patch.object(window.Engine, "start"), patch.object(window.Engine, "submit"):
            win = window.MainWindow(path, prefs.Prefs(theme="dark"), start_hidden=True)
            win._on_event("status", parse_status(status(ONLINE)))
            self.assertEqual(win.connect_button.text(), "断开连接")
            win._on_event("info", account_summary(ONLINE, {"data": {"accountInfo": []}}))
            self.assertTrue(win.tiles.count() >= 2)
            win.quitting = True
            win.engine.shutdown(timeout=0)
            win.close()
            win.tray and win.tray.hide()
            win.deleteLater()
        from PySide6.QtCore import QCoreApplication, QEvent
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


if __name__ == "__main__":
    unittest.main()
