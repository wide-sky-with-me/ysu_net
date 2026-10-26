import { beforeEach, describe, expect, it, vi } from 'vitest';
const mocks = vi.hoisted(() => ({ invoke: vi.fn(), listen: vi.fn() }));
vi.mock('@tauri-apps/api/core', () => ({ invoke: mocks.invoke }));
vi.mock('@tauri-apps/api/event', () => ({ listen: mocks.listen }));
import { canInstallUpdate, createUpdaterClient, initialUpdateSnapshot, newerUpdateSnapshot, parseUpdateSnapshot, RELEASES_URL, UPDATE_ERRORS, UPDATE_PHASES, updateCheckNotice, updateDownloadLabel, updateErrorCode, updateErrorMessage, updatePercent, updateWorking } from './updater';
import type { UpdatePhase, UpdateSnapshot } from './updater';
import { render } from 'svelte/server';
import UpdatePanel from './UpdatePanel.svelte';

const candidate = (phase: UpdatePhase = 'available'): UpdateSnapshot => ({
  sequence: 4, phase, current_version: '0.2.0', release: { version: '0.3.0', notes: '测试更新说明 <script>plain text</script>' }, downloaded: 0, total: null, download_mode: null, fallback: false, error: null, releases_url: RELEASES_URL,
});

describe('user-initiated updater bridge', () => {
  beforeEach(() => vi.resetAllMocks());
  it('status and subscription do not silently trigger a check or download', async () => {
    mocks.invoke.mockResolvedValue(initialUpdateSnapshot('desktop', false, '0.2.0'));
    mocks.listen.mockResolvedValue(() => {});
    const client = createUpdaterClient('desktop');
    await client.status(); await client.subscribe(vi.fn());
    expect(mocks.invoke.mock.calls).toEqual([['updater_status', undefined]]);
    expect(mocks.listen.mock.calls[0][0]).toBe('updater-event');
  });
  it('uses independent IPC and only passes the previously confirmed version', async () => {
    mocks.invoke.mockResolvedValue(candidate());
    const client = createUpdaterClient('desktop');
    await client.check(); await client.install('0.3.0'); await client.resume(); await client.restart();
    expect(mocks.invoke.mock.calls).toEqual([
      ['updater_check', undefined], ['updater_install', { version: '0.3.0' }], ['updater_resume', undefined], ['updater_restart'],
    ]);
  });
  it.each([['demo', false], ['desktop', true], ['web', false]] as const)('%s demo=%s never reaches native IPC, feed or installer', async (mode, demo) => {
    const client = createUpdaterClient(mode, demo, '0.2.0');
    const snapshot = await client.status();
    expect(snapshot.phase).toBe(mode === 'web' ? 'manual' : 'disabled');
    expect(snapshot.release).toBeNull();
    expect(snapshot.downloaded).toBe(0);
    const expected = mode === 'web' ? 'manual_only' : 'disabled';
    await expect(client.check()).rejects.toBe(expected);
    await expect(client.install('0.3.0')).rejects.toBe(expected);
    await expect(client.resume()).rejects.toBe(expected);
    await expect(client.restart()).rejects.toBe(expected);
    await expect(client.openReleases()).rejects.toBe(expected);
    const stop = await client.subscribe(vi.fn()); stop();
    expect(mocks.invoke).not.toHaveBeenCalled();
    expect(mocks.listen).not.toHaveBeenCalled();
  });
  it('renders a native release action, a normal web link, and no demo escape', () => {
    const native = render(UpdatePanel, { props: { mode: 'desktop' } }).body;
    expect(native).toContain('type="button" class="text-button update-release-link"');
    expect(native).not.toContain('target="_blank"');
    const web = render(UpdatePanel, { props: { mode: 'web' } }).body;
    expect(web).toContain(`href="${RELEASES_URL}" target="_blank"`);
    for (const props of [{ mode: 'demo' as const }, { mode: 'desktop' as const, demo: true }]) {
      expect(render(UpdatePanel, { props }).body).not.toContain('update-release-link');
    }
    expect(mocks.invoke).not.toHaveBeenCalled();
  });
  it('opens native releases with no URL argument, even in manual-update mode', async () => {
    mocks.invoke.mockResolvedValue(initialUpdateSnapshot('web', false, '0.2.1'));
    const client = createUpdaterClient('desktop');
    expect((await client.status()).phase).toBe('manual');
    mocks.invoke.mockClear();
    await client.openReleases();
    expect(mocks.invoke.mock.calls).toEqual([['updater_open_releases']]);
  });
  it('maps browser handoff errors without displaying raw OS messages or paths', async () => {
    mocks.invoke.mockRejectedValue('open_failed');
    await expect(createUpdaterClient('desktop').openReleases()).rejects.toBe('open_failed');
    expect(updateErrorMessage('open_failed')).toContain('默认浏览器');
    mocks.invoke.mockRejectedValue(new Error('fixture-private-path or launch command'));
    await expect(createUpdaterClient('desktop').openReleases()).rejects.toBe('ipc');
    expect(updateErrorMessage(updateErrorCode(new Error('fixture-private-path')))).not.toContain('fixture');
  });
  it('validates event payloads and forwards only the public whitelist', async () => {
    mocks.listen.mockResolvedValue(() => {});
    const handler = vi.fn(); const onerror = vi.fn();
    await createUpdaterClient('desktop').subscribe(handler, onerror);
    const callback = mocks.listen.mock.calls[0][1];
    callback({ payload: { ...candidate(), releases_url: 'https://fixture.invalid/?token=private', download_url: 'private', signature: 'private' } });
    expect(handler.mock.calls[0][0]).toEqual(candidate());
    callback({ payload: { ...candidate(), error: 'https://fixture.invalid/?token=private' } });
    expect(handler).toHaveBeenCalledTimes(1);
    expect(onerror).toHaveBeenCalledWith('ipc');
  });
  it('never renders arbitrary download error messages, URLs or tokens', async () => {
    const raw = 'download https://fixture.invalid?token=private';
    mocks.invoke.mockRejectedValue(new Error(raw));
    await expect(createUpdaterClient('desktop').check()).rejects.toBe('ipc');
    expect(updateErrorMessage(updateErrorCode(raw))).not.toContain('fixture');
    expect(updateErrorMessage(updateErrorCode(new Error(raw)))).not.toContain('private');
    mocks.invoke.mockRejectedValue('signature');
    await expect(createUpdaterClient('desktop').install('0.3.0')).rejects.toBe('signature');
    expect(updateErrorMessage('signature')).toContain('签名');
  });
  it('distinguishes an unready feed from a successful no-update check', async () => {
    mocks.invoke.mockRejectedValue('feed_not_ready');
    await expect(createUpdaterClient('desktop').check()).rejects.toBe('feed_not_ready');
    expect(updateErrorMessage('feed_not_ready')).toContain('更新源尚未就绪');
    expect(updateErrorMessage('feed_not_ready')).not.toContain('最新版');
  });
});

describe('explicit update-check completion notices', () => {
  beforeEach(() => vi.resetAllMocks());
  it('uses the existing feedback shape and exact successful check wording', () => {
    expect(updateCheckNotice({ ...candidate('up_to_date'), release: null })).toEqual({ message: '当前已是最新版本', error: false });
    const available = { ...candidate(), release: { version: '0.2.2', notes: '<script>fixture-private</script>' } };
    expect(updateCheckNotice(available)).toEqual({ message: '发现新版本 0.2.2', error: false });
    expect(JSON.stringify(updateCheckNotice(available))).not.toContain('fixture-private');
  });
  it.each(UPDATE_PHASES.filter((phase) => !['up_to_date', 'available', 'error'].includes(phase)))('never treats %s as a completed explicit check', (phase) => {
    expect(updateCheckNotice(candidate(phase))).toBeNull();
  });
  it.each(UPDATE_ERRORS)('maps terminal %s through the fixed error-message whitelist', (error) => {
    expect(updateCheckNotice({ ...candidate('error'), error })).toEqual({ message: updateErrorMessage(error), error: true });
  });
  it('does not turn a missing terminal error into success', () => {
    expect(updateCheckNotice({ ...candidate('error'), error: null })).toEqual({ message: updateErrorMessage('check_failed'), error: true });
  });
  it('only exposes sanitized IPC failures, never raw rejected text or candidate notes', async () => {
    const raw = 'https://fixture.invalid/?token=private /private/fixture.exe';
    mocks.invoke.mockRejectedValue(new Error(raw));
    let code = updateErrorCode(null);
    try { await createUpdaterClient('desktop').check(); } catch (error) { code = updateErrorCode(error); }
    expect(code).toBe('ipc');
    const notice = updateCheckNotice({ ...candidate('error'), error: code });
    expect(notice).toEqual({ message: updateErrorMessage('ipc'), error: true });
    for (const value of ['fixture.invalid', 'token=private', '/private/', '<script>']) expect(JSON.stringify(notice)).not.toContain(value);
  });
});

describe('update state and recovery semantics', () => {
  it('blocks installation during authentication, every active phase and recovery/restart', () => {
    expect(canInstallUpdate(candidate(), false)).toBe(true);
    expect(canInstallUpdate(candidate(), true)).toBe(false);
    expect(canInstallUpdate({ ...candidate('error'), error: 'download_failed' }, false)).toBe(true);
    for (const phase of ['idle', 'disabled', 'manual', 'checking', 'up_to_date', 'downloading', 'verifying', 'reconstructing', 'quiescing', 'installing', 'recovery_required', 'restart_required'] as const) {
      expect(canInstallUpdate(candidate(phase), false)).toBe(false);
    }
    expect(canInstallUpdate({ ...candidate(), release: null }, false)).toBe(false);
  });
  it('does not invent content lengths or pretend partial downloads are verified', () => {
    expect(updatePercent(candidate('downloading'))).toBeUndefined();
    expect(updatePercent({ ...candidate('downloading'), downloaded: 13, total: 40 })).toBe(32);
    expect(updatePercent({ ...candidate('verifying'), downloaded: 50, total: 40 })).toBe(100);
    expect(updatePercent({ ...candidate(), total: 0 })).toBeUndefined();
    expect(updateWorking('verifying')).toBe(true);
    expect(updateWorking('restart_required')).toBe(false);
  });
  it('retains newer progress when an older status response arrives on remount', () => {
    const progress = { ...candidate('downloading'), sequence: 10, downloaded: 50 };
    expect(newerUpdateSnapshot(progress, candidate())).toBe(progress);
    expect(newerUpdateSnapshot(candidate(), progress)).toBe(progress);
  });
  it('rejects malformed phases, counters, payloads and missing candidate metadata', () => {
    for (const value of [null, {}, { ...candidate(), phase: 'future' }, { ...candidate(), sequence: -1 }, { ...candidate(), downloaded: Infinity }, { ...candidate(), total: -4 }, { ...candidate(), error: {} }, { ...candidate(), release: null }, { ...candidate(), release: { version: '0.3.0', notes: [] } }]) {
      expect(() => parseUpdateSnapshot(value)).toThrow();
    }
    expect(parseUpdateSnapshot({ ...candidate(), releases_url: 'javascript:fixture()' }).releases_url).toBe(RELEASES_URL);
  });
  it('normalizes legacy transfer fields without admitting unknown download data', () => {
    const legacy: Record<string, unknown> = { ...candidate() };
    delete legacy.download_mode; delete legacy.fallback;
    expect(parseUpdateSnapshot(legacy)).toEqual(candidate());
    for (const value of [
      { ...candidate(), download_mode: 'https://fixture.invalid/private' },
      { ...candidate(), fallback: 'yes' },
      { ...candidate('reconstructing'), release: null },
    ]) expect(() => parseUpdateSnapshot(value)).toThrow();
    expect(parseUpdateSnapshot({ ...candidate(), download_mode: 'delta', fallback: true })).toMatchObject({ download_mode: 'delta', fallback: true });
  });
  it('distinguishes patch download, reconstruction and complete-package fallback', () => {
    expect(updateDownloadLabel({ ...candidate('downloading'), download_mode: 'delta' })).toContain('差分补丁');
    expect(updateDownloadLabel({ ...candidate('downloading'), download_mode: 'full', fallback: true })).toContain('完整包');
    expect(updateDownloadLabel(candidate('downloading'))).toContain('完整更新包');
    expect(updateDownloadLabel(candidate('reconstructing'))).toContain('还原');
    expect(updateDownloadLabel(candidate('verifying'))).toBeUndefined();
    expect(updateWorking('reconstructing')).toBe(true);
    expect(canInstallUpdate(candidate('reconstructing'), false)).toBe(false);
  });
  it('tells users how each stopped-core failure can recover', () => {
    expect(updateErrorMessage('install_failed')).toContain('后台已恢复');
    expect(updateErrorMessage('recovery_failed')).toContain('重试恢复后台');
    expect(updateErrorMessage('application_restore_failed')).toContain('重新安装');
    expect(updateErrorMessage('core_stop_failed')).toContain('更新未安装');
  });
});
