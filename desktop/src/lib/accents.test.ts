import { describe, expect, it } from 'vitest';
import { ACCENT_OPTIONS, normalizeAccent } from './accents';
import { createDemoTransport, demoSnapshot } from './demo';
import { parseSnapshot } from './protocol';
import type { CoreCommands } from './protocol';

describe('accent preferences', () => {
  it('keeps the default and six distinct named choices', () => {
    expect(ACCENT_OPTIONS.map((option) => option.value)).toEqual(['teal', 'blue', 'indigo', 'violet', 'rose', 'amber']);
    expect(new Set(ACCENT_OPTIONS.map((option) => option.label)).size).toBe(6);
    expect(demoSnapshot().prefs.accent).toBe('teal');
  });

  it.each(ACCENT_OPTIONS)('accepts $value through demo and public snapshots', ({ value }) => {
    expect(normalizeAccent(value)).toBe(value);
    expect(parseSnapshot(demoSnapshot(`?accent=${value}`)).prefs.accent).toBe(value);
  });

  it.each([undefined, null, false, 42, {}, [], 'future', 'BLUE', ' blue ', ''])('falls back without losing valid preferences: %j', (accent) => {
    const original = demoSnapshot('?theme=dark&scenario=no-auto');
    const prefs = { ...original.prefs, accent, close_to_tray: false };
    expect(parseSnapshot({ ...original, prefs }).prefs).toEqual({ theme: 'dark', accent: 'teal', close_to_tray: false, auto_reconnect: false });
    expect(prefs.accent).toBe(accent);
  });

  it('accepts an old snapshot with the field absent', () => {
    const original = demoSnapshot();
    const { accent: _accent, ...prefs } = original.prefs;
    expect(parseSnapshot({ ...original, prefs }).prefs.accent).toBe('teal');
  });

  it.each(ACCENT_OPTIONS)('saves $value without changing theme, connection or automation', async ({ value }) => {
    const transport = createDemoTransport('?theme=dark');
    const before = parseSnapshot(await transport.request('snapshot', {}));
    await transport.request('save_prefs', { accent: value });
    const after = parseSnapshot(await transport.request('snapshot', {}));
    expect(after.prefs).toEqual({ ...before.prefs, accent: value });
    expect(after.status).toEqual(before.status);
    expect(after.accounts).toEqual(before.accounts);
    expect(after.auto).toEqual(before.auto);
    await transport.request('save_prefs', { theme: 'light', close_to_tray: false });
    expect(parseSnapshot(await transport.request('snapshot', {})).prefs).toEqual({ ...after.prefs, theme: 'light', close_to_tray: false });
  });

  it('rejects an invalid accent before any partial preference update', async () => {
    const transport = createDemoTransport('?theme=light&accent=blue');
    const before = await transport.request('snapshot', {});
    await expect(transport.request('save_prefs', { theme: 'dark', accent: 'future' } as unknown as CoreCommands['save_prefs'])).rejects.toThrow('主题色');
    expect(await transport.request('snapshot', {})).toEqual(before);
  });

  it('does not publish or claim a preference after a failed save', async () => {
    const transport = createDemoTransport('?scenario=prefs-failure&accent=indigo');
    const before = await transport.request('snapshot', {});
    let events = 0;
    const stop = await transport.subscribe(() => { events += 1; });
    await expect(transport.request('save_prefs', { accent: 'rose' })).rejects.toThrow('原设置已保留');
    expect(await transport.request('snapshot', {})).toEqual(before);
    expect(events).toBe(0);
    stop();
  });

  it.each(['busy', 'external'])('keeps native-compatible local preference semantics in %s', async (scenario) => {
    const transport = createDemoTransport(`?scenario=${scenario}`);
    const before = parseSnapshot(await transport.request('snapshot', {}));
    await transport.request('save_prefs', { accent: 'amber' });
    const after = parseSnapshot(await transport.request('snapshot', {}));
    expect(after.prefs).toEqual({ ...before.prefs, accent: 'amber' });
    expect(after.busy).toBe(before.busy);
    expect(after.auto).toEqual(before.auto);
  });
});
