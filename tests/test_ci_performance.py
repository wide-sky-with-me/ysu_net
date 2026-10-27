"""Static parallel-CI contracts; never start a server, compiler, browser, or tool."""
import re
import unittest

from tests.test_ci_tools import job_block, step_blocks, workflow


BROWSER_SCRIPTS = (
    "packaging/tauri_web_smoke.py",
    "desktop/tests/rust_desktop_preview.py",
    "desktop/tests/multi_account_preview.py",
    "desktop/tests/rounded_desktop_preview.py",
    "desktop/tests/theme_palette_preview.py",
    "desktop/tests/about_preview.py",
    "desktop/tests/state_observer_preview.py",
    "desktop/tests/startup_feedback_preview.py",
    "desktop/tests/feedback_preview.py",
    "desktop/tests/connection_motion_preview.py",
)

# Preserve the complete pre-split acceptance run, not just its script names.
BROWSER_RUN = r"""mkdir -p build
npm --prefix desktop run preview -- --port 1422 --strictPort > build/tauri-preview.log 2>&1 &
server=$!
trap 'kill "$server" 2>/dev/null || true' EXIT
for attempt in {1..40}; do
  if curl --fail --silent http://127.0.0.1:1422/ > /dev/null; then break; fi
  if [ "$attempt" -eq 40 ]; then cat build/tauri-preview.log; exit 1; fi
  sleep 0.25
done
uv run --no-sync python packaging/tauri_web_smoke.py --url http://127.0.0.1:1422/ \
  --browser "$(command -v google-chrome)" --output dist/rust-desktop-preview/compatibility
uv run --no-sync python desktop/tests/rust_desktop_preview.py --url http://127.0.0.1:1422/ \
  --browser "$(command -v google-chrome)"
uv run --no-sync python desktop/tests/multi_account_preview.py --url http://127.0.0.1:1422/ \
  --browser "$(command -v google-chrome)" --output dist/rust-desktop-preview/multi-account
uv run --no-sync python desktop/tests/rounded_desktop_preview.py --url http://127.0.0.1:1422/ \
  --browser "$(command -v google-chrome)" --output dist/rust-desktop-preview/rounded
uv run --no-sync python desktop/tests/theme_palette_preview.py --url http://127.0.0.1:1422/ \
  --browser "$(command -v google-chrome)" --output dist/rust-desktop-preview/palettes
uv run --no-sync python desktop/tests/about_preview.py --url http://127.0.0.1:1422/ \
  --browser "$(command -v google-chrome)" --output dist/rust-desktop-preview/about
uv run --no-sync python desktop/tests/state_observer_preview.py --url http://127.0.0.1:1422/ \
  --browser "$(command -v google-chrome)" --output dist/rust-desktop-preview/state-observer
uv run --no-sync python desktop/tests/startup_feedback_preview.py --url http://127.0.0.1:1422/ \
  --browser "$(command -v google-chrome)" --output dist/rust-desktop-preview/startup-feedback
uv run --no-sync python desktop/tests/feedback_preview.py --url http://127.0.0.1:1422/ \
  --browser "$(command -v google-chrome)" --output dist/rust-desktop-preview/feedback
uv run --no-sync python desktop/tests/connection_motion_preview.py --url http://127.0.0.1:1422/ \
  --browser "$(command -v google-chrome)" --output dist/connection-motion-20261025/ci
"""


def named_step(job, name):
    matches = [step for step in step_blocks(job) if step.startswith(f"      - name: {name}\n")]
    if len(matches) != 1:
        raise AssertionError(f"expected one required CI step: {name}")
    return matches[0]


def run_block(step):
    _, marker, body = step.partition("        run: |\n")
    if not marker:
        raise AssertionError("required multiline run block is absent")
    lines = body.rstrip("\n").splitlines()
    if any(line and not line.startswith("          ") for line in lines):
        raise AssertionError("unexpected field after the run block")
    return "\n".join(line[10:] for line in lines) + "\n"


class ParallelBrowserAcceptanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = workflow("tauri.yml")
        cls.native = job_block(cls.text, "build")
        cls.browser = job_block(cls.text, "browser-acceptance")
        cls.format_source = job_block(cls.text, "format-source")
        cls.release = job_block(cls.text, "release")

    def test_complete_browser_run_is_moved_verbatim_and_each_script_runs_once(self):
        step = named_step(self.browser, "Built frontend browser acceptance")
        self.assertEqual(run_block(step), BROWSER_RUN)
        self.assertIn("        if: runner.os == 'Linux'\n", step)
        actual = re.findall(r"(?m)^uv run --no-sync python (\S+\.py) --url ", run_block(step))
        self.assertEqual(actual, list(BROWSER_SCRIPTS))
        for script in BROWSER_SCRIPTS:
            with self.subTest(script=script):
                self.assertEqual(self.text.count(script), 1)
                self.assertNotIn(script, self.native)
        self.assertNotIn("Reject UI regressions before expensive native bundling", self.native)

    def test_browser_job_is_independent_and_both_product_jobs_skip_format_only(self):
        for job in (self.native, self.browser):
            header = job.split("    steps:", 1)[0]
            self.assertIn("    if: ${{ inputs.format_only != true }}\n", header)
            self.assertIn("    timeout-minutes: 45\n", header)
            self.assertNotRegex(header, r"(?m)^    needs:")
        self.assertIn("    runs-on: ubuntu-22.04\n", self.browser)
        self.assertNotIn("strategy:", self.browser)
        self.assertNotIn("continue-on-error:", self.text)

    def test_browser_preparation_keeps_locked_inputs_and_actual_runtime_requirements(self):
        for required in (
            "uses: actions/checkout@v4", "uses: actions/setup-node@v4",
            'node-version: "24"', "cache-dependency-path: desktop/package-lock.json",
            "uses: astral-sh/setup-uv@v6", 'python-version: "3.12"',
            "npm ci --prefix desktop", "uv sync --locked --group desktop-test",
            "npm --prefix desktop run build", 'PYTHONUTF8: "1"', "shell: bash",
        ):
            self.assertIn(required, self.browser)
        prerequisites = named_step(self.browser, "Browser acceptance prerequisites")
        self.assertIn('chrome="$(command -v google-chrome)"', prerequisites)
        self.assertIn('test -x "$chrome"', prerequisites)
        self.assertIn("sudo apt-get install -y fonts-noto-cjk ffmpeg", prerequisites)
        acceptance = self.browser.index("      - name: Built frontend browser acceptance\n")
        for preparation in (
            "uses: actions/checkout@v4", "uses: actions/setup-node@v4",
            "uses: astral-sh/setup-uv@v6", "sudo apt-get install",
            "npm ci --prefix desktop", "uv sync --locked --group desktop-test",
            "npm --prefix desktop run build",
        ):
            self.assertLess(self.browser.index(preparation), acceptance)
        self.assertLess(self.browser.index("npm ci --prefix desktop"),
                        self.browser.index("npm --prefix desktop run build"))
        for forbidden in ("secrets.", "TAURI_SIGNING_", "GH_TOKEN", "cargo ", "rust-toolchain", "setup-delta-tools"):
            self.assertNotIn(forbidden, self.browser)

    def test_browser_evidence_is_retained_on_failure_without_artifact_name_collisions(self):
        uploads = [step for step in step_blocks(self.browser) if "uses: actions/upload-artifact@v4" in step]
        self.assertEqual(len(uploads), 1)
        upload = uploads[0]
        for required in (
            "        if: always()\n", "name: rust-desktop-preview-linux-x64\n",
            "if-no-files-found: error", "dist/rust-desktop-preview/",
            "dist/connection-motion-20261025/**", "build/tauri-preview.log",
        ):
            self.assertIn(required, upload)
        self.assertNotIn("name: rust-desktop-preview-linux-x64", self.native)
        for step in step_blocks(self.browser):
            if step != upload:
                self.assertNotIn("always()", step)

    def test_format_only_remains_only_the_original_rust_formatting_job(self):
        header = self.format_source.split("    steps:", 1)[0]
        self.assertIn("    if: ${{ github.event_name == 'workflow_dispatch' && inputs.format_only == true }}\n", header)
        runs = [run_block(step) for step in step_blocks(self.format_source) if "        run: |\n" in step]
        self.assertEqual(runs, [
            "cargo fmt --manifest-path desktop/src-tauri/Cargo.toml --all\n"
            "cargo fmt --manifest-path desktop/crates/ysu-auth/Cargo.toml --all\n"
        ])
        for forbidden in ("npm ", "apt-get", "cargo test", "cargo build", "setup-uv", "browser-acceptance"):
            self.assertNotIn(forbidden, self.format_source)
        self.assertIn("name: delta-formatted-source", self.format_source)

    def test_release_requires_all_native_targets_and_browser_success(self):
        header = self.release.split("    steps:", 1)[0]
        self.assertIn("    if: startsWith(github.ref, 'refs/tags/v')\n", header)
        self.assertIn("    needs: [build, browser-acceptance]\n", header)
        self.assertNotIn("always()", self.release)
        self.assertNotIn("continue-on-error", self.release)
        self.assertNotIn("needs.", header)
        matrix = re.findall(
            r"(?m)^          - os: ([^\n]+)\n            name: ([^\n]+)\n"
            r"            bundles: ([^\n]+)\n            binary: ([^\n]+)$", self.native,
        )
        self.assertEqual(matrix, [
            ("ubuntu-22.04", "linux-x64", "deb", "desktop/src-tauri/target/release/ysu-net"),
            ("windows-2022", "windows-x64", "nsis", "desktop/src-tauri/target/release/ysu-net.exe"),
            ("macos-15", "macos-arm64", "app,dmg", "desktop/src-tauri/target/release/bundle/macos/YSU Net.app/Contents/MacOS/ysu-net"),
            ("macos-15-intel", "macos-x64", "app,dmg", "desktop/src-tauri/target/release/bundle/macos/YSU Net.app/Contents/MacOS/ysu-net"),
        ])
        self.assertIn("      fail-fast: false\n", self.native)

    def test_native_frontend_authentication_and_real_chromium_gates_remain(self):
        frontend = named_step(self.native, "Frontend and native build entry checks")
        for command in (
            "npm --prefix desktop run check", "npm --prefix desktop test",
            "npm --prefix desktop run test:build", "npm --prefix desktop run build",
            "Public signed fixture bytes match the cloud-generated identity.",
        ):
            self.assertIn(command, frontend)
        rust = named_step(self.native, "Rust authentication and runtime tests")
        for command in (
            "npm --prefix desktop run native:build -- --prepare-only",
            "cargo fmt --manifest-path desktop/crates/ysu-auth/Cargo.toml --check",
            "cargo test --locked --manifest-path desktop/crates/ysu-auth/Cargo.toml",
            "cargo fmt --manifest-path desktop/src-tauri/Cargo.toml --check",
            "python3 packaging/tauri_tls_regression.py",
            "cargo test --locked --manifest-path desktop/src-tauri/Cargo.toml",
        ):
            self.assertIn(command, rust)
        chromium = named_step(self.native, "Real Chromium authentication fixtures")
        for platform in ("Linux)", "Windows)", "macOS)"):
            self.assertIn(platform, chromium)
        self.assertIn("cargo test --locked --manifest-path desktop/crates/ysu-auth/Cargo.toml -- --ignored --test-threads=1", chromium)
        self.assertNotRegex(chromium, r"(?m)^        if:")
        retained = named_step(self.native, "External acceptance tools and retained CLI regressions")
        for command in ("test_node_runtime.py", "test_system_browser.py", "tests.test_update_manifest tests.test_update_signature", "-p 'test_*delta*.py'"):
            self.assertIn(command, retained)
        self.assertIn("uses: ./.github/actions/setup-delta-tools", self.native)

    def test_native_bundling_signing_and_installed_smoke_gates_remain(self):
        ordinary = named_step(self.native, "Build ordinary native bundles without signing keys")
        self.assertIn("if: ${{ !startsWith(github.ref, 'refs/tags/v') || runner.os == 'Linux' }}", ordinary)
        self.assertIn('npm --prefix desktop run native:build -- "${args[@]}"', ordinary)
        self.assertNotIn("TAURI_SIGNING_", ordinary)
        signed = named_step(self.native, "Build signed updater bundles for release tags")
        self.assertIn("if: startsWith(github.ref, 'refs/tags/v') && runner.os != 'Linux'", signed)
        self.assertIn("npm --prefix desktop run native:build -- --bundles '${{ matrix.bundles }}' --signed-update", signed)
        for secret in ("TAURI_SIGNING_PRIVATE_KEY", "TAURI_SIGNING_PRIVATE_KEY_PASSWORD"):
            self.assertIn(f"{secret}: ${{{{ secrets.{secret} }}}}", signed)
        smoke = named_step(self.native, "Native WebView and lifecycle acceptance")
        self.assertIn("packaging/tauri_smoke.py", smoke)
        self.assertIn("packaging/tauri_linux_lifecycle.py", smoke)
        self.assertNotRegex(smoke, r"(?m)^        if:")
        for platform in ("Linux", "Windows", "macOS"):
            installed = named_step(self.native, f"Installed package acceptance ({platform})")
            self.assertIn(f"        if: runner.os == '{platform}'\n", installed)
            self.assertIn("packaging/tauri_smoke.py", installed)
        named_step(self.native, "Verify generated application icon envelopes")
        named_step(self.native, "Verify Windows application and installer icon pixels")

    def test_release_inventory_and_bundle_artifact_contracts_remain(self):
        for required in (
            "name: rust-desktop-${{ matrix.name }}", "name: rust-desktop-bundle-${{ matrix.name }}",
            "desktop/src-tauri/target/release/bundle/**/*.deb", "desktop/src-tauri/target/release/bundle/**/*.exe",
            "desktop/src-tauri/target/release/bundle/**/*.dmg", "desktop/src-tauri/target/release/bundle/**/*.exe.sig",
            "desktop/src-tauri/target/release/bundle/**/*.app.tar.gz", "desktop/src-tauri/target/release/bundle/**/*.app.tar.gz.sig",
        ):
            self.assertIn(required, self.native)
        for required in (
            "pattern: rust-desktop-bundle-*", "merge-multiple: false",
            "tests.test_update_manifest tests.test_update_signature tests.test_delta_manifest tests.test_delta_base",
            "packaging/tauri_delta.py --verify-only", "sha256sum -c SHA256SUMS",
            "gh release create", "--verify-tag", "uses: ./.github/actions/setup-delta-tools",
        ):
            self.assertIn(required, self.release)
        secret_steps = [step for step in step_blocks(self.release) if "secrets." in step]
        self.assertEqual(len(secret_steps), 1)
        self.assertTrue(secret_steps[0].startswith("      - name: Generate and sign worthwhile delta attachments for this release tag\n"))

    def test_no_cargo_profile_cache_or_target_change_is_bundled_with_parallelization(self):
        for forbidden in ("CARGO_PROFILE_", "CARGO_TARGET_DIR", "prefix-key:", "shared-key:", "--debug", "--profile"):
            self.assertNotIn(forbidden, self.text)
        self.assertIn('      CARGO_BUILD_JOBS: "2"\n', self.native)
        self.assertIn("          workspaces: |\n            desktop/src-tauri\n            desktop/crates/ysu-auth\n", self.native)


if __name__ == "__main__":
    unittest.main()
