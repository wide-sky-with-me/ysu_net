from dataclasses import dataclass
import os
import subprocess
import sys
import signal
import time


from ysu_net.paths import FROZEN, PROJECT_ROOT as ROOT


AUTH_WORKER_FLAG = "--ysu-auth"
MESSAGES = {
    0: "操作成功",
    1: "离线",
    2: "查询或连接失败，在线状态未知",
    3: "操作失败或未在限定时间内生效",
    4: "认证需要人工处理，请检查账号密码、验证码或风控状态",
    130: "操作已取消",
}

REASONS = {
    "session_limit": "运营商同时在线数量已达上限，请先在其他终端正常下线后重试",
    "carrier_auth": "运营商认证需要人工处理，请检查账号绑定、密码或验证码",
    "service_mismatch": "实际在线服务与请求不一致；先停止守护，再用 ysu switch <服务名> 切换",
    "unknown_service": "门户未返回可识别的在线服务，暂不切换连接",
    "dns": "校园网域名解析失败，请检查 DNS 配置与校内 DNS 连通性",
    "tls": "HTTPS 证书校验失败，请检查系统时间及可信证书",
    "browser_component": "浏览器认证组件未安装：请在图形界面“设置”中下载，或改用 API 认证",
    "browser_missing": "未找到可用浏览器：请安装 Microsoft Edge 或 Google Chrome",
}


def failure_reason(code, error):
    # Classify fixed signatures; never forward a server message or credential.
    signatures = (
        (4, "运营商同时在线数量已达上限", "session_limit"),
        (4, "运营商认证需要人工处理", "carrier_auth"),
        (3, "在线服务与请求不一致", "service_mismatch"),
        (2, "在线响应未返回唯一可识别的服务", "unknown_service"),
        (2, "NameResolutionError", "dns"),
        (2, "Temporary failure in name resolution", "dns"),
        (2, "CERTIFICATE_VERIFY_FAILED", "tls"),
        (2, "浏览器认证组件未安装", "browser_component"),
        (2, "未找到可用浏览器", "browser_missing"),
    )
    return next((reason for expected, signature, reason in signatures
                 if code == expected and signature in error), "")


@dataclass
class Result:
    code: int
    output: str = ""
    reason: str = ""

    @property
    def message(self):
        return REASONS.get(self.reason, MESSAGES.get(self.code, "认证进程异常退出"))


def _kill_process_group(process):
    if os.name == "nt":
        # The browser backend spawns Chromium children; /T terminates the whole tree.
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)],
                       capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    process.wait()


def auth_command(backend):
    # A frozen bundle re-enters its own executable instead of an interpreter.
    if FROZEN:
        return [sys.executable, AUTH_WORKER_FLAG, backend]
    return [sys.executable, "-m", f"ysu_net.auth.{backend}"]


def _isolation():
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW}
    return {"start_new_session": True}


def run_backend(config, action, *, interactive=False, raw=False, stop_event=None):
    if action == "login" and not (config.username and config.password):
        return Result(4)
    command = auth_command(config.backend) + [action]
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
        "YSU_SAVE_DEBUG_FILES": "0", "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8",
    })
    try:
        process = subprocess.Popen(
            command, env=env, cwd=ROOT, text=True, encoding="utf-8", errors="replace",
            stdin=None if interactive else subprocess.DEVNULL,
            stdout=None if interactive else subprocess.PIPE,
            stderr=None if interactive else subprocess.PIPE,
            **_isolation(),
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
                output, error = process.communicate(timeout=min(remaining, 0.5))
                break
            except subprocess.TimeoutExpired:
                continue
    except BaseException:
        _kill_process_group(process)
        raise
    # Background logs use only fixed messages, never raw authentication responses.
    reason = failure_reason(process.returncode, error or "")
    return Result(process.returncode, output or "", reason)
