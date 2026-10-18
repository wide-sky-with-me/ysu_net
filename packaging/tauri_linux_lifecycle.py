"""Test minimized-without-tray, single instance and a real X11 close request.

Run only inside a dedicated dbus-run-session and xvfb-run display.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import psutil
from tauri_smoke import kill, live, processes

X11 = r"""
#include <X11/Xlib.h>
#include <X11/Xatom.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
int main(int argc, char **argv) {
    if (argc != 3) return 2;
    Display *display = XOpenDisplay(NULL);
    if (!display) return 2;
    Window root = DefaultRootWindow(display), parent, *children;
    unsigned int count = 0;
    if (!XQueryTree(display, root, &root, &parent, &children, &count)) return 2;
    Atom pid_atom = XInternAtom(display, "_NET_WM_PID", False);
    for (unsigned int i = 0; i < count; ++i) {
        Atom type; int format; unsigned long items, after;
        unsigned char *data = NULL;
        XWindowAttributes attributes;
        XGetWindowProperty(display, children[i], pid_atom, 0, 1, False, XA_CARDINAL,
                           &type, &format, &items, &after, &data);
        int match = data && type == XA_CARDINAL && format == 32 && items == 1
                    && *(unsigned long *)data == strtoul(argv[1], NULL, 10);
        if (data) XFree(data);
        if (!match || !XGetWindowAttributes(display, children[i], &attributes)
            || attributes.map_state != IsViewable) continue;
        if (strcmp(argv[2], "close") == 0) {
            XEvent event = {0};
            event.xclient.type = ClientMessage;
            event.xclient.window = children[i];
            event.xclient.message_type = XInternAtom(display, "WM_PROTOCOLS", False);
            event.xclient.format = 32;
            event.xclient.data.l[0] = XInternAtom(display, "WM_DELETE_WINDOW", False);
            event.xclient.data.l[1] = CurrentTime;
            XSendEvent(display, children[i], False, NoEventMask, &event);
            XFlush(display);
        }
        printf("%lu\n", children[i]);
        XFree(children); XCloseDisplay(display); return 0;
    }
    if (children) XFree(children);
    XCloseDisplay(display); return 3;
}
"""


def wait_for(predicate, seconds=12):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(0.1)
    raise RuntimeError("Lifecycle condition timed out")


def legacy_runtime_pids(root):
    return {process.pid for process in processes(root) if live(process)
            and process.name().lower().startswith(("ysu-core", "python", "node", "chrome", "chromium"))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", required=True, type=Path)
    parser.add_argument("--output", default=Path("dist/tauri-smoke"), type=Path)
    args = parser.parse_args()
    binary, output = args.binary.resolve(), args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ysu-x11-") as temporary:
        source, probe = Path(temporary) / "probe.c", Path(temporary) / "probe"
        source.write_text(X11, encoding="ascii")
        subprocess.run(["cc", str(source), "-o", str(probe), "-lX11"], check=True, capture_output=True)
        with (output / "lifecycle-stderr.log").open("w", encoding="utf-8") as stderr:
            env = dict(os.environ, YSU_DESKTOP_DEMO="1")
            process = subprocess.Popen([str(binary), "--demo", "--minimized"], cwd=binary.parent, env=env,
                                       stdout=subprocess.DEVNULL, stderr=stderr, start_new_session=True)
            root = psutil.Process(process.pid)
            observed = []
            try:
                wait_for(lambda: subprocess.run([str(probe), str(root.pid), "visible"], capture_output=True).returncode == 0)
                assert not legacy_runtime_pids(root), "Native demo started an external authentication runtime"
                original = root.pid
                subprocess.run([str(binary), "--demo"], cwd=binary.parent, env=env, stdout=subprocess.DEVNULL,
                               stderr=stderr, check=True, timeout=8)
                assert process.poll() is None and root.pid == original, "Second instance replaced the original application"
                assert not legacy_runtime_pids(root), "Second instance started an authentication sidecar"
                observed = processes(root)
                subprocess.run([str(probe), str(root.pid), "close"], check=True, capture_output=True)
                assert process.wait(timeout=15) == 0, "Native close did not exit cleanly"
                wait_for(lambda: not any(live(child) for child in observed), seconds=3)
            finally:
                if process.poll() is None:
                    kill(process)
                    process.wait(timeout=10)
                for child in observed:
                    if live(child):
                        child.kill()
    report = {"ok": True, "mode": "demo", "no_tray_minimized_fallback": True,
              "single_instance": True, "native_close": True, "native_rust": True,
              "no_auth_sidecar": True, "processes_cleaned": True}
    (output / "linux-lifecycle.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
