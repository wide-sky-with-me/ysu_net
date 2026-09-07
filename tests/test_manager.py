from dataclasses import replace
import json
import os
from pathlib import Path
import signal
import shutil
import stat
import subprocess
import threading
from unittest.mock import Mock, call, patch

from ysu_manager import backend, cli, config, daemon, install, service
from ysu_manager.backend import Result
from tests.helpers import OfflineTestCase


class ConfigTests(OfflineTestCase):
    def test_roundtrip_permissions_and_special_password(self):
        path = self.tmp / "settings/config.json"
        original = config.Config(username="user", password='  a\"$()\\\n秘密  ')
        config.save_config(path, original)
        self.assertEqual(config.load_config(path, environ={}), original)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)

    def test_show_redacts_username_and_password(self):
        public = json.dumps(config.public_config(config.Config(username="private-user", password="secret")))
        self.assertNotIn("private-user", public)
        self.assertNotIn("secret", public)

    def test_environment_override_does_not_trim_password(self):
        value = config.load_config(self.tmp / "missing", environ={"YSU_USER": "u", "YSU_PASS": " p "})
        self.assertEqual(value.password, " p ")

    def test_invalid_config_rejected(self):
        for kwargs in ({"retry_interval": 0}, {"verify_tls": "false"}, {"backend": "shell"}, {"base": "http://example.com"}, {"cas_host": "https://u:p@example.com"}, {"max_retry_interval": 1}, {"password": 123}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                config.Config(**kwargs).validate()

    def test_invalid_json_and_unknown_fields(self):
        path = self.tmp / "config.json"
        for content in ('{"password": "secret",', '{"extra": 1}', '[]'):
            path.write_text(content)
            with self.assertRaises(ValueError):
                config.load_config(path, environ={})

    def test_rewrite_does_not_leave_secret_temporary_files(self):
        path = self.tmp / "config.json"
        config.save_config(path, config.Config(password="old"))
        config.save_config(path, config.Config(password="new"))
        self.assertEqual(list(self.tmp.iterdir()), [path])
        self.assertNotIn("old", path.read_text())


class ReconnectTests(OfflineTestCase):
    def setUp(self):
        super().setUp()
        self.config = config.Config(username="u", password="p")
        self.runner = Mock()
        self.worker = daemon.Reconnector(self.runner, jitter=lambda *_: 0)

    def test_online_never_logs_in(self):
        self.runner.return_value = Result(0)
        delay, message = self.worker.step(self.config)
        self.assertEqual(delay, 15)
        self.runner.assert_called_once_with(self.config, "status")

    def test_unknown_backs_off_without_login(self):
        self.runner.return_value = Result(2)
        delays = [self.worker.step(self.config)[0] for _ in range(7)]
        self.assertEqual(delays, [30, 60, 120, 240, 480, 900, 900])
        self.assertTrue(all(c.args[1] == "status" for c in self.runner.call_args_list))

    def test_confirmed_offline_logs_in(self):
        self.runner.side_effect = [Result(1), Result(0)]
        self.assertEqual(self.worker.step(self.config)[0], 15)
        self.assertEqual(self.runner.call_args_list, [call(self.config, "status"), call(self.config, "login")])

    def test_failed_login_backs_off(self):
        self.runner.side_effect = [Result(1), Result(3), Result(1), Result(3)]
        self.assertEqual(self.worker.step(self.config)[0], 30)
        self.assertEqual(self.worker.step(self.config)[0], 60)

    def test_success_resets_backoff(self):
        self.runner.side_effect = [Result(2), Result(0), Result(2)]
        self.assertEqual([self.worker.step(self.config)[0] for _ in range(3)], [30, 15, 30])

    def test_auth_rejection_pauses_until_credentials_change(self):
        self.runner.side_effect = [Result(1), Result(4), Result(1), Result(1), Result(0)]
        self.worker.step(self.config)
        self.worker.step(self.config)
        self.assertEqual(sum(c.args[1] == "login" for c in self.runner.call_args_list), 1)
        changed = replace(self.config, password="new")
        self.worker.step(changed)
        self.assertEqual(self.runner.call_args_list[-1], call(changed, "login"))

    def test_online_after_manual_login_clears_pause(self):
        self.runner.side_effect = [Result(1), Result(4), Result(0), Result(1), Result(0)]
        for _ in range(3):
            self.worker.step(self.config)
        self.assertEqual(sum(c.args[1] == "login" for c in self.runner.call_args_list), 2)

    def test_daemon_once_reads_config_without_network(self):
        path = self.tmp / "config.json"
        config.save_config(path, self.config)
        runner = self.mock("ysu_manager.daemon.run_backend", return_value=Result(0))
        self.assertEqual(daemon.run_daemon(path, once=True), 0)
        self.assertEqual(runner.call_args.args[:2], (self.config, "status"))

    def test_duplicate_daemon_is_rejected(self):
        import fcntl
        path = self.tmp / "config.json"
        config.save_config(path, self.config)
        with path.with_suffix(".lock").open("a") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(RuntimeError, "已有守护"):
                daemon.run_daemon(path, once=True)


class BackendTests(OfflineTestCase):
    def setUp(self):
        super().setUp()
        self.config = config.Config(username="user", password="secret")
        self.process = Mock(pid=999999, returncode=0)
        self.process.communicate.return_value = ("online\n", "")
        self.popen = self.mock("ysu_manager.backend.subprocess.Popen", return_value=self.process)
        self.kill = self.mock("ysu_manager.backend.os.killpg")

    def test_credentials_in_environment_only_and_stdin_closed(self):
        result = backend.run_backend(self.config, "login")
        args, kwargs = self.popen.call_args
        self.assertNotIn("secret", " ".join(args[0]))
        self.assertEqual(kwargs["env"]["YSU_PASS"], "secret")
        self.assertEqual(kwargs["stdin"], subprocess.DEVNULL)
        self.assertEqual(kwargs["env"]["YSU_SAVE_DEBUG_FILES"], "0")
        self.assertTrue(kwargs["start_new_session"])
        self.assertEqual(result.code, 0)

    def test_missing_credentials_prevents_spawn(self):
        self.assertEqual(backend.run_backend(config.Config(), "login").code, 4)
        self.popen.assert_not_called()

    def test_timeout_kills_browser_process_group(self):
        self.mock("ysu_manager.backend.time.monotonic", side_effect=[0, 181])
        self.assertEqual(backend.run_backend(self.config, "status").code, 3)
        self.kill.assert_called_once_with(999999, signal.SIGKILL)
        self.process.wait.assert_called_once()

    def test_stop_event_cancels_inflight_authentication(self):
        stop = threading.Event()
        stop.set()
        self.assertEqual(backend.run_backend(self.config, "login", stop_event=stop).code, 130)
        self.kill.assert_called_once()

    def test_interrupt_cleans_up_children(self):
        self.process.communicate.side_effect = KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt):
            backend.run_backend(self.config, "login")
        self.kill.assert_called_once()

    def test_raw_status_arguments(self):
        backend.run_backend(self.config, "status", raw=True)
        self.assertIn("--raw", self.popen.call_args.args[0])


class CliTests(OfflineTestCase):
    def setUp(self):
        super().setUp()
        self.path = self.tmp / "config.json"
        config.save_config(self.path, config.Config(username="u", password="p"))
        self.mock("ysu_manager.cli.config_path", return_value=self.path)
        self.unit = self.tmp / "ysu-net.service"
        self.unit.touch()
        self.mock("ysu_manager.cli.unit_path", return_value=self.unit)
        self.service = self.mock("ysu_manager.cli.service_action")
        self.runner = self.mock("ysu_manager.cli.run_backend", return_value=Result(0, "online\n"))
        self.mock("sys.stdin.isatty", return_value=False)

    def test_off_stops_reconnect_before_logout(self):
        calls = Mock()
        calls.attach_mock(self.service, "service")
        calls.attach_mock(self.runner, "backend")
        self.assertEqual(cli.main(["off"]), 0)
        self.assertEqual(calls.mock_calls[0], call.service("user", "stop"))
        self.assertEqual(self.runner.call_args.args[1], "logout")

    def test_stop_does_not_logout(self):
        self.assertEqual(cli.main(["stop"]), 0)
        self.runner.assert_not_called()

    def test_stop_without_service_does_not_claim_to_stop_foreground_daemon(self):
        self.unit.unlink()
        self.assertEqual(cli.main(["stop"]), 2)
        self.service.assert_not_called()

    def test_service_stop_failure_does_not_logout(self):
        self.service.side_effect = RuntimeError("permission denied")
        self.assertEqual(cli.main(["off"]), 2)
        self.runner.assert_not_called()

    def test_start_only_starts_daemon(self):
        self.assertEqual(cli.main(["on"]), 0)
        self.service.assert_called_once_with("user", "start")
        self.runner.assert_not_called()

    def test_missing_credentials_prevents_service_start(self):
        config.save_config(self.path, config.Config())
        self.assertEqual(cli.main(["on"]), 2)
        self.service.assert_not_called()

    def test_raw_output_and_exit_code_preserved(self):
        self.runner.return_value = Result(1, '{"is_online":false}\n')
        self.assertEqual(cli.main(["status", "--raw"]), 1)
        self.assertEqual(json.loads(self.output.getvalue()), {"is_online": False})

    def test_select_service_persists_without_connecting(self):
        self.assertEqual(cli.main(["service", "中国移动"]), 0)
        self.assertEqual(config.load_config(self.path, environ={}).service, "中国移动")
        self.runner.assert_not_called()

    def test_config_edit_and_validation(self):
        self.assertEqual(cli.main(["config", "set", "verify_tls", "false"]), 0)
        self.assertFalse(config.load_config(self.path, environ={}).verify_tls)
        self.assertEqual(cli.main(["config", "set", "retry_interval", "0"]), 2)
        self.assertEqual(config.load_config(self.path, environ={}).retry_interval, 30)

    def test_config_show_does_not_print_password(self):
        self.assertEqual(cli.main(["config", "show"]), 0)
        self.assertEqual(json.loads(self.output.getvalue())["password"], "已配置")

    def test_doctor_is_offline_by_default(self):
        self.mock("ysu_manager.cli.systemctl", return_value=Mock(stdout="inactive\n"))
        self.assertEqual(cli.main(["doctor"]), 0)
        self.runner.assert_not_called()

    def test_no_arguments_noninteractive_shows_help(self):
        self.assertEqual(cli.main([]), 0)
        self.assertIn("usage: ysu", self.output.getvalue())
        self.runner.assert_not_called()

    def test_custom_config_does_not_stop_default_service(self):
        self.assertEqual(cli.main(["--config", str(self.tmp / "other.json"), "off"]), 2)
        self.service.assert_not_called()
        self.runner.assert_not_called()

    def test_manual_login_cannot_race_daemon(self):
        from ysu_manager.locking import exclusive_config
        with exclusive_config(self.path):
            self.assertEqual(cli.main(["login"]), 2)
        self.runner.assert_not_called()


class InstallTests(OfflineTestCase):
    def setUp(self):
        super().setUp()
        self.root = self.tmp / "project with spaces $and%"
        (self.root / ".venv/bin").mkdir(parents=True)
        (self.root / ".venv/bin/python").touch()
        self.bin = self.tmp / "bin"
        self.unit = self.tmp / "systemd/ysu-net.service"
        self.config = self.tmp / "config/config.json"
        self.mock("ysu_manager.install.ROOT", new=self.root)
        self.mock("ysu_manager.install.bin_dir", return_value=self.bin)
        self.mock("ysu_manager.install.unit_path", return_value=self.unit)
        self.mock("ysu_manager.install.config_path", return_value=self.config)
        self.mock("ysu_manager.install.shutil.which", return_value="/usr/bin/systemctl")
        self.systemctl = self.mock("ysu_manager.install.systemctl")

    def test_install_is_idempotent_and_keeps_credentials(self):
        self.assertEqual(install.main([]), 0)
        config.save_config(self.config, config.Config(username="u", password="saved"))
        self.assertEqual(install.main([]), 0)
        self.assertEqual(config.load_config(self.config, environ={}).password, "saved")
        self.assertEqual(stat.S_IMODE((self.bin / "ysu").stat().st_mode), 0o755)
        self.assertTrue(all(c.args == ("user", "daemon-reload") for c in self.systemctl.call_args_list))

    def test_uninstall_preserves_config_and_source(self):
        install.main([])
        install.main(["--uninstall"])
        self.assertFalse(self.unit.exists())
        self.assertFalse((self.bin / "ysu").exists())
        self.assertTrue(self.config.exists())
        self.assertTrue(self.root.exists())
        self.assertIn(call("user", "disable", "--now", "ysu-net.service"), self.systemctl.call_args_list)

    def test_purge_removes_config(self):
        install.main([])
        install.main(["--uninstall", "--purge"])
        self.assertFalse(self.config.exists())

    def test_foreign_command_not_overwritten(self):
        self.bin.mkdir()
        (self.bin / "ysu").write_text("foreign command")
        with self.assertRaises(RuntimeError):
            install.main([])
        self.assertEqual((self.bin / "ysu").read_text(), "foreign command")
        self.assertFalse(self.config.exists())

    def test_no_service_mode_does_not_call_systemctl(self):
        install.main(["--no-service"])
        self.assertTrue((self.bin / "ysu").exists())
        self.assertFalse(self.unit.exists())
        self.systemctl.assert_not_called()

    def test_failed_service_stop_keeps_installation(self):
        install.main([])
        self.systemctl.side_effect = RuntimeError("systemd unavailable")
        with self.assertRaises(RuntimeError):
            install.main(["--uninstall"])
        self.assertTrue(self.unit.exists())
        self.assertTrue((self.bin / "ysu").exists())

    def test_rendered_unit_quotes_paths_and_does_not_embed_password(self):
        text = service.render_unit(self.root, self.config, "user")
        self.assertIn("WantedBy=default.target", text)
        self.assertIn("$$and%%", text)
        self.assertNotIn("WorkingDirectory=", text)
        self.assertIn("KillMode=control-group", text)
        self.assertNotIn("YSU_PASS", text)
        self.assertIn("WantedBy=multi-user.target", service.render_unit(self.root, self.config, "system"))

    def test_wrapper_executes_correct_interpreter_and_preserves_arguments(self):
        # Execute the real generated shell wrapper, with a local fake interpreter.
        interpreter = self.root / ".venv/bin/python"
        interpreter.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n')
        interpreter.chmod(0o755)
        install.main(["--no-service"])
        result = subprocess.run([str(self.bin / "ysu"), "service", "中国移动"], text=True, capture_output=True, check=True)
        self.assertEqual(result.stdout.splitlines(), [str(self.root / "ysu.py"), "--scope", "user", "service", "中国移动"])

    def test_uninstall_refuses_while_foreground_daemon_holds_lock(self):
        from ysu_manager.locking import exclusive_config
        install.main(["--no-service"])
        with exclusive_config(self.config), self.assertRaises(RuntimeError):
            install.main(["--uninstall"])
        self.assertTrue((self.bin / "ysu").exists())


class UnitValidationTests(OfflineTestCase):
    def test_systemd_accepts_generated_unit_with_special_path_characters(self):
        analyzer = shutil.which("systemd-analyze")
        if not analyzer:
            self.skipTest("systemd-analyze 不可用")
        root = self.tmp / 'project with $percent% and "quotes"'
        python = root / ".venv/bin/python"
        python.parent.mkdir(parents=True)
        python.write_text("#!/bin/sh\nexit 0\n")
        python.chmod(0o755)
        unit = self.tmp / "ysu-net.service"
        unit.write_text(service.render_unit(root, self.tmp / "config.json", "system"))
        result = subprocess.run([analyzer, "verify", str(unit)], text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
