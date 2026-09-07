import io
import json
import runpy
from types import SimpleNamespace
from unittest.mock import Mock, patch

import requests
import ysu_api as api
from ysu_common import InteractionRequired, OperationFailed, QueryError, online_state
from tests.helpers import OFFLINE, ONLINE, OfflineTestCase


class ProtocolTests(OfflineTestCase):
    def response(self, payload, status=200):
        return SimpleNamespace(status_code=status, json=lambda: payload)

    def session(self):
        sess = Mock(spec=requests.Session)
        sess.headers = {}
        sess.cookies = requests.cookies.RequestsCookieJar()
        self.mock("ysu_api.requests.Session", return_value=sess)
        self.mock("ysu_api._portal_api_headers", return_value={})
        return sess

    def test_recognized_states(self):
        self.assertTrue(online_state(ONLINE))
        self.assertFalse(online_state(OFFLINE))

    def test_unknown_errors_are_never_offline(self):
        for payload in (None, {}, [], {"data": None}, {"data": {"portalOnlineUserInfo": {"result": "fail", "message": "session expired"}}}):
            with self.subTest(payload=payload), self.assertRaises(QueryError):
                online_state(payload)

    def test_http_500_is_query_failure(self):
        sess = self.session()
        sess.get.return_value = self.response({}, 500)
        with self.assertRaises(QueryError):
            api.get_online_info(sess, "sid", False)

    def test_non_json_is_query_failure(self):
        sess = self.session()
        response = Mock(status_code=200, text="<html>captive page</html>")
        response.json.side_effect = ValueError("not JSON")
        sess.get.return_value = response
        with self.assertRaises(QueryError):
            api.get_online_info(sess, "sid", False)

    def test_status_closes_session_on_connection_failure(self):
        sess = self.session()
        sess.get.side_effect = requests.ConnectionError("mock DNS unavailable")
        with self.assertRaises(requests.ConnectionError):
            api.cmd_status(debug=False, raw=False)
        sess.close.assert_called_once()

    def context(self):
        sess = self.session()
        context = SimpleNamespace(sess=sess, session_id="sid", last_url="https://auth1.ysu.edu.cn/?sessionId=sid")
        self.mock("ysu_api.open_portal_get_session", return_value=context)
        return sess

    def test_status_raw_and_exit_code(self):
        sess = self.context()
        sess.get.return_value = self.response(OFFLINE)
        self.mock("sys.argv", new=["ysu_api.py", "status", "--raw"])
        with self.assertRaises(SystemExit) as exc:
            api.main()
        self.assertEqual(exc.exception.code, 1)
        self.assertFalse(json.loads(self.output.getvalue())["is_online"])

    def test_login_calls_service_then_online_and_verifies(self):
        sess = self.context()
        sess.get.side_effect = [self.response(OFFLINE), self.response(ONLINE)]
        sess.post.side_effect = [
            self.response({"data": {"currentNodePath": "serviceSelection"}}),
            self.response({"result": "success"}), self.response({"result": "success"}),
            self.response({"data": {}}),
        ]
        api.cmd_login("校园网", "user", "password", False, 5)
        urls = [call.args[0] for call in sess.post.call_args_list]
        self.assertEqual(urls[1:3], [api.URLS.api_service_login, api.URLS.api_user_online])
        self.assertIn("已在线", self.output.getvalue())

    def test_already_online_skips_authentication(self):
        sess = self.context()
        sess.get.return_value = self.response(ONLINE)
        sess.post.return_value = self.response({})
        cas = self.mock("ysu_api.cas_login")
        api.cmd_login("校园网", "user", "password", False, 5)
        cas.assert_not_called()
        self.assertEqual(sess.post.call_count, 1)

    def test_login_timeout_is_failure(self):
        sess = self.context()
        sess.get.return_value = self.response(OFFLINE)
        sess.post.return_value = self.response({"data": {"currentNodePath": "unknown"}})
        with self.assertRaises(OperationFailed):
            api.cmd_login("校园网", "user", "password", False, 0)

    def test_rejected_service_does_not_request_online(self):
        sess = self.context()
        sess.get.return_value = self.response(OFFLINE)
        sess.post.side_effect = [self.response({"data": {"currentNodePath": "serviceSelection"}}), self.response({"result": "fail"})]
        with self.assertRaises(OperationFailed):
            api.cmd_login("校园网", "user", "password", False, 5)
        self.assertEqual(sess.post.call_count, 2)

    def test_logout_query_failure_does_not_claim_success(self):
        sess = self.context()
        sess.get.return_value = self.response({}, 503)
        with self.assertRaises(QueryError):
            api.cmd_logout(False, 5, "", "")
        self.assertNotIn("已离线", self.output.getvalue())
        sess.post.assert_not_called()

    def test_logout_verifies_offline(self):
        self.context()
        self.mock("ysu_api.get_online_info", side_effect=[ONLINE, ONLINE, OFFLINE])
        self.mock("ysu_api._prepare_logout_context", return_value="https://example.invalid/finish")
        post = self.mock("ysu_api._post_offline", return_value=(200, {}))
        api.cmd_logout(False, 5, "", "")
        post.assert_called_once()
        self.assertIn("已下线", self.output.getvalue())

    def test_logout_timeout_is_failure(self):
        self.context()
        self.mock("ysu_api.get_online_info", return_value=ONLINE)
        self.mock("ysu_api._prepare_logout_context", return_value="https://example.invalid/finish")
        self.mock("ysu_api._post_offline", return_value=(200, {}))
        with self.assertRaises(OperationFailed):
            api.cmd_logout(False, 0, "", "")

    def test_captcha_in_daemon_requires_interaction(self):
        sess = self.session()
        sess.get.return_value = SimpleNamespace(content=b"login", url="https://cer.ysu.edu.cn/login")
        self.mock("ysu_api._get_cas_login_url_via_clientredirect", return_value="https://cer.ysu.edu.cn/login")
        self.mock("ysu_api._extract_pwd_salt", return_value="0123456789abcdef")
        self.mock("ysu_api._check_need_captcha", return_value=True)
        self.mock("sys.stdin", new=io.StringIO())
        image = self.mock("ysu_api._probe_captcha_image")
        with self.assertRaises(InteractionRequired):
            api.cas_login(sess, "user", "password", False)
        image.assert_not_called()
        sess.post.assert_not_called()

    def test_password_spaces_are_preserved(self):
        self.mock("os.environ", new={"YSU_PASS": " pass "})
        self.assertEqual(api.build_parser().parse_args(["login"]).password, " pass ")

    def test_portal_session_comes_from_redirect_history(self):
        sess = self.session()
        sess.get.return_value = SimpleNamespace(
            history=[SimpleNamespace(url="https://auth1.ysu.edu.cn/?flowSessionId=mock-session")],
            url="https://cer.ysu.edu.cn/authserver/login", text="CAS page",
        )
        context = api.open_portal_get_session(False)
        self.assertEqual(context.session_id, "mock-session")
        self.assertEqual(context.last_url, "https://cer.ysu.edu.cn/authserver/login")

    def cas_fixture(self, rejected=False):
        sess = self.session()
        login_url = "https://cer.ysu.edu.cn/authserver/login?service=mock"
        html = b'''<form action="/authserver/login">
          <input name="username"><input name="password" type="password">
          <input name="execution" value="mock-execution">
          <input id="pwdEncryptSalt" value="0123456789abcdef">
          </form>'''
        sess.get.side_effect = [
            SimpleNamespace(url="https://auth1.ysu.edu.cn/cas-sso/clientredirect", is_redirect=True, headers={"Location": login_url}),
            SimpleNamespace(content=html, url=login_url),
            SimpleNamespace(status_code=200, headers={}, url="https://auth1.ysu.edu.cn/finish"),
        ]
        sess.post.return_value = SimpleNamespace(
            status_code=200 if rejected else 302,
            headers={} if rejected else {"Location": "https://auth1.ysu.edu.cn/finish?ticket=mock-ticket"},
            url=login_url, content=b'<span id="msg">bad credentials</span>',
        )
        self.mock("ysu_api._check_need_captcha", return_value=False)
        return sess

    def test_cas_redirect_form_encryption_and_ticket_return(self):
        sess = self.cas_fixture()
        api.cas_login(sess, "mock-user", "plain-password", False)
        data = sess.post.call_args.kwargs["data"]
        self.assertEqual(data["username"], "mock-user")
        self.assertEqual(data["execution"], "mock-execution")
        self.assertNotEqual(data["password"], "plain-password")
        self.assertNotIn("plain-password", self.output.getvalue())
        self.assertEqual(sess.get.call_args.args[0], "https://auth1.ysu.edu.cn/finish?ticket=mock-ticket")

    def test_cas_rejection_requires_manual_intervention(self):
        sess = self.cas_fixture(rejected=True)
        with self.assertRaises(InteractionRequired):
            api.cas_login(sess, "mock-user", "wrong-password", False)
        self.assertEqual(sess.post.call_count, 1)

    def test_cas_server_error_is_retryable_not_credential_rejection(self):
        sess = self.cas_fixture(rejected=True)
        sess.post.return_value.status_code = 503
        with self.assertRaises(QueryError):
            api.cas_login(sess, "mock-user", "password", False)

    def test_script_maps_operation_failure_to_exit_three(self):
        self.mock("ysu_common.online_state", side_effect=OperationFailed("mock operation failure"))
        sess = self.session()
        sess.get.return_value = SimpleNamespace(
            history=[], url="https://auth1.ysu.edu.cn/?sessionId=sid", text="", status_code=200,
            json=lambda: ONLINE,
        )
        self.mock("sys.argv", new=["ysu_api.py", "status"])
        with self.assertRaises(SystemExit) as exc:
            runpy.run_path(str(api.__file__), run_name="__main__")
        self.assertEqual(exc.exception.code, 3)


class BrowserTests(OfflineTestCase):
    def setUp(self):
        super().setUp()
        try:
            import ysu_browser
        except ImportError:
            self.skipTest("需要 browser 可选依赖")
        self.browser = ysu_browser

    def test_navigation_failure_closes_all_resources(self):
        playwright = Mock()
        browser = playwright.chromium.launch.return_value
        context = browser.new_context.return_value
        self.mock("ysu_browser.sync_playwright").return_value.start.return_value = playwright
        self.mock("ysu_browser.safe_goto", side_effect=RuntimeError("mock navigation error"))
        with self.assertRaises(RuntimeError):
            self.browser.cmd_info(False, False, False)
        context.close.assert_called_once()
        browser.close.assert_called_once()
        playwright.stop.assert_called_once()

    def test_launch_failure_stops_playwright(self):
        playwright = Mock()
        playwright.chromium.launch.side_effect = RuntimeError("missing browser")
        self.mock("ysu_browser.sync_playwright").return_value.start.return_value = playwright
        with self.assertRaises(RuntimeError):
            self.browser.cmd_status(False, False, False)
        playwright.stop.assert_called_once()

    def test_invalid_online_response_is_unknown(self):
        request = Mock()
        request.get.return_value.status = 200
        request.get.return_value.json.return_value = {"error": "expired"}
        with self.assertRaises(QueryError):
            self.browser.get_online_info(request, "sid", False)

    def browser_context(self):
        context = Mock()
        page = Mock(url="https://cer.ysu.edu.cn/authserver/login")
        self.mock("ysu_browser.open_portal_and_get_session", return_value=(SimpleNamespace(session_id="sid"), (Mock(), Mock()), context, page))
        return context

    def test_browser_login_authenticates_selects_service_and_verifies_online(self):
        self.browser_context()
        self.mock("ysu_browser.get_online_info", side_effect=[OFFLINE, ONLINE])
        self.mock("ysu_browser.get_current_node", side_effect=["authenticate", "serviceSelection"])
        ui_login = self.mock("ysu_browser.ui_cas_login")
        post = self.mock("ysu_browser.api_post_json", return_value=(200, {"result": "success"}))
        self.mock("ysu_browser.get_account_info", return_value=(200, {}))
        self.browser.cmd_login("校园网", "mock-user", "password", False, 5, False)
        ui_login.assert_called_once()
        self.assertEqual([c.args[1] for c in post.call_args_list], [self.browser.URLS.api_service_login, self.browser.URLS.api_user_online])
        self.assertIn("已在线", self.output.getvalue())

    def test_browser_authentication_remaining_on_login_requires_intervention(self):
        self.browser_context()
        self.mock("ysu_browser.get_online_info", return_value=OFFLINE)
        self.mock("ysu_browser.get_current_node", return_value="authenticate")
        self.mock("ysu_browser.ui_cas_login")
        with self.assertRaises(InteractionRequired):
            self.browser.cmd_login("校园网", "mock-user", "password", False, 5, False)

    def test_browser_login_timeout_is_failure(self):
        self.browser_context()
        self.mock("ysu_browser.get_online_info", return_value=OFFLINE)
        self.mock("ysu_browser.get_current_node", return_value="unknown")
        self.mock("ysu_browser.ui_cas_login")
        with self.assertRaises(OperationFailed):
            self.browser.cmd_login("校园网", "mock-user", "password", False, 0, False)

    def test_browser_logout_verifies_offline(self):
        self.browser_context()
        self.mock("ysu_browser.get_online_info", side_effect=[ONLINE, OFFLINE])
        self.mock("ysu_browser.api_post_json", return_value=(200, {}))
        self.browser.cmd_logout(False, 5, False)
        self.assertIn("已下线", self.output.getvalue())
