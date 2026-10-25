"""Injected publisher tests: synthetic envelopes, NO tools, keys or network.

FakeRunner does not implement bsdiff: it stores target bytes in an in-memory map.
Real qbsdiff/qbspatch/Tauri/minisign integration belongs to cloud CI exclusively.
"""
import base64
from contextlib import redirect_stderr, redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).parents[1] / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


delta = load("tauri_delta_tests", "packaging/tauri_delta.py")
fixtures = load("delta_manifest_fixtures", "tests/test_update_manifest.py")
manifest = delta.manifest


def fixture_signature(payload, version):
    return fixtures.synthetic_signature(version, payload.name,
                                        "\tfixture-sha256:" + manifest.sha256_file(payload))


class FakeVerifier:
    """Tests ordering/rejection only; explicitly NOT a cryptographic verifier."""
    def __init__(self):
        self.calls = []
        self.reject_reconstructed = False

    def verify(self, payload, signature, root, version):
        self.calls.append((payload.name, version, "reconstruct-" in str(payload)))
        if self.reject_reconstructed and "reconstruct-" in str(payload):
            raise ValueError("fake original full signature rejection")
        encoded = manifest.signature_text(signature, root, version)
        comment = base64.b64decode(encoded).decode().splitlines()[2]
        if "\tfixture-sha256:" + manifest.sha256_file(payload) not in comment:
            raise ValueError("fake pinned public key rejected signature")
        return encoded


class FakeRunner:
    def __init__(self):
        self.calls = []
        self.targets = {}
        self.size = 40
        self.bad_reconstruction = False
        self.bad_magic = False
        self.fail = None
        self.version = "1.4.4"

    def __call__(self, arguments, **options):
        self.calls.append(arguments)
        tool = arguments[0]
        if self.fail == tool:
            return SimpleNamespace(returncode=1, stdout=b"sensitive child log must not be shown")
        if arguments[1:] == ["--version"]:
            return SimpleNamespace(returncode=0, stdout=f"{tool} {self.version}\n".encode())
        if tool == "qbsdiff":
            base, target, output = map(Path, arguments[1:])
            self.targets[output.name] = target.read_bytes()
            with output.open("wb") as stream:
                stream.write(b"NOTDIFF!" if self.bad_magic else b"BSDIFF40")
                stream.truncate(self.size)
        elif tool == "qbspatch":
            base, output, patch_path = map(Path, arguments[1:])
            data = self.targets[patch_path.name]
            output.write_bytes(b"wrong reconstructed bytes" if self.bad_reconstruction else data)
        else:
            raise AssertionError("unexpected real tool invocation")
        return SimpleNamespace(returncode=0, stdout=b"")


class DeltaManifestTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.UpdateManifestTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.output, self.source, self.root = self.fixture.output, self.fixture.source, self.fixture.root
        self.version, self.base_version = "0.2.1", "0.2.0"
        self.feed = self.fixture.prepare()
        for matrix, target in manifest.TARGETS.items():
            payload = self.output / manifest.payload_name(self.version, matrix)
            payload.write_bytes((matrix + " target ").encode() + b"T" * 512)
            signature = fixture_signature(payload, self.version)
            Path(str(payload) + ".sig").write_text(signature)
            self.feed["platforms"][target]["signature"] = signature
        self.write_feed(self.feed)
        self.base_dir = self.root / "public-bases"
        self.base_dir.mkdir()
        for matrix in manifest.TARGETS:
            payload = self.base_dir / manifest.payload_name(self.base_version, matrix)
            payload.write_bytes((matrix + " base ").encode() + b"B" * 512)
            Path(str(payload) + ".sig").write_text(fixture_signature(payload, self.base_version))
        self.gate, self.runner = FakeVerifier(), FakeRunner()
        self.signed = []
        self.baseline = self.snapshot()

    def write_feed(self, feed):
        (self.output / "latest.json").write_text(json.dumps(feed))
        manifest.write_checksums(self.output)

    def snapshot(self):
        return {path.name: path.read_bytes() for path in self.output.iterdir()}

    def signer(self, payload, version):
        self.signed.append(payload.name)
        Path(str(payload) + ".sig").write_text(fixture_signature(payload, version))

    def add(self, **options):
        values = dict(base_dir=self.base_dir, base_version=self.base_version,
                      public_verifier=self.gate, runner=self.runner, signer=self.signer)
        values.update(options)
        return delta.add_deltas(self.output, self.source, self.version, **values)

    def verify(self, **options):
        values = dict(base_dir=self.base_dir, base_version=self.base_version,
                      public_verifier=self.gate, runner=self.runner)
        values.update(options)
        return delta.verify_delta_release(self.output, self.source, self.version, **values)

    def test_three_authenticated_patches_preserve_original_platforms_and_assets(self):
        feed = self.add()
        self.assertEqual(feed["platforms"], self.feed["platforms"])
        self.assertEqual(feed["version"], self.version)
        self.assertEqual(set(feed["deltas"]), set(manifest.TARGETS.values()))
        self.assertEqual(len(self.snapshot()), 19)
        self.assertEqual(len(self.signed), 3)
        for name, content in self.baseline.items():
            if name not in ("latest.json", "SHA256SUMS"):
                self.assertEqual((self.output / name).read_bytes(), content)
        for matrix, target in manifest.TARGETS.items():
            descriptor, = feed["deltas"][target]
            self.assertEqual(set(descriptor), manifest.DELTA_FIELDS)
            self.assertEqual(descriptor["full_url"], self.feed["platforms"][target]["url"])
            self.assertEqual(descriptor["full_signature"], self.feed["platforms"][target]["signature"])
            self.assertEqual(descriptor["target_version"], self.version)
            self.assertEqual(descriptor["base_version"], self.base_version)
            self.assertEqual(descriptor["format"], "bsdiff40")
            name = manifest.patch_name(self.version, matrix, self.base_version)
            self.assertEqual(descriptor["url"], manifest.asset_url(self.version, name))
            self.assertEqual(descriptor["sha256"], manifest.sha256_file(self.output / name))
            self.assertTrue(any(call[0] == name for call in self.gate.calls))
        self.assertTrue(any(call[2] for call in self.gate.calls), "rebuilt full payload must be authenticated again")
        self.assertEqual(self.verify(), feed)

    def test_no_base_and_empty_base_keep_exact_thirteen_assets_without_tools_or_signer(self):
        for options in ({"base_dir": None, "base_version": None}, {}):
            if options == {}:
                for path in self.base_dir.iterdir():
                    path.unlink()
            self.assertNotIn("deltas", self.add(**options))
            self.assertEqual(self.snapshot(), self.baseline)
            self.assertFalse(self.runner.calls)
            self.assertFalse(self.signed)
        self.assertGreaterEqual(len(self.gate.calls), 3)

    def test_partial_public_base_set_emits_only_that_target(self):
        for matrix in ("macos-arm64", "macos-x64"):
            payload = self.base_dir / manifest.payload_name(self.base_version, matrix)
            payload.unlink()
            Path(str(payload) + ".sig").unlink()
        self.assertEqual(set(self.add()["deltas"]), {"windows-x86_64"})
        self.assertEqual(len(self.snapshot()), 15)

    def test_exact_eighty_percent_and_oversized_patches_are_not_signed_or_published(self):
        # Targets deliberately become 100 bytes to exercise strict integer equality.
        for matrix, target in manifest.TARGETS.items():
            payload = self.output / manifest.payload_name(self.version, matrix)
            payload.write_bytes(b"T" * 100)
            encoded = fixture_signature(payload, self.version)
            Path(str(payload) + ".sig").write_text(encoded)
            self.feed["platforms"][target]["signature"] = encoded
        self.write_feed(self.feed)
        before = self.snapshot()
        for size in (80, 81, manifest.MAX_PATCH_SIZE + 1):
            with self.subTest(size=size):
                self.runner.size = size
                self.assertNotIn("deltas", self.add())
                self.assertEqual(self.snapshot(), before)
                self.assertFalse(self.signed)

    def test_strictly_older_stable_base_and_paired_options_are_required(self):
        for version in ("0.2.1", "0.2.2", "0.2.0-beta.1", "0.02.0", "../0.2.0"):
            with self.subTest(version=version), self.assertRaises(ValueError):
                self.add(base_version=version)
        for options in ({"base_dir": None}, {"base_version": None}):
            with self.assertRaises(ValueError):
                self.add(**options)
        self.assertEqual(self.snapshot(), self.baseline)
        self.assertFalse(self.runner.calls)

    def test_invalid_base_signature_and_missing_pair_fail_before_diff(self):
        payload = self.base_dir / manifest.payload_name(self.base_version, "windows-x64")
        signature = Path(str(payload) + ".sig")
        original = signature.read_text()
        for value in ("bad-base64", fixture_signature(payload, self.version)):
            signature.write_text(value)
            with self.assertRaises(ValueError):
                self.add()
            self.assertFalse(self.runner.calls)
        signature.write_text(original)
        signature.unlink()
        with self.assertRaises(ValueError):
            self.add()
        self.assertEqual(self.snapshot(), self.baseline)

    def test_base_full_size_and_unexpected_base_files_fail(self):
        payload = self.base_dir / manifest.payload_name(self.base_version, "windows-x64")
        old = payload.read_bytes()
        with payload.open("r+b") as stream:
            stream.truncate(manifest.MAX_FULL_SIZE + 1)
        with self.assertRaisesRegex(ValueError, "size limit"):
            self.add()
        payload.write_bytes(old)
        (self.base_dir / "unexpected.log").write_text("not a public updater pair")
        with self.assertRaisesRegex(ValueError, "unexpected"):
            self.add()
        self.assertEqual(self.snapshot(), self.baseline)

    def test_bad_target_signature_fails_even_without_any_base(self):
        payload = self.output / manifest.payload_name(self.version, "windows-x64")
        payload.write_bytes(b"modified full payload")
        manifest.write_checksums(self.output)
        with self.assertRaisesRegex(ValueError, "fake pinned"):
            self.add(base_dir=None, base_version=None)
        self.assertFalse(self.runner.calls)
        self.assertFalse(self.signed)

    def test_wrong_tool_version_bad_magic_and_reconstruction_fail_without_exposing_assets(self):
        for attribute, value in (("version", "1.4.3"), ("bad_magic", True), ("bad_reconstruction", True), ("fail", "qbsdiff")):
            original = getattr(self.runner, attribute)
            setattr(self.runner, attribute, value)
            with self.subTest(failure=attribute), self.assertRaises(ValueError):
                self.add()
            setattr(self.runner, attribute, original)
            self.assertEqual(self.snapshot(), self.baseline)
            self.assertFalse(self.signed)

    def test_reconstruction_must_pass_the_original_full_signature_gate(self):
        self.gate.reject_reconstructed = True
        with self.assertRaisesRegex(ValueError, "original full signature"):
            self.add()
        self.assertEqual(self.snapshot(), self.baseline)
        self.assertFalse(self.signed)

    def test_signer_error_missing_bad_wrong_version_or_mutated_patch_never_changes_output(self):
        def raising(payload, version):
            raise ValueError("fake signer error")

        def missing(payload, version):
            pass

        def wrong_version(payload, version):
            Path(str(payload) + ".sig").write_text(fixture_signature(payload, self.base_version))

        def bad_key(payload, version):
            Path(str(payload) + ".sig").write_text(fixtures.synthetic_signature(version, payload.name))

        def mutate(payload, version):
            payload.write_bytes(b"BSDIFF40" + b"changed patch")
            self.signer(payload, version)

        for signer in (raising, missing, wrong_version, bad_key, mutate):
            with self.subTest(signer=signer.__name__), self.assertRaises((ValueError, OSError)):
                self.add(signer=signer)
            self.assertEqual(self.snapshot(), self.baseline)

    def test_final_gate_rejects_descriptor_mismatches_even_with_fresh_checksums(self):
        good = self.add()
        target = "windows-x86_64"
        for field, value in (("format", "other"), ("base_version", "0.2.1"), ("base_version", "0.1.9"),
                             ("target_version", "0.2.2"), ("full_url", good["platforms"]["darwin-aarch64"]["url"]),
                             ("full_signature", "bad"), ("url", "https://outside.invalid/file.bsdiff"),
                             ("base_sha256", "0" * 64), ("target_sha256", "0" * 64), ("sha256", "0" * 64),
                             ("size", 0), ("size", True), ("size", manifest.MAX_PATCH_SIZE + 1),
                             ("base_size", manifest.MAX_FULL_SIZE + 1), ("base_size", 1),
                             ("target_size", 1), ("signature", "bad")):
            altered = json.loads(json.dumps(good))
            altered["deltas"][target][0][field] = value
            self.write_feed(altered)
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                self.verify()
        self.write_feed(good)
        self.assertEqual(self.verify(), good)

    def test_final_gate_rejects_wrong_target_cardinality_extra_fields_and_unprofitable_metadata(self):
        good = self.add()
        for mutation in ("unknown-target", "two-entries", "no-entries", "extra-field", "unprofitable"):
            altered = json.loads(json.dumps(good))
            if mutation == "unknown-target":
                altered["deltas"]["linux-x86_64"] = altered["deltas"].pop("windows-x86_64")
            elif mutation == "two-entries":
                altered["deltas"]["windows-x86_64"] *= 2
            elif mutation == "no-entries":
                altered["deltas"]["windows-x86_64"] = []
            elif mutation == "extra-field":
                altered["deltas"]["windows-x86_64"][0]["unused"] = "reject"
            else:
                entry = altered["deltas"]["windows-x86_64"][0]
                entry["size"] = entry["target_size"]
            self.write_feed(altered)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.verify()

    def test_final_gate_rejects_missing_extra_bad_signature_and_bad_patch(self):
        good = self.add()
        name = manifest.patch_name(self.version, "windows-x64", self.base_version)
        patch_path, signature = self.output / name, self.output / (name + ".sig")
        old_patch, old_signature = patch_path.read_bytes(), signature.read_bytes()
        patch_path.unlink()
        with self.assertRaises(ValueError):
            self.verify()
        patch_path.write_bytes(old_patch)
        extra = self.output / "undeclared.bsdiff"
        extra.write_bytes(old_patch)
        manifest.write_checksums(self.output)
        with self.assertRaises(ValueError):
            self.verify()
        extra.unlink()
        signature.write_text(fixtures.synthetic_signature(self.version, name))
        altered = json.loads(json.dumps(good))
        altered["deltas"]["windows-x86_64"][0]["signature"] = signature.read_text()
        self.write_feed(altered)
        with self.assertRaisesRegex(ValueError, "fake pinned"):
            self.verify()
        signature.write_bytes(old_signature)
        patch_path.write_bytes(b"BSDIFF40" + b"tampered patch")
        altered = json.loads(json.dumps(good))
        entry = altered["deltas"]["windows-x86_64"][0]
        entry.update(size=patch_path.stat().st_size, sha256=manifest.sha256_file(patch_path))
        self.write_feed(altered)
        with self.assertRaisesRegex(ValueError, "fake pinned"):
            self.verify()

    def test_final_gate_requires_base_and_does_not_generate_or_sign(self):
        self.add()
        with self.assertRaisesRegex(ValueError, "requires.*base"):
            self.verify(base_dir=None, base_version=None)
        self.runner.calls.clear()
        signed = list(self.signed)
        self.verify()
        self.assertEqual(self.signed, signed)
        self.assertTrue(all(call[0] == "qbspatch" for call in self.runner.calls))
        with self.assertRaisesRegex(ValueError, "original prepared"):
            self.add()


class DefaultSignerContractTests(unittest.TestCase):
    """Only a fake runner and literal NOT-A-KEY placeholders are used here."""
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        cli = self.root / "desktop/node_modules/@tauri-apps/cli"
        cli.mkdir(parents=True)
        self.package = cli / "package.json"
        self.package.write_text(json.dumps({"version": "2.12.2"}))
        (cli / "tauri.js").write_text("fixture, never executed")
        self.payload = self.root / "fixture.bsdiff"
        self.payload.write_bytes(b"BSDIFF40 fixture, never installed")
        self.calls = []

    def runner(self, arguments, **options):
        self.calls.append((arguments, options))
        return SimpleNamespace(returncode=0, stdout=b"")

    def environment(self, **changes):
        values = {"GITHUB_ACTIONS": "true", "GITHUB_REF": "refs/tags/v0.2.1",
                  "TAURI_SIGNING_PRIVATE_KEY": "NOT-A-KEY-test-placeholder",
                  "TAURI_SIGNING_PRIVATE_KEY_PASSWORD": "NOT-A-PASSWORD-test-placeholder",
                  "TAURI_SIGNING_PRIVATE_KEY_PATH": "/must-not-be-read",
                  "PATH": "/fixture-bin"}
        values.update(changes)
        return patch.dict(delta.os.environ, values, clear=True)

    def test_official_signer_command_binds_version_and_uses_only_key_environment(self):
        with self.environment():
            delta.TauriSigner(self.root, runner=self.runner)(self.payload, "0.2.1")
        arguments, options = self.calls[0]
        self.assertEqual(arguments[2:], ["signer", "sign", "--app-version", "0.2.1", str(self.payload)])
        self.assertEqual(arguments[0], "node")
        self.assertFalse(any("NOT-A-" in argument for argument in arguments))
        self.assertNotIn("TAURI_SIGNING_PRIVATE_KEY_PATH", options["env"])
        self.assertEqual(options["env"]["TAURI_SIGNING_PRIVATE_KEY"], "NOT-A-KEY-test-placeholder")
        self.assertEqual(options["env"]["TAURI_SIGNING_PRIVATE_KEY_PASSWORD"], "NOT-A-PASSWORD-test-placeholder")

    def test_non_tag_job_wrong_cli_or_missing_key_never_invokes_signer(self):
        for changes in ({"GITHUB_ACTIONS": "false"}, {"GITHUB_REF": "refs/heads/main"},
                        {"GITHUB_REF": "refs/tags/v0.2.2"}, {"TAURI_SIGNING_PRIVATE_KEY": ""}):
            with self.environment(**changes), self.assertRaises(ValueError):
                delta.TauriSigner(self.root, runner=self.runner)(self.payload, "0.2.1")
        self.package.write_text(json.dumps({"version": "2.12.1"}))
        with self.environment(), self.assertRaisesRegex(ValueError, "2.12.2"):
            delta.TauriSigner(self.root, runner=self.runner)(self.payload, "0.2.1")
        self.assertFalse(self.calls)


class DeltaCliTests(unittest.TestCase):
    def test_cli_failure_is_not_reported_as_success(self):
        output, errors = io.StringIO(), io.StringIO()
        with patch.object(delta, "add_deltas", side_effect=ValueError("fixture rejection")), \
                redirect_stdout(output), redirect_stderr(errors):
            result = delta.main(["--output", "assets", "--source-root", ".", "--version", "0.2.1"])
        self.assertEqual(result, 1)
        self.assertNotIn("Verified", output.getvalue())
        self.assertIn("fixture rejection", errors.getvalue())

    def test_verify_only_routes_to_gate_without_signer(self):
        with patch.object(delta, "verify_delta_release", return_value={"deltas": {}}) as verify, \
                patch.object(delta, "add_deltas") as add, redirect_stdout(io.StringIO()):
            self.assertEqual(delta.main(["--output", "assets", "--source-root", ".", "--version", "0.2.1", "--verify-only"]), 0)
        verify.assert_called_once()
        add.assert_not_called()

    def test_checked_runner_suppresses_logs_and_wraps_tool_timeout(self):
        for runner in (lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout=b"private child diagnostic"),
                       lambda *args, **kwargs: (_ for _ in ()).throw(subprocess.TimeoutExpired("fixture", 1))):
            with self.assertRaisesRegex(ValueError, "release delta tool failed") as caught:
                delta.run_checked(runner, ["fixture"])
            self.assertNotIn("private", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
