import json
import os
import stat
import threading
import time
from unittest.mock import Mock, patch

from tests.helpers import OfflineTestCase
from ysu_net.manager import control
from ysu_net.manager.control import ControlServer, request_control
from ysu_net.manager.locking import exclusive_config


ACCOUNT_ID = "a" * 32


class ControlTests(OfflineTestCase):
    def setUp(self):
        super().setUp()
        self.path = self.tmp / "config.json"
        self.handler = Mock(return_value={"code": 0, "message": "verified", "detail": {"ready": True}})
        self.server = ControlServer(self.path, self.handler).start()
        self.addCleanup(self.server.close)
        self.directory = self.path.with_suffix(".control")
        self.counter = 0

    def put(self, directory, nonce, value):
        path = self.directory / directory / (nonce + ".json")
        raw = value if isinstance(value, bytes) else json.dumps(value).encode()
        with path.open("wb") as stream:
            stream.write(raw)
        path.chmod(0o600)
        return path

    def enqueue(self, *, nonce=None, **overrides):
        self.counter += 1
        nonce = nonce or f"{self.counter:032x}"
        now = time.time()
        value = {"version": 1, "nonce": nonce, "owner": self.server.owner,
                 "action": "switch_account", "payload": {"id": ACCOUNT_ID},
                 "created_at": now, "expires_at": now + 30}
        value.update(overrides)
        return self.put("inbox", nonce, value), value

    def request_thread(self, action="switch_account", payload=None, **kwargs):
        result = []
        errors = []

        def run():
            try:
                result.append(request_control(self.path, action, payload if payload is not None else {"id": ACCOUNT_ID}, **kwargs))
            except BaseException as exc:
                errors.append(exc)

        thread = threading.Thread(target=run)
        thread.start()
        self.addCleanup(thread.join, 2)
        return thread, result, errors

    def wait_for(self, predicate, timeout=1):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return
            threading.Event().wait(0.002)
        self.fail("Timed out waiting for offline fixture")

    def consume_one(self):
        self.wait_for(lambda: self.server.consume() == 1)

    def finish(self, thread, results, errors):
        thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(len(results), 1)
        return results[0]

    def assert_unknown(self, value):
        self.assertEqual(value["code"], 2)
        self.assertIn("\u672a\u786e\u8ba4", value["message"])
        self.assertNotIn("\u5df2\u53d6\u6d88", value["message"])

    def test_private_paths_permissions_and_owner_nonce(self):
        self.assertEqual(self.server.path, self.path.with_suffix(".control"))
        owner = json.loads((self.directory / "owner.json").read_text())
        self.assertEqual(owner, {"version": 1, "nonce": self.server.owner})
        self.assertRegex(owner["nonce"], r"^[0-9a-f]{32}$")
        if os.name != "nt":
            for name in ("", "inbox", "ack"):
                self.assertEqual(stat.S_IMODE((self.directory / name).stat().st_mode), 0o700)
            for name in ("owner.json", "queue.lock"):
                self.assertEqual(stat.S_IMODE((self.directory / name).stat().st_mode), 0o600)

    def test_roundtrip_preserves_handler_result_and_total_deadline(self):
        thread, results, errors = self.request_thread(timeout=1)
        self.wait_for(lambda: len(list((self.directory / "inbox").glob("*.json"))) == 1)
        queued = json.loads(next((self.directory / "inbox").glob("*.json")).read_text())
        self.assertAlmostEqual(queued["expires_at"] - queued["created_at"], 1)
        self.consume_one()
        self.assertEqual(self.finish(thread, results, errors), self.handler.return_value)
        self.handler.assert_called_once_with("switch_account", {"id": ACCOUNT_ID}, queued["expires_at"])
        self.assertEqual(list((self.directory / "inbox").iterdir()), [])
        self.assertEqual(list((self.directory / "ack").iterdir()), [])

    def test_rotation_boolean_roundtrip(self):
        thread, results, errors = self.request_thread("rotation", {"enabled": False}, timeout=1)
        self.consume_one()
        self.assertEqual(self.finish(thread, results, errors)["code"], 0)
        self.assertEqual(self.handler.call_args.args[:2], ("rotation", {"enabled": False}))

    def test_handler_nonzero_result_remains_nonzero(self):
        self.handler.return_value = {"code": 4, "message": "interaction required"}
        thread, results, errors = self.request_thread(timeout=1)
        self.consume_one()
        self.assertEqual(self.finish(thread, results, errors), self.handler.return_value)

    def test_explicit_clock_and_monotonic_are_used(self):
        clock = Mock(return_value=100.0)
        self.server.clock = clock
        monotonic = Mock(side_effect=time.monotonic)
        thread, results, errors = self.request_thread(timeout=1, clock=clock, monotonic=monotonic)
        self.consume_one()
        self.assertEqual(self.finish(thread, results, errors)["code"], 0)
        self.assertEqual(self.handler.call_args.args[2], 101.0)
        self.assertGreater(monotonic.call_count, 2)

    def test_requested_timeout_is_clamped_to_finite_ttl(self):
        thread, results, errors = self.request_thread(timeout=86405)
        self.consume_one()
        self.assertEqual(self.finish(thread, results, errors)["code"], 0)
        deadline = self.handler.call_args.args[2]
        self.assertLessEqual(deadline - time.time(), control.MAX_TIMEOUT)
        self.assertGreater(deadline - time.time(), control.MAX_TIMEOUT - 2)

    def test_missing_channel_is_unconfirmed_and_does_not_create_files(self):
        path = self.tmp / "other.json"
        self.assert_unknown(request_control(path, "rotation", {"enabled": True}, timeout=0.02))
        self.assertFalse(path.with_suffix(".control").exists())

    def test_old_owner_without_channel_does_not_touch_run_lock(self):
        path = self.tmp / "old.json"
        with exclusive_config(path):
            lock = path.with_suffix(".lock")
            info = lock.stat()
            self.assert_unknown(request_control(path, "switch_account", {"id": ACCOUNT_ID}, timeout=0.02))
            self.assertEqual((lock.stat().st_dev, lock.stat().st_ino), (info.st_dev, info.st_ino))
        self.assertTrue(lock.exists())

    def test_close_is_idempotent_and_preserves_run_lock(self):
        with exclusive_config(self.path):
            lock = self.path.with_suffix(".lock")
            info = lock.stat()
            self.enqueue()
            self.server.close()
            self.server.close()
            self.assertFalse((self.directory / "owner.json").exists())
            self.assertEqual(list((self.directory / "inbox").iterdir()), [])
            self.assertEqual((lock.stat().st_dev, lock.stat().st_ino), (info.st_dev, info.st_ino))
            with self.assertRaises(RuntimeError):
                with exclusive_config(self.path):
                    self.fail("ControlServer released the run lock")
        self.assert_unknown(request_control(self.path, "rotation", {"enabled": True}, timeout=0.02))

    def test_single_consume_never_executes_multiple_requests(self):
        self.enqueue()
        self.enqueue()
        self.assertEqual(self.server.consume(limit=100), 1)
        self.assertEqual(self.handler.call_count, 1)
        self.assertEqual(len(list((self.directory / "inbox").iterdir())), 1)
        self.assertEqual(self.server.consume(limit=0), 0)
        self.assertEqual(self.server.consume(), 1)
        self.assertEqual(self.handler.call_count, 2)

    def test_invalid_limit_is_rejected(self):
        for limit in (-1, True, 1.2, "1"):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                self.server.consume(limit)

    def test_queued_timeout_withdraws_request_without_claiming_cancellation(self):
        self.assert_unknown(request_control(self.path, "rotation", {"enabled": True}, timeout=0.025))
        self.assertEqual(list((self.directory / "inbox").iterdir()), [])
        self.assertEqual(self.server.consume(), 0)
        self.handler.assert_not_called()

    def test_started_timeout_is_unconfirmed_and_handler_runs_only_once(self):
        started, release = threading.Event(), threading.Event()
        now = [100.0]
        self.server.clock = lambda: now[0]

        def handler(*_):
            started.set()
            release.wait()
            return {"code": 0, "message": "late success"}

        self.server.handler = handler
        # Freeze both deadlines until the owner has actually started the request.
        thread, results, errors = self.request_thread(timeout=0.06, clock=lambda: now[0], monotonic=lambda: now[0])
        consumer = threading.Thread(target=self.consume_one)
        consumer.start()
        self.addCleanup(consumer.join, 2)
        self.addCleanup(release.set)
        self.addCleanup(now.__setitem__, 0, 101.0)
        self.assertTrue(started.wait(1))
        now[0] = 101.0
        self.assert_unknown(self.finish(thread, results, errors))
        self.assertEqual(list((self.directory / "inbox").iterdir()), [])
        running = json.loads(next((self.directory / "ack").iterdir()).read_text())
        self.assertEqual(running["state"], "running")
        release.set()
        consumer.join(2)
        self.assertFalse(consumer.is_alive())
        done = json.loads(next((self.directory / "ack").iterdir()).read_text())
        self.assert_unknown(done["result"])
        self.assertEqual(self.server.consume(), 0)
    def test_monotonic_timeout_survives_wall_clock_going_backwards(self):
        now = [100.0]
        thread, results, errors = self.request_thread(timeout=0.04, clock=lambda: now[0])
        self.wait_for(lambda: bool(list((self.directory / "inbox").glob("*.json"))))
        now[0] = 99.0
        self.assert_unknown(self.finish(thread, results, errors))
        self.assertEqual(list((self.directory / "inbox").iterdir()), [])

    def test_invalid_client_actions_do_not_enqueue_or_call_handler(self):
        for action, payload in (("login", {}), ("logout", {}), ("stop", {}),
                                ("switch_account", {"id": "../outside"}),
                                ("switch_account", {"id": ACCOUNT_ID, "password": "private"}),
                                ("rotation", {"enabled": 1}), ("rotation", {}),
                                ("rotation", {"enabled": True, "extra": None}), ("rotation", [])):
            with self.subTest(action=action, payload=payload):
                self.assert_unknown(request_control(self.path, action, payload, timeout=0.01))
        self.assertEqual(list((self.directory / "inbox").iterdir()), [])
        self.handler.assert_not_called()

    def test_invalid_timeouts_are_unconfirmed(self):
        for timeout in (0, -1, True, "1", float("nan"), float("inf")):
            with self.subTest(timeout=timeout):
                self.assert_unknown(request_control(self.path, "rotation", {"enabled": True}, timeout=timeout))
        self.assertEqual(list((self.directory / "inbox").iterdir()), [])

    def test_malformed_protocol_envelopes_never_execute(self):
        for changes in ({"version": True}, {"version": 2}, {"nonce": "bad"},
                        {"owner": "f" * 32}, {"action": "login"}, {"payload": {"id": "bad"}},
                        {"payload": {"id": ACCOUNT_ID, "extra": 1}}, {"created_at": True},
                        {"created_at": float("nan")}, {"expires_at": float("inf")},
                        {"created_at": time.time() + 60}, {"expires_at": time.time() + 600},
                        {"extra": "unknown"}):
            with self.subTest(changes=changes):
                path, _ = self.enqueue(**changes)
                self.assertEqual(self.server.consume(), 1)
                self.assertFalse(path.exists())
        self.handler.assert_not_called()

    def test_broken_json_arrays_and_duplicate_fields_never_execute(self):
        for raw in (b"[1,2]", b"{", b"\xff", b'{"version":1,"version":1}', b'{}'):
            with self.subTest(raw=raw):
                path = self.put("inbox", "1" * 32, raw)
                self.assertEqual(self.server.consume(), 1)
                self.assertFalse(path.exists())
        self.handler.assert_not_called()

    def test_oversized_request_never_executes(self):
        path = self.put("inbox", "1" * 32, b"x" * (control.MAX_MESSAGE_BYTES + 1))
        self.assertEqual(self.server.consume(), 1)
        self.assertFalse(path.exists())
        self.handler.assert_not_called()

    def test_expired_request_never_executes(self):
        now = time.time()
        path, _ = self.enqueue(created_at=now - 2, expires_at=now - 1)
        self.assertEqual(self.server.consume(), 1)
        self.assertFalse(path.exists())
        self.handler.assert_not_called()

    def test_execution_result_after_expiry_is_never_success(self):
        now = [100.0]
        self.server.clock = lambda: now[0]

        def handler(*_):
            now[0] = 111.0
            return {"code": 0, "message": "expired success"}

        self.server.handler = handler
        path, _ = self.enqueue(created_at=100.0, expires_at=110.0)
        self.assertEqual(self.server.consume(), 1)
        result = json.loads((self.directory / "ack" / path.name).read_text())
        self.assert_unknown(result["result"])

    def test_repeated_nonce_keeps_existing_result_without_reexecuting(self):
        path, request = self.enqueue()
        self.assertEqual(self.server.consume(), 1)
        ack = self.directory / "ack" / path.name
        original = ack.read_bytes()
        self.put("inbox", request["nonce"], request)
        self.assertEqual(self.server.consume(), 1)
        self.assertEqual(ack.read_bytes(), original)
        self.handler.assert_called_once()

    def test_repeated_nonce_after_ack_removal_stays_unconfirmed(self):
        path, request = self.enqueue()
        self.assertEqual(self.server.consume(), 1)
        ack = self.directory / "ack" / path.name
        ack.unlink()
        self.put("inbox", request["nonce"], request)
        self.assertEqual(self.server.consume(), 1)
        self.assert_unknown(json.loads(ack.read_text())["result"])
        self.handler.assert_called_once()
        self.assertEqual(len(self.server._replay.bits), 64 * 1024)

    def test_nonce_collision_does_not_remove_someone_elses_queued_request(self):
        path, request = self.enqueue(nonce="b" * 32)
        original = path.read_bytes()
        with patch.object(control.secrets, "token_hex", return_value=request["nonce"]):
            self.assert_unknown(request_control(self.path, "rotation", {"enabled": True}, timeout=0.01))
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(self.server.consume(), 1)
        self.handler.assert_called_once()

    def test_atomic_exclusive_publish_preserves_existing_request(self):
        path, request = self.enqueue()
        original = path.read_bytes()
        with control._Directory(self.directory / "inbox") as directory:
            with self.assertRaises(FileExistsError):
                directory.write(path.name, {"replacement": True}, exclusive=True)
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual([item.name for item in path.parent.iterdir()], [path.name])

    def test_request_and_ack_files_are_private_without_temporary_artifacts(self):
        path, _ = self.enqueue()
        self.assertEqual(self.server.consume(), 1)
        ack = self.directory / "ack" / path.name
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(ack.stat().st_mode), 0o600)
        self.assertLessEqual(ack.stat().st_size, control.MAX_MESSAGE_BYTES)
        self.assertFalse(list(self.directory.glob("**/.tmp-*")))

    def test_full_queue_rejects_an_additional_request(self):
        for _ in range(control.MAX_REQUESTS):
            self.enqueue()
        self.assert_unknown(request_control(self.path, "rotation", {"enabled": True}, timeout=0.02))
        self.assertEqual(len(list((self.directory / "inbox").iterdir())), control.MAX_REQUESTS)
        self.handler.assert_not_called()

    def test_expired_ack_is_pruned_without_reopening_duplicate_execution(self):
        now = [100.0]
        self.server.clock = lambda: now[0]
        path, original = self.enqueue(created_at=100.0, expires_at=101.0)
        self.assertEqual(self.server.consume(), 1)
        now[0] = 102.0
        thread, results, errors = self.request_thread("rotation", {"enabled": True}, timeout=1, clock=lambda: now[0])
        self.consume_one()
        self.assertEqual(self.finish(thread, results, errors)["code"], 0)
        self.assertFalse((self.directory / "ack" / path.name).exists())
        original.update(created_at=102.0, expires_at=103.0)
        self.put("inbox", original["nonce"], original)
        self.assertEqual(self.server.consume(), 1)
        self.assert_unknown(json.loads((self.directory / "ack" / path.name).read_text())["result"])
        self.assertEqual(self.handler.call_count, 2)

    def test_concurrent_clients_are_bounded_and_clean_their_queues(self):
        gate = threading.Event()
        results, errors = [], []
        threads = []

        def run():
            gate.wait(1)
            try:
                results.append(request_control(self.path, "rotation", {"enabled": True}, timeout=0.3))
            except BaseException as exc:
                errors.append(exc)

        for _ in range(40):
            thread = threading.Thread(target=run)
            thread.start()
            threads.append(thread)
        gate.set()
        peak = 0
        while any(thread.is_alive() for thread in threads):
            peak = max(peak, len(list((self.directory / "inbox").glob("*.json"))))
            threading.Event().wait(0.002)
        for thread in threads:
            thread.join(1)
        self.assertEqual(errors, [])
        self.assertEqual(len(results), 40)
        self.assertGreater(peak, 0)
        self.assertLessEqual(peak, control.MAX_REQUESTS)
        self.assertTrue(all(item["code"] == 2 for item in results))
        self.assertEqual(list((self.directory / "inbox").iterdir()), [])
        self.assertEqual(list((self.directory / "ack").iterdir()), [])

    def test_queue_and_ack_capacity_are_shared(self):
        for _ in range(control.MAX_REQUESTS):
            self.enqueue()
            self.assertEqual(self.server.consume(), 1)
        self.assertEqual(len(list((self.directory / "ack").iterdir())), control.MAX_REQUESTS)
        self.assert_unknown(request_control(self.path, "rotation", {"enabled": False}, timeout=0.02))
        self.assertEqual(list((self.directory / "inbox").iterdir()), [])

    def test_owner_replacement_invalidates_old_client_and_old_server_close(self):
        thread, results, errors = self.request_thread(timeout=1)
        self.wait_for(lambda: bool(list((self.directory / "inbox").glob("*.json"))))
        newer = ControlServer(self.path, self.handler).start()
        self.addCleanup(newer.close)
        self.assert_unknown(self.finish(thread, results, errors))
        self.assertNotEqual(self.server.owner, newer.owner)
        self.assertEqual(self.server.consume(), 0)
        self.server.close()
        self.assertEqual(json.loads((self.directory / "owner.json").read_text())["nonce"], newer.owner)
        self.handler.assert_not_called()

    def test_restart_rejects_old_owner_request(self):
        _, old_request = self.enqueue()
        old_owner = self.server.owner
        self.server.close()
        self.server.start()
        self.assertNotEqual(self.server.owner, old_owner)
        path = self.put("inbox", old_request["nonce"], old_request)
        self.assertEqual(self.server.consume(), 1)
        self.assertFalse(path.exists())
        self.handler.assert_not_called()

    def test_stale_channel_with_no_consumer_times_out_unconfirmed(self):
        self.assert_unknown(request_control(self.path, "rotation", {"enabled": True}, timeout=0.02))
        self.assertEqual(list((self.directory / "inbox").iterdir()), [])

    def test_handler_exception_and_invalid_results_are_unconfirmed(self):
        for value in (None, {"code": True, "message": "bad"}, {"code": 0},
                      {"code": 0, "message": 1}, {"code": 0, "message": "x" * 17000},
                      {"code": 0, "message": "bad", "extra": object()},
                      {"code": 0, "message": "bad", "extra": float("nan")},
                      RuntimeError("private exception")):
            with self.subTest(value=value):
                self.handler.side_effect = value if isinstance(value, Exception) else None
                self.handler.return_value = value
                thread, results, errors = self.request_thread(timeout=1)
                self.consume_one()
                result = self.finish(thread, results, errors)
                self.assert_unknown(result)
                self.assertNotIn("private exception", result["message"])

    def test_valid_request_before_malformed_request_does_not_stall(self):
        self.enqueue(nonce="0" * 32)
        self.put("inbox", "f" * 32, b"{")
        self.assertEqual(self.server.consume(), 1)
        self.handler.assert_called_once()
        self.assertEqual(self.server.consume(), 1)
        self.handler.assert_called_once()

    def test_symlink_request_never_reads_or_changes_target(self):
        target = self.tmp / "outside.json"
        target.write_bytes(b"outside-content")
        path = self.directory / "inbox" / ("1" * 32 + ".json")
        path.symlink_to(target)
        self.assertEqual(self.server.consume(), 1)
        self.assertFalse(path.is_symlink())
        self.assertEqual(target.read_bytes(), b"outside-content")
        self.handler.assert_not_called()

    def test_symlink_owner_is_unconfirmed_without_touching_target(self):
        owner = self.directory / "owner.json"
        raw = owner.read_bytes()
        target = self.tmp / "outside-owner.json"
        target.write_bytes(raw)
        owner.unlink()
        owner.symlink_to(target)
        self.assert_unknown(request_control(self.path, "rotation", {"enabled": True}, timeout=0.02))
        self.assertEqual(target.read_bytes(), raw)
        self.handler.assert_not_called()

    def test_symlink_queue_lock_is_unconfirmed_without_touching_target(self):
        lock = self.directory / "queue.lock"
        target = self.tmp / "outside-lock"
        target.write_bytes(b"do-not-touch")
        lock.unlink()
        lock.symlink_to(target)
        self.assert_unknown(request_control(self.path, "rotation", {"enabled": True}, timeout=0.02))
        self.assertEqual(self.server.consume(), 0)
        self.assertEqual(target.read_bytes(), b"do-not-touch")

    def test_symlink_control_directory_is_rejected(self):
        path = self.tmp / "linked.json"
        path.with_suffix(".control").symlink_to(self.directory, target_is_directory=True)
        self.assert_unknown(request_control(path, "rotation", {"enabled": True}, timeout=0.02))
        with self.assertRaises(ValueError):
            ControlServer(path, self.handler).start()

    def test_symlink_inbox_directory_is_rejected(self):
        inbox = self.directory / "inbox"
        inbox.rmdir()
        target = self.tmp / "outside-inbox"
        target.mkdir(mode=0o700)
        inbox.symlink_to(target, target_is_directory=True)
        self.assert_unknown(request_control(self.path, "rotation", {"enabled": True}, timeout=0.02))
        self.assertEqual(self.server.consume(), 0)
        self.assertEqual(list(target.iterdir()), [])

    def test_symlink_ack_prevents_execution_and_is_not_followed(self):
        path, _ = self.enqueue()
        target = self.tmp / "outside-ack"
        target.write_bytes(b"untouched")
        ack = self.directory / "ack" / path.name
        ack.symlink_to(target)
        self.assertEqual(self.server.consume(), 1)
        self.handler.assert_not_called()
        self.assertEqual(target.read_bytes(), b"untouched")

    def test_hard_link_request_is_rejected(self):
        path, _ = self.enqueue()
        target = self.tmp / "hard-linked.json"
        os.link(path, target)
        original = target.read_bytes()
        self.assertEqual(self.server.consume(), 1)
        self.handler.assert_not_called()
        self.assertEqual(target.read_bytes(), original)

    def test_world_readable_request_and_channel_are_rejected(self):
        if os.name == "nt":
            self.skipTest("POSIX mode validation")
        path, _ = self.enqueue()
        path.chmod(0o644)
        self.assertEqual(self.server.consume(), 1)
        self.handler.assert_not_called()
        self.directory.chmod(0o755)
        self.addCleanup(self.directory.chmod, 0o700)
        self.assert_unknown(request_control(self.path, "rotation", {"enabled": True}, timeout=0.02))
        with self.assertRaises(ValueError):
            ControlServer(self.path, self.handler).start()

    def test_world_readable_owner_is_rejected(self):
        if os.name == "nt":
            self.skipTest("POSIX mode validation")
        owner = self.directory / "owner.json"
        owner.chmod(0o644)
        self.assert_unknown(request_control(self.path, "rotation", {"enabled": True}, timeout=0.02))
        self.assertEqual(self.server.consume(), 0)

    def test_foreign_owner_and_late_ack_are_unconfirmed(self):
        for kind in ("foreign-owner", "late", "bad-nonce", "oversize", "symlink"):
            with self.subTest(kind=kind):
                thread, results, errors = self.request_thread(timeout=0.15)
                self.wait_for(lambda: bool(list((self.directory / "inbox").glob("*.json"))))
                path = next((self.directory / "inbox").glob("*.json"))
                request = json.loads(path.read_text())
                value = {"version": 1, "nonce": request["nonce"], "owner": request["owner"],
                         "expires_at": request["expires_at"], "state": "done", "completed_at": time.time(),
                         "result": {"code": 0, "message": "fabricated success"}}
                if kind == "foreign-owner":
                    value["owner"] = "f" * 32
                elif kind == "late":
                    value["completed_at"] = value["expires_at"]
                elif kind == "bad-nonce":
                    value["nonce"] = "f" * 32
                if kind == "oversize":
                    value = b"x" * (control.MAX_MESSAGE_BYTES + 1)
                ack = self.put("ack", request["nonce"], value)
                if kind == "symlink":
                    target = self.tmp / "symlink-ack"
                    target.write_bytes(ack.read_bytes())
                    ack.unlink()
                    ack.symlink_to(target)
                self.assert_unknown(self.finish(thread, results, errors))
                ack.unlink()
        self.handler.assert_not_called()

    def test_queue_lock_wait_counts_against_client_budget(self):
        with control._Directory(self.directory) as root, control._guard(root):
            thread, results, errors = self.request_thread(timeout=0.025)
            self.assert_unknown(self.finish(thread, results, errors))
        self.assertEqual(list((self.directory / "inbox").iterdir()), [])

    def test_directory_inode_replacement_is_detected(self):
        inbox = self.directory / "inbox"
        moved = self.directory / "old-inbox"
        with control._Directory(inbox) as directory:
            inbox.rename(moved)
            inbox.mkdir(mode=0o700)
            with self.assertRaises(ValueError):
                directory.write("1" * 32 + ".json", {"value": 1}, exclusive=True)
        moved.rmdir()

    def test_expired_ack_for_pending_nonce_does_not_reduce_capacity(self):
        for _ in range(control.MAX_REQUESTS):
            path, request = self.enqueue()
        now = time.time()
        self.put("ack", request["nonce"], {"owner": self.server.owner, "expires_at": now - 1, "state": "done"})
        self.assert_unknown(request_control(self.path, "rotation", {"enabled": True}, timeout=0.02))
        self.assertEqual(len(list((self.directory / "inbox").glob("*.json"))), control.MAX_REQUESTS)

    def test_extreme_numeric_fields_fail_closed(self):
        huge = 10 ** 1000
        for changes in ({"created_at": huge}, {"expires_at": huge}):
            with self.subTest(changes=changes):
                path, _ = self.enqueue(**changes)
                self.assertEqual(self.server.consume(), 1)
                self.assertFalse(path.exists())
        self.assert_unknown(request_control(self.path, "rotation", {"enabled": True}, timeout=huge))
        self.handler.assert_not_called()

    def test_concurrent_consumers_serialize_handler_execution(self):
        active = [0, 0]
        mutex = threading.Lock()
        errors, results = [], []

        def handler(*_):
            with mutex:
                active[0] += 1
                active[1] = max(active[1], active[0])
            threading.Event().wait(0.005)
            with mutex:
                active[0] -= 1
            return {"code": 0, "message": "verified"}

        def consume():
            try:
                results.append(self.server.consume())
            except BaseException as exc:
                errors.append(exc)

        self.server.handler = handler
        threads = []
        for _ in range(8):
            self.enqueue()
            threads.append(threading.Thread(target=consume))
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(2)
            self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(results, [1] * 8)
        self.assertEqual(active, [0, 1])
        self.assertEqual(list((self.directory / "inbox").iterdir()), [])

    def test_directory_entry_limit_rejects_overfilled_external_queue(self):
        for _ in range(control.MAX_REQUESTS + 1):
            self.enqueue()
        self.assertEqual(self.server.consume(), 0)
        self.assert_unknown(request_control(self.path, "rotation", {"enabled": True}, timeout=0.02))
        self.handler.assert_not_called()
        next((self.directory / "inbox").iterdir()).unlink()

    def test_final_ack_waits_for_short_queue_lock_contention(self):
        started, release = threading.Event(), threading.Event()

        def handler(*_):
            started.set()
            release.wait(1)
            return {"code": 0, "message": "verified"}

        self.server.handler = handler
        client, results, errors = self.request_thread(timeout=1)
        consumer = threading.Thread(target=self.consume_one)
        consumer.start()
        self.addCleanup(consumer.join, 2)
        self.addCleanup(release.set)
        self.assertTrue(started.wait(1))
        with control._Directory(self.directory) as root, control._guard(root, deadline=time.monotonic() + 1):
            release.set()
            threading.Event().wait(0.04)
            self.assertTrue(consumer.is_alive())
        consumer.join(2)
        self.assertFalse(consumer.is_alive())
        self.assertEqual(self.finish(client, results, errors)["code"], 0)

    def test_expired_orphan_running_acks_are_reclaimed_by_serial_owner(self):
        now = time.time()
        for index in range(control.MAX_REQUESTS):
            nonce = f"{index:032x}"
            self.put("ack", nonce, {"version": 1, "nonce": nonce, "owner": self.server.owner,
                                    "state": "running", "expires_at": now - 1})
        self.assert_unknown(request_control(self.path, "rotation", {"enabled": True}, timeout=0.02))
        self.assertEqual(self.server.consume(), 0)
        self.assertEqual(list((self.directory / "ack").iterdir()), [])
        client, results, errors = self.request_thread("rotation", {"enabled": True}, timeout=1)
        self.consume_one()
        self.assertEqual(self.finish(client, results, errors)["code"], 0)

    def test_restart_cleans_crashed_atomic_owner_temporary(self):
        self.server.close()
        temporary = self.directory / (".tmp-" + "e" * 32)
        temporary.write_bytes(b"incomplete atomic publication")
        temporary.chmod(0o600)
        self.server.start()
        self.assertFalse(temporary.exists())
        self.assertRegex(self.server.owner, r"^[0-9a-f]{32}$")

    def test_invalid_injected_clocks_are_unconfirmed_without_queueing(self):
        for value in (None, True, "bad", float("nan"), float("inf"), 10 ** 1000):
            with self.subTest(clock=value):
                self.assert_unknown(request_control(self.path, "rotation", {"enabled": True}, timeout=0.02, clock=lambda: value))
            with self.subTest(monotonic=value):
                self.assert_unknown(request_control(self.path, "rotation", {"enabled": True}, timeout=0.02, monotonic=lambda: value))
        self.assertEqual(list((self.directory / "inbox").iterdir()), [])

    def test_handler_result_just_under_limit_falls_back_when_envelope_is_large(self):
        self.handler.return_value = {"code": 0, "message": "x" * (control.MAX_MESSAGE_BYTES - 50)}
        thread, results, errors = self.request_thread(timeout=1)
        self.consume_one()
        self.assert_unknown(self.finish(thread, results, errors))


if __name__ == "__main__":
    import unittest
    unittest.main()
