"""Feed/asset structure tests use synthetic packets, not valid cryptographic signatures."""
import base64
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from urllib.parse import unquote, urlsplit

SPEC = importlib.util.spec_from_file_location("tauri_update_manifest", Path(__file__).parents[1] / "packaging/tauri_update_manifest.py")
manifest = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(manifest)


def synthetic_signature(version="0.2.1", name="YSU Net.app.tar.gz", extra=""):
    packet = base64.b64encode(b"ED" + bytes(72)).decode()
    global_signature = base64.b64encode(bytes(64)).decode()
    envelope = f"untrusted comment: synthetic structure fixture\n{packet}\ntrusted comment: timestamp:1700000000\tfile:{name}\tversion:{version}{extra}\n{global_signature}\n"
    return base64.b64encode(envelope.encode()).decode()


class UpdateManifestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.artifacts = self.root / "artifacts"
        self.dist = self.root / "dist"
        self.output = self.root / "output"
        metadata = {
            "desktop/package.json": json.dumps({"version": "0.2.1"}),
            "desktop/src-tauri/tauri.conf.json": json.dumps({"version": "0.2.1"}),
            "desktop/src-tauri/Cargo.toml": '[package]\nversion="0.2.1"\n',
            "desktop/crates/ysu-auth/Cargo.toml": '[package]\nversion="0.2.1"\n',
            "pyproject.toml": '[project]\nversion="0.2.1"\n',
        }
        for name, content in metadata.items():
            path = self.source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        self.payloads = {}
        for matrix in manifest.MATRICES:
            directory = self.artifacts / f"rust-desktop-bundle-{matrix}" / "bundle"
            directory.mkdir(parents=True)
            name = "YSU Net_0.2.1.deb" if matrix == "linux-x64" else "YSU Net_0.2.1-setup.exe" if matrix == "windows-x64" else "YSU Net_0.2.1.dmg"
            installer = directory / name
            installer.write_bytes((matrix + " installer").encode())
            if matrix in manifest.TARGETS:
                payload = installer if matrix == "windows-x64" else directory / "YSU Net.app.tar.gz"
                if matrix != "windows-x64":
                    payload.write_bytes((matrix + " updater").encode())
                self.payloads[matrix] = payload
                Path(str(payload) + ".sig").write_text(synthetic_signature(name=payload.name) + "\n")
        self.dist.mkdir()
        for name in ["ysu_net_login-0.2.1-py3-none-any.whl", "ysu_net_login-0.2.1.tar.gz"]:
            (self.dist / name).write_bytes(b"synthetic Python distribution")

    def prepare(self, **kwargs):
        args = dict(artifacts=self.artifacts, distributions=self.dist, output=self.output,
                    tag="v0.2.1", source_root=self.source, published=datetime(2026, 10, 22, tzinfo=timezone.utc))
        args.update(kwargs)
        return manifest.prepare_release(**args)

    def test_three_targets_thirteen_assets_and_checksums(self):
        data = self.prepare()
        self.assertEqual(data["version"], "0.2.1")
        self.assertEqual(data["pub_date"], "2026-10-22T00:00:00Z")
        self.assertEqual(set(data["platforms"]), {"windows-x86_64", "darwin-aarch64", "darwin-x86_64"})
        self.assertEqual(len(list(self.output.iterdir())), 13)
        self.assertEqual(json.loads((self.output / "latest.json").read_text()), data)
        for platform in data["platforms"].values():
            url = urlsplit(platform["url"])
            self.assertEqual(url.scheme, "https")
            self.assertEqual(url.netloc, "github.com")
            self.assertTrue(url.path.startswith("/wide-sky-with-me/ysu_net/releases/download/v0.2.1/"))
            payload = self.output / unquote(url.path.rsplit("/", 1)[1])
            self.assertTrue(payload.is_file())
            self.assertEqual(platform["signature"], Path(str(payload) + ".sig").read_text().strip())
            self.assertFalse(platform["signature"].startswith("http"))
        sums = (self.output / "SHA256SUMS").read_text().splitlines()
        self.assertEqual(len(sums), 12)
        for entry in sums:
            digest, name = entry.split("  ", 1)
            self.assertNotIn(" ", name)
            self.assertEqual(digest, hashlib.sha256((self.output / name).read_bytes()).hexdigest())

    def test_same_named_mac_archives_are_not_overwritten(self):
        self.assertEqual(self.payloads["macos-arm64"].name, self.payloads["macos-x64"].name)
        self.prepare()
        self.assertNotEqual((self.output / "YSU-Net_0.2.1_macos-arm64.app.tar.gz").read_bytes(),
                            (self.output / "YSU-Net_0.2.1_macos-x64.app.tar.gz").read_bytes())

    def test_missing_or_extra_artifact_fails_before_output(self):
        for matrix in manifest.MATRICES:
            with self.subTest(matrix=matrix):
                directory = self.artifacts / f"rust-desktop-bundle-{matrix}"
                moved = directory.with_name(directory.name + "-removed")
                directory.rename(moved)
                with self.assertRaises(ValueError):
                    self.prepare()
                moved.rename(directory)
        extra = self.artifacts / "rust-desktop-bundle-linux-x64" / "secret.log"
        extra.write_text("synthetic unwanted file")
        with self.assertRaises(ValueError):
            self.prepare()
        self.assertFalse(self.output.exists())

    def test_missing_empty_bad_or_wrong_version_signatures_fail(self):
        signature = Path(str(self.payloads["windows-x64"]) + ".sig")
        original = signature.read_text()
        signature.unlink()
        with self.assertRaises(ValueError):
            self.prepare()
        for value in ["", "https://outside.invalid/file.sig", "not-base64", synthetic_signature("0.2.0"),
                      synthetic_signature(extra="\tversion:0.2.1"), synthetic_signature(name="../escape")]:
            with self.subTest(kind="invalid signature metadata"):
                signature.write_text(value)
                with self.assertRaises(ValueError):
                    self.prepare()
        signature.write_text(original)
        self.assertFalse(self.output.exists())

    def test_package_version_mismatch_and_foreign_repository_fail(self):
        with self.assertRaises(ValueError):
            self.prepare(repository="outside/repository")
        with self.assertRaises(ValueError):
            self.prepare(tag="v0.2.2")
        (self.source / "desktop/package.json").write_text('{"version":"0.2.0"}')
        with self.assertRaises(ValueError):
            self.prepare()
        self.assertFalse(self.output.exists())

    def test_tags_reject_path_and_url_injection(self):
        for tag in ["0.2.1", "v0.2.01", "v0.2.1/../../outside", "https://outside.invalid", "v0.2.1-beta.01", "v0.2.1\n"]:
            with self.subTest(tag=tag), self.assertRaises(ValueError):
                manifest.release_version(tag)
        self.assertEqual(manifest.release_version("v0.2.1-beta.1"), "0.2.1-beta.1")

    def test_wrong_python_artifact_version_and_nonempty_output_fail(self):
        path = self.dist / "ysu_net_login-0.2.1.tar.gz"
        path.rename(self.dist / "ysu_net_login-0.2.0.tar.gz")
        with self.assertRaises(ValueError):
            self.prepare()
        (self.dist / "ysu_net_login-0.2.0.tar.gz").rename(path)
        self.output.mkdir()
        sentinel = self.output / "keep.txt"
        sentinel.write_text("keep")
        with self.assertRaises(ValueError):
            self.prepare()
        self.assertEqual(sentinel.read_text(), "keep")

    def test_symlink_payload_and_naive_timestamp_fail(self):
        payload = self.payloads["macos-arm64"]
        outside = self.root / "outside.app.tar.gz"
        outside.write_bytes(b"synthetic outside data")
        data = payload.read_bytes()
        payload.unlink()
        try:
            payload.symlink_to(outside)
        except (OSError, NotImplementedError):
            payload.write_bytes(data)
            self.skipTest("symlink creation is unavailable on this platform")
        with self.assertRaises(ValueError):
            self.prepare()
        payload.unlink()
        payload.write_bytes(data)
        with self.assertRaises(ValueError):
            self.prepare(published=datetime(2026, 10, 22))


if __name__ == "__main__":
    unittest.main()
