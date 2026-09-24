from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import tempfile
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
    return Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "ysu-net"


def config_path(scope="user"):
    return config_dir(scope) / "config.json"


def load_config(path, *, environ=None):
    data = {}
    if path.exists():
        try:
            data = json.loads(path.read_text())
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
        with os.fdopen(fd, "w") as stream:
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
