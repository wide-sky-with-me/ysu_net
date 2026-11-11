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

    def test_null_data_returns_empty_flow(self):
        self.assertEqual(selfservice.parse_flow({"code": 200, "data": None}), {"items": []})


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

    def test_null_data_returns_empty_package(self):
        out = selfservice.parse_package({"code": 200, "data": None})
        self.assertEqual(out["package"], "")
        self.assertIsNone(out["percent"])


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
        for expected in ("在线设备：2 台", "1. 我的设备（在线，本机）", "硕士研究生60G", "49 GB 977.47 MB",
                         "国内下行流量", "2026-11-01 至 2026-11-30", "记住的上网选择：未开启"):
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

    def test_seed_service_extracts_same_origin_oauth_callback(self):
        base = "https://auth1.ysu.edu.cn"
        oauth_cb = (
            "https://auth1.ysu.edu.cn/cas-sso/oauth2.0/callbackAuthorize"
            "?client_id=20231026142058188-9037-986575215"
            "&redirect_uri=https%3A%2F%2Fauth1.ysu.edu.cn%2Flogin%252Foauth2%252Fcode%252Fcustom-self"
            "&response_type=code&client_name=CasOAuthClient"
        )
        from urllib.parse import quote
        seed_url = f"{base}/cas-sso/login?service={quote(oauth_cb, safe='')}"
        self.assertEqual(selfservice.seed_service(seed_url, base), oauth_cb)
        # Cross-origin, credentialed, or missing service falls back to callback_url
        for bad in (
            f"{base}/cas-sso/login",
            f"{base}/cas-sso/login?service=https%3A%2F%2Foutside.invalid%2Fcb",
            f"{base}/cas-sso/login?service=http%3A%2F%2Fauth1.ysu.edu.cn%2Fcb",
            f"{base}/cas-sso/login?service=https%3A%2F%2Fuser%3Apass%40auth1.ysu.edu.cn%2Fcb",
        ):
            self.assertEqual(selfservice.seed_service(bad, base), selfservice.callback_url(base))

    def test_write_endpoints_are_an_explicit_allowlist(self):
        """写操作只能是已实现的下线与无感认证接口；新增任何写接口都必须先改这里。"""
        read_only = {"SELF_PATH", "DEVICES", "PACKAGE_OVERVIEW",
                     "PACKAGE_FLOW", "REMEMBER_CURRENT", "DEFAULT_SERVICES",
                     "DEFAULT_SERVICE_PACKAGE", "_MAX_TEXT", "_MAX_DEVICES",
                     "SESSION_TTL", "KICK_VERIFY_SECONDS", "KICK_VERIFY_INTERVAL",
                     "NOSENSE_RENEW_THRESHOLD"}
        writes = {n for n in dir(selfservice)
                  if n.isupper() and not n.startswith("_") and n not in read_only}
        self.assertEqual(writes, {"KICK_OFFLINE", "NOSENSE_REGISTER", "NOSENSE_UNBIND", "DEVICE_MODIFY"})
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

    def test_all_with_no_online_devices_fails_closed(self):
        with self.assertRaises(QueryError) as ctx:
            selfservice.select_devices([self.rows()[2]], "all")
        self.assertIn("没有可下线的在线设备", str(ctx.exception))

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

    def test_multiple_accounts_preserve_independent_session_jars(self):
        selfservice.save_session(self.jar(SESSION="s1", CASTGC="t1"), self.BASE, "u1")
        selfservice.save_session(self.jar(SESSION="s2", CASTGC="t2"), self.BASE, "u2")
        s1 = selfservice.load_session(self.BASE, "u1")
        s2 = selfservice.load_session(self.BASE, "u2")
        self.assertIsNotNone(s1)
        self.assertIsNotNone(s2)
        self.assertEqual(s1.cookies.get("CASTGC"), "t1")
        self.assertEqual(s2.cookies.get("CASTGC"), "t2")
        selfservice.clear_session(self.BASE, "u1")
        self.assertIsNone(selfservice.load_session(self.BASE, "u1"))
        self.assertIsNotNone(selfservice.load_session(self.BASE, "u2"))

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
        self.mock("ysu_net.auth.selfservice._seed_self",
                  return_value=(False, selfservice.callback_url(self.BASE)))
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
        oauth_cb = f"{self.BASE}/cas-sso/oauth2.0/callbackAuthorize?client_name=CasOAuthClient"
        self.mock("ysu_net.auth.selfservice._seed_self", return_value=(False, oauth_cb))
        login = self.mock("ysu_net.auth.api.cas_login")
        self.mock("ysu_net.auth.selfservice.landed_in_self", return_value=True)
        session = selfservice.open_session(self.BASE, "cas", "u", "p", fresh=True)
        login.assert_called_once_with(session, "u", "p", debug=False, service=oauth_cb)
        self.assertFalse(selfservice.session_state(session)["cached"])

    def test_seed_already_in_self_skips_cas_password_post(self):
        self.mock("ysu_net.auth.selfservice._seed_self",
                  return_value=(True, selfservice.callback_url(self.BASE)))
        login = self.mock("ysu_net.auth.api.cas_login")
        self.mock("ysu_net.auth.selfservice.landed_in_self", return_value=True)
        session = selfservice.open_session(self.BASE, "cas", "u", "p", fresh=True)
        login.assert_not_called()
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


class NoSenseTests(OfflineTestCase):
    SERVICES_PAYLOAD = {
        "code": 200,
        "data": [
            {"uuid": "00_DEFAULT_IN_PACKAGE", "serviceTemplateName": "套餐默认服务"},
            {"uuid": "8a8b808256b247030156b282869a008f", "serviceTemplateName": "中国移动"},
            {"uuid": "8a8b808256b247030156b2813f020087", "serviceTemplateName": "中国联通"},
            {"uuid": "8a8b808256b247030156b2831c150095", "serviceTemplateName": "中国电信"},
        ],
    }

    def setUp(self):
        super().setUp()
        self.device = {
            "onlineUserUuid": "u-self",
            "deviceName": "我的设备",
            "deviceType": "电脑",
            "terminalType": 1,
            "currentDevice": True,
            "unifiedAuthentication": True,
            "userMac": "02-00-00-00-00-01",
            "userIpv4": "10.0.0.1",
            "onlineDuration": "10分",
            "authType": "无线标准Portal接入",
            "bindNoSense": False,
            "noSenseUuid": None,
            "noSenseCreateTime": None,
            "noSenseEndTime": None,
            "defaultServiceOperaporsConfigUuid": None,
            "location": "",
        }

    def devices_payload(self):
        return {"code": 200, "data": {"onlineDevices": [dict(self.device)], "offlineDevices": []}}

    def test_normalize_and_require_mac(self):
        for raw in ("02:00:00:00:00:01", "02-00-00-00-00-01", "0200.0000.0001", "020000000001"):
            self.assertEqual(selfservice.require_mac(raw), "02-00-00-00-00-01")
        for bad in ("", "02-00-00", "GG-00-00-00-00-01"):
            with self.assertRaises(QueryError):
                selfservice.require_mac(bad)

    def test_parse_devices_extracts_nosense_and_default_service(self):
        self.device.update({
            "bindNoSense": True,
            "noSenseUuid": "ns-1",
            "noSenseEndTime": 1794883200000,
            "defaultServiceOperaporsConfigUuid": "8a8b808256b247030156b282869a008f",
        })
        services = selfservice.parse_default_services(self.SERVICES_PAYLOAD)
        row = selfservice.parse_devices(self.devices_payload(), services=services)["rows"][0]
        self.assertEqual(row["无感"], "是")
        self.assertEqual(row["缺省服务"], "中国移动")
        self.assertEqual(row["_nosense_uuid"], "ns-1")
        self.assertEqual(row["_nosense_end_ms"], 1794883200000)
        self.assertTrue(row["无感到期"].startswith("2026-11-"))

    def test_enable_nosense_unbinds_existing_and_applies_carrier_service(self):
        self.device.update({
            "bindNoSense": True,
            "noSenseUuid": "ns-old",
            "noSenseEndTime": 1794300000000,
            "defaultServiceOperaporsConfigUuid": "00_DEFAULT_IN_PACKAGE",
        })
        writes = []
        self.mock("ysu_net.auth.selfservice.open_session", return_value=object())
        self.mock("ysu_net.auth.selfservice.time.sleep")

        def fake_fetch(_session, _base, path, body=None, timeout=25):
            if path == selfservice.DEFAULT_SERVICES:
                return self.SERVICES_PAYLOAD
            if path == selfservice.DEVICES:
                return self.devices_payload()
            writes.append((path, body))
            if path == selfservice.NOSENSE_UNBIND:
                self.device.update({"bindNoSense": False, "noSenseUuid": None, "defaultServiceOperaporsConfigUuid": None})
            elif path == selfservice.NOSENSE_REGISTER:
                self.device.update({
                    "bindNoSense": True,
                    "noSenseUuid": "ns-new",
                    "noSenseEndTime": 1794883200000,
                    "defaultServiceOperaporsConfigUuid": "00_DEFAULT_IN_PACKAGE",
                })
            elif path == selfservice.DEVICE_MODIFY:
                self.device["defaultServiceOperaporsConfigUuid"] = body["defaultServiceOperaporsConfigUuid"]
            return {"code": 200, "message": "OK"}

        self.mock("ysu_net.auth.selfservice.fetch", side_effect=fake_fetch)
        result = selfservice.enable_nosense(
            "https://auth1.ysu.edu.cn", "https://cas", "u", "p", "current", service="中国移动"
        )
        self.assertEqual([w[0] for w in writes], [
            selfservice.NOSENSE_UNBIND,
            selfservice.NOSENSE_REGISTER,
            selfservice.DEVICE_MODIFY,
        ])
        self.assertEqual(writes[1][1], {"userMac": "02-00-00-00-00-01", "expireTime": 7, "expireUnit": "day"})
        self.assertTrue(result["bind_no_sense"])
        self.assertEqual(result["service"], "中国移动")

    def test_disable_nosense_unbinds_and_verifies(self):
        self.device.update({"bindNoSense": True, "noSenseUuid": "ns-1"})
        writes = []
        self.mock("ysu_net.auth.selfservice.open_session", return_value=object())
        self.mock("ysu_net.auth.selfservice.time.sleep")

        def fake_fetch(_session, _base, path, body=None, timeout=25):
            if path == selfservice.DEVICES:
                return self.devices_payload()
            writes.append((path, body))
            self.device.update({"bindNoSense": False, "noSenseUuid": None})
            return {"code": 200, "message": "OK"}

        self.mock("ysu_net.auth.selfservice.fetch", side_effect=fake_fetch)
        result = selfservice.disable_nosense("https://auth1.ysu.edu.cn", "https://cas", "u", "p", "all")
        self.assertEqual(writes, [(selfservice.NOSENSE_UNBIND, {"noSenseUuids": ["ns-1"]})])
        self.assertEqual(result["unbound"], ["02-00-00-00-00-01"])

    def test_renew_nosense_skips_when_healthy_and_renews_when_expiring(self):
        now_s = 1794300000.0
        self.device.update({
            "bindNoSense": True,
            "noSenseUuid": "ns-1",
            "noSenseEndTime": int((now_s + 5 * 86400) * 1000),
            "defaultServiceOperaporsConfigUuid": "8a8b808256b247030156b282869a008f",
        })
        writes = []
        self.mock("ysu_net.auth.selfservice.open_session", return_value=object())
        self.mock("ysu_net.auth.selfservice.time.time", return_value=now_s)
        self.mock("ysu_net.auth.selfservice.time.sleep")

        def fake_fetch(_session, _base, path, body=None, timeout=25):
            if path == selfservice.DEFAULT_SERVICES:
                return self.SERVICES_PAYLOAD
            if path == selfservice.DEVICES:
                return self.devices_payload()
            writes.append((path, body))
            if path == selfservice.NOSENSE_REGISTER:
                self.device.update({
                    "bindNoSense": True,
                    "noSenseUuid": "ns-2",
                    "noSenseEndTime": int((now_s + 7 * 86400) * 1000),
                    "defaultServiceOperaporsConfigUuid": "00_DEFAULT_IN_PACKAGE",
                })
            elif path == selfservice.DEVICE_MODIFY:
                self.device["defaultServiceOperaporsConfigUuid"] = body["defaultServiceOperaporsConfigUuid"]
            return {"code": 200, "message": "OK"}

        self.mock("ysu_net.auth.selfservice.fetch", side_effect=fake_fetch)
        skipped = selfservice.renew_nosense("https://auth1.ysu.edu.cn", "https://cas", "u", "p", "current")
        self.assertFalse(skipped["renewed"])
        self.assertEqual(writes, [])

        # Expiring within 24 hours triggers automatic renewal and preserves carrier service
        self.device["noSenseEndTime"] = int((now_s + 3600) * 1000)
        renewed = selfservice.renew_nosense("https://auth1.ysu.edu.cn", "https://cas", "u", "p", "current")
        self.assertTrue(renewed["renewed"])
        self.assertEqual(renewed["service"], "中国移动")
        self.assertEqual([w[0] for w in writes], [
            selfservice.NOSENSE_UNBIND,
            selfservice.NOSENSE_REGISTER,
            selfservice.DEVICE_MODIFY,
        ])

    def test_parse_devices_handles_null_online_and_offline_lists(self):
        self.assertEqual(
            selfservice.parse_devices({"code": 200, "data": {"onlineDevices": None, "offlineDevices": []}}),
            {"online": 0, "total": 0, "rows": []},
        )
        self.assertEqual(
            selfservice.parse_devices({"code": 200, "data": {"onlineDevices": None, "offlineDevices": None}}),
            {"online": 0, "total": 0, "rows": []},
        )

    def test_select_nosense_target_falls_back_to_local_mac_when_no_online_devices(self):
        sample_ipconfig = (
            "Ethernet adapter vEthernet (WSL):\r\n"
            "   Physical Address. . . . . . . . . : 00-15-5D-01-02-03\r\n"
            "   IPv4 Address. . . . . . . . . . . : 172.20.16.1\r\n"
            "\r\n"
            "Wireless LAN adapter WLAN:\r\n"
            "   Physical Address. . . . . . . . . : AA-BB-CC-DD-EE-FF\r\n"
            "   IPv4 Address. . . . . . . . . . . : 10.22.100.50\r\n"
            "   Default Gateway . . . . . . . . . : 10.22.0.1\r\n"
        )
        self.assertEqual(
            selfservice.parse_adapter_mac_from_text(sample_ipconfig),
            "AA-BB-CC-DD-EE-FF",
        )
        self.mock("ysu_net.auth.selfservice.detect_local_mac", return_value="AA-BB-CC-DD-EE-FF")
        mac, row = selfservice.select_nosense_target([], "current")
        self.assertEqual(mac, "AA-BB-CC-DD-EE-FF")
        self.assertIsNone(row)
