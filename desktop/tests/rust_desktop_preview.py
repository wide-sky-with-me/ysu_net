"""Build-preview UI regression using isolated offline fixtures and installed Chrome."""
import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright


TABS = ("校园网账号", "外观与启动", "认证与重试", "环境诊断")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:1421/")
    parser.add_argument("--browser", default="/usr/bin/google-chrome")
    parser.add_argument("--output", type=Path, default=Path("dist/rust-desktop-preview"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    page_errors, console_errors, external_requests, layout_results = [], [], [], []
    checks = []

    with sync_playwright() as tool:
        browser = tool.chromium.launch(headless=True, executable_path=args.browser)
        context = browser.new_context(
            viewport={"width": 1060, "height": 800}, reduced_motion="reduce",
            permissions=["clipboard-read", "clipboard-write"],
        )
        page = context.new_page()
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.on("console", lambda message: console_errors.append({"text": message.text, "location": message.location})
                if message.type == "error" else None)
        page.on("request", lambda request: external_requests.append(request.url)
                if urlsplit(request.url).hostname not in (None, "127.0.0.1", "localhost") else None)

        def visit(query="?demo=1&theme=light"):
            page.goto(args.url + query)
            page.wait_for_load_state("networkidle")

        def button(name):
            return page.get_by_role("button", name=name, exact=True)

        def navigate(name):
            button(name).click()

        def tab(name):
            page.get_by_role("tab", name=name, exact=True).click()
            expect(page.get_by_role("tab", name=name, exact=True)).to_have_attribute("aria-selected", "true")

        def screenshot(name):
            page.screenshot(path=str(args.output / name))

        def layout(name):
            result = page.evaluate("""() => {
                const main = document.querySelector('main');
                const overlaps = [...document.querySelectorAll('.form-row, .setting-row')].flatMap(row => {
                    if (row.children.length < 2) return [];
                    const label = row.children[0].getBoundingClientRect();
                    const control = row.children[1].getBoundingClientRect();
                    return label.right > control.left - 4 ? [row.textContent.trim()] : [];
                });
                return {
                    viewport: [innerWidth, innerHeight],
                    document_overflow: document.documentElement.scrollWidth > innerWidth,
                    content_overflow: main.scrollWidth > main.clientWidth + 1,
                    overlaps
                };
            }""")
            result["name"] = name
            layout_results.append(result)
            assert not result["document_overflow"], result
            assert not result["content_overflow"], result
            assert not result["overlaps"], result

        visit()
        expect(page.get_by_role("heading", name="校园网已连接", exact=True)).to_be_visible()
        screenshot("connection-light.png")
        layout("connection-light")
        # Modal cancellation preserves the actual operator and returns focus to its trigger.
        navigate("中国联通")
        expect(page.get_by_role("dialog")).to_be_visible()
        expect(page.get_by_role("dialog").get_by_role("button", name="取消", exact=True)).to_be_focused()
        page.keyboard.press("Shift+Tab")
        expect(page.get_by_role("dialog").get_by_role("button", name="确认切换", exact=True)).to_be_focused()
        page.keyboard.press("Tab")
        expect(page.get_by_role("dialog").get_by_role("button", name="取消", exact=True)).to_be_focused()
        page.keyboard.press("Tab")
        assert page.evaluate("document.activeElement.closest('dialog') !== null")
        page.keyboard.press("Tab")
        assert page.evaluate("document.activeElement.closest('dialog') !== null")
        page.keyboard.press("Escape")
        expect(page.get_by_role("dialog")).not_to_be_visible()
        expect(button("中国联通")).to_be_focused()
        expect(button("中国移动")).to_have_attribute("aria-pressed", "true")
        navigate("中国联通")
        navigate("确认切换")
        expect(page.locator(".connection-details")).to_contain_text("中国联通")
        navigate("断开连接")
        expect(page.get_by_role("dialog")).to_contain_text("关闭自动重连")
        page.get_by_role("dialog").get_by_role("button", name="断开连接", exact=True).click()
        expect(page.get_by_role("heading", name="校园网未连接", exact=True)).to_be_visible()
        expect(page.get_by_role("switch", name="自动重连", exact=True)).to_have_attribute("aria-checked", "false")
        navigate("连接校园网")
        expect(page.get_by_role("heading", name="校园网已连接", exact=True)).to_be_visible()
        checks.append("operator-confirm-esc-focus-and-logout-stops-reconnect")

        navigate("账户")
        expect(page.get_by_role("heading", name="套餐与用量", exact=True)).to_be_visible()
        screenshot("account-light.png")
        layout("account-light")
        navigate("设置")
        password = page.get_by_label("密码", exact=True)
        password.fill("fixture-password")
        navigate("显示密码")
        expect(password).to_have_attribute("type", "text")
        navigate("保存账号")
        expect(password).to_have_value("")
        expect(password).to_have_attribute("type", "password")
        password.fill("discard-on-page-leave")
        navigate("连接")
        navigate("设置")
        expect(password).to_have_value("")
        password.fill("discard-on-tab-leave")
        tab("外观与启动")
        tab("校园网账号")
        expect(password).to_have_value("")
        screenshot("settings-light.png")
        layout("settings-account-light")
        # Arrow/Home/End activate tabs with a single tab stop, without losing focus.
        selected = page.get_by_role("tab", name="校园网账号", exact=True)
        selected.focus()
        page.keyboard.press("ArrowRight")
        expect(page.get_by_role("tab", name="外观与启动", exact=True)).to_be_focused()
        expect(page.get_by_role("tab", name="外观与启动", exact=True)).to_have_attribute("aria-selected", "true")
        page.keyboard.press("End")
        expect(page.get_by_role("tab", name="环境诊断", exact=True)).to_be_focused()
        page.keyboard.press("Home")
        expect(selected).to_be_focused()
        assert page.evaluate("getComputedStyle(document.activeElement).outlineStyle !== 'none'")
        assert page.locator('[role="tab"][tabindex="0"]').count() == 1
        checks.append("password-save-page-tab-clear-and-keyboard-tabs")

        tab("认证与重试")
        page.get_by_label("认证方式").select_option("browser")
        expect(page.get_by_role("dialog")).not_to_be_visible()
        expect(page.locator(".browser-section")).to_contain_text("系统浏览器可用")
        navigate("刷新浏览器状态")
        expect(page.get_by_role("dialog")).not_to_be_visible()
        expect(page.get_by_text("浏览器状态已刷新。", exact=True)).to_be_visible()
        navigate("保存参数")
        expect(page.get_by_text("参数已保存。", exact=True)).to_be_visible()
        toggle = page.get_by_role("switch", name="HTTPS 证书校验", exact=True)
        toggle.click()
        navigate("保存参数")
        expect(page.get_by_role("dialog")).to_contain_text("关闭校验")
        page.keyboard.press("Escape")
        expect(button("保存参数")).to_be_focused()
        navigate("连接")
        expect(page.locator(".connection-security-warning")).to_have_count(0)
        expect(page.locator(".connection-context")).not_to_contain_text("HTTPS 证书校验已开启")
        expect(page.locator(".connection-context")).not_to_contain_text("API 认证")
        navigate("设置")
        tab("认证与重试")
        navigate("保存参数")
        navigate("仍然关闭并保存")
        navigate("连接")
        expect(page.locator(".connection-security-warning")).to_be_visible()
        expect(page.locator(".connection-security-warning")).to_contain_text("HTTPS 证书校验已关闭")
        navigate("设置")
        tab("认证与重试")
        toggle.click()
        navigate("保存参数")
        expect(page.get_by_role("dialog")).not_to_be_visible()
        navigate("关闭提示")
        page.locator("main").evaluate("element => { element.scrollTop = 0; }")
        screenshot("settings-authentication-light.png")
        layout("settings-authentication-light")
        tab("环境诊断")
        navigate("运行本地诊断")
        expect(page.get_by_label("诊断结果")).to_contain_text("客户端版本")
        expect(page.get_by_label("诊断结果")).not_to_contain_text("fixture-password")
        assert "Python" not in page.locator("main").inner_text()
        assert "Node.js" not in page.locator("main").inner_text()
        screenshot("settings-diagnostics-light.png")
        checks.append("browser-no-download-and-certificate-confirmation-and-local-diagnostics")

        tab("外观与启动")
        screenshot("settings-desktop-light.png")
        start = page.get_by_role("switch", name="登录系统后自动启动", exact=True)
        start.click()
        expect(start).to_have_attribute("aria-checked", "true")
        tray = page.get_by_role("switch", name="关闭窗口时驻留托盘", exact=True)
        tray.click()
        expect(tray).to_have_attribute("aria-checked", "false")
        navigate("退出应用")
        expect(page.get_by_role("dialog")).to_contain_text("不会因此自动下线")
        page.keyboard.press("Escape")
        expect(button("退出应用")).to_be_focused()
        navigate("退出应用")
        page.get_by_role("dialog").get_by_role("button", name="退出应用", exact=True).click()
        navigate("连接")
        expect(page.get_by_role("heading", name="校园网已连接", exact=True)).to_be_visible()
        checks.append("autostart-tray-quit-confirmation-keeps-connection")
        visit()
        navigate("设置")
        tab("外观与启动")
        navigate("深色")
        expect(page.locator("html")).to_have_attribute("data-theme", "dark")
        screenshot("settings-dark.png")
        layout("settings-dark")
        navigate("系统")
        page.emulate_media(color_scheme="dark")
        expect(page.locator("html")).to_have_attribute("data-theme", "dark")
        page.emulate_media(color_scheme="light")
        expect(page.locator("html")).to_have_attribute("data-theme", "light")
        navigate("深色")
        navigate("日志")
        expect(page.get_by_role("log")).to_be_visible()
        screenshot("logs-dark.png")
        page.get_by_label("筛选日志级别").select_option("success")
        assert page.locator(".log-entry").count() > 0
        page.get_by_label("搜索日志").fill("no-matching-fixture")
        expect(page.get_by_text("没有匹配的日志", exact=True)).to_be_visible()
        page.get_by_label("搜索日志").fill("")
        page.get_by_label("筛选日志级别").select_option("all")
        navigate("复制筛选日志")
        expect(page.get_by_text("当前筛选日志已复制。", exact=True)).to_be_visible()
        navigate("清空视图")
        expect(page.get_by_text("当前视图暂无日志", exact=True)).to_be_visible()
        page.keyboard.press("Control+1")
        expect(page.get_by_role("heading", name="校园网已连接", exact=True)).to_be_visible()
        page.keyboard.press("Control+3")
        expect(page.get_by_role("tablist")).to_be_visible()
        checks.append("themes-system-shortcuts-and-log-filters-copy-clear")

        for scenario, heading in (("offline", "校园网未连接"), ("unknown", "连接状态未知"),
                                  ("external", "校园网已连接"), ("empty", "校园网未连接"),
                                  ("busy", "校园网已连接")):
            visit(f"?demo=1&scenario={scenario}&theme=light")
            expect(page.get_by_role("heading", name=heading, exact=True)).to_be_visible()
            if scenario in ("external", "busy"):
                expect(button("中国电信")).to_be_disabled()
                if scenario == "external":
                    expect(page.get_by_role("switch", name="自动重连", exact=True)).to_be_disabled()
                else:
                    reconnect = page.get_by_role("switch", name="自动重连", exact=True)
                    expect(reconnect).to_be_enabled()
                    reconnect.click()
                    expect(reconnect).to_have_attribute("aria-checked", "false")
                    navigate("设置")
                    tab("外观与启动")
                    expect(button("退出应用")).to_be_enabled()
                    navigate("退出应用")
                    expect(page.get_by_role("dialog")).to_be_visible()
                    page.keyboard.press("Escape")
                    expect(button("退出应用")).to_be_focused()
                    navigate("连接")
                expect(button("断开连接")).to_be_disabled()
            if scenario == "external":
                expect(page.locator(".external-note")).to_be_visible()
                expect(page.locator(".external-note")).to_contain_text("外部后台服务管理")
                expect(page.locator(".external-note")).to_contain_text("停止服务")
            if scenario == "unknown":
                expect(page.locator(".connection-details")).to_contain_text("待核心确认")
            if scenario == "empty":
                navigate("连接校园网")
                expect(page.get_by_label("密码", exact=True)).to_be_visible()
                navigate("账户")
                expect(page.get_by_role("heading", name="连接后查看账户信息", exact=True)).to_be_visible()
            screenshot(f"scenario-{scenario}.png")
            layout(f"scenario-{scenario}")
        checks.append("offline-unknown-external-empty-busy")

        page.set_viewport_size({"width": 700, "height": 560})
        visit("?demo=1&theme=dark")
        navigate("设置")
        for name in TABS:
            tab(name)
            layout("compact-" + name)
            if name == "外观与启动":
                screenshot("settings-compact.png")
            if name == "认证与重试":
                page.get_by_label("认证方式").select_option("browser")
                layout("compact-browser-authentication")
                screenshot("settings-compact-authentication.png")
                button("保存参数").scroll_into_view_if_needed()
                expect(page.get_by_role("tab", name="认证与重试", exact=True)).to_be_visible()
                assert page.evaluate("""() => {
                    const main = document.querySelector('main').getBoundingClientRect();
                    const tabs = document.querySelector('.settings-tabs').getBoundingClientRect();
                    return Math.round(tabs.top - main.top) <= 12;
                }""")
                screenshot("settings-compact-parameters.png")
                navigate("保存参数")
                expect(page.get_by_text("参数已保存。", exact=True)).to_be_visible()
        page.set_viewport_size({"width": 390, "height": 844})
        visit()
        navigate("设置")
        for name in TABS:
            tab(name)
            layout("narrow-" + name)
        screenshot("settings-narrow.png")
        checks.append("all-settings-at-700x560-and-390x844")
        page.set_viewport_size({"width": 1060, "height": 800})
        visit("")
        expect(page.get_by_role("heading", name="等待桌面核心", exact=True)).to_be_visible()
        expect(button("连接校园网")).to_be_disabled()
        screenshot("web-no-core.png")
        assert page.evaluate("localStorage.length + sessionStorage.length") == 0
        checks.append("ordinary-web-disabled-and-no-web-storage")
        browser_version = browser.version
        browser.close()

    assert not page_errors, page_errors
    assert not console_errors, console_errors
    assert not external_requests, external_requests
    result = {
        "ok": True, "browser": args.browser, "browser_version": browser_version,
        "mode": "built-web-preview-offline-demo", "real_authentication": False,
        "checks": checks, "layouts": layout_results, "page_errors": page_errors,
        "console_errors": console_errors, "external_requests": external_requests,
    }
    (args.output / "frontend-design-report.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
