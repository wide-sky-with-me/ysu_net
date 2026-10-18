"""Run the native offline smoke and measure its complete owned process tree."""
import argparse
import ctypes
import ctypes.util
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import threading
import time
import psutil


def dismiss_native_menu():
    """Send Escape only to the dedicated X11 test display."""
    library = ctypes.util.find_library("Xtst")
    if not os.environ.get("DISPLAY") or not library:
        raise RuntimeError("Native menu smoke requires a dedicated X11 display and libXtst")
    x11 = ctypes.CDLL(ctypes.util.find_library("X11"))
    xtst = ctypes.CDLL(library)
    x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
    x11.XOpenDisplay.restype = ctypes.c_void_p
    x11.XKeysymToKeycode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    x11.XKeysymToKeycode.restype = ctypes.c_ubyte
    x11.XFlush.argtypes = [ctypes.c_void_p]
    x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
    xtst.XTestFakeKeyEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_ulong]
    display = x11.XOpenDisplay(None)
    if not display:
        raise RuntimeError("Could not open the dedicated X11 test display")
    try:
        key = x11.XKeysymToKeycode(display, 0xFF1B)
        if not key or not xtst.XTestFakeKeyEvent(display, key, 1, 0) or not xtst.XTestFakeKeyEvent(display, key, 0, 0):
            raise RuntimeError("Native menu Escape event failed")
        x11.XFlush(display)
    finally:
        x11.XCloseDisplay(display)


def live(process):
    try:
        return process.is_running() and process.status() != psutil.STATUS_ZOMBIE
    except psutil.Error:
        return False


def processes(root):
    try:
        return [root] + root.children(recursive=True)
    except psutil.Error:
        return []


def cpu(process):
    try:
        value = process.cpu_times()
        return value.user + value.system
    except psutil.Error:
        return 0


def measure(root, observed):
    time.sleep(0.25)
    initial = {process.pid: (process, cpu(process)) for process in processes(root)}
    started = time.monotonic()
    time.sleep(0.65)
    current = processes(root)
    duration = time.monotonic() - started
    rows = []
    total_cpu = 0
    for process in current:
        try:
            observed[process.pid] = process
            memory = process.memory_info()
            try:
                pss = getattr(process.memory_full_info(), "pss", None)
            except psutil.Error:
                pss = None
            rows.append({"pid": process.pid, "name": process.name(), "rss": memory.rss, "pss": pss})
            if process.pid in initial:
                total_cpu += max(0, cpu(process) - initial[process.pid][1])
        except psutil.Error:
            continue
    observed.update({pid: process for pid, (process, _) in initial.items()})
    stable = set(initial) == {process.pid for process in current}
    complete = bool(rows) and all(row["pss"] is not None for row in rows)
    return {"rss_mib": round(sum(row["rss"] for row in rows) / 2**20, 2),
            "pss_mib": round(sum(row["pss"] for row in rows) / 2**20, 2) if complete else None,
            "cpu_one_core_percent": round(total_cpu / duration * 100, 2) if stable else None,
            "sample_seconds": round(duration, 3), "process_set_stable": stable, "processes": rows}


def kill(process):
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)], capture_output=True, check=False)
    else:
        try:
            import signal
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("dist/tauri-smoke"))
    parser.add_argument("--capture-desktop", action="store_true", help="capture only a dedicated test display")
    args = parser.parse_args()
    binary, output = args.binary.resolve(), args.output.resolve()
    if not binary.is_file():
        raise SystemExit(f"Missing native binary: {binary}")
    output.mkdir(parents=True, exist_ok=True)
    native_report = output / "native-report.json"
    native_report.unlink(missing_ok=True)
    env = dict(os.environ, YSU_DESKTOP_SMOKE_REPORT=str(native_report), YSU_DESKTOP_DEMO="1")
    env["YSU_DESKTOP_SMOKE_TRAY_CAPTURE"] = "1" if args.capture_desktop and os.environ.get("DISPLAY") else "0"
    observed, measurements, runtime_names = {}, {}, set()
    events = queue.Queue()
    with (output / "native-stderr.log").open("w", encoding="utf-8") as stderr:
        process = subprocess.Popen([str(binary), "--smoke"], cwd=binary.parent, env=env, stdout=subprocess.PIPE,
                                   stderr=stderr, text=True, encoding="utf-8", start_new_session=os.name != "nt")
        stop_monitor = threading.Event()
        monitor = None
        try:
            root = psutil.Process(process.pid)
            observed[root.pid] = root

            def monitor_children():
                while not stop_monitor.wait(0.05):
                    for child in processes(root):
                        observed[child.pid] = child
                        try:
                            runtime_names.add(child.name().lower())
                        except psutil.Error:
                            pass

            monitor = threading.Thread(target=monitor_children, daemon=True)
            monitor.start()

            def read_output():
                for line in process.stdout:
                    events.put(line)
                events.put(None)

            threading.Thread(target=read_output, daemon=True).start()
            deadline = time.monotonic() + 85
            while time.monotonic() < deadline:
                try:
                    line = events.get(timeout=1)
                except queue.Empty:
                    if process.poll() is not None:
                        break
                    continue
                if line is None:
                    break
                print(line.rstrip(), flush=True)
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                phase = event.get("phase")
                if phase == "tray":
                    time.sleep(0.25)
                    if args.capture_desktop and os.environ.get("DISPLAY") and shutil.which("import"):
                        subprocess.run(["import", "-window", "root", str(output / "native-tray-menu.png")],
                                       timeout=5, check=True, capture_output=True)
                    dismiss_native_menu()
                if phase in ("visible", "background"):
                    measurements[phase] = measure(root, observed)
                    if phase == "visible" and args.capture_desktop and os.environ.get("DISPLAY") and shutil.which("import"):
                        subprocess.run(["import", "-window", "root", str(output / "native-visible.png")],
                                       timeout=5, check=True, capture_output=True)
            code = process.wait(timeout=max(1, deadline - time.monotonic()))
            if code:
                raise RuntimeError(f"Native smoke exited {code}; inspect {output / 'native-stderr.log'}")
        finally:
            if process.poll() is None:
                kill(process)
                process.wait(timeout=10)
            stop_monitor.set()
            if monitor is not None:
                monitor.join(timeout=2)
            process.stdout.close()
    report = json.loads(native_report.read_text(encoding="utf-8"))
    if not report.get("ok"):
        raise RuntimeError(f"Native smoke failed: {report}")
    deadline = time.monotonic() + 3
    while any(live(process) for process in observed.values()) and time.monotonic() < deadline:
        time.sleep(0.05)
    remaining = [process.pid for process in observed.values() if live(process)]
    if remaining:
        for process in observed.values():
            if live(process):
                process.kill()
        raise RuntimeError(f"Owned processes remained after quit: {remaining}")
    if set(measurements) != {"visible", "background"}:
        raise RuntimeError("Native smoke phase markers were missing")
    # WebView2 hosts the Windows UI itself; only a separate Edge/Chrome would be an auth runtime.
    forbidden = sorted(name for name in runtime_names
                       if name.startswith(("ysu-core", "python", "node", "chrome", "chromium", "msedge"))
                       and not name.startswith("msedgewebview2"))
    if forbidden:
        raise RuntimeError(f"Native demo started external authentication runtimes: {forbidden}")
    report.update(measurements=measurements, processes_cleaned=True, memory_scope="native-rust-demo-full-process-tree",
                  native_rust=True, no_auth_sidecar=True, observed_runtime_names=sorted(runtime_names),
                  memory_note="Short isolated samples, not a steady-state or real-auth benchmark")
    (output / "acceptance.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
