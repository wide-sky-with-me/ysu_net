"""Check the task-based desktop grid, reading order, and accessible surface states."""
import argparse
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright

from clean_desktop_preview import contrast


def channels(value):
    values = [float(number) for number in re.findall(r"[\d.]+", value)]
    assert len(values) in (3, 4), value
    return values[:3], values[3] if len(values) == 4 else 1


def color_hex(values):
    return "#" + "".join(f"{round(value):02x}" for value in values)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:1423/")
    parser.add_argument("--output", type=Path, default=Path("dist/flclash-layout-validation/design"))
    args = parser.parse_args()
    assert urlsplit(args.url).hostname in ("localhost", "127.0.0.1")
    args.output.mkdir(parents=True, exist_ok=True)
    checks, contrasts, errors, external = [], [], [], []

    with sync_playwright() as tool:
        browser = tool.chromium.launch(headless=True, executable_path="/usr/bin/google-chrome")
        context = browser.new_context(viewport={"width": 1000, "height": 720}, reduced_motion="reduce")
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
        context.route("**/*", lambda route: route.continue_() if urlsplit(route.request.url).hostname in ("localhost", "127.0.0.1") else (external.append(route.request.url), route.abort()))

        def visit(theme="light", scenario=""):
            page.goto(args.url + f"?demo=1&theme={theme}&scenario={scenario}")
            page.wait_for_load_state("networkidle")
            page.evaluate("document.fonts.ready.then(() => true)")
            expect(page.get_by_role("button", name="连接", exact=True)).to_be_visible()

        for theme in ("light", "dark"):
            for width in (1280, 1000, 881, 880, 700):
                page.set_viewport_size({"width": width, "height": 560 if width == 700 else 720})
                visit(theme)
                boxes = {name: page.locator(selector).first.bounding_box() for name, selector in {
                    "context": ".connection-context", "automation": ".connection-automation", "controls": ".connection-controls",
                    "account": ".account-choice", "service": ".service-section"}.items()}
                if width > 880:
                    assert abs(boxes["context"]["y"] - boxes["automation"]["y"]) < 1, boxes
                    assert boxes["automation"]["x"] > boxes["context"]["x"] + boxes["context"]["width"], boxes
                    assert abs(boxes["context"]["height"] - boxes["automation"]["height"]) < 1, boxes
                else:
                    assert boxes["context"]["y"] < boxes["automation"]["y"] < boxes["controls"]["y"], boxes
                    expect(page.get_by_role("button", name="环境诊断", exact=True)).to_be_visible()
                    assert float(page.locator(".sidebar-status").evaluate("node => getComputedStyle(node).fontSize").removesuffix("px")) >= 9
                assert abs(boxes["account"]["y"] - boxes["service"]["y"]) < 1, boxes
                assert boxes["account"]["x"] < boxes["service"]["x"], boxes
                assert page.locator("main").evaluate("node => node.scrollHeight <= node.clientHeight + 1"), boxes
                assert page.locator(".page-header").evaluate("node => getComputedStyle(node).backgroundColor === 'rgba(0, 0, 0, 0)' && getComputedStyle(node).boxShadow === 'none'")
                assert abs(page.locator(".page-header").bounding_box()["x"] - boxes["context"]["x"]) <= 4, boxes
                page.locator(".connection-action").focus()
                page.keyboard.press("Tab")
                expect(page.get_by_role("switch", name="自动重连", exact=True)).to_be_focused()
                page.keyboard.press("Tab")
                expect(page.get_by_role("switch", name="自动换号", exact=True)).to_be_focused()
                assert page.locator(".sidebar").evaluate("node => getComputedStyle(node).backdropFilter === 'none'")
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                checks.append({"theme": theme, "width": width, "grid": boxes, "keyboard_order": True})
                page.screenshot(path=str(args.output / f"connection-{theme}-{width}.png"))

            page.set_viewport_size({"width": 1000, "height": 720})
            visit(theme)
            for owner, selector in ((".sidebar", ".brand span"), (".sidebar nav button.active", "span"),
                                    (".connection-context", ".state-copy h2"), (".connection-context", ".connection-details dt"),
                                    (".connection-context", ".connection-footer"), (".quota-status", "span"),
                                    (".account-choice", "h2"), (".service-selector .selected", "span")):
                node = page.locator(owner).first
                fg, _ = channels(node.locator(selector).first.evaluate("node => getComputedStyle(node).color"))
                bg, alpha = channels(node.evaluate("node => getComputedStyle(node).backgroundColor"))
                canvas, _ = channels(page.locator("body").evaluate("node => getComputedStyle(node).backgroundColor"))
                composite = [alpha * a + (1 - alpha) * b for a, b in zip(bg, canvas)]
                ratio = contrast(color_hex(fg), color_hex(composite))
                contrasts.append({"theme": theme, "surface": owner, "ratio": round(ratio, 2)})
                assert ratio >= 4.5, contrasts[-1]

            page.get_by_role("button", name="设置", exact=True).click()
            button = page.get_by_role("button", name="保存账号", exact=True)
            fg, _ = channels(button.evaluate("node => getComputedStyle(node).color"))
            bg, _ = channels(button.evaluate("node => getComputedStyle(node).backgroundColor"))
            ratio = contrast(color_hex(fg), color_hex(bg))
            contrasts.append({"theme": theme, "surface": "primary", "ratio": round(ratio, 2)})
            assert ratio >= 4.5, contrasts[-1]
            client = context.new_cdp_session(page)
            client.send("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-reduced-transparency", "value": "reduce"}]})
            assert page.evaluate("matchMedia('(prefers-reduced-transparency: reduce)').matches")
            assert channels(page.locator(".settings-panel").evaluate("node => getComputedStyle(node).backgroundColor"))[1] == 1
            page.screenshot(path=str(args.output / f"reduced-transparency-{theme}.png"))
            client.send("Emulation.setEmulatedMedia", {"features": []})
            client.detach()
            page.emulate_media(forced_colors="active")
            for node in (button, page.locator(".sidebar nav button.active"), page.get_by_role("tab", selected=True)):
                expect(node).to_have_css("forced-color-adjust", "none")
                expect(node).to_be_visible()
            page.screenshot(path=str(args.output / f"forced-colors-{theme}.png"))
            page.emulate_media(forced_colors="none")
            active = page.locator(".sidebar nav button.active")
            before = active.evaluate("node => getComputedStyle(node).backgroundColor")
            active.hover()
            expect(active).to_have_css("background-color", before)
            page.locator('input[name="username"]').focus()
            page.keyboard.press("Tab")
            expect(page.locator('input[name="password"]')).to_be_focused()
            expect(page.locator(".password-control")).to_have_css("outline-style", "solid")

        for scenario in ("offline", "unknown", "external", "empty", "busy"):
            page.set_viewport_size({"width": 700, "height": 560})
            visit(scenario=scenario)
            assert page.locator("main").evaluate("node => node.scrollHeight <= node.clientHeight + 1"), scenario
            page.screenshot(path=str(args.output / f"scenario-{scenario}-700.png"))
        assert page.evaluate("localStorage.length + sessionStorage.length") == 0
        assert not errors, errors
        assert not external, external
        report = {"ok": True, "mode": "offline-built-preview", "real_authentication": False,
                  "layouts": checks, "contrast": contrasts, "scenario_checks": 5,
                  "reduced_transparency": True, "forced_colors": True, "keyboard_order": True,
                  "page_errors": errors, "external_requests": external}
        (args.output / "flclash-report.json").write_text(json.dumps(report, indent=2) + "\n")
        print(f"Task grid: {len(checks)} layouts, {len(contrasts)} contrast pairs, five compact states, keyboard order and accessibility media passed")
        context.close()
        browser.close()


if __name__ == "__main__":
    main()
