"""Public-base policy tests use injected bytes/verifiers, never network or keys."""
from contextlib import redirect_stderr, redirect_stdout
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.request import Request

SPEC = importlib.util.spec_from_file_location("public_delta_base_tests", Path(__file__).parents[1] / "packaging/tauri_delta_base.py")
base = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(base)


class FakeVerifier:
    def __init__(self):
        self.calls = []
        self.reject = False

    def verify(self, payload, signature, root, version):
        self.calls.append((payload.name, signature.name, version))
        if self.reject or signature.read_bytes() != b"public test signature":
            raise ValueError("untrusted sensitive verifier details")
        return "public test signature"


class PublicBaseTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.output = self.root / "bases"
        self.version = "1.0.0"
        self.metadata = {"tag_name": "v1.0.0", "draft": False, "prerelease": False, "assets": []}
        self.responses = {}
        self.requests = []
        self.gate = FakeVerifier()
        for matrix in base.manifest.TARGETS:
            name = base.manifest.payload_name(self.version, matrix)
            for filename, data in ((name, b"PUBLIC non-executable base"), (name + ".sig", b"public test signature")):
                url = f"https://github.com/{base.REPOSITORY}/releases/download/v1.0.0/{filename}"
                self.metadata["assets"].append({"name": filename, "size": len(data), "state": "uploaded", "browser_download_url": url})
                self.responses[url] = data

    def fetch(self, url, limit, **options):
        self.requests.append((url, limit, options))
        if url == base.LATEST_URL:
            return json.dumps(self.metadata).encode()
        return self.responses[url]

    def download(self, **options):
        arguments = dict(fetch=self.fetch, public_verifier=self.gate)
        arguments.update(options)
        return base.download_latest("2.0.0", self.output, self.root, **arguments)

    def test_only_fixed_latest_and_six_canonical_public_files_are_requested(self):
        self.metadata["assets"].append({"name": "private.key", "browser_download_url": "https://outside.invalid/private.key"})
        self.assertEqual(self.download(), "1.0.0")
        self.assertEqual(len(self.requests), 7)
        self.assertEqual(self.requests[0], (base.LATEST_URL, base.METADATA_LIMIT, {"metadata": True, "missing_ok": True}))
        self.assertEqual(len(self.gate.calls), 3)
        self.assertEqual({p.name for p in self.output.iterdir()}, {a["name"] for a in self.metadata["assets"] if a["name"] != "private.key"})
        self.assertFalse(any("private.key" in request[0] for request in self.requests))

    def test_404_and_non_older_latest_return_no_base_without_searching_history(self):
        self.assertEqual(self.download(fetch=lambda *a, **k: None), "")
        self.assertFalse(self.output.exists())
        for tag in ("v2.0.0", "v3.0.0"):
            self.metadata["tag_name"] = tag
            self.assertEqual(self.download(), "")
        self.assertTrue(all(request[0] == base.LATEST_URL for request in self.requests))
        self.assertFalse(self.gate.calls)

    def test_latest_must_be_stable_nondraft_and_canonical(self):
        for key, value in (("draft", True), ("prerelease", True), ("tag_name", "v1.0.0-beta.1"),
                           ("tag_name", "v01.0.0"), ("tag_name", "v1.0.0\nbase_version=9.0.0")):
            metadata = copy.deepcopy(self.metadata)
            metadata[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(base.BaseError):
                base.selected_pairs(metadata, "2.0.0")

    def test_absent_target_is_skipped_but_an_incomplete_pair_fails(self):
        self.metadata["assets"] = self.metadata["assets"][:2]
        self.assertEqual(self.download(), "1.0.0")
        self.assertEqual(len(self.gate.calls), 1)
        self.assertEqual(len(list(self.output.iterdir())), 2)
        self.metadata["assets"] = self.metadata["assets"][:1]
        with self.assertRaisesRegex(base.BaseError, "incomplete"):
            base.selected_pairs(self.metadata, "2.0.0")

    def test_duplicate_wrong_url_upload_state_and_size_metadata_are_rejected(self):
        for key, value in (("browser_download_url", "https://github.com/other/repo/releases/download/v1.0.0/file.exe"),
                           ("browser_download_url", self.metadata["assets"][0]["browser_download_url"] + "?token=secret"),
                           ("state", "open"), ("size", True), ("size", 0), ("size", base.FULL_LIMIT + 1)):
            metadata = copy.deepcopy(self.metadata)
            metadata["assets"][0][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(base.BaseError):
                base.selected_pairs(metadata, "2.0.0")
        metadata = copy.deepcopy(self.metadata)
        metadata["assets"].append(metadata["assets"][0])
        with self.assertRaisesRegex(base.BaseError, "ambiguous"):
            base.selected_pairs(metadata, "2.0.0")

    def test_actual_size_bad_signature_and_metadata_limit_fail_closed(self):
        first = self.metadata["assets"][0]["browser_download_url"]
        self.responses[first] += b"unexpected byte"
        with self.assertRaisesRegex(base.BaseError, "size differs"):
            self.download()
        self.assertFalse(self.gate.calls)
        self.responses[first] = b"PUBLIC non-executable base"
        self.gate.reject = True
        with self.assertRaisesRegex(base.BaseError, "signature verification failed"):
            self.download()
        with self.assertRaises(base.BaseError):
            self.download(fetch=lambda *a, **k: b"x" * (base.METADATA_LIMIT + 1))

    def test_existing_output_is_never_overwritten(self):
        self.output.mkdir()
        sentinel = self.output / "user-file"
        sentinel.write_bytes(b"keep")
        with self.assertRaisesRegex(base.BaseError, "fresh or empty"):
            self.download()
        self.assertEqual(sentinel.read_bytes(), b"keep")
        self.assertEqual(len(self.requests), 1)

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unavailable")
    def test_output_symlink_is_rejected_without_writing_its_target(self):
        destination = self.root / "real"
        destination.mkdir()
        try:
            self.output.symlink_to(destination, target_is_directory=True)
        except OSError:
            self.skipTest("symlink creation unavailable")
        with self.assertRaises(base.BaseError):
            self.download()
        self.assertEqual(list(destination.iterdir()), [])


class TransportPolicyTests(unittest.TestCase):
    def test_redirects_are_https_official_bounded_and_drop_sensitive_headers(self):
        redirect = base.PublicRedirect()
        request = Request("https://github.com/wide-sky-with-me/ysu_net/releases/download/v1.0.0/a.exe",
                          headers={"Authorization": "Bearer must-not-forward", "Cookie": "private", "Referer": "private"})
        for index in range(5):
            request = redirect.redirect_request(request, None, 302, "", {},
                                                f"https://release-assets.githubusercontent.com/file{index}?signed=public")
            self.assertIsNone(request.get_header("Authorization"))
            self.assertIsNone(request.get_header("Cookie"))
            self.assertIsNone(request.get_header("Referer"))
        with self.assertRaises(base.BaseError):
            redirect.redirect_request(request, None, 302, "", {}, "https://github.com/next")
        for url in ("http://github.com/file", "https://github.com.evil.invalid/file", "https://user:pass@github.com/file",
                    "https://github.com:443/file", "https://api.github.com/file", "https://github.com/file?token=secret"):
            self.assertFalse(base.permitted_url(url), url)

    def test_actual_response_budget_does_not_trust_content_length(self):
        for content, headers in ((b"12345", {}), (b"12345", {"Content-Length": "1"}),
                                 (b"1", {"Content-Length": "5"}), (b"1", {"Content-Length": "invalid"})):
            response = io.BytesIO(content)
            response.headers = headers
            with self.assertRaises(base.BaseError):
                base.read_bounded(response, 4, time.monotonic() + 5)
        response = io.BytesIO(b"1234")
        response.headers = {"Content-Length": "4"}
        self.assertEqual(base.read_bounded(response, 4, time.monotonic() + 5), b"1234")
        with self.assertRaises(base.BaseError):
            base.read_bounded(response, 4, time.monotonic() - 1)

    def test_only_metadata_404_is_optional_and_raw_network_error_is_hidden(self):
        opener = type("Opener", (), {})()
        for code, optional in ((404, True), (404, False), (403, True), (500, True)):
            opener.open = lambda *a, c=code, **k: (_ for _ in ()).throw(HTTPError(base.LATEST_URL, c, "sensitive", {}, None))
            with patch.object(base, "build_opener", return_value=opener):
                if code == 404 and optional:
                    self.assertIsNone(base.fetch_public(base.LATEST_URL, 10, metadata=True, missing_ok=optional))
                else:
                    with self.assertRaisesRegex(base.BaseError, "^public base request failed$"):
                        base.fetch_public(base.LATEST_URL, 10, metadata=True, missing_ok=optional)
        opener.open = lambda *a, **k: (_ for _ in ()).throw(URLError("https://private.invalid/?token=secret"))
        with patch.object(base, "build_opener", return_value=opener), self.assertRaisesRegex(base.BaseError, "^public base request failed$"):
            base.fetch_public(base.LATEST_URL, 10, metadata=True)

    def test_cli_outputs_only_validated_version_or_fixed_error(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "github-output"
            with patch.dict(os.environ, {"GITHUB_OUTPUT": str(output)}), \
                    patch.object(base, "download_latest", return_value="1.0.0"), redirect_stdout(io.StringIO()):
                self.assertEqual(base.main(["--target-version", "2.0.0", "--output", "unused"]), 0)
            self.assertEqual(output.read_text(), "base_version=1.0.0\n")
            errors = io.StringIO()
            with patch.object(base, "download_latest", side_effect=ValueError("secret network path")), redirect_stderr(errors):
                self.assertEqual(base.main(["--target-version", "2.0.0", "--output", "unused"]), 1)
            self.assertEqual(errors.getvalue(), "public delta base preparation failed\n")


if __name__ == "__main__":
    unittest.main()
