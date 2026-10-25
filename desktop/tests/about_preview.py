"""About-page acceptance with offline data and explicitly mocked native IPC only."""
import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright

NATIVE_FIXTURE = r"""(() => {
  window.isTauri = true;
  const callbacks = new Map(), listeners = new Map(); let next = 1;
  window.__aboutCalls = []; window.__aboutUnexpected = []; window.__aboutFailOpen = false;
  const core = {
    sequence: 1,
    accounts: {items: [], auto_switch: false, environment_override: false, error: '', quota: {state: 'unknown', message: ''}, message: ''},
    config: {username: '', service: '校园网', backend: 'api', base: 'https://portal.invalid', cas_host: 'https://cas.invalid', verify_tls: true, check_interval: 15, retry_interval: 30, max_retry_interval: 900, operation_timeout: 180, password_set: false},
    prefs: {theme: 'light', accent: 'blue', close_to_tray: false, auto_reconnect: false},
    status: {online: false, service: null, user: '', ip: '', message: ''},
    auto: {state: 'off', message: ''}, busy: false, busy_message: '', info: null, info_error: '', logs: [],
    environment: {version: '0.2.1', rust: 'mock', runtime: 'rust', platform: 'IPC fixture', browser_available: false, browser_component_available: true}
  };
  let update = {sequence: 0, phase: 'idle', current_version: '0.2.1', release: null, downloaded: 0, total: null, error: null, releases_url: 'https://invalid.example'};
  window.__aboutBusy = value => {
    core.sequence++; core.busy = value; core.busy_message = value ? '模拟认证任务' : '';
    for (const entry of listeners.values()) if (entry.event === 'core-event') callbacks.get(entry.handler)?.({event: entry.event, id: entry.id, payload: {kind: 'event', name: 'snapshot', payload: structuredClone(core)}});
  };
  window.__TAURI_EVENT_PLUGIN_INTERNALS__ = {unregisterListener: (_event, id) => listeners.delete(id)};
  window.__TAURI_INTERNALS__ = {
    transformCallback(callback) {const id = next++; callbacks.set(id, callback); return id;},
    unregisterCallback(id) {callbacks.delete(id);},
    async invoke(command, args) {
      window.__aboutCalls.push({command, args});
      if (command === 'plugin:event|listen') {const id = next++; listeners.set(id, {...args, id}); return id;}
      if (command === 'plugin:event|unlisten') {listeners.delete(args.eventId); return;}
      if (command === 'core_request' && args.command === 'snapshot') return structuredClone(core);
      if (command === 'get_desktop_settings') return {autostart: false, tray_available: true, version: '0.2.1', demo: false};
      if (command === 'updater_status') return structuredClone(update);
      if (command === 'updater_check') {update = {...update, sequence: update.sequence + 1, phase: 'available', release: {version: '0.2.2', notes: '<img src="https://invalid.example/avatar" onerror="window.__aboutExecuted=true">'}}; return structuredClone(update);}
      if (command === 'project_open_link') {if (!['repository', 'contributors'].includes(args?.target) || Object.keys(args).length !== 1) throw 'invalid_target'; if (window.__aboutFailOpen) throw new Error('/private/browser.exe internal failure'); return;}
      if (command === 'updater_open_releases' && (args === undefined || Object.keys(args).length === 0)) return;
      window.__aboutUnexpected.push(command); throw 'unexpected_mock_command';
    }
  };
})();"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', required=True)
    parser.add_argument('--browser', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    origin = urlsplit(args.url)
    assert origin.scheme == 'http' and origin.hostname in ('127.0.0.1', 'localhost', '::1') and not origin.username and not origin.password
    args.output.mkdir(parents=True, exist_ok=True)
    errors, external, layouts = [], [], []

    with sync_playwright() as tool:
        browser = tool.chromium.launch(executable_path=args.browser, headless=True)

        def context(native=False):
            item = browser.new_context(viewport={'width': 1000, 'height': 720}, reduced_motion='reduce', service_workers='block')
            if native:
                item.add_init_script(NATIVE_FIXTURE)

            def guard(route):
                target = urlsplit(route.request.url)
                if (target.scheme, target.hostname, target.port) == (origin.scheme, origin.hostname, origin.port):
                    route.continue_()
                else:
                    external.append(f'{target.scheme}://{target.hostname}:{target.port}')
                    route.abort()

            item.route('**/*', guard)
            return item

        def watch(page):
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('console', lambda message: errors.append(message.text) if message.type == 'error' else None)

        def layout(page, name):
            result = page.evaluate('''() => {
                const main = document.querySelector('main'), nav = document.querySelector('.sidebar nav');
                return {overflow:document.documentElement.scrollWidth>innerWidth,
                    mainOverflow:main.scrollWidth>main.clientWidth+1,navOverflow:nav.scrollWidth>nav.clientWidth+1};
            }''')
            assert not any(result.values()), (name, result)
            layouts.append({'name': name, **result})

        demo = context()
        page = demo.new_page()
        watch(page)
        for theme in ('light', 'dark'):
            for width, height in ((1000, 720), (700, 560), (390, 844), (320, 720)):
                page.set_viewport_size({'width': width, 'height': height})
                page.goto(args.url + f'?demo=1&theme={theme}&accent=blue')
                page.wait_for_load_state('networkidle')
                page.get_by_role('button', name='设置', exact=True).click()
                page.get_by_role('tab', name='认证与重试', exact=True).click()
                expect(page.get_by_text('保存后下次操作生效。', exact=True)).to_have_count(0)
                expect(page.locator('.parameter-actions .muted')).to_have_count(0)
                save = page.get_by_role('button', name='保存参数', exact=True)
                right = page.locator('.parameter-actions').bounding_box()
                box = save.bounding_box()
                assert abs((box['x'] + box['width']) - (right['x'] + right['width'] - 8)) <= 2
                if width == 1000:
                    interval = page.locator('.number-input input').first
                    interval.fill('16')
                    expect(page.get_by_text('有未保存的修改', exact=True)).to_be_visible()
                    save.click()
                    expect(page.locator('.parameter-actions .muted')).to_have_count(0)
                    expect(interval).to_have_value('16')
                    expect(page.get_by_text('参数已保存。', exact=True)).to_be_visible()
                    page.get_by_role('button', name='关闭提示', exact=True).click()
                layout(page, f'parameters-{theme}-{width}')
                page.evaluate('document.activeElement.blur()')
                page.locator('main').evaluate('el => el.scrollTop = 0')
                page.screenshot(path=str(args.output / f'parameters-{theme}-{width}.png'), full_page=True)
                page.keyboard.press('Control+5')
                expect(page.get_by_role('heading', name='关于', exact=True)).to_be_visible()
                updates = page.get_by_role('region', name='软件更新', exact=True)
                expect(updates).to_contain_text('模拟模式不联网检查或安装更新。')
                expect(page.locator('.project-address').first).to_have_text('https://github.com/wide-sky-with-me/ysu_net')
                expect(page.locator('.contributor-list')).to_contain_text('wide-sky-with-me')
                expect(page.locator('.contributor-list li')).to_have_count(1)
                expect(page.locator('.about-content img')).to_have_count(0)
                expect(page.locator('.about-content a')).to_have_count(0)
                for button in ('GitHub 仓库', '完整发布日志', '查看 GitHub 贡献者'):
                    expect(page.get_by_role('button', name=button, exact=True)).to_be_disabled()
                summary = page.locator('.about-release summary').first
                expect(summary).to_have_text('YSU Net v0.2.1')
                summary.focus()
                page.keyboard.press('Enter')
                expect(page.locator('.about-release pre').first).to_be_visible()
                expect(page.locator('.about-release pre').first).to_contain_text('签名完整包更新，不是二进制差分更新')
                layout(page, f'changelog-{theme}-{width}')
                page.keyboard.press('Enter')
                expect(page.locator('.about-release pre').first).to_be_hidden()
                layout(page, f'about-{theme}-{width}')
                page.evaluate('document.activeElement.blur()')
                page.locator('main').evaluate('el => el.scrollTop = 0')
                page.screenshot(path=str(args.output / f'about-{theme}-{width}.png'), full_page=True)
                assert page.evaluate('localStorage.length + sessionStorage.length') == 0
        demo.close()

        web = context()
        page = web.new_page()
        watch(page)
        page.goto(args.url)
        page.wait_for_load_state('networkidle')
        page.get_by_role('button', name='关于', exact=True).click()
        for label, url in (('GitHub 仓库', 'https://github.com/wide-sky-with-me/ysu_net'), ('完整发布日志', 'https://github.com/wide-sky-with-me/ysu_net/releases'), ('查看 GitHub 贡献者', 'https://github.com/wide-sky-with-me/ysu_net/graphs/contributors')):
            link = page.get_by_role('link', name=label, exact=True)
            expect(link).to_have_attribute('href', url)
            expect(link).to_have_attribute('target', '_blank')
        expect(page.get_by_role('region', name='软件更新', exact=True)).to_contain_text('请在桌面客户端检查更新。')
        web.close()

        native = context(native=True)
        page = native.new_page()
        watch(page)
        page.goto(args.url)
        page.wait_for_load_state('networkidle')
        page.get_by_role('button', name='关于', exact=True).click()
        check = page.get_by_role('button', name='检查更新', exact=True)
        expect(check).to_be_enabled()
        assert page.evaluate("__aboutCalls.filter(c=>c.command==='updater_check').length") == 0
        page.screenshot(path=str(args.output / 'about-native-ipc-idle.png'), full_page=True)
        page.get_by_role('button', name='GitHub 仓库', exact=True).click()
        page.get_by_role('button', name='查看 GitHub 贡献者', exact=True).click()
        page.get_by_role('button', name='完整发布日志', exact=True).click()
        assert page.evaluate("__aboutCalls.filter(c=>c.command==='project_open_link').map(c=>c.args.target)") == ['repository', 'contributors']
        assert page.evaluate("__aboutCalls.filter(c=>c.command==='updater_open_releases').every(c=>c.args===undefined || Object.keys(c.args).length===0)")
        page.evaluate('window.__aboutFailOpen=true')
        page.get_by_role('button', name='GitHub 仓库', exact=True).click()
        expect(page.get_by_role('alert')).to_contain_text('打开项目页面失败')
        expect(page.get_by_role('alert')).not_to_contain_text('/private/')
        check.click()
        expect(page.get_by_role('region', name='软件更新', exact=True)).to_contain_text('发现新版本 0.2.2')
        expect(page.locator('.update-notes pre')).to_contain_text('<img src=')
        assert not page.evaluate('window.__aboutExecuted === true')
        expect(page.locator('.update-notes img')).to_have_count(0)
        page.get_by_role('button', name='下载并安装', exact=True).click()
        expect(page.get_by_role('dialog')).to_be_visible()
        page.keyboard.press('Escape')
        expect(page.get_by_role('dialog')).not_to_be_visible()
        page.evaluate('window.__aboutBusy(true)')
        expect(page.get_by_role('button', name='下载并安装', exact=True)).to_be_disabled()
        page.evaluate('window.__aboutBusy(false)')
        expect(page.get_by_role('button', name='下载并安装', exact=True)).to_be_enabled()
        page.get_by_role('button', name='连接', exact=True).click()
        page.get_by_role('button', name='关于', exact=True).click()
        expect(page.get_by_role('region', name='软件更新', exact=True)).to_contain_text('发现新版本 0.2.2')
        assert page.evaluate("__aboutCalls.filter(c=>c.command==='updater_check').length") == 1
        assert page.evaluate('window.__aboutUnexpected') == []
        assert page.evaluate("__aboutCalls.filter(c=>c.command==='updater_install').length") == 0
        native.close()
        browser.close()
    assert not errors and not external, (errors, external)
    report = {'ok': True, 'mode': 'offline-browser-and-mocked-native-ipc', 'real_authentication': False, 'real_update_or_browser_open': False, 'layouts': layouts, 'errors': errors, 'external_requests': external}
    (args.output / 'about-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
