import os
import unittest
from unittest.mock import patch

from helpers import OfflineTestCase
from ysu_net.auth import node_runtime


class NodeRuntimeTests(OfflineTestCase):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.tmp),
                                                         "APPDATA": str(self.tmp)}))
        os.environ.pop(node_runtime.ENV, None)
        self.mock("ysu_net.auth.node_runtime.bundled_node", return_value=None)
        self.mock("ysu_net.auth.node_runtime._system_node", return_value=None)

    def test_override_and_system_node(self):
        exe = self.tmp / "node"
        exe.write_text("")
        with patch.dict(os.environ, {node_runtime.ENV: str(exe)}):
            self.assertEqual(node_runtime.find_node(), exe)
        system = self.tmp / "system-node"
        with patch.object(node_runtime, "_system_node", return_value=system):
            self.assertEqual(node_runtime.find_node(), system)

    def test_missing_override_is_not_replaced_by_other_runtimes(self):
        system = self.tmp / "system-node"
        with patch.dict(os.environ, {node_runtime.ENV: str(self.tmp / "missing")}), \
                patch.object(node_runtime, "_system_node", return_value=system):
            self.assertIsNone(node_runtime.find_node())

    def test_bundled_node_is_left_to_playwright(self):
        bundled = self.tmp / "driver-node"
        bundled.write_text("")
        with patch.object(node_runtime, "bundled_node", return_value=bundled):
            self.assertTrue(node_runtime.configure())
        self.assertNotIn(node_runtime.ENV, os.environ)

    def test_previously_downloaded_runtime_is_still_used(self):
        node = node_runtime.downloaded_node()
        node.parent.mkdir(parents=True)
        node.write_text("")
        self.assertTrue(node_runtime.configure())
        self.assertEqual(os.environ[node_runtime.ENV], str(node))

    def test_no_runtime_reports_unavailable(self):
        self.assertFalse(node_runtime.configure())
        self.assertNotIn(node_runtime.ENV, os.environ)


if __name__ == "__main__":
    unittest.main()
