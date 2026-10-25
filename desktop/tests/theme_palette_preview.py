"""Audit rendered light/dark palettes with offline fixtures; never authenticate or install."""
import argparse
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright

ACCENTS = {"blue": "雾蓝", "teal": "松石青", "indigo": "靛蓝", "violet": "紫罗兰", "rose": "玫瑰", "amber": "琥珀"}
NEUTRAL = ("canvas", "surface", "surface-raised", "surface-alt", "button", "field", "sidebar-hover", "sidebar-active", "text", "muted", "border", "toggle-off", "segment-selected")
SEMANTIC = ("success", "success-soft", "danger", "danger-soft", "warning", "warning-soft")
TOKENS = NEUTRAL + SEMANTIC + ("accent", "accent-soft", "accent-hover", "on-accent", "focus-outline")


def rgb(value):
    numbers = [float(part) for part in re.findall(r"[\d.]+", value)]
    channels = numbers[:3]
    if value.startswith("color("):
        channels = [part * 255 for part in channels]
    assert len(channels) == 3 and (len(numbers) == 3 or numbers[3] == 1), value
    return channels


def contrast(first, second):
    def luminance(color):
        values = [part / 255 for part in rgb(color)]
        return sum(weight * (part / 12.92 if part <= .04045 else ((part + .055) / 1.055) ** 2.4)
                   for weight, part in zip((.2126, .7152, .0722), values))
    left, right = sorted((luminance(first), luminance(second)))
    return (right + .05) / (left + .05)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:1423/")
    parser.add_argument("--browser", default="/usr/bin/google-chrome")
    parser.add_argument("--output", type=Path, default=Path("dist/theme-palette-preview"))
    args = parser.parse_args()
    base = urlsplit(args.url)
    assert base.scheme in ("http", "https") and base.hostname in ("127.0.0.1", "localhost")
    origin = (base.scheme, base.hostname, base.port or (443 if base.scheme == "https" else 80))
    args.output.mkdir(parents=True, exist_ok=True)
    errors, external, results, baselines = [], [], [], {}
    with sync_playwright() as tool:
        browser = tool.chromium.launch(headless=True, executable_path=args.browser)
        context = browser.new_context(viewport={"width": 1280, "height": 900}, reduced_motion="reduce", service_workers="block")

        def guard(route):
            address = urlsplit(route.request.url)
            target = (address.scheme, address.hostname, address.port or (443 if address.scheme == "https" else 80))
            if target == origin:
                route.continue_()
            else:
                external.append(f"{address.scheme}://{address.hostname}:{target[2]}")
                route.abort()

        context.route("**/*", guard)
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)

        def button(name):
            return page.get_by_role("button", name=name, exact=True)

        def colors(locator):
            return locator.evaluate("el => { const s=getComputedStyle(el); return {foreground:s.color, background:s.backgroundColor, border:s.borderColor, outline:s.outlineColor, shadow:s.boxShadow}; }")

        def layout():
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth && document.querySelector('main').scrollWidth <= document.querySelector('main').clientWidth + 1")

        for theme in ("light", "dark"):
            for accent, label in ACCENTS.items():
                page.goto(args.url + f"?demo=1&scenario=online-details&theme={theme}&accent={accent}")
                page.wait_for_load_state("networkidle")
                expect(page.locator("html")).to_have_attribute("data-theme", theme)
                expect(page.locator("html")).to_have_attribute("data-accent", accent)
                tokens = page.evaluate("""names => {
                    const probe=document.createElement('span');probe.style.display='none';document.body.append(probe);
                    const result={};for(const name of names){probe.style.color=`var(--${name})`;result[name]=getComputedStyle(probe).color;}probe.remove();return result;
                }""", TOKENS)
                fixed = {name: tokens[name] for name in NEUTRAL + SEMANTIC}
                if theme not in baselines:
                    baselines[theme] = fixed
                assert fixed == baselines[theme], (theme, accent, "accent changed shared surfaces/state colors")
                expected_canvas = [245, 246, 248] if theme == "light" else [21, 22, 24]
                assert rgb(tokens["canvas"]) == expected_canvas
                for name in ("canvas", "surface", "surface-raised", "field"):
                    values = rgb(tokens[name])
                    assert max(values) - min(values) <= 8, (theme, accent, name, values)
                ratios = {}
                for foreground in ("text", "muted"):
                    for background in ("canvas", "surface", "surface-raised", "field", "button", "sidebar-active"):
                        key = f"{foreground}/{background}"
                        ratios[key] = contrast(tokens[foreground], tokens[background])
                        assert ratios[key] >= 4.5, (theme, accent, key, ratios[key])
                for background in ("canvas", "surface", "field", "accent-soft"):
                    key = f"accent/{background}"
                    ratios[key] = contrast(tokens["accent"], tokens[background])
                    assert ratios[key] >= 4.5, (theme, accent, key, ratios[key])
                for semantic in ("success", "danger", "warning"):
                    key = f"{semantic}/soft"
                    ratios[key] = contrast(tokens[semantic], tokens[semantic + "-soft"])
                    assert ratios[key] >= 4.5, (theme, accent, key, ratios[key])
                expect(page.locator(".sidebar-status")).to_have_attribute("data-state", "online")
                online = colors(page.locator(".connection-emblem"))
                assert rgb(online["foreground"]) == rgb(tokens["success"])
                page.screenshot(path=str(args.output / f"{theme}-{accent}-connection.png"))
                layout()

                button("账户").click()
                expect(page.locator(".online-detail")).to_have_count(4)
                assert rgb(colors(page.locator(".flow-card"))["background"]) == rgb(tokens["surface"])
                page.screenshot(path=str(args.output / f"{theme}-{accent}-account.png"))
                layout()
                button("设置").click()
                username = page.get_by_label("账号", exact=True)
                username.fill("fixture-theme-check")
                username.focus()
                focused = colors(username)
                ratios["focused-input"] = contrast(focused["border"], focused["background"])
                assert ratios["focused-input"] >= 3 and focused["shadow"] != "none", (theme, accent, focused)
                primary = button("保存账号")
                expect(primary).to_be_enabled()
                normal = colors(primary)
                ratios["primary"] = contrast(normal["foreground"], normal["background"])
                assert ratios["primary"] >= 4.5, (theme, accent, normal)
                primary.hover()
                hovered = colors(primary)
                ratios["primary-hover"] = contrast(hovered["foreground"], hovered["background"])
                assert ratios["primary-hover"] >= 4.5, (theme, accent, hovered)
                page.get_by_role("tab", name="外观与启动", exact=True).click()
                expect(button(label)).to_have_attribute("aria-pressed", "true")
                page.mouse.move(0, 0)
                page.screenshot(path=str(args.output / f"{theme}-{accent}-settings.png"))
                layout()

                button("连接").click()
                switch = page.get_by_role("switch", name="自动换号", exact=True)
                knob = colors(switch.locator(".toggle-knob"))
                track = colors(switch)
                ratios["off-switch-thumb"] = contrast(knob["background"], track["background"])
                assert ratios["off-switch-thumb"] >= 3, (theme, accent, knob, track)
                button("断开连接").click()
                page.get_by_role("dialog").get_by_role("button", name="断开连接", exact=True).click()
                expect(page.locator(".sidebar-status")).to_have_attribute("data-state", "offline")
                offline = colors(page.locator(".connection-emblem"))
                assert rgb(offline["foreground"]) == rgb(tokens["danger"])
                expect(switch).to_be_disabled()
                expect(switch).to_have_attribute("aria-checked", "false")
                help_control = page.get_by_label("自动换号条件", exact=True)
                help_control.focus()
                focus = colors(help_control)
                assert contrast(focus["outline"], tokens["surface"]) >= 3
                page.keyboard.press("Enter")
                expect(page.locator(".rotation-help p")).to_be_visible()
                page.keyboard.press("Enter")
                expect(page.locator(".rotation-help p")).to_be_hidden()
                results.append({"theme": theme, "accent": accent, "neutral_surfaces": True, "state_colors": True,
                                "ratios": {name: round(value, 4) for name, value in ratios.items()}})
        assert page.evaluate("localStorage.length + sessionStorage.length") == 0
        assert not errors and not external, (errors, external)
        context.close()
        browser.close()
    report = {"ok": True, "mode": "offline-rendered-palettes", "combinations": len(results), "real_authentication": False,
              "results": results, "errors": errors, "external_requests": external}
    (args.output / "theme-palette-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
