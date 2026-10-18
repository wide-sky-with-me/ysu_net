"""Check the independent quota status and quiet reconnect control with offline data."""
import argparse
import copy
import json
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:1423/')
    parser.add_argument('--output', type=Path, default=Path('dist/quota-status-validation/after'))
    parser.add_argument('--baseline', action='store_true')
    args = parser.parse_args()
    assert urlsplit(args.url).hostname in ('localhost', '127.0.0.1')
    args.output.mkdir(parents=True, exist_ok=True)
    root = Path(__file__).resolve().parents[2]
    with tempfile.TemporaryDirectory(prefix='ysu-quota-fixture-') as directory:
        script = """
        const fs = require('node:fs');
        const {pathToFileURL} = require('node:url');
        const ts = require('./desktop/node_modules/typescript');
        for (const name of ['accents', 'protocol', 'demo']) {
          const code = ts.transpileModule(fs.readFileSync(`desktop/src/lib/${name}.ts`, 'utf8'), {
            compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ES2022}
          }).outputText.replaceAll("'./protocol'", "'./protocol.mjs'").replaceAll("'./accents'", "'./accents.mjs'");
          fs.writeFileSync(`${process.argv[1]}/${name}.mjs`, code);
        }
        import(pathToFileURL(`${process.argv[1]}/demo.mjs`).href).then(m=>console.log(JSON.stringify(m.demoSnapshot())));
        """
        snapshot = json.loads(subprocess.check_output(['node', '-e', script, directory], cwd=root, text=True))
    checks, errors, external = [], [], []

    def record(name, value):
        checks.append({'name': name, 'ok': bool(value)})

    with sync_playwright() as tool:
        browser = tool.chromium.launch(headless=True, executable_path='/usr/bin/google-chrome')

        def check(name, theme, width, quota=None, auto=None):
            context = browser.new_context(viewport={'width': width, 'height': 560 if width == 700 else 720}, reduced_motion='reduce')
            context.route('**/*', lambda route: route.continue_() if urlsplit(route.request.url).hostname in ('localhost', '127.0.0.1') else (external.append(route.request.url), route.abort()))
            data = copy.deepcopy(snapshot)
            data['prefs']['theme'] = theme
            if quota:
                data['accounts']['quota'] = quota
            if auto:
                data['auto'] = auto
            context.add_init_script("""(() => {
              const snapshot = DATA;
              window.isTauri = true;
              window.__TAURI_EVENT_PLUGIN_INTERNALS__ = {unregisterListener(){}};
              window.__TAURI_INTERNALS__ = {
                transformCallback(){return 1;},unregisterCallback(){},
                invoke:async(command,args={})=>{
                  if(command==='plugin:event|listen')return 1;
                  if(command==='plugin:event|unlisten')return null;
                  if(command==='get_desktop_settings')return {autostart:false,tray_available:true,version:'quota-fixture',demo:true};
                  if(command==='core_request'&&args.command==='snapshot')return structuredClone(snapshot);
                  throw new Error('Unexpected fixture command: '+command);
                }
              };
            })();""".replace('DATA', json.dumps(data, ensure_ascii=False), 1))
            page = context.new_page()
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('console', lambda message: errors.append(message.text) if message.type == 'error' else None)
            page.goto(args.url)
            page.wait_for_load_state('networkidle')
            page.evaluate('document.fonts.ready')
            expect(page.locator('.connection-action')).to_be_enabled()
            status = page.locator('.quota-state')
            expect(status).to_have_attribute('data-state', data['accounts']['quota']['state'])
            record(name+'-separate-status', status.evaluate("node=>node.parentElement.classList.contains('connection-automation')") and status.get_attribute('role') == 'status' and status.get_attribute('aria-label') == '流量状态')
            record(name+'-original-quota-text', data['accounts']['quota']['message'] in status.inner_text())
            record(name+'-zero-rounding-note', '待核心复核' in status.inner_text() if data['accounts']['quota']['state'] == 'zero_reported' else True)
            routine = page.locator('.auto-section:not(.rotation-section) p')
            if auto:
                record(name+'-actionable-notice', routine.count() == 1 and auto['message'] in routine.inner_text() and '30 秒' in routine.inner_text())
            else:
                record(name+'-quiet-reconnect', routine.count() == 0)
            record(name+'-no-overflow', page.evaluate('document.documentElement.scrollWidth<=innerWidth') and page.locator('main').evaluate('node=>node.scrollWidth<=node.clientWidth+1 && (innerWidth<=520 || node.scrollHeight<=node.clientHeight+1)'))
            page.screenshot(path=str(args.output / (name+'.png')), full_page=True)
            record(name+'-no-web-storage', page.evaluate('localStorage.length+sessionStorage.length') == 0)
            context.close()

        for theme in ('light', 'dark'):
            for width in (1000, 700, 390, 320):
                check(f'connection-{theme}-{width}', theme, width)
            for state, message in (
                ('unknown', '门户未提供可确认的剩余流量'),
                ('available', '门户原文：剩余 80.000 GiB'),
                ('zero_reported', '门户报告剩余流量 0.00 GiB'),
                ('unlimited', '本套餐不限量'),
            ):
                check(f'{state}-{theme}-700', theme, 700, quota={'state': state, 'message': message})
            check(f'reconnect-warning-{theme}-700', theme, 700, auto={'state': 'on', 'message': '操作超过时限，等待重新查询状态', 'delay': 30})
        browser.close()
    record('no-browser-errors', not errors)
    record('no-external-requests', not external)
    report = {'ok': all(item['ok'] for item in checks), 'baseline': args.baseline, 'mode': 'offline-native-contract-fixture', 'real_authentication': False, 'checks': checks, 'page_errors': errors, 'external_requests': external}
    (args.output/'quota-status-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({'ok': report['ok'], 'passed': sum(item['ok'] for item in checks), 'total': len(checks), 'failed': [item['name'] for item in checks if not item['ok']]}, ensure_ascii=False))
    raise SystemExit(0 if args.baseline or report['ok'] else 1)


if __name__ == '__main__':
    main()
