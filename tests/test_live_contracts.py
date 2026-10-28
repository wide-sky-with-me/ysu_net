"""Synthetic contracts from the 123 trace, shared with the Rust authentication library."""
import io
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from tests.helpers import OfflineTestCase, OFFLINE
from ysu_net.auth import api
from ysu_net.auth.common import check_action, InteractionRequired, OperationFailed


def cases(name):
    fixture = json.loads((Path(__file__).parent / "fixtures" / name).read_text())
    assert fixture["version"] == 1
    return fixture["cases"]


class LiveContractTests(OfflineTestCase):
    def response(self, payload):
        return SimpleNamespace(status_code=200, json=lambda: payload)

    def test_password_form_captcha_scope_and_attribute_order(self):
        for case in cases("cas-login-methods.json"):
            with self.subTest(case=case["id"]):
                self.assertEqual(api._page_says_captcha_visible(case["html"]), case["captcha"])

    def test_visible_password_challenge_stops_before_credentials_when_api_says_false(self):
        case = next(case for case in cases("cas-login-methods.json") if case["id"] == "password-visible")
        session = Mock()
        page = "https://cer.ysu.edu.cn/authserver/login?service=fixture"
        session.get.return_value = SimpleNamespace(content=case["html"].encode(), url=page)
        self.mock("ysu_net.auth.api._get_cas_login_url_via_clientredirect", return_value=page)
        self.mock("ysu_net.auth.api._check_need_captcha", return_value=False)
        with patch("sys.stdin", io.StringIO("")), self.assertRaises(InteractionRequired):
            api.cas_login(session, "fixture-user", "fixture-password", False)
        session.post.assert_not_called()

    def test_service_action_envelopes_and_no_activation_after_rejection(self):
        for case in cases("portal-action-results.json"):
            with self.subTest(case=case["id"]):
                expected = case["code"]
                if expected == 0:
                    check_action(200, case["payload"], "serviceLogin")
                    continue
                error = InteractionRequired if expected == 4 else OperationFailed
                with self.assertRaises(error):
                    check_action(200, case["payload"], "serviceLogin")
                session = Mock()
                session.get.return_value = self.response(OFFLINE)
                session.post.side_effect = [
                    self.response({"data": {"currentNodePath": "serviceSelection"}}),
                    self.response(case["payload"]),
                ]
                context = SimpleNamespace(sess=session, session_id="fixture-session", last_url="https://portal.fixture.invalid/")
                with patch("ysu_net.auth.api.open_portal_get_session", return_value=context), \
                        patch("ysu_net.auth.api._portal_api_headers", return_value={}):
                    with self.assertRaises(error):
                        api.cmd_login("校园网", "fixture-user", "fixture-password", False, 5)
                self.assertEqual(session.post.call_count, 2)
                self.assertFalse(any("userOnline" in str(call) for call in session.post.call_args_list))
