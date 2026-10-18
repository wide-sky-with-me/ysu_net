"""Windows rendering check: drive a real Windows Chrome over CDP.

Verifies layout, text truncation, scrollbar behaviour and font fallback on the
Windows side while the preview server runs in WSL, then saves screenshots.
"""
import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright

VIEWPORTS = ((1000, 720), (1280, 720), (700, 560), (520, 760), (390, 780))
PAGES = (("connection", None), ("account", "账户"), ("settings-account", "设置"), ("logs", "日志"))
SETTINGS_TABS = ("校园网账号", "外观与启动", "认证与重试", "环境诊断")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:1423/")
    parser.add_argument("--cdp", default="http://127.0.0.1:9222")
    parser.add_argument("--output", type=Path, default=Path("dist/windows-render-validation"))
    args = parser.parse_args()
    assert urlsplit(args.url).hostname in ("localhost", "127.0.0.1")
    args.output.mkdir(parents=True, exist_ok=True)
    checks, errors, external = [], [], []

    def record(name, ok, **data):
        checks.append({"name": name, "ok": bool(ok), **data})

    with sync_playwright() as tool:
        browser = tool.chromium.connect_over_cdp(args.cdp)
        context = browser.contexts[0]
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
        page.route("**/*", lambda route: route.continue_() if urlsplit(route.request.url).hostname in ("localhost", "127.0.0.1") else (external.append(route.request.url), route.abort()))

        def visit(theme="light", scenario=""):
            page.goto(f"{args.url}?demo=1&theme={theme}&scenario={scenario}")
            page.wait_for_load_state("networkidle")
            page.evaluate("document.fonts.ready.then(() => true)")
            expect(page.get_by_role("button", name="连接", exact=True)).to_be_visible()

        environment = page.evaluate("() => ({platform: navigator.platform, dpr: devicePixelRatio, ua: navigator.userAgent})")
        record("running-on-windows", environment["platform"] == "Win32", **environment)

        for theme in ("light", "dark"):
            for width, height in VIEWPORTS:
                page.set_viewport_size({"width": width, "height": height})
                visit(theme)
                prefix = f"{theme}-{width}x{height}"
                record(prefix + "-no-page-overflow", page.evaluate("document.documentElement.scrollWidth <= innerWidth"))
                record(prefix + "-font-fallback", page.evaluate('document.fonts.check(\'13px "Microsoft YaHei"\')') or page.evaluate('document.fonts.check(\'13px "Segoe UI"\')'))
                for name, nav in PAGES:
                    if nav:
                        page.get_by_role("button", name=nav, exact=True).click()
                        page.wait_for_timeout(120)
                    if name == "settings-account":
                        for tab in SETTINGS_TABS:
                            page.get_by_role("tab", name=tab, exact=True).click()
                            page.wait_for_timeout(90)
                            clipped = page.evaluate("""() => [...document.querySelectorAll('.settings-panel button, .settings-panel .section-heading h2, .settings-panel .form-row > span, .settings-panel .form-row > label')]
                                .filter(node => node.scrollWidth > node.clientWidth + 1).map(node => node.textContent.trim()).slice(0, 5)""")
                            record(f"{prefix}-{name}-{tab}-no-clipped-label", not clipped, clipped=clipped)
                            record(f"{prefix}-{name}-{tab}-no-overflow", page.evaluate("document.documentElement.scrollWidth <= innerWidth"))
                            page.screenshot(path=str(args.output / f"{prefix}-{name}-{tab}.png"))
                        continue
                    clipped = page.evaluate("""() => [...document.querySelectorAll('main button, main h1, main h2, .sidebar nav button span, .sidebar-status, .log-level, .account-summary dt')]
                        .filter(node => node.scrollWidth > node.clientWidth + 1).map(node => node.textContent.trim()).slice(0, 5)""")
                    record(f"{prefix}-{name}-no-clipped-text", not clipped, clipped=clipped)
                    record(f"{prefix}-{name}-content-visible", page.locator("main").evaluate("node => node.scrollHeight > 80"))
                    page.screenshot(path=str(args.output / f"{prefix}-{name}.png"))

        page.set_viewport_size({"width": 700, "height": 560})
        visit("light")
        page.get_by_role("button", name="设置", exact=True).click()
        page.get_by_role("tab", name="外观与启动", exact=True).click()
        page.wait_for_timeout(120)
        record("compact-tabs-single-row", page.locator(".settings-tabs").bounding_box()["height"] <= 46)
        record("compact-tabs-labels-visible", all(page.get_by_role("tab", name=tab, exact=True).is_visible() for tab in SETTINGS_TABS))
        quit_box = page.get_by_role("button", name="退出应用", exact=True).bounding_box()
        record("compact-quit-reachable", quit_box is not None and quit_box["height"] >= 28, box=quit_box)
        page.screenshot(path=str(args.output / "compact-appearance.png"))

        page.get_by_role("button", name="日志", exact=True).click()
        page.wait_for_timeout(120)
        toolbar = page.locator(".log-toolbar").bounding_box()
        record("compact-log-toolbar-fits", toolbar["height"] <= 64 and page.evaluate("document.documentElement.scrollWidth <= innerWidth"), box=toolbar)

        page.set_viewport_size({"width": 1000, "height": 720})
        visit("light")
        body_font = page.evaluate("getComputedStyle(document.body).fontFamily")
        record("font-stack-applied", "Manrope" in body_font and ("Microsoft YaHei" in body_font or "Noto Sans CJK" in body_font), fontFamily=body_font)
        record("no-browser-storage", page.evaluate("localStorage.length===0 && sessionStorage.length===0"))
        record("no-runtime-errors", not errors, errors=errors[:5])
        record("no-external-requests", not external, external_requests=external[:5])
        page.close()

    report = {"ok": all(row["ok"] for row in checks), "checks": checks}
    (args.output / "windows-render-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"ok": report["ok"], "passed": sum(row["ok"] for row in checks), "total": len(checks),
                      "failed": [row["name"] for row in checks if not row["ok"]]}, ensure_ascii=False))
    if not report["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
