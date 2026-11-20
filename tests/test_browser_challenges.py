"""CAS browser behavior on an in-memory form, with no network transport."""
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from ysu_net.auth.common import InteractionRequired, QueryError
from ysu_net.auth.system_browser import find_system_browser


class BrowserChallengeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from ysu_net.auth import browser
        except ModuleNotFoundError as exc:
            if exc.name == "playwright":
                raise unittest.SkipTest("browser extra not installed") from exc
            raise
        driver = browser._playwright().start()
        cls.addClassCleanup(driver.stop)
        if not Path(driver.chromium.executable_path).is_file() and not find_system_browser():
            raise unittest.SkipTest("no Chromium runtime installed")
        chromium = browser._launch_chromium(driver, headless=True, debug=False)
        cls.addClassCleanup(chromium.close)
        cls.chromium = chromium
        cls.backend = browser

    def setUp(self):
        self.context = self.chromium.new_context(offline=True, service_workers="block")
        self.addCleanup(self.context.close)
        self.page = self.context.new_page()
        response = Mock(status=200)
        response.json.return_value = False
        self.response = response
        self.transport = self.enterContext(patch.object(type(self.context.request), "get", return_value=response))

    def form(self, extra=""):
        self.page.set_content('<form onsubmit="window.submits++; event.preventDefault()">'
                              '<input name="username"><input type="password" name="password">'
                              '<input type="submit">' + extra + '</form><script>window.submits=0</script>')

    def login(self):
        self.backend.ui_cas_login(self.page, "user", "password", False)

    def test_frame_challenge_stops_before_credentials_or_probe(self):
        self.form('<iframe srcdoc="<input name=otp>"></iframe>')
        with self.assertRaises(InteractionRequired):
            self.login()
        self.assertEqual(self.page.locator('[name=username]').input_value(), '')
        self.assertEqual(self.page.evaluate('window.submits'), 0)
        self.transport.assert_not_called()

    def test_preflight_stops_without_filling_credentials(self):
        for payload, error in (({"needCaptcha": False, "data": {"isNeed": True}}, InteractionRequired),
                               ({"unexpected": 200}, QueryError)):
            with self.subTest(payload=payload):
                self.form()
                self.response.json.return_value = payload
                with self.assertRaises(error):
                    self.login()
                self.assertEqual(self.page.locator('[name=password]').input_value(), '')
                self.assertEqual(self.page.evaluate('window.submits'), 0)

    def test_text_only_challenge_stops_before_probe(self):
        self.form('<p>验证码错误</p>')
        with self.assertRaises(InteractionRequired):
            self.login()
        self.assertEqual(self.page.evaluate('window.submits'), 0)
        self.transport.assert_not_called()

    def test_html_challenge_in_non_success_preflight_stops_with_code_four(self):
        self.form()
        self.response.status = 403
        self.response.json.side_effect = ValueError("not JSON")
        self.response.text.return_value = '<p>请输入验证码</p>'
        with self.assertRaises(InteractionRequired):
            self.login()
        self.assertEqual(self.page.evaluate('window.submits'), 0)

    def test_challenge_revealed_by_filling_stops_submit(self):
        self.form('<input hidden name=captcha>')
        self.page.locator('[name=password]').evaluate("e=>e.oninput=()=>document.querySelector('[name=captcha]').hidden=false")
        with self.assertRaises(InteractionRequired):
            self.login()
        self.assertEqual(self.page.evaluate('window.submits'), 0)

    def test_hidden_prefilled_answer_is_not_submitted(self):
        self.form('<input hidden name=captcha value="fixture">')
        with self.assertRaises(InteractionRequired):
            self.login()
        self.assertEqual(self.page.evaluate('window.submits'), 0)

    def test_post_login_challenge_is_terminal_without_a_retry(self):
        self.form('<input hidden name=smscode>')
        self.page.evaluate("document.forms[0].addEventListener('submit', ()=>document.querySelector('[name=smscode]').hidden=false)")
        with self.assertRaises(InteractionRequired):
            self.login()
        self.assertEqual(self.page.evaluate('window.submits'), 1)

    def test_hidden_empty_challenge_allows_normal_password_login(self):
        self.form('<div id="captchaDiv" hidden><input name=captcha></div>')
        self.login()
        self.assertEqual(self.page.locator('[name=password]').input_value(), 'password')
        self.assertEqual(self.page.evaluate('window.submits'), 1)
