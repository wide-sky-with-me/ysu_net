"""Small, dependency-free terminal presentation; machine output bypasses this module."""
import os
import re
import shutil
import sys
import unicodedata


COLORS = {"success": "32", "warning": "33", "error": "31", "info": "36", "title": "1;36"}
LABELS = {"success": "完成", "warning": "注意", "error": "失败", "info": "提示"}
BACKENDS = {"api": "API 认证", "browser": "浏览器认证"}
SERVICE_STATES = {
    "active": "运行中", "inactive": "已停止", "failed": "运行失败",
    "activating": "启动中", "deactivating": "停止中", "reloading": "重新加载中",
}


def is_terminal(stream=None):
    return bool(getattr(stream or sys.stdout, "isatty", lambda: False)())


def clean(value):
    # Do not interpret terminal controls contained in paths or server responses.
    value = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", str(value))
    return "".join(c for c in value if c in "\n\t" or (ord(c) >= 32 and ord(c) != 127))


def styled(text, kind, stream=None):
    stream = stream or sys.stdout
    text = clean(text)
    if is_terminal(stream) and "NO_COLOR" not in os.environ and os.environ.get("TERM") != "dumb":
        return f"\033[{COLORS[kind]}m{text}\033[0m"
    return text


def message(text, kind="info", *, stream=None, label=None):
    stream = stream or sys.stdout
    badge = styled(f"[{label or LABELS[kind]}]", kind, stream)
    print(f"{badge} {clean(text)}", file=stream)


def hint(text, *, stream=None):
    print(f"  → {clean(text)}", file=stream or sys.stdout)


def heading(title):
    print("\n" + styled(title, "title"))
    print("─" * min(52, max(12, shutil.get_terminal_size((80, 24)).columns - 1)))


def row(label, value):
    print(f"  {clean(label)}：{clean(value)}")


def choices(items):
    if shutil.get_terminal_size((80, 24)).columns < 64:
        for item in items:
            print("  " + item)
        return
    for index in range(0, len(items), 2):
        left = items[index]
        width = sum(2 if unicodedata.east_asian_width(c) in ("W", "F") else 1 for c in left)
        right = items[index + 1] if index + 1 < len(items) else ""
        print("  " + left + (" " * max(2, 30 - width) + right if right else ""))


def progress(text, *, raw=False):
    if not raw and is_terminal(sys.stderr):
        message(text, stream=sys.stderr, label="进行中")
        sys.stderr.flush()


def result_message(action, result, service):
    if action == "status" and result.code in (0, 1):
        online = result.code == 0
        message("校园网认证在线" if online else "校园网尚未连接",
                "success" if online else "warning", label="在线" if online else "离线")
        if not online:
            hint("登录一次：ysu login；自动重连：ysu on")
        return
    if result.code == 0:
        if action in ("login", "logout"):
            message("已确认校园网在线。" if action == "login" else "已确认校园网下线。", "success")
            if action == "login" and result.output:
                for line in clean(result.output).splitlines():
                    if line and not line.startswith(("[OK]", "在线：success", "网络状态：在线")):
                        print("  " + line)
        elif result.output:
            heading("校园网账户信息")
            print(clean(result.output).rstrip())
        return
    message(result.message, "warning" if result.code == 130 else "error", stream=sys.stderr)
    next_step = {
        2: "运行 ysu doctor 检查配置；确认已接入校园网后再试。",
        3: "结果尚未确认，可先运行 ysu status 查看当前状态。",
        4: "先 ysu stop，再用 ysu config account 检查账号，运行 ysu login 手动认证。",
    }.get(result.code)
    if next_step:
        hint(next_step, stream=sys.stderr)
