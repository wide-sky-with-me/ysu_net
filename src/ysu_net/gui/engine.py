"""Toolkit-independent worker behind the graphical client.

Every network operation runs on one background thread, so manual actions and the
automatic reconnect loop never overlap. Results are reported through ``emit``.
"""
from contextlib import contextmanager
from dataclasses import dataclass
import json
import queue
import threading
import time

from ysu_net.auth.account import account_summary
from ysu_net.auth.common import QueryError, online_service, online_state
from ysu_net.manager.backend import Result, run_backend
from ysu_net.manager.config import SERVICES, load_config, update_config
from ysu_net.manager.daemon import Reconnector
from ysu_net.manager.locking import exclusive_config
from ysu_net.manager.switching import switch_service

EXTERNAL_DAEMON = "后台服务（ysu on / ysu daemon）正在管理此配置；如需在界面中操作，请先执行 ysu stop"


@dataclass(frozen=True)
class Status:
    online: bool | None
    service: str | None = None
    user: str = ""
    ip: str = ""
    message: str = ""


def parse_status(result):
    if result.code not in (0, 1):
        return Status(None, message=result.message)
    try:
        payload = json.loads(result.output)["online"]
        if not online_state(payload):
            return Status(False, message="离线")
        info = payload["data"]["portalOnlineUserInfo"]
        try:
            service = online_service(payload)
        except QueryError:
            service = None
        return Status(True, service, str(info.get("userName") or info.get("userId") or ""),
                      str(info.get("userIp") or ""), "在线")
    except (ValueError, KeyError, TypeError, QueryError):
        return Status(None, message="状态响应无法识别")


class Engine:
    def __init__(self, path, emit, runner=run_backend):
        self.path = path
        self.emit = emit
        self.runner = runner
        self.cancel = threading.Event()
        self.tasks = queue.Queue()
        self.auto = False
        self._lock = None
        self.next_check = None
        self.reconnector = Reconnector(runner=self._run)
        self.thread = threading.Thread(target=self._loop, name="ysu-engine", daemon=True)

    # ---- public API: safe to call from any thread ----
    def start(self):
        self.thread.start()

    def submit(self, name, *args):
        self.tasks.put((name, args))

    def shutdown(self, timeout=5):
        self.cancel.set()
        self.tasks.put(("quit", ()))
        if self.thread.is_alive():
            self.thread.join(timeout)

    # ---- worker thread ----
    def _run(self, config, action, **kwargs):
        if action == "status":
            # Always fetch raw JSON so every check also refreshes the displayed state.
            kwargs.pop("raw", None)
            result = self.runner(config, "status", raw=True, stop_event=self.cancel, **kwargs)
            self.emit("status", parse_status(result))
            return result
        return self.runner(config, action, stop_event=self.cancel, **kwargs)

    def _loop(self):
        while True:
            timeout = None
            if self.auto and self.next_check is not None:
                timeout = max(0.0, self.next_check - time.monotonic())
            try:
                name, args = self.tasks.get(timeout=timeout)
            except queue.Empty:
                name, args = "tick", ()
            if name == "quit":
                self._release()
                return
            try:
                getattr(self, "_do_" + name)(*args)
            except (ValueError, RuntimeError, OSError) as exc:
                self.emit("error", str(exc))
            finally:
                self.emit("idle", None)

    @contextmanager
    def _guard(self):
        # While auto reconnect is on, this process already holds the profile lock.
        if self.auto:
            yield
            return
        try:
            with exclusive_config(self.path):
                yield
        except RuntimeError as exc:
            if "守护" in str(exc):
                raise RuntimeError(EXTERNAL_DAEMON) from None
            raise

    def _release(self):
        if self._lock is not None:
            self._lock.__exit__(None, None, None)
            self._lock = None
        self.auto = False
        self.next_check = None

    def _config(self):
        return load_config(self.path)

    def _do_status(self):
        self.emit("busy", "正在查询连接状态…")
        self._run(self._config(), "status")

    def _do_info(self):
        self.emit("busy", "正在读取账户信息…")
        result = self.runner(self._config(), "info", raw=True, stop_event=self.cancel)
        summary = None
        if result.code in (0, 1):
            try:
                data = json.loads(result.output)
                summary = account_summary(data.get("online"), data.get("account"))
            except (ValueError, AttributeError):
                pass
        if summary is None:
            self.emit("error", "账户信息获取失败：" + result.message)
        self.emit("info", summary)

    def _do_login(self):
        config = self._config()
        if not config.username or not config.password:
            raise ValueError("请先在“设置”中填写账号和密码")
        self.emit("busy", f"正在登录{config.service}…")
        with self._guard():
            result = self._run(config, "login")
        self._report(result, f"已登录{config.service}")
        self._run(config, "status")

    def _do_logout(self):
        config = self._config()
        if self.auto:
            # Otherwise the reconnect loop would authenticate again immediately.
            self._release()
            self.emit("auto", {"state": "off", "message": "已为下线关闭自动重连"})
        self.emit("busy", "正在下线并确认结果…")
        with self._guard():
            result = self._run(config, "logout")
        self._report(result, "已下线")
        self._run(config, "status")

    def _do_switch(self, target):
        if target not in SERVICES:
            raise ValueError("目标服务无效")
        config = self._config()
        self.emit("busy", f"正在切换到{target}，连接可能短暂中断…")
        with self._guard():
            outcome = switch_service(config, target, runner=self._run)
            if outcome.code == 0:
                update_config(self.path, service=target)
        self.emit("config", None)
        self._report(Result(outcome.code), outcome.message, failure=outcome.message)
        self._run(self._config(), "status")

    def _do_set_service(self, target):
        update_config(self.path, service=target)
        self.emit("config", None)
        self.emit("result", {"ok": True, "message": f"下次登录将使用{target}"})

    def _do_set_auto(self, enabled):
        if not enabled:
            self._release()
            self.emit("auto", {"state": "off", "message": "自动重连已关闭"})
            return
        if self.auto:
            return
        config = self._config()
        if not config.username or not config.password:
            self.emit("auto", {"state": "off", "message": "请先配置账号密码"})
            raise ValueError("开启自动重连前，请先在“设置”中填写账号和密码")
        lock = exclusive_config(self.path)
        try:
            lock.__enter__()
        except RuntimeError:
            self.emit("auto", {"state": "external", "message": EXTERNAL_DAEMON})
            return
        self._lock = lock
        self.auto = True
        self.reconnector.blocked_credentials = None
        self.next_check = time.monotonic()
        self.emit("auto", {"state": "on", "message": "自动重连已开启，正在检查…"})

    def _do_tick(self):
        if not self.auto:
            return
        try:
            config = self._config()
            self.emit("busy", "自动重连：正在检查连接…")
            delay, message = self.reconnector.step(config)
        except (ValueError, OSError):
            delay, message = 30, "配置不可用，等待修复（未发起登录）"
        self.next_check = time.monotonic() + delay
        self.emit("auto", {"state": "on", "message": message, "delay": delay})

    def _report(self, result, success, failure=None):
        if result.code == 0:
            self.emit("result", {"ok": True, "message": success})
        else:
            self.emit("result", {"ok": False, "message": failure or result.message})
