import { beforeEach, describe, expect, it, vi } from 'vitest';
const mocks = vi.hoisted(() => ({ invoke: vi.fn(), listen: vi.fn(), isTauri: vi.fn() }));
vi.mock('@tauri-apps/api/core', () => ({ invoke: mocks.invoke, isTauri: mocks.isTauri }));
vi.mock('@tauri-apps/api/event', () => ({ listen: mocks.listen }));
import { createDesktopTransport, createTransport, selectMode } from './bridge';

describe('native bridge', () => {
  beforeEach(() => vi.resetAllMocks());
  it('uses the exact command and event envelope', async () => {
    mocks.invoke.mockResolvedValue({ accepted: true }); mocks.listen.mockResolvedValue(() => {});
    const transport = createDesktopTransport();
    await transport.request('action', { name: 'switch', value: '中国电信' });
    expect(mocks.invoke).toHaveBeenCalledWith('core_request', { command: 'action', args: { name: 'switch', value: '中国电信' } });
    const handler = vi.fn(); await transport.subscribe(handler);
    expect(mocks.listen.mock.calls[0][0]).toBe('core-event');
    mocks.listen.mock.calls[0][1]({ payload: { kind: 'event', name: 'snapshot', payload: {} } });
    expect(handler).toHaveBeenCalledWith({ kind: 'event', name: 'snapshot', payload: {} });
  });
  it('preserves rejected promises without converting errors to success', async () => {
    mocks.invoke.mockRejectedValue(new Error('operation failed'));
    await expect(createDesktopTransport().request('action', { name: 'login' })).rejects.toThrow('operation failed');
  });
  it('routes native preferences and quit directly', async () => {
    mocks.invoke.mockResolvedValue({ autostart: true, tray_available: true, version: '1.0' });
    const transport = createDesktopTransport();
    await transport.getDesktopSettings(); await transport.setAutostart(true); await transport.setStartupMode(false); await transport.quit();
    expect(mocks.invoke).toHaveBeenCalledWith('get_desktop_settings');
    expect(mocks.invoke).toHaveBeenCalledWith('set_autostart', { enabled: true });
    expect(mocks.invoke).toHaveBeenCalledWith('set_startup_mode', { minimized: false });
    expect(mocks.invoke).toHaveBeenCalledWith('quit_app', {});
  });
  it('requires explicit demo=1 and gives native mode precedence', () => {
    expect(selectMode(false, '')).toBe('web'); expect(selectMode(false, '?demo=true')).toBe('web');
    expect(selectMode(false, '?demo=1')).toBe('demo'); expect(selectMode(true, '?demo=1')).toBe('desktop');
  });
  it('ordinary browser blocks every core and system entry without native IPC', async () => {
    mocks.isTauri.mockReturnValue(false);
    const transport = createTransport(''); expect(transport.mode).toBe('web');
    for (const operation of [
      () => transport.request('snapshot', {}),
      () => transport.request('action', { name: 'login' }),
      () => transport.request('save_config', { username: 'fixture-only', password: 'fixture-only' }),
      () => transport.request('rotation', { enabled: true }),
      () => transport.getDesktopSettings(),
      () => transport.setAutostart(true),
      () => transport.setStartupMode(false),
      () => transport.quit(),
      () => transport.subscribe(() => {}),
    ]) await expect(operation()).rejects.toThrow('普通网页');
    expect(mocks.invoke).not.toHaveBeenCalled();
    expect(mocks.listen).not.toHaveBeenCalled();
  });
  it('explicit Demo keeps authentication and system changes in memory without native IPC', async () => {
    mocks.isTauri.mockReturnValue(false);
    const transport = createTransport('?demo=1');
    expect(transport.mode).toBe('demo');
    const handler = vi.fn();
    const stop = await transport.subscribe(handler);
    await transport.request('save_config', { username: 'fixture-only', password: 'fixture-only' });
    await transport.request('action', { name: 'login' });
    await transport.request('action', { name: 'logout' });
    await transport.setAutostart(true);
    expect((await transport.getDesktopSettings()).autostart).toBe(true);
    expect(await transport.setStartupMode(false)).toMatchObject({ prefs: { autostart_minimized: false } });
    expect((await transport.getDesktopSettings()).autostart).toBe(true);
    await transport.quit();
    expect(handler).toHaveBeenCalled();
    stop();
    const fresh = createTransport('?demo=1');
    expect((await fresh.getDesktopSettings()).autostart).toBe(false);
    expect(await fresh.request('snapshot', {})).toMatchObject({
      config: { username: '20260001' }, prefs: { auto_reconnect: true, autostart_minimized: true },
    });
    expect(mocks.invoke).not.toHaveBeenCalled();
    expect(mocks.listen).not.toHaveBeenCalled();
  });
  it('forwards account and rotation commands unchanged through native IPC', async () => {
    mocks.invoke.mockResolvedValue({ accepted: true });
    const transport = createDesktopTransport();
    const account = { label: '备用账号', username: 'fixture-b', service: '校园网' as const, backend: 'api' as const, enabled: true };
    await transport.request('save_account', account);
    await transport.request('delete_account', { id: 'b'.repeat(32) });
    await transport.request('rotation', { enabled: false });
    await transport.request('action', { name: 'switch_account', value: 'b'.repeat(32) });
    expect(mocks.invoke.mock.calls).toEqual([
      ['core_request', { command: 'save_account', args: account }],
      ['core_request', { command: 'delete_account', args: { id: 'b'.repeat(32) } }],
      ['core_request', { command: 'rotation', args: { enabled: false } }],
      ['core_request', { command: 'action', args: { name: 'switch_account', value: 'b'.repeat(32) } }],
    ]);
  });
});
