#!/usr/bin/env python3
"""Offline feedback-dock regression against an already running production preview.

Run after the parent builds the UI; this script never starts a server::

    python desktop/tests/feedback_preview.py --url http://127.0.0.1:1423/ \
        --browser /usr/bin/google-chrome --output build/feedback-20261025/after

Native requests are replaced BEFORE application code runs. No real IPC, Portal,
credentials, updates, or external browser opens are allowed. Account controls use
exactly the shipped offline demo switch flow from multi_account_preview.py, not
synthetic acknowledgements. This does not claim real-native integration coverage.
"""
import argparse
import json
import time
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from playwright.sync_api import expect, sync_playwright

from about_preview import NATIVE_FIXTURE


ERROR_TEXT = '离线夹具：查询失败，请重试。'
CONNECTION = ['main', '.connection-context', '.connection-automation', '.connection-controls']
PARAMETERS = ['main', '#settings-panel', '.parameter-actions']
STATUSES = '.feedback-dock [role="status"], .feedback-dock [role="alert"]'
CLOSE = '.feedback-dock button[aria-label="关闭提示"]'

# The only fixture extension is in this test-owned initialization script. In
# particular, no production hook, direct Svelte state write, or native fallback.
_FIXTURE_MARKER = '  window.__TAURI_EVENT_PLUGIN_INTERNALS__ ='
assert NATIVE_FIXTURE.count(_FIXTURE_MARKER) == 1, 'about fixture changed; inspect before reusing it'
_FIXTURE_EXTENSION = r"""
  const params = new URLSearchParams(location.search);
  core.prefs.theme = params.get('theme') === 'dark' ? 'dark' : 'light';
  const fx = window.__feedbackFixture = {
    next: {duration: 80, error: false}, active: 0, calls: [], completed: [],
    configure(plan) {
      if (![80, 900].includes(plan.duration)) throw new Error('invalid_fixture_duration');
      this.next = {duration: plan.duration, error: Boolean(plan.error)};
    },
    saveConfig(changes) {
      Object.assign(core.config, changes);
      window.__aboutBusy(false);
      return structuredClone(core);
    },
    seedInfo() {
      core.status = {online: true, service: '校园网', user: '', ip: '', message: ''};
      core.info = {online: true, fields: [['当前服务', '校园网']], items: [['套餐', '离线占位套餐']]};
      window.__aboutBusy(false);
    }
  };
"""
NATIVE = NATIVE_FIXTURE.replace(_FIXTURE_MARKER, _FIXTURE_EXTENSION + _FIXTURE_MARKER)
NATIVE += r"""
(() => {
  const original = window.__TAURI_INTERNALS__.invoke;
  const fx = window.__feedbackFixture;
  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
  window.__TAURI_INTERNALS__.invoke = async (command, args) => {
    const name = args?.args?.name;
    if (command === 'core_request' && args?.command === 'action' && ['status', 'info'].includes(name)) {
      const plan = {...fx.next}; fx.calls.push({command: 'action', name, ...plan});
      fx.active++; window.__aboutBusy(true);
      const finish = async () => {
        await sleep(plan.duration); window.__aboutBusy(false); fx.active--;
        fx.completed.push({command: 'action', name, error: plan.error});
      };
      // A successful queue acknowledgement is deliberately NOT completion.
      if (!plan.error) { void finish(); return {accepted: true, message: '离线夹具：已排队'}; }
      await finish(); throw new Error('离线夹具：查询失败，请重试。');
    }
    if (command === 'core_request' && args?.command === 'save_config') {
      const changes = args.args;
      const allowed = ['backend', 'base', 'cas_host', 'verify_tls', 'check_interval',
        'retry_interval', 'max_retry_interval', 'operation_timeout'];
      if (!changes || Object.keys(changes).some(key => !allowed.includes(key)))
        throw new Error('unexpected_fixture_config_write');
      const plan = {...fx.next}; fx.calls.push({command: 'save_config', ...plan}); fx.active++;
      await sleep(plan.duration); fx.active--;
      if (plan.error) throw new Error('离线夹具：保存失败，请重试。');
      // Parameter-only state changes are published through the registered
      // fixture event listener, exactly like a production snapshot.
      const snapshot = fx.saveConfig(changes);
      fx.completed.push({command: 'save_config', error: false});
      return snapshot;
    }
    // Only the minimal About fixture bootstrap is permitted. Unknown IPC fails
    // closed in that fixture; project links/updater/quit never reach the host.
    if (command === 'plugin:event|listen' || command === 'plugin:event|unlisten' ||
        command === 'get_desktop_settings' ||
        (command === 'core_request' && args?.command === 'snapshot'))
      return original(command, args);
    window.__aboutUnexpected.push(command);
    throw new Error('unexpected_feedback_fixture_ipc');
  };
})();
"""

# Every layout observation comes from a requestAnimationFrame, not a single
# before/after screenshot. The observer also catches short-lived stale notices.
SAMPLER = r"""selectors => {
  if (window.__feedbackSample?.running) throw new Error('sampler already running');
  const state = window.__feedbackSample = {running: true, selectors, frames: [], mutations: []};
  const visible = el => {
    const r = el.getBoundingClientRect(), c = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && c.visibility !== 'hidden' && c.display !== 'none' && +c.opacity > .01;
  };
  const feedback = () => [...document.querySelectorAll('.feedback-dock [role="status"], .feedback-dock [role="alert"]')]
    .filter(visible).map(el => ({role: el.getAttribute('role'), text: el.textContent.trim(),
      notice: Boolean(el.querySelector('button[aria-label="关闭提示"]'))}));
  const capture = () => {
    const boxes = {};
    for (const selector of selectors) {
      const el = document.querySelector(selector);
      if (el) {const r = el.getBoundingClientRect(); boxes[selector] = {x:r.x, y:r.y, width:r.width, height:r.height};}
    }
    state.frames.push({t:performance.now(), boxes, feedback:feedback()});
    if (state.running) state.raf = requestAnimationFrame(capture);
  };
  state.observer = new MutationObserver(() => state.mutations.push({t:performance.now(), feedback:feedback()}));
  state.observer.observe(document.querySelector('.workspace'), {subtree:true, childList:true, attributes:true, characterData:true});
  state.raf = requestAnimationFrame(capture);
}"""
STOP_SAMPLER = r"""() => {
  const s = window.__feedbackSample; s.running = false;
  cancelAnimationFrame(s.raf); s.observer.disconnect();
  return {selectors:s.selectors, frames:s.frames, mutations:s.mutations};
}"""


def origin_key(url):
    parsed = urlsplit(url)
    return parsed.scheme, parsed.hostname, parsed.port or (443 if parsed.scheme == 'https' else 80)


def visit_url(base, **query):
    parsed = urlsplit(base)
    params = dict(parse_qsl(parsed.query))
    params.update(query)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(params), ''))


class Regression:
    def __init__(self, args):
        self.args = args
        self.report = {'ok': False, 'mode': 'offline-mocked-native-and-shipped-demo',
                       'real_ipc': False, 'real_portal': False, 'real_authentication': False,
                       'checks': [], 'layouts': [], 'samples': [], 'blocked_requests': [],
                       'page_errors': [], 'console_errors': [], 'unexpected_ipc': []}
        self.contexts = []
        self.page = None

    def context(self, browser, *, native=True, reduced='reduce', width=1000, height=720):
        context = browser.new_context(viewport={'width': width, 'height': height},
                                      reduced_motion=reduced, service_workers='block')
        self.contexts.append(context)
        if native:
            context.add_init_script(NATIVE)
        else:
            # Fail closed even if the demo unexpectedly tries to use native IPC.
            context.add_init_script("window.__TAURI_INTERNALS__={invoke:()=>{throw new Error('native_ipc_forbidden_in_demo')}}")

        def guard(route):
            request = route.request
            # Static preview assets only: even same-origin fetch/XHR or POST is
            # forbidden. Never allow other loopback ports, external navigation,
            # service workers, Portal calls, or a local native IPC HTTP bridge.
            target = urlsplit(request.url)
            # Chromium reports the explicitly declared static favicon as "other".
            favicon = (request.resource_type == 'other' and target.path == '/favicon.svg'
                       and not target.query and not target.fragment)
            allowed = (origin_key(request.url) == origin_key(self.args.url)
                       and request.method == 'GET'
                       and (request.resource_type in ('document', 'stylesheet', 'script', 'font', 'image') or favicon))
            if allowed:
                route.continue_()
            else:
                target = urlsplit(request.url)
                self.report['blocked_requests'].append({'origin': f'{target.scheme}://{target.netloc}',
                                                        'type': request.resource_type, 'method': request.method})
                route.abort()

        context.route('**/*', guard)
        # WebSockets are separate from HTTP routing in Playwright.
        assert hasattr(context, 'route_web_socket'), 'Playwright >=1.48 is required for a WebSocket guard'
        context.route_web_socket('**/*', lambda ws: self.block_socket(ws))
        page = context.new_page()
        page.on('pageerror', lambda error: self.report['page_errors'].append(str(error)))
        page.on('console', lambda message: self.report['console_errors'].append(message.text)
                if message.type == 'error' else None)
        self.page = page
        return page

    def block_socket(self, socket):
        self.report['blocked_requests'].append({'type': 'websocket', 'origin': 'blocked'})
        socket.close()

    def load(self, page, *, theme='light', demo=False):
        if page.evaluate('Boolean(window.__feedbackFixture)'):
            self.report['unexpected_ipc'].extend(page.evaluate('window.__aboutUnexpected'))
        page.goto(visit_url(self.args.url, theme=theme, **({'demo': '1'} if demo else {})))
        page.wait_for_load_state('networkidle')
        expect(page.get_by_role('heading', name='连接', exact=True)).to_be_visible()
        expect(page.get_by_role('button', name='刷新状态', exact=True)).to_be_enabled()
        page.mouse.move(1, 1)

    def check(self, name):
        self.report['checks'].append(name)

    def configure(self, page, duration=80, error=False):
        page.evaluate('plan => window.__feedbackFixture.configure(plan)', {'duration': duration, 'error': error})

    def start_sample(self, page, selectors):
        for selector in selectors:
            expect(page.locator(selector)).to_have_count(1)
        page.evaluate(SAMPLER, selectors)
        page.wait_for_timeout(50)

    def stop_sample(self, page, name):
        sample = page.evaluate(STOP_SAMPLER)
        assert len(sample['frames']) >= 3, (name, 'insufficient animation frames')
        summary = {}
        for selector in sample['selectors']:
            assert all(selector in frame['boxes'] for frame in sample['frames']), (name, selector, 'disappeared')
            boxes = [frame['boxes'][selector] for frame in sample['frames']]
            delta = {axis: max(box[axis] for box in boxes) - min(box[axis] for box in boxes)
                     for axis in ('x', 'y', 'width', 'height')}
            summary[selector] = {'before': boxes[0], 'after': boxes[-1], 'max_delta': delta}
        sample['summary'] = summary
        filename = f'{name}-frames.json'
        (self.args.output / filename).write_text(json.dumps(sample, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        self.report['samples'].append({'name': name, 'file': filename, 'frames': len(sample['frames']), 'summary': summary})
        for selector, result in summary.items():
            assert max(result['max_delta'].values()) <= 1, (name, selector, result)
        return sample

    def no_notice(self, page):
        expect(page.locator(CLOSE)).to_have_count(0)
        expect(page.locator(STATUSES)).to_have_count(0)

    def layout(self, page, name):
        result = page.evaluate(r"""() => {
          const main = document.querySelector('main'), dock = document.querySelector('.feedback-dock');
          const bubbles = [...document.querySelectorAll('.feedback-dock [role="status"], .feedback-dock [role="alert"]')];
          return {document_overflow: document.documentElement.scrollWidth > innerWidth + 1,
            body_overflow: document.body.scrollWidth > innerWidth + 1,
            main_overflow: main.scrollWidth > main.clientWidth + 1,
            dock_overflow: Boolean(dock && dock.scrollWidth > dock.clientWidth + 1),
            bubble_outside_viewport: bubbles.some(el => {const b=el.getBoundingClientRect();return b.left < -1 || b.right > innerWidth+1;}),
            dock_position: dock ? getComputedStyle(dock).position : null,
            old_flow_feedback: [...document.querySelectorAll('.notice, .busy-line')].some(el => !el.closest('.feedback-dock'))};
        }""")
        self.report['layouts'].append({'name': name, **result})
        for key in ('document_overflow', 'body_overflow', 'main_overflow', 'dock_overflow',
                    'bubble_outside_viewport', 'old_flow_feedback'):
            assert not result[key], (name, key, result)
        if result['dock_position'] is not None or page.locator(STATUSES).count():
            assert result['dock_position'] in ('fixed', 'absolute'), (name, result)

    def refresh(self, page, name, *, duration, account=False, error=False, keyboard=False):
        self.configure(page, duration, error)
        selectors = ['main', '.account-summary', '.online-details'] if account else CONNECTION
        # The component root has varied historically; stable rendered cards are
        # discovered before sampling rather than creating or forcing any card.
        if account:
            selectors = ['main', '.account-summary']
            if page.locator('.online-details').count():
                selectors.append('.online-details')
        self.start_sample(page, selectors)
        started = page.evaluate('performance.now()')
        if keyboard:
            page.keyboard.press('F5')
        else:
            page.get_by_role('button', name='刷新账户' if account else '刷新状态', exact=True).click()
        if duration == 900:
            # Check before the 250ms threshold and during the long operation.
            page.wait_for_timeout(100)
            expect(page.locator(STATUSES)).to_have_count(0)
            expect(page.locator('.feedback-dock [role="status"]')).to_have_count(1, timeout=600)
            expect(page.get_by_role('button', name='刷新账户' if account else '刷新状态', exact=True)).to_be_disabled()
            expect(page.locator(CLOSE)).to_have_count(0)
            self.layout(page, name + '-busy')
            page.screenshot(path=str(self.args.output / f'{name}-busy.png'), full_page=True)
        page.wait_for_function('window.__feedbackFixture.active === 0')
        if error:
            expect(page.locator('.feedback-dock [role="alert"]')).to_contain_text(ERROR_TEXT)
        else:
            self.no_notice(page)
        page.wait_for_timeout(300)
        sample = self.stop_sample(page, name)
        observations = sample['frames'] + sample['mutations']
        feedback = [item for frame in observations for item in frame['feedback']]
        if duration == 80:
            assert not feedback, (name, 'fast operation displayed a transient bubble', feedback)
        else:
            busy_frames = [frame for frame in sample['frames'] if any(not item['notice'] for item in frame['feedback'])]
            assert busy_frames, (name, 'slow operation never showed busy feedback')
            delay = busy_frames[0]['t'] - started
            assert 200 <= delay <= 700, (name, 'loading delay must be approximately 250ms', delay)
            sample['loading_delay_ms'] = delay
            self.report['samples'][-1]['loading_delay_ms'] = delay
        assert not any(item['notice'] for item in feedback) or error, (name, 'refresh invented a success notice')
        assert all(len(frame['feedback']) <= 1 for frame in observations), (name, 'stacked stale feedback')
        self.check(name)
        return sample

    def parameters(self, page):
        page.get_by_role('button', name='设置', exact=True).click()
        page.get_by_role('tab', name='认证与重试', exact=True).click()

    def save(self, page, value, *, sample_name=None):
        self.configure(page, 80)
        interval = page.locator('.number-input input').first
        interval.fill(str(value))
        save = page.get_by_role('button', name='保存参数', exact=True)
        save.scroll_into_view_if_needed()
        if sample_name:
            self.start_sample(page, PARAMETERS)
        save.click()
        notice = page.locator('.feedback-dock [role="status"]').filter(has=page.locator('button[aria-label="关闭提示"]'))
        expect(notice).to_contain_text('参数已保存。')
        expect(page.locator(CLOSE)).to_have_count(1)
        expect(interval).to_have_value(str(value))
        page.mouse.move(1, 1)
        page.evaluate('document.activeElement.blur()')
        if sample_name:
            page.wait_for_timeout(300)
            self.stop_sample(page, sample_name)
        return notice

    def notice_lifecycle(self, page):
        self.parameters(page)
        notice = self.save(page, 16, sample_name='save-success-layout')
        self.layout(page, 'save-success')
        page.screenshot(path=str(self.args.output / 'save-success.png'), full_page=True)
        page.locator(CLOSE).click()
        self.no_notice(page)
        self.check('save-success-overlay-and-manual-close')

        notice = self.save(page, 17)
        started = time.monotonic()
        page.wait_for_timeout(4100)
        expect(notice).to_be_visible()
        expect(page.locator(CLOSE)).to_have_count(0, timeout=1500)
        elapsed = (time.monotonic() - started) * 1000
        assert 4100 <= elapsed <= 5900, ('success expiry should be 4500ms', elapsed)
        self.check('success-expires-after-4500ms')

        notice = self.save(page, 18)
        notice.hover()
        page.wait_for_timeout(4700)
        expect(notice).to_be_visible()
        page.mouse.move(1, 1)
        # Resuming uses remaining lifetime, not immediate dismissal.
        page.wait_for_timeout(200)
        expect(notice).to_be_visible()
        expect(page.locator(CLOSE)).to_have_count(0, timeout=5000)
        self.check('success-hover-pauses-and-resumes-lifetime')

        notice = self.save(page, 19)
        page.locator(CLOSE).focus()
        page.wait_for_timeout(4700)
        expect(notice).to_be_visible()
        expect(page.locator(CLOSE)).to_be_focused()
        page.keyboard.press('Enter')
        self.no_notice(page)
        self.check('success-focus-pauses-and-keyboard-close')

        # Replacing a still-live notice must invalidate its old expiry callback.
        self.save(page, 20)
        page.wait_for_timeout(3200)
        notice = self.save(page, 21)
        page.wait_for_timeout(1600)
        expect(notice).to_be_visible()
        expect(page.locator(CLOSE)).to_have_count(1)
        page.locator(CLOSE).click()
        page.wait_for_timeout(3100)
        self.no_notice(page)
        self.check('repeated-save-does-not-stack-or-expire-a-new-notice')

    def error_lifecycle(self, page):
        page.get_by_role('button', name='连接', exact=True).click()
        self.refresh(page, 'error-refresh', duration=900, error=True)
        alert = page.locator('.feedback-dock [role="alert"]')
        page.mouse.move(1, 1)
        page.evaluate('document.activeElement.blur()')
        page.wait_for_timeout(4800)
        expect(alert).to_contain_text(ERROR_TEXT)
        self.layout(page, 'persistent-error')
        page.screenshot(path=str(self.args.output / 'persistent-error.png'), full_page=True)
        page.locator(CLOSE).focus()
        page.keyboard.press('Enter')
        self.no_notice(page)
        self.check('error-persists-beyond-success-lifetime-and-keyboard-close')

    def reduced_motion(self, page):
        self.configure(page, 900)
        self.start_sample(page, CONNECTION)
        page.get_by_role('button', name='刷新状态', exact=True).click()
        expect(page.locator('.feedback-dock [role="status"]')).to_be_visible()
        motion = page.evaluate(r"""() => {
          const dock = document.querySelector('.feedback-dock');
          return {reduce:matchMedia('(prefers-reduced-motion: reduce)').matches,
            animations:dock.getAnimations({subtree:true}).filter(a => a.playState === 'running' &&
              (a.effect?.getComputedTiming().activeDuration || 0) > 1).map(a => a.animationName || 'web-animation'),
            styles:[dock,...dock.querySelectorAll('*')].map(el => {const s=getComputedStyle(el);
              return {animation:s.animationDuration,transition:s.transitionDuration};})};
        }""")
        assert motion['reduce'] and not motion['animations'], motion
        for style in motion['styles']:
            for durations in style.values():
                assert all(float(value.strip().removesuffix('ms').removesuffix('s')) <= .001
                           for value in durations.split(',')), ('reduce must be static', style)
        page.wait_for_function('window.__feedbackFixture.active === 0')
        self.no_notice(page)
        page.wait_for_timeout(100)
        self.stop_sample(page, 'reduced-motion-static')
        self.check('reduced-motion-static-feedback')

    def matrix(self, browser):
        page = self.context(browser)
        for theme in ('light', 'dark'):
            for width, height in ((1000, 720), (700, 560), (390, 844), (320, 720)):
                page.set_viewport_size({'width': width, 'height': height})
                self.load(page, theme=theme)
                name = f'{theme}-{width}'
                self.refresh(page, name, duration=900)
                self.layout(page, name + '-idle')
                self.parameters(page)
                self.save(page, 16)
                self.layout(page, name + '-success')
                page.screenshot(path=str(self.args.output / f'{name}-success.png'), full_page=True)
                page.locator(CLOSE).click()
                self.no_notice(page)
        self.check('light-dark-1000-700-390-320-no-horizontal-overflow')

    def demo_busy_controls(self, browser):
        # Reuse the canonical existing multi-account regression path and its
        # real shipped 800ms demo completion, rather than inventing native busy
        # stop semantics. No screenshots/DOM/accounts/IPs from this path are saved.
        page = self.context(browser, native=False)
        self.load(page, demo=True)
        picker = page.get_by_role('combobox', name='选择连接账号', exact=True)
        rotation = page.get_by_role('switch', name='自动换号', exact=True)
        reconnect = page.get_by_role('switch', name='自动重连', exact=True)
        rotation.click()
        picker.select_option('b' * 32)
        page.get_by_role('button', name='切换账号', exact=True).click()
        page.get_by_role('dialog').get_by_role('button', name='确认切换账号', exact=True).click()
        expect(picker).to_be_disabled()
        expect(page.get_by_role('button', name='刷新状态', exact=True)).to_be_disabled()
        expect(page.locator('.connection-action')).to_be_disabled()
        for button in page.locator('.service-selector button').all():
            expect(button).to_be_disabled()
        expect(rotation).to_be_enabled()
        expect(reconnect).to_be_enabled()
        rotation.click()
        expect(rotation).to_have_attribute('aria-checked', 'false')
        reconnect.click()
        expect(reconnect).to_have_attribute('aria-checked', 'false')
        expect(picker).to_have_value('b' * 32)
        expect(picker).to_be_enabled()
        self.check('shipped-demo-busy-locks-and-authoritative-stop-controls-preserved')

    def run(self, browser):
        page = self.context(browser)
        self.load(page)
        self.refresh(page, 'fast-status', duration=80, keyboard=True)
        self.refresh(page, 'slow-status', duration=900)
        for index in range(3):
            self.refresh(page, f'repeat-fast-{index + 1}', duration=80, keyboard=True)
        page.wait_for_timeout(350)
        self.no_notice(page)
        self.check('repeated-refresh-no-delayed-or-stacked-bubbles')
        page.evaluate('window.__feedbackFixture.seedInfo()')
        page.get_by_role('button', name='账户', exact=True).click()
        expect(page.locator('.account-summary')).to_be_visible()
        self.refresh(page, 'fast-info', duration=80, account=True, keyboard=True)
        self.refresh(page, 'slow-info', duration=900, account=True)
        self.notice_lifecycle(page)
        self.error_lifecycle(page)
        self.reduced_motion(page)
        normal = self.context(browser, reduced='no-preference')
        self.load(normal)
        self.refresh(normal, 'normal-motion-slow-status', duration=900)
        self.matrix(browser)
        self.demo_busy_controls(browser)
        for context in self.contexts:
            for item in context.pages:
                if item.evaluate('Boolean(window.__feedbackFixture)'):
                    self.report['unexpected_ipc'].extend(item.evaluate('window.__aboutUnexpected'))
        for key in ('blocked_requests', 'page_errors', 'console_errors', 'unexpected_ipc'):
            assert not self.report[key], (key, self.report[key])
        self.report['ok'] = True


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--url', default='http://127.0.0.1:1423/')
    parser.add_argument('--browser', default='/usr/bin/google-chrome')
    parser.add_argument('--output', type=Path, default=Path('build/feedback-20261025/after'))
    args = parser.parse_args()
    parsed = urlsplit(args.url)
    assert (parsed.scheme == 'http' and parsed.hostname in ('127.0.0.1', 'localhost', '::1')
            and not parsed.username and not parsed.password and not parsed.fragment), 'Only a loopback HTTP preview is allowed'
    assert not dict(parse_qsl(parsed.query)).get('demo'), '--url must be the native-fixture base URL, not a demo URL'
    args.output.mkdir(parents=True, exist_ok=True)
    suite = Regression(args)
    try:
        with sync_playwright() as tool:
            browser = tool.chromium.launch(executable_path=args.browser, headless=True,
                                          args=['--disable-background-networking', '--disable-component-update', '--disable-sync'])
            try:
                suite.run(browser)
            finally:
                browser.close()
    except Exception as error:
        suite.report['failure'] = f'{type(error).__name__}: {error}'
        raise
    finally:
        report = args.output / 'feedback-report.json'
        report.write_text(json.dumps(suite.report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(json.dumps({'ok': suite.report['ok'], 'report': str(report), 'checks': suite.report['checks']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
