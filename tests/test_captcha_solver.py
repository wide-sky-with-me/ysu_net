import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest import mock

from ysu_net.auth import captcha


def _serve(payload, status=200):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}")
            assert "image" in body
            raw = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, *_args):
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_port}/"


class CaptchaSolverTests(unittest.TestCase):
    def setUp(self):
        self._patches = [
            mock.patch.object(captcha.shutil, "which", lambda _name: None),
            mock.patch.dict("os.environ", {}, clear=False),
            mock.patch.object(captcha.sys, "stdin", mock.Mock(isatty=lambda: False)),
        ]
        for patch in self._patches:
            patch.start()
        for key in (captcha.ENV_BACKEND, captcha.ENV_REMOTE):
            mock.patch.dict("os.environ", {key: ""}).start()

    def tearDown(self):
        mock.patch.stopall()

    def test_auto_without_any_backend_returns_none(self):
        self.assertIsNone(captcha.solve(b"not-an-image"))

    def test_remote_backend_reads_text(self):
        server, url = _serve({"text": "aB3d"})
        try:
            with mock.patch.dict("os.environ", {captcha.ENV_BACKEND: "remote", captcha.ENV_REMOTE: url}):
                solved = captcha.solve(b"image-bytes")
            self.assertIsNotNone(solved)
            self.assertEqual(solved.text, "aB3d")
            self.assertEqual(solved.backend, "remote")
        finally:
            server.shutdown()
            server.server_close()

    def test_remote_wrong_length_falls_through(self):
        server, url = _serve({"text": "ab"})
        try:
            with mock.patch.dict("os.environ", {captcha.ENV_BACKEND: "auto", captcha.ENV_REMOTE: url}):
                self.assertIsNone(captcha.solve(b"image-bytes"))
        finally:
            server.shutdown()
            server.server_close()

    def test_remote_error_status_is_ignored(self):
        server, url = _serve({"text": "aB3d"}, status=503)
        try:
            with mock.patch.dict("os.environ", {captcha.ENV_BACKEND: "remote", captcha.ENV_REMOTE: url}):
                self.assertIsNone(captcha.solve(b"image-bytes"))
        finally:
            server.shutdown()
            server.server_close()

    def test_explicit_remote_without_url_returns_none(self):
        with mock.patch.dict("os.environ", {captcha.ENV_BACKEND: "remote"}):
            self.assertIsNone(captcha.solve(b"image-bytes"))

    def test_manual_is_skipped_without_a_terminal(self):
        with mock.patch.dict("os.environ", {captcha.ENV_BACKEND: "manual"}):
            self.assertIsNone(captcha.solve(b"image-bytes"))

    def test_non_alnum_characters_are_dropped(self):
        server, url = _serve({"text": " aB-3d "})
        try:
            with mock.patch.dict("os.environ", {captcha.ENV_BACKEND: "remote", captcha.ENV_REMOTE: url}):
                solved = captcha.solve(b"image-bytes")
            self.assertIsNotNone(solved)
            self.assertEqual(solved.text, "aB3d")
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
