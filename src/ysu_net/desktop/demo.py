"""In-memory Portal-shaped responses. This module never uses the network."""
import json
import threading

from ysu_net.manager.backend import Result
from ysu_net.manager.config import Config, SERVICES


def demo_config():
    return Config(username="demo-user", password="demo-password")


class DemoRunner:
    def __init__(self):
        self._lock = threading.Lock()
        self.online = False
        self.service = SERVICES[0]
        self.username = "demo-user"

    def _online_payload(self):
        if not self.online:
            return {"data": {"portalOnlineUserInfo": {
                "result": "fail", "message": "dx.failed.user.offline",
            }}}
        return {"data": {"portalOnlineUserInfo": {
            "result": "success", "userName": self.username,
            "userId": self.username, "userIp": "192.0.2.24",
            "ssid": "YSU-DEMO", "service": self.service,
            "realServiceName": self.service,
        }}}

    def __call__(self, config, action, *, raw=False, stop_event=None, **kwargs):
        with self._lock:
            if stop_event is not None and stop_event.is_set():
                return Result(130)
            if action == "login":
                if not config.username or not config.password:
                    return Result(4)
                if config.service not in SERVICES:
                    return Result(3)
                self.online = True
                self.service = config.service
                self.username = config.username
                return Result(0)
            if action == "logout":
                self.online = False
                return Result(0)
            if action not in ("status", "info"):
                return Result(2)
            payload = {"online": self._online_payload(), "is_online": self.online}
            if action == "info":
                payload["account"] = {"data": {
                    "name": "演示账户", "service": self.service,
                    "accountInfo": [
                        {"title": "剩余流量", "content": "<b>8.5 GB</b>"},
                        {"title": "套餐&余额", "content": "演示套餐 / 20.00 元"},
                    ],
                }} if self.online else None
            return Result(0 if self.online else 1, json.dumps(payload, ensure_ascii=False))
