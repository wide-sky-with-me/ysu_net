import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("check_community", ROOT / "scripts/check_community.py")
community = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(community)


class CommunityChecks(unittest.TestCase):
    def test_document_anchor_accepts_chinese_and_repeated_headings(self):
        self.assertEqual(community.headings("## 隐私与反馈\n## 隐私与反馈\n"), {"隐私与反馈", "隐私与反馈-1"})

    def test_link_checker_detects_missing_file_and_anchor(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            page = root / "Home.md"
            target = root / "Guide.md"
            target.write_text("# 指南\n", encoding="utf-8")
            original = community.ROOT
            community.ROOT = root
            try:
                errors = []
                community.check_links(page, "[好](Guide.md#指南) [错](Guide.md#缺失) [丢失](missing.md)", errors)
                self.assertEqual(len(errors), 2)
            finally:
                community.ROOT = original

    def test_broken_link_errors_do_not_echo_sensitive_targets(self):
        page = community.ROOT / "README.md"
        token_fixture = "ghp_" + "X" * 30
        targets = [f"missing/{token_fixture}.md", "/home/example/private.md"]
        for target in targets:
            with self.subTest(kind="redacted-link"):
                errors = []
                community.check_links(page, f"[示例]({target})", errors)
                self.assertTrue(errors)
                self.assertFalse(any(target in error or token_fixture in error for error in errors))
                self.assertTrue(all(error.startswith("README.md:1:") for error in errors))

    def test_form_requires_explicit_privacy_confirmation(self):
        path = community.ROOT / ".github/DISCUSSION_TEMPLATE/q-a.yml"
        errors = []
        community.check_form(path, {"body": [{"type": "input", "id": "question", "attributes": {"label": "问题"}}]}, errors)
        self.assertTrue(errors)

    def test_form_detects_duplicate_ids(self):
        path = community.ROOT / ".github/ISSUE_TEMPLATE/bug_report.yml"
        field = {"type": "input", "id": "version", "attributes": {"label": "版本"}}
        errors = []
        community.check_form(path, {"name": "反馈", "description": "说明", "body": [field, field]}, errors)
        self.assertTrue(any("重复" in error for error in errors))

    def test_form_accepts_required_privacy_checkbox(self):
        path = community.ROOT / ".github/DISCUSSION_TEMPLATE/q-a.yml"
        data = {"body": [
            {"type": "input", "id": "question", "attributes": {"label": "问题"}},
            {"type": "checkboxes", "id": "privacy", "attributes": {"label": "脱敏", "options": [{"label": "已移除识别信息", "required": True}]}},
        ]}
        errors = []
        community.check_form(path, data, errors)
        self.assertEqual(errors, [])

    def test_sensitive_rules_detect_fixture_without_printing_values(self):
        self.assertTrue(community.RULES["access-token"].search("ghp_" + "X" * 30))
        self.assertTrue(community.RULES["device-address"].search("192.0.2.1"))
        self.assertTrue(community.RULES["personal-home"].search("/home/example/project"))
        self.assertFalse(community.RULES["device-address"].search("地址：<IP>，路径：<USER_HOME>"))

    def test_wiki_export_preflights_all_symlinks_before_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            def git(*args):
                subprocess.run(["git", "-C", str(target), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", *args], check=True, capture_output=True)
            git("init", "-q")
            git("remote", "add", "origin", "https://github.com/wide-sky-with-me/ysu_net.wiki.git")
            (target / "Existing.md").write_text("# Existing\n", encoding="utf-8")
            (target / "Home.md").symlink_to("Existing.md")
            git("add", "Existing.md", "Home.md")
            git("commit", "-qm", "fixture")
            result = subprocess.run([sys.executable, str(ROOT / "scripts/publish_wiki.py"), str(target)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertFalse((target / "CLI-Reference.md").exists())
            self.assertEqual((target / "Existing.md").read_text(encoding="utf-8"), "# Existing\n")
            status = subprocess.check_output(["git", "-C", str(target), "status", "--porcelain"], text=True)
            self.assertEqual(status, "")

    def test_checked_in_community_assets_pass(self):
        self.assertEqual(community.main(), 0)


if __name__ == "__main__":
    unittest.main()
