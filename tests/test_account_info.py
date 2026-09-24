import copy
import json
from types import SimpleNamespace
from unittest.mock import patch

from helpers import ONLINE, OFFLINE, OfflineTestCase
from ysu_net.auth import api, browser
from ysu_net.auth.account import format_account_info, summarize_account_payload
from ysu_net.manager import cli
from ysu_net.manager.backend import Result
from ysu_net.manager.config import Config, save_config


class AccountInfoTests(OfflineTestCase):
    def payload(self, content=0):
        return {'data': {'name': 'sample', 'accountInfo': [
            {'title': '剩余流量', 'content': content, 'link': 'https://example.invalid/?token=private'},
            {'title': '套餐&余额', 'content': 0},
        ]}}

    def test_double_nested_response(self):
        payload = {'data': self.payload()}
        for backend in (api, browser):
            with self.subTest(backend=backend.__name__):
                self.assertEqual(backend.summarize_account_payload(payload)['name'], 'sample')
                self.assertIn('剩余流量：0', backend.format_info(ONLINE, payload))

    def test_outer_null_does_not_hide_nested_items(self):
        payload = {'data': {'accountInfo': None, 'data': self.payload()['data']}}
        self.assertIn('剩余流量', summarize_account_payload(payload)['items_map'])

    def test_numeric_zero_is_present(self):
        output = format_account_info(ONLINE, self.payload())
        self.assertIn('剩余流量：0', output)
        self.assertIn('套餐与余额：0', output)
        self.assertNotIn('门户未提供', output)
        self.assertNotIn('private', output)

    def test_units_are_not_guessed_or_converted(self):
        self.assertIn('剩余流量：1024 MB', format_account_info(ONLINE, self.payload('1024 MB')))

    def test_missing_and_empty_quota_are_not_zero(self):
        for value in (None, '', '  ', {}, [], False):
            with self.subTest(value=value):
                self.assertIn('剩余流量：门户未提供', format_account_info(ONLINE, self.payload(value)))

    def test_portal_html_and_terminal_controls_are_cleaned(self):
        value = '<b>12</b>&nbsp;GB<script>hidden</script>\x1b[31m\x1b]8;;https://secret.invalid\x07'
        output = format_account_info(ONLINE, self.payload(value))
        self.assertIn('剩余流量：12 GB', output)
        for hidden in ('<b>', 'hidden', '\x1b', 'secret.invalid'):
            self.assertNotIn(hidden, output)

    def test_whitespace_is_preserved_as_separator(self):
        self.assertIn('剩余流量：12 GB', format_account_info(ONLINE, self.payload('12\nGB')))

    def test_no_session_identifier_in_default_output(self):
        online = copy.deepcopy(ONLINE)
        online['data']['portalOnlineUserInfo']['userIndex'] = 'private-session'
        self.assertNotIn('private-session', format_account_info(online, self.payload()))

    def test_actual_service_has_precedence(self):
        payload = self.payload()
        payload['data']['service'] = 'outdated-package'
        self.assertIn('当前服务：校园网', format_account_info(ONLINE, payload))
        self.assertNotIn('outdated-package', format_account_info(ONLINE, payload))

    def test_invalid_response_is_unknown_not_offline(self):
        self.assertIn('未知', format_account_info({}, None))
        self.assertIn('离线', format_account_info(OFFLINE, None))

    def test_malformed_items_do_not_crash(self):
        payload = {'data': {'accountInfo': [None, 2, {}, {'title': '', 'content': 'ignored'}]}}
        self.assertIn('剩余流量：门户未提供', format_account_info(ONLINE, payload))

    def test_live_shape_without_quota_keeps_device_info(self):
        payload = {'data': {'accountInfo': [{'title': '在线设备', 'content': '1 台'},
                                          {'title': '业务明细', 'content': '', 'link': 'https://example.invalid/'}]}}
        result = format_account_info(ONLINE, payload)
        self.assertIn('在线设备：1 台', result)
        self.assertIn('剩余流量：门户未提供', result)


class AccountDoctorCliTests(OfflineTestCase):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict('os.environ', {}, clear=True))
        self.path = self.tmp/'config.json'
        self.unit = self.tmp/'ysu-net.service'
        save_config(self.path, Config(username='mock-user', password='test-secret'))
        self.mock('ysu_net.manager.cli.config_path', return_value=self.path)
        self.mock('ysu_net.manager.cli.unit_path', return_value=self.unit)
        self.mock('ysu_net.manager.cli.shutil.which', return_value='/usr/bin/systemctl')
        self.mock('ysu_net.manager.cli.importlib.util.find_spec', return_value=object())
        self.control = self.mock('ysu_net.manager.cli.systemctl')
        self.process = self.mock('ysu_net.manager.cli.subprocess.run', return_value=SimpleNamespace(returncode=0, stdout='yes\n'))
        self.runner = self.mock('ysu_net.manager.cli.run_backend', return_value=Result(0, json.dumps({'online': ONLINE})))

    def test_local_doctor_never_queries_network(self):
        self.assertEqual(cli.main(['doctor']), 0)
        self.runner.assert_not_called()

    def test_network_doctor_validates_service_without_authenticating(self):
        self.assertEqual(cli.main(['doctor', '--network']), 0)
        self.assertIn('实际服务：校园网', self.output.getvalue())
        self.assertEqual(self.runner.call_args.args[1], 'status')
        self.assertTrue(self.runner.call_args.kwargs['raw'])
        self.runner.assert_called_once()

    def test_network_doctor_flags_mismatch(self):
        online = copy.deepcopy(ONLINE)
        online['data']['portalOnlineUserInfo']['service'] = '中国移动'
        self.runner.return_value = Result(0, json.dumps({'online': online}))
        self.assertEqual(cli.main(['doctor', '--network']), 2)
        self.assertIn('ysu switch 校园网', self.output.getvalue())

    def test_network_doctor_rejects_invalid_status_payload(self):
        self.runner.return_value = Result(0, 'not-json')
        self.assertEqual(cli.main(['doctor', '--network']), 2)

    def test_network_doctor_offline_is_reachable(self):
        self.runner.return_value = Result(1)
        self.assertEqual(cli.main(['doctor', '--network']), 0)
        self.assertIn('离线（门户可达）', self.output.getvalue())
        self.runner.assert_called_once()

    def test_dns_guidance_without_secret(self):
        self.runner.return_value = Result(2, reason='dns')
        self.assertEqual(cli.main(['doctor', '--network']), 2)
        self.assertIn('DNS', self.output.getvalue())
        self.assertNotIn('test-secret', self.output.getvalue())

    def test_failed_background_service_is_unhealthy(self):
        self.unit.touch()
        self.control.side_effect = [SimpleNamespace(stdout='failed\n'), SimpleNamespace(stdout='disabled\n')]
        self.assertEqual(cli.main(['doctor']), 2)
        self.assertIn('ysu logs', self.output.getvalue())

    def test_enabled_service_without_linger_has_guidance(self):
        self.unit.touch()
        self.control.side_effect = [SimpleNamespace(stdout='active\n'), SimpleNamespace(stdout='enabled\n')]
        self.process.return_value = SimpleNamespace(returncode=0, stdout='no\n')
        self.assertEqual(cli.main(['doctor']), 2)
        self.assertIn('enable-linger', self.output.getvalue())
        self.assertEqual(self.process.call_args.kwargs['timeout'], 5)

    def test_enabled_lingering_service_is_healthy(self):
        self.unit.touch()
        self.control.side_effect = [SimpleNamespace(stdout='active\n'), SimpleNamespace(stdout='enabled\n')]
        self.assertEqual(cli.main(['doctor']), 0)

    def test_account_menu_entry(self):
        self.mock('sys.stdin.isatty', return_value=True)
        self.mock('builtins.input', side_effect=['13', '0'])
        command = self.mock('ysu_net.manager.cli.main', return_value=0)
        self.assertEqual(cli.menu(cli.parser().parse_args(['menu']), self.path), 0)
        self.assertEqual(command.call_args.args[0][-1], 'info')
        self.assertIn('账户与剩余流量', self.output.getvalue())

    def test_network_doctor_menu_entry(self):
        self.mock('sys.stdin.isatty', return_value=True)
        self.mock('builtins.input', side_effect=['14', '0'])
        command = self.mock('ysu_net.manager.cli.main', return_value=0)
        cli.menu(cli.parser().parse_args(['menu']), self.path)
        self.assertEqual(command.call_args.args[0][-2:], ['doctor', '--network'])

    def test_raw_info_remains_unchanged(self):
        raw = {'online': ONLINE, 'account': {'data': {'accountInfo': []}}}
        self.runner.return_value = Result(0, json.dumps(raw))
        self.assertEqual(cli.main(['info', '--raw']), 0)
        self.assertEqual(json.loads(self.output.getvalue()), raw)
