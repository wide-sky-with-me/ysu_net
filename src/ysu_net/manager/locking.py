from contextlib import contextmanager
import os
import time

if os.name == "nt":
    import msvcrt

    def _try_lock(stream):
        stream.seek(0)
        try:
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            raise BlockingIOError from None

    def _lock(stream):
        while True:
            try:
                return _try_lock(stream)
            except BlockingIOError:
                time.sleep(0.1)
else:
    import fcntl

    def _try_lock(stream):
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _lock(stream):
        fcntl.flock(stream, fcntl.LOCK_EX)


@contextmanager
def exclusive_config(path):
    """Serialize mutating commands against a daemon using the same profile."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with path.with_suffix(".lock").open("a+") as stream:
        try:
            _try_lock(stream)
        except BlockingIOError:
            raise RuntimeError("此配置已有守护进程运行；请先 ysu stop，或结束前台 ysu daemon") from None
        yield


@contextmanager
def configuration_write(path, *, timeout=None, stop_event=None):
    """Short shared write lock, optionally bounded by a caller's operation budget."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    deadline = None if timeout is None else time.monotonic() + max(0, timeout)
    with path.with_name(path.name + ".write.lock").open("a+") as stream:
        if deadline is None and stop_event is None:
            _lock(stream)
        else:
            while True:
                if stop_event is not None and stop_event.is_set():
                    raise TimeoutError("配置写入已取消，操作未确认")
                if deadline is not None and time.monotonic() >= deadline:
                    raise TimeoutError("配置写锁等待超时，操作未确认")
                try:
                    _try_lock(stream)
                    break
                except BlockingIOError:
                    time.sleep(min(0.05, max(0, deadline - time.monotonic())) if deadline is not None else 0.05)
        yield
