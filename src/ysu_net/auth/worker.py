"""Run an authentication module as __main__ inside a frozen bundle.

The manager starts authentication in a child process; a PyInstaller executable has
no interpreter to pass ``-m`` to, so it re-enters itself with ``--ysu-auth``.
"""
import runpy
import sys

BACKENDS = ("api", "browser")


def _utf8_stdio():
    # A frozen bundle ignores PYTHONIOENCODING; the manager always decodes UTF-8,
    # and service names in the status JSON must survive a GBK console code page.
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name)
        if stream is None:  # Windowed executables may start without stdio objects.
            try:
                stream = open(1 if name == "stdout" else 2, "w", encoding="utf-8", closefd=False)
            except OSError:
                continue
            setattr(sys, name, stream)
        elif hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def run(argv):
    if argv[:1] == ["browser-check"]:
        _utf8_stdio()
        from ysu_net.auth.browser import self_check
        try:
            return self_check()
        except Exception as exc:  # noqa: BLE001 - report any launch failure
            print(f"[ERROR] {exc}", file=sys.stderr)
            return 2
    if not argv or argv[0] not in BACKENDS:
        print("[ERROR] unknown backend", file=sys.stderr)
        return 2
    _utf8_stdio()
    module = f"ysu_net.auth.{argv[0]}"
    sys.argv = [module, *argv[1:]]
    try:
        runpy.run_module(module, run_name="__main__", alter_sys=True)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 2)
    return 0
