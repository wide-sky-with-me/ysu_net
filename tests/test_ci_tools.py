"""Static CI contracts only; never download, install, build, or execute a tool here."""
import json
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
ACTION = ".github/actions/setup-delta-tools"
ACTION_REF = f"./{ACTION}"
ARCHIVE_URL = "https://github.com/jedisct1/minisign/releases/download/0.12/minisign-0.12-linux.tar.gz"
ARCHIVE_SHA256 = "9a599b48ba6eb7b1e80f12f36b94ceca7c00b7a5173c95c3efc88d9822957e73"
CALLERS = (
    ("test.yml", "test", "python -m unittest discover -s tests -v"),
    ("tauri.yml", "build", "Frontend and native build entry checks"),
    ("tauri.yml", "release", "python -m unittest tests.test_update_manifest"),
    ("updater-delta-preflight.yml", "public-preflight", "python3 packaging/updater_delta_fixture.py --output"),
)


def workflow(name):
    return (ROOT / ".github/workflows" / name).read_text(encoding="utf-8")


def job_block(text, name):
    """Inspect our fixed job indentation, not a general-purpose YAML parser."""
    match = re.search(rf"(?m)^  {re.escape(name)}:\s*$", text)
    if match is None:
        raise AssertionError(f"required workflow job is absent: {name}")
    tail = text[match.end():]
    next_job = re.search(r"(?m)^  [A-Za-z0-9_-]+:\s*$", tail)
    return tail[:next_job.start()] if next_job else tail


def step_blocks(job):
    starts = [match.start() for match in re.finditer(r"(?m)^      - ", job)]
    return [job[start:end] for start, end in zip(starts, starts[1:] + [len(job)])]


class DeltaToolConfigurationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.action_text = (ROOT / ACTION / "action.yml").read_text(encoding="utf-8")
        # JSON is valid YAML metadata and needs no extra parser dependency.
        cls.action = json.loads(cls.action_text)
        cls.steps = cls.action["runs"]["steps"]

    def test_action_has_no_inputs_or_private_environment(self):
        self.assertEqual(set(self.action), {"name", "description", "runs"})
        self.assertEqual(self.action["runs"]["using"], "composite")
        self.assertEqual(len(self.steps), 3)
        for step in self.steps:
            self.assertEqual(set(step), {"name", "shell", "run"})
            self.assertEqual(step["shell"], "bash")
            self.assertTrue(step["run"].startswith("set -euo pipefail\n"))
        for forbidden in ("${{", "TAURI_SIGNING_", "secrets.", "GH_TOKEN", "GITHUB_TOKEN"):
            self.assertNotIn(forbidden, self.action_text)

    def test_host_guard_runs_before_any_installation(self):
        guard = self.steps[0]["run"]
        for restriction in ('"${GITHUB_ACTIONS:-}" != true', '"${RUNNER_OS:-}" != Linux', '"${RUNNER_ARCH:-}" != X64'):
            self.assertIn(restriction, guard)
        self.assertIn("exit 1", guard)
        self.assertNotIn("cargo install", guard)
        self.assertNotIn("curl --", guard)

    def test_minisign_archive_is_authenticated_before_extraction_and_execution(self):
        script = self.steps[1]["run"]
        self.assertIn(ARCHIVE_URL, script)
        self.assertIn(ARCHIVE_SHA256, script)
        self.assertIn("--proto '=https' --proto-redir '=https' --tlsv1.2 --fail", script)
        self.assertLess(script.index("sha256sum -c -"), script.index("tar -xzf"))
        self.assertLess(script.index("tar -xzf"), script.index('"$verifier/minisign" -v'))
        self.assertIn("--strip-components=2 --no-same-owner minisign-linux/x86_64/minisign", script)
        self.assertIn("""test "$("$verifier/minisign" -v)" = 'minisign 0.12'""", script)
        self.assertIn('>> "${GITHUB_PATH:?}"', script)

    def test_qbsdiff_uses_an_exact_requirement_and_checks_both_binaries(self):
        script = self.steps[2]["run"]
        installs = [line for line in script.splitlines() if line.startswith("cargo install ")]
        self.assertEqual(installs, ["cargo install qbsdiff --version '=1.4.4' --features cmd"])
        self.assertNotIn("--locked", installs[0])
        self.assertIn("self-dependency to 1.4.3", script)
        for tool in ("qbsdiff", "qbspatch"):
            self.assertIn(f'test "$({tool} --version)" = \'{tool} 1.4.4\'', script)

    def test_all_four_callers_prepare_tools_before_their_tests(self):
        for name, job_name, required_gate in CALLERS:
            with self.subTest(workflow=name, job=job_name):
                job = job_block(workflow(name), job_name)
                steps = step_blocks(job)
                tool_steps = [i for i, step in enumerate(steps) if f"uses: {ACTION_REF}" in step]
                self.assertEqual(len(tool_steps), 1)
                tool_index = tool_steps[0]
                checkout = next(i for i, step in enumerate(steps) if "uses: actions/checkout@" in step)
                rust = next(i for i, step in enumerate(steps) if "uses: dtolnay/rust-toolchain@stable" in step)
                gate = next(i for i, step in enumerate(steps) if required_gate in step)
                self.assertLess(checkout, rust)
                self.assertLess(rust, tool_index)
                self.assertLess(tool_index, gate)
                self.assertEqual(job.count("uses: dtolnay/rust-toolchain@stable"), 1)
                tool_step = steps[tool_index]
                self.assertNotRegex(tool_step, r"(?m)^\s+(?:env|with):")
                self.assertNotIn("TAURI_SIGNING_", job.split("    steps:", 1)[0])
                if name == "tauri.yml" and job_name == "build":
                    self.assertIn("if: runner.os == 'Linux'", tool_step)
                else:
                    self.assertRegex(job, r"(?m)^    runs-on: ubuntu-[a-z0-9.]+$")

    def test_workflow_filters_cover_shared_action_and_installation_is_not_duplicated(self):
        native_triggers = workflow("tauri.yml").split("jobs:", 1)[0]
        preflight_triggers = workflow("updater-delta-preflight.yml").split("jobs:", 1)[0]
        self.assertEqual(native_triggers.count(f"{ACTION}/**"), 2)
        self.assertEqual(preflight_triggers.count(f"{ACTION}/**"), 1)
        for name in {caller[0] for caller in CALLERS}:
            text = workflow(name)
            self.assertNotIn("cargo install qbsdiff", text)
            self.assertNotIn(ARCHIVE_URL, text)
            self.assertNotRegex(text, r"apt-get install[^\n]*\bminisign\b")
            self.assertNotRegex(text, r"GITHUB_ACTIONS\s*[:=]\s*['\"]?false")

    def test_real_integration_and_existing_release_gates_remain_enabled(self):
        integration = (ROOT / "tests/test_delta_signature_integration.py").read_text(encoding="utf-8")
        self.assertIn('raise AssertionError("Linux cloud delta integration requires qbsdiff/qbspatch/minisign")', integration)
        mock = job_block(workflow("test.yml"), "test")
        for gate in ("uv sync --locked --extra browser", "python -m unittest discover -s tests -v", "uv build"):
            self.assertIn(gate, mock)
        native = job_block(workflow("tauri.yml"), "build")
        self.assertIn("cargo test --locked --manifest-path desktop/src-tauri/Cargo.toml", native)
        self.assertIn("-p 'test_*delta*.py'", native)
        release = job_block(workflow("tauri.yml"), "release")
        for gate in ("if: startsWith(github.ref, 'refs/tags/v')", "needs: build", "packaging/tauri_delta.py --verify-only", "sha256sum -c SHA256SUMS", "gh release create"):
            self.assertIn(gate, release)


if __name__ == "__main__":
    unittest.main()
