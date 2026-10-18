"""Shared v1 account book; the active Config remains the only credential authority.

Decision: .agents/notes/proposals/accounts/2026-10-14-account-rotation.md
"""
from copy import deepcopy
from dataclasses import replace
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import uuid

from .config import SERVICES, load_config, save_config
from .locking import configuration_write

MAX_BYTES = 64 * 1024
MAX_ACCOUNTS = 32
ACCOUNT_FIELDS = {"id", "label", "username", "password", "service", "backend", "enabled"}
ID_PATTERN = re.compile(r"[0-9a-f]{32}\Z")
CREDENTIAL_FIELDS = ("username", "password", "service", "backend")
SOURCE_FIELDS = CREDENTIAL_FIELDS + ("base", "cas_host", "verify_tls")


def accounts_path(path):
    return Path(path).with_suffix(".accounts.json")


def environment_override(environ=None):
    env = os.environ if environ is None else environ
    return any(key in env for key in ("YSU_USER", "YSU_PASS", "YSU_SERVICE"))


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("账号簿包含重复字段")
        result[key] = value
    return result


def validate_book(book):
    if not isinstance(book, dict) or set(book) != {"version", "auto_switch", "accounts"}:
        raise ValueError("账号簿字段无效")
    if type(book["version"]) is not int or book["version"] != 1:
        raise ValueError("账号簿版本无效")
    if type(book["auto_switch"]) is not bool:
        raise ValueError("auto_switch 须为布尔值")
    entries = book["accounts"]
    if not isinstance(entries, list) or len(entries) > MAX_ACCOUNTS:
        raise ValueError("账号簿最多保存 32 个账号")
    ids, usernames = set(), set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != ACCOUNT_FIELDS:
            raise ValueError("账号字段无效")
        if not isinstance(entry["id"], str) or not ID_PATTERN.fullmatch(entry["id"]):
            raise ValueError("账号 id 无效")
        if any(not isinstance(entry[key], str) for key in CREDENTIAL_FIELDS + ("label",)):
            raise ValueError("账号文本字段须为字符串")
        if (not entry["username"] or len(entry["label"]) > 80
                or any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in entry["label"])
                or entry["username"] != entry["username"].strip()
                or any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in entry["username"])
                or len(entry["username"].encode("utf-8")) > 256
                or not entry["password"] or len(entry["password"].encode("utf-8")) > 4096):
            raise ValueError("账号用户名、密码或标签格式无效")
        if entry["service"] not in SERVICES or entry["backend"] not in ("api", "browser"):
            raise ValueError("账号服务或认证方式无效")
        if type(entry["enabled"]) is not bool:
            raise ValueError("enabled 须为布尔值")
        if entry["id"] in ids or entry["username"] in usernames:
            raise ValueError("账号簿包含重复 id 或用户名")
        ids.add(entry["id"])
        usernames.add(entry["username"])
    return book


def _read_book(path):
    file = accounts_path(path)
    if not file.exists() and not file.is_symlink():
        return {"version": 1, "auto_switch": False, "accounts": []}
    # A bounded descriptor read avoids following a replaced symlink or loading an
    # arbitrarily large malformed file. Ownership never comes from file contents.
    flags = (os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
             | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0))
    if file.is_symlink():
        raise ValueError("账号簿路径为符号链接")
    fd = os.open(file, flags)
    with os.fdopen(fd, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError("账号簿须为普通文件")
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("账号簿超过 64 KiB")
    try:
        book = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise ValueError("账号簿 JSON 无效") from exc
    return validate_book(book)


def current_entry(config, *, id="current", label="", enabled=True):
    return {"id": id, "label": label, **{key: getattr(config, key) for key in CREDENTIAL_FIELDS},
            "enabled": enabled}


def load_accounts(path, *, config=None, overlay=True):
    """Viewing never migrates files; active credentials overwrite only the view."""
    book = _read_book(path)
    if not overlay:
        return book
    config = config or load_config(Path(path), environ={})
    entry = next((item for item in book["accounts"] if item["username"] == config.username), None)
    if entry is not None:
        entry.update({key: getattr(config, key) for key in CREDENTIAL_FIELDS})
    elif config.username and config.password:
        book["accounts"].append(current_entry(config))
    return book


def _write_book(path, book):
    validate_book(book)
    raw = (json.dumps(book, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if len(raw) > MAX_BYTES:
        raise ValueError("账号簿超过 64 KiB")
    file = accounts_path(path)
    file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name != "nt":
        file.parent.chmod(0o700)
    fd, temporary = tempfile.mkstemp(prefix=".accounts-", dir=file.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, file)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _flush_current(book, config):
    if not config.username or not config.password:
        raise ValueError("当前账号缺少凭据")
    entry = next((item for item in book["accounts"] if item["username"] == config.username), None)
    if entry is None:
        entry = current_entry(config, id=uuid.uuid4().hex)
        book["accounts"].append(entry)
    else:
        entry.update({key: getattr(config, key) for key in CREDENTIAL_FIELDS})
    validate_book(book)
    return entry


def public_accounts(path, *, quota=None, message="", environ=None):
    error = ""
    try:
        config = load_config(Path(path), environ={})
        book = load_accounts(path, config=config)
    except (OSError, ValueError):
        error = "账号簿或活动配置读取失败，请检查格式与权限"
        book = {"auto_switch": False, "accounts": []}
        config = None
    items = [{key: value for key, value in entry.items() if key != "password"}
             | {"password_set": bool(entry["password"]),
                "current": config is not None and entry["username"] == config.username}
             for entry in book["accounts"]]
    return {"items": items, "auto_switch": book["auto_switch"],
            "environment_override": environment_override(environ), "error": error,
            "quota": quota or {"state": "unknown", "message": "尚未取得有效流量报告"},
            "message": message}


def save_account(path, *, id=None, label="", username, password="", service="校园网",
                 backend="api", enabled=True):
    """Persist metadata, committing an active credential edit to Config first."""
    path = Path(path)
    with configuration_write(path):
        config = load_config(path, environ={})
        book = _read_book(path)
        entry = next((item for item in book["accounts"] if item["id"] == id), None)
        if id == "current":
            if not config.username or username != config.username:
                raise ValueError("当前账号身份已变化")
            entry = next((item for item in book["accounts"] if item["username"] == username), None)
        elif id is not None and entry is None:
            raise ValueError("账号 id 未找到")
        if entry is not None and username != entry["username"]:
            raise ValueError("已保存账号的用户名固定，请新增账号后切换")
        if entry is None and any(item["username"] == username for item in book["accounts"]):
            raise ValueError("账号用户名已保存")
        old_password = (config.password if username == config.username else entry["password"] if entry else "")
        # Only an explicit save of the synthetic current identity may reuse its
        # stored credential; ordinary new accounts always need a supplied password.
        retained = old_password if entry is not None or id == "current" else ""
        updated = {"id": entry["id"] if entry else uuid.uuid4().hex, "label": label,
                   "username": username, "password": password or retained,
                   "service": service, "backend": backend, "enabled": enabled}
        if not updated["password"]:
            raise ValueError("新账号必须填写密码")
        candidate = deepcopy(book)
        if entry is None:
            candidate["accounts"].append(updated)
        else:
            candidate["accounts"][book["accounts"].index(entry)] = updated
        validate_book(candidate)
        # Validate size before the first write. A later disk failure is reported,
        # not misrepresented as a transaction rollback across the two files.
        if len((json.dumps(candidate, ensure_ascii=False, indent=2) + "\n").encode("utf-8")) > MAX_BYTES:
            raise ValueError("账号簿超过 64 KiB")
        active = username == config.username
        if active:
            save_config(path, replace(config, **{key: updated[key] for key in CREDENTIAL_FIELDS}))
        try:
            _write_book(path, candidate)
        except (OSError, ValueError) as exc:
            if active:
                raise RuntimeError("活动配置已保存，但账号簿元数据保存失败") from exc
            raise
        return {key: value for key, value in updated.items() if key != "password"} | {"password_set": True}


def delete_account(path, id):
    with configuration_write(Path(path)):
        config = load_config(Path(path), environ={})
        book = _read_book(path)
        entry = next((item for item in book["accounts"] if item["id"] == id), None)
        if id == "current" or (entry is not None and entry["username"] == config.username):
            raise ValueError("活动账号请先切换再删除")
        if entry is None:
            raise ValueError("账号 id 未找到")
        book["accounts"].remove(entry)
        _write_book(path, book)


def set_rotation(path, enabled, *, auto_reconnect=False, environ=None):
    if type(enabled) is not bool:
        raise ValueError("轮换开关须为布尔值")
    with configuration_write(Path(path)):
        book = _read_book(path)
        if enabled:
            if environment_override(environ):
                raise ValueError("环境变量覆盖存在，账号轮换已停用")
            if not auto_reconnect:
                raise ValueError("开启账号轮换前请开启自动重连")
            config = load_config(Path(path), environ={})
            view = load_accounts(path, config=config)
            if sum(item["enabled"] and bool(item["username"] and item["password"])
                   for item in view["accounts"]) < 2:
                raise ValueError("账号轮换需要两个有效启用账号")
        book["auto_switch"] = enabled
        _write_book(path, book)


def source_signature(config):
    return tuple(getattr(config, key) for key in SOURCE_FIELDS)


def candidate_signature(entry):
    return tuple(entry[key] for key in ("id",) + CREDENTIAL_FIELDS + ("enabled",))


def prepare_switch(path, id, *, timeout=None, stop_event=None, expected_source=None):
    """Short lock: flush the latest source before any network transition."""
    with configuration_write(Path(path), timeout=timeout, stop_event=stop_event):
        source = load_config(Path(path), environ={})
        if expected_source is not None and source_signature(source) != source_signature(expected_source):
            raise ValueError("流量证据对应的活动账号已变化，本轮换号已停止")
        book = _read_book(path)
        current = _flush_current(book, source)
        target = next((item for item in book["accounts"] if item["id"] == id), None)
        if id == "current":
            target = current
        if target is None or not target["enabled"] or not target["password"]:
            raise ValueError("目标账号不存在、已停用或缺少凭据")
        _write_book(path, book)
        return source, deepcopy(target)


def unchanged_switch(path, source, target):
    latest = load_config(Path(path), environ={})
    book = _read_book(path)
    candidate = next((item for item in book["accounts"] if item["id"] == target["id"]), None)
    return (source_signature(latest) == source_signature(source)
            and candidate is not None and candidate_signature(candidate) == candidate_signature(target))


def commit_switch(path, source, target, *, timeout=None, stop_event=None):
    with configuration_write(Path(path), timeout=timeout, stop_event=stop_event):
        if not unchanged_switch(path, source, target):
            raise ValueError("源配置或候选已被修改，停止提交")
        latest = load_config(Path(path), environ={})
        desired = replace(latest, **{key: target[key] for key in CREDENTIAL_FIELDS})
        save_config(Path(path), desired)
        return desired
