import argparse
from contextlib import nullcontext
from dataclasses import fields
import getpass
import importlib.util
import json
from pathlib import Path
import shutil
import stat
import subprocess
import sys

from .backend import ROOT, run_backend
from .config import Config, SERVICES, config_path, load_config, public_config, save_config
from .daemon import run_daemon
from .locking import exclusive_config
from .service import UNIT, service_action, systemctl, unit_path
from . import ui


class FriendlyParser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        ui.message(message, "error", stream=sys.stderr, label="参数错误")
        ui.hint(f"查看用法：{self.prog} --help", stream=sys.stderr)
        self.exit(2)


def parser():
    ap = FriendlyParser(
        prog="ysu", description="燕山大学校园网 · 登录与自动重连",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="首次使用\n  ysu config account    配置账号密码\n  ysu doctor            检查本地环境\n  ysu on                启动自动重连\n\n常用操作\n  ysu                   打开交互菜单\n  ysu status            查看连接状态\n  ysu logs -f           跟随运行日志\n  ysu off               停止重连并下线\n\n脚本输出：ysu status --raw；禁用颜色：NO_COLOR=1 ysu status",
    )
    ap.add_argument("--scope", choices=("user", "system"), default="user", help="服务安装范围")
    ap.add_argument("--config", type=Path, help="指定配置文件")
    sub = ap.add_subparsers(dest="command", title="可用命令", metavar="命令")
    for command, help_text in (
        ("on", "启动后台自动重连"), ("off", "停止后台重连并下线"),
        ("start", "启动后台自动重连"), ("stop", "停止后台重连，保留当前连接"),
        ("restart", "重启后台自动重连"), ("login", "登录一次"),
        ("logout", "停止后台重连并下线"), ("menu", "打开交互菜单"),
    ):
        sub.add_parser(command, help=help_text)
    for command in ("status", "info"):
        p = sub.add_parser(command, help="查询校园网状态" if command == "status" else "查询账户信息")
        p.add_argument("--raw", action="store_true", help="输出 JSON")
    p = sub.add_parser("config", help="配置账号及运行参数")
    p.add_argument("action", choices=("show", "account", "set", "path"), default="show", nargs="?")
    p.add_argument("key", nargs="?")
    p.add_argument("value", nargs="?")
    p.add_argument("--raw", action="store_true", help="以 JSON 输出脱敏配置（show）")
    p = sub.add_parser("service", help="查看或切换校园网/运营商")
    p.add_argument("name", nargs="?", choices=SERVICES)
    p = sub.add_parser("backend", help="查看或切换认证实现")
    p.add_argument("name", nargs="?", choices=("api", "browser"))
    p = sub.add_parser("boot", help="管理开机自启")
    p.add_argument("action", choices=("on", "off", "status"), default="status", nargs="?")
    p = sub.add_parser("logs", aliases=["log"], help="查看守护进程日志")
    p.add_argument("--follow", "-f", action="store_true")
    p.add_argument("--lines", "-n", type=int, default=50)
    p = sub.add_parser("doctor", help="检查本地环境（默认不访问网络）")
    p.add_argument("--network", action="store_true", help="额外查询校园网状态")
    p = sub.add_parser("daemon", help="前台自动重连（也适用于无 systemd 环境）")
    p.add_argument("--once", action="store_true", help="仅执行一轮检查")
    return ap


def configure(args, path):
    # Configuration editing always reads the stored values, not environment overrides.
    config = load_config(path, environ={})
    if args.action == "path":
        print(path)
    elif args.action == "show":
        if args.raw or not ui.is_terminal():
            print(json.dumps(public_config(config), ensure_ascii=False, indent=2))
        else:
            ui.heading("当前配置")
            ui.row("账号", "已配置" if config.username else "未配置")
            ui.row("密码", "已配置" if config.password else "未配置")
            ui.row("服务", config.service)
            ui.row("认证方式", ui.BACKENDS[config.backend])
            ui.row("证书校验", "开启" if config.verify_tls else "关闭")
            for label, key in (("检查间隔", "check_interval"), ("首次重试间隔", "retry_interval"),
                               ("最长重试间隔", "max_retry_interval"), ("操作超时", "operation_timeout")):
                ui.row(label, f"{getattr(config, key)} 秒")
            ui.row("校园网入口", config.base)
            ui.row("统一认证入口", config.cas_host)
            ui.row("配置文件", path)
            ui.hint("修改参数：ysu config set <配置项> <值>；查看字段名：ysu config show --raw")
    elif args.action == "account":
        if not sys.stdin.isatty():
            raise ValueError("请在交互终端配置账号；自动化可使用 YSU_USER/YSU_PASS 环境变量")
        ui.heading("配置校园网账号")
        ui.hint("密码输入时不显示；按 Ctrl+C 取消。")
        username = input("  账号" + ("（留空保留原值）" if config.username else "") + ": ").strip()
        password = getpass.getpass("  密码" + ("（留空保留原值）" if config.password else "") + ": ")
        config.username = username or config.username
        config.password = password or config.password
        if not config.username or not config.password:
            raise ValueError("账号和密码不能为空")
        save_config(path, config)
        ui.message("账号已保存。", "success")
        ui.hint("检查环境：ysu doctor；在校园网内登录：ysu login")
    else:
        allowed = {field.name for field in fields(Config)} - {"username", "password"}
        if args.key not in allowed or args.value is None:
            raise ValueError("用法：ysu config set <配置项> <值>；账号密码请使用 ysu config account")
        value = args.value
        current = getattr(config, args.key)
        if type(current) is bool:
            if value.lower() not in ("true", "false"):
                raise ValueError("布尔值须为 true 或 false")
            value = value.lower() == "true"
        elif type(current) is int:
            try:
                value = int(value)
            except ValueError:
                raise ValueError(f"{args.key} 需要整数秒数，例如：ysu config set {args.key} 30") from None
        setattr(config, args.key, value)
        save_config(path, config)
        ui.message(f"已更新 {args.key}。", "success")
        ui.hint("守护进程将在下一轮读取配置；立即生效：ysu restart")
    return 0


def doctor(args, path):
    healthy = True
    passed = 0
    issues = 0
    ui.heading("环境诊断")

    def report(ok, message):
        nonlocal healthy, passed, issues
        ui.message(message, "success" if ok else "warning", label="通过" if ok else "待处理")
        passed += int(ok)
        issues += int(not ok)
        healthy = healthy and ok

    report(sys.version_info >= (3, 12), f"Python {sys.version.split()[0]}：{sys.executable}")
    report(path.exists(), f"配置文件：{path}")
    config = load_config(path)
    if path.exists():
        report(stat.S_IMODE(path.stat().st_mode) & 0o077 == 0, "配置文件应仅允许当前用户读写")
    report(bool(config.username and config.password), "账号密码已配置" if config.username and config.password else "运行 ysu config account 配置账号")
    for module in ("requests", "Crypto") + (("playwright",) if config.backend == "browser" else ()):
        report(importlib.util.find_spec(module) is not None, f"依赖 {module}")
    if config.backend == "browser" and importlib.util.find_spec("playwright"):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            report(Path(p.chromium.executable_path).exists(), "Chromium 文件（缺失时运行 uv run playwright install chromium）")
    ui.row("当前服务", f"{config.service} · {ui.BACKENDS[config.backend]}")
    ui.row("证书校验", "开启" if config.verify_tls else "关闭")
    if unit_path(args.scope).exists() and shutil.which("systemctl"):
        state = systemctl(args.scope, "is-active", UNIT, check=False, capture=True)
        ui.row("后台服务", ui.SERVICE_STATES.get(state.stdout.strip(), "不可用"))
    else:
        ui.row("后台服务", "未安装")
        ui.hint("安装服务：bash install.sh；前台运行：ysu daemon")
    if args.network:
        result = run_backend(config, "status")
        report(result.code in (0, 1), "校园网：" + ("在线" if result.code == 0 else result.message))
    else:
        ui.hint("本次只检查本地环境；连接诊断：ysu doctor --network")
    print()
    ui.message(f"{passed} 项通过，{issues} 项待处理。", "success" if healthy else "warning", label="诊断结果")
    return 0 if healthy else 2


def menu(args, path):
    if not sys.stdin.isatty():
        parser().print_help()
        return 0
    commands = {
        "1": ["status"], "2": ["login"], "3": ["on"], "4": ["off"],
        "5": ["config", "account"], "6": ["service"], "7": ["doctor"], "8": ["logs"],
        "9": ["stop"], "10": ["boot", "on"], "11": ["boot", "off"], "12": ["config", "show"],
    }
    while True:
        ui.heading("YSU · 燕山大学校园网")
        try:
            config = load_config(path)
            ui.row("当前服务", f"{config.service} · {ui.BACKENDS[config.backend]}")
            ui.row("账号", "已配置" if config.username and config.password else "未配置，请先选择 5")
        except (ValueError, OSError):
            ui.message("配置暂不可用，请选择 7 检查。", "warning")
        ui.row("管理范围", "当前用户" if args.scope == "user" else "系统级")
        ui.row("网络状态", "按 1 查询")
        print("\n  连接管理")
        ui.choices([" 1  查看状态", " 2  登录一次", " 3  开启自动重连", " 4  停止重连并下线", " 9  仅停止重连"])
        print("\n  配置与维护")
        ui.choices([" 5  配置账号", " 6  切换服务", " 7  环境诊断", " 8  查看日志", "10  开启自启", "11  关闭自启", "12  查看配置"])
        print("\n   0  退出\n")
        choice = input("  请输入编号 [0 退出]: ").strip()
        if choice in ("0", "q", "exit"):
            ui.message("已退出菜单。")
            return 0
        if choice in commands:
            main(["--scope", args.scope, "--config", str(path), *commands[choice]])
            if input("\n  按 Enter 返回菜单，输入 0 退出: ").strip() in ("0", "q", "exit"):
                ui.message("已退出菜单。")
                return 0
        else:
            ui.message("请输入菜单中的编号，或输入 0 退出。", "warning")


def dispatch(args):
    path = (args.config or config_path(args.scope)).expanduser().absolute()
    command = args.command
    default_path = config_path(args.scope).expanduser().absolute()
    if command in ("on", "start", "stop", "off", "restart", "boot") and path != default_path:
        raise ValueError("自定义配置请使用 ysu --config <路径> daemon；systemd 使用默认配置")
    if command in (None, "menu"):
        return menu(args, path)
    if command == "config":
        return configure(args, path)
    if command == "doctor":
        return doctor(args, path)
    if command in ("service", "backend"):
        config = load_config(path, environ={})
        value = args.name
        if value is None and command == "service" and sys.stdin.isatty():
            ui.heading("选择校园网服务")
            for i, name in enumerate(SERVICES, 1):
                print(f"  {i}  {name}" + ("  ← 当前" if name == config.service else ""))
            selection = input("服务编号（留空查看当前服务）: ").strip()
            if selection:
                if selection not in ("1", "2", "3", "4"):
                    raise ValueError("服务编号须为 1–4")
                value = SERVICES[int(selection) - 1]
        if value:
            setattr(config, command, value)
            save_config(path, config)
        ui.row("当前服务" if command == "service" else "认证方式", config.service if command == "service" else ui.BACKENDS[config.backend])
        if value:
            ui.message("配置已保存。", "success")
            ui.hint("切换已在线连接：ysu off → ysu on")
        return 0
    if command == "daemon":
        ui.progress("开始检查校园网状态。" if args.once else "自动重连运行中，按 Ctrl+C 停止。")
        return run_daemon(path, once=args.once)
    if command in ("on", "start", "restart"):
        config = load_config(path)
        if not config.username or not config.password:
            raise ValueError("请先运行 ysu config account")
        # Unit configuration is fixed at install time: do not silently operate another profile.
        ui.progress("正在启动自动重连…")
        service_action(args.scope, "restart" if command == "restart" else "start")
        ui.message("自动重连已启动。", "success")
        ui.hint("查看认证结果：ysu status；跟随日志：ysu logs -f")
        return 0
    if command in ("stop", "off", "logout"):
        if command == "stop" and not unit_path(args.scope).exists():
            raise RuntimeError("未安装 systemd 服务；前台 ysu daemon 请在其终端按 Ctrl+C 停止")
        if path == default_path and unit_path(args.scope).exists():
            ui.progress("正在停止自动重连…")
            service_action(args.scope, "stop")
        if command == "stop":
            ui.message("自动重连已停止，当前网络连接保留。", "success")
            return 0
    if command == "boot":
        if args.action == "status":
            state = systemctl(args.scope, "is-enabled", UNIT, check=False, capture=True)
            value = state.stdout.strip()
            label = {"enabled": "已开启", "enabled-runtime": "临时开启", "disabled": "已关闭",
                     "not-found": "尚未安装", "masked": "已被屏蔽"}.get(value, "不可用")
            ui.row("开机自启", label)
            return state.returncode
        service_action(args.scope, "enable" if args.action == "on" else "disable")
        ui.message("开机自启已开启。" if args.action == "on" else "开机自启已关闭。", "success")
        if args.scope == "user" and args.action == "on":
            ui.hint("需要未登录时也运行：请管理员执行 loginctl enable-linger <用户名>")
        return 0
    if command in ("logs", "log"):
        if args.lines < 1:
            raise ValueError("日志行数须大于 0")
        if not shutil.which("journalctl"):
            raise RuntimeError("未找到 journalctl；前台守护日志直接输出到终端")
        cmd = ["journalctl"] + (["--user"] if args.scope == "user" else [])
        cmd += ["-u", UNIT, "-n", str(args.lines), "--no-pager"]
        if args.follow:
            cmd.append("-f")
        ui.progress("正在跟随日志，按 Ctrl+C 退出查看。" if args.follow else f"读取最近 {args.lines} 行日志…")
        return subprocess.run(cmd).returncode
    action = "logout" if command in ("off", "logout") else command
    if action in ("login", "logout", "status", "info"):
        config = load_config(path)
        raw = getattr(args, "raw", False)
        ui.progress({"login": "正在登录校园网，请稍候…", "logout": "正在下线并确认结果…",
                     "status": "正在查询校园网状态…", "info": "正在读取账户信息…"}[action], raw=raw)
        with exclusive_config(path) if action in ("login", "logout") else nullcontext():
            result = run_backend(config, action, interactive=action in ("login", "logout") and sys.stdin.isatty(), raw=getattr(args, "raw", False))
        if raw and result.output and result.code in (0, 1):
            print(result.output, end="" if result.output.endswith("\n") else "\n")
        elif raw and result.code:
            print(result.message, file=sys.stderr)
        elif not raw:
            ui.result_message(action, result, config.service)
        return result.code
    raise ValueError("未知命令")


def main(argv=None):
    try:
        return dispatch(parser().parse_args(argv))
    except (ValueError, RuntimeError, OSError) as exc:
        ui.message(exc, "error", stream=sys.stderr)
        return 2
    except (KeyboardInterrupt, EOFError):
        ui.message("操作已取消。", "warning", stream=sys.stderr)
        return 130
