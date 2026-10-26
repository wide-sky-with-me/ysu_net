import { describe, expect, it } from 'vitest';
import { demoSnapshot } from './demo';
import { parseSnapshot } from './protocol';
import { confirmAutostart, confirmedPreferences, parseDesktopSettings, preferenceNotice, SETTING_UNCONFIRMED, settingBusyMessage, settingError } from './settings';
import type { Setting } from './settings';

describe('confirmed desktop settings', () => {
  it('whitelists desktop state and rejects malformed or missing capabilities', () => {
    const state = { autostart: false, tray_available: true, version: '0.2.1', demo: false, tray_tooltip: true };
    expect(parseDesktopSettings({ ...state, password: 'fixture-secret', path: '/private/fixture' })).toEqual(state);
    for (const value of [null, [], true, {}, { ...state, autostart: 1 }, { ...state, tray_available: 'true' }, { ...state, demo: 'false' }, { ...state, tray_tooltip: 1 }]) {
      expect(() => parseDesktopSettings(value)).toThrow(SETTING_UNCONFIRMED);
    }
  });
  it('a completed setter is not a matching OS readback', () => {
    const state = { autostart: false, tray_available: true, version: '0.2.1' };
    expect(() => confirmAutostart(state, true)).toThrow(SETTING_UNCONFIRMED);
    expect(() => confirmAutostart(state, false)).not.toThrow();
    expect(() => confirmAutostart({ ...state, autostart: true }, true)).not.toThrow();
  });
  it('requires explicit requested values in an authoritative snapshot', () => {
    const snapshot = demoSnapshot();
    for (const changes of [{ theme: 'light' as const }, { accent: 'teal' as const }, { close_to_tray: false }, { autostart_minimized: false }]) {
      const saved = { ...snapshot, prefs: { ...snapshot.prefs, ...changes } };
      expect(confirmedPreferences(saved, changes).prefs).toMatchObject(changes);
      expect(() => confirmedPreferences({ ok: true }, changes)).toThrow(SETTING_UNCONFIRMED);
      expect(() => confirmedPreferences({ ...saved, prefs: {} }, changes)).toThrow(SETTING_UNCONFIRMED);
    }
    expect(() => confirmedPreferences(snapshot, { close_to_tray: false })).toThrow(SETTING_UNCONFIRMED);
    expect(() => confirmedPreferences({ ...snapshot, prefs: { ...snapshot.prefs, accent: 'future' } }, { accent: 'blue' })).toThrow(SETTING_UNCONFIRMED);
    expect(() => confirmedPreferences({ ...snapshot, environment: {} }, { close_to_tray: true })).toThrow();
    expect(() => confirmedPreferences(snapshot, {})).toThrow(SETTING_UNCONFIRMED);
  });
  it('legacy display defaults never stand in for a newly confirmed mode write', () => {
    const data = demoSnapshot();
    const { autostart_minimized: _, ...legacyPrefs } = data.prefs;
    const legacy = { ...data, prefs: legacyPrefs };
    expect(parseSnapshot(legacy).prefs.autostart_minimized).toBe(true);
    expect(() => confirmedPreferences(legacy, { autostart_minimized: true })).toThrow(SETTING_UNCONFIRMED);
  });
  it('presentation strips credentials even when save confirmation is valid', () => {
    const data = demoSnapshot();
    const confirmed = confirmedPreferences({ ...data, config: { ...data.config, password: 'fixture-secret' } }, { autostart_minimized: true });
    expect(confirmed.config).not.toHaveProperty('password');
  });
});

describe('setting feedback', () => {
  it('names the confirmed choice without claiming a connection or logout', () => {
    expect(preferenceNotice({ autostart_minimized: true })).toBe('自启后将进入托盘');
    expect(preferenceNotice({ autostart_minimized: false })).toBe('自启后将显示窗口');
    expect(preferenceNotice({ close_to_tray: true })).toBe('关闭窗口后保留托盘');
    expect(preferenceNotice({ close_to_tray: false })).toBe('关闭窗口后退出应用');
    expect(preferenceNotice({ theme: 'dark' })).toBe('界面主题已保存');
    expect(preferenceNotice({ accent: 'teal' })).toBe('主题色已保存');
  });
  it('never displays arbitrary native errors, paths, credentials or rejected values', () => {
    for (const kind of Object.keys(settingBusyMessage) as Setting[]) {
      const fixed = settingError(kind, null);
      for (const error of ['/private/path?token=fixture-secret', new Error('C:\\private\\fixture-secret'), { message: 'fixture-secret' }, 17, undefined]) {
        expect(settingError(kind, error)).toBe(fixed);
        expect(settingError(kind, error)).not.toMatch(/private|token|fixture-secret/);
      }
      expect(settingError(kind, new Error(SETTING_UNCONFIRMED))).toBe(SETTING_UNCONFIRMED);
    }
  });
});
