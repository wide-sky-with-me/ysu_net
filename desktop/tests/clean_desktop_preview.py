"""Verify the clean desktop layout against the actual built offline preview."""
import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright


def contrast(left, right):
    def luminance(color):
        raw = color.strip().lstrip("#")
        if len(raw) == 3:
            raw = "".join(channel * 2 for channel in raw)
        assert len(raw) == 6, color
        channels = [int(raw[i:i + 2], 16) / 255 for i in (0, 2, 4)]
        linear = [value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4 for value in channels]
        return sum(value * weight for value, weight in zip(linear, (0.2126, 0.7152, 0.0722)))
    values = sorted((luminance(left), luminance(right)))
    return (values[1] + 0.05) / (values[0] + 0.05)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:1423/")
    parser.add_argument("--browser", default="/usr/bin/google-chrome")
    parser.add_argument("--output", type=Path, default=Path("dist/clean-desktop-validation/visual"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    errors, external, layouts, contrasts = [], [], [], []
    origin = urlsplit(args.url)

    with sync_playwright() as tool:
        browser = tool.chromium.launch(headless=True, executable_path=args.browser)
        context = browser.new_context(viewport={"width": 1000, "height": 720}, reduced_motion="reduce")
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
        page.on("request", lambda request: external.append(request.url)
                if urlsplit(request.url).hostname != origin.hostname else None)

        def visit(theme):
            page.goto(args.url + f"?demo=1&theme={theme}")
            page.wait_for_load_state("networkidle")
            page.evaluate("document.fonts.ready.then(() => true)")
            expect(page.get_by_role("heading", name="校园网已连接", exact=True)).to_be_visible()

        def audit(name):
            result = page.evaluate("""() => {
                const main = document.querySelector('main');
                const collisions = [...document.querySelectorAll('.form-row, .setting-row')].filter(row => {
                    if (row.children.length < 2) return false;
                    const a = row.children[0].getBoundingClientRect(), b = row.children[1].getBoundingClientRect();
                    return a.right > b.left - 4;
                }).map(row => row.textContent.trim());
                const clipped = [...document.querySelectorAll('main button, .service-selector')].filter(node => {
                    const rect = node.getBoundingClientRect(), parent = main.getBoundingClientRect();
                    return rect.left < parent.left - 1 || rect.right > parent.right + 1 || node.scrollWidth > node.clientWidth + 2;
                }).map(node => node.textContent.trim());
                return { viewport: [innerWidth, innerHeight],
                    document_overflow: document.documentElement.scrollWidth > innerWidth,
                    main_overflow: main.scrollWidth > main.clientWidth + 1, collisions, clipped };
            }""")
            result["name"] = name
            layouts.append(result)
            assert not result["document_overflow"], result
            assert not result["main_overflow"], result
            assert not result["collisions"], result
            assert not result["clipped"], result

        for theme in ("light", "dark"):
            page.set_viewport_size({"width": 1000, "height": 720})
            visit(theme)
            expect(page.locator(".connection-overview")).to_have_css("border-top-width", "0px")
            assert page.locator("main").evaluate("node => node.scrollHeight <= node.clientHeight + 1"), "Default connection page needs scrolling"
            boxes = [page.locator(selector).bounding_box() for selector in (".account-choice", ".service-section")]
            assert abs(boxes[0]["y"] - boxes[1]["y"]) < 2
            assert boxes[0]["x"] + boxes[0]["width"] < boxes[1]["x"]
            expect(page.get_by_role("switch", name="自动换号", exact=True)).to_be_in_viewport()
            page.screenshot(path=str(args.output / f"connection-{theme}.png"))
            audit(f"connection-{theme}-1000")
            colors = page.evaluate("""() => Object.fromEntries(['text','muted','canvas','field','sidebar','accent','on-accent'].map(key =>
                [key, getComputedStyle(document.documentElement).getPropertyValue('--' + key).trim()]))""")
            for foreground, background in (("text", "canvas"), ("muted", "canvas"), ("muted", "field"),
                                           ("muted", "sidebar"), ("accent", "canvas"), ("on-accent", "accent")):
                ratio = contrast(colors[foreground], colors[background])
                contrasts.append({"theme": theme, "pair": f"{foreground}/{background}", "ratio": round(ratio, 2)})
                assert ratio >= 4.5, contrasts[-1]
            for destination in ("账户", "设置", "日志"):
                page.get_by_role("button", name=destination, exact=True).click()
                audit(f"{destination}-{theme}-1000")
                page.screenshot(path=str(args.output / f"page-{destination}-{theme}.png"))
            page.get_by_role("button", name="设置", exact=True).click()
            for tab in ("外观与启动", "认证与重试", "环境诊断"):
                page.get_by_role("tab", name=tab, exact=True).click()
                audit(f"{tab}-{theme}-1000")
                page.screenshot(path=str(args.output / f"settings-{tab}-{theme}.png"))

        for width, height in ((1280, 900), (860, 640), (700, 560), (520, 720), (390, 844), (320, 720)):
            page.set_viewport_size({"width": width, "height": height})
            for theme in ("light", "dark"):
                visit(theme)
                audit(f"connection-{theme}-{width}")
                page.screenshot(path=str(args.output / f"connection-{theme}-{width}.png"), full_page=True)
                page.get_by_role("button", name="设置", exact=True).click()
                for tab in ("校园网账号", "外观与启动", "认证与重试", "环境诊断"):
                    page.get_by_role("tab", name=tab, exact=True).click()
                    audit(f"{tab}-{theme}-{width}")
        assert page.evaluate("localStorage.length + sessionStorage.length") == 0
        version = browser.version
        browser.close()

    assert not errors, errors
    assert not external, external
    result = {"ok": True, "browser_version": version, "mode": "built-offline-preview", "real_authentication": False,
              "layouts": layouts, "contrast": contrasts, "errors": errors, "external_requests": external}
    (args.output / "clean-desktop-report.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Clean desktop: {len(layouts)} layouts and {len(contrasts)} text contrast pairs passed; no console errors or external requests")


if __name__ == "__main__":
    main()
