"""Offline CAS transcripts: only the listed requests may leave the authentication flow."""
import os
from unittest.mock import Mock, patch
from urllib.parse import urlsplit

import requests

from tests.helpers import OfflineTestCase
from ysu_net.auth import api
from ysu_net.auth.common import InteractionRequired, QueryError


LOGIN = api.URLS.cas_host + "/authserver/login?service=fixture"
CALLBACK = api.URLS.base + "/portal/finish"
FORM = ('<form action="/authserver/login"><input name="username"><input name="password">'
        '<input id="pwdEncryptSalt" value="0123456789abcdef">{}</form>')
CHALLENGE = '<div id="captchaDiv"><input name="captcha"></div>'
ENTRY = '/cas-sso/clientredirect'
PAGE = '/authserver/login'
CHECK = '/authserver/checkNeedCaptcha.htl'


def reply(body="", status=200, location=None):
    r = requests.Response()
    r.status_code = status
    r._content = body.encode()
    r.encoding = "utf-8"
    if location:
        r.headers["Location"] = location
    return r


class CaptchaChallengeTests(OfflineTestCase):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {"XDG_CACHE_HOME": str(self.tmp)}))
        self.sess = Mock(spec=requests.Session)
        self.sess.cookies = requests.cookies.RequestsCookieJar()

    def replay(self, *steps, error=InteractionRequired):
        expected = [("GET", ENTRY, reply(status=302, location=LOGIN)), *steps]

        def send(method, url, **kwargs):
            path = urlsplit(url).path
            self.assertTrue(expected, f"unexpected {method} {path}")
            want_method, want_path, response = expected.pop(0)
            self.assertEqual((method, path), (want_method, want_path))
            response.url = url
            return response

        self.sess.get.side_effect = lambda url, **kw: send("GET", url, **kw)
        self.sess.post.side_effect = lambda url, **kw: send("POST", url, **kw)
        if error:
            with self.assertRaises(error) as stopped:
                api.cas_login(self.sess, "fixture-user", "fixture-password", False)
            self.assertEqual(stopped.exception.exit_code, 4 if error is InteractionRequired else 2)
        else:
            api.cas_login(self.sess, "fixture-user", "fixture-password", False)
        self.assertFalse(expected, "CAS flow stopped before the expected response")

    def test_positive_preflight_stops_without_image_or_password(self):
        for tty, payload in ((True, '{"isNeed":true}'), (False, '{"data":{"needCaptcha":1}}')):
            with self.subTest(tty=tty), patch("sys.stdin.isatty", return_value=tty):
                self.replay(("GET", PAGE, reply(FORM.format(""))), ("GET", CHECK, reply(payload)))

    def test_initial_challenge_stops_before_preflight(self):
        for marker in (CHALLENGE, '<input name="captcha">', '<span>请输入验证码</span>',
                       '<input name="otp">', '<input name="smsCode">',
                       '<input name="secondFactor" autocomplete="one-time-code">'):
            with self.subTest(marker=marker):
                self.replay(("GET", PAGE, reply(FORM.format(marker))))

    def test_unknown_preflight_is_not_permission_to_submit(self):
        for result in (reply("not JSON"), reply("{}"), reply("false", 503)):
            with self.subTest(body=result.text, status=result.status_code):
                self.replay(("GET", PAGE, reply(FORM.format(""))), ("GET", CHECK, result), error=QueryError)

    def test_challenge_or_throttling_in_preflight_response(self):
        for result in (reply(CHALLENGE), reply(status=429), reply('{"needCaptcha":true}', 403)):
            with self.subTest(status=result.status_code):
                self.replay(("GET", PAGE, reply(FORM.format(""))), ("GET", CHECK, result))

    def test_challenge_after_password_stops_without_retry(self):
        for result in (reply(FORM.format(CHALLENGE)), reply('<span id="msg">无效的验证码</span>'),
                       reply(CHALLENGE, 302, CALLBACK)):
            with self.subTest(body=result.text, status=result.status_code):
                self.replay(("GET", PAGE, reply(FORM.format(""))), ("GET", CHECK, reply("false")),
                            ("POST", PAGE, result))

    def test_callback_challenge_is_not_success(self):
        self.replay(("GET", PAGE, reply(FORM.format(""))), ("GET", CHECK, reply("false")),
                    ("POST", PAGE, reply(status=302, location=CALLBACK)),
                    ("GET", "/portal/finish", reply(CHALLENGE)))

    def test_hidden_challenge_never_contributes_an_answer_to_normal_login(self):
        marker = ('<div hidden id="captchaDiv"><input name="captcha" value="stale"></div>'
                  '<input type="hidden" name="CAPTCHA" value="also-stale">'
                  '<input type="hidden" name="otp" value="stale-otp">'
                  '<input type="hidden" name="smsCode" value="stale-sms">'
                  '<input type="hidden" name="other" autocomplete=one-time-code value="stale-code">')
        self.replay(("GET", PAGE, reply(FORM.format(marker))), ("GET", CHECK, reply('{"data":0}')),
                    ("POST", PAGE, reply(status=302, location=CALLBACK)),
                    ("GET", "/portal/finish", reply("OK")), error=None)
        fields = self.sess.post.call_args.kwargs['data']
        self.assertTrue({'captcha', 'otp', 'smscode', 'other'}.isdisjoint(key.casefold() for key in fields))
        self.assertEqual(fields['username'], 'fixture-user')
        self.assertNotEqual(fields['password'], 'fixture-password')
