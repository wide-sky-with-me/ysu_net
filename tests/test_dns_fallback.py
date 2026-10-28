"""DNS failover and real loopback TLS proof; no campus network or user credentials."""
import ipaddress
from pathlib import Path
import shutil
import socket
import ssl
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

import requests
from urllib3.connection import HTTPSConnection
from urllib3.exceptions import NewConnectionError

from tests.helpers import OfflineTestCase
from ysu_net.auth import api, dns_fallback as dns


class DNSFallbackTests(OfflineTestCase):
    def test_shared_data_is_limited_to_exact_campus_names(self):
        names = ("auth1.ysu.edu.cn", "cer.ysu.edu.cn")
        for name in names:
            address = ipaddress.ip_address(dns.fallback_ip(name))
            self.assertFalse(address.is_loopback or address.is_unspecified or address.is_multicast)
        for name in ("outside.invalid", "auth1.ysu.edu.cn.outside.invalid", "127.0.0.1", "auth1.ysu.edu.cn."):
            self.assertIsNone(dns.fallback_ip(name))

    def test_normal_socket_does_not_consult_fallback(self):
        connection = dns.CampusHTTPSConnection("auth1.ysu.edu.cn")
        expected = object()
        with patch.object(HTTPSConnection, "_new_conn", return_value=expected), \
                patch.object(dns, "fallback_ip") as fallback:
            self.assertIs(connection._new_conn(), expected)
        fallback.assert_not_called()

    def test_refusal_and_timeout_never_trigger_another_connection(self):
        for cause in (ConnectionRefusedError("fixture"), TimeoutError("fixture")):
            connection = dns.CampusHTTPSConnection("auth1.ysu.edu.cn")
            error = NewConnectionError(connection, "fixture")
            error.__cause__ = cause
            with self.subTest(cause=type(cause).__name__), \
                    patch.object(HTTPSConnection, "_new_conn", side_effect=error) as connect, \
                    patch.object(dns, "fallback_ip") as fallback:
                with self.assertRaises(NewConnectionError):
                    connection._new_conn()
                self.assertEqual(connect.call_count, 1)
                fallback.assert_not_called()

    def test_unknown_dns_failure_is_not_mapped_to_a_campus_server(self):
        connection = dns.CampusHTTPSConnection("outside.invalid")
        error = NewConnectionError(connection, "fixture")
        error.__cause__ = socket.gaierror(socket.EAI_AGAIN, "fixture")
        with patch.object(HTTPSConnection, "_new_conn", side_effect=error) as connect:
            with self.assertRaises(NewConnectionError):
                connection._new_conn()
        self.assertEqual(connect.call_count, 1)


class TLSIdentityTests(unittest.TestCase):
    """Use ephemeral test certificates; the Mock Linux runner must provide OpenSSL."""

    def setUp(self):
        self.assertIsNotNone(shutil.which("openssl"), "TLS identity regression requires OpenSSL")
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.cert = self.root / "cert.pem"
        self.key = self.root / "key.pem"
        made = subprocess.run([
            "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
            "-subj", "/CN=auth1.ysu.edu.cn", "-addext", "subjectAltName=DNS:auth1.ysu.edu.cn",
            "-keyout", str(self.key), "-out", str(self.cert),
        ], capture_output=True, timeout=15)
        self.assertEqual(made.returncode, 0, "ephemeral TLS fixture generation failed")
        self.requests = []
        self.sni = []
        observed = self.requests

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                observed.append((dict(self.headers), body))
                self.send_response(200)
                self.send_header("Set-Cookie", "fixture=opaque; Secure; Path=/")
                self.end_headers()
                self.wfile.write(b"ok")

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(self.cert, self.key)
        context.set_servername_callback(lambda sock, name, ctx: self.sni.append(name))
        self.server.socket = context.wrap_socket(self.server.socket, server_side=True)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.port = self.server.server_port
        original_lookup = socket.getaddrinfo

        def local_only(host, port, *args, **kwargs):
            if host in ("auth1.ysu.edu.cn", "cer.ysu.edu.cn"):
                raise socket.gaierror(socket.EAI_AGAIN, "fixture system DNS failure")
            if host == "127.0.0.1":
                return original_lookup(host, port, *args, **kwargs)
            raise AssertionError("test forbids external DNS")

        def fixture_fallback(host):
            return "127.0.0.1" if host in ("auth1.ysu.edu.cn", "cer.ysu.edu.cn") else None

        self.lookup = patch.object(socket, "getaddrinfo", side_effect=local_only)
        self.lookup.start()
        self.addCleanup(self.lookup.stop)
        self.fallback = patch.object(dns, "fallback_ip", side_effect=fixture_fallback)
        self.fallback.start()
        self.addCleanup(self.fallback.stop)

    def session(self, fallback=True):
        # Exercise the production factory so losing the API adapter wiring
        # breaks the TLS integration, rather than only testing an unused class.
        with patch.object(api, "track_resource"):
            session = api._new_portal_session() if fallback else requests.Session()
        session.trust_env = False
        self.addCleanup(session.close)
        return session

    def test_fallback_preserves_sni_host_origin_cookies_and_sends_one_post(self):
        session = self.session()
        url = f"https://auth1.ysu.edu.cn:{self.port}/submit"
        response = session.post(url, data=b"fixture", headers={"Origin": "https://auth1.ysu.edu.cn"},
                                verify=str(self.cert), timeout=3)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.url, url)
        self.assertEqual(response.text, "ok")
        self.assertEqual(self.sni, ["auth1.ysu.edu.cn"])
        self.assertEqual(len(self.requests), 1)
        headers, body = self.requests[0]
        self.assertEqual(headers["Host"], f"auth1.ysu.edu.cn:{self.port}")
        self.assertEqual(headers["Origin"], "https://auth1.ysu.edu.cn")
        self.assertEqual(body, b"fixture")
        self.assertEqual(session.cookies.get("fixture", domain="auth1.ysu.edu.cn", path="/"), "opaque")

    def test_an_unrelated_requests_session_still_uses_original_dns(self):
        session = self.session(False)
        with self.assertRaises(requests.exceptions.ConnectionError):
            session.post(f"https://auth1.ysu.edu.cn:{self.port}/submit", data=b"fixture",
                         verify=str(self.cert), timeout=3)
        self.assertEqual(self.requests, [])
        self.assertEqual(self.sni, [])

    def test_wrong_certificate_hostname_stops_before_any_http_body(self):
        session = self.session()
        with self.assertRaises(requests.exceptions.SSLError):
            session.post(f"https://cer.ysu.edu.cn:{self.port}/submit", data=b"fixture",
                         verify=str(self.cert), timeout=3)
        self.assertEqual(self.requests, [])
        self.assertTrue(self.sni and all(name == "cer.ysu.edu.cn" for name in self.sni))
