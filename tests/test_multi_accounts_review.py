"""Regressions for the account feature's independent review findings."""
import json
import os
from unittest.mock import patch

from tests.helpers import OfflineTestCase
from tests.test_multi_accounts_switching import Clock, status
from ysu_net.auth.common import QueryError, online_service, online_state
from ysu_net.manager import accounts
from ysu_net.manager.account_switching import AccountRotation, switch_account
from ysu_net.manager.backend import Result
from ysu_net.manager.config import Config, load_config, save_config, update_config


class AccountReviewTests(OfflineTestCase):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {}, clear=True))
        self.path = self.tmp / "config.json"
        save_config(self.path, Config(username="fixture-a", password="fixture-only"))
        self.target = accounts.save_account(self.path, username="fixture-b", password="fixture-only")
        accounts.set_rotation(self.path, True, auto_reconnect=True)
        self.clock = Clock()
        self.mutations = []
        self.bad = None
        self.bad_stage = "all"
        self.status_calls = 0

    def runner(self, config, action, **kwargs):
        data = json.loads(status(config.username, config.service).output)
        if action == "status":
            self.status_calls += 1
            if self.bad is not None and (self.bad_stage == "all" or self.bad_stage == "after" and self.status_calls % 2 == 0):
                self.bad(data["online"])
            return Result(0, json.dumps(data))
        if action == "info":
            online = data["online"]
            if self.bad is not None and self.bad_stage in ("all", "info"):
                self.bad(online)
            return Result(0, json.dumps({"online": online, "account_http_status": 200,
                "account": {"data": {"accountInfo": [{"title": "剩余流量", "content": "0 MB"}]}}}))
        self.mutations.append((action, config.username))
        return Result(0, "verified")

    def test_business_identity_and_raw_service_conflicts_never_become_zero_evidence(self):
        mutations = [lambda p: p.update(result="fail"),
                     lambda p: p["data"].update(success=False),
                     lambda p: p.update(code=500),
                     lambda p: p["data"]["portalOnlineUserInfo"].update(userId="external", userName="fixture-a"),
                     lambda p: p["data"]["portalOnlineUserInfo"].update(realServiceName="unknown", service="校园网"),
                     lambda p: p["data"]["portalOnlineUserInfo"].update(service="unknown", realServiceName="校园网")]
        for stage in ("all", "info", "after"):
            for bad in mutations:
                with self.subTest(stage=stage, bad=bad):
                    self.bad, self.bad_stage, self.status_calls = bad, stage, 0
                    calls = []
                    rotation = AccountRotation(self.path, runner=self.runner, clock=self.clock,
                                               switcher=lambda *a, **k: calls.append((a, k)))
                    rotation.step()
                    self.clock.now += 60
                    rotation.step()
                    self.assertIsNone(rotation.zero_key)
                    self.assertEqual(calls, [])
                    self.assertEqual(self.mutations, [])

    def test_quota_source_changed_immediately_before_prepare_keeps_new_intent(self):
        def interleave(path, id, **kwargs):
            self.assertEqual(kwargs["expected_source"].username, "fixture-a")
            update_config(path, username="fixture-c", password="fixture-c-only")
            return switch_account(path, id, **kwargs)
        rotation = AccountRotation(self.path, runner=self.runner, clock=self.clock, switcher=interleave)
        rotation.step()
        self.clock.now += 60
        rotation.step()
        self.assertEqual(load_config(self.path, environ={}).username, "fixture-c")
        self.assertEqual(self.mutations, [])

    def test_cross_language_invalid_account_inputs_never_write(self):
        invalid = [{"label": "line\nbreak"}, {"username": " fixture-c "},
                   {"username": "a" * 257}, {"username": "中" * 86},
                   {"username": "fixture\x00c"}, {"password": "a" * 4097},
                   {"password": "中" * 1366}]
        before = accounts.accounts_path(self.path).read_bytes()
        for changes in invalid:
            with self.subTest(changes=list(changes)):
                values = {"username": "fixture-c", "password": "fixture-only"} | changes
                with self.assertRaises(ValueError):
                    accounts.save_account(self.path, **values)
                self.assertEqual(accounts.accounts_path(self.path).read_bytes(), before)
        saved = accounts.save_account(self.path, username="中" * 85, password="a" * 4096, label="名" * 80)
        self.assertTrue(saved["password_set"])

    def test_auto_off_and_expired_zero_require_a_fresh_pair(self):
        rotation = AccountRotation(self.path, runner=self.runner, clock=self.clock)
        rotation.step()
        self.assertIsNotNone(rotation.zero_key)
        rotation.step(auto_reconnect=False)
        self.assertIsNone(rotation.zero_key)
        rotation.step()
        self.clock.now += 121
        self.assertIn("过期", rotation.step())
        self.assertEqual(self.mutations, [])

    def test_common_outer_failure_is_query_error_even_for_nested_online(self):
        for key, value in (("result", "fail"), ("code", 500), ("success", False)):
            for layer in (0, 1, 2):
                payload = json.loads(status("fixture-a").output)["online"]
                target = [payload, payload["data"], payload["data"]["portalOnlineUserInfo"]][layer]
                target[key] = value
                with self.assertRaises(QueryError):
                    online_state(payload)
        payload = json.loads(status("fixture-a").output)["online"]
        payload["data"]["portalOnlineUserInfo"].update(realServiceName="校园网", service="opaque-id")
        self.assertEqual(online_service(payload), "校园网")
