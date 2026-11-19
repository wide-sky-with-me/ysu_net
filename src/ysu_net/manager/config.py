from dataclasses import asdict, dataclass
from datetime import datetime, time as dt_time, timedelta
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import time
from urllib.parse import urlparse


SERVICES = ("校园网", "中国移动", "中国联通", "中国电信")


@dataclass
class Config:
    username: str = ""
    password: str = ""
    service: str = "校园网"
    backend: str = "api"
    base: str = "https://auth1.ysu.edu.cn"
    cas_host: str = "https://cer.ysu.edu.cn"
    verify_tls: bool = True
    check_interval: int = 15
    retry_interval: int = 30
    max_retry_interval: int = 900
    operation_timeout: int = 180

    def validate(self):
        if self.service not in SERVICES:
            raise ValueError("服务须为校园网、中国移动、中国联通或中国电信")
        if self.backend not in ("api", "browser"):
            raise ValueError("backend 须为 api 或 browser")
        for key in ("username", "password", "base", "cas_host"):
            if not isinstance(getattr(self, key), str):
                raise ValueError(f"{key} 须为字符串")
        for key in ("base", "cas_host"):
            url = urlparse(getattr(self, key))
            if url.scheme != "https" or not url.hostname or url.username or url.password:
                raise ValueError(f"{key} 须为不含账号密码的 HTTPS URL")
        if type(self.verify_tls) is not bool:
            raise ValueError("verify_tls 须为布尔值")
        for key in ("check_interval", "retry_interval", "max_retry_interval", "operation_timeout"):
            value = getattr(self, key)
            if type(value) is not int or not 1 <= value <= 86400:
                raise ValueError(f"{key} 须为 1–86400 秒的整数")
        if self.max_retry_interval < self.retry_interval:
            raise ValueError("max_retry_interval 不能小于 retry_interval")
        return self


def config_dir(scope="user"):
    if scope == "system":
        return Path("/etc/ysu-net")
    if os.name == "nt":
        appdata = os.environ.get("APPDATA")
        return (Path(appdata) if appdata else Path.home() / "AppData/Roaming") / "ysu-net"
    # XDG: an empty or relative value is invalid and must fall back to the default.
    xdg = os.environ.get("XDG_CONFIG_HOME", "")
    base = Path(xdg) if xdg and Path(xdg).is_absolute() else Path.home() / ".config"
    return base / "ysu-net"


def config_path(scope="user"):
    return config_dir(scope) / "config.json"


def load_config(path, *, environ=None):
    data = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError) as exc:
            raise ValueError("无法读取配置文件，请检查 JSON 格式和权限") from exc
        if not isinstance(data, dict) or set(data) - set(Config.__dataclass_fields__):
            raise ValueError("配置文件包含未知字段")
    env = os.environ if environ is None else environ
    # Explicit environment overrides are useful for CI and temporary credentials.
    for key, variable in (("username", "YSU_USER"), ("password", "YSU_PASS"), ("service", "YSU_SERVICE")):
        if variable in env:
            data[key] = env[variable]
    return Config(**data).validate()


def save_config(path, config):
    config.validate()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    # mkstemp creates 0600 files; replacement is atomic even when a daemon is reading.
    fd, temporary = tempfile.mkstemp(prefix=".config-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(asdict(config), stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def update_config(path, **changes):
    from .locking import configuration_write

    with configuration_write(path):
        config = load_config(path, environ={})
        for key, value in changes.items():
            if key not in Config.__dataclass_fields__:
                raise ValueError("配置文件包含未知字段")
            setattr(config, key, value)
        save_config(path, config)
        return config


def public_config(config):
    data = asdict(config)
    data["username"] = "已配置" if config.username else "未配置"
    data["password"] = "已配置" if config.password else "未配置"
    return data


NOSENSE_SERVICES = ("", "套餐默认服务") + SERVICES


def nosense_path(path):
    return Path(path).with_suffix(".nosense.json")


def _validate_nosense_rule(data):
    from ysu_net.auth.selfservice import normalize_mac

    if not isinstance(data, dict) or set(data) - {"auto_renew", "target_mac", "service"}:
        raise ValueError("无感认证配置字段无效")
    auto_renew = data.get("auto_renew", False)
    raw_mac = data.get("target_mac", "")
    service = data.get("service", "")
    if type(auto_renew) is not bool:
        raise ValueError("auto_renew 须为布尔值")
    if not isinstance(raw_mac, str):
        raise ValueError("target_mac 须为字符串")
    raw_mac = raw_mac.strip()
    if raw_mac and raw_mac.lower() != "current":
        mac = normalize_mac(raw_mac)
        if not mac:
            raise ValueError("MAC 地址格式无效")
    else:
        mac = ""
    if not isinstance(service, str) or service.strip() not in NOSENSE_SERVICES:
        raise ValueError("无感认证缺省服务无效")
    return {
        "auto_renew": auto_renew,
        "target_mac": mac,
        "service": service.strip(),
    }


def _validate_nosense(data):
    if not isinstance(data, dict) or set(data) - {"version", "auto_renew", "target_mac", "service", "accounts"}:
        raise ValueError("无感认证配置字段无效")
    version = data.get("version", 1)
    if type(version) is not int or version != 1:
        raise ValueError("无感认证配置版本无效")
    base_rule = _validate_nosense_rule({
        "auto_renew": data.get("auto_renew", False),
        "target_mac": data.get("target_mac", ""),
        "service": data.get("service", ""),
    })
    raw_accounts = data.get("accounts", {})
    if not isinstance(raw_accounts, dict) or len(raw_accounts) > 32:
        raise ValueError("无感认证账号池配置无效")
    accounts = {}
    for username, entry in raw_accounts.items():
        if (not isinstance(username, str) or not username.strip()
                or username != username.strip()
                or any(ord(c) < 32 or 127 <= ord(c) <= 159 for c in username)
                or len(username.encode("utf-8")) > 256):
            raise ValueError("无感认证账号名无效")
        accounts[username] = _validate_nosense_rule(entry)
    return {
        "version": 1,
        **base_rule,
        "accounts": accounts,
    }


def load_nosense(path):
    file = nosense_path(path)
    if not file.exists() and not file.is_symlink():
        return {"version": 1, "auto_renew": False, "target_mac": "", "service": "", "accounts": {}}
    if file.is_symlink():
        raise ValueError("无感认证配置路径为符号链接")
    try:
        data = json.loads(file.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise ValueError("无法读取无感认证配置") from exc
    return _validate_nosense(data)


def save_nosense(path, *, auto_renew=None, target_mac=None, service=None,
                 account=None, remove_account=None):
    from .locking import configuration_write

    file = nosense_path(path)
    with configuration_write(path):
        try:
            current = load_nosense(path)
        except ValueError:
            current = {"version": 1, "auto_renew": False, "target_mac": "", "service": "", "accounts": {}}
        accounts = dict(current.get("accounts", {}))
        if remove_account is not None:
            accounts.pop(remove_account, None)
        if account is not None:
            entry = dict(accounts.get(account, {"auto_renew": False, "target_mac": "", "service": ""}))
            if auto_renew is not None:
                entry["auto_renew"] = auto_renew
            if target_mac is not None:
                entry["target_mac"] = target_mac
            if service is not None:
                entry["service"] = service
            accounts[account] = entry
        elif remove_account is None:
            if auto_renew is not None:
                current["auto_renew"] = auto_renew
            if target_mac is not None:
                current["target_mac"] = target_mac
            if service is not None:
                current["service"] = service
        current["accounts"] = accounts
        validated = _validate_nosense(current)
        file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, temporary = tempfile.mkstemp(prefix=".nosense-", dir=file.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(validated, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
            os.replace(temporary, file)
        finally:
            Path(temporary).unlink(missing_ok=True)
        return validated


DEFAULT_NIGHT_WEEKDAYS = (0, 1, 2, 3, 6)
_TIME_HHMM = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
_HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def schedule_path(path):
    return Path(path).with_suffix(".schedule.json")


def _default_schedule():
    return {
        "version": 1,
        "night_pause": False,
        "start": "23:30",
        "end": "06:00",
        "weekdays": list(DEFAULT_NIGHT_WEEKDAYS),
    }


def _validate_schedule(data):
    if not isinstance(data, dict) or set(data) - {"version", "night_pause", "start", "end", "weekdays"}:
        raise ValueError("停网时段配置字段无效")
    version = data.get("version", 1)
    if type(version) is not int or version != 1:
        raise ValueError("停网时段配置版本无效")
    night_pause = data.get("night_pause", False)
    if type(night_pause) is not bool:
        raise ValueError("night_pause 须为布尔值")
    start = data.get("start", "23:30")
    end = data.get("end", "06:00")
    if not isinstance(start, str) or not isinstance(end, str):
        raise ValueError("时间须为 HH:MM 字符串")
    start = start.strip()
    end = end.strip()
    if not _TIME_HHMM.fullmatch(start) or not _TIME_HHMM.fullmatch(end) or start == end:
        raise ValueError("起止时间须为有效的 HH:MM 且不能相同")
    raw_days = data.get("weekdays", list(DEFAULT_NIGHT_WEEKDAYS))
    if (not isinstance(raw_days, (list, tuple)) or not raw_days or len(raw_days) > 7
            or any(type(d) is not int or not 0 <= d <= 6 for d in raw_days)):
        raise ValueError("星期范围须为 0–6 的非空整数列表")
    weekdays = sorted(set(raw_days))
    return {
        "version": 1,
        "night_pause": night_pause,
        "start": start,
        "end": end,
        "weekdays": weekdays,
    }


def load_schedule(path):
    file = schedule_path(path)
    if not file.exists() and not file.is_symlink():
        return _default_schedule()
    if file.is_symlink():
        raise ValueError("停网时段配置路径为符号链接")
    try:
        data = json.loads(file.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise ValueError("无法读取停网时段配置") from exc
    return _validate_schedule(data)


def save_schedule(path, *, night_pause=None, start=None, end=None, weekdays=None):
    from .locking import configuration_write

    file = schedule_path(path)
    with configuration_write(path):
        try:
            current = load_schedule(path)
        except ValueError:
            current = _default_schedule()
        if night_pause is not None:
            current["night_pause"] = night_pause
        if start is not None:
            current["start"] = start
        if end is not None:
            current["end"] = end
        if weekdays is not None:
            current["weekdays"] = list(weekdays)
        validated = _validate_schedule(current)
        file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, temporary = tempfile.mkstemp(prefix=".schedule-", dir=file.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(validated, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
            os.replace(temporary, file)
        finally:
            Path(temporary).unlink(missing_ok=True)
        return validated


def night_pause_until(now: datetime, schedule: dict) -> datetime | None:
    if not schedule or not schedule.get("night_pause"):
        return None
    sh, sm = map(int, schedule["start"].split(":"))
    eh, em = map(int, schedule["end"].split(":"))
    days = set(schedule["weekdays"])
    if (sh, sm) > (eh, em):
        for origin in (now.date(), now.date() - timedelta(days=1)):
            if origin.weekday() not in days:
                continue
            win_start = datetime.combine(origin, dt_time(sh, sm), tzinfo=now.tzinfo)
            win_end = datetime.combine(origin + timedelta(days=1), dt_time(eh, em), tzinfo=now.tzinfo)
            if win_start <= now < win_end:
                return win_end
        return None
    if now.date().weekday() in days:
        win_start = datetime.combine(now.date(), dt_time(sh, sm), tzinfo=now.tzinfo)
        win_end = datetime.combine(now.date(), dt_time(eh, em), tzinfo=now.tzinfo)
        if win_start <= now < win_end:
            return win_end
    return None


def protection_path(path):
    return Path(path).with_suffix(".protection.json")


def credential_identity_hash(config: Config) -> str:
    raw = f"{config.username}\0{config.password}\0{config.service}\0{config.backend}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def load_protection(path):
    file = protection_path(path)
    if not file.exists() and not file.is_symlink():
        return {"version": 1, "identity": "", "login_failures": 0, "blocked": False, "code4": False, "corrupted": False}
    if file.is_symlink():
        return {"version": 1, "identity": "", "login_failures": 3, "blocked": True, "code4": True, "corrupted": True}
    try:
        data = json.loads(file.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {"version": 1, "identity": "", "login_failures": 3, "blocked": True, "code4": True, "corrupted": True}
    valid = (
        isinstance(data, dict)
        and set(data) <= {"version", "identity", "login_failures", "blocked", "code4", "updated_at"}
        and type(data.get("version")) is int and data["version"] == 1
        and isinstance(data.get("identity"), str)
        and (data["identity"] == "" or _HEX_SHA256.fullmatch(data["identity"]) is not None)
        and type(data.get("login_failures")) is int and 0 <= data["login_failures"] <= 20
        and type(data.get("blocked")) is bool
        and type(data.get("code4", False)) is bool
    )
    if not valid:
        return {"version": 1, "identity": "", "login_failures": 3, "blocked": True, "code4": True, "corrupted": True}
    return {
        "version": 1,
        "identity": data["identity"],
        "login_failures": data["login_failures"],
        "blocked": data["blocked"],
        "code4": data.get("code4", False),
        "corrupted": False,
    }


def save_protection(path, *, identity: str, login_failures: int, blocked: bool, code4: bool = False):
    file = protection_path(path)
    payload = {
        "version": 1,
        "identity": identity,
        "login_failures": max(0, min(int(login_failures), 20)),
        "blocked": bool(blocked),
        "code4": bool(code4),
        "updated_at": int(time.time()),
    }
    file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix=".protection-", dir=file.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(temporary, file)
    finally:
        Path(temporary).unlink(missing_ok=True)


def clear_protection(path):
    try:
        protection_path(path).unlink(missing_ok=True)
    except OSError:
        pass
