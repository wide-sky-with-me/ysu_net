import { describe, expect, it } from 'vitest';
import accentCss from '../accents.css?raw';
import baseCss from '../app.css?raw';
import { ACCENT_OPTIONS, DEFAULT_ACCENT, normalizeAccent } from './accents';
import { createDemoTransport, demoSnapshot } from './demo';
import { parseSnapshot } from './protocol';
import type { CoreCommands } from './protocol';

describe('accent preferences', () => {
  it('keeps the default and six distinct named choices', () => {
    expect(DEFAULT_ACCENT).toBe('blue');
    expect(ACCENT_OPTIONS.map((option) => option.value)).toEqual(['blue', 'teal', 'indigo', 'violet', 'rose', 'amber']);
    expect(new Set(ACCENT_OPTIONS.map((option) => option.label)).size).toBe(6);
    expect(demoSnapshot().prefs.accent).toBe('blue');
  });

  it.each(ACCENT_OPTIONS)('accepts $value through demo and public snapshots', ({ value }) => {
    expect(normalizeAccent(value)).toBe(value);
    expect(parseSnapshot(demoSnapshot(`?accent=${value}`)).prefs.accent).toBe(value);
  });

  it.each([undefined, null, false, 42, {}, [], 'future', 'BLUE', ' blue ', ''])('falls back without losing valid preferences: %j', (accent) => {
    const original = demoSnapshot('?theme=dark&scenario=no-auto');
    const prefs = { ...original.prefs, accent, close_to_tray: false };
    expect(parseSnapshot({ ...original, prefs }).prefs).toEqual({ theme: 'dark', accent: 'blue', close_to_tray: false, auto_reconnect: false });
    expect(prefs.accent).toBe(accent);
  });

  it('accepts an old snapshot with the field absent', () => {
    const original = demoSnapshot();
    const { accent: _accent, ...prefs } = original.prefs;
    expect(parseSnapshot({ ...original, prefs }).prefs.accent).toBe('blue');
  });

  it('preserves an explicitly selected teal accent after changing unrelated preferences', async () => {
    const transport = createDemoTransport('?accent=teal&theme=dark');
    await transport.request('save_prefs', { close_to_tray: false });
    expect(parseSnapshot(await transport.request('snapshot', {})).prefs).toEqual({
      theme: 'dark', accent: 'teal', close_to_tray: false, auto_reconnect: true,
    });
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

const declarations = (body: string) => Object.fromEntries([...body.matchAll(/--([\w-]+)\s*:\s*([^;]+);/g)].map((match) => [match[1], match[2].trim()]));
const accentRule = (value: string, dark: boolean) => {
  const selector = `:root[data-accent='${value}']${dark ? "[data-theme='dark']" : ''}`;
  const body = accentCss.slice(accentCss.indexOf(selector) + selector.length).match(/^\s*\{([^}]+)\}/)?.[1];
  expect(body, selector).toBeDefined();
  return declarations(body!);
};

describe('neutral theme palette contract', () => {
  it.each(ACCENT_OPTIONS)('$value changes highlights only and matches the picker swatches', ({ value, light, dark }) => {
    for (const isDark of [false, true]) {
      const rule = accentRule(value, isDark);
      expect(Object.keys(rule).sort()).toEqual(['accent', 'accent-hover', 'accent-soft']);
      expect(rule.accent).toBe(isDark ? dark : light);
    }
  });

  it('keeps the fallback blue palette aligned with the explicit default', () => {
    const light = declarations(baseCss.match(/:root\s*\{([^}]+)\}/)![1]);
    const dark = declarations(baseCss.match(/:root\[data-theme='dark'\]\s*\{([^}]+)\}/)![1]);
    expect(light.canvas).toBe('#f5f6f8');
    expect(dark.canvas).toBe('#151618');
    expect(dark.surface).toBe('#212225');
    for (const name of ['accent', 'accent-hover', 'accent-soft']) {
      expect(light[name]).toBe(accentRule(DEFAULT_ACCENT, false)[name]);
      expect(dark[name]).toBe(accentRule(DEFAULT_ACCENT, true)[name]);
    }
    expect(light['focus-outline']).toBe('var(--accent)');
    expect(dark['on-accent']).toBe('#171b22');
  });
});
