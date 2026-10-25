"""Offline multi-account acceptance using real, locally installed Chrome."""
import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright


A, B, C = "a" * 32, "b" * 32, "c" * 32


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:1421/")
    parser.add_argument("--browser", default="/usr/bin/google-chrome")
    parser.add_argument("--output", type=Path, default=Path("/tmp/ysu-multi-account-preview"))
    args = parser.parse_args()
    assert urlsplit(args.url).hostname in ("127.0.0.1", "localhost")
    args.output.mkdir(parents=True, exist_ok=True)
    checks, layouts, errors, console_errors, external = [], [], [], [], []

    with sync_playwright() as tool:
        browser = tool.chromium.launch(headless=True, executable_path=args.browser)
        context = browser.new_context(viewport={"width": 1060, "height": 800}, reduced_motion="reduce")
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)

        def route(request_route):
            if urlsplit(request_route.request.url).hostname not in (None, "127.0.0.1", "localhost"):
                external.append(request_route.request.url)
                request_route.abort()
            else:
                request_route.continue_()

        context.route("**/*", route)

        def button(name):
            return page.get_by_role("button", name=name, exact=True)

        def visit(scenario="", extra="", theme="light"):
            page.goto(args.url + f"?demo=1&theme={theme}&scenario={scenario}" + extra)
            page.wait_for_load_state("networkidle")
            expect(page.get_by_role("heading", name="连接", exact=True)).to_be_visible()

        def settings():
            button("设置").click()
            page.get_by_role("tab", name="校园网账号", exact=True).click()

        def row(account_id):
            return page.locator(f'.account-list > li[data-account-id="{account_id}"]')

        def editor():
            return page.locator(".account-editor")

        def layout(name):
            result = page.evaluate("""() => {
                const main = document.querySelector('main');
                const overlaps = [...document.querySelectorAll('.account-editor .form-row')].flatMap(row => {
                    const label = row.children[0].getBoundingClientRect();
                    const control = row.children[1].getBoundingClientRect();
                    return label.right > control.left - 4 ? [row.textContent.trim()] : [];
                });
                return { viewport: [innerWidth, innerHeight],
                    document_overflow: document.documentElement.scrollWidth > innerWidth,
                    content_overflow: main.scrollWidth > main.clientWidth + 1, overlaps };
            }""")
            result["name"] = name
            layouts.append(result)
            assert not result["document_overflow"] and not result["content_overflow"] and not result["overlaps"], result

        visit()
        # Inspect the rendered fixture before using controls; no page or request reaches real auth.
        (args.output / "initial-dom.html").write_text(page.content(), encoding="utf-8")
        page.screenshot(path=str(args.output / "connection-light.png"), full_page=True)
        selector = page.get_by_role("combobox", name="选择连接账号", exact=True)
        expect(selector).to_have_value(A)
        expect(selector.locator("option")).to_have_count(3)
        expect(selector.locator(f'option[value="{C}"]')).to_be_disabled()
        rotation = page.get_by_role("switch", name="自动换号", exact=True)
        reconnect = page.get_by_role("switch", name="自动重连", exact=True)
        expect(rotation).to_have_attribute("aria-checked", "false")
        expect(rotation).to_be_enabled()
        expect(page.locator('.quota-status')).to_have_count(0)
        # The switch action only exists once a different account is chosen.
        expect(button("切换账号")).to_have_count(0)
        selector.focus()
        page.keyboard.press("ArrowDown")
        page.keyboard.press("Enter")
        expect(selector).to_have_value(B)
        button("切换账号").click()
        expect(page.get_by_role("dialog")).to_contain_text("fixture-student-b")
        expect(page.get_by_role("dialog").get_by_role("button", name="取消", exact=True)).to_be_focused()
        page.keyboard.press("Shift+Tab")
        expect(page.get_by_role("dialog").get_by_role("button", name="确认切换账号", exact=True)).to_be_focused()
        page.keyboard.press("Tab")
        page.keyboard.press("Escape")
        expect(button("切换账号")).to_be_focused()
        expect(page.locator(".connection-details")).to_contain_text("20260001")
        checks.append("account-selection-keyboard-confirm-escape-focus")

        rotation.click()
        expect(rotation).to_have_attribute("aria-checked", "true")
        button("切换账号").click()
        page.get_by_role("dialog").get_by_role("button", name="确认切换账号", exact=True).click()
        expect(page.locator(".feedback-dock .feedback-busy")).to_contain_text("正在切换账号")
        expect(page.locator(".connection-details")).to_contain_text("20260001")
        expect(page.locator(".account-choice")).not_to_contain_text("已确认切换到")
        expect(rotation).to_be_enabled()
        rotation.click()
        expect(rotation).to_have_attribute("aria-checked", "false")
        expect(reconnect).to_be_enabled()
        reconnect.click()
        expect(reconnect).to_have_attribute("aria-checked", "false")
        expect(page.locator(".connection-details")).to_contain_text("fixture-student-b")
        expect(selector).to_have_value(B)
        expect(page.locator(".account-choice")).to_contain_text("已确认切换到备用账号")
        expect(button("切换账号")).to_have_count(0)
        expect(selector).to_be_focused()
        expect(page.locator('.quota-status')).to_have_count(0)
        expect(page.locator('.account-choice')).not_to_contain_text('自动换号已关闭')
        checks.append("queued-ack-not-success-and-authoritative-hot-switch-with-busy-stop-controls")

        settings()
        expect(row(B).get_by_role("button", name="删除备用账号", exact=True)).to_be_disabled()
        expect(row(A).get_by_role("button", name="删除常用账号", exact=True)).to_be_enabled()
        button("新增账号").click()
        expect(editor().get_by_label("名称", exact=True)).to_be_focused()
        editor().get_by_label("名称", exact=True).fill("离线新账号")
        editor().get_by_label("用户名", exact=True).fill("fixture-created")
        editor().get_by_label("账号密码", exact=True).fill("fixture-created-password")
        editor().get_by_label("运营商", exact=True).select_option("中国电信")
        button("保存到账号簿").click()
        expect(editor()).to_have_count(0)
        created = page.locator(".account-list > li").filter(has_text="fixture-created")
        expect(created).not_to_contain_text("待设置密码")
        button("编辑离线新账号").click()
        expect(editor().get_by_label("用户名", exact=True)).to_have_attribute("readonly", "")
        expect(editor().get_by_label("账号密码", exact=True)).to_have_value("")
        editor().get_by_label("名称", exact=True).fill("离线已编辑")
        button("保存到账号簿").click()
        expect(created).to_contain_text("离线已编辑")
        expect(created).not_to_contain_text("待设置密码")
        button("删除离线已编辑").click()
        expect(page.get_by_role("dialog")).to_contain_text("fixture-created")
        page.keyboard.press("Escape")
        expect(button("删除离线已编辑")).to_be_focused()
        button("删除离线已编辑").click()
        page.get_by_role("dialog").get_by_role("button", name="删除账号", exact=True).click()
        expect(created).to_have_count(0)
        checks.append("create-edit-fixed-username-empty-password-preserved-delete-confirm-current-protected")

        for leave in ("close", "escape", "page", "tab"):
            button("编辑常用账号").click()
            editor().get_by_label("账号密码", exact=True).fill(f"discard-{leave}")
            if leave == "close":
                button("关闭账号编辑").click()
            elif leave == "escape":
                page.keyboard.press("Escape")
            elif leave == "page":
                button("连接").click()
                settings()
            else:
                page.get_by_role("tab", name="外观与启动", exact=True).click()
                page.get_by_role("tab", name="校园网账号", exact=True).click()
            expect(editor()).to_have_count(0)
            button("编辑常用账号").click()
            expect(editor().get_by_label("账号密码", exact=True)).to_have_value("")
            button("取消编辑").click()
        button("新增账号").click()
        editor().get_by_label("账号密码", exact=True).fill("discard-validation")
        button("保存到账号簿").click()
        expect(editor().get_by_role("alert")).to_contain_text("请输入校园网账号")
        expect(editor().get_by_label("账号密码", exact=True)).to_have_value("")
        button("取消编辑").click()
        checks.append("password-cleared-on-save-validation-close-escape-page-and-tab")

        visit()
        settings()
        button("编辑备用账号").click()
        page.get_by_role("switch", name="启用此账号", exact=True).click()
        button("保存到账号簿").click()
        button("连接").click()
        expect(rotation).to_be_disabled()
        condition = page.get_by_label('自动换号条件', exact=True)
        explanation = page.locator('.rotation-help p')
        expect(explanation).to_be_hidden()
        condition.focus()
        page.keyboard.press('Enter')
        expect(explanation).to_be_visible()
        expect(explanation).to_contain_text('至少需要两个')
        page.keyboard.press('Enter')
        expect(explanation).to_be_hidden()
        settings()
        button("编辑备用账号").click()
        page.get_by_role("switch", name="启用此账号", exact=True).click()
        button("保存到账号簿").click()
        button("连接").click()
        expect(rotation).to_be_enabled()
        reconnect.click()
        expect(rotation).to_be_disabled()
        reconnect.click()
        rotation.click()
        expect(rotation).to_have_attribute("aria-checked", "true")
        reconnect.click()
        expect(rotation).to_have_attribute("aria-checked", "false")
        checks.append("two-enabled-accounts-and-auto-reconnect-required-reconnect-off-stops-rotation")

        for scenario in ("external", "environment", "accounts-error"):
            visit(scenario)
            expect(selector).to_be_disabled()
            expect(rotation).to_be_disabled()
            expect(button("切换账号")).to_have_count(0)
        visit('quota-unknown', '&rotation=1')
        expect(page.locator(".quota-status")).to_have_attribute("data-state", "unknown")
        expect(page.locator(".quota-status")).to_contain_text("额度未知")
        expect(page.locator(".quota-status")).not_to_contain_text("耗尽")
        checks.append("external-environment-book-error-locks-and-unknown-quota-preserved")

        visit("switch-failure")
        selector.select_option(B)
        button("切换账号").click()
        page.get_by_role("dialog").get_by_role("button", name="确认切换账号", exact=True).click()
        expect(page.locator(".account-choice")).to_contain_text("登录失败")
        expect(page.locator(".connection-details")).to_contain_text("20260001")
        expect(page.locator(".account-choice")).not_to_contain_text("已确认切换到")
        visit("save-failure")
        settings()
        button("新增账号").click()
        editor().get_by_label("用户名", exact=True).fill("fixture-save-failure")
        editor().get_by_label("账号密码", exact=True).fill("discard-save-failure")
        button("保存到账号簿").click()
        expect(page.get_by_role("alert")).to_contain_text("保存失败")
        expect(editor().get_by_label("账号密码", exact=True)).to_have_value("")
        expect(editor()).to_be_visible()
        button("取消编辑").click()
        expect(button("新增账号")).to_be_focused()
        expect(page.locator(".account-list")).not_to_contain_text("fixture-save-failure")
        visit("rotation-failure")
        rotation.click()
        expect(page.get_by_role("alert")).to_contain_text("保存失败")
        expect(rotation).to_have_attribute("aria-checked", "false")
        checks.append("switch-save-rotation-failures-retain-state-and-clear-secret")

        visit("busy", "&rotation=1")
        expect(rotation).to_be_enabled()
        rotation.click()
        expect(rotation).to_have_attribute("aria-checked", "false")
        expect(rotation).to_be_disabled()
        reconnect.click()
        expect(reconnect).to_have_attribute("aria-checked", "false")
        settings()
        page.get_by_role("tab", name="外观与启动", exact=True).click()
        expect(button("退出应用")).to_be_enabled()
        button("退出应用").click()
        page.get_by_role("dialog").get_by_role("button", name="退出应用", exact=True).click()
        expect(page.get_by_role("dialog")).not_to_be_visible()
        checks.append("busy-rotation-reconnect-stop-and-quit-remain-operable")

        for width, height in ((700, 560), (390, 844), (320, 720)):
            page.set_viewport_size({"width": width, "height": height})
            visit()
            layout(f"connection-{width}")
            settings()
            layout(f"list-{width}")
            button("编辑备用账号").click()
            layout(f"editor-{width}")
            page.evaluate("window.scrollTo(0, 0)")
            page.screenshot(path=str(args.output / f"editor-{width}.png"), full_page=True)
            button("关闭账号编辑").click()
        page.set_viewport_size({"width": 1060, "height": 800})
        visit(theme="dark")
        expect(page.locator("html")).to_have_attribute("data-theme", "dark")
        settings()
        button("编辑备用账号").click()
        editor().scroll_into_view_if_needed()
        page.screenshot(path=str(args.output / "editor-dark.png"), full_page=True)
        layout("editor-dark")
        assert page.evaluate("localStorage.length + sessionStorage.length") == 0
        assert "fixture-created-password" not in page.content()
        checks.append("small-screen-320-390-700-dark-theme-no-overflow-and-no-web-storage")
        version = browser.version
        browser.close()

    assert not errors, errors
    assert not console_errors, console_errors
    assert not external, external
    result = {"ok": True, "browser": args.browser, "browser_version": version,
              "mode": "offline-built-preview", "real_authentication": False,
              "checks": checks, "layouts": layouts, "page_errors": errors,
              "console_errors": console_errors, "external_requests": external}
    (args.output / "multi-account-report.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
