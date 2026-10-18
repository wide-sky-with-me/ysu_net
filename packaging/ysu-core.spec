# Decision: .agents/notes/proposals/desktop/2026-10-14-tauri-migration.md
import importlib.util
import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, copy_metadata

root = Path(SPECPATH).parents[0]
with_browser = os.environ.get("YSU_CORE_WITH_BROWSER", "1") == "1"
datas, binaries, hidden = [], [], ["ysu_net.auth.api"]
if with_browser:
    if importlib.util.find_spec("playwright") is None:
        raise RuntimeError("Install the browser extra before building, or pass --api-only")
    datas, binaries, imports = collect_all("playwright")
    hidden += imports + ["ysu_net.auth.browser"]
datas += [(str(root / "LICENSE"), ".")] + copy_metadata("ysu-net-login")
analysis = Analysis(
    [str(root / "packaging/core_launcher.py")],
    pathex=[str(root / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden,
    excludes=["PySide6", "shiboken6", "PyQt6", "PyQt5", "tkinter", "_tkinter"],
)

# Filter after hooks as Playwright's built-in hook also collects its Node binary.
def keep(entry):
    name = entry[0].replace("\\", "/")
    return name not in ("playwright/driver/node", "playwright/driver/node.exe") and not name.endswith(".dist-info/direct_url.json")

analysis.datas = [entry for entry in analysis.datas if keep(entry)]
analysis.binaries = [entry for entry in analysis.binaries if keep(entry)]
archive = PYZ(analysis.pure)
executable = EXE(
    archive, analysis.scripts, analysis.binaries, analysis.datas, [],
    name="ysu-core", console=True, debug=False, strip=False, upx=False,
    target_arch=None, codesign_identity=os.environ.get("APPLE_SIGNING_IDENTITY"),
    entitlements_file=None,
)
