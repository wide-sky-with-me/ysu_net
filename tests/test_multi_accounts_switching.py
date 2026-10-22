import json
import os
import threading
from pathlib import Path
from unittest.mock import Mock, patch

from tests.helpers import OFFLINE, OfflineTestCase
from ysu_net.auth.common import QueryError
from ysu_net.manager import accounts
from ysu_net.manager.account_switching import AccountSwitchResult, _bound_online, switch_account
from ysu_net.manager.backend import Result
from ysu_net.manager.config import Config, load_config, save_config, update_config


def status(owner=None, service="校园网"):
    online = owner is not None
    payload = {"data": {"portalOnlineUserInfo": {"result": "success", "userName": owner,
                                                "service": service}}} if online else OFFLINE
    return Result(0 if online else 1, json.dumps({"online": payload, "is_online": online}))


class Clock:
    def __init__(self, now=0):
        self.now = now

    def __call__(self):
        return self.now


class AccountSwitchTests(OfflineTestCase):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {}, clear=True))
        self.path = self.tmp / "config.json"
        self.config = Config(username="fixture-a", password="fixture-only", operation_timeout=30)
        save_config(self.path, self.config)
        self.target = accounts.save_account(self.path, username="fixture-b", password="fixture-b-password",
                                            service="中国移动")
        self.clock = Clock()

    def run_switch(self, responses, **kwargs):
        self.runner = Mock(side_effect=responses)
        return switch_account(self.path, self.target["id"], runner=self.runner, clock=self.clock, **kwargs)

    def actions(self):
        return [call.args[1] for call in self.runner.call_args_list]

    def test_shared_raw_service_contract_gates_account_switch(self):
        fixture = json.loads((Path(__file__).parent / "fixtures" / "online-service.json").read_text())
        before = self.path.read_bytes()
        for case in fixture["cases"]:
            payload = {"data": {"portalOnlineUserInfo": {
                "result": "success", "userId": "fixture-a", **case["fields"]}}}
            initial = Result(0, json.dumps({"online": payload, "is_online": True}))
            runner = Mock(return_value=initial)
            with self.subTest(case=case["id"]):
                if case["bound"]:
                    self.assertEqual(_bound_online(payload), ({"fixture-a"}, case["expected"]))
                else:
                    with self.assertRaises(QueryError):
                        _bound_online(payload)
                    outcome = switch_account(self.path, self.target["id"], runner=runner, clock=self.clock)
                    self.assertEqual(outcome.code, 2)
                    self.assertEqual(runner.call_count, 1)
                self.assertEqual(self.path.read_bytes(), before)

    def test_null_raw_service_switch_and_recovery_are_independently_verified(self):
        def null_raw(owner, service="校园网"):
            result = status(owner, service)
            payload = json.loads(result.output)
            payload["online"]["data"]["portalOnlineUserInfo"]["realServiceName"] = None
            result.output = json.dumps(payload)
            return result

        outcome = self.run_switch([null_raw("fixture-a"), Result(0), status(), Result(4),
                                   status(), Result(0), null_raw("fixture-a")])
        self.assertEqual(outcome.code, 4)
        self.assertTrue(outcome.restored)
        self.assertFalse(outcome.committed)
        self.assertEqual(load_config(self.path, environ={}).username, "fixture-a")
        outcome = self.run_switch([null_raw("fixture-a"), Result(0), status(), Result(0),
                                   null_raw("fixture-b", "中国移动")])
        self.assertEqual(outcome.code, 0)
        self.assertTrue(outcome.committed)
        self.assertEqual(load_config(self.path, environ={}).username, "fixture-b")

    def test_verified_online_switch_and_source_snapshot(self):
        outcome = self.run_switch([status("fixture-a"), Result(0), status(), Result(0),
                                   status("fixture-b", "中国移动")])
        self.assertEqual(outcome.code, 0)
        self.assertTrue(outcome.committed)
        self.assertFalse(outcome.restored)
        self.assertEqual(self.actions(), ["status", "logout", "status", "login", "status"])
        stored = load_config(self.path, environ={})
        self.assertEqual((stored.username, stored.password, stored.service),
                         ("fixture-b", "fixture-b-password", "中国移动"))
        saved = next(item for item in accounts.load_accounts(self.path, overlay=False)["accounts"]
                     if item["username"] == "fixture-a")
        self.assertEqual(saved["password"], "fixture-only")
        self.assertRegex(saved["id"], "^[0-9a-f]{32}$")

    def test_offline_switch_skips_logout_and_never_restores_offline_source(self):
        outcome = self.run_switch([status(), Result(4, reason="carrier_auth")])
        self.assertEqual(outcome.code, 4)
        self.assertEqual(self.actions(), ["status", "login"])
        self.assertFalse(outcome.restored)
        self.assertEqual(load_config(self.path, environ={}).username, "fixture-a")

    def test_unknown_or_foreign_status_has_no_mutation(self):
        for initial in (Result(2), Result(0, "invalid"), Result(0, "{}"), status("external"),
                        status("fixture-a", "unrecognized")):
            with self.subTest(initial=initial):
                outcome = self.run_switch([initial])
                self.assertNotEqual(outcome.code, 0)
                self.assertEqual(self.actions(), ["status"])
                self.assertEqual(load_config(self.path, environ={}).username, "fixture-a")

    def test_contradictory_status_exit_code_and_boolean_fail_closed(self):
        for value in (Result(1, status("fixture-a").output),
                      Result(0, '{"is_online":1,"online":{"data":{"portalOnlineUserInfo":{"result":"success","userName":"fixture-a","service":"校园网"}}}}')):
            outcome = self.run_switch([value])
            self.assertEqual(outcome.code, 2)
            self.assertEqual(self.actions(), ["status"])

    def test_target_ack_without_identity_service_verification_is_failure(self):
        for observed in (status(), status("external", "中国移动"), status("fixture-b"), Result(2)):
            with self.subTest(observed=observed):
                outcome = self.run_switch([status("fixture-a"), Result(0), status(), Result(0), observed,
                                           Result(2)])
                self.assertNotEqual(outcome.code, 0)
                self.assertFalse(outcome.committed)
                self.assertEqual(load_config(self.path, environ={}).username, "fixture-a")

    def test_logout_ack_without_offline_does_not_login_target(self):
        outcome = self.run_switch([status("fixture-a"), Result(0), status("fixture-a"), status("fixture-a")])
        self.assertNotEqual(outcome.code, 0)
        self.assertTrue(outcome.restored)
        self.assertNotIn("login", self.actions())

    def test_session_limit_one_recovery_with_independent_confirmation(self):
        outcome = self.run_switch([status("fixture-a", "中国联通"), Result(0), status(),
                                   Result(4, reason="session_limit"), status(), Result(0),
                                   status("fixture-a", "中国联通")])
        self.assertEqual(outcome.code, 4)
        self.assertTrue(outcome.restored)
        self.assertIn("同时在线数量", outcome.message)
        self.assertEqual([call.args[0].username for call in self.runner.call_args_list
                          if call.args[1] == "login"], ["fixture-b", "fixture-a"])
        self.assertEqual(self.runner.call_args_list[-2].args[0].service, "中国联通")

    def test_failed_recovery_is_not_repeated(self):
        outcome = self.run_switch([status("fixture-a"), Result(0), status(), Result(4),
                                   status(), Result(4)])
        self.assertFalse(outcome.restored)
        self.assertEqual(self.actions().count("login"), 2)
        self.assertEqual(len(self.actions()), 6)

    def test_recovery_stops_on_unknown_or_external_account(self):
        for observed in (Result(2), status("external")):
            outcome = self.run_switch([status("fixture-a"), Result(0), status(), Result(4), observed])
            self.assertFalse(outcome.restored)
            self.assertEqual(self.actions(), ["status", "logout", "status", "login", "status"])

    def test_owned_failed_target_may_be_disconnected_for_one_recovery(self):
        outcome = self.run_switch([status("fixture-a"), Result(0), status(), Result(0),
                                   status("fixture-b", "中国联通"), status("fixture-b", "中国联通"),
                                   Result(0), status(), Result(0), status("fixture-a")])
        self.assertNotEqual(outcome.code, 0)
        self.assertTrue(outcome.restored)
        self.assertEqual(self.actions().count("logout"), 2)
        self.assertEqual(self.runner.call_args_list[6].args[0].username, "fixture-b")

    def test_same_current_account_still_verifies_without_network_changes(self):
        outcome = switch_account(self.path, "current", runner=Mock(return_value=status("fixture-a")),
                                 clock=self.clock)
        self.assertEqual(outcome.code, 0)
        self.assertTrue(outcome.committed)
        self.assertEqual(load_config(self.path, environ={}).username, "fixture-a")

    def test_environment_presence_stops_even_empty_override(self):
        for key in ("YSU_USER", "YSU_PASS", "YSU_SERVICE"):
            with patch.dict(os.environ, {key: ""}):
                runner = Mock()
                outcome = switch_account(self.path, self.target["id"], runner=runner)
                self.assertEqual(outcome.code, 2)
                runner.assert_not_called()
        self.assertEqual(len(accounts.load_accounts(self.path, overlay=False)["accounts"]), 1)

    def test_missing_or_disabled_target_never_contacts_network(self):
        for id in ("../../path", "f" * 32):
            runner = Mock()
            self.assertEqual(switch_account(self.path, id, runner=runner).code, 2)
            runner.assert_not_called()
        accounts.save_account(self.path, id=self.target["id"], username="fixture-b",
                              service="中国移动", enabled=False)
        runner = Mock()
        self.assertEqual(switch_account(self.path, self.target["id"], runner=runner).code, 2)
        runner.assert_not_called()

    def test_new_source_intent_before_logout_stops_transition(self):
        def runner(config, action, **kwargs):
            update_config(self.path, password="latest-source")
            return status("fixture-a")
        runner = Mock(side_effect=runner)
        outcome = switch_account(self.path, self.target["id"], runner=runner, clock=self.clock)
        self.assertEqual(outcome.code, 3)
        self.assertEqual(runner.call_count, 1)
        self.assertEqual(load_config(self.path, environ={}).password, "latest-source")

    def test_concurrent_target_edit_after_login_stops_commit_and_recovery(self):
        responses = [status("fixture-a"), Result(0), status(), Result(0), status("fixture-b", "中国移动")]
        def runner(config, action, **kwargs):
            result = responses.pop(0)
            if action == "login":
                accounts.save_account(self.path, id=self.target["id"], username="fixture-b",
                                      password="latest-target", service="中国移动")
            return result
        runner = Mock(side_effect=runner)
        outcome = switch_account(self.path, self.target["id"], runner=runner, clock=self.clock)
        self.assertEqual(outcome.code, 3)
        self.assertFalse(outcome.restored)
        self.assertEqual(runner.call_count, 5)
        self.assertEqual(load_config(self.path, environ={}).username, "fixture-a")

    def test_concurrent_timer_updates_survive_commit(self):
        responses = [status("fixture-a"), Result(0), status(), Result(0), status("fixture-b", "中国移动")]
        def runner(config, action, **kwargs):
            if action == "login":
                update_config(self.path, check_interval=60, retry_interval=45)
            return responses.pop(0)
        outcome = switch_account(self.path, self.target["id"], runner=runner, clock=self.clock)
        self.assertEqual(outcome.code, 0)
        stored = load_config(self.path, environ={})
        self.assertEqual((stored.check_interval, stored.retry_interval), (60, 45))

    def test_shared_budget_shrinks_and_timeout_never_commits_or_overruns_recovery(self):
        responses = [status("fixture-a"), Result(0), status(), Result(4)]
        observed = []
        def runner(config, action, **kwargs):
            observed.append(config.operation_timeout)
            self.clock.now += 3
            return responses.pop(0)
        outcome = switch_account(self.path, self.target["id"], runner=runner,
                                 clock=self.clock, timeout=10)
        self.assertEqual(observed, [10, 7, 4, 1])
        self.assertEqual(outcome.code, 2)
        self.assertFalse(outcome.restored)
        self.assertEqual(load_config(self.path, environ={}).username, "fixture-a")

    def test_cancellation_never_returns_success(self):
        stop = threading.Event()
        runner = Mock()
        stop.set()
        outcome = switch_account(self.path, self.target["id"], runner=runner,
                                 clock=self.clock, stop_event=stop)
        self.assertEqual(outcome.code, 130)
        runner.assert_not_called()

    def test_local_exception_after_logout_gets_one_bounded_recovery(self):
        outcome = self.run_switch([status("fixture-a"), Result(0), status(), OSError("secret"),
                                   status(), Result(0), status("fixture-a")])
        self.assertEqual(outcome.code, 2)
        self.assertTrue(outcome.restored)
        self.assertNotIn("secret", outcome.message)

    def test_failed_config_commit_never_claims_success(self):
        with patch.object(accounts, "save_config", side_effect=PermissionError):
            outcome = self.run_switch([status("fixture-a"), Result(0), status(), Result(0),
                                       status("fixture-b", "中国移动"), status("fixture-b", "中国移动"),
                                       Result(0), status(), Result(0), status("fixture-a")])
        self.assertEqual(outcome.code, 2)
        self.assertTrue(outcome.restored)
        self.assertFalse(outcome.committed)
        self.assertEqual(load_config(self.path, environ={}).username, "fixture-a")
