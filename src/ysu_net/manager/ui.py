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


def menu_help():
    heading("选项说明 · 用途与影响")
    hint("本页只显示帮助，不联网、不修改配置、不启动或停止服务。")
    descriptions = (
        ("1 查看状态", "联网查询是否在线；不登录、不下线，不改配置。"),
        ("2 登录一次", "使用当前配置登录；不启动后台。已在线时不自动切换运营商；后台运行时请先用 9 停止守护。"),
        ("3 开启自动重连", "启动后台守护；明确离线时会自动登录。不会自动开启开机自启。"),
        ("4 停止重连并下线", "先停止守护，再退出校园网；会中断当前网络，远程 SSH 可能断开。"),
        ("5 配置账号", "修改并保存账号密码；密码输入不回显，保存在私有配置文件。不会立即登录，守护后续会读取新配置。"),
        ("6 配置下次登录服务", "选择并保存运营商；不立即切换当前连接。立即切换需先停止守护，再执行 ysu switch <服务名>。"),
        ("7 本地诊断 doctor", "检查本地配置、权限、依赖及后台状态；不访问校园网，不自动修复配置。"),
        ("8 查看日志", "读取最近的后台日志；不会停止服务。持续跟随可用 ysu logs -f。"),
        ("9 仅停止重连", "停止后台守护，但保留当前网络连接；停止后掉线不会自动恢复。"),
        ("10 开启自启", "使服务随系统或用户管理器启动；不会立即启动当前服务。未登录时运行还需开启 linger。"),
        ("11 关闭自启", "取消后续自动启动；不会停止当前守护，也不会下线。立即停守护请选择 9。"),
        ("12 查看配置", "查看脱敏配置，不显示密码原文；不联网、不修改配置。"),
        ("13 账户与剩余流量", "联网查询账户、设备和门户提供的额度；不下线、不改配置。门户未返回额度时显示未提供，不代表零或不限量。"),
        ("14 联网诊断 doctor", "在本地检查基础上查询网络及实际运营商；不登录、不下线、不自动修复。"),
        ("15 选项说明", "显示本页；也可输入 h 或 ?。"),
        ("0 退出", "仅退出菜单；已启动的后台服务会继续运行，网络连接保持不变。"),
    )
    for label, description in descriptions:
        row(label, description)
    hint("首次使用：5 配置账号 → 6 选择服务 → 14 诊断 → 2 登录一次或 3 自动重连。")
    hint("只想暂停自动重连选 9；确定要断网才选 4。")

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
