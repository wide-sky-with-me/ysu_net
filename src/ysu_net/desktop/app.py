"""Sidecar startup, isolated demo configuration and signal ownership."""
import argparse
from contextlib import ExitStack, redirect_stdout
from pathlib import Path
import signal
import sys
import tempfile
import threading


class _Parser(argparse.ArgumentParser):
    def _print_message(self, message, file=None):
        # Even --help is diagnostic output, not a JSON protocol response.
        super()._print_message(message, sys.stderr)


def _prepare_stdio():
    # Windowed frozen executables can have None streams despite inherited pipes.
    for name, descriptor, mode in (("stdin", 0, "r"), ("stdout", 1, "w"), ("stderr", 2, "w")):
        stream = getattr(sys, name)
        if stream is None:
            stream = open(descriptor, mode, encoding="utf-8", errors="replace", closefd=False)
            setattr(sys, name, stream)
        elif name != "stdin" and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    # Must precede argument parsing and desktop imports in frozen executables.
    if argv[:1] == ["--ysu-auth"]:
        from ysu_net.auth.worker import run
        return run(argv[1:])

    try:
        _prepare_stdio()
    except OSError:
        if sys.stderr is not None:
            print("后台通信通道初始化失败", file=sys.stderr)
        return 2
    parser = _Parser(description="YSU Net desktop JSON-lines sidecar")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--demo", action="store_true", help="offline simulation; never authenticate or download")
    args = parser.parse_args(argv)
    protocol_stdout = sys.stdout
    with ExitStack() as stack, redirect_stdout(sys.stderr):
        from ysu_net.manager.config import config_path, save_config
        from .core import DesktopCore, DesktopError, ERRORS
        from .demo import demo_config
        from .protocol import ProtocolServer, ProtocolWriter

        path = args.config
        if args.demo:
            # Never read or overwrite an operator-supplied profile in demo mode.
            temporary = stack.enter_context(tempfile.TemporaryDirectory(prefix="ysu-desktop-demo-"))
            path = Path(temporary) / "config.json"
        path = path if path is not None else config_path()
        try:
            if args.demo and not path.exists():
                save_config(path, demo_config())
            core = DesktopCore(path, demo=args.demo)
        except DesktopError as exc:
            print(ERRORS[exc.code], file=sys.stderr)
            return 2
        except (OSError, ValueError):
            print(ERRORS["config_invalid"], file=sys.stderr)
            return 2
        server = ProtocolServer(core, getattr(sys.stdin, "buffer", sys.stdin), ProtocolWriter(protocol_stdout))
        if threading.current_thread() is threading.main_thread():
            previous = {sig: signal.signal(sig, lambda *_: server.request_stop())
                        for sig in (signal.SIGTERM, signal.SIGINT)}
            stack.callback(lambda: [signal.signal(sig, handler) for sig, handler in previous.items()])
        return server.run()
