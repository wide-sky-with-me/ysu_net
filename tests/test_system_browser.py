import os
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from helpers import OfflineTestCase
from ysu_net.auth import system_browser


class FindSystemBrowserTests(OfflineTestCase):
    def test_override_must_exist(self):
        exe = self.tmp / "msedge.exe"
        exe.write_text("")
        with patch.dict(os.environ, {system_browser.ENV: str(exe)}):
            self.assertEqual(system_browser.find_system_browser(), ("自定义浏览器", exe))
        with patch.dict(os.environ, {system_browser.ENV: str(self.tmp / "missing")}):
            self.assertIsNone(system_browser.find_system_browser())

    def test_windows_checks_edge_before_chrome(self):
        env = {"ProgramFiles(x86)": "PF86", "LOCALAPPDATA": "LAD"}
        with patch.dict(os.environ, env, clear=True):
            labels = [label for label, _ in system_browser._windows_candidates()]
        self.assertEqual(labels[:2], ["Microsoft Edge", "Microsoft Edge"])
        self.assertLess(labels.index("Microsoft Edge"), labels.index("Google Chrome"))

    @unittest.skipIf(os.name == "nt", "POSIX lookup")
    def test_snap_browsers_are_skipped(self):
        with patch.dict(os.environ, {}, clear=False) as env:
            env.pop(system_browser.ENV, None)
            with patch.object(system_browser.shutil, "which", return_value="/snap/bin/chromium"):
                self.assertIsNone(system_browser.find_system_browser())


class LaunchFallbackTests(OfflineTestCase):
    def setUp(self):
        super().setUp()
        try:
            from ysu_net.auth import browser
        except ImportError:
            self.skipTest("需要 browser 可选依赖")
        self.browser = browser
        os.environ.pop(system_browser.ENV, None)

    def test_missing_bundled_chromium_falls_back_to_system_browser(self):
        p = Mock()
        p.chromium.launch.side_effect = [RuntimeError("Executable doesn't exist at /x"), "launched"]
        with patch.object(system_browser, "find_system_browser", return_value=("Google Chrome", Path("/usr/bin/chrome"))):
            self.assertEqual(self.browser._launch_chromium(p, headless=True, debug=False), "launched")
        self.assertEqual(p.chromium.launch.call_args.kwargs["executable_path"], str(Path("/usr/bin/chrome")))

    def test_no_browser_gives_actionable_error(self):
        p = Mock()
        p.chromium.launch.side_effect = RuntimeError("Executable doesn't exist at /x")
        with patch.object(system_browser, "find_system_browser", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "Edge 或 Google Chrome"):
                self.browser._launch_chromium(p, headless=True, debug=False)

    def test_other_launch_errors_are_not_masked(self):
        p = Mock()
        p.chromium.launch.side_effect = RuntimeError("sandbox failure")
        with patch.object(system_browser, "find_system_browser") as finder:
            with self.assertRaisesRegex(RuntimeError, "sandbox"):
                self.browser._launch_chromium(p, headless=True, debug=False)
        finder.assert_not_called()


if __name__ == "__main__":
    unittest.main()
