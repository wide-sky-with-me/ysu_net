"""Exercise accent selection against the built, isolated desktop demo."""
import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright
from clean_desktop_preview import contrast
from flclash_desktop_preview import channels, color_hex

OPTIONS = [
    ('teal', '松石青', '#007b6b', '#0bd8b6'),
    ('blue', '海蓝', '#0969c3', '#70b8ff'),
    ('indigo', '靛蓝', '#3e63dd', '#9eb1ff'),
    ('violet', '紫罗兰', '#6e56cf', '#baa7ff'),
    ('rose', '玫瑰', '#cb1d63', '#ff92ad'),
    ('amber', '琥珀', '#a05c00', '#ffca16'),
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', default='http://127.0.0.1:1423/')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    assert urlsplit(args.url).hostname in ('127.0.0.1', 'localhost')
    args.output.mkdir(parents=True, exist_ok=True)
    checks, errors, external = [], [], []

    def record(name, ok, **data):
        checks.append({'name': name, 'ok': bool(ok), **data})

    with sync_playwright() as tool:
        browser = tool.chromium.launch(headless=True, executable_path='/usr/bin/google-chrome')
        context = browser.new_context(viewport={'width': 1000, 'height': 720}, reduced_motion='reduce', color_scheme='light')
        context.route('**/*', lambda route: route.continue_() if urlsplit(route.request.url).hostname in ('localhost', '127.0.0.1') else (external.append(route.request.url), route.abort()))
        page = context.new_page()
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('console', lambda message: errors.append(message.text) if message.type == 'error' else None)
        root = page.locator('html')

        def open_settings(query):
            page.goto(args.url + query)
            page.wait_for_load_state('networkidle')
            page.evaluate('document.fonts.ready')
            page.get_by_role('button', name='设置', exact=True).click()
            page.get_by_role('tab', name='外观与启动', exact=True).click()
            expect(page.get_by_role('group', name='主题色', exact=True)).to_be_visible()

        def tokens():
            return root.evaluate('node=>Object.fromEntries(["accent","success","warning","danger"].map(key=>[key,getComputedStyle(node).getPropertyValue("--"+key).trim()]))')

        try:
            for theme in ('light', 'dark'):
                open_settings(f'?demo=1&theme={theme}')
                group = page.get_by_role('group', name='主题色', exact=True)
                expect(group.get_by_role('button')).to_have_count(6)
                neutral_keys = ['canvas', 'surface', 'surface-raised', 'field', 'sidebar', 'text', 'muted', 'border', 'control-border', 'idle', 'hover', 'backdrop']
                original_neutrals = root.evaluate('(node,keys)=>Object.fromEntries(keys.map(key=>[key,getComputedStyle(node).getPropertyValue("--"+key).trim()]))', neutral_keys)
                original_semantics = {key: value for key, value in tokens().items() if key != 'accent'}
                for value, name, light, dark in OPTIONS:
                    button = group.get_by_role('button', name=name, exact=True)
                    button.click()
                    expect(root).to_have_attribute('data-accent', value)
                    expect(root).to_have_attribute('data-theme', theme)
                    expect(button).to_have_attribute('aria-pressed', 'true')
                    record(f'{theme}-{value}-one-selection', group.locator('[aria-pressed="true"]').count() == 1 and group.locator('.accent-swatch svg').count() == 1)
                    actual = tokens()
                    record(f'{theme}-{value}-color-applied', actual['accent'] == (dark if theme == 'dark' else light), actual=actual['accent'])
                    record(f'{theme}-{value}-semantic-colors-kept', {key: color for key, color in actual.items() if key != 'accent'} == original_semantics)
                    neutrals = root.evaluate('(node,keys)=>Object.fromEntries(keys.map(key=>[key,getComputedStyle(node).getPropertyValue("--"+key).trim()]))', neutral_keys)
                    record(f'{theme}-{value}-neutral-shell-kept', neutrals == original_neutrals)
                    record(f'{theme}-{value}-no-background-wash', page.locator('.workspace').evaluate('node=>getComputedStyle(node).backgroundImage.split(",").every(layer=>layer.trim()==="none")'))
                    toggle = page.locator('.toggle[aria-checked="true"]').first
                    knob, track = toggle.evaluate('node=>[getComputedStyle(node.querySelector(".toggle-knob")).backgroundColor,getComputedStyle(node).backgroundColor]')
                    ratio = contrast(color_hex(channels(knob)[0]), color_hex(channels(track)[0]))
                    record(f'{theme}-{value}-enabled-toggle-contrast', ratio >= 3, ratio=round(ratio, 3))
                    normal = button.evaluate('node=>({fg:getComputedStyle(node).color,bg:getComputedStyle(node).backgroundColor})')
                    button.hover()
                    record(f'{theme}-{value}-selected-hover', normal == button.evaluate('node=>({fg:getComputedStyle(node).color,bg:getComputedStyle(node).backgroundColor})'))
                    for swatch in group.locator('.accent-swatch').all():
                        fg, bg = swatch.evaluate('node=>[getComputedStyle(node).backgroundColor,getComputedStyle(node.parentElement).backgroundColor]')
                        ratio = contrast(color_hex(channels(fg)[0]), color_hex(channels(bg)[0]))
                        record(f'{theme}-{value}-swatch-boundary', ratio >= 3, ratio=round(ratio, 3))
                    page.mouse.move(1, 1)
                    page.screenshot(path=str(args.output/f'settings-{value}-{theme}.png'), full_page=True)

                for width, height in ((1000, 720), (700, 560), (390, 844), (320, 740)):
                    page.set_viewport_size({'width': width, 'height': height})
                    record(f'{theme}-{width}-no-horizontal-overflow', page.evaluate('document.documentElement.scrollWidth<=innerWidth+1') and group.evaluate('node=>node.scrollWidth<=node.clientWidth+1'))
                    record(f'{theme}-{width}-readable-options', all(button.evaluate('node=>node.scrollWidth<=node.clientWidth+1 && node.getBoundingClientRect().height>=34') for button in group.get_by_role('button').all()))
                    page.screenshot(path=str(args.output/f'settings-{theme}-{width}.png'), full_page=True)
                page.set_viewport_size({'width': 1000, 'height': 720})

            open_settings('?demo=1&theme=dark&accent=violet')
            group = page.get_by_role('group', name='主题色', exact=True)
            group.get_by_role('button', name='海蓝', exact=True).focus()
            page.keyboard.press('Space')
            expect(root).to_have_attribute('data-accent', 'blue')
            record('keyboard-space-selects', group.get_by_role('button', name='海蓝', exact=True).get_attribute('aria-pressed') == 'true')
            page.get_by_role('group', name='外观', exact=True).get_by_role('button', name='系统', exact=True).click()
            page.emulate_media(color_scheme='light')
            expect(root).to_have_attribute('data-theme', 'light')
            page.emulate_media(color_scheme='dark')
            expect(root).to_have_attribute('data-theme', 'dark')
            record('follow-system-keeps-accent', root.get_attribute('data-accent') == 'blue')
            for destination in ('连接', '账户', '日志'):
                page.get_by_role('button', name=destination, exact=True).click()
                record(f'{destination}-keeps-accent', root.get_attribute('data-accent') == 'blue' and tokens()['accent'] == '#70b8ff')
            page.get_by_role('button', name='设置', exact=True).click()
            page.get_by_role('tab', name='外观与启动', exact=True).click()
            expect(group.get_by_role('button', name='海蓝', exact=True)).to_have_attribute('aria-pressed', 'true')
            page.emulate_media(forced_colors='active')
            selected = group.locator('[aria-pressed="true"]')
            record('forced-colors-selection', selected.evaluate('node=>getComputedStyle(node).color!==getComputedStyle(node).backgroundColor && getComputedStyle(node).forcedColorAdjust==="none"'))
            page.keyboard.press('Tab')
            selected.focus()
            expect(selected).to_be_focused()
            record('forced-colors-focus', selected.evaluate('node=>getComputedStyle(node).outlineStyle!=="none" && parseFloat(getComputedStyle(node).outlineWidth)>=2'))
            page.screenshot(path=str(args.output/'high-contrast.png'), full_page=True)
            page.emulate_media(forced_colors='none', color_scheme='light')

            open_settings('?demo=1&theme=light&accent=blue&scenario=prefs-failure')
            page.get_by_role('group', name='主题色', exact=True).get_by_role('button', name='玫瑰', exact=True).click()
            expect(page.get_by_role('alert')).to_contain_text('原设置已保留')
            record('failed-save-keeps-selection', root.get_attribute('data-accent') == 'blue' and page.get_by_role('button', name='海蓝', exact=True).get_attribute('aria-pressed') == 'true')
            page.screenshot(path=str(args.output/'failed-save.png'), full_page=True)
            for query, disabled in (('?demo=1&scenario=busy', True), ('?demo=1&scenario=external', False), ('', True)):
                open_settings(query)
                group = page.get_by_role('group', name='主题色', exact=True)
                record(f'controls-{query or "plain-web"}', all(button.is_disabled() == disabled for button in group.get_by_role('button').all()))
                if not disabled:
                    group.get_by_role('button', name='琥珀', exact=True).click()
                    expect(root).to_have_attribute('data-accent', 'amber')
            record('no-web-storage', page.evaluate('localStorage.length===0 && sessionStorage.length===0'))
        except Exception as error:
            errors.append(str(error))
            page.screenshot(path=str(args.output/'failure.png'), full_page=True)
        finally:
            version = browser.version
            browser.close()

    record('no-browser-errors', not errors)
    record('no-external-requests', not external)
    report = {'ok': all(row['ok'] for row in checks), 'mode': 'built-offline-demo', 'browser_version': version, 'real_authentication': False, 'checks': checks, 'page_errors': errors, 'external_requests': external, 'native_persistence_tested_here': False}
    (args.output/'accent-ui-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({'ok': report['ok'], 'passed': sum(row['ok'] for row in checks), 'total': len(checks), 'failed': [row for row in checks if not row['ok']], 'errors': errors}, ensure_ascii=False))
    raise SystemExit(0 if report['ok'] else 1)


if __name__ == '__main__':
    main()
