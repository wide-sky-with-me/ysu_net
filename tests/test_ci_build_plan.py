"""CI scope contracts; these tests never compile or contact the network."""
import importlib.util
from pathlib import Path
import unittest

from tests.test_ci_tools import job_block, step_blocks, workflow
from tests.test_ci_performance import named_step, run_block, BROWSER_RUN

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("ysu_ci_build_plan", ROOT / "packaging/ci_build_plan.py")
planner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(planner)


class BuildPlanTests(unittest.TestCase):
    def test_branch_push_checks_all_platforms_without_implicitly_requesting_installers(self):
        for branch in ("main", "build/example", "fix/runtime"):
            for supplied in planner.TARGETS:
                with self.subTest(branch=branch, supplied=supplied):
                    self.assertEqual(planner.build_plan("push", f"refs/heads/{branch}", supplied),
                                     {"package_target": "checks", "full_browser": False})

    def test_tags_and_pull_requests_force_complete_acceptance_regardless_of_input(self):
        for event, ref in (("push", "refs/tags/v0.2.4"), ("push", "refs/tags/v1.0.0-beta.1"),
                           ("pull_request", "refs/pull/1/merge")):
            for supplied in (*planner.TARGETS, "invalid", "checks\nfull_browser=false"):
                with self.subTest(event=event, supplied=supplied):
                    self.assertEqual(planner.build_plan(event, ref, supplied),
                                     {"package_target": "all", "full_browser": True})

    def test_manual_package_targets_keep_full_browser_and_allow_checks_only(self):
        for target in planner.TARGETS:
            plan = planner.build_plan("workflow_dispatch", "refs/heads/build/example", target)
            self.assertEqual(plan["package_target"], target)
            self.assertEqual(plan["full_browser"], target != "checks")
        self.assertEqual(planner.build_plan("workflow_dispatch", "refs/heads/main")["package_target"], "all")
        for target in ("windows", "../all", "checks\nfull_browser=false"):
            with self.assertRaises(ValueError):
                planner.build_plan("workflow_dispatch", "refs/heads/main", target)

    def test_unsupported_events_do_not_silently_become_successful_checks(self):
        for event, ref in (("schedule", "refs/heads/main"), ("push", "refs/tags/unrelated")):
            with self.assertRaises(ValueError):
                planner.build_plan(event, ref)


class StagedWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = workflow("tauri.yml")
        cls.native = job_block(cls.text, "build")
        cls.browser = job_block(cls.text, "browser-acceptance")
        cls.preflight = job_block(cls.text, "preflight")

    def test_preflight_blocks_expensive_native_setup_on_format_or_frontend_errors(self):
        for command in ("cargo fmt --manifest-path desktop/crates/ysu-auth/Cargo.toml --all --check",
                        "cargo fmt --manifest-path desktop/src-tauri/Cargo.toml --all --check",
                        "npm --prefix desktop run check", "npm --prefix desktop test",
                        "npm --prefix desktop run test:build"):
            self.assertIn(command, self.preflight)
        for forbidden in ("cargo build", "cargo test", "apt-get", "secrets.", "continue-on-error"):
            self.assertNotIn(forbidden, self.preflight)
        self.assertIn("if: ${{ inputs.format_only != true }}", self.preflight)
        self.assertIn('python3 packaging/ci_build_plan.py --output "$GITHUB_OUTPUT"', self.preflight)
        for key in ("package_target", "full_browser"):
            self.assertIn(f"{key}: ${{{{ steps.plan.outputs.{key} }}}}", self.preflight)
        for job in (self.native, self.browser):
            self.assertIn("    needs: preflight\n", job)

    def test_every_native_delivery_step_forces_tags_and_prs_and_selects_manual_target(self):
        names = ["Build ordinary native bundles without signing keys", "Verify generated application icon envelopes",
                 "Verify Windows application and installer icon pixels", "Native WebView and lifecycle acceptance",
                 "Installed package acceptance (Linux)", "Installed package acceptance (Windows)",
                 "Installed package acceptance (macOS)"]
        guard = "(startsWith(github.ref, 'refs/tags/v') || github.event_name == 'pull_request' || needs.preflight.outputs.package_target == 'all' || needs.preflight.outputs.package_target == matrix.name)"
        for name in names:
            with self.subTest(step=name):
                self.assertIn(guard, named_step(self.native, name))
        ordinary_upload = next(s for s in step_blocks(self.native) if "name: rust-desktop-${{ matrix.name }}" in s)
        self.assertIn("always() && " + guard, ordinary_upload)
        # Actual source tests and platform-specific browser authentication never depend on packaging selection.
        for name in ("Frontend and native build entry checks", "Rust authentication and runtime tests",
                     "Real Chromium authentication fixtures", "External acceptance tools and retained CLI regressions"):
            self.assertNotIn("package_target", named_step(self.native, name))
        for target in ("windows-x64", "linux-x64", "macos-arm64", "macos-x64"):
            self.assertIn(f"name: {target}\n", self.native)
            self.assertIn(target, planner.TARGETS)

    def test_quick_browser_is_separate_from_unchanged_full_release_suite(self):
        full = named_step(self.browser, "Built frontend browser acceptance")
        quick = named_step(self.browser, "Quick frontend browser smoke")
        self.assertEqual(run_block(full), BROWSER_RUN)
        self.assertIn("startsWith(github.ref, 'refs/tags/v') || github.event_name == 'pull_request'", full)
        self.assertIn("needs.preflight.outputs.full_browser == 'true'", full)
        self.assertIn("!startsWith(github.ref, 'refs/tags/v')", quick)
        self.assertIn("github.event_name != 'pull_request'", quick)
        self.assertIn("needs.preflight.outputs.full_browser != 'true'", quick)
        for command in ("packaging/tauri_web_smoke.py", "--strictPort", "trap 'kill", "{1..40}"):
            self.assertIn(command, quick)
        self.assertIn("--output dist/rust-desktop-preview/quick", quick)
        for job in (self.native, self.browser):
            self.assertNotIn("continue-on-error", job)
        release = job_block(self.text, "release")
        self.assertIn("    needs: [build, browser-acceptance]\n", release)
        self.assertIn("    if: startsWith(github.ref, 'refs/tags/v')\n", release)


if __name__ == "__main__":
    unittest.main()
