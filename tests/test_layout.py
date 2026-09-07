"""Exercise installed entry points without relying on the checkout as cwd."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import Mock

from ysu_net.manager import backend, install
from ysu_net.manager.config import Config
from tests.helpers import OfflineTestCase


class LayoutTests(OfflineTestCase):
    def invoke(self, *command):
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        return subprocess.run(
            command, cwd=self.tmp, env=env, text=True,
            capture_output=True, timeout=15,
        )

    def assert_help(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("usage:", result.stdout)

    def test_module_entry_outside_checkout(self):
        self.assert_help(self.invoke(sys.executable, "-m", "ysu_net", "--help"))

    def test_console_entry_outside_checkout(self):
        command = Path(sys.executable).parent / "ysu"
        self.assertTrue(command.is_file())
        self.assert_help(self.invoke(str(command), "--help"))

    def test_api_module_outside_checkout(self):
        self.assert_help(self.invoke(sys.executable, "-m", "ysu_net.auth.api", "--help"))

    def test_browser_module_outside_checkout(self):
        if importlib.util.find_spec("playwright") is None:
            self.skipTest("需要 browser 可选依赖")
        self.assert_help(self.invoke(sys.executable, "-m", "ysu_net.auth.browser", "--help"))

    def test_installed_wrapper_outside_checkout(self):
        command = self.tmp / "bin/ysu"
        command.parent.mkdir()
        command.write_text(install.wrapper("user"))
        command.chmod(0o755)
        self.assert_help(self.invoke(str(command), "--help"))

    def test_backend_spawns_importable_module(self):
        process = Mock(returncode=0)
        process.communicate.return_value = ("online\n", "")
        popen = self.mock("ysu_net.manager.backend.subprocess.Popen", return_value=process)
        result = backend.run_backend(Config(), "status")
        self.assertEqual(result.code, 0)
        self.assertEqual(popen.call_args.args[0], [sys.executable, "-m", "ysu_net.auth.api", "status"])
