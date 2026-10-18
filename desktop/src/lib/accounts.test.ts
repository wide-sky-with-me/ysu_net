import { afterEach, describe, expect, it, vi } from 'vitest';
import { createDemoTransport, demoSnapshot } from './demo';
import { parseSnapshot, rotationControl, synchronizeSnapshots, validateAccount } from './protocol';
import type { SaveAccount } from './protocol';

const saved = (): SaveAccount => ({ label: '离线备用', username: 'fixture-new', password: 'fixture-only-password', service: '校园网', backend: 'api', enabled: true });
const read = async (transport: ReturnType<typeof createDemoTransport>) => parseSnapshot(await transport.request('snapshot', {}));
afterEach(() => vi.useRealTimers());

describe('strict account snapshot', () => {
  it('requires accounts in native snapshots with no implicit legacy fallback', () => {
    const { accounts: _, ...legacy } = demoSnapshot();
    expect(() => parseSnapshot(legacy)).toThrow('账号簿');
  });
  it('whitelists every public layer including nested account and quota extras', () => {
    const data = demoSnapshot();
    const secret = 'must-never-enter-ui-state';
    const parsed = parseSnapshot({ ...data, password: secret, credentials: { password: secret },
      config: { ...data.config, password: secret, password_hash: secret },
      accounts: { ...data.accounts, password: secret, secrets: { password: secret },
        quota: { ...data.accounts.quota, password: secret },
        items: data.accounts.items.map((item) => ({ ...item, password: secret, password_hash: secret, nested: { password: secret } })) },
      prefs: { ...data.prefs, password: secret }, status: { ...data.status, password: secret },
      auto: { ...data.auto, password: secret }, environment: { ...data.environment, password: secret },
      info: { ...data.info, password: secret }, logs: data.logs.map((log) => ({ ...log, password: secret })),
    });
    expect(JSON.stringify(parsed)).not.toContain(secret);
    expect(parsed.accounts.items.every((item) => item.password_set)).toBe(true);
    expect(Object.keys(parsed.accounts.items[0]).sort()).toEqual(['backend', 'current', 'enabled', 'id', 'label', 'password_set', 'service', 'username']);
  });
  it('rejects malformed account containers and quota enum without weakening old fields', () => {
    const data = demoSnapshot();
    for (const accounts of [null, {}, { ...data.accounts, items: {} }, { ...data.accounts, auto_switch: 'true' }, { ...data.accounts, environment_override: 0 }, { ...data.accounts, error: null }, { ...data.accounts, message: false }, { ...data.accounts, quota: { state: 'exhausted', message: '' } }, { ...data.accounts, quota: { state: 'unknown' } }]) {
      expect(() => parseSnapshot({ ...data, accounts })).toThrow();
    }
    expect(() => parseSnapshot({ ...data, config: { ...data.config, verify_tls: 'true' } })).toThrow('配置');
    expect(() => parseSnapshot({ ...data, auto: { ...data.auto, delay: Infinity } })).toThrow('重连');
  });
  it('rejects each malformed account field, duplicate identities and multiple current accounts', () => {
    const data = demoSnapshot(); const item = data.accounts.items[0];
    for (const changes of [{ id: '../path' }, { id: 'A'.repeat(32) }, { id: 7 }, { label: '名'.repeat(81) }, { username: '' }, { username: null }, { service: 'other' }, { backend: 'python' }, { enabled: 1 }, { password_set: 'true' }, { current: 'yes' }]) {
      expect(() => parseSnapshot({ ...data, accounts: { ...data.accounts, items: [{ ...item, ...changes }] } })).toThrow();
    }
    for (const items of [[item, item], [item, { ...data.accounts.items[1], username: item.username }], [item, { ...data.accounts.items[1], current: true }], [{ ...item, id: 'current', current: false }]]) {
      expect(() => parseSnapshot({ ...data, accounts: { ...data.accounts, items } })).toThrow();
    }
  });
  it('accepts all quota states literally, including unknown and rounded portal zero', () => {
    const data = demoSnapshot();
    for (const state of ['unknown', 'available', 'zero_reported', 'unlimited'] as const) {
      expect(parseSnapshot({ ...data, accounts: { ...data.accounts, quota: { state, message: '门户原文' } } }).accounts.quota).toEqual({ state, message: '门户原文' });
    }
    expect(parseSnapshot({ ...data, accounts: { ...data.accounts, items: [{ ...data.accounts.items[0], id: 'current' }] } }).accounts.items[0].id).toBe('current');
  });
  it('rejects too many saved accounts even with valid opaque ids', () => {
    const data = demoSnapshot();
    const items = Array.from({ length: 33 }, (_, index) => ({ ...data.accounts.items[1], id: index.toString(16).padStart(32, '0'), username: `fixture-${index}` }));
    expect(() => parseSnapshot({ ...data, accounts: { ...data.accounts, items } })).toThrow();
  });
});

describe('account edits', () => {
  it('requires a password on create, preserves blank passwords on edit and fixes usernames', () => {
    const items = demoSnapshot().accounts.items;
    expect(validateAccount({ ...saved(), password: '' }, items)).toContain('密码');
    expect(validateAccount({ ...items[1], password: '' }, items)).toBeNull();
    expect(validateAccount({ ...items[1], username: 'different' }, items)).toContain('固定');
    expect(validateAccount({ ...saved(), username: items[0].username }, items)).toContain('已在');
    expect(validateAccount({ ...saved(), id: 'd'.repeat(32) }, items)).toContain('已变更');
    expect(validateAccount({ ...saved(), label: 'x'.repeat(81) }, items)).toContain('80');
  });
  it('supports save, edit and delete without ever returning submitted passwords', async () => {
    const transport = createDemoTransport();
    await transport.request('save_account', saved());
    let state = await read(transport);
    const item = state.accounts.items.find((account) => account.username === 'fixture-new')!;
    expect(item.password_set).toBe(true);
    expect(JSON.stringify(state)).not.toContain(saved().password);
    await transport.request('save_account', { ...item, label: '新名称', password: '' });
    state = await read(transport);
    expect(state.accounts.items.find((account) => account.id === item.id)).toMatchObject({ label: '新名称', password_set: true });
    await expect(transport.request('delete_account', { id: state.accounts.items[0].id })).rejects.toThrow('当前账号');
    await transport.request('delete_account', { id: item.id });
    expect((await read(transport)).accounts.items).toHaveLength(3);
  });
  it('keeps legacy saves valid across repeated username changes and empty initialization', async () => {
    for (const scenario of ['', '?scenario=empty']) {
      const transport = createDemoTransport(scenario);
      for (const username of ['fixture-classic-a', 'fixture-classic-b', 'fixture-classic-c']) {
        await transport.request('save_config', { username, password: 'fixture-classic-secret' });
        const state = await read(transport);
        expect(state.accounts.items.filter((item) => item.current)).toHaveLength(1);
        expect(state.accounts.items.find((item) => item.current)?.username).toBe(username);
        expect(JSON.stringify(state)).not.toContain('fixture-classic-secret');
      }
    }
  });
  it('reports save and delete failures without changing the book', async () => {
    const save = createDemoTransport('?scenario=save-failure');
    await expect(save.request('save_account', saved())).rejects.toThrow('保存失败');
    expect((await read(save)).accounts.items).toHaveLength(3);
    const remove = createDemoTransport('?scenario=delete-failure');
    await expect(remove.request('delete_account', { id: 'b'.repeat(32) })).rejects.toThrow('删除失败');
    expect((await read(remove)).accounts.items).toHaveLength(3);
  });
});

describe('rotation controls and asynchronous switches', () => {
  it('defaults off, requires two valid enabled accounts and active automatic reconnect', () => {
    const state = demoSnapshot();
    expect(state.accounts.auto_switch).toBe(false);
    expect(rotationControl(state).canEnable).toBe(true);
    for (const items of [state.accounts.items.slice(0, 1), state.accounts.items.map((item) => ({ ...item, enabled: item.current })), state.accounts.items.map((item) => ({ ...item, password_set: item.current }))]) {
      expect(rotationControl({ ...state, accounts: { ...state.accounts, items } }).canEnable).toBe(false);
    }
    expect(rotationControl(demoSnapshot('?scenario=no-auto')).reason).toContain('自动重连');
    expect(rotationControl(null).canEnable).toBe(false);
  });
  it('blocks enabling for external ownership, environment override, book errors and busy auth', () => {
    for (const scenario of ['external', 'environment', 'accounts-error', 'busy']) expect(rotationControl(demoSnapshot(`?scenario=${scenario}`)).canEnable).toBe(false);
  });
  it('unknown quota never becomes a frontend exhaustion decision', async () => {
    vi.useFakeTimers();
    const transport = createDemoTransport('?scenario=quota-unknown');
    await transport.request('rotation', { enabled: true });
    await vi.advanceTimersByTimeAsync(600_000);
    const state = await read(transport);
    expect(state.accounts.quota.state).toBe('unknown');
    expect(state.accounts.items.find((item) => item.current)?.id).toBe('a'.repeat(32));
  });
  it('allows disabling rotation and reconnect during busy authentication', async () => {
    const transport = createDemoTransport('?scenario=busy&rotation=1');
    await expect(transport.request('rotation', { enabled: true })).rejects.toThrow();
    await transport.request('rotation', { enabled: false });
    expect((await read(transport)).accounts.auto_switch).toBe(false);
    await transport.request('action', { name: 'set_auto', value: false });
    expect((await read(transport)).prefs.auto_reconnect).toBe(false);
    expect((await read(transport)).busy).toBe(true);
    await transport.quit();
    expect((await read(transport)).busy).toBe(false);
  });
  it('external or environment overrides block switching and enabling, but allow rotation off', async () => {
    for (const scenario of ['external', 'environment']) {
      const transport = createDemoTransport(`?scenario=${scenario}&rotation=1`);
      await expect(transport.request('action', { name: 'switch_account', value: 'b'.repeat(32) })).rejects.toThrow();
      await expect(transport.request('rotation', { enabled: true })).rejects.toThrow();
      await transport.request('rotation', { enabled: false });
      expect((await read(transport)).accounts.auto_switch).toBe(false);
    }
  });
  it('a queued RPC does not change the current identity until the completion snapshot', async () => {
    vi.useFakeTimers();
    const transport = createDemoTransport(); const receive = vi.fn();
    const stop = await synchronizeSnapshots(transport, receive, vi.fn());
    const result = await transport.request('action', { name: 'switch_account', value: 'b'.repeat(32) });
    expect(result).toEqual({ accepted: true, message: '模拟：切换已排队' });
    expect((await read(transport)).config.username).toBe('20260001');
    expect(receive.mock.lastCall?.[0].busy).toBe(true);
    await vi.advanceTimersByTimeAsync(800);
    expect(receive.mock.lastCall?.[0].accounts.items.find((item: { current: boolean }) => item.current).username).toBe('fixture-student-b');
    expect((await read(transport)).config.username).toBe('fixture-student-b'); stop();
  });
  it('failed switching retains the current account and publishes the failure, never success', async () => {
    vi.useFakeTimers();
    const transport = createDemoTransport('?scenario=switch-failure');
    await transport.request('action', { name: 'switch_account', value: 'b'.repeat(32) });
    await vi.advanceTimersByTimeAsync(800);
    const state = await read(transport);
    expect(state.accounts.message).toContain('失败'); expect(state.busy).toBe(false);
    expect(state.accounts.items.find((item) => item.current)?.username).toBe('20260001');
  });
  it('reports rotation persistence failure and keeps the switch off', async () => {
    const transport = createDemoTransport('?scenario=rotation-failure');
    await expect(transport.request('rotation', { enabled: true })).rejects.toThrow('保存失败');
    expect((await read(transport)).accounts.auto_switch).toBe(false);
  });
});
