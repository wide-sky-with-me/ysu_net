"""Check the compact sidebar footer against the built, offline desktop preview."""
import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright

from clean_desktop_preview import contrast


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:1423/')
    parser.add_argument('--output', type=Path, default=Path('dist/sidebar-footer-validation/after'))
    parser.add_argument('--baseline', action='store_true', help='Capture the existing layout without running interactions')
    args = parser.parse_args()
    assert urlsplit(args.url).hostname in ('localhost', '127.0.0.1')
    args.output.mkdir(parents=True, exist_ok=True)
    checks, errors, external = [], [], []

    def record(name, ok, **data):
        checks.append({'name': name, 'ok': bool(ok), **data})

    with sync_playwright() as tool:
        browser = tool.chromium.launch(headless=True, executable_path='/usr/bin/google-chrome')
        context = browser.new_context(reduced_motion='reduce')
        context.route('**/*', lambda route: route.continue_() if urlsplit(route.request.url).hostname in ('localhost', '127.0.0.1') else (external.append(route.request.url), route.abort()))
        page = context.new_page()
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('console', lambda message: errors.append(message.text) if message.type == 'error' else None)

        def visit(theme='light', scenario='', demo=True):
            query = f'?theme={theme}&scenario={scenario}' + ('&demo=1' if demo else '')
            page.goto(args.url + query)
            page.wait_for_load_state('networkidle')
            page.evaluate('document.fonts.ready.then(() => true)')
            expect(page.get_by_role('button', name='连接', exact=True)).to_be_visible()

        footer = page.locator('.sidebar-bottom')
        status = page.locator('.sidebar-status')
        doctor = page.get_by_role('button', name='环境诊断', exact=True)
        for theme in ('light', 'dark'):
            for width, height in ((1000, 720), (881, 560), (880, 560), (700, 560), (521, 560), (700, 480)):
                page.set_viewport_size({'width': width, 'height': height})
                visit(theme)
                prefix = f'{theme}-{width}-{height}'
                boxes = {name: node.bounding_box() for name, node in [('footer', footer), ('status', status), ('doctor', doctor)]}
                text = status.inner_text().strip()
                size = status.evaluate('node=>parseFloat(getComputedStyle(node).fontSize)')
                record(prefix + '-readable-status', text == '在线' and size >= 12, text=text, font_size=size)
                colors = page.evaluate('''() => ['.sidebar-status', '.sidebar'].map((selector,index) => {
                    const style=getComputedStyle(document.querySelector(selector));
                    const color=index ? style.backgroundColor : style.color;
                    return '#' + color.match(/\\d+/g).slice(0,3).map(value=>Number(value).toString(16).padStart(2,'0')).join('');
                })''')
                ratio = contrast(*colors)
                record(prefix + '-text-contrast', ratio >= 4.5, ratio=round(ratio, 3), colors=colors)
                record(prefix + '-no-version-clutter', footer.locator('.version').count() == 0)
                record(prefix + '-icon-only-diagnostics', doctor.locator('svg').count() == 1 and not doctor.inner_text().strip())
                record(prefix + '-accessible-status', status.get_attribute('role') == 'status' and status.get_attribute('aria-label') == '网络在线')
                record(prefix + '-reachable', all(box and box['y'] >= 0 and box['y'] + box['height'] <= height for box in boxes.values()), boxes=boxes)
                record(prefix + '-no-overflow', page.evaluate('document.documentElement.scrollWidth<=innerWidth') and footer.evaluate('node=>node.scrollWidth<=node.clientWidth'))
                if width > 880:
                    aligned = abs(boxes['status']['y'] + boxes['status']['height']/2 - boxes['doctor']['y'] - boxes['doctor']['height']/2) <= 1
                    record(prefix + '-one-row', aligned and boxes['footer']['height'] <= 52, boxes=boxes)
                else:
                    centered = abs(boxes['status']['x'] + boxes['status']['width']/2 - boxes['doctor']['x'] - boxes['doctor']['width']/2) <= 1
                    record(prefix + '-compact-stack', centered and boxes['footer']['height'] <= 82, boxes=boxes)
                page.screenshot(path=str(args.output / f'{prefix}.png'))

        if not args.baseline:
            page.set_viewport_size({'width': 700, 'height': 560})
            for scenario, label, text, tone in [('', '网络在线', '在线', 'online'), ('offline', '网络离线', '离线', 'offline'), ('unknown', '状态未知', '未知', 'unknown')]:
                visit(scenario=scenario)
                record(f'state-{scenario or "online"}', status.inner_text().strip() == text and status.get_attribute('aria-label') == label and status.locator('.status-dot').evaluate('(node,tone)=>node.classList.contains(tone)', tone))
            visit(demo=False)
            record('web-is-not-offline', status.inner_text().strip() == '待核心' and status.get_attribute('aria-label') == '未连接核心' and doctor.is_disabled())
            for scenario, disabled in [('busy', True), ('external', False)]:
                visit(scenario=scenario)
                record(f'{scenario}-diagnostic-lock', doctor.is_disabled() == disabled)

            visit()
            page.get_by_role('button', name='日志', exact=True).focus()
            page.keyboard.press('Tab')
            expect(doctor).to_be_focused()
            record('keyboard-focus', doctor.evaluate('node=>node.matches(":focus-visible") && parseFloat(getComputedStyle(node).outlineWidth)>=2'))
            page.keyboard.press('Enter')
            expect(page.locator('#diagnostic-result-heading')).to_be_focused()
            expect(page.locator('.diagnostic-output')).to_contain_text('Rust')
            record('diagnostic-action-and-focus', True)
            record('version-still-in-diagnostics', '0.1.0' in page.locator('.environment-list').inner_text())

            for theme in ('light', 'dark'):
                page.emulate_media(forced_colors='active')
                visit(theme)
                page.get_by_role('button', name='日志', exact=True).focus()
                page.keyboard.press('Tab')
                expect(doctor).to_be_focused()
                record(f'{theme}-forced-colors-focus', doctor.evaluate('node=>node.matches(":focus-visible") && getComputedStyle(node).outlineStyle!=="none" && parseFloat(getComputedStyle(node).outlineWidth)>=2'))
                record(f'{theme}-forced-colors-text', status.inner_text().strip() == '在线')
                page.screenshot(path=str(args.output / f'{theme}-forced-colors.png'))
            page.emulate_media(forced_colors='none')

            for width in (520, 390, 320):
                page.set_viewport_size({'width': width, 'height': 790})
                visit()
                record(f'mobile-{width}-footer-hidden', not footer.is_visible())
                page.get_by_role('button', name='设置', exact=True).click()
                page.get_by_role('tab', name='环境诊断', exact=True).click()
                page.get_by_role('button', name='运行本地诊断', exact=True).click()
                expect(page.locator('#diagnostic-result-heading')).to_be_focused()
                record(f'mobile-{width}-diagnostics-retained', page.locator('.diagnostic-result').is_visible())
            record('no-browser-storage', page.evaluate('localStorage.length===0 && sessionStorage.length===0'))
        record('no-runtime-errors', not errors, errors=errors)
        record('no-external-requests', not external, external_requests=external)
        context.close()
        browser.close()

    report = {'ok': all(row['ok'] for row in checks), 'baseline': args.baseline, 'checks': checks}
    (args.output / 'sidebar-footer-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'ok': report['ok'], 'passed': sum(row['ok'] for row in checks), 'total': len(checks), 'failed': [row['name'] for row in checks if not row['ok']]}, ensure_ascii=False))
    if not args.baseline and not report['ok']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
