"""Install command wrappers and optional systemd units; never authenticate here."""
import argparse
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

from .backend import ROOT
from .config import Config, config_path, save_config
from .locking import exclusive_config
from .service import UNIT, render_unit, systemctl, unit_path
from . import ui


MARKER = "# Managed by ysu-net installer"


def bin_dir(scope):
    return Path("/usr/local/bin") if scope == "system" else Path.home() / ".local/bin"


def write_owned(path, text, mode):
    if path.is_symlink() or (path.exists() and MARKER not in path.read_text()):
        raise RuntimeError(f"目标已存在且不属于 ysu-net，未覆盖：{path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(mode)


def wrapper(scope, alias=None):
    command = [str(ROOT / ".venv/bin/python"), str(ROOT / "ysu.py"), "--scope", scope]
    if alias:
        command.append(alias)
    return "#!/usr/bin/env bash\n" + MARKER + "\nexec " + shlex.join(command) + ' "$@"\n'


def main(argv=None):
    ap = argparse.ArgumentParser(description="安装或卸载 ysu 管理命令")
    ap.add_argument("--system", action="store_true", help="系统级安装（需要 root）")
    ap.add_argument("--no-service", action="store_true", help="仅安装命令，不注册 systemd")
    ap.add_argument("--uninstall", action="store_true")
    ap.add_argument("--purge", action="store_true", help="卸载时同时删除配置")
    args = ap.parse_args(argv)
    scope = "system" if args.system else "user"
    if args.system and os.geteuid() != 0:
        ap.error("系统级安装需要 root；使用 sudo env PATH=\"$PATH\" bash install.sh --system")
    if args.purge and not args.uninstall:
        ap.error("--purge 仅用于卸载")
    target = unit_path(scope)
    config = config_path(scope)
    commands = {"ysu": None, "ysuon": "on", "ysuoff": "off"}
    ui.heading("卸载校园网管理工具" if args.uninstall else "安装校园网管理工具")
    ui.row("安装范围", "系统级" if scope == "system" else "当前用户")
    if args.uninstall:
        # Refuse to delete any foreign file before mutating the installation.
        paths = [target, *(bin_dir(scope) / name for name in commands)]
        for path in paths:
            if path.is_symlink() or (path.exists() and MARKER not in path.read_text()):
                raise RuntimeError(f"目标不属于 ysu-net，未删除：{path}")
        if target.exists():
            systemctl(scope, "disable", "--now", UNIT)
        with exclusive_config(config):
            if target.exists():
                target.unlink()
                systemctl(scope, "daemon-reload")
            for name in commands:
                (bin_dir(scope) / name).unlink(missing_ok=True)
            if args.purge:
                config.unlink(missing_ok=True)
        ui.message("管理命令和后台服务已卸载。", "success")
        ui.row("账号配置", "已删除" if args.purge else f"已保留 · {config}")
        ui.row("项目文件", "源码和 .venv 已保留")
        return 0
    if not (ROOT / ".venv/bin/python").exists():
        raise RuntimeError("缺少虚拟环境，请通过 bash install.sh 安装")
    # Check all collisions first, including the unit; keep existing credentials on reinstall.
    for path in [*(bin_dir(scope) / name for name in commands), *([] if args.no_service else [target])]:
        if path.is_symlink() or (path.exists() and MARKER not in path.read_text()):
            raise RuntimeError(f"目标已存在且不属于 ysu-net，未覆盖：{path}")
    if not config.exists():
        save_config(config, Config())
    for name, alias in commands.items():
        write_owned(bin_dir(scope) / name, wrapper(scope, alias), 0o755)
    has_service = not args.no_service and shutil.which("systemctl")
    if has_service:
        write_owned(target, render_unit(ROOT, config, scope), 0o644)
        systemctl(scope, "daemon-reload")
        ui.message("后台服务已注册。", "success")
        ui.hint("启动服务：ysu on；开启自启：ysu boot on")
    else:
        ui.message("命令已安装，可使用前台自动重连。", "success")
    ui.row("命令位置", bin_dir(scope) / "ysu")
    ui.row("配置文件", config)
    if str(bin_dir(scope)) not in os.environ.get("PATH", "").split(os.pathsep):
        ui.message("命令目录尚未加入 PATH，请在当前终端执行：", "warning")
        ui.hint(f"export PATH={shlex.quote(str(bin_dir(scope)))}:\"$PATH\"")
    command = "sudo ysu" if scope == "system" else "ysu"
    ui.heading("接下来")
    print(f"  1. 配置账号    {command} config account\n"
          f"  2. 选择服务    {command} service\n"
          f"  3. 检查环境    {command} doctor\n"
          f"  4. 接入校园网后    {command} {'on' if has_service else 'daemon'}")
    ui.hint(f"全部命令：{command} --help")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, OSError) as exc:
        ui.message(exc, "error", stream=sys.stderr)
        raise SystemExit(2)
