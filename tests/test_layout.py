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
        env.pop("PYTHONSAFEPATH", None)
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

    def assert_installed_wrappers_help(self):
        for scope in ("user", "system"):
            for name, alias in (("ysu", None), ("ysuon", "on"), ("ysuoff", "off")):
                with self.subTest(scope=scope, command=name):
                    command = self.tmp / f"bin-{scope}" / name
                    command.parent.mkdir(exist_ok=True)
                    command.write_text(install.wrapper(scope, alias))
                    command.chmod(0o755)
                    result = self.invoke(str(command), "--help")
                    self.assert_help(result)
                    self.assertIn(f"usage: ysu{(' ' + alias) if alias else ''} ", result.stdout)

    def test_installed_wrapper_outside_checkout(self):
        self.assert_installed_wrappers_help()

    def assert_cwd_shadow_ignored(self, *names):
        marker = self.tmp / "shadow-executed"
        source = (
            "from pathlib import Path\n"
            "Path('shadow-executed').write_text('unexpected cwd import')\n"
            "raise RuntimeError('cwd ysu_net shadow executed')\n"
        )
        for name in names:
            path = self.tmp / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source)
        self.assert_installed_wrappers_help()
        self.assertFalse(marker.exists())
        for name in names:
            self.assertEqual((self.tmp / name).read_text(), source)

    def test_installed_wrappers_ignore_cwd_module(self):
        self.assert_cwd_shadow_ignored("ysu_net.py")

    def test_installed_wrappers_ignore_cwd_package(self):
        self.assert_cwd_shadow_ignored("ysu_net/__init__.py", "ysu_net/__main__.py")

    def test_backend_spawns_importable_module(self):
        process = Mock(returncode=0)
        process.communicate.return_value = ("online\n", "")
        popen = self.mock("ysu_net.manager.backend.subprocess.Popen", return_value=process)
        result = backend.run_backend(Config(), "status")
        self.assertEqual(result.code, 0)
        self.assertEqual(popen.call_args.args[0], [sys.executable, "-m", "ysu_net.auth.api", "status"])
