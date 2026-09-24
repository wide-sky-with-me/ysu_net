from unittest.mock import patch

from helpers import OfflineTestCase
from ysu_net.manager import cli, ui
from ysu_net.manager.config import Config


class MenuHelpTests(OfflineTestCase):
    def setUp(self):
        super().setUp()
        self.mock('sys.stdin.isatty', return_value=True)
        self.mock('ysu_net.manager.cli.load_config', return_value=Config())
        self.dispatch = self.mock('ysu_net.manager.cli.main')
        self.backend = self.mock('ysu_net.manager.cli.run_backend')
        self.service = self.mock('ysu_net.manager.cli.service_action')
        self.save = self.mock('ysu_net.manager.cli.update_config')

    def test_all_help_shortcuts_are_read_only(self):
        for key in ('15', 'h', '?'):
            with self.subTest(key=key):
                with patch('builtins.input', side_effect=[key, '0']):
                    self.assertEqual(cli.menu(cli.parser().parse_args(['menu']), self.tmp/'config.json'), 0)
        self.dispatch.assert_not_called()
        self.backend.assert_not_called()
        self.service.assert_not_called()
        self.save.assert_not_called()
        self.assertFalse((self.tmp/'config.json').exists())

    def test_help_covers_every_option_and_important_effects(self):
        ui.menu_help()
        text = self.output.getvalue()
        for number in range(16):
            self.assertRegex(text, rf'(?m)^  {number} ')
        for phrase in ('远程 SSH 可能断开', '不立即切换当前连接', '不会停止当前守护',
                       '已启动的后台服务会继续运行', '不代表零或不限量'):
            self.assertIn(phrase, text)

    def test_help_returns_to_menu(self):
        with patch('builtins.input', side_effect=['15', '', '0']):
            self.assertEqual(cli.menu(cli.parser().parse_args(['menu']), self.tmp/'config.json'), 0)
        self.assertEqual(self.output.getvalue().count('YSU · 燕山大学校园网'), 2)
        self.dispatch.assert_not_called()
