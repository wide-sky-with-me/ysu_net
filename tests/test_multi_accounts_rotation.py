import json
import os
from pathlib import Path
from unittest.mock import Mock, patch

from tests.helpers import OfflineTestCase
from tests.test_multi_accounts_switching import Clock, status
from ysu_net.manager import accounts
from ysu_net.manager.account_switching import AccountController, AccountRotation, AccountSwitchResult
from ysu_net.manager.backend import Result
from ysu_net.manager.config import Config, load_config, save_config, update_config


class RotationTests(OfflineTestCase):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {}, clear=True))
        self.path = self.tmp / "config.json"
        save_config(self.path, Config(username="fixture-a", password="fixture-only"))
        self.b = accounts.save_account(self.path, username="fixture-b", password="fixture-only")
        self.c = accounts.save_account(self.path, username="fixture-c", password="fixture-only")
        self.clock = Clock()
        self.raw = {"data": {"accountInfo": [{"title": "剩余流量", "content": "0 GB"}]}}
        self.classifier = Mock(return_value={"state": "zero_reported", "message": "门户报告零"})
        self.switcher = Mock(return_value=AccountSwitchResult(0, "verified", committed=True))
        self.runner = Mock(side_effect=self.run_backend_fake)
        self.rotation = AccountRotation(self.path, runner=self.runner, clock=self.clock,
                                         classifier=self.classifier, switcher=self.switcher)

    def enable(self):
        accounts.set_rotation(self.path, True, auto_reconnect=True)

    def run_backend_fake(self, config, action, **kwargs):
        online = status(config.username, config.service)
        if action == "status":
            return online
        if action == "info":
            return Result(0, json.dumps({"online": json.loads(online.output)["online"],
                                         "account_http_status": 200, "account": self.raw}))
        raise AssertionError("rotation authenticated outside the switcher")

    def two(self):
        self.rotation.step()
        self.clock.now += 60
        return self.rotation.step()

    def test_default_off_or_auto_off_never_queries(self):
        self.assertEqual(self.rotation.step(), "")
        self.enable()
        self.assertEqual(self.rotation.step(auto_reconnect=False), "")
        self.runner.assert_not_called()
        self.switcher.assert_not_called()

    def test_shared_raw_service_contract_gates_every_rotation_observation(self):
        self.enable()
        fixture = json.loads((Path(__file__).parent / "fixtures" / "online-service.json").read_text())
        for case in fixture["cases"]:
            expected = case["expected"] or "校园网"
            update_config(self.path, service=expected)
            good = json.loads(status("fixture-a", expected).output)["online"]
            payload = {"data": {"portalOnlineUserInfo": {
                "result": "success", "userId": "fixture-a", **case["fields"]}}}
            for stage in ("before", "embedded", "after"):
                with self.subTest(case=case["id"], stage=stage):
                    self.rotation.reset(manual=True)
                    self.runner.reset_mock()
                    self.switcher.reset_mock()
                    self.classifier.reset_mock()
                    observed = Result(0, json.dumps({"is_online": True, "online": payload}))
                    normal = Result(0, json.dumps({"is_online": True, "online": good}))
                    info = Result(0, json.dumps({"online": payload if stage == "embedded" else good,
                                                "account_http_status": 200, "account": self.raw}))
                    for _ in range(2):
                        self.runner.side_effect = [observed if stage == "before" else normal, info,
                                                   observed if stage == "after" else normal]
                        self.rotation.step()
                        self.clock.now += 60
                    if case["bound"]:
                        self.assertEqual(self.classifier.call_count, 2)
                        self.switcher.assert_called_once()
                    else:
                        self.switcher.assert_not_called()
                        self.assertIsNone(self.rotation.zero_time)
                        self.assertEqual(self.rotation.quota["state"], "unknown")
                    if not case["bound"] and stage == "before":
                        self.assertEqual([call.args[1] for call in self.runner.call_args_list],
                                         ["status", "status"])

    def test_zero_requires_independent_queries_at_least_sixty_seconds_apart(self):
        self.enable()
        first = self.rotation.step()
        self.assertIn("首次", first)
        self.clock.now = 59
        self.assertEqual(self.rotation.step(), "")
        self.assertEqual(self.runner.call_count, 3)
        self.switcher.assert_not_called()
        self.clock.now = 60
        self.assertEqual(self.rotation.step(), "verified")
        self.assertEqual(self.runner.call_count, 6)
        self.classifier.assert_called_with(self.raw)
        self.switcher.assert_called_once()
        self.assertEqual(self.switcher.call_args.args[1], self.b["id"])
        self.assertEqual(self.rotation.quota["state"], "unknown")
        self.assertTrue(all(call.kwargs.get("raw") for call in self.runner.call_args_list))

    def test_available_unlimited_unknown_clear_zero_chain(self):
        self.enable()
        for state in ("available", "unlimited", "unknown"):
            self.rotation.reset()
            self.classifier.return_value = {"state": "zero_reported", "message": "zero"}
            self.rotation.step()
            self.classifier.return_value = {"state": state, "message": state}
            self.clock.now += 60
            self.rotation.step()
            self.classifier.return_value = {"state": "zero_reported", "message": "zero"}
            self.clock.now += 60
            self.assertIn("首次", self.rotation.step())
            self.switcher.assert_not_called()

    def test_unknown_offline_foreign_wrong_service_status_prevents_account_query(self):
        self.enable()
        for result in (Result(2), status(), status("external"), status("fixture-a", "中国移动")):
            self.rotation.reset()
            self.runner.reset_mock()
            self.runner.side_effect = [result]
            self.rotation.step()
            self.assertEqual(self.runner.call_count, 1)
            self.switcher.assert_not_called()

    def test_http_business_and_malformed_account_failure_do_not_rotate(self):
        self.enable()
        online = json.loads(status("fixture-a").output)["online"]
        responses = [Result(4), Result(2), Result(0, "invalid"),
                     Result(0, json.dumps({"online": online, "account": self.raw})),
                     Result(0, json.dumps({"online": online, "account": self.raw, "account_http_status": 500})),
                     Result(0, json.dumps({"online": online, "account": self.raw, "account_http_status": "200"}))]
        for result in responses:
            self.rotation.reset()
            self.runner.side_effect = [status("fixture-a"), result]
            self.rotation.step()
            self.switcher.assert_not_called()
            self.assertEqual(self.rotation.quota["state"], "unknown")

    def test_info_identity_or_service_mismatch_never_counts_zero(self):
        self.enable()
        for payload in (json.loads(status("external").output)["online"],
                        json.loads(status("fixture-a", "中国移动").output)["online"]):
            self.rotation.reset()
            info = Result(0, json.dumps({"online": payload, "account_http_status": 200, "account": self.raw}))
            self.runner.side_effect = [status("fixture-a"), info]
            self.rotation.step()
            self.assertIsNone(self.rotation.zero_time)
            self.switcher.assert_not_called()

    def test_after_query_foreign_or_unknown_clears_observation(self):
        self.enable()
        info = self.run_backend_fake(load_config(self.path, environ={}), "info")
        for after in (status("external"), status("fixture-a", "中国移动"), Result(2)):
            self.rotation.reset()
            self.runner.side_effect = [status("fixture-a"), info, after]
            self.rotation.step()
            self.assertIsNone(self.rotation.zero_time)
            self.assertEqual(self.rotation.quota["state"], "unknown")

    def test_changed_config_during_query_never_counts_zero(self):
        self.enable()
        def run(config, action, **kwargs):
            if action == "info":
                update_config(self.path, password="new")
            return self.run_backend_fake(config, action, **kwargs)
        self.runner.side_effect = run
        self.rotation.step()
        self.assertIsNone(self.rotation.zero_time)
        self.switcher.assert_not_called()

    def test_disabled_intent_during_query_stops_rotation(self):
        self.enable()
        def run(config, action, **kwargs):
            if action == "info":
                accounts.set_rotation(self.path, False)
            return self.run_backend_fake(config, action, **kwargs)
        self.runner.side_effect = run
        self.rotation.step()
        self.assertIsNone(self.rotation.zero_time)
        self.switcher.assert_not_called()

    def test_environment_override_stops_queries_and_breaks_chain(self):
        self.enable()
        self.rotation.step()
        with patch.dict(os.environ, {"YSU_PASS": ""}):
            self.clock.now += 60
            self.rotation.step()
        self.assertIsNone(self.rotation.zero_time)
        self.assertEqual(self.runner.call_count, 3)
        self.switcher.assert_not_called()

    def test_current_credentials_or_service_change_breaks_chain(self):
        self.enable()
        self.rotation.step()
        update_config(self.path, service="中国移动")
        self.clock.now += 60
        self.assertIn("首次", self.rotation.step())
        self.switcher.assert_not_called()

    def test_first_enabled_candidate_in_list_only_and_failure_cooldown(self):
        self.enable()
        self.switcher.return_value = AccountSwitchResult(4, "interaction")
        self.two()
        self.assertEqual(self.switcher.call_args.args[1], self.b["id"])
        self.assertEqual(self.switcher.call_count, 1)
        self.clock.now += 60
        self.rotation.step()
        self.clock.now += 60
        self.rotation.step()
        self.assertEqual(self.switcher.call_args.args[1], self.c["id"])
        self.assertEqual(self.switcher.call_count, 2)
        self.clock.now += 60
        self.rotation.step()
        self.clock.now += 60
        message = self.rotation.step()
        self.assertIn("冷却", message)
        self.assertEqual(self.switcher.call_count, 2)

    def test_candidate_cooldown_is_at_least_nine_hundred_seconds(self):
        accounts.delete_account(self.path, self.c["id"])
        self.enable()
        self.switcher.return_value = AccountSwitchResult(3, "failure")
        self.two()
        self.clock.now = 900
        self.rotation.step()
        self.assertEqual(self.switcher.call_count, 1)
        self.clock.now = 960
        self.rotation.step()
        self.assertEqual(self.switcher.call_count, 2)

    def test_changed_candidate_credentials_allow_retry_before_cooldown(self):
        accounts.delete_account(self.path, self.c["id"])
        self.enable()
        self.switcher.return_value = AccountSwitchResult(4, "failure")
        self.two()
        accounts.save_account(self.path, id=self.b["id"], username="fixture-b", password="new")
        self.clock.now += 60
        self.rotation.step()
        self.clock.now += 60
        self.rotation.step()
        self.assertEqual(self.switcher.call_count, 2)

    def test_disabled_candidates_and_missing_credentials_are_skipped(self):
        self.enable()
        accounts.save_account(self.path, id=self.b["id"], username="fixture-b", enabled=False)
        self.two()
        self.assertEqual(self.switcher.call_args.args[1], self.c["id"])

    def test_insufficient_accounts_pauses_without_network(self):
        self.enable()
        accounts.delete_account(self.path, self.b["id"])
        accounts.delete_account(self.path, self.c["id"])
        self.assertIn("不足", self.rotation.step())
        self.runner.assert_not_called()

    def test_bad_classifier_is_unknown_never_exhaustion(self):
        self.enable()
        for value in (None, {}, {"state": "zero_reported", "message": 1},
                      {"state": "exhausted", "message": "bad"}):
            self.rotation.reset()
            self.classifier.return_value = value
            self.rotation.step()
            self.assertEqual(self.rotation.quota["state"], "unknown")
            self.switcher.assert_not_called()

    def test_manual_reset_clears_cooldown_and_observations(self):
        self.enable()
        self.switcher.return_value = AccountSwitchResult(4, "failure")
        self.two()
        self.assertTrue(self.rotation.cooldowns)
        self.rotation.reset(manual=True)
        self.assertFalse(self.rotation.cooldowns)
        self.assertIsNone(self.rotation.zero_time)

    def test_source_cooldown_survives_virtual_id_becoming_persisted(self):
        self.enable()
        self.rotation.step()
        source, target = accounts.prepare_switch(self.path, self.b["id"])
        current = next(item for item in accounts.load_accounts(self.path)["accounts"]
                       if item["username"] == "fixture-a")
        from ysu_net.manager.account_switching import _cooldown_key
        self.assertEqual(self.rotation.cooldowns[_cooldown_key(current)], 900)

    def test_rotation_budget_is_shared_with_transition(self):
        self.enable()
        def run(config, action, **kwargs):
            self.clock.now += 2
            return self.run_backend_fake(config, action, **kwargs)
        self.runner.side_effect = run
        self.rotation.step()
        self.clock.now += 60
        self.rotation.step()
        self.assertEqual(self.switcher.call_args.kwargs["timeout"], 174)

    def test_disable_latch_survives_persistence_failure(self):
        self.enable()
        controller = AccountController(self.path, runner=self.runner)
        with patch.object(accounts, "_write_book", side_effect=PermissionError):
            with self.assertRaises(OSError):
                controller.handle("rotation", {"enabled": False}, __import__("time").time() + 10)
        self.assertTrue(controller.rotation.disabled)
        self.assertEqual(controller.rotation.step(), "")
        self.runner.assert_not_called()
        self.assertFalse(controller.snapshot()["auto_switch"])

    def test_public_quota_never_relabels_a_previous_identity(self):
        self.enable()
        self.rotation.step()
        self.assertEqual(self.rotation.public_quota()["state"], "zero_reported")
        update_config(self.path, username="fixture-b", password="other")
        self.assertEqual(self.rotation.public_quota()["state"], "unknown")

    def test_public_quota_environment_override_is_unknown(self):
        self.enable()
        self.rotation.step()
        with patch.dict(os.environ, {"YSU_USER": "fixture-b"}):
            self.assertEqual(self.rotation.public_quota()["state"], "unknown")
