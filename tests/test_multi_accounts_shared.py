"""Shared raw-account cases through the rotation guard, not a display summary."""
import json
import os
from pathlib import Path
from unittest.mock import Mock, patch

from tests.helpers import OfflineTestCase
from tests.test_multi_accounts_switching import Clock, status
from ysu_net.auth.quota import classify_quota
from ysu_net.manager.accounts import save_account, set_rotation
from ysu_net.manager.account_switching import AccountRotation, AccountSwitchResult
from ysu_net.manager.backend import Result
from ysu_net.manager.config import Config, save_config


class SharedQuotaRotationTests(OfflineTestCase):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {}, clear=True))
        self.path = self.tmp / "config.json"
        save_config(self.path, Config(username="fixture-a", password="fixture-only"))
        save_account(self.path, username="fixture-b", password="fixture-only")
        set_rotation(self.path, True, auto_reconnect=True)
        self.clock = Clock()
        self.raw = None
        self.switcher = Mock(return_value=AccountSwitchResult(0, "verified", committed=True))
        self.rotation = AccountRotation(self.path, runner=self.runner, clock=self.clock,
                                         classifier=classify_quota, switcher=self.switcher)

    def runner(self, config, action, **kwargs):
        online = status(config.username, config.service)
        if action == "status":
            return online
        if action == "info":
            return Result(0, json.dumps({"online": json.loads(online.output)["online"],
                                         "account_http_status": 200, "account": self.raw}))
        raise AssertionError("unexpected authentication")

    def test_shared_quota_cases_only_independent_explicit_zero_can_rotate(self):
        fixture = Path(__file__).parent / "fixtures/account-quota.json"
        cases = json.loads(fixture.read_text(encoding="utf-8"))["cases"]
        for case in cases:
            with self.subTest(case=case["id"]):
                self.rotation.reset(manual=True)
                self.switcher.reset_mock()
                self.raw = case["raw"]
                self.clock.now += 60
                self.assertEqual(classify_quota(self.raw), case["expected"])
                self.rotation.step()
                self.clock.now += 60
                self.rotation.step()
                if case["expected"]["state"] == "zero_reported":
                    self.switcher.assert_called_once()
                else:
                    self.switcher.assert_not_called()
                    self.assertEqual(self.rotation.quota, case["expected"])

