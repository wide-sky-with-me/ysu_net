"""Read-only /self adapters: parsing, rendering and failure closure."""
import json
from pathlib import Path

from helpers import OfflineTestCase
from ysu_net.auth import selfservice
from ysu_net.auth.common import QueryError

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class DevicesTests(OfflineTestCase):
    def test_splits_online_and_offline_groups(self):
        payload = fixture("self-devices.json")
        out = selfservice.parse_devices(payload)
        self.assertEqual(out["online"], 2)
        self.assertEqual(out["total"], 2)
        self.assertEqual([row["在线"] for row in out["rows"]], ["是", "是"])
        self.assertEqual([row["本机"] for row in out["rows"]], ["是", "否"])

    def test_keeps_portal_wording_for_every_field(self):
        row = selfservice.parse_devices(fixture("self-devices.json"))["rows"][0]
        self.assertEqual(row["类型"], "电脑")
        self.assertEqual(row["MAC"], "02-00-00-00-00-01")
        self.assertEqual(row["接入方式"], "无线标准Portal接入")
        self.assertEqual(row["在线时长"], "0时48分34秒")

    def test_offline_group_is_labelled_not_dropped(self):
        payload = fixture("self-devices.json")
        payload["data"]["offlineDevices"] = [dict(payload["data"]["onlineDevices"][0])]
        out = selfservice.parse_devices(payload)
        self.assertEqual(out["online"], 2)
        self.assertEqual(out["total"], 3)
        self.assertEqual(out["rows"][-1]["在线"], "否")

    def test_missing_groups_fail_closed(self):
        for payload in ({}, {"data": None}, {"data": []}, None, []):
            with self.subTest(payload=payload):
                with self.assertRaises(QueryError):
                    selfservice.parse_devices(payload)

    def test_null_fields_render_empty_not_zero(self):
        payload = fixture("self-devices.json")
        payload["data"]["onlineDevices"][0]["userIpv4"] = None
        row = selfservice.parse_devices(payload)["rows"][0]
        self.assertEqual(row["IP"], "")


class FlowTests(OfflineTestCase):
    def test_keeps_portal_units_verbatim(self):
        out = selfservice.parse_flow(fixture("self-flow.json"))
        self.assertEqual(len(out["items"]), 1)
        item = out["items"][0]
        self.assertEqual(item["name"], "国内下行流量")
        self.assertEqual(item["left"], "49 GB 977.47 MB")
        self.assertEqual(item["total"], "60 GB 0.00 MB")
        self.assertEqual(item["percent"], 16.7)

    def test_missing_data_fails_closed(self):
        with self.assertRaises(QueryError):
            selfservice.parse_flow({"code": 200})


class PackageTests(OfflineTestCase):
    def test_reads_policy_period_and_usage(self):
        out = selfservice.parse_package(fixture("self-package.json"))
        self.assertEqual(out["package"], "硕士研究生60G")
        self.assertEqual(out["rule"], "0.00—60.00GB内免费")
        self.assertEqual(out["period"], "2026-11-01 至 2026-11-30")
        self.assertEqual(out["balance"], "0.00")
        self.assertEqual(out["percent"], 16.74)

    def test_missing_data_fails_closed(self):
        with self.assertRaises(QueryError):
            selfservice.parse_package({"data": "x"})


class RememberTests(OfflineTestCase):
    def test_disabled_state(self):
        out = selfservice.parse_remember(fixture("self-remember.json"))
        self.assertIs(out["remembered"], False)
        self.assertEqual(out["service"], "")

    def test_unknown_payload_is_not_guessed(self):
        out = selfservice.parse_remember({"data": None})
        self.assertIsNone(out["remembered"])


class RenderTests(OfflineTestCase):
    def snapshot(self):
        return {
            "devices": selfservice.parse_devices(fixture("self-devices.json")),
            "package": selfservice.parse_package(fixture("self-package.json")),
            "flow": selfservice.parse_flow(fixture("self-flow.json")),
            "remember": selfservice.parse_remember(fixture("self-remember.json")),
        }

    def test_render_keeps_every_portal_value(self):
        text = selfservice.format_snapshot(self.snapshot())
        for expected in ("在线设备：2 台", "硕士研究生60G", "49 GB 977.47 MB",
                         "2026-11-01 至 2026-11-30", "记住的上网选择：未开启"):
            self.assertIn(expected, text)

    def test_render_never_invents_missing_flow(self):
        snap = self.snapshot()
        snap["flow"] = {"items": []}
        self.assertIn("门户未提供", selfservice.format_snapshot(snap))


class UrlTests(OfflineTestCase):
    def test_endpoints_are_fixed_paths(self):
        base = "https://auth1.ysu.edu.cn"
        self.assertEqual(selfservice.self_service_url(base), base + "/self/index")
        self.assertEqual(selfservice.callback_url(base),
                         base + "/login/oauth2/code/custom-self")
        self.assertTrue(selfservice.DEVICES.startswith("/sam/api/userself/"))

    def test_write_endpoints_are_an_explicit_allowlist(self):
        """写操作只能是已知的两个；新增任何写接口都必须先改这里。"""
        read_only = {"SELF_PATH", "DELEGATE_CLIENT", "DEVICES", "PACKAGE_OVERVIEW",
                     "PACKAGE_FLOW", "REMEMBER_CURRENT", "AGGREGATE_INIT",
                     "_MAX_TEXT", "_MAX_DEVICES", "SESSION_TTL",
                     "KICK_VERIFY_SECONDS", "KICK_VERIFY_INTERVAL"}
        writes = {n for n in dir(selfservice)
                  if n.isupper() and not n.startswith("_") and n not in read_only}
        self.assertEqual(writes, {"KICK_OFFLINE", "NOSENSE_UNBIND"})
        # 破坏性更强、本项目未实现的动作必须缺席
        for forbidden in ("UNBIND_BATCH", "BIND_MAC", "PASSWORD", "DEACTIVATE"):
            self.assertNotIn(forbidden, writes)


class FetchTests(OfflineTestCase):
    def session(self, status=200, payload=None, text=None):
        class Response:
            def __init__(self):
                self.status_code = status
                self._text = text if text is not None else json.dumps(payload)

            def json(self):
                return json.loads(self._text)

            @property
            def text(self):
                return self._text

        class Session:
            last = None

            def __init__(self):
                self.headers = {}

            def post(self, url, **kwargs):
                type(self).last = (url, kwargs)
                return Response()

            def get(self, url, **kwargs):
                Response.url = url
                return Response()

        return Session()

    def test_ok_envelope(self):
        session = self.session(payload={"code": 200, "data": {}})
        got = selfservice.fetch(session, "https://auth1.ysu.edu.cn", selfservice.DEVICES)
        self.assertEqual(got["code"], 200)
        url, kwargs = session.last
        self.assertTrue(url.endswith(selfservice.DEVICES))
        self.assertEqual(kwargs["json"], {})
        self.assertEqual(kwargs["headers"]["clientType"], "self")

    def test_non_200_and_bad_envelope_fail_closed(self):
        for status, payload, text in ((500, None, ""), (200, {"code": 401}, None),
                                      (200, None, "not json")):
            with self.subTest(status=status):
                with self.assertRaises(QueryError):
                    selfservice.fetch(self.session(status, payload, text),
                                      "https://auth1.ysu.edu.cn", selfservice.DEVICES)


class SelectTests(OfflineTestCase):
    def rows(self):
        return [
            {"类型": "电脑", "在线": "是", "本机": "是", "_uuid": "u-self",
             "_unified": True, "IP": "10.0.0.1"},
            {"类型": "手机", "在线": "是", "本机": "否", "_uuid": "u-phone",
             "_unified": False, "IP": "10.0.0.2"},
            {"类型": "平板", "在线": "否", "本机": "否", "_uuid": "u-pad",
             "_unified": False, "IP": ""},
        ]

    def test_index_is_one_based(self):
        self.assertEqual([r["_uuid"] for r in selfservice.select_devices(self.rows(), "1")],
                         ["u-self"])
        self.assertEqual([r["_uuid"] for r in selfservice.select_devices(self.rows(), "2")],
                         ["u-phone"])

    def test_all_keeps_only_online(self):
        picked = selfservice.select_devices(self.rows(), "all")
        self.assertEqual([r["_uuid"] for r in picked], ["u-self", "u-phone"])

    def test_offline_target_is_refused(self):
        with self.assertRaises(QueryError) as ctx:
            selfservice.select_devices(self.rows(), "3")
        self.assertIn("不在线", str(ctx.exception))

    def test_bad_index_and_range_fail_closed(self):
        for selector in ("abc", "0", "99", ""):
            with self.subTest(selector=selector):
                with self.assertRaises(QueryError):
                    selfservice.select_devices(self.rows(), selector)

    def test_missing_uuid_fails_closed(self):
        rows = [{"在线": "是", "本机": "否", "_uuid": ""}]
        with self.assertRaises(QueryError):
            selfservice.select_devices(rows, "1")


class KickFlagTests(OfflineTestCase):
    def test_self_kick_keeps_sso(self):
        row = {"本机": "是", "_unified": True}
        self.assertFalse(selfservice.kick_unified_flag(row))

    def test_other_device_kick_ends_sso(self):
        self.assertTrue(selfservice.kick_unified_flag({"本机": "否", "_unified": True}))
        self.assertTrue(selfservice.kick_unified_flag({"本机": "是", "_unified": False}))

    def test_unknown_unified_state_defaults_to_ending_sso(self):
        self.assertTrue(selfservice.kick_unified_flag({}))


class KickFlowTests(OfflineTestCase):
    """kick() drives two reads around one write and verifies the outcome."""

    def setUp(self):
        super().setUp()
        self.state = {"online": True}

    def devices_payload(self):
        online = [{"onlineUserUuid": "u-phone", "deviceName": "我的设备",
                   "deviceType": "手机", "terminalType": 2, "currentDevice": False,
                   "unifiedAuthentication": False, "userMac": "m", "userIpv4": "10.0.0.2",
                   "onlineDuration": "1分", "authType": "portal"}] if self.state["online"] else []
        return {"code": 200, "data": {"onlineDevices": online, "offlineDevices": []}}

    def run_kick(self, selector="1", verify_ok=True):
        self.mock("ysu_net.auth.selfservice.time.sleep")
        self.mock("ysu_net.auth.selfservice.time.monotonic", side_effect=[0, 0, 0, 1e9])
        session = object()
        writes = []
        self.mock("ysu_net.auth.selfservice.open_session", return_value=session)

        def fake_fetch(_session, _base, path, body=None, timeout=25):
            if path == selfservice.DEVICES:
                return self.devices_payload()
            writes.append((path, body))
            self.state["online"] = not verify_ok
            return {"code": 200, "message": "OK"}

        self.mock("ysu_net.auth.selfservice.fetch", side_effect=fake_fetch)
        result = selfservice.kick("https://auth1.ysu.edu.cn", "https://cas", "u", "p", selector)
        return result, writes

    def test_kick_sends_portal_contract_and_verifies(self):
        result, writes = self.run_kick()
        self.assertEqual(len(writes), 1)
        path, body = writes[0]
        self.assertEqual(path, selfservice.KICK_OFFLINE)
        self.assertEqual(body["onlineUserUuids"], ["u-phone"])
        self.assertTrue(body["kickUnifiedAuthOffline"])
        self.assertEqual(result["online_before"], 1)
        self.assertEqual(result["online_after"], 0)

    def test_kick_reports_when_device_stays_online(self):
        # verify_ok=False 表示重新读取时设备仍在线，必须报错而不是静默成功。
        with self.assertRaises(selfservice.KickVerifyError):
            self.run_kick(verify_ok=False)

    def test_kick_without_target_never_writes(self):
        with self.assertRaises(QueryError):
            self.run_kick(selector="")


class SessionCacheTests(OfflineTestCase):
    BASE = "https://auth1.ysu.edu.cn"

    def setUp(self):
        super().setUp()
        import os
        os.environ["XDG_CACHE_HOME"] = str(self.tmp)
        self.addCleanup(os.environ.pop, "XDG_CACHE_HOME", None)

    def jar(self, **cookies):
        import requests
        session = requests.Session()
        for name, value in cookies.items():
            session.cookies.set(name, value, domain="auth1.ysu.edu.cn", path="/")
        return session

    def test_roundtrip_keeps_cookie_attributes(self):
        session = self.jar(SESSION="s", CASTGC="t")
        selfservice.save_session(session, self.BASE, "u")
        restored = selfservice.load_session(self.BASE, "u")
        self.assertIsNotNone(restored)
        names = {c.name for c in restored.cookies}
        self.assertEqual(names, {"SESSION", "CASTGC"})
        cookie = next(c for c in restored.cookies if c.name == "SESSION")
        self.assertEqual(cookie.domain, "auth1.ysu.edu.cn")
        self.assertEqual(cookie.path, "/")

    def test_cache_file_is_owner_only(self):
        import stat
        selfservice.save_session(self.jar(SESSION="s"), self.BASE, "u")
        mode = stat.S_IMODE(selfservice.cache_path().stat().st_mode)
        self.assertEqual(mode, 0o600)

    def test_other_account_and_origin_are_refused(self):
        selfservice.save_session(self.jar(SESSION="s"), self.BASE, "u")
        self.assertIsNone(selfservice.load_session(self.BASE, "someone-else"))
        self.assertIsNone(selfservice.load_session("https://other.invalid", "u"))

    def test_expired_cache_is_refused(self):
        selfservice.save_session(self.jar(SESSION="s"), self.BASE, "u")
        self.assertIsNone(selfservice.load_session(self.BASE, "u", ttl=0))

    def test_corrupt_or_oversized_cache_is_ignored(self):
        path = selfservice.cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not json", encoding="utf-8")
        self.assertIsNone(selfservice.load_session(self.BASE, "u"))
        path.write_text('{"version": 1, "base": "%s", "username": "u", '
                        '"saved_at": 99999999999, "cookies": []}' % self.BASE,
                        encoding="utf-8")
        self.assertIsNone(selfservice.load_session(self.BASE, "u"))

    def test_stale_cache_is_cleared_before_relogin(self):
        selfservice.save_session(self.jar(SESSION="s"), self.BASE, "u")
        self.mock("ysu_net.auth.selfservice._still_authorised", return_value=False)
        self.mock("ysu_net.auth.api.cas_login", side_effect=RuntimeError("x"))
        with self.assertRaises(QueryError):
            selfservice.open_session(self.BASE, "cas", "u", "p")
        self.assertIsNone(selfservice.load_session(self.BASE, "u"))

    def test_cached_session_skips_login(self):
        selfservice.save_session(self.jar(SESSION="s"), self.BASE, "u")
        self.mock("ysu_net.auth.selfservice._still_authorised", return_value=True)
        login = self.mock("ysu_net.auth.api.cas_login")
        session = selfservice.open_session(self.BASE, "cas", "u", "p")
        login.assert_not_called()
        self.assertTrue(selfservice.session_state(session)["cached"])

    def test_fresh_forces_login(self):
        selfservice.save_session(self.jar(SESSION="s"), self.BASE, "u")
        login = self.mock("ysu_net.auth.api.cas_login")
        self.mock("ysu_net.auth.selfservice.landed_in_self", return_value=True)
        session = selfservice.open_session(self.BASE, "cas", "u", "p", fresh=True)
        login.assert_called_once()
        self.assertFalse(selfservice.session_state(session)["cached"])

    def test_render_reports_session_source(self):
        snap = {"session": {"cached": True, "expires_in": 900},
                "devices": {"online": 0, "total": 0, "rows": []},
                "package": {}, "flow": {"items": []}, "remember": {}}
        text = selfservice.format_snapshot(snap)
        self.assertIn("复用已登录状态", text)
        self.assertIn("15 分钟", text)

    def test_render_flags_fresh_login(self):
        snap = {"session": {"cached": False, "expires_in": None},
                "devices": {"online": 0, "total": 0, "rows": []},
                "package": {}, "flow": {"items": []}, "remember": {}}
        self.assertIn("本次新登录", selfservice.format_snapshot(snap))
