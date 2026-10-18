"""Shell entry and interactive account management, with isolated fixtures only."""
import json
import os
from pathlib import Path
import select
import signal
import subprocess
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch


from tests.helpers import OfflineTestCase
from ysu_net.manager import cli
from ysu_net.manager.config import Config, save_config


class ShellAccountEntryTests(OfflineTestCase):
    def setUp(self):
        super().setUp()
        self.path = self.tmp / "private config" / "config.json"
        save_config(self.path, Config(username="fixture-current", password="fixture-current-secret"))
        self.mock("sys.stdin.isatty", return_value=True)
        self.stack.enter_context(patch.dict(os.environ, {}, clear=True))

    def test_accounts_without_action_opens_interactive_menu(self):
        args = cli.parser().parse_args(["accounts"])
        self.assertIsNone(args.account_action)
        with patch("builtins.input", return_value="0"):
            self.assertEqual(cli.account_command(args, self.path), 0)
        self.assertIn("多账号", self.output.getvalue())

    def test_enabled_flag_can_reverse_disabled_without_changing_defaults(self):
        parser = cli.parser()
        self.assertIsNone(parser.parse_args(["accounts", "save", "fixture"]).disabled)
        self.assertTrue(parser.parse_args(["accounts", "save", "fixture", "--disabled"]).disabled)
        self.assertFalse(parser.parse_args(["accounts", "save", "fixture", "--enabled"]).disabled)
        with self.assertRaises(SystemExit):
            parser.parse_args(["accounts", "save", "fixture", "--enabled", "--disabled"])

    def test_main_menu_exposes_accounts_and_preserves_scope_and_path(self):
        args = cli.parser().parse_args(["--scope", "system", "menu"])
        with patch.object(cli, "main") as dispatch, patch("builtins.input", side_effect=["16", "0"]):
            self.assertEqual(cli.menu(args, self.path), 0)
        dispatch.assert_called_once_with(["--scope", "system", "--config", str(self.path), "accounts"])


class ShellAccountMenuTests(OfflineTestCase):
    def setUp(self):
        super().setUp()
        from ysu_net.manager import accounts
        self.accounts = accounts
        self.path = self.tmp / "private config" / "config.json"
        save_config(self.path, Config(username="fixture-current", password="fixture-current-secret"))
        self.backup = accounts.save_account(self.path, username="fixture-backup", password="fixture-backup-secret", label="Backup")
        self.stack.enter_context(patch.dict(os.environ, {}, clear=True))
        self.mock("sys.stdin.isatty", return_value=True)
        self.password = self.mock("ysu_net.manager.cli.getpass.getpass", return_value="")
        self.backend = self.mock("ysu_net.manager.cli.run_backend", side_effect=AssertionError("unexpected auth"))
        self.service = self.mock("ysu_net.manager.cli.service_action", side_effect=AssertionError("unexpected service"))

    def number(self, username):
        return str(next(i for i, entry in enumerate(self.accounts.public_accounts(self.path)["items"], 1) if entry["username"] == username))

    def run_menu(self, inputs):
        with patch("builtins.input", side_effect=inputs):
            return cli.main(["--config", str(self.path), "accounts"])

    def test_add_keeps_active_account_and_hides_password(self):
        self.password.return_value = "fixture-new-secret"
        self.assertEqual(self.run_menu(["2", "fixture-new", "New", "2", "1", "0"]), 0)
        entry = next(e for e in self.accounts.load_accounts(self.path)["accounts"] if e["username"] == "fixture-new")
        self.assertEqual((entry["service"], entry["backend"], entry["password"]), ("中国移动", "api", "fixture-new-secret"))
        self.assertEqual(cli.load_config(self.path, environ={}).username, "fixture-current")
        self.assertNotIn("fixture-new-secret", self.output.getvalue() + self.errors.getvalue())
        self.backend.assert_not_called()

    def test_leading_option_characters_are_data_not_cli_flags(self):
        self.password.return_value = "fixture-option-secret"
        self.assertEqual(self.run_menu(["2", "--enabled", "--help", "", "", "0"]), 0)
        entry = next(e for e in self.accounts.load_accounts(self.path)["accounts"] if e["username"] == "--enabled")
        self.assertEqual(entry["label"], "--help")
        self.assertTrue(entry["enabled"])

    def test_edit_keeps_username_and_empty_password_preserves_secret(self):
        self.assertEqual(self.run_menu(["3", self.number("fixture-backup"), "Renamed", "", "", "0"]), 0)
        entry = next(e for e in self.accounts.load_accounts(self.path)["accounts"] if e["id"] == self.backup["id"])
        self.assertEqual((entry["username"], entry["label"], entry["password"]), ("fixture-backup", "Renamed", "fixture-backup-secret"))
        self.assertIn("用户名（固定）", self.output.getvalue())
        self.assertNotIn("fixture-backup-secret", self.output.getvalue())

    def test_toggle_is_reversible_and_never_prompts_for_or_replaces_secret(self):
        index = self.number("fixture-backup")
        self.assertEqual(self.run_menu(["6", index, "6", index, "0"]), 0)
        entry = next(e for e in self.accounts.load_accounts(self.path)["accounts"] if e["id"] == self.backup["id"])
        self.assertTrue(entry["enabled"])
        self.assertEqual(entry["password"], "fixture-backup-secret")
        self.password.assert_not_called()
        self.backend.assert_not_called()

    def test_enabled_cli_flag_reactivates_an_existing_account(self):
        args = ["--config", str(self.path), "accounts", "save", "fixture-backup", "--id", self.backup["id"]]
        self.assertEqual(cli.main([*args, "--disabled"]), 0)
        self.assertFalse(self.accounts.public_accounts(self.path)["items"][0]["enabled"])
        self.assertEqual(cli.main([*args, "--enabled"]), 0)
        self.assertTrue(self.accounts.public_accounts(self.path)["items"][0]["enabled"])
        self.assertEqual(self.accounts.load_accounts(self.path)["accounts"][0]["password"], "fixture-backup-secret")

    def test_declining_switch_and_delete_is_read_only(self):
        before = self.accounts.accounts_path(self.path).read_bytes()
        index = self.number("fixture-backup")
        self.assertEqual(self.run_menu(["4", index, "", "5", index, "n", "0"]), 0)
        self.assertEqual(self.accounts.accounts_path(self.path).read_bytes(), before)
        self.backend.assert_not_called()

    def test_current_delete_and_out_of_range_selection_never_mutate(self):
        before = self.path.read_bytes(), self.accounts.accounts_path(self.path).read_bytes()
        self.assertEqual(self.run_menu(["5", self.number("fixture-current"), "4", "99", "0"]), 0)
        self.assertEqual((self.path.read_bytes(), self.accounts.accounts_path(self.path).read_bytes()), before)
        self.backend.assert_not_called()

    def test_switch_delegates_to_existing_verified_executor(self):
        outcome = SimpleNamespace(code=0, message="fixture 已独立核验")
        with patch.object(cli, "switch_account", return_value=outcome) as switch:
            self.assertEqual(self.run_menu(["4", self.number("fixture-backup"), "y", "0"]), 0)
        switch.assert_called_once_with(self.path, self.backup["id"], runner=self.backend)
        self.assertIn("fixture 已独立核验", self.output.getvalue())
        self.service.assert_not_called()

    def test_running_owner_receives_switch_and_rotation_without_service_restart(self):
        from ysu_net.manager.locking import exclusive_config
        responses = [{"code": 3, "message": "fixture 未确认"}, {"code": 0, "message": "fixture 轮换开启"}, {"code": 0, "message": "fixture 轮换关闭"}]
        with exclusive_config(self.path), patch.object(cli, "request_control", side_effect=responses) as control:
            self.assertEqual(self.run_menu(["4", self.number("fixture-backup"), "y", "7", "yes", "8", "0"]), 0)
        self.assertEqual([call.args[1:] for call in control.call_args_list], [("switch_account", {"id": self.backup["id"]}), ("rotation", {"enabled": True}), ("rotation", {"enabled": False})])
        self.assertIn("[失败] fixture 未确认", self.output.getvalue())
        self.assertNotIn("[完成] fixture 未确认", self.output.getvalue())
        self.service.assert_not_called()
        self.backend.assert_not_called()

    def test_enabling_without_an_auto_owner_does_not_start_services_or_claim_success(self):
        self.assertEqual(self.run_menu(["7", "y", "0"]), 0)
        self.assertFalse(self.accounts.public_accounts(self.path)["auto_switch"])
        self.assertNotIn("[完成]", self.output.getvalue())
        self.service.assert_not_called()

    def test_environment_override_blocks_switch_and_rotation_but_allows_disable(self):
        with patch.dict(os.environ, {"YSU_USER": "fixture-environment-user"}):
            self.assertEqual(self.run_menu(["4", "7", "8", "0"]), 0)
        self.assertFalse(self.accounts.public_accounts(self.path)["auto_switch"])
        self.assertNotIn("fixture-environment-user", self.accounts.accounts_path(self.path).read_text())
        self.backend.assert_not_called()

    def test_bad_book_blocks_writes_but_disable_still_reaches_the_owner(self):
        from ysu_net.manager.locking import exclusive_config
        self.accounts.accounts_path(self.path).write_text("broken fixture")
        with exclusive_config(self.path), patch.object(cli, "request_control", return_value={"code": 3, "message": "fixture 已停止，保存未确认"}) as control:
            self.assertEqual(self.run_menu(["2", "4", "7", "8", "0"]), 0)
        self.assertEqual(self.accounts.accounts_path(self.path).read_text(), "broken fixture")
        self.assertEqual(control.call_args.args[1:], ("rotation", {"enabled": False}))
        self.backend.assert_not_called()

    def test_cancel_before_password_and_interrupt_are_read_only(self):
        before = self.accounts.accounts_path(self.path).read_bytes()
        self.assertEqual(self.run_menu(["2", "fixture-aborted", "", "0", "0"]), 0)
        self.password.assert_not_called()
        with patch("builtins.input", side_effect=KeyboardInterrupt):
            self.assertEqual(cli.main(["--config", str(self.path), "accounts", "menu"]), 130)
        self.assertEqual(self.accounts.accounts_path(self.path).read_bytes(), before)

    def test_eof_during_hidden_password_exits_without_writing(self):
        before = self.accounts.accounts_path(self.path).read_bytes()
        self.password.side_effect = EOFError
        self.assertEqual(self.run_menu(["2", "fixture-aborted", "", "", ""]), 130)
        self.assertEqual(self.accounts.accounts_path(self.path).read_bytes(), before)
        self.backend.assert_not_called()

    def test_non_tty_menu_does_not_read_input_or_mutate(self):
        with patch("sys.stdin.isatty", return_value=False), patch("builtins.input") as input_call:
            self.assertEqual(cli.main(["--config", str(self.path), "accounts"]), 0)
        input_call.assert_not_called()
        self.password.assert_not_called()


@unittest.skipUnless(os.name == "posix", "POSIX Shell/PTY integration")
class RealShellAccountTests(OfflineTestCase):
    def setUp(self):
        super().setUp()
        from ysu_net.manager import install
        self.path = self.tmp / "private config $and" / "config.json"
        save_config(self.path, Config(username="fixture-current", password="fixture-current-secret"))
        self.wrapper = self.tmp / "bin" / "ysu"
        self.wrapper.parent.mkdir()
        self.wrapper.write_text(install.wrapper("user"))
        self.wrapper.chmod(0o755)
        self.cwd = self.tmp / "outside checkout"
        self.cwd.mkdir()
        hook = self.tmp / "network denied"
        hook.mkdir()
        (hook / "sitecustomize.py").write_text(
            "import socket\n"
            "def denied(*args, **kwargs):\n    raise AssertionError('fixture forbids network and services')\n"
            "socket.socket.connect = denied\nsocket.create_connection = denied\nsocket.getaddrinfo = denied\n"
            "from ysu_net.manager import cli\n"
            "cli.run_backend = denied\ncli.service_action = denied\ncli.systemctl = denied\ncli.run_daemon = denied\n"
        )
        self.env = dict(os.environ, PYTHONPATH=f"{hook}{os.pathsep}{Path(cli.__file__).resolve().parents[2]}",
                        NO_COLOR="1", TERM="dumb", PYTHONDONTWRITEBYTECODE="1")
        for name in ("YSU_USER", "YSU_PASS", "YSU_SERVICE"):
            self.env.pop(name, None)

    def start_menu(self):
        import pty
        master, slave = pty.openpty()
        self.addCleanup(os.close, master)
        try:
            process = subprocess.Popen([str(self.wrapper), "--config", str(self.path), "accounts"],
                                       cwd=self.cwd, env=self.env, stdin=slave, stdout=slave, stderr=slave,
                                       start_new_session=True)
        finally:
            os.close(slave)

        def stop():
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)
        self.addCleanup(stop)
        captured = bytearray()
        cursor = 0

        def expect(text):
            nonlocal cursor
            target = text.encode()
            deadline = time.monotonic() + 10
            while True:
                found = captured.find(target, cursor)
                if found >= 0:
                    cursor = found + len(target)
                    return
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self.fail(f"TTY prompt timeout: {text}")
                ready, _, _ = select.select([master], [], [], remaining)
                if ready:
                    try:
                        data = os.read(master, 65536)
                    except OSError:
                        self.fail(f"TTY exited before prompt: {text}; code={process.poll()}")
                    if not data:
                        self.fail(f"TTY EOF before prompt: {text}")
                    captured.extend(data)

        def send(text):
            os.write(master, text.encode() + b"\n")
        return process, expect, send, captured

    def test_real_generated_shell_tty_crud_and_hidden_password(self):
        from ysu_net.manager import accounts
        process, expect, send, captured = self.start_menu()
        expect("多账号操作 [0 返回]")
        send("2")
        expect("用户名:")
        send("fixture-shell")
        expect("名称（编辑时留空保留）")
        send("Shell fixture")
        expect("运营商 [Enter")
        send("2")
        expect("认证方式 [Enter")
        send("1")
        expect("密码（更新时留空保留）")
        secret = "FIXTURE-PTY-PASSWORD"
        send(secret)
        expect("账号已保存")
        expect("多账号操作 [0 返回]")
        item = accounts.load_accounts(self.path)["accounts"][0]
        self.assertEqual((item["username"], item["service"], item["password"]), ("fixture-shell", "中国移动", secret))
        self.assertNotIn(secret.encode(), captured)
        self.assertEqual(accounts.accounts_path(self.path).stat().st_mode & 0o777, 0o600)
        send("3")
        expect("账号编号")
        send("1")
        expect("名称（编辑时留空保留）")
        send("Renamed shell")
        expect("运营商 [Enter")
        send("")
        expect("认证方式 [Enter")
        send("")
        expect("密码（更新时留空保留）")
        send("")
        expect("账号已保存")
        expect("多账号操作 [0 返回]")
        item = accounts.load_accounts(self.path)["accounts"][0]
        self.assertEqual((item["label"], item["password"]), ("Renamed shell", secret))
        for enabled in (False, True):
            send("6")
            expect("账号编号")
            send("1")
            expect("候选状态已保存")
            expect("多账号操作 [0 返回]")
            self.assertIs(accounts.load_accounts(self.path)["accounts"][0]["enabled"], enabled)
        send("4")
        expect("账号编号")
        send("1")
        expect("继续？ [y/N]")
        send("n")
        expect("多账号操作 [0 返回]")
        self.assertEqual(cli.load_config(self.path, environ={}).username, "fixture-current")
        send("8")
        expect("自动轮换已关闭")
        expect("多账号操作 [0 返回]")
        send("5")
        expect("账号编号")
        send("1")
        expect("删除选中的保存账号？ [y/N]")
        send("y")
        expect("账号已删除")
        expect("多账号操作 [0 返回]")
        self.assertEqual(accounts.load_accounts(self.path)["accounts"][-1]["username"], "fixture-current")
        self.assertFalse(any(e["username"] == "fixture-shell" for e in accounts.load_accounts(self.path)["accounts"]))
        send("0")
        self.assertEqual(process.wait(timeout=5), 0)
        self.assertNotIn(secret.encode(), captured)

    def test_real_shell_non_tty_raw_output_remains_machine_readable(self):
        from ysu_net.manager import accounts
        accounts.save_account(self.path, username="fixture-shell", password="fixture-shell-secret")
        result = subprocess.run([str(self.wrapper), "--config", str(self.path), "accounts", "list", "--raw"],
                                cwd=self.cwd, env=self.env, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        view = json.loads(result.stdout)
        self.assertEqual(view["items"][0]["username"], "fixture-shell")
        self.assertNotIn("fixture-shell-secret", result.stdout + result.stderr)
        self.assertTrue(all("password" not in entry for entry in view["items"]))


