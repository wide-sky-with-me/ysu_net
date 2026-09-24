"""Desktop-only preferences and per-user autostart, kept apart from the shared config."""
from dataclasses import asdict, dataclass, fields
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from ysu_net.paths import FROZEN

APP_ID = "ysu-net"
THEMES = ("system", "light", "dark")


@dataclass
class Prefs:
    theme: str = "system"
    close_to_tray: bool = True
    auto_reconnect: bool = False


def prefs_path(config_file):
    return Path(config_file).with_name("gui.json")


def load_prefs(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Prefs()
    known = {f.name: type(getattr(Prefs, f.name)) for f in fields(Prefs)}
    clean = {k: v for k, v in data.items() if k in known and type(v) is known[k]} if isinstance(data, dict) else {}
    prefs = Prefs(**clean)
    if prefs.theme not in THEMES:
        prefs.theme = "system"
    return prefs


def save_prefs(path, prefs):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix=".gui-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(asdict(prefs), stream, ensure_ascii=False, indent=2)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def launch_command():
    if FROZEN:
        return [sys.executable]
    python = Path(sys.executable)
    # pythonw avoids an empty console window when started from the Windows registry.
    if os.name == "nt" and (python.with_name("pythonw.exe")).exists():
        python = python.with_name("pythonw.exe")
    return [str(python), "-m", "ysu_net.gui"]


# ---- autostart ----
_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_RUN_VALUE = "YSU Net"


def _desktop_quote(arg):
    # Desktop Entry Exec quoting: reserved characters need a double-quoted argument.
    if arg and not any(c in arg for c in ' \t\n"\'\\><~|&;$*?#()`='):
        return arg
    return '"' + "".join("\\" + c if c in '"`$\\' else c for c in arg) + '"'


def autostart_file():
    base = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
    return base / "autostart" / f"{APP_ID}.desktop"


def desktop_entry(command, *, autostart=False):
    exec_line = " ".join(_desktop_quote(a) for a in command)
    lines = [
        "[Desktop Entry]", "Type=Application", "Name=YSU Net",
        "Name[zh_CN]=燕大校园网", "Comment=燕山大学校园网登录与自动重连",
        f"Exec={exec_line}", "Icon=ysu-net", "Terminal=false",
        "Categories=Network;", "StartupWMClass=ysu-net",
    ]
    if autostart:
        lines += ["X-GNOME-Autostart-enabled=true", "NoDisplay=true"]
    return "\n".join(lines) + "\n"


def autostart_enabled():
    if os.name == "nt":
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
                winreg.QueryValueEx(key, _RUN_VALUE)
            return True
        except OSError:
            return False
    return autostart_file().exists()


def set_autostart(enabled):
    command = launch_command() + ["--minimized"]
    if os.name == "nt":
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            if enabled:
                winreg.SetValueEx(key, _RUN_VALUE, 0, winreg.REG_SZ, subprocess.list2cmdline(command))
            else:
                try:
                    winreg.DeleteValue(key, _RUN_VALUE)
                except FileNotFoundError:
                    pass
        return
    path = autostart_file()
    if enabled:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(desktop_entry(command, autostart=True), encoding="utf-8")
    else:
        path.unlink(missing_ok=True)
