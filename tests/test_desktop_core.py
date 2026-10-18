import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import patch

from helpers import OfflineTestCase
from ysu_net.desktop.app import _prepare_stdio, main
from ysu_net.desktop.core import DesktopCore, DesktopError, ERRORS, LOG_LIMIT, local_environment
from ysu_net.desktop.demo import DemoRunner, demo_config
from ysu_net.desktop.protocol import MAX_LINE_BYTES, ProtocolServer, ProtocolWriter, parse_request
from ysu_net.gui.engine import Status, parse_status
from ysu_net.gui.prefs import Prefs, load_prefs, prefs_path, save_prefs
from ysu_net.manager import backend
from ysu_net.manager.backend import Result
from ysu_net.manager.config import Config, SERVICES, load_config, save_config
from ysu_net.manager.locking import exclusive_config

ENVIRONMENT = {
    "version": "test", "python": "3.12", "platform": "test",
    "browser_available": False, "node_available": False,
    "browser_component_available": True,
}
ROOT = Path(__file__).resolve().parents[1]


def request(request_id, command, args=None):
    return json.dumps({"id": request_id, "command": command, "args": args or {}}, ensure_ascii=False) + "\n"


def wait_for(predicate, timeout=3):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        threading.Event().wait(0.005)
    raise AssertionError("desktop event did not arrive")


class CoreTests(OfflineTestCase):
    def setUp(self):
        super().setUp()
        self.path = self.tmp / "config.json"
        save_config(self.path, Config(username="mock-user", password="sensitive-test-password"))
        self.events = []
        self.core = self.make_core()

    def make_core(self, **kwargs):
        core = DesktopCore(self.path, lambda name, payload: self.events.append((name, payload)),
                           demo=True, environment_reader=lambda: dict(ENVIRONMENT), **kwargs)
        self.addCleanup(core.close)
        return core

    def test_snapshot_schema_is_exact_and_password_is_absent(self):
        snapshot = self.core.handle("snapshot", {})
        self.assertEqual(set(snapshot), {"sequence", "config", "prefs", "status", "auto", "busy",
                                         "busy_message", "info", "logs", "environment"})
        self.assertEqual(set(snapshot["config"]), set(Config.__dataclass_fields__) - {"password"} | {"password_set"})
        self.assertEqual(set(snapshot["environment"]), set(ENVIRONMENT))
        self.assertTrue(snapshot["config"]["password_set"])
        self.assertIsNone(snapshot["status"])
        self.assertNotIn("sensitive-test-password", json.dumps(snapshot))
        snapshot["config"]["service"] = "changed"
        self.assertEqual(self.core.snapshot()["config"]["service"], "校园网")

    def test_secret_is_scrubbed_from_all_engine_output_and_old_passwords(self):
        secret = "sensitive-test-password"
        self.core._on_engine_event("busy", secret)
        self.core._on_engine_event("status", Status(True, "校园网", secret, secret, secret))
        self.core._on_engine_event("info", {"online": True, "fields": [("账户", secret)], "items": [(secret, secret)]})
        self.core._on_engine_event("result", {"ok": False, "message": secret})
        self.core._on_engine_event("error", "raw server exception " + secret)
        self.core.handle("save_config", {"password": "new-secret-value"})
        self.core._on_engine_event("result", {"ok": True, "message": secret + "new-secret-value"})
        output = json.dumps(self.events) + json.dumps(self.core.snapshot())
        self.assertNotIn(secret, output)
        self.assertNotIn("new-secret-value", output)
        self.assertNotIn("raw server exception", output)

    def test_sequence_changes_only_for_actual_mutation_and_logs_are_bounded(self):
        self.core._on_engine_event("busy", "working")
        sequence = self.core.snapshot()["sequence"]
        self.core._on_engine_event("busy", "working")
        self.core.handle("snapshot", {})
        self.assertEqual(self.core.snapshot()["sequence"], sequence)
        for index in range(LOG_LIMIT + 20):
            self.core._on_engine_event("result", {"ok": True, "message": str(index)})
        logs = self.core.snapshot()["logs"]
        self.assertEqual(len(logs), LOG_LIMIT)
        self.assertEqual(logs[0]["message"], "20")
        self.assertTrue(all(item["level"] == "success" for item in logs))
        sequences = [payload["sequence"] for name, payload in self.events if name == "snapshot"]
        self.assertEqual(sequences, sorted(set(sequences)))

    def test_save_config_blank_password_preserves_and_merges_fields(self):
        self.core.handle("save_config", {"username": "new-user", "password": "", "check_interval": 17})
        self.core.handle("save_config", {"service": "中国移动"})
        config = load_config(self.path, environ={})
        self.assertEqual((config.username, config.password, config.service, config.check_interval),
                         ("new-user", "sensitive-test-password", "中国移动", 17))
        self.assertEqual(self.core.snapshot()["config"]["username"], "new-user")

    def test_invalid_config_is_atomic_and_error_is_fixed(self):
        before = self.path.read_bytes()
        for args in ({"password_set": False}, {"check_interval": True}, {"service": "bad"},
                     {"base": "http://bad"}, {"retry_interval": 1000}, {"password": None}):
            with self.subTest(args=args), self.assertRaises(DesktopError) as caught:
                self.core.handle("save_config", args)
            self.assertIn(str(caught.exception), ERRORS.values())
            self.assertEqual(self.path.read_bytes(), before)

    def test_config_save_uses_shared_write_lock_without_daemon_lock(self):
        with exclusive_config(self.path):
            self.core.handle("save_config", {"retry_interval": 33})
        self.assertTrue(self.path.with_name("config.json.write.lock").exists())
        self.assertEqual(load_config(self.path, environ={}).retry_interval, 33)

    def test_parallel_config_writers_preserve_unrelated_fields(self):
        other = self.make_core()
        barrier = threading.Barrier(3)
        failures = []

        def write(core, args):
            try:
                barrier.wait()
                core.handle("save_config", args)
            except Exception as exc:
                failures.append(exc)
        workers = [threading.Thread(target=write, args=(self.core, {"username": "concurrent"})),
                   threading.Thread(target=write, args=(other, {"service": "中国电信"}))]
        for worker in workers:
            worker.start()
        barrier.wait()
        for worker in workers:
            worker.join(2)
            self.assertFalse(worker.is_alive())
        self.assertEqual(failures, [])
        config = load_config(self.path, environ={})
        self.assertEqual((config.username, config.service, config.password),
                         ("concurrent", "中国电信", "sensitive-test-password"))

    def test_preferences_are_strict_and_preserve_reconnect(self):
        self.core._auto_desired = True
        self.core._on_engine_event("auto", {"state": "on", "message": "enabled"})
        self.core.handle("save_prefs", {"theme": "dark"})
        self.core.handle("save_prefs", {"close_to_tray": False})
        prefs = load_prefs(self.core.prefs_file)
        self.assertEqual(prefs, Prefs(theme="dark", close_to_tray=False, auto_reconnect=True))
        for args in ({"theme": "neon"}, {"close_to_tray": 1}, {"auto_reconnect": False}, {"autostart": True}):
            with self.subTest(args=args), self.assertRaises(DesktopError):
                self.core.handle("save_prefs", args)

    def test_preference_write_failure_does_not_mutate_snapshot(self):
        before = self.core.snapshot()
        with patch("ysu_net.desktop.core.save_prefs", side_effect=OSError("sensitive-test-password")):
            with self.assertRaises(DesktopError) as caught:
                self.core.handle("save_prefs", {"theme": "dark"})
        self.assertEqual(caught.exception.code, "save_failed")
        self.assertEqual(self.core.snapshot(), before)

    def test_disable_and_logout_persist_before_queued_engine_work(self):
        for action in ({"name": "set_auto", "value": False}, {"name": "logout"}):
            with self.subTest(action=action):
                self.core._auto_desired = True
                self.core._on_engine_event("auto", {"state": "on", "message": "enabled"})
                self.assertTrue(load_prefs(self.core.prefs_file).auto_reconnect)
                self.core.handle("action", action)
                self.assertFalse(load_prefs(self.core.prefs_file).auto_reconnect)
                self.core._on_engine_event("auto", {"state": "on", "message": "old queued confirmation"})
                self.assertFalse(load_prefs(self.core.prefs_file).auto_reconnect)

    def test_enable_is_saved_only_after_engine_confirms(self):
        self.core.handle("action", {"name": "set_auto", "value": True})
        self.assertFalse(load_prefs(self.core.prefs_file).auto_reconnect)
        self.core.engine._do_set_auto(True)
        self.assertTrue(load_prefs(self.core.prefs_file).auto_reconnect)
        self.assertEqual(self.core.snapshot()["auto"]["state"], "on")

    def test_enable_conflict_and_missing_credentials_do_not_persist_true(self):
        self.core.handle("action", {"name": "set_auto", "value": True})
        with exclusive_config(self.path):
            self.core.engine._do_set_auto(True)
        self.assertEqual(self.core.snapshot()["auto"]["state"], "external")
        self.assertFalse(load_prefs(self.core.prefs_file).auto_reconnect)
        save_config(self.path, Config())
        with self.assertRaises(ValueError):
            self.core.engine._do_set_auto(True)
        self.assertFalse(load_prefs(self.core.prefs_file).auto_reconnect)

    def test_logout_still_queues_when_preference_save_fails(self):
        with patch("ysu_net.desktop.core.save_prefs", side_effect=OSError):
            with self.assertRaises(DesktopError):
                self.core.handle("action", {"name": "logout"})
        self.assertEqual(self.core.engine.tasks.get_nowait(), ("logout", ()))
        self.assertFalse(self.core._auto_desired)

    def test_unknown_status_remains_unknown_and_info_does_not_replace_status(self):
        self.core._on_engine_event("status", Status(None, message="unknown"))
        self.core._on_engine_event("info", {"online": False, "fields": [], "items": []})
        self.assertIsNone(self.core.snapshot()["status"]["online"])
        self.core._on_engine_event("status", Status(True, "校园网"))
        self.core._on_engine_event("info", {"online": False, "fields": [], "items": []})
        self.assertTrue(self.core.snapshot()["status"]["online"])

    def test_engine_auto_does_not_authenticate_unknown_status(self):
        calls = []

        def runner(config, action, **kwargs):
            calls.append(action)
            return Result(2, reason="dns")
        core = self.make_core(runner=runner)
        core.handle("action", {"name": "set_auto", "value": True})
        core.engine._do_set_auto(True)
        core.engine._do_tick()
        self.assertEqual(calls, ["status"])
        self.assertIsNone(core.snapshot()["status"]["online"])

    def test_action_whitelist_and_argument_types(self):
        invalid = ({"name": "_release"}, {"name": "set_auto", "value": 1},
                   {"name": "switch", "value": []}, {"name": "set_service", "value": "bad"},
                   {"name": "login", "value": False}, {"name": "status", "raw": True}, {})
        for args in invalid:
            with self.subTest(args=args), self.assertRaises(DesktopError):
                self.core.handle("action", args)
        self.assertTrue(self.core.engine.tasks.empty())

    def test_diagnostics_are_local_and_do_not_submit_engine_tasks(self):
        with patch("ysu_net.gui.prefs.set_autostart", side_effect=AssertionError("no autostart")), \
                patch("ysu_net.manager.service.subprocess.run", side_effect=AssertionError("no service")):
            snapshot = self.core.handle("diagnostics", {})
        self.assertEqual(snapshot["environment"], ENVIRONMENT)
        self.assertTrue(self.core.engine.tasks.empty())
        with patch("ysu_net.desktop.core.node_runtime.find_node", return_value=None), \
                patch("ysu_net.desktop.core.find_system_browser", return_value=None):
            environment = local_environment()
        self.assertFalse(environment["node_available"])
        self.assertFalse(environment["browser_available"])

    def test_demo_full_thread_flow_all_services_and_account(self):
        self.core.start()
        wait_for(lambda: self.core.snapshot()["status"] is not None)
        self.assertFalse(self.core.snapshot()["status"]["online"])
        self.core.handle("action", {"name": "login"})
        wait_for(lambda: self.core.snapshot()["status"]["online"] is True)
        for service in SERVICES:
            self.core.handle("action", {"name": "switch", "value": service})
            wait_for(lambda: self.core.snapshot()["config"]["service"] == service
                     and self.core.snapshot()["status"]["service"] == service)
        self.core.handle("action", {"name": "info"})
        wait_for(lambda: self.core.snapshot()["info"] is not None and self.core.snapshot()["info"]["online"])
        self.assertIn(["剩余流量", "8.5 GB"], self.core.snapshot()["info"]["items"])
        self.core.handle("action", {"name": "logout"})
        wait_for(lambda: self.core.snapshot()["status"]["online"] is False)
        self.assertEqual(self.core.snapshot()["info"], {"online": False, "fields": [], "items": []})

    def test_demo_ignores_real_environment_credentials(self):
        with patch.dict(os.environ, {"YSU_USER": "real-env-user", "YSU_PASS": "real-env-password",
                                     "YSU_SERVICE": "中国电信"}):
            core = self.make_core()
            core.engine._do_login()
        snapshot = core.snapshot()
        self.assertEqual(snapshot["status"]["user"], "mock-user")
        self.assertEqual(snapshot["status"]["service"], "校园网")
        self.assertNotIn("real-env", json.dumps(snapshot))

    def test_real_runner_exceptions_are_fixed_and_do_not_crash_engine(self):
        def runner(*args, **kwargs):
            raise RuntimeError("sensitive-test-password raw server message")
        core = self.make_core(runner=runner)
        core.start()
        wait_for(lambda: core.snapshot()["status"] is not None)
        self.assertIsNone(core.snapshot()["status"]["online"])
        self.assertTrue(core.engine.thread.is_alive())
        self.assertNotIn("raw server message", json.dumps(self.events))

    def test_demo_browser_install_is_independent_cancellable_and_no_network(self):
        self.assertEqual(self.core.handle("browser_install", {}), {"state": "started"})
        self.assertTrue(self.core.snapshot()["busy"])
        self.assertIsInstance(self.core.handle("snapshot", {}), dict)
        with self.assertRaises(DesktopError) as caught:
            self.core.handle("browser_install", {})
        self.assertEqual(caught.exception.code, "download_busy")
        wait_for(lambda: any(name == "browser_install" and payload["state"] == "progress"
                             for name, payload in self.events))
        self.assertEqual(self.core.handle("browser_install", {"cancel": True}), {"state": "cancelling"})
        self.core._download_thread.join(2)
        self.assertFalse(self.core._download_thread.is_alive())
        self.assertFalse(self.core.snapshot()["busy"])
        self.assertTrue(any(name == "browser_install" and payload["state"] == "cancelled"
                            for name, payload in self.events))

    def test_demo_browser_install_completes_without_calling_real_installer(self):
        core = self.make_core(installer=lambda **kwargs: self.fail("demo attempted download"))
        core.handle("browser_install", {})
        core._download_thread.join(2)
        self.assertTrue(core.snapshot()["environment"]["node_available"])
        self.assertTrue(core.handle("diagnostics", {})["environment"]["node_available"])

    def test_real_browser_install_progress_and_errors_are_sanitized(self):
        def install(progress, cancel):
            progress(5, 10)
            raise RuntimeError("sensitive-test-password download URL")
        core = DesktopCore(self.path, lambda name, payload: self.events.append((name, payload)),
                           installer=install, environment_reader=lambda: dict(ENVIRONMENT))
        self.addCleanup(core.close)
        with patch("ysu_net.desktop.core.node_runtime.supported", return_value=True):
            core.handle("browser_install", {})
        core._download_thread.join(2)
        self.assertFalse(core.snapshot()["busy"])
        self.assertIn("failed", [payload["state"] for name, payload in self.events if name == "browser_install"])
        self.assertNotIn("download URL", json.dumps(self.events))

    def test_close_cancels_engine_releases_profile_and_is_idempotent(self):
        self.core.handle("action", {"name": "set_auto", "value": True})
        self.core.start()
        wait_for(lambda: self.core.engine.auto)
        self.core.close()
        self.core.close()
        self.assertFalse(self.core.engine.thread.is_alive())
        self.assertTrue(self.core.engine.cancel.is_set())
        with exclusive_config(self.path):
            pass
        with self.assertRaises(DesktopError):
            self.core.handle("snapshot", {})

    def test_start_restores_reconnect_and_exit_preserves_enabled_preference(self):
        save_prefs(self.core.prefs_file, Prefs(theme="dark", auto_reconnect=True))
        core = self.make_core()
        core.start()
        wait_for(lambda: core.snapshot()["auto"]["state"] == "on"
                 and core.snapshot()["status"] is not None and core.snapshot()["status"]["online"] is True)
        core.close()
        self.assertEqual(load_prefs(core.prefs_file), Prefs(theme="dark", auto_reconnect=True))

    def test_shutdown_discards_backlog_without_starting_another_auth_operation(self):
        entered = threading.Event()
        calls = []

        def runner(config, action, stop_event=None, **kwargs):
            calls.append(action)
            entered.set()
            stop_event.wait(3)
            return Result(130)
        core = self.make_core(runner=runner)
        core.start()
        self.assertTrue(entered.wait(1))
        for _ in range(500):
            core.handle("action", {"name": "status"})
        core.close()
        self.assertEqual(calls, ["status"])
        self.assertFalse(core.engine.thread.is_alive())
        self.assertTrue(core.engine.tasks.empty())

    def test_shutdown_cancels_download_without_publishing_after_close(self):
        entered = threading.Event()
        cancelled = threading.Event()

        def installer(progress, cancel):
            entered.set()
            if cancel.wait(2):
                cancelled.set()
            raise InterruptedError
        core = DesktopCore(self.path, lambda name, payload: self.events.append((name, payload)),
                           installer=installer, environment_reader=lambda: dict(ENVIRONMENT))
        self.addCleanup(core.close)
        with patch("ysu_net.desktop.core.node_runtime.supported", return_value=True):
            core.handle("browser_install", {})
        self.assertTrue(entered.wait(1))
        count = len(self.events)
        core.close()
        self.assertTrue(cancelled.is_set())
        self.assertFalse(core._download_thread.is_alive())
        self.assertEqual(len(self.events), count)


class ProtocolTests(OfflineTestCase):
    def setUp(self):
        super().setUp()
        self.path = self.tmp / "config.json"
        save_config(self.path, demo_config())

    def serve(self, lines, **kwargs):
        output = io.StringIO()
        core = DesktopCore(self.path, demo=True, environment_reader=lambda: dict(ENVIRONMENT), **kwargs)
        server = ProtocolServer(core, io.StringIO(lines), ProtocolWriter(output))
        self.assertEqual(server.run(), 0)
        self.assertFalse(core.engine.thread.is_alive())
        messages = [json.loads(line) for line in output.getvalue().splitlines()]
        responses = [item for item in messages if item["kind"] == "response"]
        return responses, messages, core

    def test_responses_correlate_ids_and_snapshot_events_are_valid(self):
        responses, messages, _ = self.serve(request(1, "snapshot") + request(2, "save_prefs", {"theme": "dark"})
                                            + request(3, "shutdown") + request(4, "snapshot"))
        self.assertEqual([item["id"] for item in responses], [1, 2, 3])
        self.assertTrue(all(item["ok"] for item in responses))
        self.assertEqual(responses[1]["data"]["prefs"]["theme"], "dark")
        self.assertEqual(responses[2]["data"], {"shutdown": True})
        events = [item for item in messages if item["kind"] == "event"]
        self.assertTrue(events)
        self.assertTrue(all(item["name"] == "snapshot" for item in events))
        self.assertNotIn("demo-password", json.dumps(messages))

    def test_invalid_json_duplicate_keys_and_nonfinite_values_are_fixed(self):
        malformed = ["not json", "[]", '{"id":true,"command":"snapshot","args":{}}',
                     '{"id":1,"id":2,"command":"snapshot","args":{}}',
                     '{"id":1,"command":"snapshot","args":{"x":NaN}}',
                     "[" * 2000 + "]" * 2000]
        responses, _, _ = self.serve("\n".join(malformed) + "\n" + request(7, "snapshot"))
        self.assertEqual(len(responses), 7)
        self.assertTrue(responses[-1]["ok"])
        for response in responses[:-1]:
            self.assertEqual(response, {"kind": "response", "id": None, "ok": False,
                                        "error": ERRORS["invalid_request"]})

    def test_invalid_shape_command_and_args_keep_valid_request_id(self):
        lines = ('{"id":1,"command":"snapshot"}\n'
                 '{"id":2,"command":"eval","args":{}}\n'
                 '{"id":3,"command":"action","args":[]}\n'
                 '{"id":4,"command":"action","args":{"name":"quit"}}\n')
        responses, _, _ = self.serve(lines)
        self.assertEqual([item["id"] for item in responses], [1, 2, 3, 4])
        self.assertTrue(all(not item["ok"] and item["error"] in ERRORS.values() for item in responses))

    def test_oversized_utf8_lines_are_drained_then_next_request_runs(self):
        oversized = "中" * (MAX_LINE_BYTES // 3 + 10) + "\n"
        responses, _, _ = self.serve(oversized + request(2, "snapshot"))
        self.assertEqual(responses[0]["error"], ERRORS["line_too_long"])
        self.assertTrue(responses[1]["ok"])
        self.assertEqual(responses[1]["id"], 2)

    def test_final_request_without_newline_is_processed_before_eof(self):
        responses, _, _ = self.serve(request(99, "snapshot").rstrip("\n"))
        self.assertEqual(responses[0]["id"], 99)
        self.assertTrue(responses[0]["ok"])

    def test_binary_utf8_input_rejects_bad_bytes(self):
        with self.assertRaises(DesktopError):
            parse_request(b"\xff\n")
        self.assertEqual(parse_request(request(4, "snapshot").encode()), (4, "snapshot", {}))

    def test_protocol_writer_serializes_concurrent_threads(self):
        class SplitStream(io.StringIO):
            def write(self, text):
                midpoint = len(text) // 2
                super().write(text[:midpoint])
                threading.Event().wait(0.0001)
                return midpoint + super().write(text[midpoint:])
        output = SplitStream()
        writer = ProtocolWriter(output)
        threads = [threading.Thread(target=lambda number=n: [writer.response(number, data={"x": index})
                                                            for index in range(20)]) for n in range(5)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(3)
            self.assertFalse(thread.is_alive())
        messages = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(len(messages), 100)

    def test_broken_stdout_stops_without_raw_traceback(self):
        class BrokenStream:
            def write(self, text):
                raise BrokenPipeError
        core = DesktopCore(self.path, demo=True, environment_reader=lambda: dict(ENVIRONMENT))
        writer = ProtocolWriter(BrokenStream())
        server = ProtocolServer(core, io.StringIO(request(1, "snapshot")), writer)
        self.assertEqual(server.run(), 0)
        self.assertTrue(writer.failed.is_set())
        self.assertFalse(core.engine.thread.is_alive())

    def test_eof_cancels_active_operation_and_engine(self):
        entered = threading.Event()
        cancelled = threading.Event()

        def runner(config, action, stop_event=None, **kwargs):
            entered.set()
            if stop_event.wait(2):
                cancelled.set()
            return Result(130)

        class EofAfterStarted:
            def readline(self, limit):
                if not entered.wait(2):
                    raise AssertionError("worker did not start")
                return b""
        core = DesktopCore(self.path, demo=True, runner=runner, environment_reader=lambda: dict(ENVIRONMENT))
        server = ProtocolServer(core, EofAfterStarted(), ProtocolWriter(io.StringIO()))
        self.assertEqual(server.run(), 0)
        self.assertTrue(cancelled.is_set())
        self.assertFalse(core.engine.thread.is_alive())

    @unittest.skipIf(os.name == "nt", "POSIX process-group cleanup")
    def test_eof_terminates_real_auth_child_process_group(self):
        spawned = threading.Event()
        processes = []
        failures = []
        actual_popen = subprocess.Popen

        def clean_child(process):
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=2)
            process.communicate(timeout=1)

        def popen(*args, **kwargs):
            process = actual_popen(*args, **kwargs)
            processes.append(process)
            self.addCleanup(clean_child, process)
            spawned.set()
            return process

        def runner(*args, **kwargs):
            try:
                return backend.run_backend(*args, **kwargs)
            except Exception as exc:
                failures.append(type(exc).__name__)
                raise

        class EofAfterSpawn:
            def readline(self, limit):
                if not spawned.wait(2):
                    raise AssertionError("auth child did not spawn")
                return b""
        core = DesktopCore(self.path, runner=runner, environment_reader=lambda: dict(ENVIRONMENT))
        command = [sys.executable, "-c", "import time; time.sleep(60)"]
        server = ProtocolServer(core, EofAfterSpawn(), ProtocolWriter(io.StringIO()))
        with patch.object(backend, "auth_command", return_value=command), \
                patch.object(backend.subprocess, "Popen", side_effect=popen):
            self.assertEqual(server.run(), 0)
        self.assertEqual(failures, [])
        self.assertEqual(len(processes), 1)
        self.assertIsNotNone(processes[0].poll(), "auth child survived EOF cancellation")


class EntryTests(OfflineTestCase):
    def test_worker_dispatch_precedes_desktop_argument_parser(self):
        with patch("ysu_net.auth.worker.run", return_value=37) as run, \
                patch("ysu_net.desktop.app._Parser", side_effect=AssertionError("parser reached")):
            self.assertEqual(main(["--ysu-auth", "api", "--help"]), 37)
        run.assert_called_once_with(["api", "--help"])

    def test_windowed_frozen_stdio_is_restored_from_inherited_descriptors(self):
        streams = {0: io.StringIO(), 1: io.StringIO(), 2: io.StringIO()}
        with patch.object(sys, "stdin", None), patch.object(sys, "stdout", None), \
                patch.object(sys, "stderr", None), patch("builtins.open", side_effect=lambda fd, *a, **k: streams[fd]) as opened:
            _prepare_stdio()
            self.assertIs(sys.stdin, streams[0])
            self.assertIs(sys.stdout, streams[1])
            self.assertIs(sys.stderr, streams[2])
        self.assertEqual([call.args[0] for call in opened.call_args_list], [0, 1, 2])
        self.assertTrue(all(call.kwargs["closefd"] is False for call in opened.call_args_list))

    def child_env(self):
        return dict(os.environ, PYTHONPATH=str(ROOT / "src"), XDG_CONFIG_HOME=str(self.tmp / "real-config"),
                    YSU_USER="real-user", YSU_PASS="real-password", YSU_SERVICE="中国电信")

    def test_module_demo_without_path_is_isolated_and_password_free(self):
        config_root = self.tmp / "real-config" / "ysu-net"
        config_root.mkdir(parents=True)
        config = config_root / "config.json"
        save_config(config, Config(username="real-file-user", password="real-file-password"))
        before = config.read_bytes()
        result = subprocess.run([sys.executable, "-m", "ysu_net.desktop", "--demo"],
                                input=request(1, "snapshot") + request(2, "shutdown"), capture_output=True,
                                text=True, encoding="utf-8", env=self.child_env(), cwd=self.tmp, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        messages = [json.loads(line) for line in result.stdout.splitlines()]
        response = next(item for item in messages if item.get("id") == 1)
        self.assertEqual(response["data"]["config"]["username"], "demo-user")
        self.assertEqual(response["data"]["config"]["service"], "校园网")
        for secret in ("demo-password", "real-password", "real-file-password", "real-file-user"):
            self.assertNotIn(secret, result.stdout + result.stderr)
        self.assertEqual(config.read_bytes(), before)
        self.assertEqual(sorted(path.name for path in config_root.iterdir()), ["config.json"])

    def test_explicit_demo_path_never_reads_or_modifies_real_profile(self):
        path = self.tmp / "operator-profile.json"
        save_config(path, Config(username="operator-real-user", password="operator-real-secret"))
        before = path.read_bytes()
        commands = (request(1, "snapshot") + request(2, "save_config", {"username": "demo-change"})
                    + request(3, "save_prefs", {"theme": "dark"}) + request(4, "shutdown"))
        result = subprocess.run([sys.executable, "-m", "ysu_net.desktop", "--demo", "--config", str(path)],
                                input=commands, capture_output=True, text=True, encoding="utf-8",
                                env=self.child_env(), cwd=self.tmp, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse(prefs_path(path).exists())
        self.assertNotIn("operator-real", result.stdout + result.stderr)
        frames = [json.loads(line) for line in result.stdout.splitlines()]
        snapshot = next(frame["data"] for frame in frames if frame.get("id") == 1)
        self.assertEqual(snapshot["config"]["username"], "demo-user")

    def test_qt_imports_and_network_are_blocked_in_fresh_demo_process(self):
        code = """
import importlib.abc
import socket
import sys
class NoQt(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(('PySide', 'PyQt', 'ysu_net.gui.window', 'ysu_net.gui.app')):
            raise AssertionError('Qt dependency imported')
sys.meta_path.insert(0, NoQt())
def blocked(*args, **kwargs):
    raise AssertionError('network attempted')
socket.socket.connect = blocked
socket.create_connection = blocked
socket.getaddrinfo = blocked
from ysu_net.desktop.app import main
raise SystemExit(main(['--demo']))
"""
        result = subprocess.run([sys.executable, "-c", code], input=request(1, "snapshot") + request(2, "shutdown"),
                                capture_output=True, text=True, encoding="utf-8", env=self.child_env(),
                                cwd=self.tmp, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(all(json.loads(line)["kind"] in ("response", "event") for line in result.stdout.splitlines()))

    @unittest.skipIf(os.name == "nt", "POSIX SIGTERM")
    def test_sigterm_exits_while_stdin_stays_open(self):
        process = subprocess.Popen([sys.executable, "-m", "ysu_net.desktop", "--demo"], stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
                                   env=self.child_env(), cwd=self.tmp)
        self.addCleanup(lambda: process.kill() if process.poll() is None else None)
        first = process.stdout.readline()
        self.assertEqual(json.loads(first)["kind"], "event")
        process.send_signal(signal.SIGTERM)
        output, error = process.communicate(timeout=5)
        self.assertEqual(process.returncode, 0, error)
        self.assertTrue(all(json.loads(line)["kind"] == "event" for line in output.splitlines()))

    def test_invalid_config_exits_with_fixed_stderr_and_empty_stdout(self):
        path = self.tmp / "broken.json"
        path.write_text("raw-secret invalid json", encoding="utf-8")
        result = subprocess.run([sys.executable, "-m", "ysu_net.desktop", "--config", str(path)],
                                capture_output=True, text=True, encoding="utf-8", env=self.child_env(), timeout=10)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr.strip(), ERRORS["config_invalid"])

    def test_help_is_written_to_stderr_only(self):
        result = subprocess.run([sys.executable, "-m", "ysu_net.desktop", "--help"], capture_output=True,
                                text=True, encoding="utf-8", env=self.child_env(), timeout=5)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertIn("--demo", result.stderr)


class DemoRunnerTests(OfflineTestCase):
    def test_portal_response_semantics_and_cancellation(self):
        runner = DemoRunner()
        config = demo_config()
        self.assertIs(parse_status(runner(config, "status", raw=True)).online, False)
        for service in SERVICES:
            config.service = service
            self.assertEqual(runner(config, "login").code, 0)
            state = parse_status(runner(config, "status", raw=True))
            self.assertEqual((state.online, state.service, state.user), (True, service, "demo-user"))
            self.assertEqual(runner(config, "logout").code, 0)
            self.assertIs(parse_status(runner(config, "status", raw=True)).online, False)
        stop = threading.Event()
        stop.set()
        self.assertEqual(runner(config, "login", stop_event=stop).code, 130)
        self.assertFalse(runner.online)


if __name__ == "__main__":
    unittest.main()
