import contextlib
import io
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ONLINE = {"data": {"portalOnlineUserInfo": {"result": "success", "userName": "mock-user"}}}
OFFLINE = {"data": {"portalOnlineUserInfo": {"result": "fail", "message": "dx.failed.user.offline"}}}


class OfflineTestCase(unittest.TestCase):
    """Every test fails closed if code accidentally attempts a network connection."""
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(socket.socket, "connect", side_effect=AssertionError("测试禁止真实连接")))
        self.stack.enter_context(patch("socket.create_connection", side_effect=AssertionError("测试禁止真实连接")))
        self.stack.enter_context(patch("socket.getaddrinfo", side_effect=AssertionError("测试禁止 DNS 请求")))
        self.tmp = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.output = self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        self.errors = self.stack.enter_context(contextlib.redirect_stderr(io.StringIO()))

    def mock(self, target, **kwargs):
        return self.stack.enter_context(patch(target, **kwargs))
