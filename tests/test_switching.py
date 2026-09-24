import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

from tests.helpers import OFFLINE, ONLINE, OfflineTestCase
from ysu_net.auth import api
from ysu_net.auth.common import (
    InteractionRequired, OperationFailed, QueryError,
    check_action, online_service, require_online_service,
)
from ysu_net.manager import backend, cli, config
from ysu_net.manager.backend import Result
from ysu_net.manager.locking import exclusive_config
from ysu_net.manager.switching import SwitchResult, switch_service


def status(service=None, owner="mock-user"):
    payload = OFFLINE if service is None else {
        "data": {"portalOnlineUserInfo": {
            "result": "success", "service": service, "userName": owner,
        }}
    }
    return Result(1 if service is None else 0,
                  json.dumps({"is_online": service is not None, "online": payload}))


class ServiceProtocolTests(OfflineTestCase):
    def test_live_session_limit_is_immediate_and_redacted(self):
        response = {"code": 200, "data": {"online": False,
            "message": "portal认证失败，失败原因：你使用的账号已达到同时在线用户数量上限!，用户(secret-account)"}}
        with self.assertRaises(InteractionRequired) as error:
            check_action(200, response, "上线")
        self.assertIn("同时在线数量", str(error.exception))
        self.assertNotIn("secret-account", str(error.exception))

    def test_known_credential_failure_requires_intervention(self):
        with self.assertRaises(InteractionRequired):
            check_action(200, {"data": {"online": False, "message": "portal认证失败，账号密码错误"}}, "上线")

    def test_business_rejection_inside_http_success(self):
        with self.assertRaises(OperationFailed):
            check_action(200, {"data": {"online": False, "message": "portal认证失败，secret"}}, "上线")

    def test_pending_without_error_can_still_be_polled(self):
        check_action(200, {"data": {"online": False, "message": None}}, "上线")
        check_action(200, {"data": {"online": True, "message": None}}, "上线")

    def test_real_service_name_is_supported(self):
        payload = {"data": {"portalOnlineUserInfo": {
            "result": "success", "service": "opaque-id", "realServiceName": "中国移动"}}}
        self.assertEqual(online_service(payload), "中国移动")

    def test_unknown_or_conflicting_service_fails_closed(self):
        for fields in ({}, {"service": "unknown"},
                       {"service": "校园网", "realServiceName": "中国移动"}):
            with self.subTest(fields=fields), self.assertRaises(QueryError):
                online_service({"data": {"portalOnlineUserInfo": {"result": "success", **fields}}})

    def test_wrong_service_is_not_success(self):
        with self.assertRaises(OperationFailed):
            require_online_service(ONLINE, "中国移动")
        self.assertEqual(require_online_service(ONLINE, "校园网"), "校园网")

    def test_api_already_online_does_not_claim_mobile_login(self):
        self.mock("ysu_net.auth.api.open_portal_get_session", return_value=SimpleNamespace(sess=Mock(), session_id="sid"))
        self.mock("ysu_net.auth.api.get_online_info", return_value=ONLINE)
        post = self.mock("ysu_net.auth.api.api_post_json")
        with self.assertRaises(OperationFailed):
            api.cmd_login("中国移动", "mock-user", "password", False, 5)
        post.assert_not_called()

    def test_api_verifies_service_after_login(self):
        self.mock("ysu_net.auth.api.open_portal_get_session", return_value=SimpleNamespace(sess=Mock(), session_id="sid", last_url="https://portal.invalid/"))
        self.mock("ysu_net.auth.api.get_online_info", side_effect=[OFFLINE, ONLINE])
        self.mock("ysu_net.auth.api.get_current_node", return_value="serviceSelection")
        self.mock("ysu_net.auth.api.api_post_json", return_value=(200, {"result": "success"}))
        with self.assertRaises(OperationFailed):
            api.cmd_login("中国移动", "mock-user", "password", False, 5)

    def test_diagnostics_use_only_fixed_messages(self):
        for code, error, reason in (
            (4, "运营商同时在线数量已达上限 secret-account", "session_limit"),
            (3, "在线服务与请求不一致 secret-account", "service_mismatch"),
            (2, "NameResolutionError secret-host", "dns"),
            (2, "CERTIFICATE_VERIFY_FAILED secret-host", "tls"),
        ):
            with self.subTest(reason=reason):
                classified = backend.failure_reason(code, error)
                self.assertEqual(classified, reason)
                self.assertNotIn("secret", Result(code, reason=classified).message)
        self.assertEqual(backend.failure_reason(0, "NameResolutionError"), "")
        self.assertEqual(backend.failure_reason(2, "private-account"), "")

    def test_backend_keeps_redacted_reason_from_stderr(self):
        process = Mock(returncode=4)
        process.communicate.return_value = ("", "[ERROR] 运营商同时在线数量已达上限 private-account")
        self.mock("ysu_net.manager.backend.subprocess.Popen", return_value=process)
        result = backend.run_backend(config.Config(username="u", password="p"), "login")
        self.assertEqual(result.reason, "session_limit")
        self.assertNotIn("private-account", result.message)


class SwitchingTests(OfflineTestCase):
    def setUp(self):
        super().setUp()
        self.config = config.Config(username="mock-user", password="password")

    def run_switch(self, results, target="中国移动"):
        self.runner = Mock(side_effect=results)
        return switch_service(self.config, target, runner=self.runner)

    def test_verified_switch(self):
        result = self.run_switch([status("校园网"), Result(0), status(), Result(0), status("中国移动")])
        self.assertEqual(result.code, 0)
        self.assertEqual([c.args[1] for c in self.runner.call_args_list], ["status", "logout", "status", "login", "status"])
        self.assertEqual(self.runner.call_args_list[3].args[0].service, "中国移动")
        self.assertEqual(self.config.service, "校园网")

    def test_same_service_is_non_destructive(self):
        result = self.run_switch([status("中国移动")])
        self.assertEqual(result.code, 0)
        self.assertEqual(self.runner.call_count, 1)

    def test_offline_login_has_no_logout(self):
        result = self.run_switch([status(), Result(0), status("中国移动")])
        self.assertEqual(result.code, 0)
        self.assertEqual([c.args[1] for c in self.runner.call_args_list], ["status", "login", "status"])

    def test_unknown_state_never_mutates(self):
        for value in (Result(2), Result(0, "not json"), Result(0, "{}"), status("unknown")):
            with self.subTest(value=value):
                self.assertEqual(self.run_switch([value]).code, 2)
                self.assertEqual(self.runner.call_count, 1)

    def test_inconsistent_exit_code_never_mutates(self):
        value = status("校园网")
        value.code = 1
        self.assertEqual(self.run_switch([value]).code, 2)
        self.assertEqual(self.runner.call_count, 1)

    def test_other_account_is_preserved(self):
        self.assertEqual(self.run_switch([status("校园网", owner="other")]).code, 3)
        self.assertEqual(self.runner.call_count, 1)

    def test_session_limit_restores_original_once(self):
        result = self.run_switch([status("校园网"), Result(0), status(),
            Result(4, reason="session_limit"), status(), Result(0), status("校园网")])
        self.assertEqual(result.code, 4)
        self.assertTrue(result.restored)
        self.assertIn("同时在线数量", result.message)
        self.assertIn("已恢复校园网", result.message)
        logins = [c.args[0].service for c in self.runner.call_args_list if c.args[1] == "login"]
        self.assertEqual(logins, ["中国移动", "校园网"])

    def test_failed_logout_does_not_login_target(self):
        result = self.run_switch([status("校园网"), Result(3), status("校园网")])
        self.assertEqual(result.code, 3)
        self.assertTrue(result.restored)
        self.assertNotIn("login", [c.args[1] for c in self.runner.call_args_list])

    def test_logout_ack_without_offline_is_not_enough(self):
        result = self.run_switch([status("校园网"), Result(0), status("校园网"), status("校园网")])
        self.assertEqual(result.code, 3)
        self.assertTrue(result.restored)

    def test_login_ack_without_target_is_not_enough(self):
        result = self.run_switch([status("校园网"), Result(0), status(), Result(0), status("校园网"), status("校园网")])
        self.assertEqual(result.code, 3)
        self.assertTrue(result.restored)

    def test_recovery_unknown_is_not_blind_login(self):
        result = self.run_switch([status("校园网"), Result(0), status(), Result(4), Result(2)])
        self.assertFalse(result.restored)
        self.assertIn("恢复未确认", result.message)
        self.assertEqual(self.runner.call_count, 5)

    def test_recovery_never_disconnects_other_account(self):
        result = self.run_switch([status("校园网"), Result(0), status(), Result(4), status("中国移动", owner="other")])
        self.assertFalse(result.restored)
        self.assertEqual(self.runner.call_count, 5)

    def test_actual_service_is_the_rollback_target(self):
        result = self.run_switch([status("中国联通"), Result(0), status(), Result(3), status(), Result(0), status("中国联通")])
        self.assertTrue(result.restored)
        self.assertEqual(self.runner.call_args_list[-2].args[0].service, "中国联通")

    def test_local_exception_after_logout_triggers_recovery(self):
        result = self.run_switch([status("校园网"), Result(0), status(), OSError("secret"), status(), Result(0), status("校园网")])
        self.assertEqual(result.code, 2)
        self.assertTrue(result.restored)
        self.assertNotIn("secret", result.message)

    def test_cancel_attempts_recovery_and_propagates(self):
        with self.assertRaises(KeyboardInterrupt):
            self.run_switch([status("校园网"), Result(0), status(), KeyboardInterrupt(), status(), Result(0), status("校园网")])
        self.assertEqual(self.runner.call_count, 7)

    def test_missing_credentials_does_not_touch_network(self):
        self.config.password = ""
        self.assertEqual(self.run_switch([]).code, 4)
        self.runner.assert_not_called()

    def test_invalid_service_does_not_touch_network(self):
        self.assertEqual(self.run_switch([], "unknown").code, 2)
        self.runner.assert_not_called()


class SwitchCliTests(OfflineTestCase):
    def setUp(self):
        super().setUp()
        self.path = self.tmp / "config.json"
        config.save_config(self.path, config.Config(username="stored-user", password="stored-password"))
        self.mock("ysu_net.manager.cli.config_path", return_value=self.path)
        self.switch = self.mock("ysu_net.manager.cli.switch_service", return_value=SwitchResult(0, "success"))

    def test_success_saves_only_stored_credentials(self):
        with patch.dict("os.environ", {"YSU_USER": "env-user", "YSU_PASS": "env-password"}):
            self.assertEqual(cli.main(["switch", "中国移动"]), 0)
        stored = config.load_config(self.path, environ={})
        self.assertEqual(stored.service, "中国移动")
        self.assertEqual(stored.password, "stored-password")
        self.assertEqual(self.switch.call_args.args[0].password, "env-password")

    def test_failure_keeps_configuration(self):
        before = self.path.read_bytes()
        self.switch.return_value = SwitchResult(4, "limit", "校园网", True)
        self.assertEqual(cli.main(["switch", "中国移动"]), 4)
        self.assertEqual(self.path.read_bytes(), before)

    def test_daemon_lock_prevents_switch(self):
        with exclusive_config(self.path):
            self.assertEqual(cli.main(["switch", "中国移动"]), 2)
        self.switch.assert_not_called()

    def test_concurrent_config_updates_are_preserved(self):
        def during_network(current, target):
            self.assertEqual(cli.main(["config", "set", "check_interval", "60"]), 0)
            config.update_config(self.path, password="new-password")
            return SwitchResult(0, "success")
        self.switch.side_effect = during_network
        self.assertEqual(cli.main(["switch", "中国移动"]), 0)
        stored = config.load_config(self.path, environ={})
        self.assertEqual(stored.password, "new-password")
        self.assertEqual(stored.check_interval, 60)
        self.assertEqual(stored.service, "中国移动")

    def test_config_hot_reload_remains_available_during_daemon(self):
        with exclusive_config(self.path):
            self.assertEqual(cli.main(["config", "set", "check_interval", "60"]), 0)
        self.assertEqual(config.load_config(self.path, environ={}).check_interval, 60)

    def test_save_failure_reports_network_already_changed(self):
        self.mock("ysu_net.manager.cli.update_config", side_effect=PermissionError())
        self.assertEqual(cli.main(["switch", "中国移动"]), 2)
        self.assertIn("已切换到中国移动", self.errors.getvalue())
