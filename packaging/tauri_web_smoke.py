"""Offline browser acceptance. Start Vite with the webapp-testing server helper."""
import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright, expect


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:1420/")
    parser.add_argument("--browser", help="installed Chrome/Chromium executable")
    parser.add_argument("--output", type=Path, default=Path("dist/tauri-preview"))
    args = parser.parse_args()
    base = urlsplit(args.url)
    if base.scheme not in ("http", "https") or base.hostname not in ("127.0.0.1", "localhost"):
        parser.error("acceptance requires a loopback preview URL")
    origin = (base.scheme, base.hostname, base.port or (443 if base.scheme == "https" else 80))
    args.output.mkdir(parents=True, exist_ok=True)
    errors, external, console_errors = [], [], []
    with sync_playwright() as tool:
        browser = tool.chromium.launch(headless=True, **({"executable_path": args.browser} if args.browser else {}))
        context = browser.new_context(viewport={"width": 1060, "height": 800}, reduced_motion="reduce",
                                      permissions=["clipboard-read", "clipboard-write"], service_workers="block")

        def guard_request(route):
            request = route.request
            url = urlsplit(request.url)
            target = (url.scheme, url.hostname, url.port or (443 if url.scheme == "https" else 80))
            if target == origin:
                route.continue_()
            else:
                # Fail closed before a broken Demo can reach a portal/feed/other local service.
                external.append({"origin": f"{url.scheme}://{url.hostname}:{target[2]}",
                                 "type": request.resource_type})
                route.abort()

        context.route("**/*", guard_request)
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)

        def visit(query):
            page.goto(args.url + query)
            page.wait_for_load_state("networkidle")

        def navigate(name):
            page.get_by_role("button", name=name, exact=True).click()

        def shot(name):
            page.screenshot(path=str(args.output / name), full_page=True)

        visit("?demo=1&theme=light")
        expect(page.get_by_role("heading", name="校园网已连接", exact=True)).to_be_visible()
        # Validate the Demo contract through its log and blocked updater, not an obsolete banner.
        navigate("日志")
        expect(page.get_by_role("log")).to_contain_text("所有数据和操作均为演示")
        navigate("连接")
        shot("connection-light.png")
        navigate("中国联通")
        expect(page.get_by_role("dialog")).to_be_visible()
        navigate("取消")
        expect(page.get_by_role("button", name="中国移动", exact=True)).to_have_attribute("aria-pressed", "true")
        navigate("中国联通")
        navigate("确认切换")
        expect(page.locator(".connection-details")).to_contain_text("中国联通")
        navigate("断开连接")
        expect(page.get_by_role("dialog")).to_be_visible()
        page.get_by_role("dialog").get_by_role("button", name="断开连接", exact=True).click()
        expect(page.get_by_role("heading", name="校园网未连接", exact=True)).to_be_visible()
        expect(page.get_by_role("switch", name="自动重连", exact=True)).to_have_attribute("aria-checked", "false")
        navigate("连接校园网")
        expect(page.get_by_role("heading", name="校园网已连接", exact=True)).to_be_visible()
        navigate("账户")
        expect(page.get_by_role("heading", name="套餐与用量", exact=True)).to_be_visible()
        shot("account-light.png")
        navigate("设置")
        page.get_by_label("密码", exact=True).fill("fake-e2e-password")
        navigate("保存账号")
        expect(page.get_by_label("密码", exact=True)).to_have_value("")
        page.get_by_label("密码", exact=True).fill("discard-on-leave")
        navigate("连接")
        navigate("设置")
        expect(page.get_by_label("密码", exact=True)).to_have_value("")
        page.get_by_label("密码", exact=True).fill("discard-on-settings-tab")
        page.get_by_role("tab", name="认证与重试", exact=True).click()
        page.get_by_role("tab", name="校园网账号", exact=True).click()
        expect(page.get_by_label("密码", exact=True)).to_have_value("")
        page.get_by_role("tab", name="认证与重试", exact=True).click()
        page.get_by_label("认证方式").select_option("browser")
        expect(page.get_by_role("dialog")).not_to_be_visible()
        expect(page.locator(".browser-section")).to_contain_text("系统浏览器可用")
        expect(page.get_by_role("button", name="下载认证组件", exact=True)).to_have_count(0)
        navigate("保存参数")
        navigate("刷新浏览器状态")
        expect(page.get_by_role("dialog")).not_to_be_visible()
        expect(page.locator(".browser-section")).to_contain_text("系统浏览器可用")
        expect(page.locator(".browser-status p")).to_have_count(0)
        page.get_by_role("tab", name="环境诊断", exact=True).click()
        navigate("运行本地诊断")
        expect(page.locator(".diagnostic-result summary")).to_be_focused()
        expect(page.get_by_label("诊断结果")).to_be_hidden()
        page.locator(".diagnostic-result summary").click()
        expect(page.get_by_label("诊断结果")).to_be_visible()
        expect(page.get_by_label("诊断结果")).to_contain_text("客户端版本")
        expect(page.get_by_label("诊断结果")).to_contain_text("Rust 原生")
        expect(page.get_by_label("诊断结果")).not_to_contain_text("Python")
        expect(page.get_by_label("诊断结果")).not_to_contain_text("Node.js")
        expect(page.get_by_label("诊断结果")).not_to_contain_text("fake-e2e-password")
        page.get_by_role("tab", name="外观与启动", exact=True).click()
        updates = page.get_by_role("region", name="软件更新", exact=True)
        expect(updates).to_contain_text("模拟模式不联网检查或安装更新。")
        expect(updates.get_by_role("button")).to_have_count(0)
        expect(updates.get_by_role("link")).to_have_count(0)
        autostart = page.get_by_role("switch", name="登录系统后自动启动", exact=True)
        expect(autostart).to_have_attribute("aria-checked", "false")
        autostart.click()
        expect(autostart).to_have_attribute("aria-checked", "true")
        navigate("深色")
        expect(page.locator("html")).to_have_attribute("data-theme", "dark")
        shot("settings-dark.png")
        navigate("连接")
        shot("connection-dark.png")
        navigate("日志")
        expect(page.get_by_role("log")).to_be_visible()
        shot("logs-dark.png")
        navigate("复制筛选日志")
        expect(page.get_by_text("当前筛选日志已复制。", exact=True)).to_be_visible()
        navigate("清空视图")
        expect(page.get_by_text("当前视图暂无日志", exact=True)).to_be_visible()
        assert page.evaluate("localStorage.length + sessionStorage.length") == 0
        visit("?demo=1&theme=light")
        navigate("设置")
        page.get_by_role("tab", name="外观与启动", exact=True).click()
        expect(page.get_by_role("switch", name="登录系统后自动启动", exact=True)).to_have_attribute("aria-checked", "false")
        expect(page.get_by_role("region", name="软件更新", exact=True)).to_contain_text("模拟模式不联网检查或安装更新。")

        for scenario, heading in (("offline", "校园网未连接"), ("unknown", "连接状态未知"),
                                  ("external", "校园网已连接"), ("empty", "校园网未连接"),
                                  ("busy", "校园网已连接")):
            visit(f"?demo=1&scenario={scenario}&theme=light")
            expect(page.get_by_role("heading", name=heading, exact=True)).to_be_visible()
            if scenario in ("external", "busy"):
                expect(page.get_by_role("button", name="中国电信", exact=True)).to_be_disabled()
                if scenario == "external":
                    expect(page.get_by_role("switch", name="自动重连", exact=True)).to_be_disabled()
                else:
                    reconnect = page.get_by_role("switch", name="自动重连", exact=True)
                    expect(reconnect).to_be_enabled()
                    reconnect.click()
                    expect(reconnect).to_have_attribute("aria-checked", "false")
            if scenario == "empty":
                navigate("账户")
                expect(page.get_by_role("heading", name="连接后查看账户信息", exact=True)).to_be_visible()
            shot(f"scenario-{scenario}.png")
        page.set_viewport_size({"width": 700, "height": 560})
        visit("?demo=1&theme=dark")
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        shot("compact-dark.png")
        page.set_viewport_size({"width": 1060, "height": 800})
        visit("")
        expect(page.get_by_role("heading", name="等待桌面核心", exact=True)).to_be_visible()
        expect(page.get_by_text("普通网页", exact=True)).to_be_visible()
        expect(page.get_by_role("button", name="连接校园网", exact=True)).to_be_disabled()
        navigate("设置")
        expect(page.get_by_role("button", name="保存账号", exact=True)).to_be_disabled()
        page.get_by_role("tab", name="外观与启动", exact=True).click()
        expect(page.get_by_role("switch", name="登录系统后自动启动", exact=True)).to_be_disabled()
        expect(page.get_by_role("switch", name="关闭窗口时驻留托盘", exact=True)).to_be_disabled()
        expect(page.get_by_role("button", name="退出应用", exact=True)).to_be_disabled()
        assert page.evaluate("localStorage.length + sessionStorage.length") == 0
        shot("web-no-core.png")
        browser.close()
    assert not errors, errors
    assert not console_errors, console_errors
    assert not external, external
    result = {"ok": True, "mode": "browser-demo", "real_network": False,
              "dialogs": True, "actions": True, "password_cleared": True, "no_web_storage": True,
              "themes": True, "scenarios": True, "compact": True, "web_not_native": True,
              "native_runtime_contract": True, "no_auth_runtime_download": True,
              "demo_log_contract": True, "demo_state_reset": True, "demo_updates_blocked": True,
              "external_requests_blocked": True,
              "external_requests": external, "page_errors": errors, "console_errors": console_errors}
    (args.output / "browser-report.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
