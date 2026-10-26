from contextlib import redirect_stderr, redirect_stdout
import importlib.util
import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("check_community", ROOT / "scripts/check_community.py")
community = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(community)
PUBLISH_SPEC = importlib.util.spec_from_file_location("publish_wiki", ROOT / "scripts/publish_wiki.py")
publisher = importlib.util.module_from_spec(PUBLISH_SPEC)
PUBLISH_SPEC.loader.exec_module(publisher)


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

class WikiExportSafetyTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.source = self.root / "source/docs/wiki"
        self.source.mkdir(parents=True)
        self.target = self.root / "wiki"
        self.target.mkdir()
        (self.target / ".git").mkdir()
        (self.source / "Home.md").write_text("# Home\n[Guide](Guide.md#section)\n", encoding="utf-8")
        (self.source / "_Sidebar.md").write_text("[Home](Home.md)\n", encoding="utf-8")
        (self.source / "Guide.md").write_text("# Guide\n## section\n", encoding="utf-8")

    def test_empty_or_missing_required_reviewed_pages_fail_before_any_export(self):
        for missing in ("all", "Home.md", "_Sidebar.md"):
            source = self.root / missing.replace(".md", "")
            source.mkdir()
            if missing != "all":
                for name in ("Home.md", "_Sidebar.md"):
                    if name != missing:
                        (source / name).write_text("# Fixture\n", encoding="utf-8")
            with self.subTest(missing=missing), self.assertRaisesRegex(ValueError, "Home / _Sidebar"):
                publisher.prepare_exports(source, self.target)
            self.assertEqual(sorted(p.name for p in self.target.iterdir()), [".git"])

    def test_links_convert_only_reviewed_pages_and_additional_target_pages_are_preserved(self):
        extra = self.target / "Extra.md"
        extra.write_text("# Keep extra page\n", encoding="utf-8")
        plan = publisher.prepare_exports(self.source, self.target)
        self.assertEqual(len(plan), 3)
        for destination, content in plan:
            publisher.replace_page(destination, content)
        self.assertIn(f"[Guide]({publisher.WIKI_URL}/Guide#section)", (self.target / "Home.md").read_text())
        self.assertEqual(extra.read_text(), "# Keep extra page\n")
        self.assertFalse(list(self.target.glob(".ysu-wiki-*.tmp")))
        (self.source / "Home.md").write_text("[Unreviewed](Extra.md)\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "未指向受审查源文件"):
            publisher.prepare_exports(self.source, self.target)
        self.assertEqual(extra.read_text(), "# Keep extra page\n")

    def test_late_and_dangling_symlink_targets_abort_entire_preflight(self):
        home = self.target / "Home.md"
        home.write_text("# Existing home\n", encoding="utf-8")
        late = self.target / "_Sidebar.md"
        external = self.root / "external.md"
        for dangling in (False, True):
            if not dangling:
                external.write_text("# Outside untouched\n", encoding="utf-8")
            try:
                late.symlink_to(external if not dangling else self.root / "missing.md")
            except OSError:
                self.skipTest("symlink creation unavailable")
            with self.subTest(dangling=dangling), self.assertRaisesRegex(ValueError, "符号链接"):
                publisher.prepare_exports(self.source, self.target)
            self.assertEqual(home.read_text(), "# Existing home\n")
            self.assertFalse((self.target / "Guide.md").exists())
            self.assertEqual(external.read_text(), "# Outside untouched\n")
            late.unlink()

    def test_target_directory_is_rejected_during_preflight(self):
        (self.target / "Home.md").mkdir()
        with self.assertRaisesRegex(ValueError, "不是普通文件"):
            publisher.prepare_exports(self.source, self.target)
        self.assertFalse((self.target / "Guide.md").exists())

    def test_replace_failure_cleans_only_its_own_temp_and_preserves_existing_destination(self):
        home = self.target / "Home.md"
        home.write_text("# Keep old inode\n", encoding="utf-8")
        unrelated = self.target / ".ysu-wiki-unrelated.tmp"
        unrelated.write_text("keep unrelated file", encoding="utf-8")
        before = set(self.target.iterdir())
        with patch.object(publisher.os, "replace", side_effect=PermissionError("injected replace failure")), self.assertRaises(OSError):
            publisher.replace_page(home, "# New content\n")
        self.assertEqual(home.read_text(), "# Keep old inode\n")
        self.assertEqual(unrelated.read_text(), "keep unrelated file")
        self.assertEqual(set(self.target.iterdir()), before)

    def test_fsync_failure_closes_and_removes_the_new_temporary_file(self):
        home = self.target / "Home.md"
        home.write_text("# Existing\n", encoding="utf-8")
        before = set(self.target.iterdir())
        with patch.object(publisher.os, "fsync", side_effect=OSError("injected sync failure")), self.assertRaises(OSError):
            publisher.replace_page(home, "# New\n")
        self.assertEqual(home.read_text(), "# Existing\n")
        self.assertEqual(set(self.target.iterdir()), before)

    def test_partial_write_failure_cleans_the_created_temporary_file(self):
        home = self.target / "Home.md"
        home.write_text("# Existing\n", encoding="utf-8")
        factory = publisher.tempfile.NamedTemporaryFile

        class PartialWriter:
            def __init__(self, stream):
                self.stream = stream
                self.name = stream.name

            def __enter__(self):
                return self

            def __exit__(self, *args):
                self.stream.close()

            def write(self, content):
                self.stream.write(content[:3])
                raise OSError("injected partial write failure")

        def broken_stream(*args, **kwargs):
            return PartialWriter(factory(*args, **kwargs))

        before = set(self.target.iterdir())
        with patch.object(publisher.tempfile, "NamedTemporaryFile", side_effect=broken_stream), self.assertRaises(OSError):
            publisher.replace_page(home, "# New data\n")
        self.assertEqual(home.read_text(), "# Existing\n")
        self.assertEqual(set(self.target.iterdir()), before)

    def test_exports_are_per_page_not_a_whole_site_transaction(self):
        plan = publisher.prepare_exports(self.source, self.target)
        second = plan[1][0]
        second.write_text("# Previous second page\n", encoding="utf-8")
        replace = publisher.os.replace
        calls = 0

        def fail_second(source, destination):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("injected second page failure")
            return replace(source, destination)

        with patch.object(publisher.os, "replace", side_effect=fail_second), self.assertRaises(OSError):
            for destination, content in plan:
                publisher.replace_page(destination, content)
        self.assertEqual(plan[0][0].read_text(), plan[0][1])
        self.assertEqual(second.read_text(), "# Previous second page\n")
        self.assertFalse(plan[2][0].exists())
        self.assertFalse(list(self.target.glob(".ysu-wiki-*.tmp")))

    def test_main_reuses_running_python_and_keeps_origin_clean_outside_gates(self):
        argv = ["publish_wiki.py", str(self.target)]
        root = self.root / "source"
        with patch.object(publisher, "ROOT", root), patch.object(sys, "argv", argv), \
                patch.object(publisher.subprocess, "check_output", side_effect=[next(iter(publisher.ALLOWED_REMOTES)), ""]), \
                patch.object(publisher.subprocess, "run") as checker, redirect_stdout(io.StringIO()):
            self.assertEqual(publisher.main(), 0)
        checker.assert_called_once_with([sys.executable, str(root / "scripts/check_community.py")], check=True)
        self.assertFalse(list(self.target.glob(".ysu-wiki-*.tmp")))
        for replies in (["https://github.com/other/project.wiki.git"],
                        [next(iter(publisher.ALLOWED_REMOTES)), " M Home.md\n"]):
            with patch.object(publisher, "ROOT", root), patch.object(sys, "argv", argv), \
                    patch.object(publisher.subprocess, "check_output", side_effect=replies), \
                    patch.object(publisher, "replace_page") as writer, redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as result:
                publisher.main()
            self.assertEqual(result.exception.code, 2)
            writer.assert_not_called()
        with patch.object(publisher, "ROOT", self.target), patch.object(sys, "argv", argv), \
                patch.object(publisher.subprocess, "check_output") as git, redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as result:
            publisher.main()
        self.assertEqual(result.exception.code, 2)
        git.assert_not_called()

    def test_clean_tracked_hardlink_does_not_modify_outside_inode_or_commit(self):
        # Real Git records content, not the hard-link relationship. Old write_text
        # modified the outside inode even though this clone was completely clean.
        target = self.root / "hardlink-wiki"
        target.mkdir()

        def git(*args):
            return subprocess.check_output(["git", "-C", str(target), "-c", "user.name=Fixture",
                                            "-c", "user.email=fixture@example.invalid", *args], text=True)

        git("init", "-q")
        git("remote", "add", "origin", "https://github.com/wide-sky-with-me/ysu_net.wiki.git")
        external = self.root / "outside-hardlink.md"
        external.write_text("# Outside must remain identical\n", encoding="utf-8")
        home = target / "Home.md"
        os.link(external, home)
        extra = target / "Extra.md"
        extra.write_text("# Keep extra page\n", encoding="utf-8")
        git("add", "Home.md", "Extra.md")
        git("commit", "-qm", "fixture")
        original_head = git("rev-parse", "HEAD")
        self.assertEqual(git("status", "--porcelain"), "")
        self.assertTrue(os.path.samefile(home, external))
        original_bytes, original_stat = external.read_bytes(), external.stat()
        result = subprocess.run([sys.executable, str(ROOT / "scripts/publish_wiki.py"), str(target)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(external.read_bytes(), original_bytes)
        self.assertEqual((external.stat().st_dev, external.stat().st_ino), (original_stat.st_dev, original_stat.st_ino))
        self.assertFalse(os.path.samefile(home, external))
        self.assertIn(f"{publisher.WIKI_URL}/Quick-Start", home.read_text(encoding="utf-8"))
        self.assertEqual(extra.read_text(), "# Keep extra page\n")
        self.assertEqual(git("rev-parse", "HEAD"), original_head)
        self.assertFalse(list(target.glob(".ysu-wiki-*.tmp")))



if __name__ == "__main__":
    unittest.main()
