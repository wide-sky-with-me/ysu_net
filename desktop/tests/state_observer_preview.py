"""Cloud browser acceptance: synthetic window hints + authoritative mocked native events.

No OS network changes, portal requests, authentication or real native operations occur.
"""
import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright
from about_preview import NATIVE_FIXTURE

MARKER = '  window.__TAURI_EVENT_PLUGIN_INTERNALS__ = '
OBSERVE = "      if (command === 'core_request' && args.command === 'observe' && Object.keys(args.args).length === 0) return structuredClone(core);"
assert NATIVE_FIXTURE.count(MARKER) == NATIVE_FIXTURE.count(OBSERVE) == 1
EXTENSION = r"""
  Object.assign(core.config, {username:'saved-user', service:'中国移动', password_set:true});
  core.accounts.items = [{id:'a'.repeat(32), label:'Saved intent', username:'saved-user', service:'中国移动', backend:'api', enabled:true, password_set:true, current:true}];
  core.status = {online:true, service:'中国联通', user:'portal-user-a', ip:'192.0.2.10', message:''};
  core.info = {online:true, fields:[['账号','portal-user-a']], items:[['剩余流量','80.00 GB']]};
  const observer = {calls:0, held:false, resolve:null, fail:false};
  window.__observerFixture = {
    count: () => observer.calls,
    reset() {if(observer.resolve) throw 'held_observation_pending'; observer.calls=0;},
    hold() {observer.held=true;},
    pending: () => Boolean(observer.resolve),
    release() {if(!observer.resolve) throw 'no_held_observation'; const done=observer.resolve;observer.resolve=null;observer.held=false;done({sequence:999999,status:{online:false},config:{username:'untrusted-ACK'}});},
    fail() {observer.fail=true;},
    saved: () => JSON.stringify([core.config,core.accounts,core.prefs]),
    patch(patch) {Object.assign(core,structuredClone(patch));window.__aboutBusy(core.busy);},
    observe() {
      observer.calls++;
      if(observer.fail) {observer.fail=false;throw new Error('https://fixture.invalid/?token=private /private/fixture.exe');}
      if(observer.held) return new Promise(resolve=>{if(observer.resolve) throw 'duplicate_observe';observer.resolve=resolve;});
      return {sequence:999999,status:{online:false},config:{username:'untrusted-ACK'}};
    }
  };
"""
NATIVE = NATIVE_FIXTURE.replace(MARKER, EXTENSION + MARKER).replace(OBSERVE, "      if (command === 'core_request' && args.command === 'observe' && Object.keys(args.args).length === 0) return window.__observerFixture.observe();")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', required=True)
    parser.add_argument('--browser', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    origin = urlsplit(args.url)
    assert origin.scheme == 'http' and origin.hostname in ('127.0.0.1', 'localhost', '::1') and not origin.username and not origin.password
    args.output.mkdir(parents=True, exist_ok=True)
    errors, console_errors, blocked, checks = [], [], [], []
    with sync_playwright() as tool:
        browser = tool.chromium.launch(executable_path=args.browser, headless=True)
        contexts = []

        def context(native=False):
            item = browser.new_context(viewport={'width':1000,'height':720}, reduced_motion='reduce', service_workers='block')
            contexts.append(item)
            if native:
                item.add_init_script(NATIVE)
            else:
                item.add_init_script("window.isTauri=false;window.__observerForbidden=[];window.__TAURI_INTERNALS__={invoke(){window.__observerForbidden.push('invoke');throw new Error('native_ipc_forbidden_in_demo_or_web')}};")
            def watch(page):
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.on('console', lambda message: console_errors.append(message.text) if message.type=='error' else None)
            item.on('page', watch)

            def guard(route):
                request = route.request
                target = urlsplit(request.url)
                favicon = request.resource_type == 'other' and target.path == '/favicon.svg' and not target.query
                if ((target.scheme,target.hostname,target.port)==(origin.scheme,origin.hostname,origin.port)
                        and request.method=='GET' and (request.resource_type in ('document','stylesheet','script','font','image') or favicon)):
                    route.continue_()
                else:
                    blocked.append(f'{target.scheme}://{target.hostname}:{target.port} {request.method} {request.resource_type}')
                    route.abort()
            item.route('**/*', guard)
            return item

        def hint(page, events=('focus','online','offline')):
            page.evaluate('events=>{for(const name of events)window.dispatchEvent(new Event(name));document.dispatchEvent(new Event("visibilitychange"));}', list(events))

        def count(page):
            return page.evaluate('window.__observerFixture.count()')

        page = context(True).new_page()
        page.goto(args.url, wait_until='networkidle')
        expect(page.get_by_text('portal-user-a', exact=True)).to_be_visible()
        page.wait_for_timeout(700)
        saved = page.evaluate('window.__observerFixture.saved()')
        page.evaluate('window.__observerFixture.reset()')
        for _ in range(10):
            hint(page)
        page.wait_for_function('window.__observerFixture.count()===1')
        page.wait_for_timeout(400)
        assert count(page)==1
        expect(page.get_by_text('portal-user-a', exact=True)).to_be_visible()
        expect(page.locator('.feedback-notice')).to_have_count(0)
        checks.append('window-events-coalesce-and-offline-hint-or-ACK-cannot-change-status')

        page.evaluate('window.__observerFixture.reset();window.__observerFixture.hold()')
        hint(page, ('focus',))
        page.wait_for_function('window.__observerFixture.pending()')
        for _ in range(10):
            hint(page)
        page.wait_for_timeout(450)
        assert count(page)==1
        page.evaluate('window.__observerFixture.release()')
        page.wait_for_function('window.__observerFixture.count()===2')
        expect(page.get_by_text('portal-user-a', exact=True)).to_be_visible()
        checks.append('one-held-ACK-and-at-most-one-follow-up-no-overlapping-IPC')

        page.evaluate('window.__observerFixture.reset();window.__observerFixture.patch({busy:true})')
        expect(page.get_by_role('button',name='刷新状态',exact=True)).to_be_disabled()
        hint(page, ('online',))
        page.wait_for_function('window.__observerFixture.count()===1')
        expect(page.get_by_role('button',name='刷新状态',exact=True)).to_be_disabled()
        expect(page.locator('.feedback-notice')).to_have_count(0)
        page.evaluate('window.__observerFixture.patch({busy:false})')
        checks.append('busy-authentication-still-admits-advisory-without-changing-busy-state')

        page.keyboard.press('Control+2')
        expect(page.get_by_role('heading',name='账户',exact=True)).to_be_visible()
        page.evaluate('window.__observerFixture.patch({status:{online:true,user:"portal-user-b",service:"中国电信",ip:"192.0.2.11",message:""},info:null,info_error:""})')
        expect(page.get_by_role('heading',name='尚未读取账户信息',exact=True)).to_be_visible()
        assert 'portal-user-a' not in page.locator('main').inner_text()
        assert '80.00' not in page.locator('main').inner_text()
        assert page.evaluate('window.__observerFixture.saved()')==saved
        expect(page.locator('.feedback-notice')).to_have_count(0)
        page.screenshot(path=str(args.output/'identity-invalidated.png'), full_page=True)
        checks.append('authoritative-identity-change-clears-old-detail-not-saved-account-intent')

        page.evaluate('window.__observerFixture.patch({status:{online:null,user:"",service:null,ip:"",message:"固定查询失败"},info:null})')
        expect(page.get_by_role('heading',name='连接状态未知',exact=True)).to_be_visible()
        assert page.evaluate('window.__observerFixture.saved()')==saved
        checks.append('unknown-observation-is-not-offline-and-never-authenticates')

        page.evaluate('window.__observerFixture.reset();window.__observerFixture.fail()')
        hint(page, ('focus',))
        page.wait_for_function('window.__observerFixture.count()===1')
        page.wait_for_timeout(400)
        expect(page.locator('.feedback-notice')).to_have_count(0)
        assert 'token=private' not in page.locator('body').inner_text()
        assert '/private/' not in page.locator('body').inner_text()
        hint(page, ('focus',))
        page.wait_for_function('window.__observerFixture.count()===2')
        calls=page.evaluate('window.__aboutCalls')
        core_calls=[call['args'] for call in calls if call['command']=='core_request']
        assert all(call['command'] in ('snapshot','observe') for call in core_calls),core_calls
        assert all(not call.get('args') for call in core_calls if call['command']=='observe')
        assert page.evaluate('window.__aboutUnexpected')==[]
        assert page.evaluate('localStorage.length+sessionStorage.length')==0
        checks.append('raw-passive-errors-contained-and-all-native-calls-remain-read-only')

        for query in ('?demo=1',''):
            plain = context().new_page()
            plain.goto(args.url+query, wait_until='networkidle')
            plain.wait_for_function('document.querySelector("main")!==null')
            hint(plain)
            plain.wait_for_timeout(500)
            assert plain.evaluate('localStorage.length+sessionStorage.length')==0
            assert plain.evaluate('window.__observerForbidden')==[]
            checks.append('no-native-observation-in-'+('demo' if query else 'ordinary-web'))
        for item in contexts:
            item.close()
        browser.close()
    report={'checks':checks,'pageErrors':errors,'consoleErrors':console_errors,'blockedRequests':blocked,'realOsNetworkChanges':False,'realAuthenticationOrSettingsWrites':False,'nativeIpc':'mocked fixture only'}
    (args.output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    assert not errors and not console_errors and not blocked,report
    print(json.dumps({'checks':len(checks),'pageErrors':len(errors),'consoleErrors':len(console_errors),'blockedRequests':len(blocked)}))


if __name__=='__main__':
    main()
