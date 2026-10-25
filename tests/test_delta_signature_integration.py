"""Cloud/Linux-only REAL qbsdiff + Minisign producer integration.

The files are public signed TEXT, not installers. No production private key is
read and the default production signer is never invoked. The injected signer
may copy the public patch signature ONLY after exact patch-byte equality.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location("cloud_delta_signature_integration", ROOT / "packaging/tauri_delta.py")
delta = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(delta)
manifest = delta.manifest
FIXTURES = ROOT / "desktop/src-tauri/fixtures/delta"
PUBLIC_FILES = ("base.bin", "base.sig", "target.bin", "target.sig", "patch.bsdiff", "patch.sig", "public.key", "fixture.json")


class RealDeltaProducerIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.environ.get("GITHUB_ACTIONS") != "true" or sys.platform != "linux":
            raise unittest.SkipTest("real delta producer tools run only on Linux GitHub Actions")
        missing = [name for name in ("qbsdiff", "qbspatch", "minisign") if not shutil.which(name)]
        if missing:
            raise AssertionError("Linux cloud delta integration requires qbsdiff/qbspatch/minisign")
        for name in PUBLIC_FILES:
            path = FIXTURES / name
            if path.is_symlink() or not path.is_file():
                raise AssertionError("committed public delta fixtures are mandatory in Linux cloud CI")
        metadata = json.loads((FIXTURES / "fixture.json").read_text(encoding="utf-8"))
        if (metadata["base_version"], metadata["target_version"], metadata["algorithm"]) != ("1.0.0", "2.0.0", "bsdiff40"):
            raise AssertionError("public delta fixture versions or algorithm differ")
        for name in PUBLIC_FILES[:-1]:
            data = (FIXTURES / name).read_bytes()
            if metadata["files"][name] != {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}:
                raise AssertionError("committed public fixture integrity differs")
        # Exact CLI versions and signatures, not mocked version/tool output.
        delta.require_tools(delta.subprocess.run, "qbsdiff", "qbspatch")

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.output = self.root / "assets"
        self.output.mkdir()
        self.bases = self.root / "public-bases"
        self.bases.mkdir()
        self.source = self.root / "source"
        config = self.source / "desktop/src-tauri/tauri.conf.json"
        config.parent.mkdir(parents=True)
        config.write_text(json.dumps({"plugins": {"updater": {
            "pubkey": (FIXTURES / "public.key").read_text(encoding="utf-8").strip(),
            "requireSignedVersion": True,
        }}}), encoding="utf-8")
        self.gate = manifest.PublicVerifier(self.source)
        self.version, self.base_version = "2.0.0", "1.0.0"
        self.feed = {"version": self.version, "notes": "PUBLIC non-executable integration data", "platforms": {}}
        for matrix, target in manifest.TARGETS.items():
            name = manifest.payload_name(self.version, matrix)
            shutil.copyfile(FIXTURES / "target.bin", self.output / name)
            shutil.copyfile(FIXTURES / "target.sig", self.output / (name + ".sig"))
            self.feed["platforms"][target] = {"url": manifest.asset_url(self.version, name),
                                           "signature": (FIXTURES / "target.sig").read_text().strip()}
            base_name = manifest.payload_name(self.base_version, matrix)
            shutil.copyfile(FIXTURES / "base.bin", self.bases / base_name)
            shutil.copyfile(FIXTURES / "base.sig", self.bases / (base_name + ".sig"))
        # Complete original inventory, with harmless TEXT placeholders for assets
        # not consumed by the updater (deb/dmg/Python distributions).
        for name in (f"YSU-Net_{self.version}_linux-x64.deb",
                     f"YSU-Net_{self.version}_macos-arm64.dmg", f"YSU-Net_{self.version}_macos-x64.dmg",
                     f"ysu_net_login-{self.version}-py3-none-any.whl", f"ysu_net_login-{self.version}.tar.gz"):
            (self.output / name).write_bytes(b"PUBLIC inventory-only placeholder; NEVER execute or install\n")
        self.write_feed(self.feed)
        manifest.verify_release_assets(self.output, self.source, self.version)
        self.original = {path.name: path.read_bytes() for path in self.output.iterdir()}
        self.signed = []

    def write_feed(self, feed):
        (self.output / "latest.json").write_text(json.dumps(feed), encoding="utf-8")
        manifest.write_checksums(self.output)

    def fixture_signer(self, payload, version):
        self.assertEqual(version, self.version)
        # Never attach an authentic signature to different encoded patch bytes.
        # Different qbsdiff output must FAIL CI, not bypass authentication.
        self.assertEqual(payload.read_bytes(), (FIXTURES / "patch.bsdiff").read_bytes(),
                         "qbsdiff output differs from public signed fixture; regenerate only with an independent cloud test key")
        shutil.copyfile(FIXTURES / "patch.sig", Path(str(payload) + ".sig"))
        self.signed.append(payload.name)

    def produce(self):
        with patch.object(delta, "TauriSigner", side_effect=AssertionError("production default signer must not run in integration")):
            return delta.add_deltas(self.output, self.source, self.version, base_dir=self.bases,
                                    base_version=self.base_version, public_verifier=self.gate,
                                    signer=self.fixture_signer)

    def test_real_producer_preserves_complete_packages_and_reauthenticates_reconstruction(self):
        feed = self.produce()
        self.assertEqual(feed["platforms"], self.feed["platforms"])
        self.assertEqual(set(feed["deltas"]), set(manifest.TARGETS.values()))
        self.assertEqual(len(self.signed), 3)
        self.assertEqual(len(list(self.output.iterdir())), 19)
        for name, data in self.original.items():
            if name not in ("latest.json", "SHA256SUMS"):
                self.assertEqual((self.output / name).read_bytes(), data)
        self.assertEqual(delta.verify_delta_release(self.output, self.source, self.version,
                         base_dir=self.bases, base_version=self.base_version), feed)

    def test_real_minisign_rejects_tampered_patch_even_after_untrusted_hashes_are_updated(self):
        feed = self.produce()
        matrix, target = next(iter(manifest.TARGETS.items()))
        name = manifest.patch_name(self.version, matrix, self.base_version)
        payload = self.output / name
        data = bytearray(payload.read_bytes())
        data[-1] ^= 1
        payload.write_bytes(data)
        feed["deltas"][target][0]["sha256"] = hashlib.sha256(data).hexdigest()
        self.write_feed(feed)
        with self.assertRaisesRegex(ValueError, "does not verify"):
            delta.verify_delta_release(self.output, self.source, self.version,
                                       base_dir=self.bases, base_version=self.base_version)

    def test_real_full_and_patch_signatures_cannot_be_relabelled_as_a_new_version(self):
        for payload_name, signature_name in (("target.bin", "target.sig"), ("patch.bsdiff", "patch.sig")):
            with self.subTest(payload=payload_name), self.assertRaisesRegex(ValueError, "version metadata"):
                self.gate.verify(FIXTURES / payload_name, FIXTURES / signature_name, FIXTURES, "2.0.1")

    def test_untrusted_base_never_reaches_real_delta_generation(self):
        payload = self.bases / manifest.payload_name(self.base_version, "windows-x64")
        payload.write_bytes(b"tampered PUBLIC text")
        with self.assertRaisesRegex(ValueError, "does not verify"):
            self.produce()
        self.assertEqual(self.signed, [])
        self.assertEqual({path.name: path.read_bytes() for path in self.output.iterdir()}, self.original)


if __name__ == "__main__":
    unittest.main()
