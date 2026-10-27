"""Shared synthetic SID outcomes, not an adoption of Rust's transport policy.

The CLI implementation remains unchanged. These tests do not send requests or
assert that Requests enforces the Rust HTTPS/origin/rewrite boundaries.
"""
import json
from pathlib import Path
from urllib.parse import urlparse

from tests.helpers import OfflineTestCase
from ysu_net.auth import api


class PortalEntryVariantTests(OfflineTestCase):
    def setUp(self):
        super().setUp()
        self.fixture = json.loads(
            (Path(__file__).parent / "fixtures" / "portal-entry-variants.json").read_text()
        )
        self.assertEqual(self.fixture["version"], 1)

    def test_both_fixed_sources_extract_the_same_synthetic_sid_from_history(self):
        fixture = self.fixture
        for source in fixture["sources"]:
            with self.subTest(source=source["id"]):
                chain = [source["url"], fixture["legacy_target"], fixture["https_target"]]
                self.assertEqual(api._extract_sid_from_chain(chain), fixture["session_id"])

    def test_fixed_source_parameters_are_not_guessed_to_be_session_ids(self):
        for source in self.fixture["sources"]:
            with self.subTest(source=source["id"]):
                self.assertIsNone(api._extract_sid_from_chain([source["url"]]))
                self.assertIsNone(api.extract_q(source["url"], "sessionId"))

    def test_normalized_landing_preserves_sid_and_the_original_query(self):
        fixture = self.fixture
        self.assertEqual(urlparse(fixture["legacy_target"]).query,
                         urlparse(fixture["https_target"]).query)
        for key in ("legacy_target", "https_target"):
            with self.subTest(target=key):
                self.assertEqual(api.extract_q(fixture[key], "sessionId"), fixture["session_id"])
