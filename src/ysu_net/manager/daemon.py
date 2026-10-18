import logging
from pathlib import Path
import random
import signal
import threading
import time

from .account_switching import AccountController
from .backend import run_backend
from .config import load_config
from .control import ControlServer
from .locking import exclusive_config


class Reconnector:
    def __init__(self, runner=run_backend, jitter=random.uniform):
        self.runner = runner
        self.jitter = jitter
        self.failures = 0
        self.blocked_credentials = None

    def step(self, config):
        result = self.runner(config, "status")
        if result.code == 0:
            self.failures = 0
            self.blocked_credentials = None
            return config.check_interval, "在线"
        if result.code == 1:
            credentials = (config.username, config.password, config.service, config.backend)
            if self.blocked_credentials == credentials:
                return config.max_retry_interval, "认证已暂停：修改配置或手动登录后恢复"
            result = self.runner(config, "login")
            if result.code == 0:
                self.failures = 0
                return config.check_interval, "重连成功"
            if result.code == 4:
                self.blocked_credentials = credentials
                return config.max_retry_interval, result.message
        # Query failures never trigger login; both queries and transient login failures back off.
        self.failures = min(self.failures + 1, 20)
        delay = min(config.max_retry_interval, config.retry_interval * 2 ** (self.failures - 1))
        delay = min(config.max_retry_interval, delay + self.jitter(0, delay * 0.1))
        return delay, result.message


def run_daemon(config_file, *, once=False):
    config_file = Path(config_file)
    load_config(config_file)  # Validate before creating runtime files.
    with exclusive_config(config_file):
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
        stop = threading.Event()
        previous = {}
        for sig in (signal.SIGTERM, signal.SIGINT):
            previous[sig] = signal.signal(sig, lambda *_: stop.set())
        runner = lambda config, action, **kwargs: run_backend(config, action, stop_event=stop, **kwargs)
        worker = Reconnector(runner=runner)
        accounts = AccountController(config_file, runner=runner, stop_event=stop)
        control = ControlServer(config_file, accounts.handle)
        last_message = None
        next_check = 0.0
        try:
            control.start()
            while not stop.is_set():
                control.consume()
                now = time.monotonic()
                if now < next_check:
                    stop.wait(min(0.25, next_check - now))
                    continue
                try:
                    delay, message = worker.step(load_config(config_file))
                    rotation_message = accounts.rotation.step()
                    if rotation_message:
                        message += "；" + rotation_message
                except (ValueError, OSError):
                    delay, message = 30, "配置不可用，等待修复（未发起登录）"
                if message != last_message:
                    logging.info("%s；下次检查 %.0f 秒后", message, delay)
                    last_message = message
                if once:
                    return 0
                next_check = time.monotonic() + delay
        finally:
            control.close()
            for sig, handler in previous.items():
                signal.signal(sig, handler)
    return 0
