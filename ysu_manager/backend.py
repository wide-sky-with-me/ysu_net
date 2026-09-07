from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
import sys
import signal
import time


ROOT = Path(__file__).resolve().parent.parent
MESSAGES = {
    0: "操作成功",
    1: "离线",
    2: "查询或连接失败，在线状态未知",
    3: "操作失败或未在限定时间内生效",
    4: "认证需要人工处理，请检查账号密码、验证码或风控状态",
    130: "操作已取消",
}


@dataclass
class Result:
    code: int
    output: str = ""

    @property
    def message(self):
        return MESSAGES.get(self.code, "认证进程异常退出")


def _kill_process_group(process):
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait()


def run_backend(config, action, *, interactive=False, raw=False, stop_event=None):
    if action == "login" and not (config.username and config.password):
        return Result(4)
    command = [sys.executable, str(ROOT / f"ysu_{config.backend}.py"), action]
    if action == "login":
        command += ["--service", config.service, "--max-wait", "60"]
    elif action == "logout":
        command += ["--max-wait", "30"]
    if raw and action in ("info", "status"):
        command.append("--raw")
    env = os.environ.copy()
    env.update({
        "YSU_USER": config.username, "YSU_PASS": config.password,
        "YSU_BASE": config.base, "YSU_CAS_HOST": config.cas_host,
        "YSU_VERIFY_TLS": "1" if config.verify_tls else "0",
        "YSU_SAVE_DEBUG_FILES": "0", "PYTHONUNBUFFERED": "1",
    })
    try:
        process = subprocess.Popen(
            command, env=env, cwd=ROOT, text=True,
            stdin=None if interactive else subprocess.DEVNULL,
            stdout=None if interactive else subprocess.PIPE,
            stderr=None if interactive else subprocess.PIPE,
            start_new_session=True,
        )
    except OSError:
        return Result(2)
    deadline = time.monotonic() + config.operation_timeout
    try:
        while True:
            if stop_event is not None and stop_event.is_set():
                _kill_process_group(process)
                return Result(130)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _kill_process_group(process)
                return Result(3)
            try:
                output, _ = process.communicate(timeout=min(remaining, 0.5))
                break
            except subprocess.TimeoutExpired:
                continue
    except BaseException:
        _kill_process_group(process)
        raise
    # Background logs use only fixed messages, never raw authentication responses.
    return Result(process.returncode, output or "")
