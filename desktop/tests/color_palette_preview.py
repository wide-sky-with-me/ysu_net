"""Audit the desktop palette and rendered control states using the built preview."""
import argparse
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright

from clean_desktop_preview import contrast
from flclash_desktop_preview import channels, color_hex


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:1423/')
    parser.add_argument('--output', type=Path, default=Path('dist/color-palette-validation/after'))
    parser.add_argument('--baseline', action='store_true')
    parser.add_argument('--accent', choices=('teal', 'blue', 'indigo', 'violet', 'rose', 'amber'), default='teal')
    args = parser.parse_args()
    assert urlsplit(args.url).hostname in ('localhost', '127.0.0.1')
    args.output.mkdir(parents=True, exist_ok=True)
    checks, errors, external, palettes = [], [], [], {}

    def record(name, ok, **data):
        checks.append({'name': name, 'ok': bool(ok), **data})

    def pair(name, fg, bg, minimum):
        ratio = contrast(fg, bg)
        record(name, ratio >= minimum, foreground=fg, background=bg, ratio=round(ratio, 3), minimum=minimum)

    text_pairs = [('text', bg) for bg in ('canvas', 'surface', 'surface-raised', 'field', 'sidebar')]
    text_pairs += [('muted', bg) for bg in ('canvas', 'surface', 'surface-raised', 'field', 'sidebar', 'hover')]
    text_pairs += [('text', 'hover')]
    text_pairs += [('accent', 'surface'), ('accent', 'accent-soft'), ('accent', 'hover'), ('on-accent', 'primary-fill'), ('on-accent', 'accent-hover'), ('success', 'success-soft'), ('warning', 'warning-soft'), ('danger', 'danger-soft'), ('on-danger', 'danger')]
    keys = sorted({key for pair in text_pairs for key in pair} | {'control-border', 'focus', 'idle', 'brand-fill'})

    with sync_playwright() as tool:
        browser = tool.chromium.launch(headless=True, executable_path='/usr/bin/google-chrome')
        context = browser.new_context(viewport={'width': 1000, 'height': 720}, reduced_motion='reduce')
        context.route('**/*', lambda route: route.continue_() if urlsplit(route.request.url).hostname in ('localhost', '127.0.0.1') else (external.append(route.request.url), route.abort()))
        page = context.new_page()
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('console', lambda message: errors.append(message.text) if message.type == 'error' else None)
        for theme in ('light', 'dark'):
            page.set_viewport_size({'width': 1000, 'height': 720})
            page.goto(args.url + f'?demo=1&theme={theme}&accent={args.accent}')
            page.wait_for_load_state('networkidle')
            page.evaluate('document.fonts.ready')
            expect(page.get_by_role('status', name='流量状态', exact=True)).to_be_visible()
            record(f'{theme}-accent-choice', page.locator('html').get_attribute('data-accent') == args.accent)
            colors = page.evaluate('(keys)=>Object.fromEntries(keys.map(key=>[key,getComputedStyle(document.documentElement).getPropertyValue("--"+key).trim()]))', keys)
            palettes[theme] = colors
            for fg, bg in text_pairs:
                pair(f'{theme}-{fg}/{bg}', colors[fg], colors[bg], 4.5)
            for bg in ('field', 'surface', 'surface-raised'):
                pair(f'{theme}-control-border/{bg}', colors['control-border'], colors[bg], 3)
            pair(f'{theme}-focus/field', colors['focus'], colors['field'], 3)
            pair(f'{theme}-idle/field', colors['idle'], colors['field'], 3)
            pair(f'{theme}-off-toggle-knob', '#ffffff', colors['idle'], 3)
            for index, color in enumerate(re.findall(r'#[0-9a-fA-F]{6}\b', colors['brand-fill'])):
                pair(f'{theme}-brand-icon-{index}', '#ffffff', color, 3)
            background = page.locator('.connection-context').evaluate('node=>getComputedStyle(node).backgroundColor')
            record(f'{theme}-opaque-card-surface', channels(background)[1] == 1, actual=background)
            label = page.locator('.quota-status')
            fg = color_hex(channels(label.locator('span').first.evaluate('node=>getComputedStyle(node).color'))[0])
            bg = color_hex(channels(label.evaluate('node=>getComputedStyle(node).backgroundColor'))[0])
            pair(f'{theme}-rendered-quota-label', fg, bg, 4.5)
            record(f'{theme}-quota-tonal-surface', contrast(bg, colors['accent-soft']) == 1, actual=bg)
            selected = page.locator('.service-selector button.selected')
            original = selected.evaluate('node=>({fg:getComputedStyle(node).color,bg:getComputedStyle(node).backgroundColor})')
            selected.hover()
            record(f'{theme}-selected-hover-keeps-colors', selected.evaluate('node=>({fg:getComputedStyle(node).color,bg:getComputedStyle(node).backgroundColor})') == original)
            unselected = page.locator('.service-selector button:not(.selected)').first
            unselected.hover()
            fg, bg = unselected.evaluate('node=>[getComputedStyle(node).color,getComputedStyle(node).backgroundColor]')
            pair(f'{theme}-rendered-unselected-hover', color_hex(channels(fg)[0]), color_hex(channels(bg)[0]), 4.5)
            page.mouse.move(1, 1)
            page.screenshot(path=str(args.output/f'connection-{theme}-1000.png'), full_page=True)
            page.set_viewport_size({'width': 700, 'height': 560})
            record(f'{theme}-compact-no-overflow', page.locator('main').evaluate('node=>node.scrollHeight<=node.clientHeight+1 && node.scrollWidth<=node.clientWidth+1'))
            page.screenshot(path=str(args.output/f'connection-{theme}-700.png'), full_page=True)
        version = browser.version
        browser.close()
    record('no-browser-errors', not errors)
    record('no-external-requests', not external)
    report = {'ok': all(item['ok'] for item in checks), 'baseline': args.baseline, 'accent': args.accent, 'browser_version': version, 'mode': 'built-offline-preview', 'real_authentication': False, 'checks': checks, 'palettes': palettes, 'page_errors': errors, 'external_requests': external}
    (args.output/'color-palette-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({'ok': report['ok'], 'passed': sum(item['ok'] for item in checks), 'total': len(checks), 'failed': [item for item in checks if not item['ok']]}, ensure_ascii=False))
    raise SystemExit(0 if args.baseline or report['ok'] else 1)


if __name__ == '__main__':
    main()
