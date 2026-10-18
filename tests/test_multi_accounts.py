from copy import deepcopy
from dataclasses import replace
import json
import os
import stat
from unittest.mock import patch

from tests.helpers import OfflineTestCase
from ysu_net.manager import accounts
from ysu_net.manager.config import Config, load_config, save_config, update_config
from ysu_net.manager.locking import configuration_write


class AccountBookTests(OfflineTestCase):
    def setUp(self):
        super().setUp()
        self.path = self.tmp / "private/config.json"
        self.config = Config(username="fixture-a", password="fixture-only")
        save_config(self.path, self.config)
        self.stack.enter_context(patch.dict(os.environ, {}, clear=True))

    def add(self, username="fixture-b", **kwargs):
        return accounts.save_account(self.path, username=username, password="fixture-only", **kwargs)

    def raw(self):
        return accounts.load_accounts(self.path, overlay=False)

    def test_view_synthetic_current_never_migrates(self):
        view = accounts.public_accounts(self.path)
        self.assertEqual(view["items"][0]["id"], "current")
        self.assertTrue(view["items"][0]["current"])
        self.assertTrue(view["items"][0]["password_set"])
        self.assertFalse(accounts.accounts_path(self.path).exists())
        self.assertFalse(view["auto_switch"])
        self.assertNotIn("password", view["items"][0])
        self.assertNotIn("fixture-only", json.dumps(view))

    def test_empty_activity_is_not_synthetic(self):
        save_config(self.path, Config())
        self.assertEqual(accounts.public_accounts(self.path)["items"], [])

    def test_path_shape_permissions_and_v1_contract(self):
        item = self.add(label="A")
        file = self.path.with_suffix(".accounts.json")
        self.assertEqual(accounts.accounts_path(self.path), file)
        self.assertEqual(stat.S_IMODE(file.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(file.parent.stat().st_mode), 0o700)
        self.assertRegex(item["id"], "^[0-9a-f]{32}$")
        self.assertEqual(set(self.raw()), {"version", "auto_switch", "accounts"})
        self.assertEqual(set(self.raw()["accounts"][0]), accounts.ACCOUNT_FIELDS)
        self.assertEqual(self.raw()["version"], 1)
        self.assertEqual(list(self.path.parent.glob(".accounts-*")), [])

    def test_config_overlay_wins_over_stale_mirror(self):
        item = self.add(username="fixture-a", label="active")
        update_config(self.path, password="latest-secret", service="中国移动", backend="browser")
        entry = accounts.load_accounts(self.path)["accounts"][0]
        self.assertEqual(entry["id"], item["id"])
        self.assertEqual((entry["password"], entry["service"], entry["backend"]),
                         ("latest-secret", "中国移动", "browser"))
        self.assertEqual(self.raw()["accounts"][0]["password"], "fixture-only")
        self.assertNotIn("latest-secret", json.dumps(accounts.public_accounts(self.path)))

    def test_current_save_allocates_id_without_environment_secrets(self):
        with patch.dict(os.environ, {"YSU_USER": "env-user", "YSU_PASS": "env-secret"}):
            item = accounts.save_account(self.path, id="current", username="fixture-a")
            self.assertTrue(accounts.public_accounts(self.path)["environment_override"])
        self.assertRegex(item["id"], "^[0-9a-f]{32}$")
        self.assertEqual(self.raw()["accounts"][0]["password"], "fixture-only")
        self.assertNotIn("env-secret", accounts.accounts_path(self.path).read_text())

    def test_new_account_requires_password(self):
        with self.assertRaises(ValueError):
            accounts.save_account(self.path, username="new")
        self.assertFalse(accounts.accounts_path(self.path).exists())

    def test_blank_password_update_retains_latest_active_config(self):
        item = self.add(username="fixture-a")
        update_config(self.path, password="latest")
        accounts.save_account(self.path, id=item["id"], username="fixture-a", password="", label="edited")
        self.assertEqual(load_config(self.path, environ={}).password, "latest")
        self.assertEqual(self.raw()["accounts"][0]["password"], "latest")

    def test_username_is_immutable_and_active_deletion_is_stopped(self):
        item = self.add(username="fixture-a")
        before = self.path.read_bytes(), accounts.accounts_path(self.path).read_bytes()
        with self.assertRaises(ValueError):
            accounts.save_account(self.path, id=item["id"], username="different", password="new")
        for id in (item["id"], "current"):
            with self.assertRaises(ValueError):
                accounts.delete_account(self.path, id)
        self.assertEqual((self.path.read_bytes(), accounts.accounts_path(self.path).read_bytes()), before)

    def test_non_active_deletion_and_revalidation(self):
        item = self.add()
        update_config(self.path, username="fixture-b")
        with self.assertRaises(ValueError):
            accounts.delete_account(self.path, item["id"])
        update_config(self.path, username="fixture-a")
        accounts.delete_account(self.path, item["id"])
        self.assertEqual(self.raw()["accounts"], [])

    def test_unknown_id_and_duplicate_username_are_stopped(self):
        item = self.add()
        for kwargs in ({"id": "f" * 32, "username": "other"}, {"username": "fixture-b"}):
            with self.assertRaises(ValueError):
                accounts.save_account(self.path, password="other", **kwargs)
        with self.assertRaises(ValueError):
            accounts.delete_account(self.path, "f" * 32)
        self.assertEqual(self.raw()["accounts"][0]["id"], item["id"])

    def test_strict_fields_types_ids_and_duplicate_entries(self):
        self.add()
        valid = self.raw()
        mutated = []
        for key, value in (("version", True), ("version", 2), ("auto_switch", 1), ("extra", "bad")):
            book = deepcopy(valid)
            book[key] = value
            mutated.append(book)
        for key, value in (("id", "current"), ("id", "A" * 32), ("label", "x" * 81),
                           ("username", ""), ("password", 1), ("service", "bad"),
                           ("backend", "shell"), ("enabled", 1), ("extra", "bad")):
            book = deepcopy(valid)
            book["accounts"][0][key] = value
            mutated.append(book)
        for duplicate in (deepcopy(valid["accounts"][0]),
                          dict(valid["accounts"][0], id="f" * 32),
                          dict(valid["accounts"][0], username="other")):
            book = deepcopy(valid)
            book["accounts"].append(duplicate)
            mutated.append(book)
        for book in mutated:
            with self.subTest(book=book), self.assertRaises(ValueError):
                accounts.validate_book(book)

    def test_duplicate_json_fields_and_oversized_file_fail_closed(self):
        file = accounts.accounts_path(self.path)
        for raw in ('{"version":1,"version":1,"auto_switch":false,"accounts":[]}',
                    'x' * (accounts.MAX_BYTES + 1), '\ud800'):
            with self.subTest(length=len(raw)):
                file.write_bytes(raw.encode("utf-8", errors="surrogatepass"))
                with self.assertRaises(ValueError):
                    accounts.load_accounts(self.path)
                self.assertTrue(accounts.public_accounts(self.path)["error"])

    def test_symlink_book_never_followed(self):
        fixture = self.tmp / "fixture.json"
        fixture.write_text('{"version":1,"auto_switch":false,"accounts":[]}')
        accounts.accounts_path(self.path).symlink_to(fixture)
        with self.assertRaises(ValueError):
            accounts.load_accounts(self.path)

    def test_count_and_serialized_size_limits(self):
        for index in range(32):
            self.add(username=f"fixture-{index}")
        with self.assertRaises(ValueError):
            self.add(username="fixture-overflow")
        with self.assertRaises(ValueError):
            accounts.prepare_switch(self.path, self.raw()["accounts"][0]["id"])
        self.assertEqual(len(self.raw()["accounts"]), 32)
        file_before = accounts.accounts_path(self.path).read_bytes()
        with self.assertRaises(ValueError):
            accounts.save_account(self.path, id=self.raw()["accounts"][0]["id"],
                                  username="fixture-0", password="x" * 65536)
        self.assertEqual(accounts.accounts_path(self.path).read_bytes(), file_before)

    def test_failed_active_metadata_write_keeps_config_authoritative(self):
        item = self.add(username="fixture-a")
        with patch.object(accounts, "_write_book", side_effect=PermissionError):
            with self.assertRaisesRegex(RuntimeError, "活动配置已保存"):
                accounts.save_account(self.path, id=item["id"], username="fixture-a", password="changed")
        self.assertEqual(load_config(self.path, environ={}).password, "changed")
        self.assertEqual(self.raw()["accounts"][0]["password"], "fixture-only")
        self.assertEqual(accounts.load_accounts(self.path)["accounts"][0]["password"], "changed")

    def test_prepare_flushes_latest_source_under_shared_write_lock(self):
        item = self.add()
        update_config(self.path, password="latest", service="中国联通")
        source, target = accounts.prepare_switch(self.path, item["id"])
        saved = next(entry for entry in self.raw()["accounts"] if entry["username"] == "fixture-a")
        self.assertEqual(saved["password"], "latest")
        self.assertEqual(saved["service"], "中国联通")
        self.assertEqual(source.password, "latest")
        self.assertTrue(accounts.unchanged_switch(self.path, source, target))

    def test_cas_preserves_unrelated_timing_changes(self):
        item = self.add(service="中国移动")
        source, target = accounts.prepare_switch(self.path, item["id"])
        update_config(self.path, check_interval=60, operation_timeout=100)
        accounts.commit_switch(self.path, source, target)
        stored = load_config(self.path, environ={})
        self.assertEqual((stored.username, stored.service, stored.check_interval, stored.operation_timeout),
                         ("fixture-b", "中国移动", 60, 100))

    def test_cas_stops_new_source_or_target_intent(self):
        item = self.add()
        for changed in ("source", "target"):
            save_config(self.path, self.config)
            source, target = accounts.prepare_switch(self.path, item["id"])
            if changed == "source":
                update_config(self.path, base="https://fixture.invalid", password="new")
            else:
                accounts.save_account(self.path, id=item["id"], username="fixture-b", password="new")
            before = self.path.read_bytes()
            with self.assertRaises(ValueError):
                accounts.commit_switch(self.path, source, target)
            self.assertEqual(self.path.read_bytes(), before)

    def test_rotation_requires_auto_and_two_effective_enabled_accounts(self):
        with self.assertRaises(ValueError):
            accounts.set_rotation(self.path, True, auto_reconnect=False)
        with self.assertRaises(ValueError):
            accounts.set_rotation(self.path, True, auto_reconnect=True)
        item = self.add(enabled=False)
        with self.assertRaises(ValueError):
            accounts.set_rotation(self.path, True, auto_reconnect=True)
        accounts.save_account(self.path, id=item["id"], username="fixture-b")
        accounts.set_rotation(self.path, True, auto_reconnect=True)
        self.assertTrue(self.raw()["auto_switch"])
        with patch.dict(os.environ, {"YSU_SERVICE": "校园网"}):
            with self.assertRaises(ValueError):
                accounts.set_rotation(self.path, True, auto_reconnect=True)
            accounts.set_rotation(self.path, False)
        self.assertFalse(self.raw()["auto_switch"])

    def test_deep_json_and_nonregular_book_fail_closed(self):
        file = accounts.accounts_path(self.path)
        file.write_text("[" * 2000 + "0" + "]" * 2000)
        with self.assertRaises(ValueError):
            accounts.load_accounts(self.path)
        file.unlink()
        if hasattr(os, "mkfifo"):
            os.mkfifo(file, 0o600)
            with self.assertRaises(ValueError):
                accounts.load_accounts(self.path)

    def test_write_enforces_private_existing_directory(self):
        self.path.parent.chmod(0o755)
        self.add()
        self.assertEqual(stat.S_IMODE(self.path.parent.stat().st_mode), 0o700)
