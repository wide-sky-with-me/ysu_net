"""Interactive adapter over the shared account store and CLI commands.

Decision: .agents/notes/proposals/accounts/2026-10-14-account-rotation.md
"""
import sys

from . import ui
from .accounts import public_accounts, save_account
from .config import SERVICES


def show_accounts(view):
    ui.heading("多账号与自动换号")
    ui.row("自动换号配置", "开启（随运行中的自动重连生效）" if view["auto_switch"] else "关闭")
    if view["error"]:
        ui.message(view["error"], "warning")
    if view["environment_override"]:
        ui.hint("环境变量覆盖期间停用账号切换与开启自动换号。")
    for number, entry in enumerate(view["items"], 1):
        state = "当前 · " if entry["current"] else ""
        state += "启用" if entry["enabled"] else "停用"
        if not entry["password_set"]:
            state += " · 缺少密码"
        name = f'{entry["label"]} · {entry["username"]}' if entry["label"] else entry["username"]
        ui.row(str(number), f'{name} · {entry["service"]} · {ui.BACKENDS[entry["backend"]]} · {state}')
    if not view["items"] and not view["error"]:
        ui.hint("暂无账号；先配置当前账号，或选择 2 保存备用账号。")


def _select(view):
    value = input("  账号编号 [0 取消]: ").strip()
    if value in ("", "0"):
        return None
    try:
        number = int(value)
    except ValueError:
        raise ValueError("请输入列表中的账号编号") from None
    if not 1 <= number <= len(view["items"]):
        raise ValueError("账号编号超出列表范围")
    return view["items"][number - 1]


def _pick(title, values, default):
    ui.choices([f"{number} {value}" for number, value in enumerate(values, 1)])
    value = input(f"  {title} [Enter 保留 {default}，0 取消]: ").strip()
    if value == "0":
        return None
    if not value:
        return default
    if value in values:
        return value
    try:
        number = int(value)
    except ValueError:
        raise ValueError("请输入列出的选项") from None
    if not 1 <= number <= len(values):
        raise ValueError("选项超出范围")
    return values[number - 1]


def _confirm(message):
    return input(f"  {message} [y/N]: ").strip().casefold() in ("y", "yes", "是", "确认")


def _save(view, invoke, *, editing):
    entry = _select(view) if editing else None
    if editing and entry is None:
        return
    username = entry["username"] if entry else input("  用户名: ").strip()
    if not username:
        raise ValueError("用户名不能为空")
    if entry:
        ui.row("用户名（固定）", username)
    label = input("  名称（编辑时留空保留）: ").strip()
    if entry and not label:
        label = entry["label"]
    service = _pick("运营商", SERVICES, entry["service"] if entry else "校园网")
    if service is None:
        return
    backend = _pick("认证方式", ("api", "browser"), entry["backend"] if entry else "api")
    if backend is None:
        return
    command = ["accounts", "save", f"--label={label}", f"--service={service}", f"--backend={backend}"]
    if entry:
        command += [f'--id={entry["id"]}']
    command += ["--", username]
    # Password input remains in the existing getpass-only save command.
    invoke(command)


def run_menu(args, path, command):
    if not sys.stdin.isatty():
        ui.hint("多账号交互菜单请在终端运行；脚本用法：ysu accounts --help")
        return 0

    def invoke(tokens):
        code = command(["--scope", args.scope, "--config", str(path), *tokens])
        if code == 130:
            raise KeyboardInterrupt
        return code

    while True:
        view = public_accounts(path)
        show_accounts(view)
        ui.choices(["1 刷新账号列表", "2 新增账号", "3 编辑账号", "4 热切换账号", "5 删除账号",
                    "6 启用/停用候选", "7 开启自动换号", "8 关闭自动换号", "9 查询账户与剩余流量", "0 返回"])
        try:
            choice = input("  多账号操作 [0 返回]: ").strip()
            if choice in ("0", "q", "exit"):
                return 0
            if choice == "1":
                continue
            if choice == "8":
                invoke(["accounts", "rotation", "off"])
                continue
            if choice == "9":
                invoke(["info"])
                continue
            if choice not in ("2", "3", "4", "5", "6", "7"):
                ui.message("请输入菜单中的编号。", "warning")
                continue
            if view["error"]:
                ui.message("请先检查账号簿和当前配置；本次未修改。", "warning")
                continue
            if choice in ("4", "7") and view["environment_override"]:
                ui.message("环境变量覆盖期间停用账号切换与开启自动换号。", "warning")
                continue
            if choice in ("2", "3"):
                _save(view, invoke, editing=choice == "3")
            elif choice == "7":
                ui.hint("需先启动自动重连；连续两次确认零剩余流量才换号，额度未知不触发。")
                if _confirm("开启流量自动换号？"):
                    invoke(["accounts", "rotation", "on"])
            else:
                entry = _select(view)
                if entry is None:
                    continue
                if choice in ("4", "5") and entry["current"]:
                    ui.message("这是当前账号，无需切换。" if choice == "4" else "当前账号请先切换后再删除。", "warning")
                    continue
                if choice == "4":
                    if not entry["enabled"] or not entry["password_set"]:
                        ui.message("请先启用候选并补齐密码。", "warning")
                    elif _confirm("换号会短暂断网，继续？"):
                        invoke(["accounts", "switch", entry["id"]])
                elif choice == "5":
                    if _confirm("删除选中的保存账号？"):
                        invoke(["accounts", "delete", entry["id"]])
                else:
                    save_account(path, id=entry["id"], username=entry["username"], label=entry["label"],
                                 service=entry["service"], backend=entry["backend"], enabled=not entry["enabled"])
                    ui.message("候选状态已保存，当前网络连接保持不变。", "success")
        except (ValueError, RuntimeError, OSError) as exc:
            ui.message(exc, "error", stream=sys.stderr)
        except (KeyboardInterrupt, EOFError):
            ui.message("已退出多账号菜单。", "warning")
            return 130
