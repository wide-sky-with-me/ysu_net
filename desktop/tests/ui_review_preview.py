"""Regressions for the page-by-page design review, using built UI and offline fixtures."""
import argparse
import copy
import json
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:1423/")
    parser.add_argument("--output", type=Path, default=Path("dist/ui-review-validation/after"))
    parser.add_argument("--fixture", type=Path, help="Optional frozen offline snapshot JSON")
    args = parser.parse_args()
    assert urlsplit(args.url).hostname in ("localhost", "127.0.0.1")
    args.output.mkdir(parents=True, exist_ok=True)
    if args.fixture:
        snapshot = json.loads(args.fixture.read_text())
    else:
        root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory(prefix="ysu-review-fixture-") as directory:
            script = r"""
                const fs = require('node:fs');
                const { pathToFileURL } = require('node:url');
                const ts = require('./desktop/node_modules/typescript');
                const output = process.argv[1];
                for (const name of ['accents', 'protocol', 'demo']) {
                    const code = ts.transpileModule(fs.readFileSync(`desktop/src/lib/${name}.ts`, 'utf8'), {
                        compilerOptions: {target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022}
                    }).outputText.replaceAll("'./protocol'", "'./protocol.mjs'").replaceAll("'./accents'", "'./accents.mjs'");
                    fs.writeFileSync(`${output}/${name}.mjs`, code);
                }
                import(pathToFileURL(`${output}/demo.mjs`).href).then(module => console.log(JSON.stringify(module.demoSnapshot())));
            """
            snapshot = json.loads(subprocess.check_output(["node", "-e", script, directory], cwd=root, text=True))
    results = []

    with sync_playwright() as tool:
        browser = tool.chromium.launch(headless=True, executable_path="/usr/bin/google-chrome")

        def button(page, name):
            return page.get_by_role("button", name=name, exact=True)

        def settings(page, tab):
            button(page, "设置").click()
            page.get_by_role("tab", name=tab, exact=True).click()

        def visible_in_viewport(node):
            expect(node).to_be_visible()
            assert node.evaluate("el => { const r=el.getBoundingClientRect(); const m=document.querySelector('main').getBoundingClientRect(); return r.top>=0 && r.bottom<=innerHeight && (innerWidth<=520 || (r.top>=m.top && r.bottom<=m.bottom)); }"), node.bounding_box()

        def test(name, callback, width=1000, height=720, scenario="", fixture=None, desktop=None):
            context = browser.new_context(viewport={"width": width, "height": height}, reduced_motion="reduce", color_scheme="light")
            errors, external = [], []
            def route(request):
                if urlsplit(request.request.url).hostname not in (None, "localhost", "127.0.0.1"):
                    external.append(request.request.url)
                    request.abort()
                else:
                    request.continue_()
            context.route("**/*", route)
            if fixture is not None:
                data = json.dumps({"snapshot": fixture, "desktop": desktop}, ensure_ascii=False)
                context.add_init_script("""(() => {
                    const data = DATA;
                    window.isTauri = true;
                    window.__reviewCalls = [];
                    window.__TAURI_EVENT_PLUGIN_INTERNALS__ = {unregisterListener() {}};
                    window.__TAURI_INTERNALS__ = {
                        transformCallback() { return 1; }, unregisterCallback() {},
                        invoke: async (command, args = {}) => {
                            window.__reviewCalls.push(command);
                            if (command === 'plugin:event|listen') return 1;
                            if (command === 'plugin:event|unlisten') return null;
                            if (command === 'get_desktop_settings') {
                                if (data.desktop === 'read-error') throw new Error('读取系统自启设置失败');
                                return data.desktop || {autostart:false, tray_available:true, version:'offline-fixture'};
                            }
                            if (command === 'core_request' && args.command === 'snapshot') return structuredClone(data.snapshot);
                            if (command === 'core_request' && args.command === 'diagnostics') return {environment:data.snapshot.environment};
                            throw new Error('Unexpected fixture command: ' + command);
                        }
                    };
                })();""".replace("DATA", data, 1))
            page = context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            result = {"name": name, "viewport": [width, height], "ok": False}
            try:
                page.goto(args.url + f"?demo=1&theme=light&scenario={scenario}")
                page.wait_for_load_state("networkidle")
                expect(button(page, "连接")).to_be_visible()
                page.evaluate("document.fonts.ready.then(() => true)")
                measurements = callback(page)
                assert not errors, errors
                assert not external, external
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), "Document overflow"
                result.update(ok=True, measurements=measurements)
            except Exception as error:
                result["error"] = str(error)
            finally:
                page.screenshot(path=str(args.output / f"{name}.png"), full_page=False)
                result.update(page_errors=errors, external_requests=external)
                results.append(result)
                context.close()

        def breakpoint(page):
            values = []
            for width in (961, 960):
                page.set_viewport_size({"width": width, "height": 720})
                values.append(page.locator(".connection-controls").bounding_box())
            assert abs(values[0]["height"] - values[1]["height"]) < 32, values
            return values
        test("connection-breakpoint", breakpoint)
        test("unknown-ip", lambda p: expect(p.locator(".connection-details .numeric")).to_have_text("待核心确认"), scenario="unknown")
        test("quota-copy", lambda p: expect(p.locator(".quota-state")).not_to_contain_text("门户已提供额度"))

        def external_reason(page):
            assert page.locator(".external-note").bounding_box()["y"] < page.locator(".connection-controls").bounding_box()["y"]
            settings(page, "校园网账号")
            expect(page.locator(".account-book")).to_contain_text("外部")
            expect(button(page, "新增账号")).to_be_disabled()
        test("external-local-reason", external_reason, scenario="external")

        def account_density(page):
            button(page, "账户").click()
            cards = page.locator(".account-summary dl > div").all()
            assert len({round(card.bounding_box()["y"]) for card in cards}) == 1
            assert float(page.locator(".account-summary dd").first.evaluate("el => getComputedStyle(el).fontSize").removesuffix("px")) <= 18
            expect(page.locator(".portal-note")).to_have_count(0)
            visible_in_viewport(page.locator(".account-fields dl > div").last)
        test("account-density", account_density)
        missing = copy.deepcopy(snapshot)
        missing["info"]["items"] = [["我的运营商", "中国移动"], ["在线设备", "1"]]
        missing["info"]["fields"].extend([["设备类型", "有线设备"], ["认证方式", "API"]])
        def missing_values(page):
            button(page, "账户").click()
            expect(page.locator(".account-summary dd.missing")).to_have_count(2)
            expect(page.locator(".account-summary dd.missing").first).to_have_css("font-size", "13px")
            expect(page.locator(".portal-note")).to_contain_text("不代表")
            expect(page.locator(".account-summary dt")).not_to_contain_text(["套餐与余额"])
        test("missing-values-small", missing_values, width=390, fixture=missing)
        raw = copy.deepcopy(snapshot)
        raw["info"]["items"] = [["已用流量", "2048"], ["余额", "0"]]
        def raw_values(page):
            button(page, "账户").click()
            entries = page.locator(".account-summary dl > div")
            expect(entries.filter(has=page.locator("dt", has_text="已用流量")).locator("dd")).to_have_text("2048")
            expect(entries.filter(has=page.locator("dt", has_text="余额")).locator("dd")).to_have_text("0")
        test("portal-original-values", raw_values, fixture=raw)

        def account_settings_density(page):
            settings(page, "校园网账号")
            visible_in_viewport(page.locator(".account-list > li").last)
            button(page, "编辑备用账号").click()
            visible_in_viewport(button(page, "保存到账号簿"))
        test("account-settings-density", account_settings_density)
        def new_password_copy(page):
            settings(page, "校园网账号")
            button(page, "新增账号").click()
            editor = page.locator(".account-editor")
            editor.get_by_label("用户名", exact=True).fill("fixture-password-required")
            button(page, "保存到账号簿").click()
            expect(editor.get_by_role("alert")).to_contain_text("须填写密码")
            expect(editor).not_to_contain_text("空密码保留原密码")
        test("new-password-copy", new_password_copy)
        def save_failure(page):
            settings(page, "校园网账号")
            button(page, "新增账号").click()
            editor = page.locator(".account-editor")
            editor.get_by_label("用户名", exact=True).fill("fixture-save-error")
            editor.get_by_label("账号密码", exact=True).fill("fixture-discarded-password")
            button(page, "保存到账号簿").click()
            expect(page.get_by_role("alert")).to_contain_text("保存失败")
            visible_in_viewport(page.get_by_role("alert"))
            expect(editor.get_by_label("账号密码", exact=True)).to_have_value("")
        def delete_failure(page):
            settings(page, "校园网账号")
            button(page, "删除备用账号").click()
            page.get_by_role("dialog").get_by_role("button", name="删除账号", exact=True).click()
            expect(page.get_by_role("alert")).to_contain_text("删除失败")
            visible_in_viewport(page.get_by_role("alert"))
            expect(page.locator(".account-list")).to_contain_text("备用账号")
        for width in (390, 320):
            test(f"save-error-{width}", save_failure, width=width, scenario="save-failure")
            test(f"delete-error-{width}", delete_failure, width=width, scenario="delete-failure")

        test("appearance-density", lambda p: (settings(p, "外观与启动"), visible_in_viewport(button(p, "退出应用"))), width=700, height=560)
        def unknown_desktop(page):
            settings(page, "外观与启动")
            expect(page.locator("#settings-panel")).to_contain_text("托盘状态待确认")
            expect(page.locator("#settings-panel")).not_to_contain_text("未提供系统托盘")
        test("desktop-read-error", unknown_desktop, fixture=snapshot, desktop="read-error")
        def native_demo(page):
            settings(page, "外观与启动")
            expect(page.get_by_role("switch", name="登录系统后自动启动", exact=True)).to_be_disabled()
            expect(page.locator("#settings-panel")).to_contain_text("模拟不修改系统自启")
        test("native-demo-autostart", native_demo, fixture=snapshot, desktop={"autostart": False, "tray_available": True, "demo": True, "version": "fixture"})

        def auth_density(page):
            settings(page, "认证与重试")
            visible_in_viewport(button(page, "保存参数"))
            page.get_by_label("认证方式", exact=True).select_option("browser")
            visible_in_viewport(button(page, "保存参数"))
        test("authentication-density", auth_density)
        def auth_states(page):
            settings(page, "认证与重试")
            page.get_by_label("认证方式", exact=True).select_option("browser")
            page.get_by_label("认证方式", exact=True).select_option("api")
            expect(page.locator(".parameter-actions")).not_to_contain_text("有未保存的修改")
            page.get_by_role("switch", name="HTTPS 证书校验", exact=True).click()
            expect(page.locator(".certificate-warning")).to_contain_text("保存")
            button(page, "保存参数").click()
            button(page, "仍然关闭并保存").click()
            expect(page.locator(".certificate-warning")).not_to_contain_text("需再次确认")
            expect(page.locator(".certificate-warning")).to_contain_text("不验证")
        test("authentication-state-copy", auth_states)

        def diagnostics(page):
            button(page, "环境诊断").click()
            expect(page.get_by_role("status").filter(has_text="诊断已完成")).to_be_visible()
            expect(page.locator(".diagnostic-result summary")).to_be_focused()
            visible_in_viewport(page.locator(".diagnostic-result summary"))
            page.locator(".diagnostic-result summary").click()
            expect(page.locator(".diagnostic-output")).to_contain_text("Rust")
        test("diagnostic-feedback", diagnostics, width=700, height=560)

        def logs(page):
            button(page, "日志").click()
            assert page.locator(".log-toolbar").bounding_box()["height"] < 85
            button(page, "清空视图").focus()
            page.keyboard.press("Tab")
            expect(page.locator(".log-list")).to_be_focused()
            expect(page.locator(".log-list")).to_have_css("outline-offset", "-3px")
        test("log-toolbar-and-focus", logs, width=700, height=560)
        def forced_selection(page):
            page.emulate_media(forced_colors="active")
            expect(page.locator('.service-selector [aria-pressed="true"]')).to_have_css("forced-color-adjust", "none")
            settings(page, "外观与启动")
            expect(page.locator('.theme-selector [aria-pressed="true"]')).to_have_css("forced-color-adjust", "none")
        test("forced-color-selection", forced_selection)
        def long_title(page):
            settings(page, "校园网账号")
            button(page, "编辑备用账号").click()
            page.locator(".account-editor").get_by_label("名称", exact=True).fill("Backup_account_" + "x" * 65)
            button(page, "保存到账号簿").click()
            button(page, "连接").click()
            page.get_by_role("combobox", name="选择连接账号", exact=True).select_option("b" * 32)
            button(page, "切换账号").click()
            dialog = page.get_by_role("dialog")
            assert dialog.evaluate("el => el.scrollWidth <= el.clientWidth"), dialog.bounding_box()
            expect(dialog.get_by_role("button", name="取消", exact=True)).to_be_focused()
            page.keyboard.press("Escape")
            expect(button(page, "切换账号")).to_be_focused()
        test("long-confirmation-title", long_title, width=320, height=640)
        def compact_connection(page):
            for selector in ('.connection-state > button', '.account-choice-controls', '.service-selector', '.connection-automation'):
                visible_in_viewport(page.locator(selector))
            for node in page.get_by_role('switch').all():
                visible_in_viewport(node)
            assert page.locator('.connection-context .connection-details').count() == 1
            assert page.locator('.connection-context .connection-footer').count() == 1
            assert page.locator('main').evaluate('el => el.scrollHeight <= el.clientHeight + 1')
            return page.locator('.connection-automation').bounding_box()
        for scenario in ('', 'offline', 'unknown'):
            test('compact-native-' + (scenario or 'online'), compact_connection, width=700, height=560, scenario=scenario)
        def manage_entry(page):
            button(page, '账户').click()
            button(page, '管理账号').click()
            expect(page.locator('input[name="username"]')).to_be_visible()
            expect(page.get_by_role('tab', name='校园网账号')).to_have_attribute('aria-selected', 'true')
        test('account-management-entry', manage_entry, width=700, height=560, scenario='offline')
        crowded = copy.deepcopy(snapshot)
        crowded['accounts']['items'] = crowded['accounts']['items'][:2]
        for index in range(30):
            entry = copy.deepcopy(snapshot['accounts']['items'][-1])
            entry.update(id=f'{index:032x}', username=f'fixture-{index}', label=f'备用 {index}', current=False)
            crowded['accounts']['items'].append(entry)
        def long_book_editor(page):
            settings(page, '校园网账号')
            row = page.locator('.account-list > li').last
            edit = row.get_by_role('button', name='编辑备用 29', exact=True)
            edit.click()
            expect(page.locator('.account-list')).to_have_count(0)
            expect(page.locator('#saved-account-label')).to_be_focused()
            visible_in_viewport(page.locator('#saved-account-label'))
            page.locator('[name="saved-account-password"]').fill('offline-test-only')
            page.keyboard.press('Escape')
            expect(page.locator('.account-editor')).to_have_count(0)
            expect(page.get_by_role('button', name='编辑备用 29', exact=True)).to_be_focused()
            page.get_by_role('button', name='编辑备用 29', exact=True).click()
            expect(page.locator('[name="saved-account-password"]')).to_have_value('')
            page.keyboard.press('Escape')
            button(page, '新增账号').click()
            button(page, '取消编辑').click()
            expect(button(page, '新增账号')).to_be_focused()
        test('long-book-task-editor', long_book_editor, width=700, height=560, fixture=crowded)

        def concise_copy(page):
            settings(page, '外观与启动')
            tray = page.locator('.setting-row').filter(has=page.get_by_role('switch', name='关闭窗口时驻留托盘', exact=True))
            expect(tray.locator('p')).to_have_count(0)
            expect(page.locator('.quit-row p')).to_have_count(0)
            page.screenshot(path=str(args.output / f"concise-appearance-{page.viewport_size['width']}.png"), full_page=True)
            button(page, '退出应用').click()
            expect(page.get_by_role('dialog')).to_contain_text('自动重连将停止')
            expect(page.get_by_role('dialog')).to_contain_text('不会因此自动下线')
            page.keyboard.press('Escape')
            settings(page, '校园网账号')
            expect(page.locator('.current-account-form .form-actions .muted')).to_have_count(0)
            button(page, '编辑备用账号').click()
            expect(page.locator('.account-editor .form-actions .muted')).to_have_count(0)
            expect(page.locator('#fixed-username-note')).to_be_visible()
            page.locator('[name="saved-account-password"]').fill('copy-fixture-password')
            button(page, '取消编辑').click()
            button(page, '编辑备用账号').click()
            expect(page.locator('[name="saved-account-password"]')).to_have_value('')
            button(page, '取消编辑').click()
            settings(page, '认证与重试')
            page.get_by_label('认证方式', exact=True).select_option('browser')
            expect(page.locator('.browser-status strong')).to_have_text('系统浏览器可用')
            expect(page.locator('.browser-status p')).to_have_count(0)
            page.get_by_label('认证方式', exact=True).select_option('api')
            settings(page, '环境诊断')
            expect(page.locator('.diagnostics-section .form-actions .muted')).to_have_count(0)
            button(page, '运行本地诊断').click()
            expect(page.locator('.diagnostic-result summary')).to_be_focused()
            button(page, '日志').click()
            expect(button(page, '清空视图')).to_have_attribute('title', '仅清空当前视图，保留核心日志')
            assert page.locator('.log-note').evaluate(r'el => /^\d+ 条记录$/.test(el.textContent)')
            button(page, '清空视图').click()
            expect(page.locator('.log-note')).to_have_text('0 条记录')
        for width in (1000, 320):
            test(f'concise-copy-{width}', concise_copy, width=width)

        def missing_browser_help(page):
            settings(page, '认证与重试')
            page.get_by_label('认证方式', exact=True).select_option('browser')
            expect(page.locator('.browser-status strong')).to_have_text('未发现系统浏览器')
            expect(page.locator('.browser-status p')).to_have_text('请在本机安装 Edge 或 Chrome，再刷新状态。')
        missing_browser = copy.deepcopy(snapshot)
        missing_browser['environment']['browser_available'] = False
        test('missing-browser-help', missing_browser_help, fixture=missing_browser)

        def missing_component_help(page):
            settings(page, '认证与重试')
            page.get_by_label('认证方式', exact=True).select_option('browser')
            expect(page.locator('.browser-status strong')).to_have_text('当前安装未包含浏览器认证')
            expect(page.locator('.browser-status p')).to_have_text('请使用 API 认证。')
        missing_component = copy.deepcopy(snapshot)
        missing_component['environment']['browser_component_available'] = False
        test('missing-browser-component-help', missing_component_help, fixture=missing_component)

        def missing_tray_help(page):
            settings(page, '外观与启动')
            expect(page.get_by_role('switch', name='关闭窗口时驻留托盘', exact=True)).to_be_disabled()
            expect(page.locator('#settings-panel')).to_contain_text('当前环境未提供系统托盘，关闭窗口将退出应用。')
        test('missing-tray-help', missing_tray_help, fixture=snapshot, desktop={'autostart': False, 'tray_available': False, 'version': 'copy-fixture'})
        browser.close()

    report = {"ok": all(item["ok"] for item in results), "mode": "offline-built-preview", "real_authentication": False, "checks": results}
    (args.output / "review-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n")
    failures = [item for item in results if not item["ok"]]
    for item in failures:
        print(item["name"], item["error"])
    print(f"Review checks: {len(results) - len(failures)}/{len(results)} passed")
    raise SystemExit(bool(failures))


if __name__ == "__main__":
    main()
