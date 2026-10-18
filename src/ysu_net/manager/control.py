"""Bounded, private file IPC; the caller, not this module, owns the run lock.

Decision: .agents/notes/proposals/accounts/2026-10-14-account-rotation.md
"""

from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import stat
import threading
import time

from .locking import _try_lock


MAX_REQUESTS = 32
MAX_MESSAGE_BYTES = 16 * 1024
MAX_TIMEOUT = 300
POLL_INTERVAL = 0.01
_NONCE = re.compile(r"[0-9a-f]{32}\Z")
_REQUEST_FIELDS = {"version", "nonce", "owner", "action", "payload", "created_at", "expires_at"}
_UNKNOWN = "\u63a7\u5236\u8bf7\u6c42\u672a\u786e\u8ba4\uff1b\u64cd\u4f5c\u53ef\u80fd\u5df2\u5f00\u59cb\uff0c\u8bf7\u91cd\u65b0\u67e5\u8be2\u72b6\u6001"


class _Invalid(ValueError):
    pass


def _unknown():
    return {"code": 2, "message": _UNKNOWN}


def _nonce(value):
    return isinstance(value, str) and _NONCE.fullmatch(value) is not None


def _number(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def _action(action, payload):
    if not isinstance(payload, dict):
        raise _Invalid("Invalid payload")
    if action == "switch_account" and set(payload) == {"id"} and _nonce(payload["id"]):
        return
    if action == "rotation" and set(payload) == {"enabled"} and type(payload["enabled"]) is bool:
        return
    raise _Invalid("Invalid action")


def _decode(raw):
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise _Invalid("Duplicate JSON key")
            value[key] = item
        return value

    def constant(_):
        raise _Invalid("Nonfinite JSON")

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise _Invalid("Invalid JSON") from exc
    if not isinstance(value, dict):
        raise _Invalid("Expected JSON object")
    return value


def _encode(value):
    try:
        raw = json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError, RecursionError) as exc:
        raise _Invalid("Invalid result") from exc
    if len(raw) > MAX_MESSAGE_BYTES:
        raise _Invalid("Message too large")
    return raw


def _private(info, mode, *, directory=False):
    expected = stat.S_ISDIR if directory else stat.S_ISREG
    if not expected(info.st_mode):
        raise _Invalid("Expected private regular file or directory")
    if os.name != "nt":
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != mode:
            raise _Invalid("Invalid owner or permissions")
    if not directory and info.st_nlink != 1:
        raise _Invalid("Hard-linked file")


class _Directory:
    """Bind operations to a checked directory inode; use openat where available."""

    def __init__(self, path, *, create=False):
        self.path = Path(path)
        self.fd = None
        if create:
            self.path.mkdir(mode=0o700, exist_ok=True)
        self.info = self.path.lstat()
        _private(self.info, 0o700, directory=True)
        if os.name != "nt" and os.open in os.supports_dir_fd:
            self.fd = os.open(self.path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            opened = os.fstat(self.fd)
            if (opened.st_dev, opened.st_ino) != (self.info.st_dev, self.info.st_ino):
                self.close()
                raise _Invalid("Directory changed")

    def check(self):
        info = self.path.lstat()
        _private(info, 0o700, directory=True)
        if (info.st_dev, info.st_ino) != (self.info.st_dev, self.info.st_ino):
            raise _Invalid("Directory changed")

    def target(self, name):
        self.check()
        if self.fd is not None:
            return name, {"dir_fd": self.fd}
        return self.path / name, {}

    def open(self, name, flags):
        target, kwargs = self.target(name)
        before = None
        try:
            before = self.stat(name)
            _private(before, 0o600)
        except FileNotFoundError:
            pass
        fd = os.open(target, flags | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0), 0o600, **kwargs)
        try:
            info = os.fstat(fd)
            _private(info, 0o600)
            if before is not None and (before.st_dev, before.st_ino) != (info.st_dev, info.st_ino):
                raise _Invalid("File changed")
            self.check()
            return fd
        except BaseException:
            os.close(fd)
            raise

    def stat(self, name):
        target, kwargs = self.target(name)
        return os.stat(target, follow_symlinks=False, **kwargs)

    def names(self):
        self.check()
        names = []
        with os.scandir(self.fd if self.fd is not None else self.path) as entries:
            for entry in entries:
                names.append(entry.name)
                if len(names) > MAX_REQUESTS:
                    raise _Invalid("Too many channel entries")
        return sorted(names)

    def unlink(self, name):
        target, kwargs = self.target(name)
        try:
            os.unlink(target, **kwargs)
        except FileNotFoundError:
            pass

    def read(self, name):
        fd = self.open(name, os.O_RDONLY)
        with os.fdopen(fd, "rb") as stream:
            if os.fstat(stream.fileno()).st_size > MAX_MESSAGE_BYTES:
                raise _Invalid("Message too large")
            raw = stream.read(MAX_MESSAGE_BYTES + 1)
        if len(raw) > MAX_MESSAGE_BYTES:
            raise _Invalid("Message too large")
        return _decode(raw)

    def write(self, name, value, *, exclusive=False):
        raw = _encode(value)
        temporary = ".tmp-" + secrets.token_hex(16)
        fd = self.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            target, kwargs = self.target(name)
            source, source_kwargs = self.target(temporary)
            if exclusive:
                # Linking the complete temporary JSON is an atomic exclusive publish.
                os.link(source, target, follow_symlinks=False,
                        **({"src_dir_fd": self.fd, "dst_dir_fd": self.fd} if source_kwargs else {}))
            else:
                try:
                    _private(self.stat(name), 0o600)
                except FileNotFoundError:
                    pass
                os.replace(source, target,
                           **({"src_dir_fd": self.fd, "dst_dir_fd": self.fd} if kwargs else {}))
        finally:
            self.unlink(temporary)

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


@contextmanager
def _guard(root, *, deadline=None, monotonic=time.monotonic):
    fd = root.open("queue.lock", os.O_RDWR | os.O_CREAT)
    with os.fdopen(fd, "r+b") as stream:
        while True:
            try:
                _try_lock(stream)
                break
            except BlockingIOError:
                if deadline is None or monotonic() >= deadline:
                    raise TimeoutError("Control queue busy") from None
                time.sleep(POLL_INTERVAL)
        root.check()
        yield


def _owner(root):
    value = root.read("owner.json")
    if set(value) != {"version", "nonce"} or type(value["version"]) is not int or value["version"] != 1 or not _nonce(value["nonce"]):
        raise _Invalid("Invalid channel owner")
    return value["nonce"]


def _request(value, name, owner, now):
    if set(value) != _REQUEST_FIELDS or type(value["version"]) is not int or value["version"] != 1:
        raise _Invalid("Invalid request envelope")
    if not _nonce(value["nonce"]) or name != value["nonce"] + ".json" or value["owner"] != owner:
        raise _Invalid("Invalid request identity")
    _action(value["action"], value["payload"])
    created, expires = value["created_at"], value["expires_at"]
    if not _number(created) or not _number(expires) or not 0 <= created < expires or expires - created > MAX_TIMEOUT or created > now + 5:
        raise _Invalid("Invalid request deadline")
    if expires <= now:
        raise _Invalid("Expired request")
    return value


def _result(value):
    if not isinstance(value, dict) or type(value.get("code")) is not int or not isinstance(value.get("message"), str):
        raise _Invalid("Invalid handler result")
    _encode(value)
    return value


def _ack(value, nonce, owner, expires):
    if type(value.get("version")) is not int or value["version"] != 1 or value.get("nonce") != nonce or value.get("owner") != owner or value.get("expires_at") != expires:
        raise _Invalid("Invalid acknowledgment identity")
    if value.get("state") == "running":
        if set(value) != {"version", "nonce", "owner", "expires_at", "state"}:
            raise _Invalid("Invalid running acknowledgment")
        return None
    if value.get("state") != "done" or set(value) != {"version", "nonce", "owner", "expires_at", "state", "completed_at", "result"}:
        raise _Invalid("Invalid acknowledgment")
    if not _number(value["completed_at"]) or value["completed_at"] >= expires:
        raise _Invalid("Expired execution result")
    return _result(value["result"])


def _inventory(inbox, ack, owner, now, *, prune_requests=False, prune_running=False):
    occupied = set()
    for directory, pending in ((inbox, True), (ack, False)):
        remaining = set()
        for name in directory.names():
            nonce = name.removesuffix(".json")
            remaining.add(nonce)
            try:
                value = directory.read(name)
            except (OSError, ValueError):
                continue
            expiry = value.get("expires_at")
            expired = _number(expiry) and expiry <= now
            reclaimable = value.get("state") != "running" or (prune_running and not pending)
            if (not pending or prune_requests) and reclaimable and (expired or value.get("owner") != owner):
                directory.unlink(name)
                remaining.discard(nonce)
        occupied.update(remaining)
    if len(occupied) > MAX_REQUESTS:
        raise _Invalid("Control queue full")
    return occupied


class _ReplayFilter:
    """Fixed memory, no false negatives; rare collisions fail unconfirmed."""

    def __init__(self):
        self.bits = bytearray(64 * 1024)

    def seen(self, nonce):
        digest = hashlib.sha256(nonce.encode("ascii")).digest()
        offsets = [int.from_bytes(digest[index:index + 4], "big") % (8 * len(self.bits)) for index in (0, 4, 8, 12)]
        present = all(self.bits[bit // 8] & (1 << (bit % 8)) for bit in offsets)
        for bit in offsets:
            self.bits[bit // 8] |= 1 << (bit % 8)
        return present


class ControlServer:
    """Start only while holding the profile's lifetime lock; consume serially.

    ``handler(action, payload, expires_at)`` must use the supplied wall-clock
    deadline for its whole operation. Closing withdraws only this owner, leaving
    the private queue lock inode intact so old clients cannot split its lock.
    """

    def __init__(self, path, handler, *, clock=time.time):
        self.path = Path(path).with_suffix(".control")
        self.handler = handler
        self.clock = clock
        self.owner = None
        self._serial = threading.RLock()
        self._replay = _ReplayFilter()

    def start(self):
        with self._serial:
            if self.owner is not None:
                return self
            with _Directory(self.path, create=True) as root:
                with _guard(root, deadline=time.monotonic() + 1):
                    for name in root.names():
                        if name.startswith(".tmp-") and _nonce(name[5:]):
                            root.unlink(name)
                        elif name not in {"owner.json", "queue.lock", "inbox", "ack"}:
                            raise _Invalid("Invalid channel entry")
                    with _Directory(self.path / "inbox", create=True) as inbox, _Directory(self.path / "ack", create=True) as ack:
                        for directory in (inbox, ack):
                            for name in directory.names():
                                directory.unlink(name)
                        owner = secrets.token_hex(16)
                        root.write("owner.json", {"version": 1, "nonce": owner})
                        self.owner = owner
                        self._replay = _ReplayFilter()
            return self

    def consume(self, limit=1):
        """Consume at most one entry, including malformed or expired entries."""
        if type(limit) is not int or limit < 0:
            raise ValueError("limit must be a nonnegative integer")
        if not limit:
            return 0
        with self._serial:
            if self.owner is None:
                return 0
            try:
                return self._consume()
            except (OSError, ValueError, TimeoutError):
                return 0

    def _consume(self):
        with _Directory(self.path) as root, _Directory(self.path / "inbox") as inbox, _Directory(self.path / "ack") as ack:
            with _guard(root):
                if _owner(root) != self.owner:
                    return 0
                # The serial owner can reclaim expired markers after a lost final write.
                _inventory(inbox, ack, self.owner, self.clock(), prune_running=True)
                names = inbox.names()
                if not names:
                    return 0
                name = names[0]
                try:
                    request = _request(inbox.read(name), name, self.owner, self.clock())
                except (OSError, ValueError):
                    inbox.unlink(name)
                    return 1
                nonce = request["nonce"]
                expires = request["expires_at"]
                try:
                    ack.stat(name)
                except FileNotFoundError:
                    pass
                else:
                    # Any existing acknowledgment reserves this nonce, even if damaged.
                    inbox.unlink(name)
                    self._replay.seen(nonce)
                    return 1
                envelope = {"version": 1, "nonce": nonce, "owner": self.owner, "expires_at": expires, "state": "running"}
                repeated = self._replay.seen(nonce)
                ack.write(name, envelope, exclusive=True)
                inbox.unlink(name)
            result = _unknown()
            if not repeated and self.clock() < expires:
                try:
                    result = _result(self.handler(request["action"], request["payload"], expires))
                except Exception:
                    result = _unknown()
            completed = self.clock()
            if completed >= expires:
                result = _unknown()
            envelope.update(state="done", completed_at=completed, result=result)
            try:
                _encode(envelope)
            except _Invalid:
                envelope["result"] = _unknown()
            with _guard(root, deadline=time.monotonic() + 1):
                if _owner(root) == self.owner:
                    if self.clock() >= expires:
                        envelope["completed_at"] = self.clock()
                        envelope["result"] = _unknown()
                    ack.write(name, envelope)
            return 1

    def close(self):
        with self._serial:
            if self.owner is None:
                return
            try:
                with _Directory(self.path) as root:
                    with _guard(root, deadline=time.monotonic() + 1):
                        if _owner(root) != self.owner:
                            return
                        root.unlink("owner.json")
                        for subdir in ("inbox", "ack"):
                            with _Directory(self.path / subdir) as directory:
                                for name in directory.names():
                                    directory.unlink(name)
            except (OSError, ValueError, TimeoutError):
                pass
            finally:
                self.owner = None


def request_control(path, action, payload, *, timeout=180, clock=time.time, monotonic=time.monotonic):
    """Return the confirmed handler dictionary, or code 2 / unconfirmed.

    A queued request is withdrawn on timeout; a started operation is not
    cancelled. Enqueueing and waiting share one monotonic budget, with the
    requested timeout capped at MAX_TIMEOUT seconds.
    """
    channel = Path(path).with_suffix(".control")
    owner = nonce = None
    published = False
    try:
        _action(action, payload)
        if not _number(timeout) or timeout <= 0:
            return _unknown()
        timeout = min(timeout, MAX_TIMEOUT)
        created = clock()
        started = monotonic()
        if not _number(started):
            return _unknown()
        deadline = started + timeout
        if not _number(deadline) or deadline <= started:
            return _unknown()
        expires = created + timeout
        if not _number(created) or not _number(expires) or not 0 <= created < expires:
            return _unknown()
        with _Directory(channel) as root, _Directory(channel / "inbox") as inbox, _Directory(channel / "ack") as ack:
            with _guard(root, deadline=deadline, monotonic=monotonic):
                owner = _owner(root)
                occupied = _inventory(inbox, ack, owner, created, prune_requests=True)
                nonce = secrets.token_hex(16)
                if len(occupied) >= MAX_REQUESTS or nonce in occupied or monotonic() >= deadline or clock() >= expires:
                    return _unknown()
                name = nonce + ".json"
                inbox.write(name, {"version": 1, "nonce": nonce, "owner": owner, "action": action, "payload": payload,
                                  "created_at": created, "expires_at": expires}, exclusive=True)
                published = True
            while monotonic() < deadline and clock() < expires:
                with _guard(root, deadline=deadline, monotonic=monotonic):
                    if _owner(root) != owner:
                        return _unknown()
                    try:
                        result = _ack(ack.read(name), nonce, owner, expires)
                    except FileNotFoundError:
                        result = None
                    if result is not None and monotonic() < deadline and clock() < expires:
                        ack.unlink(name)
                        return result
                time.sleep(min(POLL_INTERVAL, max(0, deadline - monotonic())))
    except (OSError, ValueError, TypeError, TimeoutError, OverflowError):
        pass
    finally:
        if published:
            try:
                # Cleanup has a separate short bound and never claims cancellation.
                with _Directory(channel) as root, _Directory(channel / "inbox") as inbox:
                    with _guard(root, deadline=time.monotonic() + 0.1):
                        if _owner(root) == owner:
                            inbox.unlink(nonce + ".json")
            except (OSError, ValueError, TimeoutError):
                pass
    return _unknown()
