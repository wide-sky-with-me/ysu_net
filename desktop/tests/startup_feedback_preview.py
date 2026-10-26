#!/usr/bin/env python3
"""Synthetic startup/settings feedback regression for an existing production preview.

    python desktop/tests/startup_feedback_preview.py --url http://127.0.0.1:1423/ \
        --browser /usr/bin/google-chrome --output build/startup-feedback-preview

This script does NOT build, start a server, install dependencies, invoke real
native IPC, or modify OS startup settings. Native mode is the existing
about_preview.NATIVE_FIXTURE plus test-owned overrides installed before app code.
Plain demo mode exercises the shipped in-memory transport, not a replacement.
Only same-origin production documents/static assets may reach HTTP; all other
HTTP and all WebSockets fail closed. No production test hooks/module imports.

Reports contain synthetic fixture state, DOM geometry and actual browser
animation timelines/styles. They do not establish real-native/OS integration,
platform tray behavior, or persistence across application restarts. Run only
when explicitly authorized; static AST/node syntax checks do not run this suite.
"""
import argparse
import json
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from playwright.sync_api import expect, sync_playwright

from about_preview import NATIVE_FIXTURE


AUTOSTART = '登录系统后自动启动'
STARTUP = '自启后进入托盘'
TRAY = '关闭窗口时驻留托盘'
NOTICE = '.feedback-dock .feedback-notice'
BUSY = '.feedback-dock .feedback-busy'
CLOSE = '.feedback-dock button[aria-label="关闭提示"]'
SUCCESS = {
    'autostart': {True: '登录自启已开启', False: '登录自启已关闭'},
    'startup': {True: '自启后将进入托盘', False: '自启后将显示窗口'},
    'tray': {True: '关闭窗口后保留托盘', False: '关闭窗口后退出应用'},
    'theme': {'light': '界面主题已保存', 'dark': '界面主题已保存'},
    'accent': {'blue': '主题色已保存', 'rose': '主题色已保存'},
}
LABELS = {'autostart': AUTOSTART, 'startup': STARTUP, 'tray': TRAY}
OPTIONS = {'theme': {'light': '浅色', 'dark': '深色'}, 'accent': {'blue': '雾蓝', 'rose': '玫瑰'}}
SELECTORS = {key: f'[role="switch"][aria-label="{label}"]' for key, label in LABELS.items()}
OPTION_SELECTORS = {'theme': {'light': '.theme-selector button:nth-child(2)', 'dark': '.theme-selector button:nth-child(3)'},
                    'accent': {'blue': '.accent-selector button:nth-child(1)', 'rose': '.accent-selector button:nth-child(5)'}}
STABLE = ['main', '#settings-panel', '.theme-selector', '.accent-selector'] + list(SELECTORS.values())
RAW_MARKERS = ('/private/startup-fixture', 'fixture-private-token', 'token=', 'startup-fixture.invalid')

# Inject inside the existing fixture only to access its synthetic core. The
# second script overrides the fixture's fake invoke, never a host implementation.
_MARKER = '  window.__TAURI_EVENT_PLUGIN_INTERNALS__ ='
assert NATIVE_FIXTURE.count(_MARKER) == 1, 'Inspect changed About fixture before reusing it'
EXTENSION = r"""
  const fixtureParams = new URLSearchParams(location.search);
  core.prefs.theme = fixtureParams.get('theme') === 'dark' ? 'dark' : 'light';
  core.prefs.accent = 'blue';
  if (fixtureParams.get('fixture_legacy') !== '1') core.prefs.autostart_minimized = true;
  const settings = {autostart: false, tray_available: fixtureParams.get('fixture_tray') !== '0',
    version: '0.2.1', demo: fixtureParams.get('fixture_demo') === '1'};
  const plans = new Map();
  const fx = window.__startupFixture = {
    calls: [], completed: [], settings,
    snapshot: () => structuredClone(core),
    saved: () => structuredClone({prefs: core.prefs, settings}),
    hold(operation, afterMs = null) {
      if (!['autostart', 'settings', 'startup', 'tray', 'theme', 'accent'].includes(operation) ||
          plans.has(operation) || ![null, 80].includes(afterMs)) throw new Error('invalid_startup_fixture_hold');
      plans.set(operation, {afterMs});
    },
    pending: operation => Boolean(plans.get(operation)?.resolve),
    discard(operation) {
      if (plans.get(operation)?.resolve) throw new Error('cannot_discard_pending_fixture_operation');
      plans.delete(operation);
    },
    request(operation, payload) {
      const plan = plans.get(operation);
      if (!plan || plan.resolve) throw new Error('startup_operation_not_explicitly_held');
      fx.calls.push({operation, payload: structuredClone(payload), t: performance.now()});
      return new Promise((resolve, reject) => {
        Object.assign(plan, {payload: structuredClone(payload), resolve, reject, started: performance.now()});
        if (plan.afterMs !== null) plan.timer = setTimeout(() => fx.finish(operation), plan.afterMs);
      });
    },
    finish(operation, outcome = 'saved', actual = null) {
      const plan = plans.get(operation);
      if (!plan?.resolve || !['saved', 'ack', 'raw', 'error'].includes(outcome))
        throw new Error('startup_fixture_not_pending');
      clearTimeout(plan.timer); plans.delete(operation);
      fx.completed.push({operation, outcome, t: performance.now(), started: plan.started});
      if (outcome === 'raw' || outcome === 'error') {
        plan.reject(outcome === 'raw'
          ? new Error('/private/startup-fixture/prefs.json https://startup-fixture.invalid/?token=fixture-private-token')
          : new Error('fixture_settings_failure'));
        return;
      }
      if (operation === 'settings') {
        if (actual !== null) {
          if (typeof actual !== 'boolean') throw new Error('invalid_fixture_actual_autostart');
          settings.autostart = actual;
        }
        plan.resolve(structuredClone(settings)); return;
      }
      if (outcome === 'saved') {
        if (operation === 'autostart') settings.autostart = plan.payload.enabled;
        else if (operation === 'startup') core.prefs.autostart_minimized = plan.payload.minimized;
        else Object.assign(core.prefs, plan.payload);
        core.sequence++;
      }
      if (operation === 'autostart') {
        // A setter acknowledgement is intentionally not the read-back settings.
        plan.resolve(undefined); return;
      }
      if (operation !== 'startup') {
        // Core save_prefs publishes through the existing registered event path.
        // set_startup_mode, in contrast, must use its returned Snapshot; no
        // synthetic event masks a caller that ignores that native return value.
        window.__aboutBusy(false);
      }
      plan.resolve(structuredClone(core));
    }
  };
"""
OVERRIDE = r"""(() => {
  const originalFixtureInvoke = window.__TAURI_INTERNALS__.invoke;
  const fx = window.__startupFixture;
  const exact = (args, key, type) => args && Object.keys(args).length === 1 && typeof args[key] === type;
  window.__TAURI_INTERNALS__.invoke = async (command, args) => {
    if (command === 'get_desktop_settings') {
      if (args !== undefined && Object.keys(args).length) throw new Error('unexpected_settings_args');
      if (fx.pending('settings')) throw new Error('duplicate_settings_read');
      // A read is held only when explicitly armed after initial bootstrap.
      try { return await fx.request('settings', {}); }
      catch (error) {
        if (error.message !== 'startup_operation_not_explicitly_held') throw error;
        fx.calls.push({operation: 'settings-bootstrap', payload: {}, t: performance.now()});
        return structuredClone(fx.settings);
      }
    }
    if (command === 'set_autostart' && exact(args, 'enabled', 'boolean'))
      return fx.request('autostart', args);
    if (command === 'set_startup_mode' && exact(args, 'minimized', 'boolean'))
      return fx.request('startup', args);
    if (command === 'core_request' && args?.command === 'save_prefs' &&
        Object.keys(args).every(key => ['command', 'args'].includes(key))) {
      const change = args.args;
      if (exact(change, 'close_to_tray', 'boolean')) return fx.request('tray', change);
      if (exact(change, 'theme', 'string') && ['system', 'light', 'dark'].includes(change.theme))
        return fx.request('theme', change);
      if (exact(change, 'accent', 'string') && ['blue', 'rose'].includes(change.accent))
        return fx.request('accent', change);
    }
    if (command === 'plugin:event|listen' || command === 'plugin:event|unlisten' ||
        (command === 'core_request' && args?.command === 'snapshot'))
      return originalFixtureInvoke(command, args);
    window.__aboutUnexpected.push(command);
    throw new Error('unexpected_startup_fixture_ipc');
  };
})();"""
NATIVE = NATIVE_FIXTURE.replace(_MARKER, EXTENSION + _MARKER) + '\n' + OVERRIDE
NO_NATIVE = r"""(() => {
  window.isTauri = false;
  window.__startupForbiddenNative = [];
  window.__TAURI_INTERNALS__ = {invoke(command) {
    window.__startupForbiddenNative.push(command);
    throw new Error('native_forbidden_in_plain_browser');
  }};
})();"""

# Capture real rAF samples, mutation-time notices and Web Animation timelines.
# Nothing here sets application state or imports a production module.
SAMPLER = r"""({selectors, control}) => {
  if (window.__startupSample?.running) throw new Error('startup_sampler_already_running');
  const ids = window.__startupNoticeIds ||= new WeakMap();
  window.__startupNoticeNext ||= 1;
  const identify = el => {if (!ids.has(el)) ids.set(el, window.__startupNoticeNext++); return ids.get(el);};
  const animations = el => el.getAnimations({subtree: true}).map(animation => ({
    name: animation.animationName || '', time: animation.currentTime, state: animation.playState,
    pseudo: animation.effect?.pseudoElement || '', duration: animation.effect?.getTiming().duration,
    keyframes: animation.effect?.getKeyframes().map(k => ({opacity: k.opacity, transform: k.transform})) || []
  }));
  const notices = () => [...document.querySelectorAll('.feedback-dock .feedback-notice, .feedback-dock .feedback-busy')]
    .map(el => ({id: identify(el), notice: el.classList.contains('feedback-notice'),
      error: el.getAttribute('role') === 'alert', text: el.querySelector('.feedback-message')?.textContent || '',
      opacity: +getComputedStyle(el).opacity, animations: animations(el)}));
  const s = window.__startupSample = {running: true, selectors, control, frames: [], mutations: [],
    initialNotices: notices().map(n => n.id)};
  const capture = () => {
    const boxes = {};
    for (const selector of selectors) {
      const el = document.querySelector(selector);
      if (el) {const r = el.getBoundingClientRect(); boxes[selector] = {x:r.x, y:r.y, width:r.width, height:r.height};}
    }
    const el = document.querySelector(control), knob = el?.querySelector('.toggle-knob');
    const css = knob && getComputedStyle(knob, '::after');
    s.frames.push({t: performance.now(), boxes, feedback: notices(),
      theme: document.documentElement.dataset.theme, accent: document.documentElement.dataset.accent,
      control: el ? {busy: el.getAttribute('aria-busy'), disabled: el.disabled,
        value: el.getAttribute('aria-checked') ?? el.getAttribute('aria-pressed'), focused: el === document.activeElement,
        knob: css ? {name: css.animationName, duration: css.animationDuration,
          iterations: css.animationIterationCount, timing: css.animationTimingFunction, transform: css.transform,
          content: css.content, animations: animations(knob)} : null} : null});
    if (s.running) s.raf = requestAnimationFrame(capture);
  };
  s.observer = new MutationObserver(() => s.mutations.push({t: performance.now(), feedback: notices()}));
  s.observer.observe(document.querySelector('.workspace'), {subtree:true, childList:true, attributes:true, characterData:true});
  capture();
}"""
STOP_SAMPLER = r"""async () => {
  for (let i = 0; i < 12; i++) await new Promise(requestAnimationFrame);
  const s = window.__startupSample; s.running = false;
  cancelAnimationFrame(s.raf); s.observer.disconnect();
  return {selectors:s.selectors, control:s.control, frames:s.frames, mutations:s.mutations, initialNotices:s.initialNotices};
}"""


def origin_key(url):
    parsed = urlsplit(url)
    return parsed.scheme, parsed.hostname, parsed.port or 80


def visit_url(base, **query):
    parsed = urlsplit(base)
    params = dict(parse_qsl(parsed.query))
    params.update(query)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path or '/', urlencode(params), ''))


class Regression:
    def __init__(self, args):
        self.args = args
        self.contexts = []
        self.report = {
            'ok': False, 'mode': 'synthetic-native-fixture-and-shipped-memory-demo',
            'real_native_ipc': False, 'real_os_autostart': False, 'real_authentication': False,
            'production_preview_started_by_script': False,
            'limits': ['Browser assertions require an explicitly authorized run against the existing production preview.',
                       'No native OS startup/tray integration or disk persistence is exercised.',
                       'Animation evidence is Chromium rAF/computed style/Web Animations, not a compositor trace.'],
            'checks': [], 'samples': [], 'layouts': [], 'blocked_requests': [],
            'page_errors': [], 'console_errors': [], 'unexpected_ipc': [],
        }

    def check(self, name):
        self.report['checks'].append(name)

    def context(self, browser, *, native=True, reduced=False):
        context = browser.new_context(viewport={'width': 1000, 'height': 720},
                                      reduced_motion='reduce' if reduced else 'no-preference', service_workers='block')
        self.contexts.append(context)
        context.add_init_script(NATIVE if native else NO_NATIVE)
        base_path = urlsplit(self.args.url).path or '/'
        asset_root = base_path.rsplit('/', 1)[0] + '/assets/'
        extensions = {
            'script': ('.js', '.mjs'), 'stylesheet': ('.css',),
            'font': ('.woff', '.woff2', '.ttf', '.otf'),
            'image': ('.svg', '.png', '.jpg', '.jpeg', '.webp', '.ico', '.avif'),
        }

        def guard(route):
            request, target = route.request, urlsplit(route.request.url)
            static_asset = (target.path.startswith(asset_root) and not target.query and not target.fragment
                            and '%' not in target.path and '\\' not in target.path and '..' not in target.path
                            and target.path.endswith(extensions.get(request.resource_type, ())))
            document = (request.resource_type == 'document' and request.is_navigation_request()
                        and target.path == base_path)
            favicon = (request.resource_type in ('image', 'other') and target.path == '/favicon.svg'
                       and not target.query and not target.fragment)
            if (origin_key(request.url) == origin_key(self.args.url) and not target.username and not target.password
                    and request.method == 'GET' and (document or static_asset or favicon)):
                route.continue_()
            else:
                # Never put query strings, credentials or response bodies in the report.
                self.report['blocked_requests'].append({'type': request.resource_type, 'method': request.method,
                                                        'same_origin': origin_key(request.url) == origin_key(self.args.url)})
                route.abort()

        def block_socket(socket):
            self.report['blocked_requests'].append({'type': 'websocket'})
            socket.close()

        context.route('**/*', guard)
        assert hasattr(context, 'route_web_socket'), 'Playwright >=1.48 required: WebSockets must fail closed'
        context.route_web_socket('**/*', block_socket)
        page = context.new_page()
        page.on('pageerror', lambda error: self.report['page_errors'].append(str(error)))
        page.on('console', lambda message: self.report['console_errors'].append(message.text)
                if message.type == 'error' else None)
        return page

    def load(self, page, **query):
        page.goto(visit_url(self.args.url, **query))
        page.wait_for_load_state('networkidle')
        expect(page.get_by_role('heading', name='连接', exact=True)).to_be_visible()
        self.desktop(page)
        page.mouse.move(1, 1)

    def desktop(self, page):
        page.get_by_role('button', name='设置', exact=True).click()
        page.get_by_role('tab', name='外观与启动', exact=True).click()
        expect(page.get_by_role('switch', name=STARTUP, exact=True)).to_be_visible()
        page.wait_for_timeout(350)  # Settle shipped page motion before geometry sampling.

    def control(self, page, operation, desired=None):
        if operation in LABELS:
            return page.get_by_role('switch', name=LABELS[operation], exact=True)
        return page.get_by_role('group', name='外观' if operation == 'theme' else '主题色', exact=True).get_by_role(
            'button', name=OPTIONS[operation][desired], exact=True)

    def selected(self, page, operation):
        if operation in LABELS:
            return self.control(page, operation).get_attribute('aria-checked') == 'true'
        group = page.get_by_role('group', name='外观' if operation == 'theme' else '主题色', exact=True)
        return next(value for value, label in OPTIONS[operation].items()
                    if group.get_by_role('button', name=label, exact=True).get_attribute('aria-pressed') == 'true')

    def expect_selected(self, page, operation, value):
        if operation in LABELS:
            expect(self.control(page, operation)).to_have_attribute('aria-checked', str(value).lower())
        else:
            expect(self.control(page, operation, value)).to_have_attribute('aria-pressed', 'true')
            expect(page.locator('html')).to_have_attribute('data-' + operation, value)

    def fixture(self, page, method, *values):
        return page.evaluate('([method, values]) => window.__startupFixture[method](...values)', [method, list(values)])

    def wait_pending(self, page, operation):
        page.wait_for_function('operation => window.__startupFixture.pending(operation)', arg=operation)

    def dismiss(self, page):
        if page.locator(CLOSE).count():
            page.locator(CLOSE).click()
        expect(page.locator(NOTICE)).to_have_count(0)
        expect(page.locator(BUSY)).to_have_count(0)

    def layout(self, page, name):
        result = page.evaluate(r"""() => {
          const main = document.querySelector('main'), dock = document.querySelector('.feedback-dock');
          const notices = [...dock.querySelectorAll('.feedback-toast')];
          return {documentOverflow: document.documentElement.scrollWidth > innerWidth + 1,
            mainOverflow: main.scrollWidth > main.clientWidth + 1, dockPosition: getComputedStyle(dock).position,
            noticeOverflow: notices.some(el => {const r = el.getBoundingClientRect();
              return r.left < -1 || r.right > innerWidth + 1 || r.top < -1 || r.bottom > innerHeight + 1;}),
            inlineFeedback: [...document.querySelectorAll('.notice, .busy-line')].some(el => !el.closest('.feedback-dock'))};
        }""")
        self.report['layouts'].append({'name': name, **result})
        assert result['dockPosition'] == 'absolute', (name, 'global dock must remain absolute', result)
        assert not any(result[key] for key in ('documentOverflow', 'mainOverflow', 'noticeOverflow', 'inlineFeedback')), (name, result)

    def start_sample(self, page, operation, desired, *, detached=False):
        control = SELECTORS.get(operation) or OPTION_SELECTORS[operation][desired]
        selectors = ['main', '.page-header'] if detached else STABLE
        for selector in selectors:
            expect(page.locator(selector)).to_have_count(1)
        page.evaluate(SAMPLER, {'selectors': selectors, 'control': control})

    def stop_sample(self, page, name, *, reduced, operation, before, success=None, spinning=True,
                    fast=False, detached=False):
        sample = page.evaluate(STOP_SAMPLER)
        frames = sample['frames']
        assert len(frames) >= 12, (name, 'missing rAF evidence')
        geometry = {}
        for selector in sample['selectors']:
            boxes = [frame['boxes'][selector] for frame in frames if selector in frame['boxes']]
            assert len(boxes) == len(frames), (name, selector, 'stable element disappeared')
            delta = {axis: max(box[axis] for box in boxes) - min(box[axis] for box in boxes)
                     for axis in ('x', 'y', 'width', 'height')}
            assert max(delta.values()) <= 1, (name, selector, delta)
            geometry[selector] = delta
        observations = frames + sample['mutations']
        feedback = [notice for frame in observations for notice in frame['feedback']]
        assert not any(marker in notice['text'] for notice in feedback for marker in RAW_MARKERS), (name, 'raw fixture error leaked')
        audit = page.evaluate('({calls: window.__startupFixture.calls, completed: window.__startupFixture.completed})')
        started = next(call['t'] for call in reversed(audit['calls']) if call['operation'] == operation)
        completion_kind = 'settings' if operation == 'autostart' and any(
            item['operation'] == 'settings' and item['t'] >= started for item in audit['completed']) else operation
        confirmed_at = next(item['t'] for item in reversed(audit['completed']) if item['operation'] == completion_kind)
        held_frames = [frame for frame in frames if started <= frame['t'] < confirmed_at and frame['control']]
        assert held_frames, (name, 'missing pre-confirmation frame evidence')
        expected_value = str(before).lower() if operation in LABELS else 'false'
        assert all(frame['control']['value'] == expected_value for frame in held_frames), (name, 'optimistic control value')
        if operation in OPTIONS:
            assert all(frame[operation] == before for frame in held_frames), (name, 'optimistic appearance preference')
        assert not any(notice['notice'] and not notice['error'] and notice['id'] not in sample['initialNotices']
                       for frame in observations if started <= frame['t'] < confirmed_at
                       for notice in frame['feedback']), (name, 'success before authoritative result')
        pending = [frame for frame in frames if frame['control'] and frame['control']['busy'] == 'true']
        if operation in LABELS and spinning and not fast:
            assert pending, (name, 'no pending switch frames')
            assert all(frame['control']['value'] == str(before).lower() for frame in pending), (name, 'optimistic switch value')
            knobs = [frame['control']['knob'] for frame in pending]
            assert all(knob is not None for knob in knobs), (name, 'missing switch knob')
            if reduced:
                assert all(knob['name'] == 'none' and not any(a['name'] == 'feedback-spin' for a in knob['animations'])
                           for knob in knobs), (name, 'reduced-motion spinner')
            else:
                assert all(knob['name'] == 'feedback-spin' and knob['duration'] == '1s'
                           and knob['iterations'] == 'infinite' and knob['timing'] == 'linear' for knob in knobs), (name, knobs)
                assert len({knob['transform'] for knob in knobs}) > 1, (name, 'pseudo-element transform did not advance')
                times = [animation['time'] for knob in knobs for animation in knob['animations']
                         if animation['name'] == 'feedback-spin' and isinstance(animation['time'], (int, float))]
                assert len(times) > 1 and max(times) > min(times), (name, 'pseudo-element animation timeline did not advance')
        if fast:
            assert not any(not notice['notice'] for notice in feedback), (name, 'fast operation flashed busy feedback')
        if success:
            arrivals = [notice for notice in feedback if notice['notice'] and not notice['error']
                        and notice['text'] == success and notice['id'] not in sample['initialNotices']]
            assert arrivals, (name, 'completion did not mount a fresh success notice')
            if reduced:
                assert all(notice['opacity'] == 1 for notice in arrivals), (name, 'reduced-motion fade')
                assert all(animation['duration'] == 0 or animation['state'] == 'finished'
                           for notice in arrivals for animation in notice['animations']), (name, 'running reduced-motion notice')
            else:
                assert any(animation['duration'] == 120 and len({key.get('opacity') for key in animation['keyframes']}) > 1
                           for notice in arrivals for animation in notice['animations']), (name, 'missing actual 120ms success fade')
        sample.update({'name': name, 'reduced_motion': reduced, 'detached_controls': detached, 'max_geometry_delta': geometry})
        filename = name + '-frames.json'
        (self.args.output / filename).write_text(json.dumps(sample, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        self.report['samples'].append({'name': name, 'file': filename, 'frames': len(frames), 'max_geometry_delta': geometry})
        return sample

    def begin(self, page, operation, desired, *, keyboard=False, readback=True, fast=False):
        old = self.selected(page, operation)
        assert old != desired, (operation, 'test must change the actual control')
        self.fixture(page, 'hold', operation, 80 if fast else None)
        if operation == 'autostart' and readback:
            self.fixture(page, 'hold', 'settings')
        control = self.control(page, operation, desired)
        expect(control).to_be_enabled()
        if keyboard:
            control.focus()
            expect(control).to_be_focused()
            page.keyboard.press('Space')
        else:
            control.click()
        self.wait_pending(page, operation) if not fast else None
        if not fast:
            expect(control).to_be_disabled()
            if operation in LABELS:
                expect(control).to_have_attribute('aria-busy', 'true')
            self.expect_selected(page, operation, old)
        return old

    def pending_delay(self, page, operation, old):
        expect(page.locator(NOTICE)).to_have_count(0)
        expect(page.locator(BUSY)).to_be_visible(timeout=1500)
        self.expect_selected(page, operation, old)
        if operation in LABELS:
            expect(self.control(page, operation)).to_have_attribute('aria-busy', 'true')
        page.wait_for_timeout(180)  # Enough live frames to observe spinner progression.

    def finish(self, page, operation, outcome='saved', *, actual=None):
        self.fixture(page, 'finish', operation, outcome)
        if operation == 'autostart' and outcome in ('raw', 'error'):
            self.fixture(page, 'discard', 'settings')
        if operation == 'autostart' and outcome not in ('raw', 'error'):
            self.wait_pending(page, 'settings')
            expect(page.locator(NOTICE)).to_have_count(0)
            # Read-back is separately held: setter acknowledgement cannot save UI state.
            expect(self.control(page, operation)).to_have_attribute('aria-busy', 'true')
            self.fixture(page, 'finish', 'settings', 'saved', actual)

    def success(self, page, operation, desired, *, reduced, name, keyboard=False, fast=False, dismiss=True):
        self.start_sample(page, operation, desired)
        old = self.begin(page, operation, desired, keyboard=keyboard, fast=fast)
        if not fast:
            self.pending_delay(page, operation, old)
            if operation == 'autostart':
                self.fixture(page, 'finish', operation)
                self.wait_pending(page, 'settings')
                self.expect_selected(page, operation, old)
                expect(self.control(page, operation)).to_have_attribute('aria-busy', 'true')
                expect(page.locator(NOTICE)).to_have_count(0)
                page.wait_for_timeout(100)
                self.expect_selected(page, operation, old)
                self.fixture(page, 'finish', 'settings')
            else:
                self.finish(page, operation)
        message = SUCCESS[operation][desired]
        expect(page.locator(NOTICE + '[role="status"] .feedback-message')).to_have_text(message)
        self.expect_selected(page, operation, desired)
        expect(self.control(page, operation, desired)).to_be_enabled()
        if operation in LABELS:
            expect(self.control(page, operation)).to_have_attribute('aria-busy', 'false')
        assert not page.locator('.feedback-dock :focus').count(), 'feedback must not steal keyboard focus'
        page.mouse.move(1, 1)
        sample = self.stop_sample(page, name, reduced=reduced, operation=operation, before=old, success=message, fast=fast)
        self.layout(page, name)
        if not fast:
            calls = page.evaluate('window.__startupFixture.calls')
            started = next(call['t'] for call in reversed(calls) if call['operation'] == operation)
            visible = [frame['t'] for frame in sample['frames']
                       if any(not notice['notice'] and notice['opacity'] > .01 for notice in frame['feedback'])]
            assert visible and min(visible) - started >= 240, (name, 'busy appeared before the existing 250ms delay')
        if keyboard:
            self.control(page, operation, desired).focus()
            expect(self.control(page, operation, desired)).to_be_focused()
            page.keyboard.press('Tab')
            assert not page.locator('body:focus').count(), 'completed control must rejoin keyboard navigation'
        if dismiss:
            self.dismiss(page)
        self.check(name)

    def failure(self, page, operation, desired, *, reduced, name, mismatch=False, persist=False):
        self.start_sample(page, operation, desired)
        old = self.begin(page, operation, desired)
        self.pending_delay(page, operation, old)
        self.finish(page, operation, 'ack' if mismatch else 'raw', actual=old if operation == 'autostart' else None)
        expect(page.locator(NOTICE + '[role="alert"]')).to_be_visible()
        expect(page.locator(NOTICE + ' .feedback-message')).not_to_have_text('')
        self.expect_selected(page, operation, old)
        expect(self.control(page, operation, desired)).to_be_enabled()
        body = page.locator('body').inner_text()
        assert not any(marker in body for marker in RAW_MARKERS), (name, 'raw private error displayed')
        sample = self.stop_sample(page, name, reduced=reduced, operation=operation, before=old)
        assert not any(notice['notice'] and not notice['error'] for frame in sample['frames'] + sample['mutations']
                       for notice in frame['feedback']), (name, 'failure produced a false success')
        if persist:
            page.mouse.move(1, 1)
            self.control(page, operation, desired).focus()  # No hover/focus pause on the error notice.
            page.wait_for_timeout(4800)
            expect(page.locator(NOTICE + '[role="alert"]')).to_be_visible()
            self.layout(page, name + '-persistent')
        page.locator(CLOSE).focus()
        page.keyboard.press('Enter')
        expect(page.locator(NOTICE)).to_have_count(0)
        self.check(name)

    def detached(self, page, *, reduced, fail=False):
        operation, desired = 'startup', not self.selected(page, 'startup')
        name = ('reduced' if reduced else 'normal') + '-detached-' + ('failure' if fail else 'success')
        self.start_sample(page, operation, desired, detached=True)
        old = self.begin(page, operation, desired)
        self.pending_delay(page, operation, old)
        page.get_by_role('button', name='连接', exact=True).click()
        expect(self.control(page, operation)).to_have_count(0)
        # Let navigation motion settle; geometry across *different pages* is not
        # an invariant. The dock must survive even though the initiating node did not.
        self.finish(page, operation, 'raw' if fail else 'saved')
        expect(page.locator(NOTICE + ('[role="alert"]' if fail else '[role="status"]'))).to_be_visible()
        sample = page.evaluate(STOP_SAMPLER)
        assert any(frame['control'] is None for frame in sample['frames']), (name, 'control never detached')
        assert not any(marker in notice['text'] for frame in sample['frames'] + sample['mutations']
                       for notice in frame['feedback'] for marker in RAW_MARKERS), (name, 'raw detached error')
        if fail:
            assert not any(n['notice'] and not n['error'] for frame in sample['frames'] + sample['mutations']
                           for n in frame['feedback']), (name, 'detached failure claimed success')
        else:
            assert any(n['text'] == SUCCESS[operation][desired] for frame in sample['frames']
                       for n in frame['feedback']), (name, 'detached success missing')
        filename = name + '-frames.json'
        (self.args.output / filename).write_text(json.dumps(sample, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        self.report['samples'].append({'name': name, 'file': filename, 'frames': len(sample['frames']),
                                       'geometry_limit': 'Page navigation intentionally changes content geometry.'})
        self.layout(page, name)
        self.desktop(page)
        self.expect_selected(page, operation, old if fail else desired)
        self.dismiss(page)
        self.check(name)

    def native_matrix(self, browser, *, reduced):
        page = self.context(browser, reduced=reduced)
        prefix = 'reduced' if reduced else 'normal'
        self.load(page, fixture_legacy='1')
        self.expect_selected(page, 'startup', True)  # Missing legacy pref must default TRUE.
        self.expect_selected(page, 'autostart', False)
        before = len(page.evaluate('window.__startupFixture.calls'))
        self.success(page, 'startup', False, reduced=reduced, name=prefix + '-startup-while-autostart-off', keyboard=True)
        calls = page.evaluate('window.__startupFixture.calls')[before:]
        assert not any(call['operation'] == 'autostart' for call in calls), 'Startup mode must not enable OS autostart'
        assert page.evaluate('window.__startupFixture.settings.autostart') is False
        self.success(page, 'startup', True, reduced=reduced, name=prefix + '-startup-tray')
        for operation, desired in (('autostart', True), ('autostart', False), ('tray', True), ('tray', False),
                                   ('theme', 'dark'), ('theme', 'light'), ('accent', 'rose'), ('accent', 'blue')):
            self.success(page, operation, desired, reduced=reduced, name=f'{prefix}-{operation}-{str(desired).lower()}',
                         keyboard=operation == 'autostart' and desired is True)
        self.success(page, 'startup', False, reduced=reduced, name=prefix + '-fast-startup', fast=True)
        # Same success text while its predecessor is live must remount/replay;
        # no direct notice injection and no manual close between these operations.
        for index, value in enumerate(('dark', 'light', 'dark')):
            self.success(page, 'theme', value, reduced=reduced, name=f'{prefix}-repeat-theme-{index}', dismiss=False)
        expect(page.locator(NOTICE)).to_have_count(1)
        self.dismiss(page)
        for operation, desired in (('autostart', True), ('startup', True), ('tray', True),
                                   ('theme', 'light'), ('accent', 'rose')):
            self.failure(page, operation, desired, reduced=reduced, name=f'{prefix}-{operation}-raw-failure',
                         persist=not reduced and operation == 'startup')
            self.failure(page, operation, desired, reduced=reduced, name=f'{prefix}-{operation}-ack-without-save', mismatch=True)
        # Also cover failed disable: read-back true must remain true, not an
        # optimistic unchecked UI or a false "disabled" success.
        self.success(page, 'autostart', True, reduced=reduced, name=prefix + '-autostart-before-disable-mismatch')
        self.failure(page, 'autostart', False, reduced=reduced, name=prefix + '-disable-readback-opposite', mismatch=True)
        self.success(page, 'autostart', False, reduced=reduced, name=prefix + '-autostart-cleanup')
        self.detached(page, reduced=reduced)
        self.detached(page, reduced=reduced, fail=True)
        for width, height in ((1000, 720), (700, 560), (390, 844), (320, 720)):
            page.set_viewport_size({'width': width, 'height': height})
            self.layout(page, f'{prefix}-width-{width}')
        self.check(prefix + '-legacy-default-and-normal-reduced-settings-contract')

    def readback_failure(self, browser):
        page = self.context(browser)
        self.load(page)
        self.start_sample(page, 'autostart', True)
        old = self.begin(page, 'autostart', True)
        self.pending_delay(page, 'autostart', old)
        self.fixture(page, 'finish', 'autostart', 'ack')
        self.wait_pending(page, 'settings')
        self.expect_selected(page, 'autostart', old)
        expect(page.locator(NOTICE)).to_have_count(0)
        self.fixture(page, 'finish', 'settings', 'raw')
        expect(page.locator(NOTICE + '[role="alert"]')).to_be_visible()
        self.expect_selected(page, 'autostart', old)
        sample = self.stop_sample(page, 'autostart-readback-failure', reduced=False, operation='autostart', before=old)
        assert not any(n['notice'] and not n['error'] for frame in sample['frames'] + sample['mutations']
                       for n in frame['feedback']), 'Read-back rejection must not announce success'
        self.dismiss(page)
        self.check('autostart-setter-ack-and-readback-error-are-not-saved-state')

    def restricted_modes(self, browser):
        native_demo = self.context(browser, reduced=True)
        self.load(native_demo, fixture_demo='1')
        for operation in ('autostart', 'startup'):
            expect(self.control(native_demo, operation)).to_be_disabled()
        expect(self.control(native_demo, 'tray')).to_be_enabled()
        assert not any(call['operation'] in ('autostart', 'startup')
                       for call in native_demo.evaluate('window.__startupFixture.calls'))
        self.success(native_demo, 'tray', True, reduced=True, name='native-demo-tray-temporary-preference')
        self.success(native_demo, 'theme', 'dark', reduced=True, name='native-demo-theme-safe-preference')
        self.success(native_demo, 'accent', 'rose', reduced=True, name='native-demo-accent-safe-preference')
        no_tray = self.context(browser, reduced=True)
        self.load(no_tray, fixture_tray='0')
        expect(self.control(no_tray, 'tray')).to_be_disabled()
        self.check('native-demo-os-affecting-controls-and-no-tray-control-disabled')

        demo = self.context(browser, native=False, reduced=True)
        self.load(demo, demo='1', theme='light')
        self.expect_selected(demo, 'startup', True)
        self.expect_selected(demo, 'autostart', False)
        self.control(demo, 'startup').focus()
        demo.keyboard.press('Space')
        self.expect_selected(demo, 'startup', False)
        self.expect_selected(demo, 'autostart', False)
        expect(demo.locator(NOTICE + ' .feedback-message')).to_have_text(SUCCESS['startup'][False])
        self.dismiss(demo)
        self.control(demo, 'autostart').click()
        self.expect_selected(demo, 'autostart', True)
        expect(demo.locator(NOTICE + ' .feedback-message')).to_have_text(SUCCESS['autostart'][True])
        self.dismiss(demo)
        self.control(demo, 'tray').click()
        self.expect_selected(demo, 'tray', False)
        expect(demo.locator(NOTICE + ' .feedback-message')).to_have_text(SUCCESS['tray'][False])
        self.dismiss(demo)
        self.control(demo, 'theme', 'dark').click()
        self.expect_selected(demo, 'theme', 'dark')
        expect(demo.locator(NOTICE + ' .feedback-message')).to_have_text(SUCCESS['theme']['dark'])
        self.dismiss(demo)
        self.control(demo, 'accent', 'rose').click()
        self.expect_selected(demo, 'accent', 'rose')
        expect(demo.locator(NOTICE + ' .feedback-message')).to_have_text(SUCCESS['accent']['rose'])
        self.layout(demo, 'plain-demo-memory-only')
        assert demo.evaluate('window.__startupForbiddenNative') == []
        demo.reload()
        demo.wait_for_load_state('networkidle')
        self.desktop(demo)
        self.expect_selected(demo, 'startup', True)
        self.expect_selected(demo, 'autostart', False)
        self.expect_selected(demo, 'theme', 'light')
        self.expect_selected(demo, 'accent', 'blue')
        self.check('shipped-plain-demo-startup-mode-is-memory-only-and-never-enables-autostart')

        web = self.context(browser, native=False, reduced=True)
        self.load(web)
        for operation in LABELS:
            expect(self.control(web, operation)).to_be_disabled()
        for operation in OPTIONS:
            for option in OPTIONS[operation]:
                expect(self.control(web, operation, option)).to_be_disabled()
        expect(web.locator('.web-mode')).to_contain_text('普通网页')
        expect(web.locator(NOTICE)).to_have_count(0)
        self.layout(web, 'ordinary-web-disabled')
        assert web.evaluate('window.__startupForbiddenNative') == []
        self.check('ordinary-web-controls-disabled-without-native-fallback')

    def run(self, browser):
        self.native_matrix(browser, reduced=False)
        self.native_matrix(browser, reduced=True)
        self.readback_failure(browser)
        self.restricted_modes(browser)
        for context in self.contexts:
            for page in context.pages:
                assert page.evaluate('localStorage.length + sessionStorage.length') == 0, 'Preview must not persist real settings'
                if page.evaluate('Boolean(window.__startupFixture)'):
                    self.report['unexpected_ipc'].extend(page.evaluate('window.__aboutUnexpected'))
                    assert page.evaluate("window.__aboutCalls.every(c => ['plugin:event|listen', 'plugin:event|unlisten'].includes(c.command) || (c.command === 'core_request' && c.args.command === 'snapshot'))"), 'Only fixture bootstrap may delegate to About invoke'
                else:
                    assert page.evaluate('window.__startupForbiddenNative') == []
        for key in ('blocked_requests', 'page_errors', 'console_errors', 'unexpected_ipc'):
            assert not self.report[key], (key, self.report[key])
        self.report['ok'] = True


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--url', required=True)
    parser.add_argument('--browser', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    base = urlsplit(args.url)
    assert (base.scheme == 'http' and base.hostname in ('127.0.0.1', 'localhost', '::1')
            and not base.username and not base.password and not base.fragment), 'Only a loopback HTTP production preview is allowed'
    assert not dict(parse_qsl(base.query)).get('demo'), '--url must be the production base, not a demo URL'
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
        report = args.output / 'startup-feedback-report.json'
        report.write_text(json.dumps(suite.report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(json.dumps({'ok': suite.report['ok'], 'report': str(report), 'checks': suite.report['checks']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
