"""Check glass surfaces, contrast bounds, and accessibility media in the built UI."""
import argparse
import json
import re
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

from clean_desktop_preview import contrast


def rgba(value):
    channels = [float(number) for number in re.findall(r"[\d.]+", value)]
    assert len(channels) in (3, 4), value
    return channels[:3], channels[3] if len(channels) == 4 else 1


def hex_color(channels):
    return "#" + "".join(f"{round(channel):02x}" for channel in channels)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:1423/")
    parser.add_argument("--output", type=Path, default=Path("dist/glass-desktop-validation/glass"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    results, errors = [], []
    # Sample translucent surfaces over each source color, not just the white fallback.
    stops = {"light": ("#edf5ff", "#43caee", "#bc9df3", "#7fe3cd", "#ffcab0"),
             "dark": ("#111f33", "#1687b4", "#7761b8", "#1e8f80")}
    with sync_playwright() as tool:
        browser = tool.chromium.launch(headless=True, executable_path="/usr/bin/google-chrome")
        page = browser.new_page(viewport={"width": 1000, "height": 720}, reduced_motion="reduce")
        page.on("pageerror", lambda error: errors.append(str(error)))
        for theme in ("light", "dark"):
            page.goto(args.url + f"?demo=1&theme={theme}")
            page.wait_for_load_state("networkidle")
            page.evaluate("document.fonts.ready.then(() => true)")
            expect(page.get_by_role("heading", name="校园网已连接", exact=True)).to_be_visible()
            active_background = page.locator('.sidebar nav button.active').evaluate("node => getComputedStyle(node).backgroundColor")
            gradient = page.locator(".app-shell").evaluate("node => getComputedStyle(node).backgroundImage")
            assert gradient.count("radial-gradient") >= 3, gradient
            page.screenshot(path=str(args.output / f"connection-{theme}.png"))
            for owner, text in ((".sidebar", ".brand span"), (".page-header", "h1"),
                                (".connection-context", ".state-copy h2"), (".connection-context", ".connection-details dt"),
                                (".connection-automation", ".auto-section p"), (".connection-context", ".connection-footer")):
                node = page.locator(owner).first
                color_node = node.locator(text).first if text else node
                style = node.evaluate("node => ({background: getComputedStyle(node).backgroundColor, radius: parseFloat(getComputedStyle(node).borderTopLeftRadius)})")
                foreground, _ = rgba(color_node.evaluate("node => getComputedStyle(node).color"))
                background, alpha = rgba(style["background"])
                assert 0.6 <= alpha < 1 and style["radius"] >= 14, (owner, style)
                for stop in stops[theme]:
                    underlay = [int(stop[index:index + 2], 16) for index in (1, 3, 5)]
                    composite = [alpha * front + (1 - alpha) * back for front, back in zip(background, underlay)]
                    ratio = contrast(hex_color(foreground), hex_color(composite))
                    results.append({"theme": theme, "surface": owner, "underlay": stop, "ratio": round(ratio, 2)})
                    assert ratio >= 4.5, results[-1]
            page.get_by_role("button", name="设置", exact=True).click()
            expect(page.locator('.sidebar nav button.active')).to_have_css('background-color', active_background)
            page.screenshot(path=str(args.output / f"settings-{theme}.png"))
            button = page.get_by_role("button", name="保存账号", exact=True)
            fill = button.evaluate("node => getComputedStyle(node).backgroundImage")
            foreground, _ = rgba(button.evaluate("node => getComputedStyle(node).color"))
            colors = re.findall(r"rgba?\([^)]+\)", fill)
            assert len(colors) == 2, fill
            endpoints = [rgba(color)[0] for color in colors]
            for index in range(21):
                fraction = index / 20
                background = [a * (1 - fraction) + b * fraction for a, b in zip(*endpoints)]
                ratio = contrast(hex_color(foreground), hex_color(background))
                assert ratio >= 4.5, (theme, "primary", fraction, ratio)
            client = page.context.new_cdp_session(page)
            client.send("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-reduced-transparency", "value": "reduce"}]})
            assert page.evaluate("matchMedia('(prefers-reduced-transparency: reduce)').matches")
            assert rgba(page.locator(".sidebar").evaluate("node => getComputedStyle(node).backgroundColor"))[1] == 1
            assert page.locator(".sidebar").evaluate("node => getComputedStyle(node).backdropFilter") == "none"
            page.screenshot(path=str(args.output / f"reduced-transparency-{theme}.png"))
            client.send("Emulation.setEmulatedMedia", {"features": []})
            client.detach()
            page.emulate_media(forced_colors="active")
            expect(button).to_be_visible()
            assert button.evaluate("node => getComputedStyle(node).backgroundImage") == "none"
            expect(button).to_have_css("forced-color-adjust", "none")
            page.screenshot(path=str(args.output / f"forced-colors-{theme}.png"))
            page.emulate_media(forced_colors="none")
        browser.close()
    assert not errors, errors
    report = {"ok": True, "mode": "offline-built-preview", "real_authentication": False,
              "surface_contrast_bounds": results, "primary_gradient_samples": 42,
              "reduced_transparency": True, "forced_colors": True, "page_errors": errors}
    (args.output / "glass-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Glass UI: {len(results)} composited contrast samples, primary gradients, selected hover, and accessibility media passed")


if __name__ == "__main__":
    main()
