"""Regress compact copy, account identity disclosure, and long-name alignment."""
import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:1423/")
    parser.add_argument("--output", type=Path, default=Path("dist/desktop-detail-validation/after"))
    parser.add_argument("--baseline", action="store_true")
    args = parser.parse_args()
    assert urlsplit(args.url).hostname in ("localhost", "127.0.0.1")
    args.output.mkdir(parents=True, exist_ok=True)
    checks, errors, external = [], [], []

    def record(name, passed, **evidence):
        checks.append({"name": name, "ok": bool(passed), **evidence})

    with sync_playwright() as tool:
        browser = tool.chromium.launch(headless=True, executable_path="/usr/bin/google-chrome")
        context = browser.new_context(reduced_motion="reduce")
        context.route("**/*", lambda route: route.continue_() if urlsplit(route.request.url).hostname in ("localhost", "127.0.0.1") else (external.append(route.request.url), route.abort()))
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)

        def visit(theme, width, scenario=""):
            page.set_viewport_size({"width": width, "height": 560 if width == 700 else 720})
            page.goto(args.url + f"?demo=1&theme={theme}&scenario={scenario}")
            page.wait_for_load_state("networkidle")
            page.evaluate("document.fonts.ready")
            expect(page.locator(".connection-action")).to_be_enabled()

        for theme in ("light", "dark"):
            for width in (1000, 700, 390, 320):
                visit(theme, width)
                select = page.get_by_role("combobox", name="选择连接账号", exact=True)
                selected = select.locator("option:checked").inner_text()
                record(f"{theme}-{width}-complete-account-title", select.get_attribute("title") == selected, selected=selected, title=select.get_attribute("title"))
                if width <= 880:
                    descriptions = page.locator('.quota-status').evaluate_all("nodes => nodes.map(node => ({size: parseFloat(getComputedStyle(node).fontSize), x: node.getBoundingClientRect().x, width: node.getBoundingClientRect().width, parentX: node.parentElement.getBoundingClientRect().x, parentWidth: node.parentElement.getBoundingClientRect().width}))")
                    record(f"{theme}-{width}-readable-full-width-copy", len(descriptions) == 1 and all(row['size'] >= 11 and abs(row['x'] - row['parentX']) < 1 and abs(row['width'] - row['parentWidth']) < 1 for row in descriptions), measurements=descriptions)
                record(f"{theme}-{width}-no-horizontal-overflow", page.evaluate("document.documentElement.scrollWidth <= innerWidth") and page.locator("main").evaluate("node => node.scrollWidth <= node.clientWidth + 1"))
                page.screenshot(path=str(args.output / f"connection-{theme}-{width}.png"), full_page=True)

            visit(theme, 320)
            page.get_by_role("button", name="设置", exact=True).click()
            page.get_by_role("button", name="编辑常用账号", exact=True).click()
            editor = page.locator(".account-editor")
            long_name = "名称较长的校园网常用账号" * 2
            editor.get_by_label("名称", exact=True).fill(long_name)
            page.get_by_role("button", name="保存到账号簿", exact=True).click()
            expect(editor).to_have_count(0)
            row = page.locator('.account-list > li.current')
            label = row.locator("strong").bounding_box()
            badge = row.locator(".inline-label").bounding_box()
            record(f"{theme}-long-name-current-badge", badge["y"] <= label["y"] + 8 and badge["x"] >= label["x"] + label["width"], label=label, badge=badge)
            page.screenshot(path=str(args.output / f"long-account-{theme}.png"), full_page=True)
            page.get_by_role("button", name="编辑" + long_name, exact=True).click()
            editor.get_by_label("名称", exact=True).fill("")
            page.get_by_role("button", name="保存到账号簿", exact=True).click()
            expect(editor).to_have_count(0)
            page.get_by_role("button", name="连接", exact=True).click()
            option = page.locator('.account-choice-controls option:checked').inner_text()
            record(f"{theme}-unnamed-account-no-duplicate", option == "20260001 · 当前", option=option)

            visit(theme, 700, "empty")
            record(f"{theme}-empty-state-no-vertical-scroll", page.locator("main").evaluate("node => node.scrollHeight <= node.clientHeight + 1"))
            page.screenshot(path=str(args.output / f"empty-{theme}-700.png"))

        record("no-browser-errors", not errors, errors=errors)
        record("no-external-requests", not external, external=external)
        record("no-web-storage", page.evaluate("localStorage.length + sessionStorage.length") == 0)
        context.close()
        browser.close()
    report = {"ok": all(check["ok"] for check in checks), "mode": "offline-built-preview", "baseline": args.baseline, "real_authentication": False, "checks": checks}
    (args.output / "detail-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"ok": report["ok"], "passed": sum(check["ok"] for check in checks), "total": len(checks), "failed": [check["name"] for check in checks if not check["ok"]]}, ensure_ascii=False))
    raise SystemExit(0 if args.baseline or report["ok"] else 1)


if __name__ == "__main__":
    main()
