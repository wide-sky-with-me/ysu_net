"""Thread-safe, toolkit-independent desktop state and command handling."""
from collections import deque
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import datetime, timezone
import importlib.util
from importlib.metadata import PackageNotFoundError, version
import math
from pathlib import Path
import platform
import queue
import threading

from ysu_net.auth import node_runtime
from ysu_net.auth.system_browser import find_system_browser
from ysu_net.gui.engine import EXTERNAL_DAEMON, Engine, Status
from ysu_net.gui.prefs import THEMES, load_prefs, prefs_path, save_prefs
from ysu_net.manager.backend import Result, run_backend
from ysu_net.manager.config import Config, SERVICES, load_config, update_config

from .demo import DemoRunner

COMMANDS = frozenset({
    "snapshot", "action", "save_config", "save_prefs", "diagnostics",
    "browser_install", "shutdown",
})
ACTIONS = frozenset({"status", "info", "login", "logout", "switch", "set_service", "set_auto"})
CONFIG_FIELDS = frozenset(Config.__dataclass_fields__)
LOG_LIMIT = 200
ERRORS = {
    "invalid_request": "请求格式无效",
    "invalid_command": "命令未受支持",
    "invalid_args": "命令参数无效",
    "line_too_long": "请求行超过长度限制",
    "config_invalid": "配置无效，请检查设置",
    "save_failed": "设置保存失败，请检查文件权限",
    "operation_failed": "操作失败，请检查配置或稍后重试",
    "stopped": "后台正在退出",
    "download_busy": "组件下载正在进行",
    "browser_unavailable": "当前安装或平台未提供浏览器组件下载",
}


class DesktopError(Exception):
    def __init__(self, code):
        self.code = code if code in ERRORS else "operation_failed"
        super().__init__(ERRORS[self.code])


def local_environment():
    """Read local capabilities only; never launch a browser or manage services."""
    try:
        app_version = version("ysu-net-login")
    except PackageNotFoundError:
        app_version = "dev"
    component = importlib.util.find_spec("playwright") is not None
    return {
        "version": app_version,
        "python": platform.python_version(),
        "platform": platform.system(),
        "browser_available": find_system_browser() is not None,
        "node_available": node_runtime.find_node() is not None,
        "browser_component_available": component,
    }


class _DesktopEngine(Engine):
    def __init__(self, path, emit, runner, *, demo=False):
        super().__init__(path, emit, runner=runner)
        self.demo = demo

    def _config(self):
        # Demo must ignore real credentials supplied through the environment.
        return load_config(self.path, environ={} if self.demo else None)

    def _loop(self):
        try:
            super()._loop()
        except Exception:
            self.emit("error", ERRORS["operation_failed"])
        finally:
            self._release()


class DesktopCore:
    """Own one Engine, preferences and immutable public snapshots.

    Action responses acknowledge queueing, not authentication success. Engine
    results and independent status observations arrive through snapshot events.
    """

    def __init__(self, path, emit=None, *, demo=False, runner=None, installer=None,
                 environment_reader=None):
        self.path = Path(path)
        self.prefs_file = prefs_path(self.path)
        self.demo = demo
        self._lock = threading.RLock()
        self._emit = emit or (lambda name, payload: None)
        self._closed = False
        self._started = False
        self._secrets = set()
        self._logs = deque(maxlen=LOG_LIMIT)
        self._sequence = 0
        self._status = None
        self._info = None
        self._auto = {"state": "off", "message": "自动重连已关闭"}
        self._engine_busy = False
        self._engine_message = ""
        self._download_busy = False
        self._download_thread = None
        self._download_cancel = threading.Event()
        self._demo_installed = False
        self._installer = installer or node_runtime.install
        self._environment_reader = environment_reader or local_environment
        self._prefs = load_prefs(self.prefs_file)
        self._auto_desired = self._prefs.auto_reconnect
        try:
            self._config = self._load_config()
            self._environment = self._environment_reader()
        except (OSError, ValueError, RuntimeError):
            raise DesktopError("config_invalid") from None
        self._remember_password(self._config.password)
        actual_runner = runner or (DemoRunner() if demo else run_backend)

        def guarded_runner(config, action, **kwargs):
            if self.engine.cancel.is_set():
                return Result(130)
            with self._lock:
                self._remember_password(config.password)
            try:
                return actual_runner(config, action, **kwargs)
            except Exception:
                # No raw exception, server output or credential reaches the UI.
                return Result(2)

        self.engine = _DesktopEngine(self.path, self._on_engine_event, guarded_runner, demo=demo)

    def _load_config(self):
        return load_config(self.path, environ={} if self.demo else None)

    def _remember_password(self, password):
        if password:
            self._secrets.add(password)

    def _text(self, value):
        text = str(value)
        for secret in sorted(self._secrets, key=len, reverse=True):
            text = text.replace(secret, "[redacted]")
        return "".join(c for c in text if c >= " " or c in "\n\t")[:2048]

    def _scrub(self, value):
        if isinstance(value, str):
            return self._text(value)
        if isinstance(value, dict):
            return {key: self._scrub(item) for key, item in value.items()}
        if isinstance(value, (tuple, list)):
            return [self._scrub(item) for item in value]
        return value

    def _snapshot_locked(self):
        config = {key: value for key, value in asdict(self._config).items() if key != "password"}
        config["password_set"] = bool(self._config.password)
        busy = self._engine_busy or self._download_busy
        message = self._engine_message if self._engine_busy else (
            "正在下载浏览器认证组件…" if self._download_busy else "")
        return self._scrub({
            "sequence": self._sequence, "config": config, "prefs": asdict(self._prefs),
            "status": deepcopy(self._status), "auto": deepcopy(self._auto),
            "busy": busy, "busy_message": message, "info": deepcopy(self._info),
            "logs": list(self._logs), "environment": dict(self._environment),
        })

    def snapshot(self):
        with self._lock:
            return self._snapshot_locked()

    def set_event_sink(self, emit):
        with self._lock:
            self._emit = emit

    def _publish_locked(self, before):
        current = self._snapshot_locked()
        if current == before:
            return
        self._sequence += 1
        self._emit("snapshot", self._snapshot_locked())

    def _log_locked(self, level, message):
        self._logs.append({
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "level": level, "message": self._text(message),
        })

    def _persist_prefs_locked(self, **changes):
        candidate = replace(self._prefs, **changes)
        try:
            save_prefs(self.prefs_file, candidate)
        except OSError:
            raise DesktopError("save_failed") from None
        self._prefs = candidate

    def _refresh_config_locked(self):
        self._config = self._load_config()
        self._remember_password(self._config.password)

    def start(self):
        with self._lock:
            if self._closed:
                raise DesktopError("stopped")
            if self._started:
                return
            self._started = True
            self._emit("snapshot", self._snapshot_locked())
            self.engine.start()
            self.engine.submit("status")
            if self._auto_desired:
                self.engine.submit("set_auto", True)

    def request_stop(self):
        self.engine.cancel.set()
        self._download_cancel.set()

    def close(self):
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self.request_stop()
            while True:
                try:
                    self.engine.tasks.get_nowait()
                except queue.Empty:
                    break
            download = self._download_thread
        # Do not join with the snapshot lock held: Engine callbacks also need it.
        self.engine.shutdown(timeout=5)
        if not self.engine.thread.is_alive():
            self.engine._release()
        if download is not None and download is not threading.current_thread():
            download.join(timeout=1)

    def _on_engine_event(self, name, payload):
        with self._lock:
            if self._closed:
                return
            before = self._snapshot_locked()
            if name == "busy":
                self._engine_busy = True
                self._engine_message = self._text(payload)
            elif name == "idle":
                self._engine_busy = False
                self._engine_message = ""
            elif name == "status" and isinstance(payload, Status):
                self._status = asdict(payload)
                # Account results are separate observations, never status sources.
                if payload.online is False:
                    self._info = {"online": False, "fields": [], "items": []}
            elif name == "info":
                if isinstance(payload, dict) and type(payload.get("online")) is bool:
                    summary = {"online": payload["online"], "fields": [], "items": []}
                    for key in ("fields", "items"):
                        for pair in payload.get(key, [])[:100]:
                            if isinstance(pair, (list, tuple)) and len(pair) == 2:
                                summary[key].append([self._text(pair[0]), self._text(pair[1])])
                    self._info = summary
                else:
                    self._info = None
            elif name == "auto" and isinstance(payload, dict):
                state = payload.get("state")
                if state not in ("off", "on", "external"):
                    return
                self._auto = {"state": state, "message": self._text(payload.get("message", ""))}
                delay = payload.get("delay")
                if type(delay) in (int, float) and math.isfinite(delay) and delay >= 0:
                    self._auto["delay"] = delay
                enabled = state == "on" and self._auto_desired
                if self._prefs.auto_reconnect != enabled:
                    try:
                        self._persist_prefs_locked(auto_reconnect=enabled)
                    except DesktopError:
                        self._log_locked("error", ERRORS["save_failed"])
                if before["auto"].get("message") != self._auto["message"]:
                    self._log_locked("info", "自动重连：" + self._auto["message"])
            elif name == "config":
                try:
                    self._refresh_config_locked()
                except (OSError, ValueError):
                    self._log_locked("error", ERRORS["config_invalid"])
            elif name == "result" and isinstance(payload, dict):
                self._log_locked("success" if payload.get("ok") is True else "error",
                                 payload.get("message", ERRORS["operation_failed"]))
            elif name == "error":
                self._log_locked("error", EXTERNAL_DAEMON if payload == EXTERNAL_DAEMON
                                 else ERRORS["operation_failed"])
            else:
                return
            self._publish_locked(before)

    def handle(self, command, args):
        if command not in COMMANDS:
            raise DesktopError("invalid_command")
        if not isinstance(args, dict):
            raise DesktopError("invalid_args")
        with self._lock:
            if self._closed:
                raise DesktopError("stopped")
            if command in ("snapshot", "diagnostics", "shutdown") and args:
                raise DesktopError("invalid_args")
            if command == "snapshot":
                return self._snapshot_locked()
            if command == "shutdown":
                return {"shutdown": True}
            if command == "action":
                return self._action_locked(args)
            if command == "save_config":
                return self._save_config_locked(args)
            if command == "save_prefs":
                return self._save_prefs_locked(args)
            if command == "diagnostics":
                before = self._snapshot_locked()
                self._environment = self._environment_reader()
                if self.demo and self._demo_installed:
                    self._environment["node_available"] = True
                self._publish_locked(before)
                return self._snapshot_locked()
            return self._browser_install_locked(args)

    def _action_locked(self, args):
        name = args.get("name")
        if not isinstance(name, str) or name not in ACTIONS or set(args) - {"name", "value"}:
            raise DesktopError("invalid_args")
        values = ()
        if name in ("switch", "set_service"):
            target = args.get("value")
            if not isinstance(target, str) or target not in SERVICES:
                raise DesktopError("invalid_args")
            values = (target,)
        elif name == "set_auto":
            if type(args.get("value")) is not bool:
                raise DesktopError("invalid_args")
            self._auto_desired = args["value"]
            values = (args["value"],)
        elif "value" in args:
            raise DesktopError("invalid_args")
        if name == "logout" or (name == "set_auto" and not values[0]):
            self._auto_desired = False
            before = self._snapshot_locked()
            try:
                # Save intent immediately, even while an auth operation is active.
                self._persist_prefs_locked(auto_reconnect=False)
            except DesktopError:
                self.engine.submit(name, *values)
                raise
            self._publish_locked(before)
        self.engine.submit(name, *values)
        return self._snapshot_locked()

    def _save_config_locked(self, args):
        if not args or set(args) - CONFIG_FIELDS:
            raise DesktopError("invalid_args")
        changes = dict(args)
        password = changes.get("password")
        if "password" in changes:
            if not isinstance(password, str):
                raise DesktopError("invalid_args")
            self._remember_password(password)
            if not password:
                changes.pop("password")
        before = self._snapshot_locked()
        try:
            update_config(self.path, **changes)
            self._refresh_config_locked()
        except (ValueError, TypeError):
            raise DesktopError("config_invalid") from None
        except OSError:
            raise DesktopError("save_failed") from None
        self._log_locked("success", "配置已保存")
        self._publish_locked(before)
        return self._snapshot_locked()

    def _save_prefs_locked(self, args):
        if not args or set(args) - {"theme", "close_to_tray"}:
            raise DesktopError("invalid_args")
        if "theme" in args and (not isinstance(args["theme"], str) or args["theme"] not in THEMES):
            raise DesktopError("invalid_args")
        if "close_to_tray" in args and type(args["close_to_tray"]) is not bool:
            raise DesktopError("invalid_args")
        before = self._snapshot_locked()
        self._persist_prefs_locked(**args)
        self._publish_locked(before)
        return self._snapshot_locked()

    def _browser_install_locked(self, args):
        if set(args) - {"cancel"} or ("cancel" in args and type(args["cancel"]) is not bool):
            raise DesktopError("invalid_args")
        if args.get("cancel"):
            if self._download_busy:
                self._download_cancel.set()
                self._emit("browser_install", {"state": "cancelling", "done": 0, "total": 0})
                return {"state": "cancelling"}
            return {"state": "idle"}
        if self._download_busy:
            raise DesktopError("download_busy")
        if not self.demo and (not self._environment["browser_component_available"]
                              or not node_runtime.supported()):
            raise DesktopError("browser_unavailable")
        before = self._snapshot_locked()
        self._download_cancel = threading.Event()
        self._download_busy = True
        self._publish_locked(before)
        self._emit("browser_install", {"state": "started", "done": 0, "total": 0})
        self._download_thread = threading.Thread(target=self._download, name="ysu-browser-download", daemon=True)
        self._download_thread.start()
        return {"state": "started"}

    def _download_progress(self, done, total):
        if self._download_cancel.is_set():
            raise InterruptedError
        with self._lock:
            if not self._closed:
                self._emit("browser_install", {"state": "progress", "done": max(0, int(done)),
                                               "total": max(0, int(total))})

    def _download(self):
        state = "completed"
        try:
            if self.demo:
                for done in range(1, 5):
                    if self._download_cancel.wait(0.05):
                        raise InterruptedError
                    self._download_progress(done, 4)
            else:
                if self._download_cancel.is_set():
                    raise InterruptedError
                self._installer(progress=self._download_progress, cancel=self._download_cancel)
            if self._download_cancel.is_set():
                raise InterruptedError
        except InterruptedError:
            state = "cancelled"
        except Exception:
            state = "failed"
        with self._lock:
            if self._closed:
                return
            before = self._snapshot_locked()
            self._download_busy = False
            if state == "completed":
                try:
                    self._environment = self._environment_reader()
                    if self.demo:
                        self._demo_installed = True
                        self._environment["node_available"] = True
                except (OSError, ValueError, RuntimeError):
                    state = "failed"
            message = {"completed": "浏览器认证组件已安装", "cancelled": "组件下载已取消",
                       "failed": "浏览器认证组件下载失败，请稍后重试"}[state]
            self._log_locked("error" if state == "failed" else "success" if state == "completed" else "info", message)
            self._publish_locked(before)
            self._emit("browser_install", {"state": state, "done": 0, "total": 0, "message": message})
