import { afterEach, describe, expect, it, vi } from 'vitest';
import { accountItems, advanceLogFloor, formatDiagnostics, formatLogTime, parseSnapshot, snapshotEvent, SnapshotSequence, synchronizeSnapshots, validateConfig } from './protocol';
import type { Snapshot, Transport } from './protocol';
import { createDemoTransport, demoSnapshot } from './demo';

afterEach(() => vi.useRealTimers());

describe('snapshot contract', () => {
  it('keeps unknown online distinct from offline', () => { expect(parseSnapshot(demoSnapshot('?scenario=unknown')).status?.online).toBeNull(); });
  it('accepts public account errors and keeps older snapshots compatible', () => {
    const snapshot = demoSnapshot('?scenario=info-error');
    expect(parseSnapshot(snapshot).info_error).toBe('账户信息获取失败，请稍后重试');
    const { info_error: _, ...older } = snapshot;
    expect(parseSnapshot(older).info_error).toBe('');
    for (const info_error of [null, false, 7, {}, []]) expect(() => parseSnapshot({ ...snapshot, info_error })).toThrow('账户读取错误');
  });
  it('defaults legacy startup mode to tray but rejects malformed native mode values', () => {
    const data = demoSnapshot();
    const { autostart_minimized: _, ...legacy } = data.prefs;
    expect(parseSnapshot({ ...data, prefs: legacy }).prefs.autostart_minimized).toBe(true);
    expect(parseSnapshot({ ...data, prefs: { ...data.prefs, autostart_minimized: false } }).prefs.autostart_minimized).toBe(false);
    for (const value of [null, 'false', 0, {}, []]) expect(() => parseSnapshot({ ...data, prefs: { ...data.prefs, autostart_minimized: value } })).toThrow('偏好格式');
  });
  it('rejects malformed sequences and shape', () => {
    for (const sequence of [-1, 1.5, NaN, Infinity, '4']) expect(() => parseSnapshot({ ...demoSnapshot(), sequence })).toThrow();
    expect(() => parseSnapshot({ ...demoSnapshot(), info: { online: true, items: [['bad']], fields: [] } })).toThrow();
  });
  it('requires the native runtime contract and rejects legacy or spoofed environments', () => {
    const data = demoSnapshot();
    expect(parseSnapshot(data).environment.runtime).toBe('rust');
    expect(() => parseSnapshot({ ...data, environment: { ...data.environment, runtime: 'python' } })).toThrow();
    expect(() => parseSnapshot({ ...data, environment: { version: 'legacy', python: '3.12', platform: 'linux', node_available: true, browser_available: true, browser_component_available: true } })).toThrow();
  });
  it('drops unexpected credentials from public config', () => {
    const data = demoSnapshot();
    expect(parseSnapshot({ ...data, config: { ...data.config, password: 'never-store' } }).config).not.toHaveProperty('password');
  });
  it('accepts only the named event envelope', () => {
    expect(snapshotEvent({ kind: 'event', name: 'snapshot', payload: demoSnapshot() })?.sequence).toBe(1);
    expect(snapshotEvent({ kind: 'event', name: 'result', payload: { online: true } })).toBeNull();
    expect(snapshotEvent({ payload: demoSnapshot() })).toBeNull();
  });
  it('rejects older and duplicate snapshots', () => {
    const gate = new SnapshotSequence();
    expect(gate.accept({ ...demoSnapshot(), sequence: 7 })).toBe(true);
    expect(gate.accept({ ...demoSnapshot(), sequence: 2 })).toBe(false);
    expect(gate.accept({ ...demoSnapshot(), sequence: 7 })).toBe(false);
    expect(gate.accept({ ...demoSnapshot(), sequence: 8 })).toBe(true);
  });
  it('subscribes before fetching and preserves a newer event', async () => {
    const order: string[] = [];
    let emit: (event: unknown) => void = () => {};
    const unlisten = vi.fn();
    const transport: Transport = { ...createDemoTransport(),
      subscribe: async (handler) => { order.push('subscribe'); emit = handler; return unlisten; },
      request: async () => { order.push('request'); emit({ kind: 'event', name: 'snapshot', payload: { ...demoSnapshot(), sequence: 5 } }); return { ...demoSnapshot(), sequence: 4 }; },
    };
    const received: Snapshot[] = [];
    const stop = await synchronizeSnapshots(transport, (data) => received.push(data), vi.fn());
    expect(order).toEqual(['subscribe', 'request']); expect(received.map((data) => data.sequence)).toEqual([5]);
    stop(); emit({ kind: 'event', name: 'snapshot', payload: { ...demoSnapshot(), sequence: 6 } });
    expect(received).toHaveLength(1); expect(unlisten).toHaveBeenCalledOnce();
  });
  it('cleans listener up when initial request rejects', async () => {
    const unlisten = vi.fn();
    const transport: Transport = { ...createDemoTransport(), subscribe: async () => unlisten, request: async () => { throw new Error('core unavailable'); } };
    await expect(synchronizeSnapshots(transport, vi.fn(), vi.fn())).rejects.toThrow('core unavailable');
    expect(unlisten).toHaveBeenCalledOnce();
  });
  it('reports malformed events without destroying a healthy subscription', async () => {
    let emit: (event: unknown) => void = () => {};
    const fail = vi.fn(); const receive = vi.fn();
    const stop = await synchronizeSnapshots({ ...createDemoTransport(), subscribe: async (handler) => { emit = handler; return () => {}; } }, receive, fail);
    emit({ kind: 'event', name: 'snapshot', payload: {} });
    emit({ kind: 'event', name: 'snapshot', payload: { ...demoSnapshot(), sequence: 9 } });
    expect(fail).toHaveBeenCalledOnce(); expect(receive).toHaveBeenCalledTimes(2); stop();
  });
});

describe('portal original values', () => {
  it('adds only missing flow and never invents a balance item', () => {
    expect(accountItems({ online: true, fields: [], items: [['套餐', '原文套餐']] })).toEqual([['套餐', '原文套餐'], ['剩余流量', '门户未提供']]);
    const portal: [string, string][] = [['套餐与余额', '校园套餐；余额 0.00 元'], ['剩余流量', ' 80.000 GiB ']];
    expect(accountItems({ online: true, fields: [], items: portal })).toEqual(portal);
  });
  it('preserves units, wording and literal zero', () => {
    expect(accountItems({ online: true, fields: [], items: [['剩余流量', '0'], ['余额', ' 12 元 ']] })).toEqual([['剩余流量', '0'], ['余额', ' 12 元 ']]);
    expect(accountItems({ online: true, fields: [], items: [['剩余流量', ''], ['余额', ' ']] })).toEqual([['剩余流量', '门户未提供'], ['余额', '门户未提供']]);
    expect(accountItems(null)).toEqual([]);
  });
});

describe('config and explicit demo', () => {
  it('requires valid intervals and HTTPS host without embedded credentials', () => {
    const config = demoSnapshot().config;
    expect(validateConfig({ password: '' }, config)).toBeNull();
    expect(validateConfig({ retry_interval: 10, max_retry_interval: 2 }, config)).toBeTruthy();
    expect(validateConfig({ check_interval: 1.5 }, config)).toBeTruthy();
    expect(validateConfig({ base: 'http://example.test' }, config)).toBeTruthy();
    expect(validateConfig({ cas_host: 'https://user:secret@example.test' }, config)).toBeTruthy();
    expect(validateConfig({ password: '' }, { ...config, password_set: false })).toBeTruthy();
  });
  it('empty password preserves saved password without exposing it', async () => {
    const transport = createDemoTransport();
    await transport.request('save_config', { username: 'new-user', password: '' });
    const state = parseSnapshot(await transport.request('snapshot', {}));
    expect(state.config.password_set).toBe(true); expect(state.config).not.toHaveProperty('password');
  });
  it('a result is not a state; only an authoritative event changes connection', async () => {
    const transport = createDemoTransport('?scenario=offline'); const receive = vi.fn();
    const stop = await synchronizeSnapshots(transport, receive, vi.fn());
    const result = await transport.request('action', { name: 'login' });
    expect(result).not.toHaveProperty('status');
    expect(receive.mock.lastCall?.[0].status.online).toBe(true); stop();
  });
});

describe('read-only demo account queries', () => {
  it('publishes busy then error without converting an unknown connection to offline', async () => {
    vi.useFakeTimers();
    const transport = createDemoTransport('?scenario=unknown');
    const events: Snapshot[] = [];
    const stop = await synchronizeSnapshots(transport, (snapshot) => events.push(snapshot), vi.fn());
    await transport.request('action', { name: 'info' });
    expect(events.at(-1)?.busy).toBe(true);
    await expect(transport.request('action', { name: 'info' })).rejects.toThrow('当前任务');
    await vi.advanceTimersByTimeAsync(300);
    const snapshot = parseSnapshot(await transport.request('snapshot', {}));
    expect(snapshot.busy).toBe(false);
    expect(snapshot.status?.online).toBeNull();
    expect(snapshot.info).toBeNull();
    expect(snapshot.info_error).toBe('账户信息获取失败，请稍后重试');
    expect(snapshot.logs.at(-1)?.level).toBe('error');
    expect(snapshot.config).toEqual(demoSnapshot('?scenario=unknown').config);
    expect(snapshot.accounts).toEqual(demoSnapshot('?scenario=unknown').accounts);
    expect(snapshot.prefs).toEqual(demoSnapshot('?scenario=unknown').prefs);
    stop();
  });

  it('clears a previous account error only after successful read completion', async () => {
    vi.useFakeTimers();
    const transport = createDemoTransport('?scenario=info-error');
    const before = parseSnapshot(await transport.request('snapshot', {}));
    await transport.request('action', { name: 'info' });
    expect(parseSnapshot(await transport.request('snapshot', {})).info_error).toBe(before.info_error);
    await vi.advanceTimersByTimeAsync(300);
    const snapshot = parseSnapshot(await transport.request('snapshot', {}));
    expect(snapshot.info_error).toBe('');
    expect(snapshot.info?.online).toBe(true);
    expect(snapshot.status).toEqual(before.status);
  });

  it('returns a confirmed offline account response rather than unread data', async () => {
    vi.useFakeTimers();
    const transport = createDemoTransport('?scenario=offline');
    await transport.request('action', { name: 'info' });
    await vi.advanceTimersByTimeAsync(300);
    const snapshot = parseSnapshot(await transport.request('snapshot', {}));
    expect(snapshot.info).toEqual({ online: false, fields: [], items: [] });
    expect(snapshot.info_error).toBe('');
    expect(snapshot.status?.online).toBe(false);
  });
});

describe('diagnostics and bounded logs', () => {
  it('shows only local environment when diagnostics return a full snapshot', () => {
    const output = formatDiagnostics(demoSnapshot());
    expect(output).toContain('Rust 原生'); expect(output).toContain('原生 CDP');
    expect(output).not.toContain('Python'); expect(output).not.toContain('Node.js');
    expect(output).not.toContain('20260001'); expect(output).not.toContain('10.24.16.82');
  });
  it('keeps newly appended logs visible after clearing a rolling buffer', () => {
    const previous = demoSnapshot().logs;
    const added = { timestamp: '09:00:00', level: 'info' as const, message: 'new event' };
    const next = [...previous.slice(1), added];
    const floor = advanceLogFloor(previous, next, previous.length);
    expect(next.slice(floor)).toEqual([added]);
  });
  it('preserves clear boundary on unchanged snapshots and resets on replaced logs', () => {
    const logs = demoSnapshot().logs;
    expect(advanceLogFloor(logs, [...logs], 3)).toBe(3);
    expect(advanceLogFloor(logs, [], 3)).toBe(0);
  });
  it('formats ISO timestamps compactly while retaining raw or invalid values', () => {
    expect(formatLogTime('2026-10-14T06:00:00.000+00:00')).toMatch(/^\d{2}:\d{2}:\d{2}$/);
    expect(formatLogTime('08:42:03')).toBe('08:42:03');
    expect(formatLogTime('2026-99-99Tinvalid')).toBe('2026-99-99Tinvalid');
  });
});
