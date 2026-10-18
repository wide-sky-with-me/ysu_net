import json
import os
import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock, patch

from tests.helpers import OfflineTestCase
from tests.test_multi_accounts_switching import status
from ysu_net.gui.engine import Engine
from ysu_net.manager import accounts, cli, daemon
from ysu_net.manager.backend import Result
from ysu_net.manager.config import Config, load_config, save_config
from ysu_net.manager.locking import configuration_write, exclusive_config


class MultiAccountIntegrationTests(OfflineTestCase):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {}, clear=True))
        self.path = self.tmp / "config.json"
        save_config(self.path, Config(username="fixture-a", password="fixture-only", operation_timeout=5))
        self.target = accounts.save_account(self.path, username="fixture-b", password="fixture-only",
                                            service="中国移动")
        self.service = self.mock("ysu_net.manager.cli.service_action")
        self.mock("ysu_net.manager.cli.systemctl", side_effect=AssertionError("unexpected systemd call"))
        self.mock("sys.stdin.isatty", return_value=False)
        self.online = ("fixture-a", "校园网")
        self.calls = []
        self.ready = threading.Event()

    def command(self, *args):
        return cli.main(["--config", str(self.path), "accounts", *args])

    def runner(self, config, action, **kwargs):
        self.calls.append((threading.get_ident(), action, config.username, config.operation_timeout))
        self.ready.set()
        if action == "login":
            self.online = (config.username, config.service)
            return Result(0)
        if action == "logout":
            self.online = None
            return Result(0)
        online = status(*self.online) if self.online else status()
        if action == "info":
            return Result(0, json.dumps({"online": json.loads(online.output)["online"],
                                         "account_http_status": 200, "account": {}}))
        return online

    def engine(self):
        engine = Engine(self.path, lambda *_: None, runner=self.runner)
        self.addCleanup(engine.shutdown)
        return engine

    def test_cli_accounts_list_is_public_without_environment_passwords(self):
        with patch.dict(os.environ, {"YSU_PASS": "env-secret"}):
            self.assertEqual(self.command("list", "--raw"), 0)
        payload = json.loads(self.output.getvalue())
        self.assertTrue(payload["environment_override"])
        self.assertEqual(len(payload["items"]), 2)
        self.assertNotIn("fixture-only", self.output.getvalue())
        self.assertNotIn("env-secret", self.output.getvalue())
        self.assertTrue(all("password" not in item for item in payload["items"]))

    def test_cli_save_uses_getpass_and_no_password_argument(self):
        with patch("sys.stdin.isatty", return_value=True), patch("getpass.getpass", return_value="hidden-fixture") as prompt:
            self.assertEqual(self.command("save", "fixture-c", "--label", "C"), 0)
        prompt.assert_called_once()
        self.assertNotIn("hidden-fixture", self.output.getvalue())
        self.assertEqual(accounts.load_accounts(self.path, overlay=False)["accounts"][-1]["username"], "fixture-c")
        with self.assertRaises(SystemExit):
            cli.parser().parse_args(["accounts", "save", "fixture-x", "--password", "fixture-value"])

    def test_nonterminal_save_leaves_book_unchanged(self):
        before = accounts.accounts_path(self.path).read_bytes()
        self.assertEqual(self.command("save", "fixture-c"), 2)
        self.assertEqual(accounts.accounts_path(self.path).read_bytes(), before)

    def test_cli_direct_switch_has_independent_verification_and_no_service_effects(self):
        with patch.object(cli, "run_backend", side_effect=self.runner):
            self.assertEqual(self.command("switch", self.target["id"]), 0)
        self.assertEqual(load_config(self.path, environ={}).username, "fixture-b")
        self.assertEqual([call[1] for call in self.calls], ["status", "logout", "status", "login", "status"])
        self.service.assert_not_called()

    def test_cli_old_owner_without_channel_reports_unconfirmed_not_success(self):
        runner = self.mock("ysu_net.manager.cli.run_backend", side_effect=AssertionError("foreign lock owner"))
        before = self.path.read_bytes()
        with exclusive_config(self.path):
            self.assertEqual(self.command("switch", self.target["id"]), 2)
            with self.assertRaises(RuntimeError):
                with exclusive_config(self.path):
                    pass
        self.assertEqual(self.path.read_bytes(), before)
        runner.assert_not_called()
        self.service.assert_not_called()
        self.assertIn("未确认", self.output.getvalue())

    def test_cli_override_stops_before_delegation_even_when_owner_has_no_override(self):
        engine = self.engine()
        engine._do_set_auto(True)
        delegated = self.mock("ysu_net.manager.cli.request_control")
        with patch.dict(os.environ, {"YSU_PASS": ""}):
            self.assertEqual(self.command("switch", self.target["id"]), 2)
        delegated.assert_not_called()
        engine._release()

    def test_cli_qt_owner_executes_only_on_worker_thread_and_retains_run_lock(self):
        engine = self.engine()
        engine._do_set_auto(True)
        engine.start()
        self.assertTrue(self.ready.wait(2))
        direct = self.mock("ysu_net.manager.cli.run_backend", side_effect=AssertionError("CLI authenticated"))
        self.assertEqual(self.command("switch", self.target["id"]), 0)
        direct.assert_not_called()
        self.assertEqual(load_config(self.path, environ={}).username, "fixture-b")
        self.assertTrue(all(call[0] == engine.thread.ident for call in self.calls))
        with self.assertRaises(RuntimeError):
            with exclusive_config(self.path):
                pass
        engine.shutdown()
        with exclusive_config(self.path):
            pass
        self.assertFalse(self.path.with_suffix(".control").joinpath("owner.json").exists())
        self.service.assert_not_called()

    def test_cli_daemon_owner_executes_on_daemon_thread_without_unlocking(self):
        stop = threading.Event()
        errors = []
        def run():
            try:
                daemon.run_daemon(self.path)
            except BaseException as exc:
                errors.append(exc)
        with patch.object(daemon, "run_backend", side_effect=self.runner), \
                patch.object(daemon.signal, "signal", return_value=None), \
                patch.object(daemon, "threading", SimpleNamespace(Event=lambda: stop)):
            worker = threading.Thread(target=run, name="fixture-daemon")
            worker.start()
            try:
                self.assertTrue(self.ready.wait(2))
                direct = self.mock("ysu_net.manager.cli.run_backend", side_effect=AssertionError("CLI authenticated"))
                self.assertEqual(self.command("switch", self.target["id"]), 0)
                direct.assert_not_called()
                self.assertTrue(all(call[0] == worker.ident for call in self.calls))
                with self.assertRaises(RuntimeError):
                    with exclusive_config(self.path):
                        pass
            finally:
                stop.set()
                worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(load_config(self.path, environ={}).username, "fixture-b")
        self.service.assert_not_called()

    def test_rotation_enable_only_through_running_auto_owner(self):
        self.assertEqual(self.command("rotation", "on"), 2)
        self.assertFalse(accounts.load_accounts(self.path, overlay=False)["auto_switch"])
        engine = self.engine()
        engine._do_set_auto(True)
        engine.start()
        self.assertTrue(self.ready.wait(2))
        self.assertEqual(self.command("rotation", "on"), 0)
        self.assertTrue(accounts.load_accounts(self.path, overlay=False)["auto_switch"])
        self.assertEqual(self.command("rotation", "off"), 0)
        self.assertFalse(accounts.load_accounts(self.path, overlay=False)["auto_switch"])
        self.assertTrue(engine.accounts.rotation.disabled)
        self.service.assert_not_called()

    def test_qt_manual_account_action_uses_guard_and_verified_common_logic(self):
        events = []
        engine = Engine(self.path, lambda kind, value: events.append((kind, value)), runner=self.runner)
        engine._do_switch_account(self.target["id"])
        self.assertEqual(load_config(self.path, environ={}).username, "fixture-b")
        self.assertTrue(next(value for kind, value in events if kind == "result")["ok"])
        view = next(value for kind, value in events if kind == "accounts")
        self.assertNotIn("fixture-only", json.dumps(view))
        self.assertEqual(view["quota"]["state"], "unknown")

    def test_qt_logout_turns_off_both_reconnect_and_rotation(self):
        engine = self.engine()
        engine._do_set_auto(True)
        engine._do_rotation(True)
        self.assertTrue(accounts.load_accounts(self.path, overlay=False)["auto_switch"])
        engine._do_logout()
        self.assertFalse(engine.auto)
        self.assertTrue(engine.accounts.rotation.disabled)
        self.assertFalse(accounts.load_accounts(self.path, overlay=False)["auto_switch"])
        self.assertIsNone(self.online)
        with exclusive_config(self.path):
            pass

    def test_short_write_lock_budget_does_not_remove_lock_or_authenticate(self):
        with configuration_write(self.path):
            start = time.monotonic()
            with self.assertRaises(TimeoutError):
                with configuration_write(self.path, timeout=0.03):
                    pass
            self.assertLess(time.monotonic() - start, 0.5)
        self.assertTrue(self.path.with_name(self.path.name + ".write.lock").exists())
        self.assertEqual(self.calls, [])
