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
  let update = {sequence: 0, phase: 'idle', current_version: '0.2.1', release: null, downloaded: 0, total: null, download_mode: null, fallback: false, error: null, releases_url: 'https://invalid.example'};
  const held = new Map();
  const publishUpdate = patch => {
    update = {...update, ...structuredClone(patch), sequence: update.sequence + 1};
    for (const entry of listeners.values()) if (entry.event === 'updater-event') callbacks.get(entry.handler)?.({event: entry.event, id: entry.id, payload: structuredClone(update)});
  };
  const holdRequest = command => new Promise((resolve, reject) => {
    const plan = held.get(command);
    if (plan.resolve) throw new Error('duplicate_held_update_request');
    Object.assign(plan, {resolve, reject});
  });
  window.__aboutUpdater = {
    failNextStatus: false,
    hold(command) {
      if (!['status', 'check', 'install'].includes(command) || held.has(command)) throw new Error('invalid_update_hold');
      held.set(command, {});
    },
    pending: command => Boolean(held.get(command)?.resolve),
    publish: publishUpdate,
    complete(command, patch = {}) {
      const plan = held.get(command);
      if (!plan?.resolve) throw new Error('update_request_not_pending');
      publishUpdate(patch); held.delete(command); plan.resolve(structuredClone(update));
    },
    rejectCheck(raw = false) {
      const plan = held.get('check');
      if (!plan?.reject) throw new Error('update_check_not_pending');
      publishUpdate({phase: 'error', error: raw ? 'ipc' : 'check_failed'});
      held.delete('check'); plan.reject(raw ? new Error('https://fixture.invalid/?token=private /private/fixture.exe') : 'check_failed');
    }
  };
  window.__aboutConnection = {
    observe(online, service) {
      core.status = {online, service, user: online ? 'observed-fixture' : '', ip: online ? '192.0.2.10' : '', message: ''};
      window.__aboutBusy(false);
    },
    saved: () => JSON.stringify([core.config, core.accounts, core.prefs])
  };
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
      if (command === 'updater_status') {
        if (window.__aboutUpdater.failNextStatus) {window.__aboutUpdater.failNextStatus = false; throw 'ipc';}
        return held.has('status') ? holdRequest('status') : structuredClone(update);
      }
      if (command === 'updater_check') {
        if (held.has('check')) return holdRequest('check');
        publishUpdate({phase: 'available', error: null, release: {version: '0.2.2', notes: '<img src="https://invalid.example/avatar" onerror="window.__aboutExecuted=true">'}});
        return structuredClone(update);
      }
      // Only an explicitly held simulation can acknowledge installation; no installer exists.
      if (command === 'updater_install' && args?.version === '0.2.2' && Object.keys(args).length === 1 && held.has('install')) return holdRequest('install');
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
    errors, external, layouts, update_checks = [], [], [], []

    with sync_playwright() as tool:
        browser = tool.chromium.launch(executable_path=args.browser, headless=True)

        def context(native=False, reduced='reduce'):
            item = browser.new_context(viewport={'width': 1000, 'height': 720}, reduced_motion=reduced, service_workers='block')
            if native:
                item.add_init_script(NATIVE_FIXTURE)

            def guard(route):
                request = route.request
                target = urlsplit(request.url)
                favicon = request.resource_type == 'other' and target.path == '/favicon.svg' and not target.query
                # Same-origin business fetch/XHR/POST is forbidden as well as external HTTP.
                if ((target.scheme, target.hostname, target.port) == (origin.scheme, origin.hostname, origin.port)
                        and request.method == 'GET'
                        and (request.resource_type in ('document', 'stylesheet', 'script', 'font', 'image') or favicon)):
                    route.continue_()
                else:
                    external.append(f'{target.scheme}://{target.hostname}:{target.port} {request.method} {request.resource_type}')
                    route.abort()

            def block_socket(socket):
                external.append('websocket:blocked')
                socket.close()

            item.route('**/*', guard)
            assert hasattr(item, 'route_web_socket'), 'Playwright >=1.48 is required for the WebSocket guard'
            item.route_web_socket('**/*', block_socket)
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

        def start_update_sample(page):
            page.evaluate(r'''() => {
                if (window.__aboutSample?.running) throw new Error('update_sampler_already_running');
                const ids = window.__aboutNoticeIds ||= new WeakMap();
                window.__aboutNoticeNext ||= 1;
                const identify = el => {if (!ids.has(el)) ids.set(el, window.__aboutNoticeNext++); return ids.get(el);};
                const state = window.__aboutSample = {running: true, frames: [], initialNotices: [...document.querySelectorAll('.feedback-notice')].map(identify)};
                const capture = () => {
                    const boxes = {};
                    for (const selector of ['main', '.update-section > .setting-row', '.update-check']) {
                        const el = document.querySelector(selector);
                        if (el) {const r = el.getBoundingClientRect(); boxes[selector] = {x:r.x, y:r.y, width:r.width, height:r.height};}
                    }
                    const icon = document.querySelector('.update-check svg'), css = icon && getComputedStyle(icon);
                    const notices = [...document.querySelectorAll('.feedback-notice')].map(el => ({
                        id: identify(el), text: el.querySelector('.feedback-message').textContent, role: el.getAttribute('role'),
                        opacity: +getComputedStyle(el).opacity,
                        animations: el.getAnimations().map(a => ({duration:a.effect.getTiming().duration, state:a.playState,
                            keyframes:a.effect.getKeyframes().map(k => ({opacity:k.opacity})), time:a.currentTime}))
                    }));
                    state.frames.push({t:performance.now(), boxes, notices, icon:css ? {name:css.animationName,
                        duration:css.animationDuration, iterations:css.animationIterationCount, timing:css.animationTimingFunction,
                        transform:css.transform, times:icon.getAnimations().map(a => a.currentTime)} : null});
                    if (state.running) state.raf = requestAnimationFrame(capture);
                };
                capture();
            }''')

        def finish_update_sample(page, name, *, stable=(), no_notice=False, notice=None, reduced=False, spinning=False):
            sample = page.evaluate(r'''async () => {
                for (let i=0; i<12; i++) await new Promise(requestAnimationFrame);
                const s = window.__aboutSample; s.running = false; cancelAnimationFrame(s.raf);
                return {frames:s.frames, initialNotices:s.initialNotices};
            }''')
            frames = sample['frames']
            assert len(frames) >= 12, (name, 'missing frame evidence')
            for selector in stable:
                assert all(selector in frame['boxes'] for frame in frames), (name, selector, 'disappeared')
                boxes = [frame['boxes'][selector] for frame in frames]
                for axis in ('x', 'y', 'width', 'height'):
                    assert max(box[axis] for box in boxes) - min(box[axis] for box in boxes) <= 1, (name, selector, axis, boxes)
            if no_notice:
                assert all(not frame['notices'] for frame in frames), (name, 'unexpected or premature notice', frames)
            if spinning:
                icons = [frame['icon'] for frame in frames]
                assert all(icon is not None for icon in icons), (name, 'missing spinner')
                if reduced:
                    assert all(icon['name'] == 'none' and not icon['times'] for icon in icons), (name, icons)
                else:
                    assert all(icon['name'] == 'feedback-spin' and icon['duration'] == '1s'
                               and icon['iterations'] == 'infinite' and icon['timing'] == 'linear' for icon in icons), (name, icons)
                    assert len({icon['transform'] for icon in icons}) > 1, (name, 'spinner transform did not advance')
                    times = [icon['times'][0] for icon in icons if icon['times'] and isinstance(icon['times'][0], (int, float))]
                    assert len(times) >= 2 and max(times) > min(times), (name, 'spinner timeline did not advance', times)
            if notice is not None:
                arrivals = [item for frame in frames for item in frame['notices']
                            if item['text'] == notice and item['id'] not in sample['initialNotices']]
                assert arrivals, (name, 'no newly mounted completion notice', frames)
                animations = [animation for item in arrivals for animation in item['animations']]
                if reduced:
                    assert all(animation['duration'] == 0 or animation['state'] == 'finished' for animation in animations), (name, animations)
                    assert all(item['opacity'] == 1 for item in arrivals), (name, 'reduced-motion fade', arrivals)
                else:
                    assert any(animation['duration'] == 120 and len({key.get('opacity') for key in animation['keyframes']}) > 1
                               for animation in animations), (name, 'missing existing dock fade animation', arrivals)
            update_checks.append({'name': name, 'reduced_motion': reduced, **sample})
            return sample

        def check_motion(page, active, *, reduced=False):
            button = page.locator('.update-check')
            expect(button).to_have_count(1)
            expect(button).to_have_attribute('aria-busy', str(active).lower())
            if active:
                expect(button).to_be_disabled()
                expect(button).to_have_text('正在检查')
            expect(button.locator('svg')).to_have_css('animation-name', 'feedback-spin' if active and not reduced else 'none')

        def no_update_notice(page):
            expect(page.locator('.feedback-dock .feedback-notice')).to_have_count(0)

        def dismiss_update_notice(page):
            page.locator('.feedback-dock button[aria-label="关闭提示"]').click()
            no_update_notice(page)

        carrier = context(native=True)
        page = carrier.new_page()
        watch(page)
        page.goto(args.url)
        page.wait_for_load_state('networkidle')
        controls = page.get_by_role('group', name='选择运营商', exact=True)
        saved = page.evaluate('window.__aboutConnection.saved()')
        for service in ('校园网', '中国移动', '中国联通', '中国电信'):
            page.evaluate('service => window.__aboutConnection.observe(true, service)', service)
            expect(page.get_by_role('heading', name=service + '已连接', exact=True)).to_be_visible()
            expect(controls.get_by_role('button', name=service, exact=True)).to_have_attribute('aria-pressed', 'true')
            expect(controls.locator('[aria-pressed="true"]')).to_have_count(1)
            expect(page.locator('.connection-details div').first.locator('dd')).to_have_text(service)
            assert page.evaluate('window.__aboutConnection.saved()') == saved
        page.evaluate("window.__aboutConnection.observe(true, '中国联通')")
        controls.get_by_role('button', name='中国联通', exact=True).click()
        expect(page.get_by_role('dialog')).not_to_be_visible()
        controls.get_by_role('button', name='校园网', exact=True).click()
        expect(page.get_by_role('dialog')).to_contain_text('将从中国联通下线')
        page.keyboard.press('Escape')
        expect(controls.get_by_role('button', name='中国联通', exact=True)).to_have_attribute('aria-pressed', 'true')
        for online, service, title in ((False, '中国联通', '校园网未连接'), (None, '中国移动', '连接状态未知'), (True, None, '校园网已连接'), (True, '未识别服务', '校园网已连接')):
            page.evaluate('args => window.__aboutConnection.observe(...args)', [online, service])
            expect(page.get_by_role('heading', name=title, exact=True)).to_be_visible()
            expect(controls.get_by_role('button', name='校园网', exact=True)).to_have_attribute('aria-pressed', 'true')
            assert page.evaluate('window.__aboutConnection.saved()') == saved
        assert page.evaluate("__aboutCalls.filter(c=>c.command==='core_request'&&c.args.command!=='snapshot')") == []
        assert page.evaluate('window.__aboutUnexpected') == []
        page.evaluate("window.__aboutConnection.observe(true, '中国联通')")
        expect(controls.get_by_role('button', name='中国联通', exact=True)).to_have_attribute('aria-pressed', 'true')
        page.screenshot(path=str(args.output / 'carrier-observation-sync.png'), full_page=True)
        update_checks.append({'name': 'online-carrier-title-and-selection-readonly-sync', 'ok': True, 'saved_account_and_prefs_unchanged': True, 'native_mutations': 0})
        carrier.close()

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

        for reduced in (False, True):
            native = context(native=True, reduced='reduce' if reduced else 'no-preference')
            page = native.new_page()
            watch(page)
            page.goto(args.url)
            page.wait_for_load_state('networkidle')
            page.get_by_role('button', name='关于', exact=True).click()
            check = page.locator('.update-check')
            expect(check).to_have_text('检查更新')
            expect(check).to_be_enabled()
            check_motion(page, False, reduced=reduced)
            no_update_notice(page)
            suffix = 'reduced' if reduced else 'motion'
            fixture = 'window.__aboutUpdater'
            notice = page.locator('.feedback-dock .feedback-notice')

            # Pending IPC is visible immediately, even before the first native event.
            page.evaluate(f"{fixture}.hold('check')")
            check.click()
            page.wait_for_function(f"{fixture}.pending('check')")
            check_motion(page, True, reduced=reduced)
            expect(page.get_by_role('region', name='软件更新', exact=True)).not_to_contain_text('当前已是最新版本')
            start_update_sample(page)
            finish_update_sample(page, f'check-pending-before-event-{suffix}', stable=('.update-check', '.update-section > .setting-row'),
                                 no_notice=True, spinning=True, reduced=reduced)
            page.evaluate(f"{fixture}.publish({{phase:'checking'}})")
            check_motion(page, True, reduced=reduced)
            # A terminal event alone is not the explicit promise's completion.
            page.evaluate(f"{fixture}.publish({{phase:'up_to_date',release:null,error:null}})")
            start_update_sample(page)
            finish_update_sample(page, f'no-premature-completion-{suffix}', no_notice=True, spinning=True, reduced=reduced)
            start_update_sample(page)
            page.evaluate(f"{fixture}.complete('check')")
            expect(notice).to_have_attribute('role', 'status')
            expect(notice.locator('.feedback-message')).to_have_text('当前已是最新版本')
            check_motion(page, False, reduced=reduced)
            expect(check).to_be_enabled()
            finish_update_sample(page, f'up-to-date-completion-{suffix}', stable=('main',), notice='当前已是最新版本', reduced=reduced)

            # Repeating the same completion must produce a new dock fade, not reuse
            # an already-present DOM node whose message happened to be unchanged.
            page.evaluate(f"{fixture}.hold('check')")
            start_update_sample(page)
            check.click()
            page.wait_for_function(f"{fixture}.pending('check')")
            # Complete before waiting for the prior toast's outro to disappear;
            # the new notice identity must restart its own fade.
            page.evaluate(f"{fixture}.complete('check',{{phase:'up_to_date',release:null,error:null}})")
            expect(notice.locator('.feedback-message')).to_have_text(['当前已是最新版本'])
            check_motion(page, False, reduced=reduced)
            finish_update_sample(page, f'repeated-completion-{suffix}', stable=('main',), notice='当前已是最新版本', reduced=reduced)
            dismiss_update_notice(page)

            # The explicit promise may outlive its About component. Completion is
            # still App-global, and a later passive remount must not replay it.
            page.evaluate(f"{fixture}.hold('check')")
            check.click()
            page.wait_for_function(f"{fixture}.pending('check')")
            page.evaluate(f"{fixture}.publish({{phase:'checking',release:null,error:null}})")
            page.get_by_role('button', name='连接', exact=True).click()
            expect(page.get_by_role('heading', name='连接', exact=True)).to_be_visible()
            expect(page.locator('.update-check')).to_have_count(0)
            no_update_notice(page)
            # Let the existing page-entry reveal settle before geometry sampling.
            page.evaluate('''async () => {await Promise.all(document.querySelector('main').getAnimations({subtree:true}).map(a => a.finished.catch(() => {})));}''')
            start_update_sample(page)
            page.evaluate(f"{fixture}.complete('check',{{phase:'available',error:null,release:{{version:'0.2.2',notes:'<img src=\"https://invalid.example/fixture\" onerror=\"window.__aboutExecuted=true\">'}}}})")
            expect(notice).to_have_attribute('role', 'status')
            expect(notice.locator('.feedback-message')).to_have_text('发现新版本 0.2.2')
            assert notice.evaluate("el => !el.closest('main')"), 'completion notice must remain App-global'
            finish_update_sample(page, f'detached-available-completion-{suffix}', stable=('main',), notice='发现新版本 0.2.2', reduced=reduced)
            dismiss_update_notice(page)
            calls = page.evaluate("__aboutCalls.filter(c=>c.command==='updater_check').length")
            start_update_sample(page)
            page.get_by_role('button', name='关于', exact=True).click()
            expect(check).to_be_enabled()
            expect(page.locator('.update-notes pre')).to_contain_text('<img src=')
            finish_update_sample(page, f'no-completion-replay-on-remount-{suffix}', no_notice=True, reduced=reduced)
            assert page.evaluate("__aboutCalls.filter(c=>c.command==='updater_check').length") == calls
            expect(page.locator('.update-notes img')).to_have_count(0)
            assert not page.evaluate('window.__aboutExecuted === true')

            # Native checking remains authoritative on a passive remount, without
            # inventing a new explicit check or completion toast.
            page.evaluate(f"{fixture}.publish({{phase:'checking',release:null,error:null}})")
            check_motion(page, True, reduced=reduced)
            page.get_by_role('button', name='连接', exact=True).click()
            page.get_by_role('button', name='关于', exact=True).click()
            check_motion(page, True, reduced=reduced)
            start_update_sample(page)
            finish_update_sample(page, f'native-checking-after-remount-{suffix}', no_notice=True, spinning=True, reduced=reduced,
                                 stable=('.update-check', '.update-section > .setting-row'))
            assert page.evaluate("__aboutCalls.filter(c=>c.command==='updater_check').length") == calls
            for phase in ('up_to_date', 'available', 'error'):
                page.evaluate(f"phase => {fixture}.publish({{phase,error:phase==='error'?'check_failed':null,release:phase==='available'?{{version:'0.2.2',notes:''}}:null}})", phase)
                check_motion(page, False, reduced=reduced)
                start_update_sample(page)
                finish_update_sample(page, f'passive-{phase}-no-notice-{suffix}', no_notice=True, reduced=reduced)

            # Check rejection uses fixed messages in the global dock, never raw
            # rejected URLs, tokens, paths or a stale successful-check notice.
            for raw, message in ((False, '检查更新失败，请检查网络后重试。'), (True, '读取更新状态失败，请重新打开设置后重试。')):
                page.evaluate(f"{fixture}.hold('check')")
                check.click()
                page.wait_for_function(f"{fixture}.pending('check')")
                check_motion(page, True, reduced=reduced)
                no_update_notice(page)
                start_update_sample(page)
                page.evaluate(f"raw => {fixture}.rejectCheck(raw)", raw)
                expect(notice).to_have_attribute('role', 'alert')
                expect(notice.locator('.feedback-message')).to_have_text(message)
                check_motion(page, False, reduced=reduced)
                expect(check).to_be_enabled()
                for private in ('fixture.invalid', 'token=private', '/private/', '当前已是最新版本'):
                    expect(page.locator('body')).not_to_contain_text(private)
                finish_update_sample(page, f'check-error-{raw}-{suffix}', stable=('main',), notice=message, reduced=reduced)
                dismiss_update_notice(page)

            page.evaluate(f"{fixture}.hold('check')")
            check.click()
            page.wait_for_function(f"{fixture}.pending('check')")
            start_update_sample(page)
            page.evaluate(f"{fixture}.complete('check',{{phase:'error',error:'feed_not_ready',release:null}})")
            expect(notice).to_have_attribute('role', 'alert')
            expect(notice.locator('.feedback-message')).to_have_text('更新源尚未就绪，请稍后重试或前往发布页。')
            check_motion(page, False, reduced=reduced)
            finish_update_sample(page, f'terminal-error-is-not-success-{suffix}', stable=('main',),
                                 notice='更新源尚未就绪，请稍后重试或前往发布页。', reduced=reduced)
            dismiss_update_notice(page)

            # A failed passive status read can be retried, but pending status is
            # not an update check and must not borrow its spinner or notice.
            page.evaluate(f"{fixture}.publish({{phase:'idle',release:null,error:null}}); {fixture}.failNextStatus=true")
            page.get_by_role('button', name='连接', exact=True).click()
            page.get_by_role('button', name='关于', exact=True).click()
            expect(check).to_have_text('重新读取状态')
            expect(page.locator('.update-error')).to_contain_text('读取更新状态失败')
            page.evaluate(f"{fixture}.hold('status')")
            check.click()
            page.wait_for_function(f"{fixture}.pending('status')")
            check_motion(page, False, reduced=reduced)
            expect(check).to_be_disabled()
            start_update_sample(page)
            finish_update_sample(page, f'status-pending-no-check-feedback-{suffix}', no_notice=True, reduced=reduced)
            page.evaluate(f"{fixture}.complete('status',{{phase:'available',release:{{version:'0.2.2',notes:''}},error:null}})")
            expect(check).to_have_text('检查更新')
            expect(check).to_be_enabled()
            no_update_notice(page)
            assert page.evaluate("__aboutCalls.filter(c=>c.command==='updater_check').length") == calls + 3

            # Explicitly simulated install IPC stays held; no installer or network
            # is reachable, and every install/download phase has a static icon.
            page.evaluate(f"{fixture}.hold('install')")
            page.get_by_role('button', name='下载并安装', exact=True).click()
            page.get_by_role('button', name='确认下载并安装', exact=True).click()
            page.wait_for_function(f"{fixture}.pending('install')")
            check_motion(page, False, reduced=reduced)
            expect(check).to_be_disabled()
            for phase in ('downloading', 'verifying', 'reconstructing', 'quiescing', 'installing'):
                page.evaluate(f"phase => {fixture}.publish({{phase,download_mode:'delta',downloaded:256,total:1024}})", phase)
                check_motion(page, False, reduced=reduced)
                expect(check).to_be_disabled()
                no_update_notice(page)
            start_update_sample(page)
            page.evaluate(f"{fixture}.complete('install',{{phase:'error',error:'download_failed'}})")
            expect(check).to_be_enabled()
            check_motion(page, False, reduced=reduced)
            finish_update_sample(page, f'install-completion-is-not-check-feedback-{suffix}', no_notice=True, reduced=reduced)
            assert page.evaluate("__aboutCalls.filter(c=>c.command==='updater_install').map(c=>c.args)") == [{'version': '0.2.2'}]
            assert page.evaluate('window.__aboutUnexpected') == []
            assert page.evaluate('localStorage.length + sessionStorage.length') == 0
            page.screenshot(path=str(args.output / f'about-update-feedback-{suffix}.png'), full_page=True)
            native.close()
        browser.close()
    assert not errors and not external, (errors, external)
    report = {'ok': True, 'mode': 'offline-browser-and-mocked-native-ipc', 'real_ipc': False, 'real_business_http_or_websocket': False, 'real_authentication': False, 'real_update_or_browser_open': False, 'layouts': layouts, 'update_checks': update_checks, 'errors': errors, 'external_requests': external}
    (args.output / 'about-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
