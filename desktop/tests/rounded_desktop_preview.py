"""Rounded desktop surfaces and real motion, using isolated offline demo data."""
import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:1421/')
    parser.add_argument('--browser', default='/usr/bin/google-chrome')
    parser.add_argument('--output', type=Path, default=Path('dist/rounded-desktop-preview'))
    args = parser.parse_args()
    assert urlsplit(args.url).hostname in ('127.0.0.1', 'localhost')
    args.output.mkdir(parents=True, exist_ok=True)
    errors, external, layouts, checks = [], [], [], []

    with sync_playwright() as tool:
        browser = tool.chromium.launch(headless=True, executable_path=args.browser)
        context = browser.new_context(viewport={'width': 1060, 'height': 800}, reduced_motion='no-preference')
        context.add_init_script('''window.__motionCalls = [];
            const animate = Element.prototype.animate;
            Element.prototype.animate = function(frames, options) {
                window.__motionCalls.push({target: this.className, duration: options?.duration});
                return animate.call(this, frames, options);
            };''')
        page = context.new_page()
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('console', lambda message: errors.append(message.text) if message.type == 'error' else None)
        context.route('**/*', lambda route: route.continue_()
                      if urlsplit(route.request.url).hostname in (None, '127.0.0.1', 'localhost')
                      else (external.append(route.request.url), route.abort()))

        def button(name):
            return page.get_by_role('button', name=name, exact=True)

        def visit(theme='light', accent=None, scenario=None):
            query = f'?demo=1&theme={theme}' + (f'&accent={accent}' if accent else '') + (f'&scenario={scenario}' if scenario else '')
            page.goto(args.url + query)
            page.wait_for_load_state('networkidle')

        def settle():
            page.wait_for_function("document.getAnimations().every(a => (a.effect.getComputedTiming().iterations === Infinity && (a.effect?.target?.matches?.('.quota-wave-layer') || (a.animationName === 'connection-ripple' && a.effect?.target?.matches?.('.connection-emblem')))) || (a.playState !== 'running' && a.playState !== 'pending'))")

        def layout(name):
            result = page.evaluate('''() => {
                const main = document.querySelector('main');
                const detailAlignment = [...document.querySelectorAll('.online-detail')].map((field, index) => {
                    const icon = field.querySelector('.online-field-symbol').getBoundingClientRect();
                    const heading = field.querySelector('dt').getBoundingClientRect();
                    const label = field.querySelector('dt > span:last-child').getBoundingClientRect();
                    const value = field.querySelector('dd').getBoundingClientRect();
                    return {index, labelValueOffset: Math.abs(label.left - value.left),
                        iconCenterOffset: Math.abs((icon.top + icon.bottom) / 2 - (heading.top + value.bottom) / 2),
                        iconTextGap: label.left - icon.right};
                });
                return {overflow: document.documentElement.scrollWidth > innerWidth,
                    mainOverflow: main.scrollWidth > main.clientWidth + 1,
                    detailAlignment,
                    radius: parseFloat(getComputedStyle(document.querySelector('.connection-context') || document.querySelector('.settings-section') || document.querySelector('.online-info-card')).borderRadius)};
            }''')
            assert not result['overflow'] and not result['mainOverflow'], result
            assert result['radius'] >= 24, result
            layouts.append(dict(name=name, **result))
            assert all(field['labelValueOffset'] <= 1 and field['iconCenterOffset'] <= 1 and field['iconTextGap'] >= 10
                       for field in result['detailAlignment']), result

        def status_colors(state):
            expect(page.locator('.sidebar-status')).to_have_attribute('data-state', state)
            colors = page.evaluate('''() => {
                const color = selector => getComputedStyle(document.querySelector(selector)).color;
                return {text: color('.sidebar-status-text'), marker: color('.sidebar-status-marker'), emblem: color('.connection-emblem')};
            }''')
            assert colors['text'] == colors['marker'] == colors['emblem'], colors
            rgb = [int(value) for value in colors['text'].replace('rgb(', '').replace(')', '').split(',')]
            assert (rgb[1] > rgb[0] and rgb[1] > rgb[2]) if state == 'online' else (rgb[0] > rgb[1] and rgb[0] > rgb[2]), colors

        visit()
        expect(page.locator('html')).to_have_attribute('data-accent', 'blue')
        expect(page.locator('.connection-security-warning')).to_have_count(0)
        expect(page.locator('.connection-context')).not_to_contain_text('HTTPS 证书校验已开启')
        expect(page.locator('.connection-context')).not_to_contain_text('API 认证')
        assert page.locator('.connection-details > div').first.evaluate('el => getComputedStyle(el).backgroundColor') == 'rgba(0, 0, 0, 0)'
        assert page.evaluate('window.__motionCalls.some(item => item.duration === 240)')
        page.screenshot(path=str(args.output / 'connection-light.png'))
        button('账户').click()
        settle()
        expect(page.locator('.online-identity dt')).to_have_text('账号')
        expect(page.locator('.online-identity dd')).to_have_text('20260001')
        expect(page.locator('.online-detail-list .online-detail')).to_have_count(2)
        expect(page.locator('.online-detail[data-kind="service"] dd')).to_have_text('中国移动')
        expect(page.locator('.online-detail[data-kind="address"] dd')).to_have_text('10.24.16.82')
        identity = page.locator('.online-identity').bounding_box()
        detail = page.locator('.online-detail-list').bounding_box()
        card = page.locator('.online-info-card').bounding_box()
        assert identity['y'] + identity['height'] <= detail['y'], (identity, detail)
        assert identity['height'] < 100 and identity['width'] >= card['width'] - 60, (identity, card)
        flow = page.locator('.account-summary dd.flow-accent')
        expect(flow).to_have_text('80.00 GB')
        assert flow.inner_text() == '80.00 GB'
        assert '80.00 GB' in flow.aria_snapshot()
        assert flow.locator('.animated-metric').count() == 1
        assert page.evaluate("window.__motionCalls.some(item => item.target === 'animated-metric' && item.duration === 450)")
        layout('account-light')
        page.screenshot(path=str(args.output / 'account-light.png'))
        checks.append('online-account-identity-and-raw-service-address-details')
        expect(page.locator('.account-summary')).not_to_contain_text('余额')
        expect(page.locator('.account-summary > dl > div')).to_have_count(2)
        expect(button('门户数据说明')).to_have_count(0)
        ambient = page.locator('.quota-ambient')
        expect(ambient).to_have_attribute('data-motion', 'running')
        wave = page.locator('.quota-wave-layer').first
        start_transform = wave.evaluate('el => getComputedStyle(el).transform')
        page.wait_for_function('(previous) => getComputedStyle(document.querySelector(".quota-wave-layer")).transform !== previous', arg=start_transform)
        expect(flow).to_have_text('80.00 GB')
        page.set_viewport_size({'width': 1060, 'height': 320})
        page.locator('main').evaluate('el => { el.scrollTop = el.scrollHeight; }')
        expect(ambient).to_have_attribute('data-motion', 'paused')
        page.set_viewport_size({'width': 1060, 'height': 800})
        page.locator('main').evaluate('el => { el.scrollTop = 0; }')
        expect(ambient).to_have_attribute('data-motion', 'running')
        checks.append('visible-quota-waves-no-invented-balance-and-offscreen-pause')

        # Status paints change only after the authoritative action, never on confirmation.
        visit()
        settle()
        status_colors('online')
        state_calls = lambda: page.evaluate("window.__motionCalls.filter(item => ['sidebar-status', 'connection-emblem'].includes(item.target)).length")
        before_state = state_calls()
        button('断开连接').click()
        expect(page.locator('.sidebar-status')).to_have_attribute('data-state', 'online')
        assert state_calls() == before_state
        page.get_by_role('dialog').get_by_role('button', name='断开连接', exact=True).click()
        expect(page.get_by_role('heading', name='校园网未连接', exact=True)).to_be_visible()
        settle()
        status_colors('offline')
        assert state_calls() > before_state
        page.screenshot(path=str(args.output / 'connection-offline.png'))
        same_value_calls = page.evaluate('window.__motionCalls.length')
        button('刷新状态').click()
        settle()
        assert page.evaluate('window.__motionCalls.length') == same_value_calls
        button('连接校园网').click()
        expect(page.get_by_role('heading', name='校园网已连接', exact=True)).to_be_visible()
        settle()
        status_colors('online')
        checks.append('green-online-red-offline-real-state-pulse-and-no-same-snapshot-replay')
        visit()
        # Route changes animate existing content; ordinary core snapshots do not replay it.
        before = page.evaluate('window.__motionCalls.length')
        button('设置').evaluate('element => element.click()')
        page.wait_for_function('window.__motionCalls.length > ' + str(before))
        expect(page.get_by_label('密码', exact=True)).to_be_visible()
        page.get_by_label('密码', exact=True).fill('discard-during-motion')
        button('连接').evaluate('element => element.click()')
        page.wait_for_function("document.querySelector('#account-password') === null")
        button('设置').click()
        expect(page.get_by_label('密码', exact=True)).to_have_value('')
        checks.append('normal-motion-navigation-never-delays-password-unmount')

        page.get_by_role('tab', name='外观与启动', exact=True).click()
        settle()
        page.screenshot(path=str(args.output / 'settings-light.png'))
        button('深色').click()
        expect(page.locator('html')).to_have_attribute('data-theme', 'dark')
        settle()
        page.screenshot(path=str(args.output / 'settings-dark.png'))
        button('日志').click()
        settle()
        page.screenshot(path=str(args.output / 'logs-dark.png'))

        visit()
        reconnect = page.get_by_role('switch', name='自动重连', exact=True)
        duration = reconnect.locator('.toggle-knob').evaluate('el => getComputedStyle(el).transitionDuration')
        assert any(float(value.strip().rstrip('s')) > 0 for value in duration.split(',')), duration
        reconnect.click()
        expect(reconnect).to_have_attribute('aria-checked', 'false')
        page.wait_for_function("Math.abs(new DOMMatrixReadOnly(getComputedStyle(document.querySelector('[aria-label=自动重连] .toggle-knob')).transform).m41) < 0.1")
        button('中国联通').click()
        expect(page.get_by_role('dialog')).to_be_visible()
        expect(page.get_by_role('dialog').get_by_role('button', name='取消', exact=True)).to_be_focused()
        assert page.get_by_role('dialog').evaluate("el => getComputedStyle(el).animationName") == 'dialog-in'
        settle()
        page.screenshot(path=str(args.output / 'confirmation.png'))
        page.keyboard.press('Escape')
        expect(page.get_by_role('dialog')).not_to_be_visible()
        expect(button('中国联通')).to_be_focused()
        checks.append('switch-knob-motion-and-native-dialog-focus')

        # Turning reduced motion on cancels Web Animations as well as CSS transitions.
        before = page.evaluate('window.__motionCalls.length')
        button('设置').evaluate('element => element.click()')
        page.wait_for_function('window.__motionCalls.length > ' + str(before))
        page.emulate_media(reduced_motion='reduce')
        settle()
        before = page.evaluate('window.__motionCalls.length')
        page.get_by_role('tab', name='外观与启动', exact=True).click()
        button('连接').click()
        assert page.evaluate('window.__motionCalls.length') == before
        assert page.locator('.toggle-knob').first.evaluate('el => getComputedStyle(el).transitionDuration') == '0s'
        expect(page.locator('.quota-status')).to_have_count(0)
        reconnect.click()
        page.get_by_role('switch', name='自动换号', exact=True).click()
        expect(page.locator('.quota-status')).to_contain_text('80.00 GB')
        button('断开连接').click()
        page.get_by_role('dialog').get_by_role('button', name='断开连接', exact=True).click()
        expect(page.locator('.sidebar-status')).to_have_attribute('data-state', 'offline')
        button('连接校园网').click()
        expect(page.locator('.sidebar-status')).to_have_attribute('data-state', 'online')
        assert page.evaluate('window.__motionCalls.length') == before
        checks.append('live-reduced-motion-cancels-and-prevents-page-state-and-digit-animation')

        # Changing a saved accent is reversible and must never recolor common surfaces.
        visit()
        button('设置').click()
        page.get_by_role('tab', name='外观与启动', exact=True).click()
        neutral = lambda: page.evaluate("['--canvas','--surface','--field','--text','--muted'].map(name => getComputedStyle(document.documentElement).getPropertyValue(name))")
        original_neutral = neutral()
        button('松石青').click()
        expect(page.locator('html')).to_have_attribute('data-accent', 'teal')
        assert neutral() == original_neutral
        assert page.locator('body').evaluate('el => getComputedStyle(el).backgroundColor') == 'rgb(245, 246, 248)'
        button('连接').click()
        page.screenshot(path=str(args.output / 'optional-teal.png'))
        button('设置').click()
        page.get_by_role('tab', name='外观与启动', exact=True).click()
        button('雾蓝').click()
        expect(page.locator('html')).to_have_attribute('data-accent', 'blue')
        assert neutral() == original_neutral
        assert page.locator('body').evaluate('el => getComputedStyle(el).backgroundColor') == 'rgb(245, 246, 248)'
        checks.append('blue-default-and-reversible-accent-with-neutral-surfaces')

        # Every color remains an accent, never a new state or invented network metric.
        for theme in ('light', 'dark'):
            for accent in ('teal', 'blue', 'indigo', 'violet', 'rose', 'amber'):
                visit(theme, accent)
                expect(page.get_by_role('heading', name='校园网已连接', exact=True)).to_be_visible()
                settle()
                status_colors('online')
                layout(theme + '-' + accent)
        for theme in ('light', 'dark'):
            for accent in ('blue', 'teal', 'indigo', 'violet', 'rose', 'amber'):
                page.goto(args.url + f'?demo=1&theme={theme}&accent={accent}&scenario=offline')
                page.wait_for_load_state('networkidle')
                status_colors('offline')
        page.goto(args.url + '?demo=1&scenario=unknown')
        page.wait_for_load_state('networkidle')
        expect(page.locator('.sidebar-status')).to_have_attribute('data-state', 'unknown')
        expect(page.get_by_role('heading', name='连接状态未知', exact=True)).to_be_visible()
        for theme in ('light', 'dark'):
            page.set_viewport_size({'width': 1600, 'height': 1000})
            page.goto(args.url + f'?demo=1&theme={theme}&accent=blue&scenario=online-details')
            page.wait_for_load_state('networkidle')
            expect(page.locator('.quota-status')).to_have_count(0)
            settle()
            page.screenshot(path=str(args.output / f'connection-compact-{theme}.png'))
            button('账户').click()
            settle()
            expect(page.locator('.online-detail')).to_have_count(4)
            expect(page.locator('.online-detail-list')).to_contain_text('演示用户')
            expect(page.locator('.online-detail-list')).to_contain_text('2001:db8::42')
            expect(page.locator('.online-detail-list')).to_contain_text('Campus Demo')
            expect(page.locator('.online-detail-list')).to_contain_text('中国移动')
            identity = page.locator('.online-identity').bounding_box()
            detail = page.locator('.online-detail-list').bounding_box()
            assert identity['height'] < 100 and identity['y'] + identity['height'] <= detail['y']
            layout('account-compact-' + theme)
            page.screenshot(path=str(args.output / f'account-compact-{theme}.png'))
        for width, height in ((700, 560), (390, 844), (320, 720)):
            page.set_viewport_size({'width': width, 'height': height})
            visit('dark', scenario='online-details')
            layout('connection-' + str(width))
            page.screenshot(path=str(args.output / f'compact-{width}.png'), full_page=True)
            page.get_by_role('switch', name='自动重连', exact=True).click()
            help_control = page.get_by_label('自动换号条件', exact=True)
            help_control.focus()
            page.keyboard.press('Enter')
            expect(page.locator('.rotation-help p')).to_be_visible()
            expect(page.locator('.rotation-help p')).to_contain_text('请先开启自动重连')
            help_box = page.locator('.rotation-help p').bounding_box()
            assert help_box['x'] >= 0 and help_box['x'] + help_box['width'] <= width, help_box
            layout('rotation-help-' + str(width))
            page.keyboard.press('Enter')
            expect(page.locator('.rotation-help p')).to_be_hidden()
            button('账户').click()
            layout('account-' + str(width))
            expect(page.locator('.online-identity dd')).to_have_text('20260001')
            expect(page.locator('.online-detail')).to_have_count(4)
            page.screenshot(path=str(args.output / f'account-{width}.png'), full_page=True)
            expect(page.locator('.quota-ambient')).to_have_attribute('data-motion', 'paused')
            expect(page.locator('.account-summary')).not_to_contain_text('余额')
            button('设置').click()
            for name in ('校园网账号', '外观与启动', '认证与重试', '环境诊断'):
                page.get_by_role('tab', name=name, exact=True).click()
                layout(name + '-' + str(width))
            if width > 520:
                page.get_by_role('tab', name='认证与重试', exact=True).click()
                button('保存参数').scroll_into_view_if_needed()
                expect(page.get_by_role('tab', name='认证与重试', exact=True)).to_be_visible()
                assert page.evaluate("document.querySelector('.settings-tabs').getBoundingClientRect().top - document.querySelector('main').getBoundingClientRect().top <= 12")
        checks.append('all-themes-accents-and-320-390-700-layouts')
        assert page.evaluate('localStorage.length + sessionStorage.length') == 0
        assert not errors, errors
        assert not external, external
        context.close()
        browser.close()

    report = {'ok': True, 'mode': 'offline-built-preview', 'real_authentication': False,
              'checks': checks, 'layouts': layouts, 'errors': errors, 'external_requests': external}
    (args.output / 'rounded-desktop-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
