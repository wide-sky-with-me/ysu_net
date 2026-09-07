import os
from pathlib import Path
import shutil
import subprocess


UNIT = "ysu-net.service"


def unit_path(scope):
    if scope == "system":
        return Path("/etc/systemd/system") / UNIT
    return Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "systemd/user" / UNIT


def systemctl(scope, *arguments, check=True, capture=False):
    if not shutil.which("systemctl"):
        raise RuntimeError("未找到 systemd；可使用 ysu daemon 前台运行")
    command = ["systemctl"] + (["--user"] if scope == "user" else []) + list(arguments)
    result = subprocess.run(command, text=True, capture_output=capture)
    if check and result.returncode:
        raise RuntimeError("systemd 操作失败；请检查权限或用户会话，运行 ysu doctor 查看配置")
    return result


def service_action(scope, action):
    if not unit_path(scope).exists():
        raise RuntimeError("尚未安装服务；运行 bash install.sh，或使用 ysu daemon 前台运行")
    return systemctl(scope, action, UNIT, capture=True)


def quote_unit(value):
    # systemd performs percent-specifier and (ExecStart only) dollar expansion.
    value = str(value)
    if any(c in value for c in ("\n", "\r", "\x00")):
        raise ValueError("安装路径不能包含换行符")
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%') + '"'


def render_unit(root, config_file, scope):
    python = root / ".venv/bin/python"
    args = [python, "-m", "ysu_net", "--scope", scope, "--config", config_file, "daemon"]
    # systemd restricts executable-path characters more than argument characters.
    # A fixed env executable also handles checkouts containing spaces, quotes or $.
    command = "/usr/bin/env -- " + " ".join(quote_unit(arg).replace('$', '$$') for arg in args)
    return f"""# Managed by ysu-net installer
[Unit]
Description=YSU campus network automatic authentication
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart={command}
Restart=on-failure
RestartSec=15
KillMode=control-group
TimeoutStopSec=10
UMask=0077
NoNewPrivileges=true
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy={"default.target" if scope == "user" else "multi-user.target"}
"""
