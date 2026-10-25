"""Public-only minisign release gate; fixtures never contain a private key."""
import base64
from contextlib import redirect_stderr, redirect_stdout
import io
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("tauri_signature_gate", Path(__file__).parents[1] / "packaging/tauri_update_manifest.py")
manifest = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(manifest)

# Same independent, public signed-text fixture used by the official updater tests.
# Its private key was destroyed; this text cannot be installed or executed.
PAYLOAD = b"offline updater artifact fixture; never executable\n"
PUBLIC_KEY = "dW50cnVzdGVkIGNvbW1lbnQ6IG1pbmlzaWduIHB1YmxpYyBrZXk6IEVENDVFQzhGNkJFOTJEOUEKUldTYUxlbHJqK3hGN1lVUUFYdDlKMGdodDR0dnBFeVBPVlFEL2lTcUV5WmVhY0s3dm1Zd2dieVUK"
SIGNATURE = "dW50cnVzdGVkIGNvbW1lbnQ6IHNpZ25hdHVyZSBmcm9tIHRhdXJpIHNlY3JldCBrZXkKUlVTYUxlbHJqK3hGN2FTMVowZXV3ZFFCY1dMN1JoaTZybTBhS0pwSnloSmRwQktVREZkblZhaFp2REF0cGNEMmJ4Y21sN3Q5YWI0YzJvNi9idHpoTFRSa3hxQWVZUDFoTGdZPQp0cnVzdGVkIGNvbW1lbnQ6IHRpbWVzdGFtcDoxNzkyNjY4NjQxCWZpbGU6YXJ0aWZhY3QudHh0CXZlcnNpb246OTk5LjAuMAp0WWM2ejFya0M3cENPdlR5WG1KTkFvbEZYM0N1QjJramQ0UU9VVTM2U3AvR0ZaelQzUUR3RlMxb3JTeGpEaGRIZWMyYkxNdmg4bHhMVlR5Ry9FcWFEUT09Cg=="


class PublicSignatureGateTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "source"
        self.output = self.root / "assets"
        self.output.mkdir()
        self.config = self.source / "desktop/src-tauri/tauri.conf.json"
        self.config.parent.mkdir(parents=True)
        self.config.write_text(json.dumps({"plugins": {"updater": {"pubkey": PUBLIC_KEY, "requireSignedVersion": True}}}))
        self.version = "999.0.0"
        self.payloads = []
        self.feed = {"version": self.version, "platforms": {}}
        for matrix, target in manifest.TARGETS.items():
            name = f"YSU-Net_{self.version}_{matrix}{'-setup.exe' if matrix == 'windows-x64' else '.app.tar.gz'}"
            payload = self.output / name
            payload.write_bytes(PAYLOAD)
            Path(str(payload) + ".sig").write_text(SIGNATURE)
            self.payloads.append(payload)
            self.feed["platforms"][target] = {
                "url": f"https://github.com/{manifest.REPOSITORY}/releases/download/v{self.version}/{name}",
                "signature": SIGNATURE,
            }
        self.write_feed()

    def write_feed(self):
        (self.output / "latest.json").write_text(json.dumps(self.feed))

    def verify(self, **kwargs):
        return manifest.verify_release_signatures(self.output, self.source, self.version, **kwargs)

    def replace_signature(self, signature):
        for payload in self.payloads:
            Path(str(payload) + ".sig").write_text(signature)
        for platform in self.feed["platforms"].values():
            platform["signature"] = signature
        self.write_feed()

    def test_missing_verifier_is_a_hard_failure(self):
        with self.assertRaisesRegex(ValueError, "verifier is required"):
            self.verify(verifier=str(self.root / "missing-verifier"))

    def test_signed_version_requirement_cannot_be_disabled(self):
        config = json.loads(self.config.read_text())
        config["plugins"]["updater"]["requireSignedVersion"] = False
        self.config.write_text(json.dumps(config))
        with self.assertRaisesRegex(ValueError, "requires signed-version"):
            self.verify()

    @unittest.skipUnless(shutil.which("minisign"), "requires the maintained minisign verifier; mandatory in release CI")
    def test_real_verifier_accepts_all_three_independent_signed_text_payloads(self):
        self.verify()

    @unittest.skipUnless(shutil.which("minisign"), "requires the maintained minisign verifier; mandatory in release CI")
    def test_tampered_payload_is_rejected(self):
        for payload in self.payloads:
            with self.subTest(target=payload.name):
                payload.write_bytes(b"tampered text, never executable")
                try:
                    with self.assertRaisesRegex(ValueError, "does not verify"):
                        self.verify()
                finally:
                    payload.write_bytes(PAYLOAD)

    @unittest.skipUnless(shutil.which("minisign"), "requires the maintained minisign verifier; mandatory in release CI")
    def test_valid_signature_under_a_different_public_key_is_rejected(self):
        production = Path(__file__).parents[1] / "desktop/src-tauri/tauri.conf.json"
        other_public_key = json.loads(production.read_text())["plugins"]["updater"]["pubkey"]
        self.assertNotEqual(other_public_key, PUBLIC_KEY)
        config = json.loads(self.config.read_text())
        config["plugins"]["updater"]["pubkey"] = other_public_key
        self.config.write_text(json.dumps(config))
        with self.assertRaisesRegex(ValueError, "does not verify"):
            self.verify()

    @unittest.skipUnless(shutil.which("minisign"), "requires the maintained minisign verifier; mandatory in release CI")
    def test_unsigned_trusted_comment_changes_are_rejected(self):
        decoded = base64.b64decode(SIGNATURE).decode()
        changed = decoded.replace("file:artifact.txt", "file:tampered.txt")
        self.assertNotEqual(decoded, changed)
        self.replace_signature(base64.b64encode(changed.encode()).decode())
        with self.assertRaisesRegex(ValueError, "does not verify"):
            self.verify()

    @unittest.skipUnless(shutil.which("minisign"), "requires the maintained minisign verifier; mandatory in release CI")
    def test_old_signed_version_cannot_be_relabelled(self):
        self.feed["version"] = "999.0.1"
        self.write_feed()
        with self.assertRaisesRegex(ValueError, "version or targets differ"):
            self.verify()
        # Announce a new release and retain an authentic OLD signature/payload.
        # Cryptography succeeds, but the authenticated old version must still fail.
        self.version = "999.0.1"
        self.feed["platforms"] = {}
        for matrix, target in manifest.TARGETS.items():
            name = f"YSU-Net_{self.version}_{matrix}{'-setup.exe' if matrix == 'windows-x64' else '.app.tar.gz'}"
            (self.output / name).write_bytes(PAYLOAD)
            (self.output / (name + ".sig")).write_text(SIGNATURE)
            self.feed["platforms"][target] = {
                "url": f"https://github.com/{manifest.REPOSITORY}/releases/download/v{self.version}/{name}",
                "signature": SIGNATURE,
            }
        self.write_feed()
        with self.assertRaisesRegex(ValueError, "signature version metadata is missing or mismatched"):
            self.verify()

    @unittest.skipUnless(shutil.which("minisign"), "requires the maintained minisign verifier; mandatory in release CI")
    def test_structurally_valid_forged_signature_is_not_enough(self):
        lines = base64.b64decode(SIGNATURE).decode().splitlines()
        lines[1] = base64.b64encode(b"ED" + bytes(72)).decode()
        lines[3] = base64.b64encode(bytes(64)).decode()
        self.replace_signature(base64.b64encode(("\n".join(lines) + "\n").encode()).decode())
        with self.assertRaisesRegex(ValueError, "does not verify"):
            self.verify()

    @unittest.skipUnless(shutil.which("minisign"), "requires the maintained minisign verifier; mandatory in release CI")
    def test_inline_signature_and_fixed_url_must_match_local_verified_files(self):
        target = next(iter(self.feed["platforms"]))
        original = self.feed["platforms"][target].copy()
        self.feed["platforms"][target]["signature"] += "A"
        self.write_feed()
        with self.assertRaisesRegex(ValueError, "URL or inline signature differs"):
            self.verify()
        self.feed["platforms"][target] = original
        self.feed["platforms"][target]["url"] = "https://untrusted.invalid/payload.exe"
        self.write_feed()
        with self.assertRaisesRegex(ValueError, "URL or inline signature differs"):
            self.verify()

class SharedPublicVerifierTests(unittest.TestCase):
    """Injected runner tests never invoke a tool or generate a signing key."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        config = self.root / "desktop/src-tauri/tauri.conf.json"
        config.parent.mkdir(parents=True)
        config.write_text(json.dumps({"plugins": {"updater": {"pubkey": PUBLIC_KEY, "requireSignedVersion": True}}}))
        self.payload = self.root / "artifact.txt"
        self.payload.write_bytes(PAYLOAD)
        self.signature = self.root / "artifact.txt.sig"
        self.signature.write_text(SIGNATURE)

    def gate(self, runner):
        with patch.object(manifest.shutil, "which", return_value="fixture-minisign"):
            return manifest.PublicVerifier(self.root, runner=runner)

    def test_runner_receives_original_public_key_and_captured_envelope(self):
        calls = []

        def runner(arguments, **options):
            calls.append(arguments)
            detached = Path(arguments[arguments.index("-x") + 1])
            self.assertEqual(detached.read_bytes(), base64.b64decode(SIGNATURE))
            self.assertEqual(arguments[-2:], ["-P", base64.b64decode(PUBLIC_KEY).decode().splitlines()[1]])
            self.assertTrue(options["capture_output"])
            self.assertFalse(options["check"])
            return type("Result", (), {"returncode": 0})()

        self.assertEqual(self.gate(runner).verify(self.payload, self.signature, self.root, "999.0.0"), SIGNATURE)
        self.assertEqual(len(calls), 1)

    def test_rejected_crypto_cannot_be_replaced_by_structure_or_hash(self):
        gate = self.gate(lambda *args, **kwargs: type("Result", (), {"returncode": 1})())
        with self.assertRaisesRegex(ValueError, "does not verify"):
            gate.verify(self.payload, self.signature, self.root, "999.0.0")

    def test_valid_crypto_still_requires_exact_signed_version(self):
        gate = self.gate(lambda *args, **kwargs: type("Result", (), {"returncode": 0})())
        with self.assertRaisesRegex(ValueError, "version metadata"):
            gate.verify(self.payload, self.signature, self.root, "999.0.1")

    def test_verifier_interprets_authenticated_capture_not_changed_signature_file(self):
        def runner(*args, **kwargs):
            self.signature.write_text("mutated during verifier invocation")
            return type("Result", (), {"returncode": 0})()

        self.assertEqual(self.gate(runner).verify(self.payload, self.signature, self.root, "999.0.0"), SIGNATURE)



class ReleaseCliGateTests(unittest.TestCase):
    def invoke(self, verify_error=None, asset_error=None):
        order = []
        output, errors = io.StringIO(), io.StringIO()

        def prepare(*args):
            order.append("prepare")

        def verify(*args):
            order.append("verify")
            if verify_error:
                raise verify_error

        def validate(*args):
            order.append("assets")
            if asset_error:
                raise asset_error

        arguments = ["--artifacts", "fixture-artifacts", "--dist", "fixture-dist",
                     "--output", "fixture-output", "--tag", "v0.2.1"]
        with patch.object(manifest, "prepare_release", side_effect=prepare), \
                patch.object(manifest, "verify_release_signatures", side_effect=verify), \
                patch.object(manifest, "validate_release_assets", side_effect=validate), \
                redirect_stdout(output), redirect_stderr(errors):
            result = manifest.main(arguments)
        return result, order, output.getvalue(), errors.getvalue()

    def test_cli_crypto_failure_cannot_return_or_print_success(self):
        result, order, output, errors = self.invoke(ValueError("signature rejection fixture"))
        self.assertEqual(result, 1)
        self.assertEqual(order, ["prepare", "verify"])
        self.assertNotIn("Prepared 13 assets", output)
        self.assertIn("signature rejection fixture", errors)

    def test_cli_requires_verification_after_assembly_before_success(self):
        result, order, output, errors = self.invoke()
        self.assertEqual(result, 0)
        self.assertEqual(order, ["prepare", "verify", "assets"])
        self.assertIn("signatures and signed versions verified", output)
        self.assertEqual(errors, "")

    def test_cli_inventory_failure_cannot_return_or_print_success(self):
        result, order, output, errors = self.invoke(asset_error=ValueError("fixture inventory rejection"))
        self.assertEqual(result, 1)
        self.assertEqual(order, ["prepare", "verify", "assets"])
        self.assertNotIn("Prepared 13 assets", output)
        self.assertIn("fixture inventory rejection", errors)


if __name__ == "__main__":
    unittest.main()
