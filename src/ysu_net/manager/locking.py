from contextlib import contextmanager
import fcntl


@contextmanager
def exclusive_config(path):
    """Serialize mutating commands against a daemon using the same profile."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with path.with_suffix(".lock").open("a") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("此配置已有守护进程运行；请先 ysu stop，或结束前台 ysu daemon") from None
        yield


@contextmanager
def configuration_write(path):
    """Short write lock, separate from the daemon's lifetime operation lock."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with path.with_name(path.name + ".write.lock").open("a") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        yield
