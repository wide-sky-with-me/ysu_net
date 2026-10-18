"""Check the sidebar brand wordmark against the built, offline desktop preview."""
import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright

from clean_desktop_preview import contrast


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:1423/')
    parser.add_argument('--output', type=Path, default=Path('dist/brand-wordmark-validation/after'))
    parser.add_argument('--baseline', action='store_true', help='Capture the existing brand without running interactions')
    args = parser.parse_args()
    assert urlsplit(args.url).hostname in ('localhost', '127.0.0.1')
    args.output.mkdir(parents=True, exist_ok=True)
    checks, errors, external = [], [], []

    def record(name, ok, **data):
        checks.append({'name': name, 'ok': bool(ok), **data})

    def hex_of(value):
        value = value.strip()
        if value.startswith('#'):
            return value.lower() if len(value) == 7 else '#' + ''.join(char * 2 for char in value[1:])
        numbers = value[value.index('(') + 1:value.index(')')].replace(',', ' ').split()
        return '#' + ''.join(f'{round(float(number)):02x}' for number in numbers[:3])

    with sync_playwright() as tool:
        browser = tool.chromium.launch(headless=True, executable_path='/usr/bin/google-chrome')
        context = browser.new_context(reduced_motion='reduce')
        context.route('**/*', lambda route: route.continue_() if urlsplit(route.request.url).hostname in ('localhost', '127.0.0.1') else (external.append(route.request.url), route.abort()))
        page = context.new_page()
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('console', lambda message: errors.append(message.text) if message.type == 'error' else None)

        def visit(theme='light', accent='teal'):
            page.goto(f'{args.url}?demo=1&theme={theme}&accent={accent}')
            page.wait_for_load_state('networkidle')
            page.evaluate('document.fonts.ready.then(() => true)')
            expect(page.get_by_role('button', name='连接', exact=True)).to_be_visible()

        mark = page.locator('.brand-mark')
        copy = page.locator('.brand-copy')
        title = page.locator('.brand strong')
        note = page.locator('.brand span')
        for theme in ('light', 'dark'):
            for width, height in ((1000, 720), (881, 560), (880, 560), (700, 560), (521, 560), (520, 700), (390, 760), (320, 760)):
                page.set_viewport_size({'width': width, 'height': height})
                visit(theme)
                prefix = f'{theme}-{width}-{height}'
                block, box = page.locator('.brand').bounding_box(), mark.bounding_box()
                record(prefix + '-mark-square', abs(box['width'] - box['height']) <= 1, box=box)
                record(prefix + '-mark-visible', box['width'] >= 28 and box['height'] >= 28)
                record(prefix + '-mark-svg', mark.locator('svg path').count() == 2 and mark.locator('svg circle').count() == 0 and mark.locator('svg').get_attribute('aria-hidden') == 'true' and abs(float(mark.locator('svg path').first.evaluate('node => getComputedStyle(node).strokeWidth').removesuffix('px')) - 3.4) < 0.2)
                record(prefix + '-mark-brand-fill', hex_of(mark.evaluate('node => getComputedStyle(node).backgroundColor')) == hex_of(page.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--brand-fill')")))
                icon_ratio = contrast('#ffffff', hex_of(mark.evaluate('node => getComputedStyle(node).backgroundColor')))
                record(prefix + '-mark-contrast', icon_ratio >= 3, ratio=round(icon_ratio, 3))
                if width > 880:
                    title_size = title.evaluate('node => parseFloat(getComputedStyle(node).fontSize)')
                    note_size = note.evaluate('node => parseFloat(getComputedStyle(node).fontSize)')
                    note_ratio = contrast(hex_of(note.evaluate('node => getComputedStyle(node).color')), hex_of(page.evaluate("getComputedStyle(document.querySelector('.sidebar')).backgroundColor")))
                    em = page.locator('.brand strong em')
                    record(prefix + '-wordmark-text', title.inner_text() == 'YSU Net' and em.inner_text() == 'Net' and note.inner_text() == '燕山大学校园网')
                    record(prefix + '-title-size', title_size >= 15 and title_size > note_size, title=title_size, note=note_size)
                    record(prefix + '-note-readable', note_size >= 11 and note_ratio >= 4.5, note=note_size, ratio=round(note_ratio, 3))
                    record(prefix + '-weight-contrast', float(title.evaluate('node => getComputedStyle(node).fontWeight')) - float(em.evaluate('node => getComputedStyle(node).fontWeight')) >= 200)
                    record(prefix + '-copy-visible', copy.is_visible() and title.is_visible() and note.is_visible())
                    record(prefix + '-inside-sidebar', block['x'] >= 0 and block['x'] + block['width'] <= 184)
                elif width > 520:
                    record(prefix + '-copy-hidden', not copy.is_visible() and not note.is_visible())
                    centre = page.locator('.sidebar').bounding_box()
                    record(prefix + '-mark-centered', abs(box['x'] + box['width'] / 2 - (centre['x'] + centre['width'] / 2)) <= 2, box=box)
                else:
                    record(prefix + '-copy-back', copy.is_visible() and title.is_visible() and note.is_visible())
                    record(prefix + '-compact-title', title.evaluate('node => parseFloat(getComputedStyle(node).fontSize)') >= 14)
                record(prefix + '-no-overlap', mark.bounding_box()['y'] + box['height'] <= page.locator('.sidebar nav').bounding_box()['y'])
                record(prefix + '-no-overflow', page.evaluate('document.documentElement.scrollWidth<=innerWidth') and page.locator('.sidebar').evaluate('node=>node.scrollWidth<=node.clientWidth'))
                page.screenshot(path=str(args.output / f'{prefix}.png'))

        page.set_viewport_size({'width': 1000, 'height': 720})
        for accent in ('blue', 'amber', 'rose'):
            visit('light', accent)
            fill = hex_of(mark.evaluate('node => getComputedStyle(node).backgroundColor'))
            record(f'accent-{accent}-follows', fill == hex_of(page.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--brand-fill')")) and contrast('#ffffff', fill) >= 3, fill=fill)
            page.screenshot(path=str(args.output / f'accent-{accent}.png'))
        visit('dark', 'teal')
        page.screenshot(path=str(args.output / 'accent-teal-dark.png'))

        record('no-browser-storage', page.evaluate('localStorage.length===0 && sessionStorage.length===0'))
        record('no-runtime-errors', not errors, errors=errors)
        record('no-external-requests', not external, external_requests=external)
        context.close()
        browser.close()

    report = {'ok': all(row['ok'] for row in checks), 'baseline': args.baseline, 'checks': checks}
    (args.output / 'brand-wordmark-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'ok': report['ok'], 'passed': sum(row['ok'] for row in checks), 'total': len(checks), 'failed': [row['name'] for row in checks if not row['ok']]}, ensure_ascii=False))
    if not args.baseline and not report['ok']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
