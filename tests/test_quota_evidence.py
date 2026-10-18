"""Offline cross-language quota contract; shared JSON is also asserted by ysu-auth."""
import copy
import json
import math
from pathlib import Path
import unittest

from ysu_net.auth.quota import classify_quota


_FIXTURE = Path(__file__).parent / 'fixtures' / 'account-quota.json'
_UNKNOWN = {'state': 'unknown', 'message': '剩余流量证据未知'}
_ZERO = {'state': 'zero_reported', 'message': '门户报告剩余流量为零'}


def raw(content='0 MB', title='剩余流量'):
    return {'accountInfo': [{'title': title, 'content': content}]}


class QuotaEvidenceTests(unittest.TestCase):
    def test_shared_raw_fixtures_full_contract(self):
        fixture = json.loads(_FIXTURE.read_text(encoding='utf-8'))
        self.assertEqual(fixture['version'], 1)
        self.assertGreaterEqual(len(fixture['cases']), 25)
        ids = [case['id'] for case in fixture['cases']]
        self.assertEqual(len(ids), len(set(ids)))
        for case in fixture['cases']:
            with self.subTest(case=case['id']):
                original = copy.deepcopy(case['raw'])
                self.assertEqual(classify_quota(case['raw']), case['expected'])
                self.assertEqual(case['raw'], original)
                if case['expected']['state'] == 'unlimited':
                    self.assertTrue(case['synthetic_rule'])

    def test_entry_limit_is_not_a_truncated_zero(self):
        unrelated = {'title': '在线设备', 'content': '1 台'}
        payload = raw()
        payload['accountInfo'].extend(copy.deepcopy(unrelated) for _ in range(255))
        self.assertEqual(classify_quota(payload), _ZERO)
        payload['accountInfo'].append(unrelated)
        self.assertEqual(classify_quota(payload), _UNKNOWN)

    def test_wrapper_limit_checks_whole_chain(self):
        payload = raw()
        for _ in range(5):
            payload = {'data': payload}
        self.assertEqual(classify_quota(payload), _ZERO)
        self.assertEqual(classify_quota({'data': payload}), _UNKNOWN)
        self.assertEqual(classify_quota({'accountInfo': raw()['accountInfo'], 'data': 1}), _UNKNOWN)

    def test_digit_limit_and_tiny_decimal_without_underflow(self):
        self.assertEqual(classify_quota(raw('0' * 128 + ' MB')), _ZERO)
        self.assertEqual(classify_quota(raw('0' * 129 + ' MB')), _UNKNOWN)
        content = '0.' + '0' * 126 + '1 GB'
        self.assertEqual(classify_quota(raw(content))['state'], 'available')
        self.assertEqual(classify_quota(raw('0.' + '0' * 127 + '1 GB')), _UNKNOWN)

    def test_source_byte_limit_includes_hidden_markup(self):
        prefix = '0 MB<script>'
        suffix = '</script>'
        content = prefix + 'x' * (4096 - len(prefix) - len(suffix)) + suffix
        self.assertEqual(classify_quota(raw(content)), _ZERO)
        self.assertEqual(classify_quota(raw(content + ' ')), _UNKNOWN)
        self.assertEqual(classify_quota(raw(title='<b>' + '剩' * 1366 + '</b>')), _UNKNOWN)

    def test_nonfinite_and_binary_floats_are_unknown(self):
        for value in (math.nan, math.inf, -math.inf, -0.0, 0.0, 1.0):
            with self.subTest(value=value):
                self.assertEqual(classify_quota(raw(value, '剩余流量(MB)')), _UNKNOWN)

    def test_status_types_and_raw_integer_bounds(self):
        for code in (True, False, 0.0, '200', None):
            with self.subTest(code=code):
                self.assertEqual(classify_quota(dict(raw(), code=code)), _UNKNOWN)
        self.assertEqual(classify_quota(raw(2**63, '剩余流量(MB)')), _UNKNOWN)
        self.assertEqual(classify_quota(raw(-(2**63) - 1, '剩余流量(MB)')), _UNKNOWN)
        for key in ('result', 'success', 'online'):
            self.assertEqual(classify_quota(dict(raw(), **{key: None})), _UNKNOWN)

    def test_hidden_ascii_case_and_malformed_fragments(self):
        for tag in ('script', 'style', 'noscript'):
            with self.subTest(tag=tag):
                self.assertEqual(classify_quota(raw(f'0 MB<{tag.upper()}>1 GB</{tag.upper()}>')), _ZERO)
                self.assertEqual(classify_quota(raw(f'0 MB<{tag}>1 GB')), _UNKNOWN)
                self.assertEqual(classify_quota(raw(f'0 MB</{tag}>')), _UNKNOWN)
        self.assertEqual(classify_quota(raw('0 MB<ſcript>1 GB</ſcript>')), _UNKNOWN)
        self.assertEqual(classify_quota(raw('0 MB<scrİpt>1 GB</scrİpt>')), _UNKNOWN)
        self.assertEqual(classify_quota(raw('0 MB<!-- 1 GB -->')), _UNKNOWN)

    def test_invalid_entities_and_unpaired_surrogates(self):
        for value in ('0&#xD800; MB', '0&#4294967296; MB', '0&#0; MB', '0\ud800 MB'):
            with self.subTest(value=repr(value)):
                self.assertEqual(classify_quota(raw(value)), _UNKNOWN)


if __name__ == '__main__':
    unittest.main()
