import hashlib
import io
import os
import tarfile
import threading
import unittest
import zipfile
from unittest.mock import patch

from helpers import OfflineTestCase
from ysu_net.auth import node_runtime


def fake_archive(platform):
    payload = b"#!node-binary"
    buffer = io.BytesIO()
    if platform == "win32":
        with zipfile.ZipFile(buffer, "w") as bundle:
            bundle.writestr(f"node-{node_runtime.VERSION}-win-x64/node.exe", payload)
            bundle.writestr(f"node-{node_runtime.VERSION}-win-x64/node_modules/x/node.exe", b"decoy")
    else:
        with tarfile.open(fileobj=buffer, mode="w:xz") as bundle:
            info = tarfile.TarInfo(f"node-{node_runtime.VERSION}-linux-x64/bin/node")
            info.size = len(payload)
            bundle.addfile(info, io.BytesIO(payload))
    return buffer.getvalue(), payload


class NodeRuntimeTests(OfflineTestCase):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.tmp),
                                                         "APPDATA": str(self.tmp)}))
        os.environ.pop(node_runtime.ENV, None)
        self.mock("ysu_net.auth.node_runtime.bundled_node", return_value=None)
        self.mock("ysu_net.auth.node_runtime._system_node", return_value=None)

    def install_with(self, archive, digest, *, fail_first=False):
        name = node_runtime.ARCHIVES[node_runtime.sys.platform][0]
        entries = {node_runtime.sys.platform: (name, digest, len(archive))}
        calls = []

        def fetch(url, size, progress, cancel):
            calls.append(url)
            if fail_first and len(calls) == 1:
                raise ConnectionError("mirror down")
            return archive
        with patch.dict(node_runtime.ARCHIVES, entries), patch.object(node_runtime, "_fetch", fetch):
            return node_runtime.install(mirrors=("https://a", "https://b")), calls

    @unittest.skipUnless(node_runtime.supported(), "平台不支持下载")
    def test_install_verifies_and_falls_back_to_next_mirror(self):
        archive, payload = fake_archive(node_runtime.sys.platform)
        path, calls = self.install_with(archive, hashlib.sha256(archive).hexdigest(), fail_first=True)
        self.assertEqual(path.read_bytes(), payload)
        self.assertEqual(len(calls), 2)
        self.assertEqual(node_runtime.find_node(), path)
        self.assertTrue(node_runtime.configure())
        self.assertEqual(os.environ[node_runtime.ENV], str(path))

    @unittest.skipUnless(node_runtime.supported(), "平台不支持下载")
    def test_checksum_mismatch_installs_nothing(self):
        archive, _ = fake_archive(node_runtime.sys.platform)
        with self.assertRaisesRegex(RuntimeError, "校验失败"):
            self.install_with(archive, "0" * 64)
        self.assertIsNone(node_runtime.find_node())
        self.assertFalse(node_runtime.configure())

    def test_cancel_stops_download(self):
        cancel = threading.Event()
        cancel.set()

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def raise_for_status(self):
                pass

            def iter_content(self, _size):
                yield b"x"
        with patch("requests.get", return_value=Response()):
            with self.assertRaises(InterruptedError):
                node_runtime._fetch("https://a", 10, None, cancel)

    def test_override_and_system_node(self):
        exe = self.tmp / "node"
        exe.write_text("")
        with patch.dict(os.environ, {node_runtime.ENV: str(exe)}):
            self.assertEqual(node_runtime.find_node(), exe)
        system = self.tmp / "system-node"
        with patch.object(node_runtime, "_system_node", return_value=system):
            self.assertEqual(node_runtime.find_node(), system)

    def test_bundled_node_is_left_to_playwright(self):
        bundled = self.tmp / "driver-node"
        bundled.write_text("")
        with patch.object(node_runtime, "bundled_node", return_value=bundled):
            self.assertTrue(node_runtime.configure())
        self.assertNotIn(node_runtime.ENV, os.environ)


if __name__ == "__main__":
    unittest.main()
