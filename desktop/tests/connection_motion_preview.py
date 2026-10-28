#!/usr/bin/env python3
"""Offline connection-ripple acceptance against the parent's existing preview.

    python desktop/tests/connection_motion_preview.py --url http://127.0.0.1:1423/ \
        --browser /usr/bin/google-chrome --output build/connection-motion-20261025/after

Never builds or starts a server. Native IPC is replaced before app initialization;
only fixed, synthetic snapshots and a read-only status query are supported. The
visibilitychange case overrides a document property in this isolated browser: it
is NOT a real OS minimize/background integration test. --fixture-smoke uses only
about:blank and synthetic HTML, without loading the application or any server.
"""
import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Importing the existing test fixture must not create an unauthorized __pycache__.
sys.dont_write_bytecode = True
from playwright.sync_api import expect, sync_playwright
from about_preview import NATIVE_FIXTURE


ROOT = Path(__file__).resolve().parents[2]
ACCENTS = ('blue', 'teal', 'indigo', 'violet', 'rose', 'amber')
EMBLEM = '.connection-emblem'
BOXES = (EMBLEM, EMBLEM + ' svg', '.state-copy h2', '.connection-context',
         '.connection-overview', '.page-header h1')
MARKER = '  window.__TAURI_EVENT_PLUGIN_INTERNALS__ ='
assert NATIVE_FIXTURE.count(MARKER) == 1, 'Inspect changed About fixture before reuse'
EXTENSION = r"""
  const query = new URLSearchParams(location.search);
  core.prefs.theme = query.get('theme') === 'dark' ? 'dark' : 'light';
  core.prefs.accent = ['blue','teal','indigo','violet','rose','amber'].includes(query.get('accent')) ? query.get('accent') : 'blue';
  const fx = window.__connectionMotionFixture = {
    active: false, statusCalls: 0,
    emit() {window.__aboutBusy(core.busy);},
    state(online) {
      if (![true, false, null].includes(online)) throw new Error('invalid_fixture_state');
      core.status = {online, service: online ? '校园网' : null, user: '', ip: '', message: ''};
      this.emit();
    },
    same() {this.emit();},
    prefs(theme, accent) {
      if (!['light','dark'].includes(theme) || !['blue','teal','indigo','violet','rose','amber'].includes(accent)) throw new Error('invalid_fixture_palette');
      core.prefs = {...core.prefs, theme, accent}; this.emit();
    },
    query() {
      if (this.active) throw new Error('fixture_query_already_active');
      this.active = true; this.statusCalls++; window.__aboutBusy(true);
      setTimeout(() => {this.active = false; window.__aboutBusy(false);}, 900);
      return {accepted:true, message:'离线夹具：只读状态查询已排队'};
    }
  };
"""
NATIVE = NATIVE_FIXTURE.replace(MARKER, EXTENSION + MARKER) + r"""
(() => {
  const original = window.__TAURI_INTERNALS__.invoke;
  window.__TAURI_INTERNALS__.invoke = async (command, args) => {
    if (command === 'plugin:event|listen' || command === 'plugin:event|unlisten' ||
        command === 'get_desktop_settings' || (command === 'core_request' && ['snapshot', 'observe'].includes(args?.command))) return original(command, args);
    if (command === 'core_request' && args?.command === 'action' && args?.args?.name === 'status' &&
        Object.keys(args.args).length === 1) {
      window.__aboutCalls.push({command, args}); return window.__connectionMotionFixture.query();
    }
    window.__aboutUnexpected.push(command); throw new Error('unexpected_connection_motion_fixture_ipc');
  };
})();
"""
# These guards also cover transports which HTTP routing would otherwise miss.
# They never delegate to a real Tauri IPC object or a browser network method.
NETWORK_GUARD = r"""(() => {
  window.__motionForbidden = [];
  const forbidden = kind => {window.__motionForbidden.push(kind); throw new Error('forbidden_test_transport:' + kind);};
  window.fetch = () => forbidden('fetch');
  XMLHttpRequest.prototype.open = () => forbidden('xhr');
  window.WebSocket = class {constructor() {forbidden('websocket');}};
  window.EventSource = class {constructor() {forbidden('eventsource');}};
  navigator.sendBeacon = () => forbidden('beacon');
  window.open = () => forbidden('window.open');
})();"""

# CSS pseudo-elements are observed via actual computed styles and actual
# CSSAnimation objects. Animation objects receive stable weak identities so a
# cancel/recreate or same-state restart cannot hide behind an equal phase.
OBSERVER = r"""(() => {
  let next = 1; const ids = new WeakMap();
  const id = animation => {if (!ids.has(animation)) ids.set(animation, next++); return ids.get(animation);};
  const box = node => {const r=node.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height};};
  const pseudo = animation => animation.effect?.pseudoElement || '';
  const describe = animation => {
    const t=animation.effect?.getTiming(), target=animation.effect?.target;
    return {id:id(animation),name:animation.animationName || '',pseudo:pseudo(animation),
      target:target?.classList?.contains('connection-emblem') ? 'emblem' : target?.tagName || '',
      currentTime:animation.currentTime, startTime:animation.startTime, state:animation.playState,
      iterations:t?.iterations === Infinity ? 'infinite' : t?.iterations, duration:t?.duration,
      delay:t?.delay, frames:animation.effect?.getKeyframes().map(k=>({transform:k.transform,opacity:k.opacity}))};
  };
  const isLoop = a => a.effect?.getTiming().iterations === Infinity;
  const decoration = (node, selector) => {
    const c=getComputedStyle(node,selector), e=node.getBoundingClientRect();
    let rect=null;
    if (c.content !== 'none' && c.display !== 'none' && Number.isFinite(parseFloat(c.left)) && Number.isFinite(parseFloat(c.top))) {
      const number = value => parseFloat(value) || 0;
      const width=number(c.width)+(c.boxSizing==='border-box'?0:number(c.paddingLeft)+number(c.paddingRight)+number(c.borderLeftWidth)+number(c.borderRightWidth));
      const height=number(c.height)+(c.boxSizing==='border-box'?0:number(c.paddingTop)+number(c.paddingBottom)+number(c.borderTopWidth)+number(c.borderBottomWidth));
      const origin=c.transformOrigin.split(' ').map(number), m=new DOMMatrixReadOnly(c.transform==='none'?undefined:c.transform);
      const points=[[0,0],[width,0],[0,height],[width,height]].map(([x,y])=>new DOMPoint(x-origin[0],y-origin[1]).matrixTransform(m));
      const xs=points.map(p=>e.x+number(getComputedStyle(node).borderLeftWidth)+number(c.left)+origin[0]+p.x);
      const ys=points.map(p=>e.y+number(getComputedStyle(node).borderTopWidth)+number(c.top)+origin[1]+p.y);
      rect={x:Math.min(...xs),y:Math.min(...ys),width:Math.max(...xs)-Math.min(...xs),height:Math.max(...ys)-Math.min(...ys)};
    }
    return {selector, name:c.animationName, duration:c.animationDuration, delay:c.animationDelay,
      iterations:c.animationIterationCount, playState:c.animationPlayState, opacity:c.opacity,
      transform:c.transform, color:c.color, pointerEvents:c.pointerEvents, rect};
  };
  window.__motionInspect = () => {
    const node=document.querySelector('.connection-emblem');
    const boxes={};for(const selector of %BOXES%) {const item=document.querySelector(selector);if(item) boxes[selector]=box(item);}
    const animations=node?.getAnimations({subtree:true}) || [];
    const sidebar=document.querySelector('.sidebar');
    const main=document.querySelector('main'), card=document.querySelector('.connection-context');
    return {t:performance.now(),boxes,motion:node?.dataset.motion,bodyTransform:node?getComputedStyle(node).transform:null,
      svgTransform:node?.querySelector('svg')?getComputedStyle(node.querySelector('svg')).transform:null,
      loops:animations.filter(isLoop).map(describe),finite:animations.filter(a=>!isLoop(a)).map(describe),
      totalRipples:document.getAnimations().filter(a=>a.animationName==='connection-ripple').length,
      sidebarLoops:sidebar?.getAnimations({subtree:true}).filter(isLoop).map(describe) || [],
      pseudos:node?['::before','::after'].map(p=>decoration(node,p)):[],
      overflow:document.documentElement.scrollWidth>innerWidth+1 || Boolean(main&&main.scrollWidth>main.clientWidth+1) || Boolean(card&&card.scrollWidth>card.clientWidth+1)};
  };
  window.__motionSample = duration => new Promise(resolve => {
    const start=performance.now(),frames=[];
    function frame() {frames.push(window.__motionInspect());if(performance.now()-start<duration) requestAnimationFrame(frame);else resolve(frames);}
    requestAnimationFrame(frame);
  });
})();""".replace('%BOXES%', json.dumps(BOXES))


def origin_key(url):
    value = urlsplit(url)
    return value.scheme, value.hostname, value.port or (443 if value.scheme == 'https' else 80)


def static_request_allowed(base, url, method, resource):
    """Exact origin, GET, preview entry or typed build assets; never API traffic."""
    target, entry = urlsplit(url), urlsplit(base)
    if target.username or target.password or origin_key(base) != origin_key(url) or method != 'GET':
        return False
    if resource == 'document':
        return target.path == (entry.path or '/')
    if target.path == '/favicon.svg' and not target.query and not target.fragment:
        return resource in ('image', 'other')
    if not target.path.startswith('/assets/') or target.query or target.fragment or '..' in target.path:
        return False
    extensions = {'script': ('.js', '.mjs'), 'stylesheet': ('.css',), 'font': ('.woff', '.woff2', '.ttf', '.otf'),
                  'image': ('.png', '.jpg', '.jpeg', '.webp', '.svg', '.gif', '.ico')}
    return target.path.endswith(extensions.get(resource, ('\0',)))


def page_url(base, theme='light', accent='blue'):
    value = urlsplit(base)
    params = dict(parse_qsl(value.query))
    params.update(theme=theme, accent=accent)
    return urlunsplit((value.scheme, value.netloc, value.path or '/', urlencode(params), ''))


def stable(frames, label):
    assert len(frames) >= 5, (label, 'too few rAF observations', len(frames))
    for selector in BOXES:
        assert all(selector in frame['boxes'] for frame in frames), (label, selector, 'missing')
        for key in ('x', 'y', 'width', 'height'):
            values = [frame['boxes'][selector][key] for frame in frames]
            assert max(values) - min(values) <= .15, (label, selector, key, min(values), max(values))
    assert not any(frame['overflow'] or frame['sidebarLoops'] for frame in frames), (label, 'overflow/sidebar loop')
    for frame in frames:
        assert frame['bodyTransform'] in ('none', 'matrix(1, 0, 0, 1, 0, 0)'), (label, 'emblem transforms')
        assert frame['svgTransform'] in ('none', 'matrix(1, 0, 0, 1, 0, 0)'), (label, 'SVG transforms')
        title = frame['boxes']['.state-copy h2']
        for ring in frame['pseudos']:
            rect = ring['rect']
            if ring['name'] == 'connection-ripple':
                assert ring['pointerEvents'] == 'none', (label, 'decorative ring intercepts pointer')
            if rect and float(ring['opacity']) > .001:
                overlap = (min(rect['x'] + rect['width'], title['x'] + title['width']) - max(rect['x'], title['x']) > .2 and
                           min(rect['y'] + rect['height'], title['y'] + title['height']) - max(rect['y'], title['y']) > .2)
                assert not overlap, (label, 'ring covers title', rect, title)


def progressing(frames, label, previous=None):
    stable(frames, label)
    first, last = frames[0], frames[-1]
    assert all(len(frame['loops']) == frame['totalRipples'] == 2 for frame in frames), (label, 'expected exactly two loops')
    ids = [item['id'] for item in first['loops']]
    assert len(set(ids)) == 2
    for frame in frames:
        assert [item['id'] for item in frame['loops']] == ids, (label, 'loop recreated')
        for animation in frame['loops']:
            assert animation['name'] == 'connection-ripple' and animation['iterations'] == 'infinite'
            assert animation['target'] == 'emblem' and animation['state'] == 'running', (label, animation)
            assert animation['pseudo'] in ('::before', '::after'), (label, 'infinite animation is not a pseudo-element', animation)
            assert abs(animation['duration'] - 2800) <= 1, (label, animation)
    assert {item['pseudo'] for item in first['loops']} == {'::before', '::after'}
    assert abs(abs(first['loops'][0]['delay'] - first['loops'][1]['delay']) - 1400) <= 1, (label, 'wrong stagger')
    elapsed = last['t'] - first['t']
    for index in range(2):
        times = [frame['loops'][index]['currentTime'] for frame in frames]
        assert all(isinstance(value, (int, float)) for value in times)
        assert all(b >= a - .1 for a, b in zip(times, times[1:])), (label, 'time reset')
        assert times[-1] - times[0] >= elapsed * .65, (label, 'loop does not advance')
        phases = {(frame['pseudos'][index]['opacity'], frame['pseudos'][index]['transform']) for frame in frames}
        assert len(phases) >= 3, (label, 'opacity/scale phase did not change')
    if previous:
        before = {item['id']: item for item in previous['loops']}
        assert set(before) == set(ids), (label, 'same-state/busy/lifecycle replaced animation')
        for item in first['loops']:
            assert item['currentTime'] >= before[item['id']]['currentTime'] - 1, (label, 'loop restarted')
            if before[item['id']]['state'] == 'running':
                assert item['startTime'] == before[item['id']]['startTime'], (label, 'timeline restarted')


def frozen(frames, label, *, absent=False):
    stable(frames, label)
    assert all(not frame['sidebarLoops'] for frame in frames)
    if absent:
        assert all(not frame['loops'] and frame['totalRipples'] == 0 for frame in frames), (label, 'unexpected loop')
    first = frames[0]
    for frame in frames:
        assert [a['id'] for a in frame['loops']] == [a['id'] for a in first['loops']], (label, 'static animation recreated')
        for index, animation in enumerate(frame['loops']):
            assert animation['state'] != 'running', (label, 'animation still running')
            assert abs(animation['currentTime'] - first['loops'][index]['currentTime']) <= 1, (label, 'paused time advanced')
        assert [(p['opacity'], p['transform']) for p in frame['pseudos']] == [(p['opacity'], p['transform']) for p in first['pseudos']], (label, 'static phase changed')


class Regression:
    def __init__(self, args):
        self.args = args
        self.report = {'ok': False, 'mode': 'offline-mocked-native', 'real_ipc': False, 'real_portal': False,
                       'real_authentication': False, 'real_os_minimize_tested': False,
                       'visibility_note': 'Synthetic document.visibilityState override + visibilitychange, not real OS minimization.',
                       'checks': [], 'samples': [], 'palettes': [], 'artifacts': [], 'blocked_requests': [],
                       'page_errors': [], 'console_errors': [], 'unexpected_ipc': [], 'forbidden_transports': []}
        self.contexts = []

    def context(self, browser, *, reduced='no-preference'):
        options = {'viewport': {'width': 1000, 'height': 720}, 'reduced_motion': reduced, 'service_workers': 'block'}
        context = browser.new_context(**options)
        self.contexts.append(context)
        context.add_init_script(NETWORK_GUARD + NATIVE + OBSERVER)

        def guard(route):
            request = route.request
            if static_request_allowed(self.args.url, request.url, request.method, request.resource_type):
                route.continue_()
            else:
                address = urlsplit(request.url)
                self.report['blocked_requests'].append({'origin': f'{address.scheme}://{address.netloc}',
                                                        'type': request.resource_type, 'method': request.method})
                route.abort()
        context.route('**/*', guard)
        assert hasattr(context, 'route_web_socket'), 'Playwright >=1.48 required for WebSocket fail-closed routing'

        def block_socket(socket):
            self.report['blocked_requests'].append({'type': 'websocket'})
            socket.close()
        context.route_web_socket('**/*', block_socket)
        page = context.new_page()
        page.on('pageerror', lambda error: self.report['page_errors'].append(str(error)))
        page.on('console', lambda item: self.report['console_errors'].append(item.text) if item.type == 'error' else None)
        page.set_default_timeout(8000)
        return context, page

    def collect(self, context):
        try:
            for page in context.pages:
                if not page.is_closed():
                    self.report['unexpected_ipc'].extend(page.evaluate('window.__aboutUnexpected || []'))
                    self.report['forbidden_transports'].extend(page.evaluate('window.__motionForbidden || []'))
                    # Opaque about:blank origins intentionally have no Web Storage.
                    if urlsplit(page.url).scheme in ('http', 'https'):
                        assert page.evaluate('localStorage.length + sessionStorage.length') == 0, 'unexpected persistence'
        finally:
            context.close()
            self.contexts.remove(context)

    def sample(self, page, label, duration=360):
        frames = page.evaluate('duration => window.__motionSample(duration)', duration)
        self.report['samples'].append({'name': label, 'frames': len(frames), 'elapsed_ms': frames[-1]['t'] - frames[0]['t'],
                                       'first': frames[0], 'last': frames[-1]})
        return frames

    def settled(self, page):
        page.wait_for_function("""() => !document.getAnimations().some(a => a.playState === 'running' && a.effect?.getTiming().iterations !== Infinity)""")
        page.evaluate('() => document.fonts.ready')
        page.evaluate('() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))')

    def load(self, page):
        page.goto(page_url(self.args.url))
        page.wait_for_load_state('networkidle')
        expect(page.locator(EMBLEM)).to_be_visible()
        expect(page.get_by_role('heading', name='校园网未连接', exact=True)).to_be_visible()
        self.settled(page)

    def state(self, page, value, *, feedback=True):
        page.evaluate('value => window.__connectionMotionFixture.state(value)', value)
        title = '校园网已连接' if value is True else '校园网未连接' if value is False else '连接状态未知'
        expect(page.get_by_role('heading', name=title, exact=True)).to_be_visible()
        expect(page.locator('.sidebar-status')).to_have_attribute('data-state', 'online' if value is True else 'offline' if value is False else 'unknown')
        if feedback:
            page.wait_for_function("""() => document.querySelector('.connection-emblem').getAnimations().some(a =>
                a.effect?.getTiming().iterations === 1 && a.effect?.getTiming().duration === 450 && a.playState === 'running')""")
            finite = page.evaluate('window.__motionInspect().finite')
            assert any(a['duration'] == 450 and a['iterations'] == 1 for a in finite)
            self.report['checks'].append('450ms-real-state-feedback:' + str(value))
        self.settled(page)

    def active(self, page):
        expect(page.locator(EMBLEM)).to_have_attribute('data-motion', 'running')
        page.wait_for_function("window.__motionInspect().loops.length === 2 && window.__motionInspect().loops.every(a => a.state === 'running')")

    def regular(self, browser):
        context, page = self.context(browser)
        self.load(page)
        frozen(self.sample(page, 'initial-offline'), 'initial-offline', absent=True)
        self.state(page, None)
        frozen(self.sample(page, 'unknown-not-online'), 'unknown-not-online', absent=True)
        expect(page.get_by_role('heading', name='校园网已连接', exact=True)).to_have_count(0)
        self.state(page, True)
        self.active(page)
        frames = self.sample(page, 'online-across-full-2.8s-cycle', 3100)
        progressing(frames, 'online-across-full-2.8s-cycle')
        before = frames[-1]
        page.evaluate('window.__connectionMotionFixture.same()')
        self.settled(page)
        frames = self.sample(page, 'identical-snapshot-does-not-restart')
        progressing(frames, 'identical-snapshot-does-not-restart', before)
        assert not any(frame['finite'] for frame in frames), 'identical state retriggered finite feedback'
        before = frames[-1]
        page.get_by_role('button', name='刷新状态', exact=True).click()
        page.wait_for_function('window.__connectionMotionFixture.active')
        frames = self.sample(page, 'read-only-query-busy', 400)
        progressing(frames, 'read-only-query-busy', before)
        assert not any(frame['finite'] for frame in frames), 'busy query retriggered finite state feedback'
        page.wait_for_function('!window.__connectionMotionFixture.active')
        frames = self.sample(page, 'read-only-query-complete')
        progressing(frames, 'read-only-query-complete', before)
        assert page.evaluate('window.__connectionMotionFixture.statusCalls') == 1
        self.report['checks'].append('same-snapshot-and-read-only-busy-query-preserve-loop-identity-and-phase')

        # Actual scrolling of shipped content, not a mocked IntersectionObserver.
        page.set_viewport_size({'width': 390, 'height': 400})
        self.settled(page)
        before = page.evaluate('window.__motionInspect()')
        self.report['scroll_owner'] = page.evaluate("""() => {
            const main = document.querySelector('main');
            const owner = ['auto','scroll'].includes(getComputedStyle(main).overflowY) && main.scrollHeight > main.clientHeight
                ? main : document.scrollingElement;
            if (!owner || owner.scrollHeight <= owner.clientHeight) throw new Error('narrow viewport must be scrollable');
            window.__motionScrollOwner = owner;
            owner.scrollTop = owner.scrollHeight;
            return owner === main ? 'main' : 'document';
        }""")
        expect(page.locator(EMBLEM)).to_have_attribute('data-motion', 'paused')
        page.wait_for_timeout(80)  # Allow the browser to commit the pending CSS pause time.
        frozen(self.sample(page, 'scrolled-offscreen-pauses'), 'scrolled-offscreen-pauses')
        page.evaluate('window.__motionScrollOwner.scrollTop = 0')
        self.active(page)
        frames = self.sample(page, 'scroll-restore-continues')
        progressing(frames, 'scroll-restore-continues', {**before, 'loops': [{**a, 'state': 'paused'} for a in before['loops']]})
        page.set_viewport_size({'width': 1000, 'height': 720})
        self.settled(page)

        before = page.evaluate('window.__motionInspect()')
        page.evaluate("""() => {
            Object.defineProperty(document,'visibilityState',{configurable:true,get:()=> 'hidden'});
            Object.defineProperty(document,'hidden',{configurable:true,get:()=> true});
            document.dispatchEvent(new Event('visibilitychange'));
        }""")
        expect(page.locator(EMBLEM)).to_have_attribute('data-motion', 'paused')
        page.wait_for_timeout(80)
        frozen(self.sample(page, 'synthetic-document-hidden-pauses'), 'synthetic-document-hidden-pauses')
        page.evaluate("""() => {delete document.visibilityState;delete document.hidden;document.dispatchEvent(new Event('visibilitychange'));}""")
        self.active(page)
        progressing(self.sample(page, 'synthetic-visible-continues'), 'synthetic-visible-continues',
                    {**before, 'loops': [{**a, 'state': 'paused'} for a in before['loops']]})
        self.report['checks'].append('scroll-and-synthetic-document-visibility-pause-resume-without-restart')

        running_boxes = page.evaluate('window.__motionInspect().boxes')
        page.emulate_media(reduced_motion='reduce')
        page.evaluate('() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))')
        expect(page.locator(EMBLEM)).to_have_attribute('data-motion', 'paused')
        frames = self.sample(page, 'dynamic-reduced-motion-immediately-static')
        frozen(frames, 'dynamic-reduced-motion-immediately-static')
        assert frames[-1]['boxes'] == running_boxes, 'reduced-motion toggle changed connection geometry'
        page.emulate_media(reduced_motion='no-preference')
        self.active(page)
        progressing(self.sample(page, 'dynamic-motion-restored'), 'dynamic-motion-restored')

        page.evaluate('window.__motionDetached = []')
        for index in range(3):
            page.evaluate("""() => {const node=document.querySelector('.connection-emblem');window.__motionDetached.push({node,animations:node.getAnimations({subtree:true})});}""")
            page.get_by_role('button', name='设置', exact=True).click()
            expect(page.locator(EMBLEM)).to_have_count(0)
            assert page.evaluate("""() => window.__motionDetached.every(x => !x.node.isConnected &&
                x.node.dataset.motion === undefined && x.animations.every(a=>a.playState!=='running')) &&
                document.getAnimations().filter(a=>a.animationName==='connection-ripple').length===0"""), 'detached action/animations survived'
            page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
            assert page.evaluate('window.__motionDetached.every(x => x.node.dataset.motion === undefined)'), 'destroyed listener updated detached node'
            page.get_by_role('button', name='连接', exact=True).click()
            self.settled(page)
            self.active(page)
            assert page.evaluate("window.__motionDetached.every(x => x.node !== document.querySelector('.connection-emblem'))")
            progressing(self.sample(page, f'page-remount-{index + 1}'), f'page-remount-{index + 1}')
        self.report['checks'].append('three-page-destroy-remount-cycles-without-stacked-loops')
        self.palettes(page)
        self.state(page, False)
        frozen(self.sample(page, 'online-to-offline-removes-loops'), 'online-to-offline-removes-loops', absent=True)
        self.state(page, None)
        frozen(self.sample(page, 'final-unknown-no-loop'), 'final-unknown-no-loop', absent=True)
        self.collect(context)

    def palettes(self, page):
        baselines = {}
        for theme in ('light', 'dark'):
            for accent in ACCENTS:
                page.evaluate('([theme,accent]) => window.__connectionMotionFixture.prefs(theme,accent)', [theme, accent])
                expect(page.locator('html')).to_have_attribute('data-theme', theme)
                expect(page.locator('html')).to_have_attribute('data-accent', accent)
                for width in (320, 390, 700, 1000):
                    page.set_viewport_size({'width': width, 'height': 844 if width < 700 else 720})
                    page.locator('main').evaluate('el=>el.scrollTop=0')
                    self.settled(page)
                    self.active(page)
                    expect(page.get_by_role('heading', name='校园网已连接', exact=True)).to_be_visible()
                    name = f'{theme}-{accent}-{width}'
                    # Cover every phase at each width once; other palettes reuse
                    # the same geometry while checking the live semantic color.
                    frames = self.sample(page, name, 3000 if theme == 'light' and accent == 'blue' else 240)
                    progressing(frames, name)
                    box = frames[-1]['boxes'][EMBLEM]
                    expected = 40 if width <= 880 else 44
                    assert abs(box['width'] - expected) <= .1 and abs(box['height'] - expected) <= .1, (name, box)
                    palette = page.evaluate("""() => {
                        const node=document.querySelector('.connection-emblem'), probe=document.createElement('span');
                        probe.style.color='var(--success)';document.body.append(probe);const success=getComputedStyle(probe).color;probe.remove();
                        return {emblem:getComputedStyle(node).color,svg:getComputedStyle(node.querySelector('svg')).color,
                          sidebar:getComputedStyle(document.querySelector('.sidebar-status')).color,success};
                    }""")
                    assert all(palette[key] == palette['success'] for key in ('emblem', 'svg', 'sidebar')), (name, palette)
                    channels = [float(n) for n in re.findall(r'[\d.]+', palette['success'])][:3]
                    assert len(channels) == 3 and channels[1] > channels[0] and channels[1] > channels[2], (name, 'not semantic green')
                    baselines.setdefault((theme, width), frames[-1]['boxes'])
                    assert frames[-1]['boxes'] == baselines[(theme, width)], (name, 'accent changed geometry')
                    self.report['palettes'].append({'theme': theme, 'accent': accent, 'width': width,
                                                     'semantic_green': True, 'no_overflow_or_title_overlap': True,
                                                     'stable_raf_frames': len(frames)})
                if accent == 'blue':
                    path = self.args.output / f'online-{theme}-1000.png'
                    page.screenshot(path=str(path), animations='allow')
                    self.report['artifacts'].append(path.name)
        self.report['checks'].append('light-dark-six-accents-four-widths-semantic-green-and-stable-geometry')

    def reduced_default(self, browser):
        context, page = self.context(browser, reduced='reduce')
        self.load(page)
        self.state(page, True, feedback=False)
        expect(page.locator(EMBLEM)).to_have_attribute('data-motion', 'paused')
        frozen(self.sample(page, 'default-reduced-motion-online-static'), 'default-reduced-motion-online-static')
        assert not page.evaluate('window.__motionInspect().finite'), 'reduced motion retained finite feedback'
        page.get_by_role('button', name='设置', exact=True).click()
        page.get_by_role('button', name='连接', exact=True).click()
        self.settled(page)
        frozen(self.sample(page, 'default-reduced-motion-remount-static'), 'default-reduced-motion-remount-static')
        self.report['checks'].append('initial-reduced-motion-and-remount-are-static')
        self.collect(context)

    def evidence(self, browser):
        # Use the installed system encoder, not Playwright's optional downloaded
        # ffmpeg. Frame bytes come from this fixed-data page, never user images.
        encoder = shutil.which('ffmpeg')
        assert encoder, 'System ffmpeg is required for the short local WebM preview'
        context, page = self.context(browser)
        self.load(page)
        self.state(page, True)
        self.active(page)
        fps, count, chunks, times = 12, 48, [], []
        start = time.monotonic()
        card = page.locator('.connection-context').bounding_box()
        for index in range(count):
            remaining = start + index / fps - time.monotonic()
            if remaining > 0:
                page.wait_for_timeout(remaining * 1000)
            phase = page.evaluate('window.__motionInspect()')
            image = page.screenshot(clip=card, animations='allow', type='png')
            chunks.append(image)
            times.append({'t_ms': phase['t'], 'loop_times_ms': [a['currentTime'] for a in phase['loops']]})
            if index in (0, 8, 16, 24, 32, 40):
                path = self.args.output / f'online-light-ring-keyframe-{index // 8 + 1}.png'
                path.write_bytes(image)
                self.report['artifacts'].append({'path': path.name, **times[-1], 'pseudos': phase['pseudos']})
        progressing(self.sample(page, 'recorded-online-live-frames', 500), 'recorded-online-live-frames')
        path = self.args.output / 'online-light-ripple.webm'
        subprocess.run([encoder, '-hide_banner', '-loglevel', 'error', '-nostdin', '-y',
                        '-protocol_whitelist', 'file,pipe', '-f', 'image2pipe', '-framerate', str(fps),
                        '-i', 'pipe:0', '-an', '-c:v', 'libvpx-vp9', '-b:v', '0', '-crf', '32',
                        '-vf', 'pad=ceil(iw/2)*2:ceil(ih/2)*2', '-pix_fmt', 'yuv420p', str(path)],
                       input=b''.join(chunks), check=True, timeout=30)
        self.report['artifacts'].append({'path': path.name, 'method': 'live-browser-PNG-frames-to-local-WebM',
                                         'fps': fps, 'source_frames': times})
        self.collect(context)

    def fixture_smoke(self, browser):
        context, page = self.context(browser)
        page.goto('about:blank')
        assert page.evaluate("window.__TAURI_INTERNALS__.invoke('core_request',{command:'snapshot'})").get('status') == {
            'online': False, 'service': None, 'user': '', 'ip': '', 'message': ''}
        page.evaluate("""async () => {
            const handler=window.__TAURI_INTERNALS__.transformCallback(event=>window.__motionSmokeSnapshot=event.payload.payload);
            await window.__TAURI_INTERNALS__.invoke('plugin:event|listen',{event:'core-event',handler});
            window.__connectionMotionFixture.state(true);
        }""")
        assert page.evaluate('window.__motionSmokeSnapshot.status.online') is True
        page.evaluate("window.__TAURI_INTERNALS__.invoke('core_request',{command:'action',args:{name:'status'}})")
        assert page.evaluate('window.__motionSmokeSnapshot.busy') is True
        page.wait_for_function('!window.__connectionMotionFixture.active')
        assert page.evaluate('window.__motionSmokeSnapshot.busy') is False
        # Smoke only the observation helpers against deliberately synthetic HTML.
        # This is NOT a substitute for the parent's real application regression.
        page.set_content('''<style>
            .connection-emblem{position:relative;width:44px;height:44px;color:green;}
            .connection-emblem svg{width:24px;height:24px;}
            .connection-emblem::before,.connection-emblem::after{content:"";position:absolute;inset:0;border:1px solid green;border-radius:50%;pointer-events:none;animation:connection-ripple 2.8s linear infinite;}
            .connection-emblem::after{animation-delay:-1.4s;}
            @keyframes connection-ripple{from{opacity:.3;transform:scale(1)}to{opacity:0;transform:scale(1.1)}}
            </style><header class="page-header"><h1>夹具</h1></header><main><div class="connection-overview"><div class="connection-context">
            <div class="connection-emblem" data-motion="running"><svg></svg></div><div class="state-copy"><h2>离线假数据</h2></div></div></div></main><aside class="sidebar"></aside>''')
        page.evaluate(OBSERVER)
        progressing(self.sample(page, 'synthetic-observer-smoke', 260), 'synthetic-observer-smoke')
        self.report['checks'].append('about-blank-fixture-event-query-and-animation-observer-smoke-only')
        # Deliberately test a forbidden native command and verify it fails closed.
        assert page.evaluate("""async () => {try {await window.__TAURI_INTERNALS__.invoke('project_open_link',{target:'repository'});return false;}catch{return true;}}""")
        assert page.evaluate('window.__aboutUnexpected') == ['project_open_link']
        page.evaluate('window.__aboutUnexpected.length=0')
        self.collect(context)

    def run(self):
        try:
            with sync_playwright() as tool:
                browser = tool.chromium.launch(headless=True, executable_path=self.args.browser)
                try:
                    if self.args.fixture_smoke:
                        self.fixture_smoke(browser)
                    else:
                        self.regular(browser)
                        self.reduced_default(browser)
                        self.evidence(browser)
                    for key in ('blocked_requests', 'page_errors', 'console_errors', 'unexpected_ipc', 'forbidden_transports'):
                        assert not self.report[key], (key, self.report[key])
                    self.report['ok'] = True
                finally:
                    # Cleanup diagnostics must not overwrite the original assertion/navigation failure.
                    original_error = sys.exc_info()[0] is not None
                    for context in list(self.contexts):
                        try:
                            self.collect(context)
                        except Exception as cleanup_error:
                            if not original_error:
                                raise
                            self.report.setdefault('cleanup_errors', []).append(str(cleanup_error))
                    browser.close()
        except Exception as error:
            self.report['ok'] = False
            self.report['failure'] = str(error)
            raise
        finally:
            path = self.args.output / ('fixture-smoke-report.json' if self.args.fixture_smoke else 'connection-motion-report.json')
            path.write_text(json.dumps(self.report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            print(json.dumps({'ok': self.report['ok'], 'report': str(path), 'checks': self.report['checks']}, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--url', default='http://127.0.0.1:1423/', help='Existing production preview; never starts/builds it')
    parser.add_argument('--browser', default='/usr/bin/google-chrome', help='Installed Chromium executable')
    parser.add_argument('--output', type=Path, default=ROOT / 'build/connection-motion-20261025', help='Artifacts under the authorized build/dist connection-motion-20261025 tree')
    parser.add_argument('--fixture-smoke', action='store_true', help='about:blank fixture/observer smoke only; no app or HTTP request')
    args = parser.parse_args()
    origin = urlsplit(args.url)
    assert origin.scheme in ('http', 'https') and origin.hostname in ('127.0.0.1', 'localhost', '::1')
    assert not origin.username and not origin.password and not origin.fragment
    assert not dict(parse_qsl(origin.query)).get('demo'), 'Use base preview URL, not demo mode'
    args.output = args.output.resolve()
    roots = [ROOT / kind / 'connection-motion-20261025' for kind in ('build', 'dist')]
    assert any(args.output.is_relative_to(root.resolve()) for root in roots), 'Output must stay inside authorized build/dist connection-motion-20261025/'
    args.output.mkdir(parents=True, exist_ok=True)
    # Pure policy checks; these never issue requests, even intentionally blocked ones.
    assert static_request_allowed(args.url, page_url(args.url), 'GET', 'document')
    same = urlunsplit((origin.scheme, origin.netloc, '/favicon.svg', '', ''))
    assert static_request_allowed(args.url, same, 'GET', 'other')
    assert not static_request_allowed(args.url, same + '?not-static=1', 'GET', 'other')
    for resource in ('fetch', 'xhr', 'websocket', 'eventsource', 'other'):
        assert not static_request_allowed(args.url, page_url(args.url), 'GET', resource)
    assert not static_request_allowed(args.url, same, 'POST', 'image')
    assert not static_request_allowed(args.url, 'http://127.0.0.1:9/favicon.svg', 'GET', 'image')
    assert not static_request_allowed(args.url, 'https://portal.invalid/favicon.svg', 'GET', 'image')
    Regression(args).run()


if __name__ == '__main__':
    main()
